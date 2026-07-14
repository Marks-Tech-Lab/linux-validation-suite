#!/usr/bin/env python3
"""Shared post-stage bookkeeping helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from Modules.lvs_stage_event_state import apply_stage_events


@dataclass(frozen=True)
class PostStageBookkeepingResult:
    run_aborted: bool
    stage_aborted: bool
    stage_abort_reason: str
    should_break_run: bool


def apply_completed_stage_bookkeeping(
    *,
    stage_window: Any,
    stage_plan: Dict[str, Any],
    stage_windows: List[Any],
    executed_plan: List[Dict[str, Any]],
    stage_failure_reasons: List[str],
    run_aborted: bool,
    stage_aborted: bool,
    stage_abort_reason: str,
    operator_stop_requested: bool,
    abort_run_on_stage_abort: bool,
    abort_on_system_fault: bool,
    stage_id: str,
    stage_name: str,
    stage_started_iso: str,
    stage_ended_iso: str,
    collect_stage_faults: Callable[[Any], List[Dict[str, Any]]],
    capture_stage_end: Callable[..., None],
) -> PostStageBookkeepingResult:
    stage_windows.append(stage_window)
    executed_plan.append(stage_plan)

    stage_faults = collect_stage_faults(stage_window)
    if stage_faults:
        event_state = apply_stage_events(
            stage_faults,
            stage_window.system_faults,
            stage_failure_reasons,
            stage_window.verdict,
            aborted=stage_aborted,
            abort_reason=stage_abort_reason,
            abort_on_error=abort_on_system_fault,
            abort_only_from_pass=True,
            fail_only_from_pass=True,
        )
        stage_window.verdict = event_state.verdict
        stage_aborted = event_state.aborted
        stage_abort_reason = event_state.abort_reason
        stage_window.failure_reasons = stage_failure_reasons
        if executed_plan:
            executed_plan[-1]["system_faults"] = stage_window.system_faults
            executed_plan[-1]["failure_reasons"] = stage_window.failure_reasons
            executed_plan[-1]["verdict"] = stage_window.verdict

    should_break_run = stage_window.verdict == "aborted" and (operator_stop_requested or abort_run_on_stage_abort)
    if should_break_run:
        run_aborted = True

    capture_stage_end(
        stage_name=stage_name,
        stage_id=stage_id,
        timestamp_iso=stage_ended_iso,
        since_iso=stage_started_iso,
        verdict=stage_window.verdict,
    )
    return PostStageBookkeepingResult(
        run_aborted=run_aborted,
        stage_aborted=stage_aborted,
        stage_abort_reason=stage_abort_reason,
        should_break_run=should_break_run,
    )
