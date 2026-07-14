#!/usr/bin/env python3
"""Shared profile readiness and preflight orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional


@dataclass
class ProfileReadiness:
    profile_path: Path
    profile: Any
    labels: list[str]
    label_source_info: Dict[str, Any]
    validation: Dict[str, list[str]]


@dataclass
class PreflightReadiness:
    report: Dict[str, Any]
    skipped_stage_count: int
    report_dir: Optional[Path] = None


class RunPreflightManager:
    """Frontend-neutral profile validation and preflight checks."""

    def __init__(
        self,
        *,
        profile_loader: Any,
        orchestrator: Any,
        profile_reports: Any,
        ensure_ready: Callable[[], bool] | None = None,
    ) -> None:
        self.profile_loader = profile_loader
        self.orchestrator = orchestrator
        self.profile_reports = profile_reports
        self.ensure_ready = ensure_ready

    def inspect_profile(self, profile_path: Path) -> ProfileReadiness:
        profile = self.profile_loader.load_profile(profile_path)
        labels = self.profile_loader.load_segment_labels(profile_path, profile)
        return self.inspect_profile_context(profile_path, profile, labels)

    def inspect_profile_context(
        self,
        profile_path: Path,
        profile: Any,
        labels: list[str],
    ) -> ProfileReadiness:
        label_source_info = self.profile_loader.inspect_segment_label_source(profile_path, profile)
        validation = self.orchestrator.validator.validate(profile, labels)
        validation["warnings"].extend(label_source_info["issues"])
        return ProfileReadiness(
            profile_path=profile_path,
            profile=profile,
            labels=labels,
            label_source_info=label_source_info,
            validation=validation,
        )

    def run_preflight(
        self,
        readiness: ProfileReadiness,
        *,
        save_blocked_report: bool = False,
    ) -> PreflightReadiness:
        if self.ensure_ready is not None:
            self.ensure_ready()
        report = self.orchestrator.dry_run(
            readiness.profile_path,
            readiness.profile,
            readiness.labels,
        )
        issues = list(readiness.label_source_info.get("issues") or [])
        if issues:
            report["validation"]["warnings"].extend(issues)
        skipped_stage_count = max(
            0,
            int(report.get("enabled_stage_count", 0)) - int(report.get("runnable_stage_count", 0)),
        )
        report_dir = None
        if save_blocked_report and not report.get("runnable"):
            report_dir = self.save_preflight_report(readiness, report)
        return PreflightReadiness(
            report=report,
            skipped_stage_count=skipped_stage_count,
            report_dir=report_dir,
        )

    def save_preflight_report(self, readiness: ProfileReadiness, report: Dict[str, Any]) -> Path:
        workload_runner = getattr(self.orchestrator, "workload_runner", None)
        runtime_environment = (
            workload_runner.runtime_environment()
            if workload_runner is not None and callable(getattr(workload_runner, "runtime_environment", None))
            else {}
        )
        backends = (
            workload_runner.detect_backends()
            if workload_runner is not None and callable(getattr(workload_runner, "detect_backends", None))
            else {}
        )
        backend_details = (
            workload_runner.backend_details()
            if workload_runner is not None and callable(getattr(workload_runner, "backend_details", None))
            else {}
        )
        return self.profile_reports.save_cli_preflight_report(
            readiness.profile_path,
            readiness.profile,
            readiness.labels,
            report,
            runtime_environment=runtime_environment,
            backends=backends,
            backend_details=backend_details,
            summary_text=self.profile_reports.preflight_summary_text(report),
        )
