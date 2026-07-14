#!/usr/bin/env python3
"""Dependency and readiness summary helpers for UI frontends."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .lvs_core import JsonStore
from .lvs_dependency_report_artifacts import (
    new_report_dir,
    save_dependency_check_report as write_dependency_check_report,
)
from .lvs_dependency_payload import (
    DependencyCheckPayloadBuilder,
    gpu_opencl_coverage,
    memory_module_has_identity_default,
    memory_modules_default,
)
from .lvs_dependency_report_text import (
    dependency_check_detail_text as render_dependency_check_detail_text,
    dependency_check_summary_text as render_dependency_check_summary_text,
    dependency_summary_text as render_dependency_summary_text,
    dependency_item_lines,
    dependency_status_text,
)


@dataclass
class DependencyCheckResult:
    payload: Dict[str, Any]
    detail_text: str
    summary_text: str
    report_dir: Path


class DependencyReportManager:
    """Builds compact dependency summaries without frontend prompt logic."""

    def __init__(
        self,
        settings: Any,
        orchestrator: Any,
        drive_readiness: Callable[[], Dict[str, Any]],
        telemetry_factory: Optional[Callable[..., Any]] = None,
        memory_modules_factory: Optional[Callable[[bool], list[Dict[str, Any]]]] = None,
    ) -> None:
        self.settings = settings
        self.orchestrator = orchestrator
        self.drive_readiness = drive_readiness
        self.telemetry_factory = telemetry_factory or self._default_telemetry_factory()
        self.memory_modules_factory = memory_modules_factory or self._memory_modules
        self.payload_builder = DependencyCheckPayloadBuilder(
            settings,
            orchestrator,
            drive_readiness,
            self.telemetry_factory,
            self.memory_modules_factory,
        )

    def _default_telemetry_factory(self) -> Callable[..., Any]:
        from linux_validation_suite import TelemetryCollector

        return TelemetryCollector

    def dependency_summary_text(self) -> str:
        backends = self.orchestrator.workload_runner.detect_backends()
        details = self.orchestrator.workload_runner.backend_details()
        telemetry = self.telemetry_factory(
            interval_seconds=self.settings.sample_interval_seconds,
            runtime_environment=self.settings.runtime_environment,
            privileged_helper_enabled=bool(self.settings.privileged_helper_enabled),
        )
        capabilities = telemetry.detect_capabilities()
        drive = self.drive_readiness()
        return render_dependency_summary_text(backends, details, capabilities, drive)

    def dependency_check_payload(
        self,
        *,
        sudo_noninteractive_ready: Optional[Callable[[], bool]] = None,
        memory_module_has_identity: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> Dict[str, Any]:
        return self.payload_builder.dependency_check_payload(
            sudo_noninteractive_ready=sudo_noninteractive_ready,
            memory_module_has_identity=memory_module_has_identity,
        )

    @staticmethod
    def _memory_module_has_identity(module: Dict[str, Any]) -> bool:
        return memory_module_has_identity_default(module)

    @staticmethod
    def _memory_modules(privileged_helper_enabled: bool) -> list[Dict[str, Any]]:
        return memory_modules_default(privileged_helper_enabled)

    @staticmethod
    def _gpu_opencl_coverage(workload_runner: Any) -> list[Dict[str, Any]]:
        return gpu_opencl_coverage(workload_runner)

    def dependency_check_detail_text(self, payload: Dict[str, Any]) -> str:
        return render_dependency_check_detail_text(payload)

    @classmethod
    def _dependency_item_lines(
        cls,
        name: str,
        available: bool,
        *,
        detail: str = "",
        fix: str = "",
        preferred: bool = False,
    ) -> list[str]:
        return dependency_item_lines(
            name,
            available,
            detail=detail,
            fix=fix,
            preferred=preferred,
        )

    @staticmethod
    def _dependency_status_text(available: bool, preferred: bool = False) -> str:
        return dependency_status_text(available, preferred=preferred)

    def save_dependency_check_report(self, results_dir: Path | str, text: str, payload: Dict[str, Any]) -> Path:
        return write_dependency_check_report(
            results_dir,
            text,
            payload,
            summary_renderer=self.dependency_check_summary_text,
        )

    def run_dependency_check(
        self,
        results_dir: Path | str,
        *,
        sudo_noninteractive_ready: Optional[Callable[[], bool]] = None,
        memory_module_has_identity: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> DependencyCheckResult:
        payload = self.dependency_check_payload(
            sudo_noninteractive_ready=sudo_noninteractive_ready,
            memory_module_has_identity=memory_module_has_identity,
        )
        detail_text = self.dependency_check_detail_text(payload)
        report_dir = self.save_dependency_check_report(results_dir, detail_text, payload)
        saved_payload = JsonStore.read(report_dir / "dependency_check.json", payload)
        summary_text = self.dependency_check_summary_text(saved_payload, report_dir)
        return DependencyCheckResult(
            payload=saved_payload,
            detail_text=detail_text,
            summary_text=summary_text,
            report_dir=report_dir,
        )

    def dependency_check_summary_text(self, payload: Dict[str, Any], report_dir: Optional[Path] = None) -> str:
        return render_dependency_check_summary_text(payload, report_dir)

    def _new_report_dir(self, results_dir: Path | str, suffix: str) -> Path:
        return new_report_dir(results_dir, suffix)
