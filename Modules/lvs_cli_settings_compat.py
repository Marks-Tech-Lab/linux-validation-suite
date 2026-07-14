from __future__ import annotations

from typing import Dict, List, Optional

from Modules.lvs_cli_settings import SettingsCliAdapter


class SettingsCompatibilityMixin:
    """Compatibility delegates for legacy launcher settings helper methods."""

    def _settings_cli_adapter(self) -> SettingsCliAdapter:
        adapter = getattr(self, "settings_cli", None)
        if adapter is None:
            adapter = SettingsCliAdapter(self)
            self.settings_cli = adapter
        return adapter

    def _settings_menu(self) -> None:
        self._settings_cli_adapter().settings_menu()

    def _settings_environment_mode(self) -> None:
        self._settings_cli_adapter().settings_environment_mode()

    def _settings_text_list(self, title: str, attr_name: str, defaults: List[str]) -> None:
        self._settings_cli_adapter().settings_text_list(title, attr_name, defaults)

    def _choose_text_list_index(self, values: List[str]) -> Optional[int]:
        return self._settings_cli_adapter().choose_text_list_index(values)

    def _settings_profile_menu_groups(self) -> None:
        self._settings_cli_adapter().settings_profile_menu_groups()

    def _choose_profile_menu_group_list_index(self, groups: List[Dict[str, str]]) -> Optional[int]:
        return self._settings_cli_adapter().choose_profile_menu_group_list_index(groups)
