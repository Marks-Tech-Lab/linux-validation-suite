from __future__ import annotations

"""Textual TUI profile-edit adapter methods.

Profile mutation is handled by ``SuiteAppService``. This mixin owns the TUI
adapter flow around that service: sidebar rows, picker routing, input prompts,
and profile edit commit/cancel handling.
"""

from typing import Optional

from Modules.lvs_tui_input_state import tui_input_state
from Modules.lvs_tui_navigation_state import tui_navigation_reset
from Modules.lvs_tui_picker_presentation import TuiPickerOpenPresentation, profile_edit_picker_open_presentation
from Modules.lvs_tui_profile_edit_flow import (
    normalized_profile_edit_input_value,
    profile_edit_trim_start_value,
    selected_profile_edit_stage_index,
)
from Modules.lvs_tui_profile_edit_presentation import (
    profile_edit_description_input_presentation,
    profile_edit_failed_detail,
    profile_edit_name_input_presentation,
    profile_edit_presentation,
    profile_edit_stage_input_presentation,
    profile_edit_updated_detail,
    selected_stage_detail_text,
)


class TuiProfileEditAdapterMixin:
    async def _apply_profile_edit_picker_open_presentation(self, presentation: TuiPickerOpenPresentation) -> None:
        self.profile_edit_picker_key = presentation.key
        self.profile_edit_picker_options = list(presentation.options)
        self.profile_edit_picker_stage_index = presentation.stage_index
        await self._apply_picker_presentation(presentation.picker)

    async def _show_profile_edit(self, detail: str = "") -> None:
        if self.profile_edit is None:
            self._set_detail("Open a profile first.")
            return
        self.view_mode = "profile_edit"
        self.query_one("#sidebar-title").update("Profile Edit")
        list_view = self.query_one("#items")
        edit = self.profile_edit
        profile = edit.profile
        labels = self.service.normalize_profile_labels(profile, edit.labels)
        edit.labels = labels
        self.profile_edit_items = self.service.profile_edit_items(edit)
        presentation = profile_edit_presentation(
            self.profile_edit_items,
            self.profile_edit_selected_index,
            self.service.profile_edit_summary_text(edit),
            detail,
        )
        if presentation.selected_index is not None:
            self.profile_edit_selected_index = presentation.selected_index
        await self._replace_sidebar_labels(
            list_view,
            list(presentation.labels),
            selected_index=presentation.selected_index,
            focus=True,
        )
        self._set_detail(presentation.detail)

    async def _activate_profile_edit_item(self, index: int) -> None:
        if self.profile_edit is None or index < 0 or index >= len(self.profile_edit_items):
            return
        item = self.profile_edit_items[index]
        kind = item.kind
        self.profile_edit_discard_confirm = False
        if kind == "save":
            await self._save_profile_edit()
            return
        if kind == "name":
            self._begin_profile_name_input()
            return
        if kind == "group":
            selected = self.service.cycle_profile_menu_group(self.profile_edit)
            self.profile_edit_discard_confirm = False
            await self._show_profile_edit(f"Menu group changed to: {self.service.profile_loader.menu_group_label(selected)}")
            return
        if kind == "description":
            self._begin_profile_description_input()
            return
        if kind == "strict":
            value = self.service.cycle_profile_edit_strict_threshold_warnings(self.profile_edit)
            self.profile_edit_discard_confirm = False
            await self._show_profile_edit(f"Strict threshold warning setting changed to: {value}")
            return
        if kind == "add_template":
            await self._add_profile_stage_from_template(item.template_key or "cpu")
            return
        if kind == "stage":
            self._set_detail(selected_stage_detail_text(self.service.profile_edit_summary_text(self.profile_edit)))

    def _selected_profile_edit_stage_index(self) -> Optional[int]:
        return selected_profile_edit_stage_index(
            self.profile_edit_items,
            self.profile_edit_selected_index,
            edit_present=self.profile_edit is not None,
        )

    async def _add_profile_stage_from_template(self, template_key: str) -> None:
        if self.profile_edit is None:
            return
        stage, label = self.service.create_profile_stage_from_template(self.profile_edit.profile, template_key)
        self.profile_edit.labels = self.service.add_profile_stage_to_edit(
            self.profile_edit,
            stage,
            label,
        )
        self.profile_edit_selected_index = len(self.profile_edit_items)
        self.profile_edit_discard_confirm = False
        await self._show_profile_edit(f"Added stage: {label}")

    async def _save_profile_edit(self) -> None:
        if self.profile_edit is None:
            return
        try:
            path = self.profile_edit.profile_path
            message = self.service.save_profile_edit(self.profile_edit)
            self.profiles = self.service.list_profiles()
            self.profile_edit = self.service.create_profile_edit(path)
            self.profile_edit_discard_confirm = False
            await self._show_profile_edit(message)
        except Exception as exc:
            self._set_detail(f"Profile save failed:\n{exc}\n\n{self.service.profile_edit_summary_text(self.profile_edit)}")

    async def _cancel_profile_edit(self) -> None:
        if self.profile_edit is None:
            await self.action_show_profiles()
            return
        if self.profile_edit.dirty and not self.profile_edit_discard_confirm:
            self.profile_edit_discard_confirm = True
            self._set_detail(
                self.service.profile_edit_summary_text(self.profile_edit)
                + "\n\nUnsaved profile changes are present. Press Esc again to discard them, or press S to save."
            )
            return
        self.profile_edit = None
        self.profile_edit_items = []
        self.profile_edit_selected_index = 0
        self.profile_edit_discard_confirm = False
        await self.action_show_profiles()

    async def _remove_selected_profile_stage(self) -> None:
        if self.profile_edit is None:
            return
        index = self._selected_profile_edit_stage_index()
        if index is None:
            self._set_detail("Select a stage row first.")
            return
        try:
            self.profile_edit.labels = self.service.remove_profile_stage_from_edit(self.profile_edit, index)
            self.profile_edit_discard_confirm = False
            self.profile_edit_selected_index = max(0, self.profile_edit_selected_index - 1)
            await self._show_profile_edit(f"Removed stage {index + 1}.")
        except Exception as exc:
            self._set_detail(f"Unable to remove stage:\n{exc}")

    async def _toggle_selected_profile_stage(self) -> None:
        if self.profile_edit is None:
            return
        index = self._selected_profile_edit_stage_index()
        if index is None:
            self._set_detail("Select a stage row first.")
            return
        state = self.service.toggle_profile_edit_stage_enabled(self.profile_edit, index)
        self.profile_edit_discard_confirm = False
        await self._show_profile_edit(f"Stage {index + 1} is now {'enabled' if state else 'disabled'}.")

    async def _open_profile_stage_picker(self, key: str) -> None:
        if self.profile_edit is None:
            return
        index = self._selected_profile_edit_stage_index()
        if index is None:
            self._set_detail("Select a stage row first.")
            return
        try:
            spec = self.service.profile_stage_picker_spec(self.profile_edit, index, key)
        except Exception as exc:
            self._set_detail(str(exc))
            return
        await self._apply_profile_edit_picker_open_presentation(
            profile_edit_picker_open_presentation(
                spec,
                self.service.profile_edit_summary_text(self.profile_edit),
                stage_index=index,
            )
        )

    async def _select_profile_edit_picker_option(self, selected: str) -> None:
        if self.profile_edit is None or self.profile_edit_picker_key is None:
            return
        index = self.profile_edit_picker_stage_index
        if index is None or index < 0 or index >= len(self.profile_edit.profile.stages):
            await self._restore_profile_edit_sidebar()
            return
        key = self.profile_edit_picker_key
        try:
            changed = self.service.apply_profile_edit_picker(self.profile_edit, index, key, selected)
            self.profile_edit_discard_confirm = False
            await self._restore_profile_edit_sidebar(f"Stage {index + 1} updated: {changed}")
        except Exception as exc:
            await self._restore_profile_edit_sidebar(f"Profile edit failed: {exc}")

    async def _restore_profile_edit_sidebar(self, detail: str = "") -> None:
        self._apply_navigation_reset(
            tui_navigation_reset(
                clear_setup_picker=False,
                clear_profile_edit_picker=True,
                reset_input_widget=False,
            )
        )
        await self._show_profile_edit(detail)

    def _begin_profile_description_input(self) -> None:
        if self.profile_edit is None:
            return
        presentation = profile_edit_description_input_presentation(
            value=self.profile_edit.profile.menu_description,
            profile_summary=self.service.profile_edit_summary_text(self.profile_edit),
        )
        self._apply_input_state(
            tui_input_state(
                presentation.pending_field,
                value=presentation.value,
                placeholder=presentation.placeholder,
                detail=presentation.detail,
            )
        )

    def _begin_profile_name_input(self) -> None:
        if self.profile_edit is None:
            return
        presentation = profile_edit_name_input_presentation(
            value=self.profile_edit.profile.profile_name,
            profile_summary=self.service.profile_edit_summary_text(self.profile_edit),
        )
        self._apply_input_state(
            tui_input_state(
                presentation.pending_field,
                value=presentation.value,
                placeholder=presentation.placeholder,
                detail=presentation.detail,
            )
        )

    def _begin_profile_stage_input(self, field: str) -> None:
        if self.profile_edit is None:
            return
        index = self._selected_profile_edit_stage_index()
        if index is None:
            self._set_detail("Select a stage row first.")
            return
        try:
            spec = self.service.profile_stage_input_spec(self.profile_edit, index, field)
        except Exception as exc:
            message = str(exc)
            if message:
                self._set_detail(message)
            return
        self.pending_stage_index = index
        presentation = profile_edit_stage_input_presentation(
            spec=spec,
            profile_summary=self.service.profile_edit_summary_text(self.profile_edit),
        )
        self._apply_input_state(
            tui_input_state(
                presentation.pending_field,
                value=presentation.value,
                placeholder=presentation.placeholder,
                detail=presentation.detail,
            )
        )

    async def _commit_profile_edit_input(self, field: str, value: str) -> None:
        if self.profile_edit is None:
            self._clear_setup_input()
            return
        value = normalized_profile_edit_input_value(value)
        try:
            trim_start = profile_edit_trim_start_value(
                field,
                value,
                pending_stage_index=self.pending_stage_index,
            )
            if trim_start is not None:
                self.pending_trim_start = trim_start
                self._clear_setup_input()
                self._begin_profile_stage_input("trim_end")
                return
            self.service.apply_profile_edit_input(
                self.profile_edit,
                field,
                value,
                stage_index=self.pending_stage_index,
                trim_start=self.pending_trim_start,
            )
            if field == "__profile_stage_trim_end":
                self.pending_trim_start = None
            self.profile_edit_discard_confirm = False
            self.pending_stage_index = None
            self._clear_setup_input()
            self._focus_items()
            await self._show_profile_edit(profile_edit_updated_detail())
        except Exception as exc:
            self.pending_stage_index = None
            self._clear_setup_input()
            self._set_detail(
                profile_edit_failed_detail(
                    exc,
                    self.service.profile_edit_summary_text(self.profile_edit),
                )
            )
