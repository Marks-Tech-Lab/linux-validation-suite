from __future__ import annotations

"""CLI entrypoint and compatibility facade for Linux Validation Suite.

The implementation now lives in shared modules under ``Modules/`` so the CLI,
TUI, future GUI, and smoke tests can use the same backend behavior. Keep this
file small: add re-exports here only when older callers still import from the
top-level ``linux_validation_suite`` module.
"""

from pathlib import Path

from Modules.lvs_cli_launcher import (
    BackRequested,
    GoogleDriveUploader,
    Launcher,
    ProfileLoader,
    RunSummaryTextExporter,
    ValidationOrchestrator,
    WorkloadRunner,
)
from Modules.lvs_compat_exporter import CompatibilityExporter
from Modules.lvs_core import APP_NAME, APP_VERSION, JsonStore
from Modules.lvs_profile_models import (
    ModuleCpu,
    ModuleGpu3D,
    ModuleMemory,
    ModuleVram,
    ProfileDefaults,
    StageConfig,
    StageModules,
    StageNormalization,
    ValidationProfile,
)
from Modules.lvs_profile_validation import ProfileValidator
from Modules.lvs_run_metadata import RunMetadata
from Modules.lvs_run_models import StageWindow
from Modules.lvs_segment_parser import SegmentParser
from Modules.lvs_service_models import RunSetupState
from Modules.lvs_settings import (
    DEFAULT_GOOGLE_CREDENTIALS_PATH,
    DEFAULT_GOOGLE_SHARED_DRIVE_ID,
    DEFAULT_PROFILES_DIR,
    DEFAULT_RESULTS_DIR,
    DEFAULT_SAMPLE_INTERVAL_SECONDS,
    DEFAULT_SETTINGS_DIR,
    DEFAULT_STAGE_PROGRESS_INTERVAL_SECONDS,
    DEFAULT_TRIM_END_SECONDS,
    DEFAULT_TRIM_START_SECONDS,
    GlobalSettings,
    SettingsManager,
)
from Modules.lvs_telemetry_collector import Sample, TelemetryCollector


DEFAULT_NATIVE_DIR = Path("native")
DEFAULT_BUILD_DIR = Path("build")
DEFAULT_CPU_TUNER_SAMPLE_INTERVAL_SECONDS = 0.5
DEFAULT_CPU_TUNER_WARMUP_SECONDS = 1.0
DEFAULT_CPU_TUNER_MEASURE_SECONDS = 3.0


__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "BackRequested",
    "CompatibilityExporter",
    "DEFAULT_BUILD_DIR",
    "DEFAULT_CPU_TUNER_MEASURE_SECONDS",
    "DEFAULT_CPU_TUNER_SAMPLE_INTERVAL_SECONDS",
    "DEFAULT_CPU_TUNER_WARMUP_SECONDS",
    "DEFAULT_GOOGLE_CREDENTIALS_PATH",
    "DEFAULT_GOOGLE_SHARED_DRIVE_ID",
    "DEFAULT_NATIVE_DIR",
    "DEFAULT_PROFILES_DIR",
    "DEFAULT_RESULTS_DIR",
    "DEFAULT_SAMPLE_INTERVAL_SECONDS",
    "DEFAULT_SETTINGS_DIR",
    "DEFAULT_STAGE_PROGRESS_INTERVAL_SECONDS",
    "DEFAULT_TRIM_END_SECONDS",
    "DEFAULT_TRIM_START_SECONDS",
    "GlobalSettings",
    "GoogleDriveUploader",
    "JsonStore",
    "Launcher",
    "ModuleCpu",
    "ModuleGpu3D",
    "ModuleMemory",
    "ModuleVram",
    "ProfileDefaults",
    "ProfileLoader",
    "ProfileValidator",
    "RunMetadata",
    "RunSetupState",
    "RunSummaryTextExporter",
    "Sample",
    "SegmentParser",
    "SettingsManager",
    "StageConfig",
    "StageModules",
    "StageNormalization",
    "StageWindow",
    "TelemetryCollector",
    "ValidationOrchestrator",
    "ValidationProfile",
    "WorkloadRunner",
    "main",
]


def main() -> int:
    Launcher().start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
