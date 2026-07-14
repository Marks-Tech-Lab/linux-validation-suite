#!/usr/bin/env python3
"""Run event presentation helpers for CLI-style frontends."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from Modules.lvs_core import format_duration_hms
from Modules.lvs_run_lifecycle import phase_line


class CliRunEventPresenter:
    """CLI phase-line presenter for shared run orchestration callbacks."""

    def __init__(self, *, started_iso: str, emit: Callable[[str], None] = print) -> None:
        self.started_iso = started_iso
        self.emit = emit

    def run_header(self, profile_name: str, run_dir: Path, debug_enabled: bool) -> None:
        self.emit(f"\nRunning profile: {profile_name}")
        self.emit(f"Results folder: {run_dir}")
        if debug_enabled:
            self.emit(f"Advanced debug logging: {run_dir / 'advanced_debug'}")

    def stage_skip(self, label: str, reason: str) -> None:
        self.emit(phase_line(self.started_iso, "stage-skip", stage=label, reason=reason))

    def run_start(self, profile_name: str) -> None:
        self.emit(phase_line(self.started_iso, "run-start", profile=profile_name) + "\n")

    def cpu_tune_start(self, display_name: str, timestamp: str, policy: str) -> None:
        self.emit(
            phase_line(
                timestamp,
                "cpu-tune-start",
                stage=display_name,
                policy=policy,
            )
        )

    def cpu_tune_end(
        self,
        display_name: str,
        timestamp: str,
        tune_elapsed: float,
        selected: str,
        tune_summary_suffix: str,
    ) -> None:
        self.emit(
            phase_line(
                timestamp,
                "cpu-tune-end",
                stage=display_name,
                duration=format_duration_hms(tune_elapsed),
                selected=selected,
            )
            + tune_summary_suffix
        )

    def stage_start(
        self,
        display_name: str,
        timestamp: str,
        stage_type: str,
        planned: str,
        expected_end: str,
        cpu_suffix: str,
        gpu_suffix: str,
    ) -> None:
        self.emit(
            phase_line(
                timestamp,
                "stage-start",
                stage=display_name,
                type=stage_type,
                planned=planned,
                expected_end=expected_end,
            )
            + cpu_suffix
            + gpu_suffix
        )

    def stage_abort(self, display_name: str, timestamp: str, reason: str) -> None:
        self.emit(phase_line(timestamp, "stage-abort", stage=display_name, reason=reason))

    def stage_end(
        self,
        display_name: str,
        timestamp: str,
        stage_elapsed: float,
        verdict: str,
        issue_count: int,
    ) -> None:
        self.emit(
            phase_line(
                timestamp,
                "stage-end",
                stage=display_name,
                actual=format_duration_hms(stage_elapsed),
                verdict=verdict,
            )
            + (f" | issues={issue_count}" if issue_count else "")
        )

    def operator_stop(self, display_name: str, stop_event: dict) -> None:
        self.emit(
            "\n"
            + phase_line(
                str(stop_event["timestamp"]),
                "operator-stop",
                stage=display_name,
                action="stop-workers-and-save",
            )
        )

    def run_end(self, ended_iso: str, total_elapsed: float, overall_verdict: str, skipped_count: int) -> None:
        skipped_suffix = f" | skipped={skipped_count}" if skipped_count else ""
        self.emit(
            "\n"
            + phase_line(
                ended_iso,
                "run-end",
                elapsed=format_duration_hms(total_elapsed),
                verdict=overall_verdict,
            )
            + skipped_suffix
        )

    def run_complete(self, run_dir: Path) -> None:
        self.emit("Run complete.")
        self.emit(f"Compatibility JSON: {run_dir / 'parsed_results_custom.json'}")
        self.emit(f"Run summary: {run_dir / 'run_summary.txt'}")
