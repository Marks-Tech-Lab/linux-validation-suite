from __future__ import annotations

"""Textual TUI settings adapter methods."""

from Modules.lvs_tui_input_state import tui_input_state
from Modules.lvs_tui_navigation_state import tui_navigation_reset
from Modules.lvs_tui_settings_list_presentation import (
    settings_input_presentation,
    settings_list_input_presentation,
    settings_list_presentation,
)


class TuiSettingsAdapterMixin:
    def _begin_settings_input(self, field: str) -> None:
        if field == "department":
            initial = str(self.service.settings.suite_department or "")
        else:
            initial = str(getattr(self.service.settings, field, ""))
        presentation = settings_input_presentation(
            field=field,
            label=self.service.settings_input_label(field),
            value=initial,
            summary=self.service.settings_summary_text(),
        )
        if presentation is None:
            return
        self._apply_input_state(
            tui_input_state(
                presentation.pending_field,
                value=presentation.value,
                placeholder=presentation.placeholder,
                detail=presentation.detail,
            )
        )

    async def _open_settings_list(self, list_key: str) -> None:
        self.setting_list_key = list_key
        self.setting_list_selected_index = 0
        await self._show_settings_list(list_key)

    async def _show_settings_list(self, list_key: str, detail: str = "") -> None:
        self.view_mode = "settings_list"
        self.setting_list_key = list_key
        self._apply_navigation_reset(
            tui_navigation_reset(
                clear_pending_input=False,
                clear_setting_list=False,
                clear_selected_profile=True,
                clear_selected_result=True,
                reset_input_widget=False,
            )
        )
        title = self.service.setting_text_list_title(list_key)
        values = self.service.setting_text_list(list_key)
        presentation = settings_list_presentation(
            title=title,
            values=values,
            selected_index=self.setting_list_selected_index,
            summary=self.service.setting_text_list_summary(list_key),
            detail=detail,
        )
        self.query_one("#sidebar-title").update(presentation.title)
        list_view = self.query_one("#items")
        self.setting_list_selected_index = presentation.selected_index if presentation.selected_index is not None else 0
        await self._replace_sidebar_labels(
            list_view,
            list(presentation.values),
            selected_index=presentation.selected_index,
            focus=True,
        )
        self._set_detail(presentation.detail)

    def _begin_settings_list_input(self, mode: str) -> None:
        if not self.setting_list_key:
            return
        values = self.service.setting_text_list(self.setting_list_key)
        title = self.service.setting_text_list_title(self.setting_list_key)
        presentation = settings_list_input_presentation(
            mode=mode,
            title=title,
            values=values,
            selected_index=self.setting_list_selected_index,
            summary=self.service.setting_text_list_summary(self.setting_list_key),
        )
        if presentation is None:
            return
        if presentation.selected_index is not None:
            self.setting_list_selected_index = presentation.selected_index
        self._apply_input_state(
            tui_input_state(
                presentation.pending_field,
                value=presentation.value,
                placeholder=presentation.placeholder,
                detail=presentation.detail,
            )
        )

    async def _delete_selected_settings_list_item(self) -> None:
        if not self.setting_list_key:
            return
        text = self.service.delete_setting_text_list_item(
            self.setting_list_key,
            self.setting_list_selected_index,
        )
        self.setting_list_selected_index = max(0, self.setting_list_selected_index - 1)
        await self._show_settings_list(self.setting_list_key, detail=text)

    async def _restore_settings_list_defaults(self) -> None:
        if not self.setting_list_key:
            return
        text = self.service.restore_setting_text_list_defaults(self.setting_list_key)
        self.setting_list_selected_index = 0
        await self._show_settings_list(self.setting_list_key, detail=text)

    async def _commit_settings_input(self, field: str, value: str) -> bool:
        if field == "__settings_department":
            self._set_detail(self.service.set_department_text(value))
            self._clear_setup_input(focus_items=True)
            return True
        if field.startswith("__settings_numeric:"):
            attr_name = field.split(":", 1)[1]
            self._set_detail(self.service.set_numeric_setting_text(attr_name, value))
            self._clear_setup_input(focus_items=True)
            return True
        if field == "__settings_list_add":
            list_key = self.setting_list_key or ""
            text = self.service.add_setting_text_list_item(list_key, value)
            self._clear_setup_input()
            await self._show_settings_list(list_key, detail=text)
            return True
        if field == "__settings_list_rename":
            list_key = self.setting_list_key or ""
            index = self.setting_list_selected_index
            text = self.service.rename_setting_text_list_item(list_key, index, value)
            self._clear_setup_input()
            await self._show_settings_list(list_key, detail=text)
            return True
        return False
