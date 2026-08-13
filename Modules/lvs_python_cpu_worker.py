#!/usr/bin/env python3
"""Portable supervised Python CPU fallback worker."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import multiprocessing as mp
import os
import queue
import signal
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from Modules.lvs_cpu_targeting import discover_linux_cpu_sets, parse_linux_cpu_list


PYTHON_CPU_FALLBACK_BACKEND = "python_fallback"
SUPERVISION_INTERVAL_SECONDS = 0.2
WORKER_STARTUP_TIMEOUT_SECONDS = 30.0


def apply_python_cpu_affinity(
    worker_index: int,
    target_cpu_id: int,
    *,
    affinity_setter: Optional[Callable[[int, set[int]], None]] = None,
    affinity_getter: Optional[Callable[[int], Any]] = None,
    affinity_available: Optional[bool] = None,
) -> Dict[str, Any]:
    setter = (
        None
        if affinity_available is False
        else affinity_setter if affinity_setter is not None else getattr(os, "sched_setaffinity", None)
    )
    getter = affinity_getter if affinity_getter is not None else getattr(os, "sched_getaffinity", None)
    evidence: Dict[str, Any] = {
        "worker_index": worker_index,
        "affinity_requested": True,
        "affinity_target_cpu": int(target_cpu_id),
        "affinity_applied": False,
        "affinity_status": "unavailable",
        "affinity_error": "",
        "observed_allowed_cpu_ids": [],
    }
    if setter is None:
        return evidence
    try:
        setter(0, {int(target_cpu_id)})
        evidence["affinity_applied"] = True
        evidence["affinity_status"] = "applied"
        if getter is not None:
            evidence["observed_allowed_cpu_ids"] = sorted(getter(0))
    except Exception as exc:
        evidence["affinity_status"] = "failed"
        evidence["affinity_error"] = f"{type(exc).__name__}: {exc}"
    return evidence


def python_cpu_workload(
    worker_index: int,
    algorithm: str,
    iterations: int,
    payload_bytes: int,
    target_cpu_id: int,
    ready_event: Any,
    evidence_queue: Any,
    progress_counter: Any,
    verification_counter: Any,
    verification_error_counter: Any,
) -> None:
    """Run one CPU fallback workload; this top-level target is spawn/forkserver importable."""
    affinity = apply_python_cpu_affinity(worker_index, target_cpu_id)
    try:
        evidence_queue.put(affinity)
    except Exception:
        pass
    # Readiness means the child process and its affinity attempt completed. It
    # deliberately precedes payload initialization so weak CPUs do not trip a
    # modern-speed startup deadline.
    ready_event.set()

    seed = bytearray(payload_bytes)
    for index in range(payload_bytes):
        seed[index] = (index + worker_index) & 0xFF
    salt_counter = worker_index + 1
    while True:
        salt = salt_counter.to_bytes(16, "little", signed=False)
        workload_input = bytes(seed)
        digest = hashlib.pbkdf2_hmac(algorithm, workload_input, salt, iterations, dklen=64)
        verification = hashlib.pbkdf2_hmac(algorithm, workload_input, salt, iterations, dklen=64)
        if not hmac.compare_digest(digest, verification):
            try:
                verification_error_counter.value += 1
            except Exception:
                pass
            raise RuntimeError("Python CPU fallback PBKDF2 verification mismatch")
        seed[:64] = digest
        salt_counter += 1
        try:
            progress_counter.value += 1
            verification_counter.value += 1
        except Exception:
            pass


def _child_exit_information(processes: List[Any], expected_termination: bool) -> List[Dict[str, Any]]:
    return [
        {
            "worker_index": worker_index,
            "pid": getattr(process, "pid", None),
            "exit_code": getattr(process, "exitcode", None),
            "expected_termination": bool(expected_termination),
        }
        for worker_index, process in enumerate(processes)
    ]


def _stop_children(processes: List[Any]) -> None:
    for process in processes:
        try:
            if process.is_alive():
                process.terminate()
        except Exception:
            pass
    for process in processes:
        try:
            process.join(timeout=1)
        except Exception:
            pass


def write_worker_result(path: str, payload: Dict[str, Any]) -> None:
    if not path:
        return
    result_path = Path(path)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def supervise_python_cpu_workers(
    *,
    worker_count: int,
    algorithm: str,
    iterations: int,
    payload_bytes: int,
    resolved_mode: str,
    result_file: str,
    stop_requested: Callable[[], bool],
    target_cpu_ids: Optional[List[int]] = None,
    process_factory: Callable[..., Any] = mp.Process,
    event_factory: Callable[[], Any] = mp.Event,
    queue_factory: Callable[[], Any] = mp.Queue,
    value_factory: Callable[..., Any] = mp.Value,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    requested_count = max(1, int(worker_count))
    target_ids = [int(cpu_id) for cpu_id in (target_cpu_ids or [])]
    if len(target_ids) < requested_count:
        discovered = list(discover_linux_cpu_sets().get("executable_cpu_ids") or [])
        target_ids = discovered[:requested_count]
    if len(target_ids) < requested_count:
        target_ids.extend([-1] * (requested_count - len(target_ids)))
    processes: List[Any] = []
    ready_events: List[Any] = []
    startup_errors: List[str] = []
    unexpected_exits: List[Dict[str, Any]] = []
    affinity_queue = queue_factory()
    progress_counters: List[Any] = []
    verification_counters: List[Any] = []
    verification_error_counters: List[Any] = []

    for worker_index in range(requested_count):
        if stop_requested():
            break
        try:
            ready_event = event_factory()
            progress_counter = value_factory("Q", 0, lock=False)
            verification_counter = value_factory("Q", 0, lock=False)
            verification_error_counter = value_factory("Q", 0, lock=False)
            process = process_factory(
                target=python_cpu_workload,
                args=(
                    worker_index,
                    algorithm,
                    iterations,
                    payload_bytes,
                    target_ids[worker_index],
                    ready_event,
                    affinity_queue,
                    progress_counter,
                    verification_counter,
                    verification_error_counter,
                ),
                daemon=True,
            )
            process.start()
            processes.append(process)
            ready_events.append(ready_event)
            progress_counters.append(progress_counter)
            verification_counters.append(verification_counter)
            verification_error_counters.append(verification_error_counter)
        except Exception as exc:
            startup_errors.append(f"worker {worker_index} failed to start: {exc}")
            break

    if not startup_errors and len(processes) != requested_count and not stop_requested():
        startup_errors.append(f"started {len(processes)} of {requested_count} requested workers")

    startup_deadline = monotonic() + WORKER_STARTUP_TIMEOUT_SECONDS
    while not startup_errors and not stop_requested() and not all(event.is_set() for event in ready_events):
        unexpected_exits = [
            {
                "worker_index": worker_index,
                "pid": getattr(process, "pid", None),
                "exit_code": getattr(process, "exitcode", None),
            }
            for worker_index, process in enumerate(processes)
            if getattr(process, "exitcode", None) is not None
        ]
        if unexpected_exits:
            break
        if monotonic() >= startup_deadline:
            missing = [index for index, event in enumerate(ready_events) if not event.is_set()]
            startup_errors.append(f"workers did not become ready before timeout: {missing}")
            break
        sleep(SUPERVISION_INTERVAL_SECONDS)

    while not startup_errors and not unexpected_exits and not stop_requested():
        unexpected_exits = [
            {
                "worker_index": worker_index,
                "pid": getattr(process, "pid", None),
                "exit_code": getattr(process, "exitcode", None),
            }
            for worker_index, process in enumerate(processes)
            if getattr(process, "exitcode", None) is not None
        ]
        if unexpected_exits:
            break
        sleep(SUPERVISION_INTERVAL_SECONDS)

    if not startup_errors and not unexpected_exits:
        unexpected_exits = [
            {
                "worker_index": worker_index,
                "pid": getattr(process, "pid", None),
                "exit_code": getattr(process, "exitcode", None),
            }
            for worker_index, process in enumerate(processes)
            if getattr(process, "exitcode", None) is not None
        ]
    ready_count = sum(1 for event in ready_events if event.is_set())
    expected_stop = bool(stop_requested()) and not startup_errors and not unexpected_exits
    healthy_before_shutdown = sum(
        1 for process in processes if getattr(process, "exitcode", None) is None
    )
    _stop_children(processes)

    affinity_evidence: List[Dict[str, Any]] = []
    while True:
        try:
            item = affinity_queue.get_nowait()
        except queue.Empty:
            break
        except Exception:
            break
        if isinstance(item, dict):
            affinity_evidence.append(item)
    affinity_evidence.sort(key=lambda item: int(item.get("worker_index") or 0))

    failed_worker_count = max(
        len(startup_errors) + len(unexpected_exits),
        requested_count - ready_count,
    )
    if not expected_stop and failed_worker_count == 0:
        failed_worker_count = max(1, requested_count - healthy_before_shutdown)
    status = "ok" if expected_stop and ready_count == requested_count and healthy_before_shutdown == requested_count else "error"
    error_count = 0 if status == "ok" else max(1, failed_worker_count)
    errors = list(startup_errors)
    errors.extend(
        f"worker {entry['worker_index']} pid={entry['pid']} exited unexpectedly with code {entry['exit_code']}"
        for entry in unexpected_exits
    )
    if status == "error" and not errors:
        errors.append("Python CPU fallback stopped without all requested workers remaining healthy")
    verification_passes = sum(int(getattr(counter, "value", 0) or 0) for counter in verification_counters)
    verification_errors = sum(int(getattr(counter, "value", 0) or 0) for counter in verification_error_counters)
    if status == "ok" and (verification_passes <= 0 or verification_errors > 0):
        status = "error"
        error_count = max(1, verification_errors)
        failed_worker_count = max(1, failed_worker_count)
        errors.append(
            "Python CPU fallback did not complete clean PBKDF2 verification"
            if verification_errors <= 0
            else f"Python CPU fallback reported {verification_errors} PBKDF2 verification mismatch(es)"
        )

    payload: Dict[str, Any] = {
        "kind": "cpu",
        "backend": PYTHON_CPU_FALLBACK_BACKEND,
        "status": status,
        "error_count": error_count,
        "last_error": errors[-1] if errors else "",
        "errors": errors,
        "requested_worker_count": requested_count,
        "requested_thread_count": requested_count,
        "target_cpu_ids": target_ids[:requested_count],
        "actual_worker_count": len(processes),
        "launched_worker_count": len(processes),
        "started_worker_count": ready_count,
        "healthy_worker_count": healthy_before_shutdown,
        "completed_worker_count": requested_count if status == "ok" else 0,
        "failed_worker_count": failed_worker_count,
        "worker_pids": [getattr(process, "pid", None) for process in processes],
        "child_exit_information": _child_exit_information(processes, expected_stop),
        "resolved_mode": resolved_mode,
        "algorithm": algorithm,
        "iterations": iterations,
        "payload_bytes": payload_bytes,
        "supervisor_pid": os.getpid(),
        "multiprocessing_start_method": mp.get_start_method(),
        "termination_reason": "expected_stop" if expected_stop else "worker_failure",
        "affinity_requested": True,
        "affinity_applied_count": sum(1 for item in affinity_evidence if item.get("affinity_applied")),
        "affinity_failed_count": sum(1 for item in affinity_evidence if item.get("affinity_status") == "failed"),
        "affinity_unavailable_count": sum(1 for item in affinity_evidence if item.get("affinity_status") == "unavailable"),
        "affinity_evidence": affinity_evidence,
        "worker_progress": [
            {
                "worker_index": index,
                "target_cpu_id": target_ids[index],
                "completed_pbkdf2_iterations": int(getattr(counter, "value", 0) or 0),
                "verification_passes": int(getattr(verification_counters[index], "value", 0) or 0),
                "verification_errors": int(getattr(verification_error_counters[index], "value", 0) or 0),
            }
            for index, counter in enumerate(progress_counters)
        ],
        "verification_passes": verification_passes,
        "verification_error_count": verification_errors,
        "verification_method": "duplicate_pbkdf2_compare_digest",
        "capability_scope": "generic_approximate_workload_no_isa_enforcement",
    }
    try:
        write_worker_result(result_file, payload)
    except Exception as exc:
        print(f"failed to write Python CPU fallback result: {exc}", file=sys.stderr, flush=True)
        return 1
    if errors:
        for error in errors:
            print(error, file=sys.stderr, flush=True)
    return 0 if status == "ok" else 1


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LVS portable Python CPU fallback")
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--algorithm", required=True)
    parser.add_argument("--iterations", type=int, required=True)
    parser.add_argument("--payload-bytes", type=int, required=True)
    parser.add_argument("--resolved-mode", default="")
    parser.add_argument("--cpu-ids", default="")
    parser.add_argument("--result-file", default="")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _argument_parser().parse_args(argv)
    stopping = False

    def request_stop(*_: Any) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    return supervise_python_cpu_workers(
        worker_count=args.workers,
        algorithm=args.algorithm,
        iterations=args.iterations,
        payload_bytes=args.payload_bytes,
        resolved_mode=args.resolved_mode,
        result_file=args.result_file,
        target_cpu_ids=parse_linux_cpu_list(args.cpu_ids),
        stop_requested=lambda: stopping,
    )


if __name__ == "__main__":
    raise SystemExit(main())
