#!/usr/bin/env python3
"""Shared final run/stage verdict consolidation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List

from Modules.lvs_run_verdict import combine_run_verdict


@dataclass(frozen=True)
class RunFinalizationResult:
    overall_verdict: str
    all_events: List[Dict[str, Any]]
    warning_events: List[Dict[str, Any]]
    error_events: List[Dict[str, Any]]
    manual_abort: bool


def event_identity(event: Dict[str, Any]) -> tuple[Any, Any, Any]:
    return (
        event.get("category"),
        event.get("source"),
        event.get("message"),
    )


def event_severity(event: Dict[str, Any]) -> str:
    return str(event.get("severity") or "").strip().lower()


def finalize_run_stage_windows(
    stage_windows: List[Any],
    executed_plan: List[Dict[str, Any]],
    *,
    run_aborted: bool,
    stage_sensor_events: Callable[[Any], Iterable[Dict[str, Any]]],
    stage_faults: Callable[[Any], Iterable[Dict[str, Any]]],
) -> RunFinalizationResult:
    for index, window in enumerate(stage_windows):
        existing_sensor_keys = {event_identity(event) for event in getattr(window, "error_events", [])}
        sensor_events = [
            event
            for event in stage_sensor_events(window)
            if event_identity(event) not in existing_sensor_keys
        ]
        existing_fault_keys = {event_identity(event) for event in getattr(window, "system_faults", [])}
        faults = [
            event
            for event in stage_faults(window)
            if event_identity(event) not in existing_fault_keys
        ]

        if sensor_events:
            window.error_events.extend(sensor_events)
        if faults:
            window.system_faults.extend(faults)
        if sensor_events or faults:
            window.failure_reasons.extend(
                str(event.get("message") or "")
                for event in [*sensor_events, *faults]
                if event_severity(event) == "error" and str(event.get("message") or "")
            )

        if window.verdict != "aborted":
            combined_events = [*window.error_events, *window.system_faults]
            if any(event_severity(event) == "error" for event in combined_events):
                window.verdict = "fail"
            elif any(event_severity(event) == "warning" for event in combined_events):
                window.verdict = "warning"

        if index < len(executed_plan):
            executed_plan[index]["error_events"] = window.error_events
            executed_plan[index]["system_faults"] = window.system_faults
            executed_plan[index]["failure_reasons"] = window.failure_reasons
            executed_plan[index]["verdict"] = window.verdict

    run_all_events: List[Dict[str, Any]] = []
    for window in stage_windows:
        run_all_events.extend(window.error_events)
        run_all_events.extend(window.system_faults)

    manual_abort = any(str(event.get("category") or "").strip().lower() == "operator_stop" for event in run_all_events)
    overall_verdict = combine_run_verdict(
        (window.verdict for window in stage_windows),
        run_aborted=run_aborted,
        manual_abort=manual_abort,
    )
    run_warning_events = [
        event for event in run_all_events
        if event_severity(event) == "warning"
    ]
    run_error_events = [
        event for event in run_all_events
        if event_severity(event) == "error"
    ]
    return RunFinalizationResult(
        overall_verdict=overall_verdict,
        all_events=run_all_events,
        warning_events=run_warning_events,
        error_events=run_error_events,
        manual_abort=manual_abort,
    )
