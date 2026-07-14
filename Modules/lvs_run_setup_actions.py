#!/usr/bin/env python3
"""Run setup action and picker specifications."""

from __future__ import annotations

from typing import Callable, List, Optional

from .lvs_service_models import FrontendActionSpec, RunSetupState, SetupInputSpec, SetupPickerSpec


INPUT_LABELS = {
    "case_sku": "Case/SKU",
    "description": "Description",
    "heatsoak_minutes": "Heatsoak minutes",
    "psu_wattage": "PSU wattage",
    "power_limit_data": "Power limit",
    "cpu_cooler": "CPU cooler",
    "cpu_cooler_description": "CPU cooler description",
    "fan_type": "Fan type",
    "fan_details": "Fan details",
    "stage_duration": "Stage duration seconds",
    "trim_start": "Trim start seconds",
    "trim_end": "Trim end seconds",
    "segment_label": "Segment label",
}

PICKER_TITLES = {
    "case_sku": "Case/SKU",
    "psu_rating": "PSU rating",
    "cpu_cooler": "CPU cooler",
    "power_limit_vendor": "Power Limit",
    "power_limit_amd_type": "AMD Power Limit Type",
    "stage_override": "Stage Overrides",
    "stage_duration": "Stage Durations",
    "stage_toggle": "Toggle Stage Enabled",
    "segment_label": "Segment Labels",
}

SETUP_KEY_FIELDS = {
    "2": "description",
    "3": "heatsoak_minutes",
    "4": "psu_wattage",
    "8": "fan_type",
    "9": "fan_details",
}

PICKER_KEY_MAP = {
    "1": "case_sku",
    "5": "psu_rating",
    "7": "cpu_cooler",
}

SETUP_SPECIAL_ACTIONS = {
    "d": FrontendActionSpec("d", "toggle_debug_logging", label="toggle advanced debug logging"),
    "6": FrontendActionSpec("6", "power_limit_picker", label="edit power limit"),
    "o": FrontendActionSpec("o", "stage_override_picker", label="edit stage overrides"),
    "l": FrontendActionSpec("l", "segment_label_picker", label="edit segment labels"),
}

POWER_LIMIT_VENDOR_OPTIONS = ["Auto", "Intel", "AMD", "Other/Unknown"]
AMD_POWER_LIMIT_TYPE_OPTIONS = ["PPT", "TDP", "Other"]


def input_spec(
    field: str,
    *,
    label: str = "",
    blank_default: str = "",
    initial_value: str = "",
) -> SetupInputSpec:
    return SetupInputSpec(
        field=field,
        label=label or INPUT_LABELS.get(field, field),
        blank_default=blank_default,
        initial_value=initial_value,
    )


def picker_title(key: str) -> str:
    return PICKER_TITLES.get(key, key)


def picker_spec(
    key: str,
    options: List[str],
    *,
    title: str = "",
    current: str = "",
) -> SetupPickerSpec:
    return SetupPickerSpec(
        key=key,
        title=title or picker_title(key),
        options=list(options),
        current=current,
    )


def option_picker_spec(setup: RunSetupState, key: str, option_values: Callable[[str], List[str]]) -> SetupPickerSpec:
    current = str(getattr(setup.metadata, key, "") or "")
    return picker_spec(key, option_values(key), current=current)


def power_limit_vendor_picker_spec() -> SetupPickerSpec:
    return picker_spec("power_limit_vendor", list(POWER_LIMIT_VENDOR_OPTIONS))


def amd_power_limit_type_picker_spec() -> SetupPickerSpec:
    return picker_spec("power_limit_amd_type", list(AMD_POWER_LIMIT_TYPE_OPTIONS))


def input_field_for_key(key: str) -> str:
    return SETUP_KEY_FIELDS.get(str(key or ""), "")


def picker_key_for_key(key: str) -> str:
    return PICKER_KEY_MAP.get(str(key or ""), "")


def setup_action_for_key(key: str) -> FrontendActionSpec:
    normalized = str(key or "").lower()
    picker_key = picker_key_for_key(normalized)
    if picker_key:
        return FrontendActionSpec(normalized, "picker", picker_key)
    special = SETUP_SPECIAL_ACTIONS.get(normalized)
    if special is not None:
        return special
    input_field = input_field_for_key(normalized)
    if input_field:
        return FrontendActionSpec(normalized, "input", input_field)
    return FrontendActionSpec(normalized, "")


def setup_action_specs(
    setup: Optional[RunSetupState],
    *,
    production: bool,
    detail_provider: Callable[[Optional[RunSetupState], str], str],
) -> List[FrontendActionSpec]:
    actions: List[FrontendActionSpec] = []
    if production:
        actions.extend(
            [
                FrontendActionSpec("1", "picker", "case_sku", "Case/SKU", detail_provider(setup, "case_sku")),
            ]
        )
    actions.extend(
        [
            FrontendActionSpec("2", "input", "description", "Description", detail_provider(setup, "description")),
            FrontendActionSpec("3", "input", "heatsoak_minutes", "Heatsoak minutes", detail_provider(setup, "heatsoak_minutes")),
        ]
    )
    if production:
        actions.extend(
            [
                FrontendActionSpec("4", "input", "psu_wattage", "PSU wattage", detail_provider(setup, "psu_wattage")),
                FrontendActionSpec("5", "picker", "psu_rating", "PSU rating", detail_provider(setup, "psu_rating")),
                FrontendActionSpec("6", "power_limit_picker", label="Power limit", detail=detail_provider(setup, "power_limit_data")),
                FrontendActionSpec("7", "picker", "cpu_cooler", "CPU cooler", detail_provider(setup, "cpu_cooler")),
                FrontendActionSpec("8", "input", "fan_type", "Fan type", detail_provider(setup, "fan_type")),
                FrontendActionSpec("9", "input", "fan_details", "Fan details", detail_provider(setup, "fan_details")),
            ]
        )
    actions.extend(
        [
            FrontendActionSpec("o", "stage_override_picker", label="Stage durations / trim / enabled", detail=detail_provider(setup, "stage_overrides")),
            FrontendActionSpec("l", "segment_label_picker", label="Segment labels", detail=detail_provider(setup, "segment_labels")),
            FrontendActionSpec("h", "load_history", label="Load previous setup"),
            FrontendActionSpec("d", "toggle_debug_logging", label="Advanced debug logging", detail=detail_provider(setup, "advanced_debug_logging")),
            FrontendActionSpec("u", "run_selected", label="Review and run", detail=detail_provider(setup, "review_run")),
        ]
    )
    return actions
