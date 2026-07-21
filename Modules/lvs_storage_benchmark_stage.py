#!/usr/bin/env python3
"""Completion-based validation-stage adapter for Storage Benchmark v1."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .lvs_core import now_local_iso
from .lvs_run_models import StageWindow


@dataclass(frozen=True)
class StorageBenchmarkStageResult:
    run_aborted: bool
    should_break_run: bool


class _CancelSignal:
    def __init__(self, cancel_check: Optional[Callable[[], bool]]) -> None:
        self._event = threading.Event()
        self._cancel_check = cancel_check

    def is_set(self) -> bool:
        if self._event.is_set():
            return True
        try:
            return bool(self._cancel_check and self._cancel_check())
        except Exception:
            return False

    def set(self) -> None:
        self._event.set()

    def wait(self, timeout: float | None = None) -> bool:
        if self.is_set():
            return True
        self._event.wait(timeout)
        return self.is_set()


def _read_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return payload


def _stage_verdict(value: Any) -> str:
    return {
        "PASS": "pass",
        "WARN": "warning",
        "FAIL": "fail",
        "CANCELLED": "aborted",
    }.get(str(value or "").upper(), "fail")


def _payload_messages(payload: Dict[str, Any], key: str) -> List[str]:
    messages = [str(item) for item in payload.get(key) or []]
    for target in payload.get("targets") or []:
        if not isinstance(target, dict):
            continue
        device = str(target.get("device") or "storage target")
        for item in target.get(key) or []:
            messages.append(f"{device}: {item}")
        if key == "warnings" and target.get("skipped_reason"):
            messages.append(f"{device} skipped: {target['skipped_reason']}")
    return list(dict.fromkeys(messages))


def _events(stage: Any, display_name: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for severity, values in (("warning", _payload_messages(payload, "warnings")), ("error", _payload_messages(payload, "errors"))):
        for message in values:
            events.append({
                "timestamp": now_local_iso(),
                "category": "storage_benchmark",
                "severity": severity,
                "stage": display_name,
                "source": stage.id,
                "message": str(message),
                "details": {"profile_id": stage.modules.storage_benchmark.profile_id},
            })
    if str(payload.get("verdict") or "").upper() == "CANCELLED":
        events.append({
            "timestamp": now_local_iso(),
            "category": "operator_stop",
            "severity": "warning",
            "stage": display_name,
            "source": "storage_benchmark",
            "message": "Storage benchmark cancelled by the operator.",
            "details": {},
        })
    return events


def _skipped_payload(message: str, storage: Any) -> Dict[str, Any]:
    return {
        "contract_id": "lvs.storage_benchmark_stage",
        "contract_version": 1,
        "kind": "storage_benchmark_stage",
        "status": "skipped",
        "verdict": "WARN",
        "profile_id": storage.profile_id,
        "target_mode": storage.target_mode,
        "warnings": [message],
        "errors": [],
        "targets": [],
    }


def run_storage_benchmark_stage(
    *,
    service: Any,
    stage: Any,
    display_name: str,
    run_dir: Path,
    stage_plan: Dict[str, Any],
    stage_windows: List[Any],
    executed_plan: List[Dict[str, Any]],
    monotonic: Callable[[], float],
    cancel_check: Optional[Callable[[], bool]] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> StorageBenchmarkStageResult:
    storage = stage.modules.storage_benchmark
    started_iso = now_local_iso()
    started = monotonic()
    output_root = Path(run_dir) / "storage_benchmark"
    cancel = _CancelSignal(cancel_check)
    payload: Dict[str, Any]
    result_path: Path | None = None

    if progress:
        progress(f"{display_name} | completion-based | start")

    def emit(event: Dict[str, Any]) -> None:
        if not progress:
            return
        phase = event.get("phase") or "benchmark"
        device = f" {event.get('device')}" if event.get("device") else ""
        row = f" | {event.get('row')}" if event.get("row") else ""
        repeat = f" | run {event.get('run')}/{event.get('runs')}" if event.get("run") else ""
        progress(f"{display_name} | completion-based | {phase}{device}{row}{repeat}")

    try:
        if storage.target_mode in {"all_internal", "all_internal_non_root_low_occupancy"}:
            low_occupancy = storage.target_mode == "all_internal_non_root_low_occupancy"
            root_confirmation = "BENCHMARK ROOT" if storage.allow_system_drive else None
            if low_occupancy:
                root_confirmation = None
                plan = service.discover_all_internal_non_root_low_occupancy(
                    test_size_gib=storage.test_size_gib,
                    max_used_percent=storage.max_used_percent,
                )
            else:
                plan = service.discover_all_eligible(
                    test_size_gib=storage.test_size_gib,
                    root_confirmation=root_confirmation,
                )
            result_path = service.run_all_internal(
                plan,
                test_size_gib=storage.test_size_gib,
                runs=storage.runs,
                confirmation="BENCHMARK ALL INTERNAL",
                root_confirmation=root_confirmation,
                cancel_event=cancel,
                progress=emit,
                aggregate_dir=output_root,
                embed_per_drive_results=True,
                target_mode=storage.target_mode if low_occupancy else "",
                max_used_percent=storage.max_used_percent if low_occupancy else None,
            )
            payload = _read_json(result_path / "storage_benchmark_all_internal.json")
        else:
            target_path = Path(str(storage.target_path or ""))
            root_confirmation = "BENCHMARK ROOT" if storage.allow_system_drive else None
            try:
                target = service.preflight(
                    target_path,
                    test_size_gib=storage.test_size_gib,
                    root_confirmation=root_confirmation,
                )
            except ValueError as exc:
                output_root.mkdir(parents=True, exist_ok=False)
                payload = _skipped_payload(str(exc), storage)
                service._write_json(output_root / "storage_benchmark_stage.json", payload)
                (output_root / "storage_benchmark_stage_summary.txt").write_text(
                    f"Storage Benchmark\nVerdict: WARN\nSkipped: {exc}\n", encoding="utf-8"
                )
            else:
                output_root.mkdir(parents=True, exist_ok=False)
                result_path = service.run(
                    target.target_path,
                    test_size_gib=storage.test_size_gib,
                    runs=storage.runs,
                    root_confirmation=root_confirmation,
                    confirmed=True,
                    cancel_event=cancel,
                    progress=emit,
                    result_dir=output_root / target.primary_block_name,
                )
                payload = _read_json(result_path / "storage_benchmark.json")
    except Exception as exc:
        output_root.mkdir(parents=True, exist_ok=True)
        payload = {
            "contract_id": "lvs.storage_benchmark_stage",
            "contract_version": 1,
            "kind": "storage_benchmark_stage",
            "status": "failed",
            "verdict": "FAIL",
            "profile_id": storage.profile_id,
            "target_mode": storage.target_mode,
            "warnings": [],
            "errors": [str(exc)],
        }
        service._write_json(output_root / "storage_benchmark_stage.json", payload)

    ended = monotonic()
    ended_iso = now_local_iso()
    verdict = _stage_verdict(payload.get("verdict"))
    events = _events(stage, display_name, payload)
    warnings = _payload_messages(payload, "warnings")
    failures = _payload_messages(payload, "errors")
    summary = {
        "verdict": payload.get("verdict"),
        "status": payload.get("status"),
        "profile_id": storage.profile_id,
        "target_mode": storage.target_mode,
        "drive_execution": storage.drive_execution,
        "test_size_gib": storage.test_size_gib,
        "runs": storage.runs,
        "allow_system_drive": storage.allow_system_drive,
        "artifact_path": str((result_path or output_root).relative_to(run_dir)),
        "total_targets": payload.get("total_targets", 1 if result_path else 0),
        "completed_targets": payload.get("completed_targets", 1 if result_path else 0),
        "warnings": warnings,
        "errors": failures,
    }
    if storage.target_mode == "all_internal_non_root_low_occupancy":
        summary["max_used_percent"] = storage.max_used_percent
    stage_plan.update({
        "execution_mode": "completion",
        "duration_seconds": None,
        "storage_benchmark_summary": summary,
        "error_events": events,
        "failure_reasons": failures,
        "verdict": verdict,
    })
    window = StageWindow(
        stage_id=stage.id,
        stage_type=stage.name,
        display_name=display_name,
        started_iso=started_iso,
        ended_iso=ended_iso,
        started_monotonic=started,
        ended_monotonic=ended,
        duration_seconds=max(0.0, ended - started),
        trim_start_seconds=0,
        trim_end_seconds=0,
        verdict=verdict,
        failure_reasons=failures,
        error_events=events,
        storage_benchmark_summary=summary,
    )
    stage_windows.append(window)
    executed_plan.append(stage_plan)
    if progress:
        progress(f"{display_name} | completion-based | complete | verdict={str(payload.get('verdict') or 'FAIL').upper()}")
    cancelled = verdict == "aborted"
    return StorageBenchmarkStageResult(run_aborted=cancelled, should_break_run=cancelled)
