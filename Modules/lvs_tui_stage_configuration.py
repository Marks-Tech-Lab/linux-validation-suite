"""Widget-independent adapter for the shared stage workload settings screen."""
from __future__ import annotations

from dataclasses import replace
from contextlib import suppress

from .lvs_service_models import SetupPickerSpec
from .lvs_tui_input_state import tui_input_state
from .lvs_tui_picker_presentation import profile_edit_picker_open_presentation


def _stage_setting_value(stage, setting):
    module = getattr(stage.modules, setting.module)
    if setting.key == "thermal_system_access":
        return dict(device_ids=list(getattr(module, "_system_device_ids", ())),
                    colocated=getattr(module, "_control_plane_colocation", False),
                    swap=getattr(module, "_system_swap", False))
    if setting.key == "thermal_rates":
        return {key: getattr(module, key) for key in ("rate_mode", "iops", "bandwidth_bytes_per_second")}
    return getattr(module, setting.attribute)


class TuiStageConfigurationMixin:
    def _stage_configuration_edit(self):
        if self.stage_configuration_for_run:
            return self.service.run_setup_stage_edit(self.run_setup)
        return self.profile_edit

    async def _open_stage_configuration(self, index: int, *, for_run: bool = False) -> None:
        self.stage_configuration_index = index
        self.stage_configuration_for_run = for_run
        await self._show_stage_configuration()

    async def _show_stage_configuration(self, detail: str = "") -> None:
        try:
            await self._render_stage_configuration(detail)
        except Exception as exc:
            # Do not retry a failed renderer from its own error path. Disable
            # stale rows/input; Esc/Back can leave this screen and reopen it.
            self.view_mode = "stage_configuration"
            self.stage_configuration_fields = []
            self.setup_picker_key = self.profile_edit_picker_key = None
            self.pending_input_field = None
            self.confirm_run = False
            message = (detail + "\n\n" if detail else "") + f"Unable to display stage configuration: {exc}. Press Esc to return."
            with suppress(Exception):
                self._set_detail(message)
            with suppress(Exception):
                self.notify(message, severity="error")

    async def _render_stage_configuration(self, detail: str = "") -> None:
        self.view_mode = "stage_configuration"
        self.setup_picker_key = None
        self.profile_edit_picker_key = None
        self._clear_setup_input()
        edit = self._stage_configuration_edit()
        index = self.stage_configuration_index
        self.stage_configuration_fields = self.service.stage_configuration_settings(edit, index)
        rows = ["Back"]
        original = getattr(self.run_setup, "original_profile", None) if self.stage_configuration_for_run else None
        from .lvs_stage_configuration import setting_value_text
        for setting in self.stage_configuration_fields:
            effective = _stage_setting_value(edit.profile.stages[index], setting)
            value = setting_value_text(effective)
            suffix = ""
            if original is not None:
                old = _stage_setting_value(original.stages[index], setting)
                if old != effective:
                    suffix = f" (profile default: {old!r}; overridden)"
            rows.append(f"{setting.label}: {value or '(none)'}{suffix}")
        title = "Run-only Stage Configuration" if self.stage_configuration_for_run else "Stage Configuration"
        self.query_one("#sidebar-title").update(title)
        await self._replace_sidebar_labels(self.query_one("#items"), rows, selected_index=0, focus=True)
        self._set_detail((detail + "\n\n" if detail else "") + f"{title} — stage {index + 1}\n"
            + ("Changes affect this pending run only; the profile file is never saved.\n" if self.stage_configuration_for_run
               else "Changes remain unsaved until Save or Save As.\n")
            + "Select a setting and press Enter. Only settings applicable to enabled workloads/backends are offered.\n"
            + "Hardware readiness, memory budgets and runtime safety are still checked before execution.\n\n"
            + (self._thermal_access_help() if edit.profile.stages[index].modules.storage_thermal.enabled else ''))

    @staticmethod
    def _thermal_access_help():
        from .lvs_profile_report_text import storage_thermal_access_help
        return storage_thermal_access_help()

    async def _activate_stage_configuration_item(self, row: int) -> None:
        if row == 0:
            await self._leave_stage_configuration()
            return
        if not 0 < row <= len(self.stage_configuration_fields):
            return
        setting = self.stage_configuration_fields[row - 1]
        self.stage_configuration_key = setting.key
        if setting.options:
            spec = SetupPickerSpec(key="configuration:" + setting.key, title=setting.label,
                                   options=list(setting.options), current=str(setting.value).lower()
                                   if isinstance(setting.value, bool) else str(setting.value))
            presentation = profile_edit_picker_open_presentation(
                spec, "This setting is applied transactionally; invalid combinations are rejected. "
                "Physical selections are rechecked before execution; backend identity binding is still required.",
                stage_index=self.stage_configuration_index)
            if setting.key == 'thermal_access_mode':
                presentation = replace(presentation, picker=replace(presentation.picker,
                    detail=presentation.picker.detail + '\n\n' + self._thermal_access_help()))
            if setting.option_labels:
                presentation = replace(presentation, picker=replace(presentation.picker,
                    labels=tuple(label + (" (current)" if value == spec.current else "")
                                 for value, label in zip(setting.options, setting.option_labels))))
            await self._apply_profile_edit_picker_open_presentation(presentation)
        else:
            from .lvs_stage_configuration import setting_value_text
            self._apply_input_state(tui_input_state("__profile_configuration_value", value=setting_value_text(setting.value),
                placeholder=setting.label, detail=f"{setting.label}. Enter a valid value; Esc cancels."))

    async def _commit_stage_configuration(self, value: str) -> None:
        try:
            edit = self._stage_configuration_edit()
            result = self.service.apply_stage_configuration(edit, self.stage_configuration_index,
                                                            self.stage_configuration_key, value)
        except Exception as exc:
            detail = f"Setting unchanged: {exc}"
        else:
            if self.stage_configuration_for_run:
                self.run_setup.profile, self.run_setup.labels = edit.profile, edit.labels
            self.confirm_run = False
            detail = f"Updated: {result!r}"
        await self._show_stage_configuration(detail)

    async def _leave_stage_configuration(self) -> None:
        if self.stage_configuration_for_run:
            await self._show_run_setup_sidebar()
        else:
            await self._show_profile_edit()
