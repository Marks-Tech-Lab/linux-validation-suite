#!/usr/bin/env python3
"""Shared run completion/finalization orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List

from Modules.lvs_run_artifacts import FinalRunArtifactsResult, write_final_run_artifacts


@dataclass(frozen=True)
class RunCompletionResult:
    run_dir: Path
    ended_iso: str
    total_elapsed: float
    overall_verdict: str
    final_artifacts: FinalRunArtifactsResult


def complete_validation_run(
    *,
    run_dir: Path,
    manifest_payload: Dict[str, Any],
    app_name: str,
    app_version: str,
    profile: Any,
    metadata: Any,
    started_iso: str,
    started_monotonic: float,
    system_info: Dict[str, Any],
    telemetry: Any,
    stage_windows: List[Any],
    executed_plan: List[Dict[str, Any]],
    recovery_report: Dict[str, Any],
    skipped_stages: List[Dict[str, Any]],
    run_aborted: bool,
    keep_raw_telemetry: bool,
    export_compatibility_json: bool,
    export_extended_json: bool,
    segment_parser: Any,
    exporter: Any,
    summary_exporter: Any,
    stage_sensor_events: Callable[[Any], List[Dict[str, Any]]],
    collect_kernel_faults: Callable[[str, str], List[Dict[str, Any]]],
    faults_for_stage: Callable[[List[Dict[str, Any]], Any], List[Dict[str, Any]]],
    capture_run_end: Callable[..., None],
    run_events: Any,
    now_local_iso: Callable[[], str],
    monotonic: Callable[[], float],
) -> RunCompletionResult:
    ended_iso = now_local_iso()
    total_elapsed = monotonic() - started_monotonic
    kernel_faults = collect_kernel_faults(started_iso, ended_iso)
    final_artifacts = write_final_run_artifacts(
        run_dir=run_dir,
        manifest_payload=manifest_payload,
        app_name=app_name,
        app_version=app_version,
        profile=profile,
        metadata=metadata,
        started_iso=started_iso,
        ended_iso=ended_iso,
        total_elapsed=total_elapsed,
        system_info=system_info,
        telemetry=telemetry,
        stage_windows=stage_windows,
        executed_plan=executed_plan,
        recovery_report=recovery_report,
        skipped_stages=skipped_stages,
        run_aborted=run_aborted,
        keep_raw_telemetry=keep_raw_telemetry,
        export_compatibility_json=export_compatibility_json,
        export_extended_json=export_extended_json,
        segment_parser=segment_parser,
        exporter=exporter,
        summary_exporter=summary_exporter,
        stage_sensor_events=stage_sensor_events,
        stage_faults=lambda window: faults_for_stage(kernel_faults, window),
        capture_run_end=capture_run_end,
    )
    overall_verdict = final_artifacts.overall_verdict
    run_events.run_end(ended_iso, total_elapsed, overall_verdict, len(skipped_stages))
    run_events.run_complete(run_dir)
    return RunCompletionResult(
        run_dir=run_dir,
        ended_iso=ended_iso,
        total_elapsed=total_elapsed,
        overall_verdict=overall_verdict,
        final_artifacts=final_artifacts,
    )
