#!/usr/bin/env python3
"""Run setup helpers shared by optional frontends."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .lvs_run_metadata import RunMetadata
from .lvs_service_models import (
    CycleSetupResult,
    FrontendActionSpec,
    RunSetupHistoryEntry,
    RunSetupState,
    SetupInputSpec,
    SetupPickerSpec,
)
from .lvs_run_setup_actions import (
    AMD_POWER_LIMIT_TYPE_OPTIONS,
    INPUT_LABELS,
    PICKER_KEY_MAP,
    PICKER_TITLES,
    POWER_LIMIT_VENDOR_OPTIONS,
    SETUP_KEY_FIELDS,
    SETUP_SPECIAL_ACTIONS,
    amd_power_limit_type_picker_spec as build_amd_power_limit_type_picker_spec,
    input_field_for_key as resolve_input_field_for_key,
    input_spec as build_input_spec,
    option_picker_spec as build_option_picker_spec,
    picker_key_for_key as resolve_picker_key_for_key,
    picker_spec as build_picker_spec,
    picker_title as resolve_picker_title,
    power_limit_vendor_picker_spec as build_power_limit_vendor_picker_spec,
    setup_action_for_key as build_setup_action_for_key,
    setup_action_specs as build_setup_action_specs,
)
from .lvs_run_setup_history_service import (
    apply_run_setup_history_entry as apply_history_entry,
    metadata_from_history,
    raw_run_setup_history as load_raw_run_setup_history,
    run_setup_history_entries as load_run_setup_history_entries,
    run_setup_history_path as history_path,
    run_setup_history_signature as history_signature,
    save_run_setup_history as write_run_setup_history,
)
from .lvs_run_setup_stages import (
    set_all_stage_trim as apply_all_stage_trim,
    set_segment_label as apply_segment_label,
    set_stage_duration as apply_stage_duration,
    stage_option_values as build_stage_option_values,
    stage_override_options as build_stage_override_options,
    toggle_stage_enabled as apply_toggle_stage_enabled,
)
from .lvs_run_setup_text import (
    run_setup_overview_text as render_run_setup_overview_text,
    run_setup_summary_text as render_run_setup_summary_text,
    setup_action_detail_text as render_setup_action_detail_text,
    setup_action_detail_value,
)


class RunSetupManager:
    """Non-interactive helpers for configuring a pending profile run."""

    INPUT_LABELS = INPUT_LABELS
    PICKER_TITLES = PICKER_TITLES
    SETUP_KEY_FIELDS = SETUP_KEY_FIELDS
    PICKER_KEY_MAP = PICKER_KEY_MAP
    SETUP_SPECIAL_ACTIONS = SETUP_SPECIAL_ACTIONS
    POWER_LIMIT_VENDOR_OPTIONS = POWER_LIMIT_VENDOR_OPTIONS
    AMD_POWER_LIMIT_TYPE_OPTIONS = AMD_POWER_LIMIT_TYPE_OPTIONS

    def __init__(
        self,
        settings_provider: Callable[[], Any],
        profile_loader: Any,
        environment_mode_label_provider: Callable[[], str],
    ) -> None:
        self.settings_provider = settings_provider
        self.profile_loader = profile_loader
        self.environment_mode_label_provider = environment_mode_label_provider

    @property
    def settings(self) -> Any:
        return self.settings_provider()

    def default_run_metadata(self, profile_path: Path, description: str = "") -> RunMetadata:
        profile = self.profile_loader.load_profile(profile_path)
        return RunMetadata(
            dept=str(self.settings.suite_department or "Production"),
            description=description or profile.profile_name,
        )

    def create_run_setup(self, profile_path: Path) -> RunSetupState:
        profile = self.profile_loader.load_profile(profile_path)
        labels = self.profile_loader.load_segment_labels(profile_path, profile)
        return RunSetupState(
            profile_path=profile_path,
            metadata=self.default_run_metadata(profile_path),
            profile=profile,
            labels=labels,
            heatsoak_minutes=0.0,
        )

    def run_setup_history_entries(self) -> List[RunSetupHistoryEntry]:
        return load_run_setup_history_entries(self.settings)

    def apply_run_setup_history_entry(self, setup: RunSetupState, entry: RunSetupHistoryEntry) -> None:
        apply_history_entry(self.settings, setup, entry)

    def raw_run_setup_history(self) -> List[Dict[str, Any]]:
        return load_raw_run_setup_history(self.settings)

    def run_setup_history_path(self) -> Path:
        return history_path(self.settings)

    def save_run_setup_history(
        self,
        profile_path: Path,
        profile: Any,
        metadata: RunMetadata,
        *,
        heatsoak_minutes: float = 0.0,
    ) -> None:
        write_run_setup_history(self.settings, profile_path, profile, metadata, heatsoak_minutes=heatsoak_minutes)

    def run_setup_history_signature(self, item: Dict[str, Any]) -> str:
        return history_signature(item)

    def _metadata_from_history(self, payload: dict[str, Any], fallback: RunMetadata) -> RunMetadata:
        return metadata_from_history(payload, fallback)

    def option_values(self, key: str) -> List[str]:
        if key == "case_sku":
            return list(self.settings.case_options)
        if key == "psu_rating":
            return list(self.settings.psu_rating_options)
        if key == "cpu_cooler":
            return list(self.settings.cpu_cooler_options)
        return []

    def input_spec(
        self,
        field: str,
        *,
        label: str = "",
        blank_default: str = "",
        initial_value: str = "",
    ) -> SetupInputSpec:
        return build_input_spec(
            field,
            label=label,
            blank_default=blank_default,
            initial_value=initial_value,
        )

    def picker_title(self, key: str) -> str:
        return resolve_picker_title(key)

    def picker_spec(
        self,
        key: str,
        options: List[str],
        *,
        title: str = "",
        current: str = "",
    ) -> SetupPickerSpec:
        return build_picker_spec(key, options, title=title, current=current)

    def option_picker_spec(self, setup: RunSetupState, key: str) -> SetupPickerSpec:
        return build_option_picker_spec(setup, key, self.option_values)

    def power_limit_vendor_picker_spec(self) -> SetupPickerSpec:
        return build_power_limit_vendor_picker_spec()

    def amd_power_limit_type_picker_spec(self) -> SetupPickerSpec:
        return build_amd_power_limit_type_picker_spec()

    def stage_override_picker_spec(self, setup: RunSetupState) -> SetupPickerSpec:
        return self.picker_spec("stage_override", self.stage_override_options(setup))

    def segment_label_picker_spec(self, setup: RunSetupState) -> SetupPickerSpec:
        return self.picker_spec("segment_label", self.stage_option_values(setup, "label"))

    def stage_duration_picker_spec(self, setup: RunSetupState) -> SetupPickerSpec:
        return self.picker_spec("stage_duration", self.stage_option_values(setup, "duration"))

    def stage_toggle_picker_spec(self, setup: RunSetupState) -> SetupPickerSpec:
        return self.picker_spec("stage_toggle", self.stage_option_values(setup, "toggle"))

    def input_field_for_key(self, key: str) -> str:
        return resolve_input_field_for_key(key)

    def picker_key_for_key(self, key: str) -> str:
        return resolve_picker_key_for_key(key)

    def setup_action_for_key(self, key: str) -> FrontendActionSpec:
        return build_setup_action_for_key(key)

    def setup_action_specs(self, setup: Optional[RunSetupState] = None) -> List[FrontendActionSpec]:
        production = self.environment_mode_label_provider() == "Production"
        return build_setup_action_specs(
            setup,
            production=production,
            detail_provider=self._setup_action_detail,
        )

    def setup_action_detail_text(self, setup: RunSetupState, action: FrontendActionSpec) -> str:
        return render_setup_action_detail_text(setup, action, self.option_values)

    def _setup_action_detail(self, setup: Optional[RunSetupState], key: str) -> str:
        return setup_action_detail_value(setup, key)

    def cycle_setup_option(self, setup: RunSetupState, key: str) -> str:
        return self.cycle_setup_option_result(setup, key).selected

    def cycle_setup_option_result(self, setup: RunSetupState, key: str) -> CycleSetupResult:
        values = self.option_values(key)
        if not values:
            return CycleSetupResult("")
        current = str(getattr(setup.metadata, key, "") or "")
        current_index = -1
        for index, value in enumerate(values):
            if value.lower() == current.lower():
                current_index = index
                break
        selected = values[(current_index + 1) % len(values)]
        return self.select_setup_option_result(setup, key, selected)

    def select_setup_option_result(self, setup: RunSetupState, key: str, selected: str) -> CycleSetupResult:
        selected = re.sub(r"\s+", " ", str(selected or "").strip())
        if not selected:
            return CycleSetupResult("")
        if key == "psu_rating" and selected.lower() == "skip":
            setup.metadata.psu_rating = ""
            return CycleSetupResult("")

        if key == "case_sku":
            lower = selected.lower()
            if lower == "oem":
                setup.metadata.case_sku = "OEM"
                return CycleSetupResult(
                    selected="OEM",
                    requires_text=True,
                    text_field="case_sku",
                    prompt="OEM SKU",
                    blank_default="OEM",
                )
            if "other" in lower or "custom" in lower:
                setup.metadata.case_sku = "Other/Unclassifiable"
                return CycleSetupResult(
                    selected="Other/Unclassifiable",
                    requires_text=True,
                    text_field="case_sku",
                    prompt="custom case/SKU",
                    blank_default="Other/Unclassifiable",
                )

        if key == "cpu_cooler":
            lower = selected.lower()
            if lower == "skip":
                setup.metadata.cpu_cooler = ""
                return CycleSetupResult("")
            setup.metadata.cpu_cooler = "Other" if "other" in lower or "custom" in lower else selected
            return CycleSetupResult(
                selected=setup.metadata.cpu_cooler,
                requires_text=True,
                text_field="cpu_cooler_description",
                prompt="CPU cooler description (Enter to use selected type only)",
                blank_default="",
            )

        setattr(setup.metadata, key, selected)
        return CycleSetupResult(selected)

    def set_setup_field(self, setup: RunSetupState, key: str, value: str) -> None:
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if key == "heatsoak_minutes":
            if not text:
                return
            try:
                setup.heatsoak_minutes = max(0.0, min(24.0 * 60.0, float(text or "0")))
            except Exception:
                pass
            return
        if key == "psu_wattage":
            if not text:
                return
            if text.lower() in {"skip", "none", "-"}:
                setup.metadata.psu_wattage = ""
                setup.metadata.psu_rating = ""
                return
            cleaned = text.upper().rstrip("W").strip()
            try:
                value_float = float(cleaned)
                if value_float <= 0:
                    raise ValueError
                setup.metadata.psu_wattage = f"{int(value_float) if value_float.is_integer() else value_float:g}W"
            except Exception:
                setup.metadata.psu_wattage = text
            return
        if key == "cpu_cooler_description":
            base = str(setup.metadata.cpu_cooler or "").strip()
            if not text:
                return
            setup.metadata.cpu_cooler = f"{base}-{text}" if base else text
            return
        if key == "description":
            if text:
                setup.metadata.description = text
            return
        if key == "fan_type":
            if text:
                setup.metadata.fan_type = text
            return
        if key == "fan_details":
            if text:
                setup.metadata.fan_details = text
            return
        if key == "power_limit_data":
            setup.metadata.power_limit_data = text or setup.metadata.power_limit_data or "Auto"
            return
        if hasattr(setup.metadata, key):
            setattr(setup.metadata, key, text)

    def finalize_run_metadata(self, setup: RunSetupState) -> RunMetadata:
        profile = setup.profile
        metadata = setup.metadata
        if not str(metadata.case_sku or "").strip():
            metadata.case_sku = "Unknown"
        if not str(metadata.description or "").strip():
            metadata.description = profile.profile_name
        if not str(metadata.dept or "").strip():
            metadata.dept = str(self.settings.suite_department or "Production")
        return metadata

    def toggle_advanced_debug_logging(self, setup: RunSetupState) -> bool:
        setup.metadata.advanced_debug_logging = not bool(setup.metadata.advanced_debug_logging)
        return bool(setup.metadata.advanced_debug_logging)

    def run_setup_summary_text(self, setup: RunSetupState) -> str:
        mode_label = self.environment_mode_label_provider()
        return render_run_setup_summary_text(
            setup,
            mode_label=mode_label,
            suite_department=self.settings.suite_department,
            production=mode_label == "Production",
        )

    def run_setup_overview_text(self, setup: RunSetupState) -> str:
        mode_label = self.environment_mode_label_provider()
        return render_run_setup_overview_text(
            setup,
            mode_label=mode_label,
            suite_department=self.settings.suite_department,
            production=mode_label == "Production",
        )

    def stage_override_options(self, setup: RunSetupState) -> List[str]:
        return build_stage_override_options(setup)

    def stage_option_values(self, setup: RunSetupState, mode: str) -> List[str]:
        return build_stage_option_values(setup, mode)

    def set_stage_duration(self, setup: RunSetupState, stage_index: int, raw_seconds: str) -> None:
        apply_stage_duration(setup, stage_index, raw_seconds)

    def set_all_stage_trim(self, setup: RunSetupState, start_seconds: int, end_seconds: int) -> None:
        apply_all_stage_trim(setup, start_seconds, end_seconds)

    def toggle_stage_enabled(self, setup: RunSetupState, stage_index: int) -> None:
        apply_toggle_stage_enabled(setup, stage_index)

    def set_segment_label(self, setup: RunSetupState, stage_index: int, label: str) -> None:
        apply_segment_label(setup, stage_index, label)
