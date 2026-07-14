from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any


class SettingsMenuPresenterMixin:
    """CLI settings menu rendering and basic setting mutations."""

    def settings_display_payload(self, settings: Any) -> dict[str, Any]:
        display_settings = asdict(settings)
        display_settings.pop("privileged_helper_enabled", None)
        display_settings.pop("privileged_helper_prompt_for_sudo", None)
        if self._environment_mode() == "end_user":
            for key in (
                "suite_department",
                "case_options",
                "psu_rating_options",
                "cpu_cooler_options",
                "google_drive_credentials_path",
                "google_drive_shared_drive_id",
                "google_drive_move_to_uploaded_on_success",
                "google_drive_prompt_after_run",
            ):
                if key in display_settings:
                    display_settings[key] = "(hidden in end-user mode)"
        return display_settings

    def print_settings_menu(self, settings: Any) -> None:
        print("\nCurrent settings:")
        print(json.dumps(self.settings_display_payload(settings), indent=2))
        print(
            "Enhanced telemetry is session-only and is chosen at suite launch; "
            "it is not saved in settings."
        )
        print("\n0. Change environment mode")
        print("1. Change sample interval")
        print("2. Change default trim start")
        print("3. Change default trim end")
        print("4. Toggle compatibility export")
        print("5. Toggle extended export")
        print("6. Toggle keep raw telemetry")
        print("7. Toggle post-run wall wattage prompt")
        print("8. Toggle abort on fail thresholds")
        print("9. Toggle abort on worker errors")
        print("10. Toggle abort on system faults")
        print("11. Toggle stop run after aborted stage")
        print("12. Edit runtime environment overrides")
        print("13. Edit target GPU utilization thresholds")
        print("14. Edit GPU tuning safeguards")
        print("15. Toggle strict threshold recommendation warnings")
        print("16. Edit profile menu groups")
        if self._feature_enabled("settings_inventory_lists"):
            print("17. Change suite department")
            print("18. Edit case/SKU list")
            print("19. Edit PSU rating list")
            print("20. Edit CPU cooler list")
            print("21. Back")
        else:
            print("17. Back")

    def apply_basic_settings_choice(self, choice: str, settings: Any) -> bool:
        if choice == "1":
            try:
                settings.sample_interval_seconds = float(self._input("New sample interval seconds: ").strip())
            except Exception:
                print("Invalid value.")
            return True
        if choice == "2":
            try:
                settings.trim_start_seconds = int(self._input("New trim start seconds: ").strip())
            except Exception:
                print("Invalid value.")
            return True
        if choice == "3":
            try:
                settings.trim_end_seconds = int(self._input("New trim end seconds: ").strip())
            except Exception:
                print("Invalid value.")
            return True
        if choice == "4":
            settings.export_compatibility_json = not settings.export_compatibility_json
            return True
        if choice == "5":
            settings.export_extended_json = not settings.export_extended_json
            return True
        if choice == "6":
            settings.keep_raw_telemetry = not settings.keep_raw_telemetry
            return True
        if choice == "7":
            settings.prompt_for_wall_wattage = not settings.prompt_for_wall_wattage
            return True
        if choice == "8":
            settings.abort_on_fail_threshold = not settings.abort_on_fail_threshold
            return True
        if choice == "9":
            settings.abort_on_worker_error = not settings.abort_on_worker_error
            return True
        if choice == "10":
            settings.abort_on_system_fault = not settings.abort_on_system_fault
            return True
        if choice == "11":
            settings.abort_run_on_stage_abort = not settings.abort_run_on_stage_abort
            return True
        if choice == "15":
            settings.strict_threshold_recommendation_warnings = not settings.strict_threshold_recommendation_warnings
            print(f"Strict threshold recommendation warnings: {settings.strict_threshold_recommendation_warnings}")
            return True
        if choice == "17" and self._feature_enabled("settings_inventory_lists"):
            raw = self._input(f"Suite department [{settings.suite_department}]: ").strip()
            if raw:
                settings.suite_department = raw
            return True
        return False
