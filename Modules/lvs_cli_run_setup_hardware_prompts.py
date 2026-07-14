from __future__ import annotations

from typing import List

from .lvs_cli_compat import BackRequested


class RunSetupHardwarePromptMixin:
    """CLI prompts for run setup hardware metadata."""

    def _select_case_sku(self, current: str = "") -> str:
        choice = self._select_from_numbered_list(
            "Select Case/SKU",
            self.settings_manager.settings.case_options,
            "Select case",
            current=current,
        )
        if choice.lower() == "oem":
            return self._input("Enter OEM SKU: ").strip() or "OEM"
        if "other" in choice.lower() or "custom" in choice.lower():
            return self._input("Enter custom case/SKU: ").strip() or "Other/Unclassifiable"
        return choice

    def _enter_description(self, current: str = "") -> str:
        raw = self._input(f"Description [{current or 'Test'}]: ").strip()
        return raw or current or "Test"

    def _enter_psu_wattage(self, current: str = "") -> str:
        raw = self._input(f"PSU wattage [{current or 'skip'}]: ").strip()
        if not raw:
            return current
        if raw.lower() in {"skip", "none", "-"}:
            return ""
        cleaned = raw.upper().rstrip("W").strip()
        try:
            value = float(cleaned)
            if value <= 0:
                raise ValueError
            return f"{int(value) if value.is_integer() else value:g}W"
        except Exception:
            print("Invalid wattage. Keeping current value.")
            return current

    def _select_psu_rating(self, current: str = "") -> str:
        choice = self._select_from_numbered_list(
            "PSU Rating",
            self.settings_manager.settings.psu_rating_options,
            "Select PSU rating",
            current=current,
        )
        return "" if choice.lower() == "skip" else choice

    def _enter_power_limit(self, current: str = "") -> str:
        print("\nPower Limit Configuration")
        vendors = ["Intel", "AMD", "Other/Unknown"]
        vendor = self._select_from_numbered_list("CPU Vendor", vendors, "Select CPU vendor")
        if vendor == "Intel":
            pl1 = self._input("Enter PL1 (Enter for Auto): ").strip() or "Auto"
            pl2 = "Auto"
            if pl1 != "Auto":
                pl2 = self._input("Enter PL2 (Enter for Auto): ").strip() or "Auto"
            turbo = "Auto"
            if pl1 != "Auto" or pl2 != "Auto":
                turbo = self._input("Enter Turbo Timer (Enter for Auto): ").strip() or "Auto"
            return "Auto" if pl1 == "Auto" and pl2 == "Auto" and turbo == "Auto" else f"PL1:{pl1}|PL2:{pl2}|Turbo:{turbo}"
        if vendor == "AMD":
            power = self._input("Enter Power Limit (Enter for Auto): ").strip()
            if not power:
                return "Auto"
            power_type = self._select_from_numbered_list(
                "AMD Power Limit Type",
                ["PPT", "TDP", "Other"],
                "Select type",
            )
            other = self._input("Enter Other info (Enter for N/A): ").strip() or "N/A"
            return f"(MB) {power}W-{power_type}" if other == "N/A" else f"(MB) {power}W-{power_type}|Other:{other}"
        raw = self._input(f"Power Limit [{current or 'Auto'}]: ").strip()
        return raw or current or "Auto"

    def _select_cpu_cooler(self, current: str = "") -> str:
        choice = self._select_from_numbered_list(
            "Select CPU Cooler",
            self.settings_manager.settings.cpu_cooler_options,
            "Select CPU cooler",
            current=current,
        )
        if choice.lower() == "skip":
            return ""
        desc = self._input("Enter CPU cooler description: ").strip()
        if not desc:
            print("Description empty. Using cooler type only.")
            return choice
        return f"{choice}-{desc}"

    def _enter_fan_type(self, current_type: str = "", current_details: str = "") -> tuple[str, str]:
        raw = self._input(f"Fan type [{current_type or 'skip'}, M for more details]: ").strip()
        if not raw:
            return current_type, current_details
        if raw.lower() == "m":
            return current_type, self._enter_fan_details(current_details)
        return raw, current_details

    def _enter_fan_details(self, current: str = "") -> str:
        raw = self._input(f"Fan details [{current or 'plain text, optional'}]: ").strip()
        return raw or current

    def _select_from_numbered_list(
        self,
        title: str,
        options: List[str],
        prompt: str,
        current: str = "",
    ) -> str:
        normalized = self._normalize_text_list(options, [])
        if not normalized:
            raise BackRequested()
        print(f"\n{title}")
        for index, option in enumerate(normalized, start=1):
            suffix = " [current]" if current and option.lower() == current.lower() else ""
            print(f"{index}. {option}{suffix}")
        raw = self._input(f"{prompt} (1-{len(normalized)}): ").strip()
        try:
            selection = int(raw) - 1
            if 0 <= selection < len(normalized):
                return normalized[selection]
        except Exception:
            pass
        print("Invalid selection.")
        return self._select_from_numbered_list(title, normalized, prompt, current=current)
