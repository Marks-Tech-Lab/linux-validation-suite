from __future__ import annotations

from typing import Any

from Modules.lvs_cli_settings_advanced import SettingsAdvancedEditorMixin
from Modules.lvs_cli_settings_lists import SettingsListEditorMixin
from Modules.lvs_cli_settings_menu import SettingsMenuPresenterMixin
from Modules.lvs_option_defaults import (
    DEFAULT_CASE_OPTIONS,
    DEFAULT_CPU_COOLER_OPTIONS,
    DEFAULT_PSU_RATING_OPTIONS,
)


class SettingsCliAdapter(SettingsAdvancedEditorMixin, SettingsListEditorMixin, SettingsMenuPresenterMixin):
    """CLI-only settings menus backed by the shared settings manager/facade."""

    def __init__(self, launcher: Any) -> None:
        self.launcher = launcher

    def __getattr__(self, name: str) -> Any:
        return getattr(self.launcher, name)

    def settings_menu(self) -> None:
        settings = self.settings_manager.settings
        self.print_settings_menu(settings)
        choice = self._input("Select: ").strip()
        if choice == "0":
            self.settings_environment_mode()
            return
        if self.apply_basic_settings_choice(choice, settings):
            pass
        elif choice == "12":
            if not self.settings_runtime_environment_overrides():
                return
        elif choice == "13":
            if not self.settings_gpu_target_thresholds():
                return
        elif choice == "14":
            if not self.settings_gpu_tuning_safeguards():
                return
        elif choice == "16":
            self.settings_profile_menu_groups()
            return
        elif choice == "17" and not self._feature_enabled("settings_inventory_lists"):
            return
        elif choice == "18" and self._feature_enabled("settings_inventory_lists"):
            self.settings_text_list(
                "Case/SKU List",
                "case_options",
                DEFAULT_CASE_OPTIONS,
            )
            return
        elif choice == "19" and self._feature_enabled("settings_inventory_lists"):
            self.settings_text_list(
                "PSU Rating List",
                "psu_rating_options",
                DEFAULT_PSU_RATING_OPTIONS,
            )
            return
        elif choice == "20" and self._feature_enabled("settings_inventory_lists"):
            self.settings_text_list(
                "CPU Cooler List",
                "cpu_cooler_options",
                DEFAULT_CPU_COOLER_OPTIONS,
            )
            return
        elif choice == "21":
            return
        self.settings_manager.save()
        self._reload_runtime_state()
        print("Settings saved.")

    def settings_environment_mode(self) -> None:
        settings = self.settings_manager.settings
        print("\nEnvironment Mode")
        print("1. Production - department workflow, inventory fields, Google Drive upload, and setup history")
        print("2. End User - simplified public-facing workflow without department-specific setup fields")
        raw = self._input(f"Choose environment mode [{self._environment_mode_label()}]: ").strip().lower()
        if not raw:
            return
        if raw in {"1", "production", "prod"}:
            settings.environment_mode = "production"
        elif raw in {"2", "end_user", "end-user", "user", "public"}:
            settings.environment_mode = "end_user"
        else:
            print("Invalid environment mode.")
            return
        self.settings_manager.save()
        self._reload_runtime_state()
        print(f"Environment mode saved: {self._environment_mode_label()}")
