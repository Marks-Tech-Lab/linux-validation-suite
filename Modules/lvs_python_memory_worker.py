#!/usr/bin/env python3
"""Python system-memory fallback with exact incremental allocation evidence."""

from __future__ import annotations

import json
import os
import signal
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from Modules.lvs_gpu_allocation_plan import allocation_attainment


MIB = 1024 ** 2
DEFAULT_CHUNK_BYTES = 256 * MIB


class WorkerStop(Exception):
    pass


def initial_python_memory_state(target_bytes: int) -> Dict[str, Any]:
    target = max(0, int(target_bytes or 0))
    return {
        "kind": "memory",
        "backend": "python_fallback",
        "status": "initializing",
        "error_count": 0,
        "assigned_target_bytes": target,
        "planned_target_bytes": target,
        "successfully_allocated_bytes": 0,
        "successful_chunk_count": 0,
        "attempted_chunk_count": 0,
        "allocation_failure_count": 0,
        "final_attempted_chunk_bytes": 0,
        "memory_error_occurred": False,
        "allocation_shortfall_bytes": target,
        "allocation_ratio": 0.0,
        "allocation_outcome": "not_started",
        "allocation_valid": False,
        "allocation_verified": False,
        "verification_passes": 0,
        "verification_failures": 0,
        "verified_bytes_per_pass": 0,
        "current_pattern": 1,
        "target_cap_reason": "",
        "runtime_memory_guard_triggered": False,
        "allocation_growth_stopped": False,
        "runtime_memory_guard_details": {},
    }


def update_python_memory_attainment(state: Dict[str, Any]) -> None:
    target = max(0, int(state.get("assigned_target_bytes") or 0))
    achieved = max(0, int(state.get("successfully_allocated_bytes") or 0))
    attainment = allocation_attainment(assigned_target_bytes=target, achieved_bytes=achieved)
    state.update(attainment)
    state["allocation_shortfall_bytes"] = max(0, target - achieved)
    if target > 0 and achieved >= target:
        state["status"] = "ok"
        state["error_count"] = 0
        state["target_cap_reason"] = "assigned_target_achieved"
        state["last_error"] = ""
    elif bool(attainment.get("allocation_valid")):
        state["status"] = "ok"
        state["error_count"] = 0
        state["target_cap_reason"] = "python_memory_error" if state.get("memory_error_occurred") else "partial_allocation"
        state["last_error"] = ""
    else:
        state["status"] = "error"
        state["error_count"] = 1
        state["target_cap_reason"] = "python_memory_error" if state.get("memory_error_occurred") else "allocation_failed"
        state["last_error"] = "Python memory fallback did not achieve the minimum meaningful allocation"


