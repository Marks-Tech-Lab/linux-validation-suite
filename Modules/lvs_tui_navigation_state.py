"""Textual-free navigation reset specs for the optional TUI frontend."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TuiNavigationReset:
    clear_confirm_run: bool = True
    clear_pending_input: bool = True
    clear_setup_picker: bool = True
    clear_profile_edit_picker: bool = False
    clear_setting_list: bool = False
    clear_selected_profile: bool = False
    clear_selected_result: bool = False
    reset_input_widget: bool = True


def tui_navigation_reset(
    *,
    clear_confirm_run: bool = True,
    clear_pending_input: bool = True,
    clear_setup_picker: bool = True,
    clear_profile_edit_picker: bool = False,
    clear_setting_list: bool = False,
    clear_selected_profile: bool = False,
    clear_selected_result: bool = False,
    reset_input_widget: bool = True,
) -> TuiNavigationReset:
    return TuiNavigationReset(
        clear_confirm_run=bool(clear_confirm_run),
        clear_pending_input=bool(clear_pending_input),
        clear_setup_picker=bool(clear_setup_picker),
        clear_profile_edit_picker=bool(clear_profile_edit_picker),
        clear_setting_list=bool(clear_setting_list),
        clear_selected_profile=bool(clear_selected_profile),
        clear_selected_result=bool(clear_selected_result),
        reset_input_widget=bool(reset_input_widget),
    )
