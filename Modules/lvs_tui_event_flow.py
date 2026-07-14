from __future__ import annotations

"""Frontend-neutral helpers for TUI event routing."""

from typing import Any, Sequence

from Modules.lvs_tui_input_state import tui_input_reset_state


BUTTON_ACTIONS = {
    "profiles": "show_profiles",
    "dry-run": "dry_run",
    "deps": "dependency_check",
    "new-profile": "new_profile",
    "setup": "setup_run",
    "edit-profile": "edit_profile",
    "history": "setup_history",
    "run": "run_selected",
    "results": "show_results",
    "settings": "show_settings",
    "refresh": "refresh",
    "upload": "upload_last_result",
    "wall-wattage": "edit_wall_wattage",
    "back": "cancel_setup_input",
    "esc-back": "cancel_setup_input",
    "cancel": "cancel_setup_input",
    "quit": "quit",
}

ESCAPE_CANCEL_VIEW_MODES = {
    "setup_picker",
    "post_run_upload_picker",
    "profile_edit_picker",
    "setup_history",
    "setup_history_prompt",
    "setup_history_confirm",
}

STAGE_INPUT_FIELDS = {"stage_duration", "trim_start", "trim_end", "segment_label"}


def button_action(button_id: object) -> str:
    value = str(button_id or "")
    if value.startswith("global-"):
        value = value.removeprefix("global-")
    return BUTTON_ACTIONS.get(value, "")


def selected_index(event: Any) -> int | None:
    index = getattr(getattr(event, "list_view", None), "index", None)
    return index if isinstance(index, int) else None


def index_in_range(index: int | None, items: Sequence[Any]) -> bool:
    return index is not None and 0 <= index < len(items)


def event_key(event: Any) -> str:
    return str(getattr(event, "key", "") or "")


def is_escape_key(event: Any) -> bool:
    return event_key(event) == "escape"


def view_uses_escape_cancel(view_mode: object) -> bool:
    return str(view_mode or "") in ESCAPE_CANCEL_VIEW_MODES


def pending_input_route(field: object) -> str:
    value = str(field or "")
    if not value:
        return ""
    if value == "__post_wall_wattage":
        return "post_wall_wattage"
    if value == "__post_upload_prompt":
        return "post_upload_prompt"
    if value.startswith("__settings_"):
        return "settings"
    if value.startswith("__profile_"):
        return "profile_edit"
    if value.startswith("power_limit_"):
        return "power_limit"
    if value in STAGE_INPUT_FIELDS:
        return "stage_input"
    if value == "fan_type":
        return "fan_type"
    return "run_setup"


def setup_input_value(raw_value: str, blank_default: str) -> str:
    value = str(raw_value or "")
    if not value.strip() and blank_default:
        return blank_default
    return value


def setup_input_reset_state():
    return tui_input_reset_state()
