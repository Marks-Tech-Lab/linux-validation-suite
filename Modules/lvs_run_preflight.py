#!/usr/bin/env python3
"""Shared profile readiness and preflight orchestration."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import platform
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

    def save_effective_setup_report(self, readiness: ProfileReadiness, setup: Any, report: Dict[str, Any]) -> Path:
        """Persist the evaluated setup, never relabel an original-profile dry run."""
        from .lvs_profile_report_artifacts import profile_used_payload
        original = getattr(setup, "original_profile", None)
        original_basis = "run_setup_snapshot"
        if original is None:
            original = self.profile_loader.load_profile(readiness.profile_path)
            original_basis = "saved_profile_at_evaluation"
        original_labels = getattr(setup, "original_labels", None)
        if original_labels is None:
            original_labels = self.profile_loader.load_segment_labels(readiness.profile_path, original)
        original_payload = profile_used_payload(original, original_labels)
        effective_payload = profile_used_payload(readiness.profile, readiness.labels)
        changes = []
        def compare(before, after, path=""):
            if isinstance(before, dict) and isinstance(after, dict):
                for key in sorted(before.keys() | after.keys()):
                    compare(before.get(key), after.get(key), path+"/"+key)
            elif isinstance(before, list) and isinstance(after, list) and len(before)==len(after):
                for i,(a,b) in enumerate(zip(before, after)):
                    compare(a,b,path+"/"+str(i))
            elif before != after:
                changes.append({"path":path,"original":deepcopy(before),"effective":deepcopy(after)})
        compare(original_payload,effective_payload)
        context = {"diagnostic_scope":"effective_run_setup", "original_profile_basis":original_basis,
                   "original_profile":original_payload, "effective_profile":effective_payload,
                   "run_local_overrides":changes,
                   "advanced_debug_logging":bool(getattr(setup.metadata,"advanced_debug_logging",False)),
                   "execution_started":False}
        # Repeated display of the same decision refreshes its artifact. A changed
        # setup/decision gets a separate folder, retaining earlier blocked evidence.
        decision = {k:report.get(k) for k in ("runnable","validation","plan","enabled_stage_count","runnable_stage_count")}
        key = hashlib.sha256(json.dumps([context,decision],sort_keys=True).encode()).hexdigest()
        cache = getattr(setup,"_effective_preflight_reports",{})
        context["hardware_identity"] = {"hostname":platform.node(), "architecture":platform.machine(),
                                        "kernel":platform.release(), "processor":platform.processor(), "status":"host_identity_and_recorded_readiness"}
        # Capability/target and backend evidence stays in the exact evaluated report;
        # no second capability probe or command generation is performed for saving.
        context["hardware_identity"]["cpu_targets"] = [deepcopy(p.get("cpu_targeting",{})) for p in report.get("plan",[])]
        result = self.profile_reports.save_cli_preflight_report(
            readiness.profile_path,readiness.profile,readiness.labels,report,
            runtime_environment=report.get("runtime_environment",{}),backends=report.get("backends",{}),
            backend_details=report.get("backend_details",{}),
            summary_text=self.profile_reports.preflight_summary_text(report),
            effective_context=context, report_dir=cache.get(key),
        )
        cache[key]=result
        setup._effective_preflight_reports=cache
        return result

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
