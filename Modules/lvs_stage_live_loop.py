#!/usr/bin/env python3
"""Shared live stage loop policy helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from Modules.lvs_stage_completion import build_stage_check_window
from Modules.lvs_stage_event_state import apply_stage_events
from Modules.lvs_linux_memory import read_linux_memory_snapshot
from Modules.lvs_runtime_memory_guard import update_runtime_memory_guard


@dataclass(frozen=True)
class StageLiveLoopResult:
    stage_processes: List[Any]
    stage_verdict: str
    stage_aborted: bool
    stage_abort_reason: str


def _runtime_memory_guard_context(stage_processes: List[Any]) -> tuple[Dict[str, Any] | None, List[str]]:
    plan = next(
        (getattr(entry, "system_memory_plan", None) for entry in stage_processes if getattr(entry, "system_memory_plan", None)),
        None,
    )
    affected: List[str] = []
    for entry in stage_processes:
        if getattr(entry, "kind", "") == "memory":
            affected.append("system_ram")
        gpu_spec = getattr(entry, "gpu_spec", None)
        if gpu_spec is not None and getattr(gpu_spec, "gpu_memory_kind", "") in {"shared", "unknown"}:
            affected.append(str(getattr(gpu_spec, "memory_budget_consumer_id", "") or getattr(gpu_spec, "target_id", "gpu")))
    for row in (plan or {}).get("unbudgeted_shared_gpu_workers", []):
        affected.append(str(row.get("target_id") or row.get("backend") or "unbudgeted_shared_gpu"))
    return plan, sorted(set(item for item in affected if item))


def run_stage_live_loop(
    *,
    stage_window_cls: Callable[..., Any],
    stage: Any,
    display_name: str,
    stage_started_iso: str,
    stage_start: float,
    stage_processes: List[Any],
    telemetry_collect_once: Callable[[], None],
    telemetry_interval_seconds: float,
    stage_error_events: List[Dict[str, Any]],
    stage_failure_reasons: List[str],
    stage_verdict: str,
    stage_aborted: bool,
    stage_abort_reason: str,
    abort_on_worker_error: bool,
    abort_on_fail_threshold: bool,
    gpu_retune_events: List[Dict[str, Any]],
    progress_interval_seconds: float,
    poll_stage_process_failures: Callable[[List[Any], str], List[Dict[str, Any]]],
    stage_sensor_events: Callable[[Any], List[Dict[str, Any]]],
    maybe_retune_gpu_processes: Callable[[List[Any], float, float], List[Any]],
    stage_target_gpu_progress_summary: Callable[[List[Any], float], str],
    effective_gpu_retune_cooldown_seconds: Callable[[float], float],
    now_local_iso: Callable[[], str],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    format_duration_hms: Callable[[float], str],
    print_progress: Callable[[str], None],
    cancel_check: Callable[[], bool] | None = None,
    memory_snapshot_reader: Callable[[], Dict[str, Any]] = read_linux_memory_snapshot,
) -> StageLiveLoopResult:
    next_progress = stage_start + min(progress_interval_seconds, max(telemetry_interval_seconds, 1.0))
    next_gpu_tune = stage_start + 20.0
    runtime_memory_plan, runtime_memory_workers = _runtime_memory_guard_context(stage_processes)
    memory_warning_event_emitted = False
    while True:
        if cancel_check is not None and cancel_check():
            raise KeyboardInterrupt
        elapsed = monotonic() - stage_start
        if elapsed >= stage.duration_seconds:
            break
        telemetry_collect_once()
        if runtime_memory_plan and (runtime_memory_plan.get("runtime_memory_guard") or {}).get("enabled"):
            memory_snapshot = memory_snapshot_reader()
            guard = update_runtime_memory_guard(
                runtime_memory_plan,
                runtime_mem_available_bytes=int(memory_snapshot.get("mem_available_bytes") or 0),
                timestamp=now_local_iso(),
                affected_workers=runtime_memory_workers,
            )
            if guard.get("runtime_memory_warning_triggered") and not memory_warning_event_emitted:
                warning_event = {
                    "timestamp": now_local_iso(),
                    "category": "runtime_memory_pressure",
                    "severity": "warning",
                    "stage": display_name,
                    "source": "linux_memavailable",
                    "message": "Sustained runtime memory pressure entered the LVS safety warning range.",
                    "details": dict(guard),
                }
                warning_state = apply_stage_events(
                    [warning_event],
                    stage_error_events,
                    stage_failure_reasons,
                    stage_verdict,
                    aborted=stage_aborted,
                    abort_reason=stage_abort_reason,
                )
                stage_verdict = warning_state.verdict
                memory_warning_event_emitted = True
            if guard.get("stage_termination_required"):
                emergency_event = {
                    "timestamp": str(guard.get("guard_trigger_timestamp") or now_local_iso()),
                    "category": "runtime_memory_guard",
                    "severity": "error",
                    "stage": display_name,
                    "source": "linux_memavailable",
                    "message": "Stage stopped after sustained emergency MemAvailable pressure.",
                    "details": dict(guard),
                }
                emergency_state = apply_stage_events(
                    [emergency_event],
                    stage_error_events,
                    stage_failure_reasons,
                    stage_verdict,
                    aborted=stage_aborted,
                    abort_reason=stage_abort_reason,
                    abort_on_error=True,
                )
                stage_verdict = emergency_state.verdict
                stage_aborted = emergency_state.aborted
                stage_abort_reason = emergency_state.abort_reason
                break
        failed_process_events = poll_stage_process_failures(stage_processes, display_name)
        if failed_process_events:
            event_state = apply_stage_events(
                failed_process_events,
                stage_error_events,
                stage_failure_reasons,
                stage_verdict,
                aborted=stage_aborted,
                abort_reason=stage_abort_reason,
                abort_on_error=abort_on_worker_error,
            )
            stage_verdict = event_state.verdict
            stage_aborted = event_state.aborted
            stage_abort_reason = event_state.abort_reason
            if event_state.aborted:
                break
        now_monotonic = monotonic()
        live_sensor_events = [
            event
            for event in stage_sensor_events(
                build_stage_check_window(
                    stage_window_cls=stage_window_cls,
                    stage=stage,
                    display_name=display_name,
                    started_iso=stage_started_iso,
                    ended_iso=now_local_iso(),
                    started_monotonic=stage_start,
                    ended_monotonic=now_monotonic,
                    duration_seconds=max(0.0, now_monotonic - stage_start),
                    trim_start_seconds=0,
                    trim_end_seconds=0,
                ),
            )
            if event.get("severity") == "error"
        ]
        if live_sensor_events:
            event_state = apply_stage_events(
                live_sensor_events,
                stage_error_events,
                stage_failure_reasons,
                stage_verdict,
                aborted=stage_aborted,
                abort_reason=stage_abort_reason,
                abort_on_error=abort_on_fail_threshold,
            )
            stage_verdict = event_state.verdict
            stage_aborted = event_state.aborted
            stage_abort_reason = event_state.abort_reason
            if event_state.aborted:
                break
        if now_monotonic >= next_gpu_tune:
            stage_processes = maybe_retune_gpu_processes(
                stage_processes,
                elapsed,
                stage.duration_seconds,
            )
            next_gpu_tune = now_monotonic + max(
                20.0,
                effective_gpu_retune_cooldown_seconds(stage.duration_seconds),
            )
        if now_monotonic >= next_progress:
            remaining = max(0.0, stage.duration_seconds - elapsed)
            gpu_progress = stage_target_gpu_progress_summary(stage_processes, elapsed)
            print_progress(
                f"[progress] {now_local_iso()} | stage={display_name} | elapsed={format_duration_hms(elapsed)} | remaining={format_duration_hms(remaining)}{gpu_progress}"
            )
            next_progress += progress_interval_seconds
        sleep(telemetry_interval_seconds)
    return StageLiveLoopResult(
        stage_processes=stage_processes,
        stage_verdict=stage_verdict,
        stage_aborted=stage_aborted,
        stage_abort_reason=stage_abort_reason,
    )
