#!/usr/bin/env python3
"""Settings-facing service helpers for optional UI frontends."""

from __future__ import annotations

import json
import re
from typing import Any, Callable, List

from .lvs_option_defaults import (
    DEFAULT_CASE_OPTIONS,
    DEFAULT_CPU_COOLER_OPTIONS,
    DEFAULT_PROFILE_MENU_GROUPS,
    DEFAULT_PSU_RATING_OPTIONS,
)
from .lvs_profile_loader import ProfileLoader
from .lvs_service_models import FrontendActionSpec


class SettingsFacade:
    """Text and mutation helpers for frontend-visible suite settings."""

    SETTINGS_ACTIONS = {
        "e": FrontendActionSpec("e", "toggle_environment", label="toggle Production / End User mode"),
        "b": FrontendActionSpec("b", "input", "department", "edit department"),
        "1": FrontendActionSpec("1", "input", "sample_interval_seconds", "edit sample interval"),
        "i": FrontendActionSpec("i", "input", "sample_interval_seconds", "edit sample interval"),
        "2": FrontendActionSpec("2", "input", "trim_start_seconds", "edit default trim start"),
        "3": FrontendActionSpec("3", "input", "trim_end_seconds", "edit default trim end"),
        "4": FrontendActionSpec("4", "toggle_bool", "export_compatibility_json", "toggle compatibility export"),
        "5": FrontendActionSpec("5", "toggle_bool", "export_extended_json", "toggle extended export"),
        "6": FrontendActionSpec("6", "toggle_bool", "keep_raw_telemetry", "toggle keep raw telemetry"),
        "7": FrontendActionSpec("7", "toggle_bool", "prompt_for_wall_wattage", "toggle post-run wall wattage prompt"),
        "8": FrontendActionSpec("8", "toggle_bool", "abort_on_fail_threshold", "toggle abort on fail thresholds"),
        "9": FrontendActionSpec("9", "toggle_bool", "abort_on_worker_error", "toggle abort on worker errors"),
        "0": FrontendActionSpec("0", "toggle_bool", "abort_run_on_stage_abort", "toggle stop after aborted stage"),
        "n": FrontendActionSpec("n", "toggle_bool", "strict_threshold_recommendation_warnings", "toggle strict threshold recommendation warnings"),
        "g": FrontendActionSpec("g", "toggle_bool", "google_drive_prompt_after_run", "toggle Google Drive prompt after run"),
        "u": FrontendActionSpec("u", "toggle_bool", "google_drive_move_to_uploaded_on_success", "toggle move to Uploaded after upload"),
        "a": FrontendActionSpec("a", "settings_list", "case_options", "edit Case/SKU list"),
        "y": FrontendActionSpec("y", "settings_list", "psu_rating_options", "edit PSU rating list"),
        "k": FrontendActionSpec("k", "settings_list", "cpu_cooler_options", "edit CPU cooler list"),
        "m": FrontendActionSpec("m", "google_drive_readiness", label="check Google Drive readiness"),
    }
    SETTINGS_INPUT_LABELS = {
        "department": "Department",
        "sample_interval_seconds": "Sample interval seconds",
        "trim_start_seconds": "Default trim start seconds",
        "trim_end_seconds": "Default trim end seconds",
    }
    SETTINGS_LIST_ACTIONS = {
        "escape": FrontendActionSpec("escape", "cancel", label="return to settings"),
        "a": FrontendActionSpec("a", "input", "add", "add list item"),
        "n": FrontendActionSpec("n", "input", "rename", "rename selected list item"),
        "enter": FrontendActionSpec("enter", "input", "rename", "rename selected list item"),
        "delete": FrontendActionSpec("delete", "delete", label="delete selected list item"),
        "f": FrontendActionSpec("f", "restore_defaults", label="restore list defaults"),
    }

    def __init__(
        self,
        settings_manager: Any,
        reload_callback: Callable[[], None],
        google_readiness_provider: Callable[[], dict[str, Any]],
        environment_mode_label_provider: Callable[[], str],
        normalize_text_list: Callable[[List[str], List[str]], List[str]],
    ) -> None:
        self.settings_manager = settings_manager
        self.reload_callback = reload_callback
        self.google_readiness_provider = google_readiness_provider
        self.environment_mode_label_provider = environment_mode_label_provider
        self.normalize_text_list = normalize_text_list

    @property
    def settings(self) -> Any:
        return self.settings_manager.settings

    def settings_summary_text(self) -> str:
        drive = self.google_readiness_provider()
        missing = ", ".join(str(item) for item in drive.get("missing") or []) or "none"
        return "\n".join(
            [
                "Settings",
                "========",
                f"Mode: {self.environment_mode_label_provider()}",
                f"Department: {self.settings.suite_department or 'Production'}",
                f"Profiles dir: {self.settings.profiles_dir}",
                f"Results dir: {self.settings.results_dir}",
                f"Sample interval: {self.settings.sample_interval_seconds}s",
                f"Default trim: start {self.settings.trim_start_seconds}s, end {self.settings.trim_end_seconds}s",
                f"Compatibility export: {bool(self.settings.export_compatibility_json)}",
                f"Extended export: {bool(self.settings.export_extended_json)}",
                f"Keep raw telemetry: {bool(self.settings.keep_raw_telemetry)}",
                f"Prompt wall wattage after run: {bool(self.settings.prompt_for_wall_wattage)}",
                f"Abort on fail thresholds: {bool(self.settings.abort_on_fail_threshold)}",
                f"Abort on worker errors: {bool(self.settings.abort_on_worker_error)}",
                f"Abort on system faults: {bool(self.settings.abort_on_system_fault)}",
                f"Stop run after aborted stage: {bool(self.settings.abort_run_on_stage_abort)}",
                f"Strict threshold recommendation warnings: {bool(self.settings.strict_threshold_recommendation_warnings)}",
                f"Prompt Google Drive upload after run: {bool(self.settings.google_drive_prompt_after_run)}",
                f"Move uploaded results to Uploaded/: {bool(self.settings.google_drive_move_to_uploaded_on_success)}",
                f"Google Drive ready: {bool(drive.get('ready'))}",
                f"Google Drive missing: {missing}",
                f"Google Drive credential path: {self.settings.google_drive_credentials_path or '-'}",
                f"Google Drive shared drive ID: {'configured' if self.settings.google_drive_shared_drive_id else 'missing'}",
                "Advanced debug logging: configured per run in Run Setup (D)",
                "",
                "TUI Settings actions:",
                "- E toggle Production / End User mode",
                "- B edit department",
                "- I or 1 edit sample interval",
                "- 2 edit default trim start",
                "- 3 edit default trim end",
                "- 4 toggle compatibility export",
                "- 5 toggle extended export",
                "- 6 toggle keep raw telemetry",
                "- 7 toggle post-run wall wattage prompt",
                "- 8 toggle abort on fail thresholds",
                "- 9 toggle abort on worker errors",
                "- 0 toggle stop after aborted stage",
                "- N toggle strict threshold recommendation warnings",
                "- G toggle Google Drive upload prompt after run",
                "- U toggle move successful uploads to Uploaded/",
                "- A edit Case/SKU list",
                "- Y edit PSU rating list",
                "- K edit CPU cooler list",
                "- M check Google Drive readiness",
                "",
                "Use the CLI Settings menu for runtime environment overrides, GPU thresholds, "
                "GPU tuning safeguards, and profile menu group editing.",
            ]
        )

    def toggle_environment_mode_text(self) -> str:
        current = str(self.settings.environment_mode or "production").strip().lower()
        self.settings.environment_mode = "end_user" if current == "production" else "production"
        self.settings_manager.save()
        self.reload_callback()
        return self.settings_summary_text()

    def set_department_text(self, value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if text:
            self.settings.suite_department = text
            self.settings_manager.save()
            self.reload_callback()
        return self.settings_summary_text()

    def set_numeric_setting_text(self, attr_name: str, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return self.settings_summary_text()
        numeric_attrs = {
            "sample_interval_seconds": float,
            "trim_start_seconds": int,
            "trim_end_seconds": int,
        }
        caster = numeric_attrs.get(attr_name)
        if caster is None or not hasattr(self.settings, attr_name):
            return self.settings_summary_text()
        try:
            parsed = caster(float(text)) if caster is int else caster(text)
            if attr_name == "sample_interval_seconds":
                parsed = max(0.1, float(parsed))
            else:
                parsed = max(0, int(parsed))
            setattr(self.settings, attr_name, parsed)
            self.settings_manager.save()
            self.reload_callback()
        except Exception:
            pass
        return self.settings_summary_text()

    def toggle_bool_setting_text(self, attr_name: str) -> str:
        if hasattr(self.settings, attr_name):
            setattr(self.settings, attr_name, not bool(getattr(self.settings, attr_name)))
            self.settings_manager.save()
            self.reload_callback()
        return self.settings_summary_text()

    def apply_runtime_environment_overrides(self, raw: str) -> dict[str, str]:
        text = str(raw or "").strip()
        if not text:
            self.settings.runtime_environment = {}
            return {}
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("runtime environment must be a JSON object")
        runtime_environment = {
            str(key): str(value)
            for key, value in parsed.items()
            if str(key).strip()
        }
        self.settings.runtime_environment = runtime_environment
        return runtime_environment

    def set_runtime_environment_overrides_text(self, raw: str) -> str:
        self.apply_runtime_environment_overrides(raw)
        self.settings_manager.save()
        self.reload_callback()
        return self.settings_summary_text()

    def apply_gpu_target_thresholds(self, values: dict[str, str]) -> None:
        mapping = {
            "target_gpu_busy_min_percent": ("target_gpu_busy_min_percent", float, 0.0, None),
            "target_gpu_busy_sustain_seconds": ("target_gpu_busy_sustain_seconds", float, 0.0, None),
            "target_gpu_memory_busy_min_percent": ("target_gpu_memory_busy_min_percent", float, 0.0, None),
            "target_gpu_memory_busy_sustain_seconds": ("target_gpu_memory_busy_sustain_seconds", float, 0.0, None),
        }
        for key, (attr_name, caster, minimum, maximum) in mapping.items():
            self._apply_optional_numeric(values.get(key, ""), attr_name, caster, minimum, maximum)

    def set_gpu_target_thresholds_text(self, values: dict[str, str]) -> str:
        self.apply_gpu_target_thresholds(values)
        self.settings_manager.save()
        self.reload_callback()
        return self.settings_summary_text()

    def apply_gpu_safe_mode_settings(self, values: dict[str, str]) -> None:
        raw_safe_mode = str(values.get("gpu_safe_mode", "") or "").strip().lower()
        if raw_safe_mode in {"y", "yes"}:
            self.settings.gpu_safe_mode = True
        elif raw_safe_mode in {"n", "no"}:
            self.settings.gpu_safe_mode = False
        mapping = {
            "gpu_retune_warmup_seconds": ("gpu_retune_warmup_seconds", float, 0.0, None),
            "gpu_retune_cooldown_seconds": ("gpu_retune_cooldown_seconds", float, 0.0, None),
            "gpu_max_retunes_per_worker": ("gpu_max_retunes_per_worker", int, 0, None),
            "gpu_internal_ramp_step_seconds": ("gpu_internal_ramp_step_seconds", float, 0.0, None),
            "gpu_safe_start_load_fraction": ("gpu_safe_start_load_fraction", float, 0.15, 1.0),
            "gpu_safe_max_tuning_step": ("gpu_safe_max_tuning_step", int, 0, None),
            "gpu_safe_max_load_scale": ("gpu_safe_max_load_scale", float, 0.75, None),
            "gpu_safe_max_vram_percent": ("gpu_safe_max_vram_percent", float, 10.0, 100.0),
            "gpu_external_max_processes": ("gpu_external_max_processes", int, 1, None),
        }
        for key, (attr_name, caster, minimum, maximum) in mapping.items():
            self._apply_optional_numeric(values.get(key, ""), attr_name, caster, minimum, maximum)

    def set_gpu_safe_mode_settings_text(self, values: dict[str, str]) -> str:
        self.apply_gpu_safe_mode_settings(values)
        self.settings_manager.save()
        self.reload_callback()
        return self.settings_summary_text()

    def google_drive_readiness_text(self) -> str:
        status = self.google_readiness_provider()
        modules = status.get("python_modules") if isinstance(status.get("python_modules"), dict) else {}
        missing = ", ".join(str(item) for item in status.get("missing") or []) or "none"
        lines = [
            "Google Drive Upload Readiness",
            "=============================",
            f"Credentials: {'OK' if status.get('credential_exists') else 'missing'}",
            f"Credential path: {status.get('credential_path') or '-'}",
            f"Shared Drive ID: {'configured' if status.get('shared_drive_id_configured') else 'missing'}",
            f"Google DNS: {'OK' if status.get('dns_ok') else 'missing'}",
            "Python Google API modules:",
        ]
        for name, available in modules.items():
            lines.append(f"  - {name}: {'OK' if available else 'missing'}")
        lines.extend(
            [
                f"Ready: {'yes' if status.get('ready') else 'no'}",
                f"Missing: {missing}",
            ]
        )
        if status.get("dns_error"):
            lines.append(f"DNS error: {status.get('dns_error')}")
        return "\n".join(lines)

    def settings_action_for_key(self, key: str) -> FrontendActionSpec:
        return self.SETTINGS_ACTIONS.get(str(key or "").lower(), FrontendActionSpec(str(key or ""), ""))

    def settings_list_action_for_key(self, key: str) -> FrontendActionSpec:
        normalized = str(key or "").lower()
        return self.SETTINGS_LIST_ACTIONS.get(normalized, FrontendActionSpec(normalized, ""))

    def settings_input_label(self, field: str) -> str:
        return self.SETTINGS_INPUT_LABELS.get(field, field)

    def setting_text_list(self, list_key: str) -> List[str]:
        attr_name, defaults = self._setting_text_list_spec(list_key)
        return self.normalize_text_list(getattr(self.settings, attr_name), defaults)

    def setting_text_list_summary(self, list_key: str) -> str:
        title = self.setting_text_list_title(list_key)
        values = self.setting_text_list(list_key)
        lines = [
            title,
            "=" * len(title),
            "",
            "Actions: A add, N rename selected, Delete remove selected, F restore defaults, Esc back.",
            "",
        ]
        for index, item in enumerate(values, start=1):
            lines.append(f"{index}. {item}")
        return "\n".join(lines)

    def setting_text_list_title(self, list_key: str) -> str:
        if list_key == "case_options":
            return "Case/SKU List"
        if list_key == "psu_rating_options":
            return "PSU Rating List"
        if list_key == "cpu_cooler_options":
            return "CPU Cooler List"
        return "Settings List"

    def add_setting_text_list_item(self, list_key: str, value: str) -> str:
        attr_name, defaults = self._setting_text_list_spec(list_key)
        values = self.setting_text_list(list_key)
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if text:
            values.append(text)
            setattr(self.settings, attr_name, self.normalize_text_list(values, defaults))
            self.settings_manager.save()
            self.reload_callback()
        return self.setting_text_list_summary(list_key)

    def rename_setting_text_list_item(self, list_key: str, index: int, value: str) -> str:
        attr_name, defaults = self._setting_text_list_spec(list_key)
        values = self.setting_text_list(list_key)
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if 0 <= index < len(values) and text:
            values[index] = text
            setattr(self.settings, attr_name, self.normalize_text_list(values, defaults))
            self.settings_manager.save()
            self.reload_callback()
        return self.setting_text_list_summary(list_key)

    def delete_setting_text_list_item(self, list_key: str, index: int) -> str:
        attr_name, defaults = self._setting_text_list_spec(list_key)
        values = self.setting_text_list(list_key)
        if 0 <= index < len(values):
            del values[index]
            setattr(self.settings, attr_name, self.normalize_text_list(values, defaults))
            self.settings_manager.save()
            self.reload_callback()
        return self.setting_text_list_summary(list_key)

    def restore_setting_text_list_defaults(self, list_key: str) -> str:
        attr_name, defaults = self._setting_text_list_spec(list_key)
        setattr(self.settings, attr_name, list(defaults))
        self.settings_manager.save()
        self.reload_callback()
        return self.setting_text_list_summary(list_key)

    def _setting_text_list_spec(self, list_key: str) -> tuple[str, List[str]]:
        if list_key == "case_options":
            return "case_options", DEFAULT_CASE_OPTIONS
        if list_key == "psu_rating_options":
            return "psu_rating_options", DEFAULT_PSU_RATING_OPTIONS
        if list_key == "cpu_cooler_options":
            return "cpu_cooler_options", DEFAULT_CPU_COOLER_OPTIONS
        raise ValueError(f"unknown settings list: {list_key}")

    def profile_menu_groups(self) -> list[dict[str, str]]:
        self.settings.profile_menu_groups = ProfileLoader.normalize_menu_groups(self.settings.profile_menu_groups)
        return self.settings.profile_menu_groups

    def add_profile_menu_group(self, raw_key: str, label: str) -> dict[str, str]:
        if not str(raw_key or "").strip():
            raise ValueError("Group key required.")
        current = self.profile_menu_groups()
        entry = ProfileLoader.normalize_menu_group_entry(raw_key, label)
        existing = {item["key"] for item in current}
        if entry["key"] in existing:
            raise ValueError("That group key already exists. Rename its label instead.")
        current.append(entry)
        self.settings.profile_menu_groups = current
        return entry

    def rename_profile_menu_group(self, index: int, label: str) -> dict[str, str] | None:
        current = self.profile_menu_groups()
        if index < 0 or index >= len(current):
            raise IndexError("Invalid group number.")
        text = str(label or "").strip()
        if not text:
            return None
        entry = ProfileLoader.normalize_menu_group_entry(current[index]["key"], text)
        current[index] = entry
        self.settings.profile_menu_groups = current
        return entry

    def delete_profile_menu_group(self, index: int) -> dict[str, str]:
        current = self.profile_menu_groups()
        if index < 0 or index >= len(current):
            raise IndexError("Invalid group number.")
        removed = current[index]
        del current[index]
        self.settings.profile_menu_groups = ProfileLoader.normalize_menu_groups(current)
        return removed

    def restore_profile_menu_group_defaults(self) -> list[dict[str, str]]:
        self.settings.profile_menu_groups = [dict(item) for item in DEFAULT_PROFILE_MENU_GROUPS]
        return self.settings.profile_menu_groups

    def add_profile_menu_group_text(self, raw_key: str, label: str) -> str:
        self.add_profile_menu_group(raw_key, label)
        self.settings_manager.save()
        self.reload_callback()
        return self.profile_menu_group_summary_text()

    def rename_profile_menu_group_text(self, index: int, label: str) -> str:
        self.rename_profile_menu_group(index, label)
        self.settings_manager.save()
        self.reload_callback()
        return self.profile_menu_group_summary_text()

    def delete_profile_menu_group_text(self, index: int) -> str:
        self.delete_profile_menu_group(index)
        self.settings_manager.save()
        self.reload_callback()
        return self.profile_menu_group_summary_text()

    def restore_profile_menu_group_defaults_text(self) -> str:
        self.restore_profile_menu_group_defaults()
        self.settings_manager.save()
        self.reload_callback()
        return self.profile_menu_group_summary_text()

    def profile_menu_group_summary_text(self) -> str:
        lines = ["Profile Menu Groups", "===================", ""]
        for index, item in enumerate(self.profile_menu_groups(), start=1):
            lines.append(f"{index}. {item['label']} ({item['key']})")
        return "\n".join(lines)

    def _apply_optional_numeric(
        self,
        raw: str,
        attr_name: str,
        caster: Callable[[Any], Any],
        minimum: float | int,
        maximum: float | int | None,
    ) -> None:
        text = str(raw or "").strip()
        if not text:
            return
        if caster is int:
            value = int(text)
        else:
            value = float(text)
        if value < minimum:
            value = minimum
        if maximum is not None and value > maximum:
            value = maximum
        setattr(self.settings, attr_name, value)
