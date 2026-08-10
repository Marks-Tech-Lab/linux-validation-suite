#!/usr/bin/env python3
"""Portable supervised Python CPU fallback worker."""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


PYTHON_CPU_FALLBACK_BACKEND = "python_fallback"
SUPERVISION_INTERVAL_SECONDS = 0.2
WORKER_STARTUP_TIMEOUT_SECONDS = 10.0


def python_cpu_workload(
    worker_index: int,
    algorithm: str,
    iterations: int,
    payload_bytes: int,
    ready_event: Any,
) -> None:
    """Run one CPU fallback workload; this top-level target is spawn/forkserver importable."""
    try:
        if hasattr(os, "sched_setaffinity"):
            cpu_total = max(1, os.cpu_count() or 1)
            os.sched_setaffinity(0, {worker_index % cpu_total})
    except Exception:
        pass

    seed = bytearray(payload_bytes)
    for index in range(payload_bytes):
        seed[index] = (index + worker_index) & 0xFF
    ready_event.set()
    salt_counter = worker_index + 1
    while True:
        salt = salt_counter.to_bytes(16, "little", signed=False)
        digest = hashlib.pbkdf2_hmac(algorithm, seed, salt, iterations, dklen=64)
        seed[:64] = digest
        salt_counter += 1


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
    process_factory: Callable[..., Any] = mp.Process,
    event_factory: Callable[[], Any] = mp.Event,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    requested_count = max(1, int(worker_count))
    processes: List[Any] = []
    ready_events: List[Any] = []
    startup_errors: List[str] = []
    unexpected_exits: List[Dict[str, Any]] = []

    for worker_index in range(requested_count):
        if stop_requested():
            break
        try:
            ready_event = event_factory()
            process = process_factory(
                target=python_cpu_workload,
                args=(worker_index, algorithm, iterations, payload_bytes, ready_event),
                daemon=True,
            )
            process.start()
            processes.append(process)
            ready_events.append(ready_event)
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

    payload: Dict[str, Any] = {
        "kind": "cpu",
        "backend": PYTHON_CPU_FALLBACK_BACKEND,
        "status": status,
        "error_count": error_count,
        "last_error": errors[-1] if errors else "",
        "errors": errors,
        "requested_worker_count": requested_count,
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
        stop_requested=lambda: stopping,
    )


if __name__ == "__main__":
    raise SystemExit(main())
