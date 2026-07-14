from __future__ import annotations

from typing import List


class RunSetupHardwareCompatibilityMixin:
    """Compatibility delegates for legacy launcher hardware metadata prompts."""

    def _select_case_sku(self, current: str = "") -> str:
        return self._run_setup_cli_adapter()._select_case_sku(current)

    def _enter_description(self, current: str = "") -> str:
        return self._run_setup_cli_adapter()._enter_description(current)

    def _enter_psu_wattage(self, current: str = "") -> str:
        return self._run_setup_cli_adapter()._enter_psu_wattage(current)

    def _select_psu_rating(self, current: str = "") -> str:
        return self._run_setup_cli_adapter()._select_psu_rating(current)

    def _enter_power_limit(self, current: str = "") -> str:
        return self._run_setup_cli_adapter()._enter_power_limit(current)

    def _select_cpu_cooler(self, current: str = "") -> str:
        return self._run_setup_cli_adapter()._select_cpu_cooler(current)

    def _enter_fan_type(self, current_type: str = "", current_details: str = "") -> tuple[str, str]:
        return self._run_setup_cli_adapter()._enter_fan_type(current_type, current_details)

    def _enter_fan_details(self, current: str = "") -> str:
        return self._run_setup_cli_adapter()._enter_fan_details(current)

    def _select_from_numbered_list(
        self,
        title: str,
        options: List[str],
        prompt: str,
        current: str = "",
    ) -> str:
        return self._run_setup_cli_adapter()._select_from_numbered_list(title, options, prompt, current=current)