def write_python_memory_result(path: str, state: Dict[str, Any]) -> None:
    if not path:
        return
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=destination.name + ".", dir=str(destination.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def allocate_python_memory_chunks(
    state: Dict[str, Any],
    retained_chunks: List[Any],
    *,
    allocator: Callable[[int], Any] = bytearray,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
    touch_pages: bool = True,
    progress_callback: Callable[[Dict[str, Any]], None] = lambda _state: None,
) -> None:
    target = max(0, int(state.get("assigned_target_bytes") or 0))
    achieved = max(0, int(state.get("successfully_allocated_bytes") or 0))
    chunk_limit = max(1, int(chunk_bytes or 0))
    while achieved < target:
        request = min(chunk_limit, target - achieved)
        state["attempted_chunk_count"] = int(state.get("attempted_chunk_count") or 0) + 1
        state["final_attempted_chunk_bytes"] = request
        try:
            block = allocator(request)
        except MemoryError:
            state["memory_error_occurred"] = True
            state["allocation_failure_count"] = int(state.get("allocation_failure_count") or 0) + 1
            update_python_memory_attainment(state)
            progress_callback(state)
            return
        if touch_pages:
            for index in range(0, request, 4096):
                block[index] = 1
        retained_chunks.append(block)
        achieved += request
        state["successfully_allocated_bytes"] = achieved
        state["successful_chunk_count"] = int(state.get("successful_chunk_count") or 0) + 1
        update_python_memory_attainment(state)
        # Durably record every retained success before attempting more memory.
        progress_callback(state)
    update_python_memory_attainment(state)


def apply_runtime_guard_precedence(state: Dict[str, Any]) -> None:
    guard_path = os.environ.get("LVS_RUNTIME_MEMORY_GUARD_PATH", "")
    if not guard_path:
        return
    try:
        guard = json.loads(Path(guard_path).read_text(encoding="utf-8"))
    except Exception:
        return
    if not guard.get("runtime_memory_guard_triggered"):
        return
    state["runtime_memory_guard_triggered"] = True
    state["allocation_growth_stopped"] = True
    state["runtime_memory_guard_details"] = guard
    state["target_cap_reason"] = "runtime_memory_guard"


def verify_python_memory_chunks(
    state: Dict[str, Any],
    retained_chunks: List[Any],
    *,
    progress_callback: Callable[[Dict[str, Any]], None] = lambda _state: None,
) -> None:
    # Zero is a valid byte pattern in the rewrite sequence.  Truthiness would
    # turn an expected 0 back into 1 and create a deterministic false mismatch.
    current_pattern = state.get("current_pattern", 1)
    expected = int(1 if current_pattern is None else current_pattern) & 0xFF
    next_pattern = (expected * 33 + 17) & 0xFF
    if next_pattern == expected:
        next_pattern ^= 0xFF
    verified_bytes = 0
    for chunk_index, block in enumerate(retained_chunks):
        for offset in range(0, len(block), 4096):
            actual = int(block[offset])
            if actual != expected:
                state["verification_failures"] = int(state.get("verification_failures") or 0) + 1
                state["error_count"] = int(state.get("error_count") or 0) + 1
                state["status"] = "error"
                state.setdefault(
                    "first_verification_error",
                    {
                        "chunk_index": chunk_index,
                        "offset": offset,
                        "expected": expected,
                        "actual": actual,
                    },
                )
            block[offset] = next_pattern
            verified_bytes += min(4096, len(block) - offset)
        state["verification_chunks_completed"] = chunk_index + 1
        progress_callback(state)
    state["verified_bytes_per_pass"] = verified_bytes
    state["current_pattern"] = next_pattern
    state["verification_passes"] = int(state.get("verification_passes") or 0) + 1
    state["allocation_verified"] = bool(state.get("allocation_valid")) and int(state.get("verification_failures") or 0) == 0
    if state["allocation_verified"]:
        state["status"] = "ok"
    progress_callback(state)


def run_python_memory_worker(target_bytes: int, result_file: str = "") -> int:
    state = initial_python_memory_state(target_bytes)
    retained_chunks: List[Any] = []

    def write_progress(current: Dict[str, Any]) -> None:
        write_python_memory_result(result_file, current)

    def stop(*_args: Any) -> None:
        raise WorkerStop()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    write_progress(state)
    try:
        allocate_python_memory_chunks(state, retained_chunks, progress_callback=write_progress)
        if not state.get("allocation_valid"):
            return 12
        while True:
            verify_python_memory_chunks(state, retained_chunks, progress_callback=write_progress)
            if int(state.get("verification_failures") or 0) > 0:
                return 13
    except WorkerStop:
        if not state.get("allocation_valid"):
            return 12
        if int(state.get("verification_failures") or 0) > 0:
            return 13
        if int(state.get("verification_passes") or 0) <= 0:
            state["status"] = "error"
            state["error_count"] = int(state.get("error_count") or 0) + 1
            state["last_error"] = "Python memory fallback ended before completing a retained-memory verification pass"
            return 14
        return 0
    finally:
        apply_runtime_guard_precedence(state)
        write_progress(state)


def python_memory_fallback_script(target_bytes: int, result_file: str = "") -> str:
    return "\n".join(
        [
            "from Modules.lvs_python_memory_worker import run_python_memory_worker",
            f"raise SystemExit(run_python_memory_worker({max(0, int(target_bytes or 0))}, {str(result_file)!r}))",
        ]
    )
