#!/usr/bin/env python3
"""Shared final run artifact/export writer."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List

from Modules.lvs_core import JsonStore
from Modules.lvs_output_contract_identity import (
    RUN_MANIFEST_CONTRACT_ID,
    RUN_MANIFEST_KIND,
    TELEMETRY_SOURCE_MAP_CONTRACT_ID,
    TELEMETRY_SOURCE_MAP_KIND,
    stamp_contract_identity,
)
from Modules.lvs_run_finalization import finalize_run_stage_windows


@dataclass(frozen=True)
class FinalRunArtifactsResult:
    overall_verdict: str
    all_events: List[Dict[str, Any]]
    warning_events: List[Dict[str, Any]]
    error_events: List[Dict[str, Any]]
    parser_output: Dict[str, Any]
    compatibility_export: Dict[str, Any]


def write_final_run_artifacts(
    *,
    run_dir: Path,
    manifest_payload: Dict[str, Any],
    app_name: str,
    app_version: str,
    profile: Any,
    metadata: Any,
    started_iso: str,
    ended_iso: str,
    total_elapsed: float,
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
    stage_faults: Callable[[Any], List[Dict[str, Any]]],
    capture_run_end: Callable[..., None],
) -> FinalRunArtifactsResult:
    run_finalization = finalize_run_stage_windows(
        stage_windows,
        executed_plan,
        run_aborted=run_aborted,
        stage_sensor_events=stage_sensor_events,
        stage_faults=stage_faults,
    )
    overall_verdict = run_finalization.overall_verdict
    run_all_events = run_finalization.all_events
    run_warning_events = run_finalization.warning_events
    run_error_events = run_finalization.error_events

    capture_run_end(ended_iso=ended_iso, since_iso=started_iso, verdict=overall_verdict)

    manifest_payload["ended"] = ended_iso
    manifest_payload["elapsed_seconds"] = round(total_elapsed, 2)
    manifest_payload["executed_plan"] = executed_plan
    manifest_payload["stage_windows"] = [asdict(w) for w in stage_windows]
    manifest_payload["verdict"] = overall_verdict
    manifest_payload["events"] = run_all_events
    manifest_payload["warning_events"] = run_warning_events
    manifest_payload["error_events"] = run_error_events
    stamp_contract_identity(
        manifest_payload,
        contract_id=RUN_MANIFEST_CONTRACT_ID,
        kind=RUN_MANIFEST_KIND,
    )
    JsonStore.write(run_dir / "run_manifest.json", manifest_payload)

    if keep_raw_telemetry:
        telemetry.write_csv(run_dir / "raw_telemetry.csv")
        source_map = telemetry.source_map()
        stamp_contract_identity(
            source_map,
            contract_id=TELEMETRY_SOURCE_MAP_CONTRACT_ID,
            kind=TELEMETRY_SOURCE_MAP_KIND,
        )
        JsonStore.write(run_dir / "telemetry_source_map.json", source_map)

    parser_output = segment_parser.summarize(
        stage_windows,
        telemetry,
        system_info["Hardware"].get("Gpu", []),
        system_info["Hardware"].get("Cpu", {}),
    )
    compat = exporter.build(
        metadata,
        started_iso,
        ended_iso,
        total_elapsed,
        system_info,
        parser_output,
        telemetry,
        stage_windows,
        recovery_report,
        skipped_stages,
    )

    if export_compatibility_json:
        JsonStore.write(run_dir / "parsed_results_custom.json", compat)
    (run_dir / "run_summary.txt").write_text(
        summary_exporter.build(compat),
        encoding="utf-8",
    )
    if export_extended_json:
        JsonStore.write(
            run_dir / "parsed_results_extended.json",
            {
                "app_name": app_name,
                "app_version": app_version,
                "profile": asdict(profile),
                "run_metadata": asdict(metadata),
                "stage_windows": [asdict(w) for w in stage_windows],
                "system_info": system_info,
                "gpu_recovery": recovery_report,
                "compatibility_export": compat,
            },
        )

    return FinalRunArtifactsResult(
        overall_verdict=overall_verdict,
        all_events=run_all_events,
        warning_events=run_warning_events,
        error_events=run_error_events,
        parser_output=parser_output,
        compatibility_export=compat,
    )
