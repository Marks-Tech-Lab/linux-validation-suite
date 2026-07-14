from __future__ import annotations

"""CLI launcher compatibility facade.

This module intentionally keeps a small legacy import surface for
``linux_validation_suite.py`` and older callers, while the actual launcher
runtime wiring and CLI adapters live in focused modules.
"""

from Modules.lvs_cli_compat import (
    BackRequested,
    GoogleDriveUploader,
    ProfileLoader,
    RunSummaryTextExporter,
    ValidationOrchestrator,
    WorkloadRunner,
)
from Modules.lvs_cli_diagnostics_compat import DiagnosticsCompatibilityMixin
from Modules.lvs_cli_heatsoak_compat import HeatsoakCompatibilityMixin
from Modules.lvs_cli_input import InputCompatibilityMixin
from Modules.lvs_cli_privileged import PrivilegedCompatibilityMixin
from Modules.lvs_cli_profile_compat import ProfileCompatibilityMixin
from Modules.lvs_cli_results import ResultsCompatibilityMixin
from Modules.lvs_cli_run import RunCompatibilityMixin
from Modules.lvs_cli_run_setup_compat import RunSetupCompatibilityMixin
from Modules.lvs_cli_run_setup_hardware_compat import RunSetupHardwareCompatibilityMixin
from Modules.lvs_cli_run_setup_history_compat import RunSetupHistoryCompatibilityMixin
from Modules.lvs_cli_settings_compat import SettingsCompatibilityMixin
from Modules.lvs_cli_shell import ShellCompatibilityMixin
from Modules.lvs_cli_state import StateCompatibilityMixin
from Modules.lvs_cli_runtime import LauncherRuntimeMixin


class Launcher(
    LauncherRuntimeMixin,
    DiagnosticsCompatibilityMixin,
    HeatsoakCompatibilityMixin,
    InputCompatibilityMixin,
    ProfileCompatibilityMixin,
    PrivilegedCompatibilityMixin,
    RunCompatibilityMixin,
    RunSetupCompatibilityMixin,
    RunSetupHardwareCompatibilityMixin,
    RunSetupHistoryCompatibilityMixin,
    ResultsCompatibilityMixin,
    SettingsCompatibilityMixin,
    ShellCompatibilityMixin,
    StateCompatibilityMixin,
):
    pass
