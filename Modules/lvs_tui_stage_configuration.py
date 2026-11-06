"""Widget-independent adapter for the shared stage workload settings screen."""
from __future__ import annotations

from dataclasses import replace

from .lvs_service_models import SetupPickerSpec
from .lvs_tui_input_state import tui_input_state
from .lvs_tui_picker_presentation import profile_edit_picker_open_presentation


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
            value = setting_value_text(setting.value)
            suffix = ""
            if original is not None:
                old = getattr(getattr(original.stages[index].modules, setting.module), setting.attribute)
                if setting.key == "thermal_rates":
                    module = original.stages[index].modules.storage_thermal
                    old = {key:getattr(module,key) for key in setting.value}
                if old != setting.value:
                    suffix = f" (profile default: {old!r}; overridden)"
            rows.append(f"{setting.label}: {value or '(none)'}{suffix}")
        title = "Run-only Stage Configuration" if self.stage_configuration_for_run else "Stage Configuration"
        self.query_one("#sidebar-title").update(title)
        await self._replace_sidebar_labels(self.query_one("#items"), rows, selected_index=0, focus=True)
        self._set_detail((detail + "\n\n" if detail else "") + f"{title} — stage {index + 1}\n"
            + ("Changes affect this pending run only; the profile file is never saved.\n" if self.stage_configuration_for_run
               else "Changes remain unsaved until Save or Save As.\n")
            + "Select a setting and press Enter. Only settings applicable to enabled workloads/backends are offered.\n"
            + "Hardware readiness, memory budgets and runtime safety are still checked before execution.")

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
            if self.stage_configuration_for_run:
                self.run_setup.profile, self.run_setup.labels = edit.profile, edit.labels
            self.confirm_run = False
            await self._show_stage_configuration(f"Updated: {result!r}")
        except Exception as exc:
            await self._show_stage_configuration(f"Setting unchanged: {exc}")

    async def _leave_stage_configuration(self) -> None:
        if self.stage_configuration_for_run:
            await self._show_run_setup_sidebar()
        else:
            await self._show_profile_edit()
