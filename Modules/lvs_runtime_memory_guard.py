#!/usr/bin/env python3
"""One stage-wide runtime MemAvailable safety guard and worker claim file."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable


MIB = 1024 ** 2


def runtime_memory_thresholds(reserve_bytes: int) -> Dict[str, int]:
    reserve = max(0, int(reserve_bytes or 0))
    return {
        "warning_mem_available_bytes": reserve,
        "emergency_mem_available_bytes": min(reserve, max(4 * MIB, reserve // 2)),
        "warning_consecutive_samples": 2,
        "emergency_consecutive_samples": 3,
    }


def runtime_guard_required(plan: Dict[str, Any]) -> bool:
    return bool(plan.get("consumers") or plan.get("unbudgeted_shared_gpu_workers"))


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _locked_update(path: Path, callback: Any) -> Dict[str, Any]:
    lock_path = Path(str(path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                current = {}
            updated = callback(current)
            _write_json_atomic(path, updated)
            return updated
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def initialize_runtime_memory_guard(plan: Dict[str, Any], control_path: Path | str) -> Dict[str, Any]:
    path = Path(control_path)
    reserve = max(0, int(plan.get("system_memory_safety_reserve_bytes") or 0))
    launch_available = max(0, int(plan.get("system_memory_available_bytes") or 0))
    thresholds = runtime_memory_thresholds(reserve)
    state: Dict[str, Any] = {
        "enabled": runtime_guard_required(plan),
        "control_path": str(path),
        "mem_total_bytes": max(0, int(plan.get("system_memory_total_bytes") or 0)),
        "launch_mem_available_bytes": launch_available,
        "system_memory_reserve_bytes": reserve,
        "launch_system_memory_pool_bytes": max(0, int(plan.get("system_memory_budget_bytes") or 0)),
        "runtime_mem_available_bytes": launch_available,
        "minimum_runtime_mem_available_bytes": launch_available,
        "runtime_headroom_bytes": max(0, launch_available - reserve),
        "runtime_growth_allowance_bytes": max(0, launch_available - reserve),
        "runtime_memory_warning_triggered": False,
        "runtime_memory_guard_triggered": False,
        "guard_trigger_timestamp": "",
        "headroom_at_trigger_bytes": None,
        "affected_workers": [],
        "allocation_growth_stopped": False,
        "stage_termination_required": False,
        "warning_consecutive_count": 0,
        "emergency_consecutive_count": 0,
        **thresholds,
    }
    _write_json_atomic(path, state)
    plan["runtime_memory_guard"] = state
    return state


def refresh_runtime_memory_guard(plan: Dict[str, Any]) -> Dict[str, Any]:
    prior = dict(plan.get("runtime_memory_guard") or {})
    raw_path = str(prior.get("control_path") or "")
    if not raw_path:
        return prior
    try:
        state = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    except Exception:
        return prior
    plan["runtime_memory_guard"] = state
    return state


def update_runtime_memory_guard(
    plan: Dict[str, Any],
    *,
    runtime_mem_available_bytes: int,
    timestamp: str,
    affected_workers: Iterable[str] = (),
) -> Dict[str, Any]:
    prior = dict(plan.get("runtime_memory_guard") or {})
    if not prior.get("enabled"):
        return prior
    path = Path(str(prior.get("control_path") or ""))
    if not str(path):
        return prior
    available = max(0, int(runtime_mem_available_bytes or 0))

    def apply(current: Dict[str, Any]) -> Dict[str, Any]:
        state = {**prior, **current}
        warning_threshold = max(0, int(state.get("warning_mem_available_bytes") or 0))
        emergency_threshold = max(0, int(state.get("emergency_mem_available_bytes") or 0))
        warning_count = int(state.get("warning_consecutive_count") or 0)
        emergency_count = int(state.get("emergency_consecutive_count") or 0)
        warning_count = warning_count + 1 if available < warning_threshold else 0
        emergency_count = emergency_count + 1 if available < emergency_threshold else 0
        warning_triggered = bool(state.get("runtime_memory_warning_triggered")) or warning_count >= int(
            state.get("warning_consecutive_samples") or 2
        )
        guard_triggered = bool(state.get("runtime_memory_guard_triggered")) or emergency_count >= int(
            state.get("emergency_consecutive_samples") or 3
        )
        reserve = max(0, int(state.get("system_memory_reserve_bytes") or 0))
        workers = sorted(set(str(item) for item in affected_workers if str(item)))
        trigger_now = guard_triggered and not bool(state.get("runtime_memory_guard_triggered"))
        state.update(
            {
                "runtime_mem_available_bytes": available,
                "minimum_runtime_mem_available_bytes": min(
                    max(0, int(state.get("minimum_runtime_mem_available_bytes") or available)), available
                ),
                "runtime_headroom_bytes": max(0, available - reserve),
                "runtime_growth_allowance_bytes": max(0, available - reserve),
                "warning_consecutive_count": warning_count,
                "emergency_consecutive_count": emergency_count,
                "runtime_memory_warning_triggered": warning_triggered,
                "runtime_memory_guard_triggered": guard_triggered,
                "allocation_growth_stopped": available < reserve or bool(state.get("allocation_growth_stopped")),
                "stage_termination_required": guard_triggered,
                "affected_workers": sorted(set(state.get("affected_workers") or []).union(workers)),
            }
        )
        if trigger_now:
            state["guard_trigger_timestamp"] = timestamp
            state["headroom_at_trigger_bytes"] = max(0, available - reserve)
        return state

    state = _locked_update(path, apply)
    plan["runtime_memory_guard"] = state
    return state


def claim_runtime_allocation_growth(
    request_bytes: int,
    *,
    shared_system_memory: bool,
    control_path: str | None = None,
) -> Dict[str, Any]:
    request = max(0, int(request_bytes or 0))
    if not shared_system_memory or request <= 0:
        return {"allowed": True, "claimed_bytes": request, "reason": "not_shared_system_memory"}
    raw_path = control_path or os.environ.get("LVS_RUNTIME_MEMORY_GUARD_PATH", "")
    if not raw_path:
        return {"allowed": True, "claimed_bytes": request, "reason": "guard_not_configured"}
    path = Path(raw_path)

    def apply(state: Dict[str, Any]) -> Dict[str, Any]:
        allowance = max(0, int(state.get("runtime_growth_allowance_bytes") or 0))
        allowed = bool(state.get("enabled")) and not bool(state.get("stage_termination_required")) and allowance >= request
        state["last_claim_requested_bytes"] = request
        state["last_claim_allowed"] = allowed
        if allowed:
            state["runtime_growth_allowance_bytes"] = allowance - request
            state["total_runtime_growth_claimed_bytes"] = int(state.get("total_runtime_growth_claimed_bytes") or 0) + request
        else:
            state["allocation_growth_stopped"] = True
            state["last_claim_denial_reason"] = "runtime_memory_guard"
        return state

    state = _locked_update(path, apply)
    allowed = bool(state.get("last_claim_allowed"))
    return {
        "allowed": allowed,
        "claimed_bytes": request if allowed else 0,
        "reason": "allowed" if allowed else "runtime_memory_guard",
        "runtime_mem_available_bytes": int(state.get("runtime_mem_available_bytes") or 0),
        "runtime_headroom_bytes": int(state.get("runtime_headroom_bytes") or 0),
    }


def release_runtime_allocation_claim(
    claimed_bytes: int,
    *,
    shared_system_memory: bool,
    control_path: str | None = None,
) -> None:
    amount = max(0, int(claimed_bytes or 0))
    if not shared_system_memory or amount <= 0:
        return
    raw_path = control_path or os.environ.get("LVS_RUNTIME_MEMORY_GUARD_PATH", "")
    if not raw_path:
        return
    path = Path(raw_path)

    def apply(state: Dict[str, Any]) -> Dict[str, Any]:
        state["runtime_growth_allowance_bytes"] = int(state.get("runtime_growth_allowance_bytes") or 0) + amount
        state["total_runtime_growth_claimed_bytes"] = max(
            0, int(state.get("total_runtime_growth_claimed_bytes") or 0) - amount
        )
        return state

    _locked_update(path, apply)
