from __future__ import annotations

"""Compatibility adapters for the legacy top-level CLI module.

These wrappers keep older imports from ``linux_validation_suite`` stable while
the implementation continues moving into shared backend modules.
"""

import sys
from typing import Any, Dict

from .lvs_core import APP_NAME
from .lvs_google_drive_uploader import GoogleDriveUploader as ModuleGoogleDriveUploader
from .lvs_profile_loader import ProfileLoader as ModuleProfileLoader
from .lvs_profile_models import ModuleCpu
from .lvs_settings import GlobalSettings
from .lvs_summary_text import SummaryTextBuilder
from .lvs_telemetry_collector import TelemetryCollector
from .lvs_validation_orchestrator import ValidationOrchestrator as ModuleValidationOrchestrator
import Modules.lvs_workload_runner as lvs_workload_runner_module
from .lvs_workload_runner import WorkloadRunner as ModuleWorkloadRunner


class BackRequested(Exception):
    """Raised when the operator asks to leave the current prompt/menu."""


class ProfileLoader(ModuleProfileLoader):
    """Compatibility wrapper for the module-backed profile loader."""


class WorkloadRunner(ModuleWorkloadRunner):
    """Compatibility wrapper for the module-backed workload runner."""

    def _sync_compat_dependencies(self) -> None:
        public_module = sys.modules.get("linux_validation_suite")
        lvs_workload_runner_module.TelemetryCollector = getattr(
            public_module,
            "TelemetryCollector",
            TelemetryCollector,
        )

    def resolve_cpu_execution(self, cpu: ModuleCpu, tune_max_power: bool = False) -> Dict[str, Any]:
        self._sync_compat_dependencies()
        return super().resolve_cpu_execution(cpu, tune_max_power=tune_max_power)


class RunSummaryTextExporter(SummaryTextBuilder):
    def __init__(self) -> None:
        super().__init__(APP_NAME)


class ValidationOrchestrator(ModuleValidationOrchestrator):
    """Compatibility wrapper that injects the CLI workload runner."""

    def __init__(self, settings: GlobalSettings) -> None:
        super().__init__(
            settings,
            workload_runner_cls=WorkloadRunner,
            summary_exporter_cls=RunSummaryTextExporter,
        )


class GoogleDriveUploader(ModuleGoogleDriveUploader):
    """Compatibility wrapper for the module-backed Google Drive uploader."""
