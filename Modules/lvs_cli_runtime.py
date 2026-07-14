from __future__ import annotations

from Modules.lvs_cli_compat import ProfileLoader, ValidationOrchestrator
from Modules.lvs_cli_input import TerminalInputAdapter
from Modules.lvs_cli_privileged import PrivilegedCliAdapter
from Modules.lvs_cli_profile import ProfileCliAdapter
from Modules.lvs_cli_profile_compat import ProfileCompatibilityAdapter
from Modules.lvs_cli_results import ResultCliAdapter
from Modules.lvs_cli_run import RunCliAdapter
from Modules.lvs_cli_run_setup import RunSetupCliAdapter
from Modules.lvs_cli_settings import SettingsCliAdapter
from Modules.lvs_cli_shell import ShellCliAdapter
from Modules.lvs_cli_state import CliStateAdapter
from Modules.lvs_cli_upload import UploadCliAdapter
from Modules.lvs_diagnostics_cli import DiagnosticsCliAdapter
from Modules.lvs_runtime_services import build_runtime_services, normalize_runtime_settings
from Modules.lvs_settings import DEFAULT_SETTINGS_DIR, SettingsManager


class LauncherRuntimeMixin:
    """Runtime service wiring for the CLI launcher facade."""

    def __init__(self) -> None:
        settings_path = DEFAULT_SETTINGS_DIR / "global_settings.json"
        self.settings_manager = SettingsManager(settings_path)
        self._pending_heatsoak_minutes: float = 0.0
        self.input_cli = TerminalInputAdapter()
        self.state_cli = CliStateAdapter(self)
        self.privileged_cli = PrivilegedCliAdapter(self)
        self._prompt_privileged_helper_at_launch()
        self._reload_runtime_state()

    def _reload_runtime_state(self) -> None:
        normalize_runtime_settings(
            self.settings_manager.settings,
            normalize_text_list=self._normalize_text_list,
            profile_loader_type=ProfileLoader,
        )
        runtime = build_runtime_services(
            settings=self.settings_manager.settings,
            orchestrator_factory=ValidationOrchestrator,
            ensure_ready=lambda: self._ensure_privileged_helper_ready("this run"),
            run_heatsoak_if_requested=self._run_heatsoak_if_requested,
            environment_mode_label=self._environment_mode_label,
            profile_loader_type=ProfileLoader,
            ensure_example_profile=True,
        )
        runtime.bind_to(self)
        self.profile_cli = ProfileCliAdapter(self)
        self.profile_compat_cli = ProfileCompatibilityAdapter(self)
        self.diagnostics_cli = DiagnosticsCliAdapter(self)
        self.results_cli = ResultCliAdapter(self)
        self.run_cli = RunCliAdapter(self)
        self.run_setup_cli = RunSetupCliAdapter(self)
        self.settings_cli = SettingsCliAdapter(self)
        self.shell_cli = ShellCliAdapter(self)
        self.upload_cli = UploadCliAdapter(self)
