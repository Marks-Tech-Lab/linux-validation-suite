"""Widget-independent adapter for the shared stage workload settings screen."""
from __future__ import annotations

from dataclasses import replace
from contextlib import suppress
from types import SimpleNamespace

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
        self.stage_configuration_section = 'workloads'
        self.thermal_picker_rows = []
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
        section = getattr(self, 'stage_configuration_section', 'workloads')
        if section == 'workloads':
            from .lvs_stage_configuration import StageSetting
            self.stage_configuration_fields = [s for s in self.service.stage_configuration_settings(edit, index)
                                                if not s.key.startswith('thermal_')]
            self.stage_configuration_fields.append(StageSetting('thermal_ui_open', 'Storage Thermal Assist…',
                'storage_thermal', 'enabled', 'On' if edit.profile.stages[index].modules.storage_thermal.enabled else 'Off'))
        else:
            self.stage_configuration_fields = self.service.thermal_configuration_settings(edit, index, section,
                getattr(self, 'thermal_picker_rows', ()))
        rows = ["Back"]
        original = getattr(self.run_setup, "original_profile", None) if self.stage_configuration_for_run else None
        from .lvs_stage_configuration import setting_value_text
        old_fields = self.service.thermal_configuration_settings(SimpleNamespace(profile=original), index, section,
            getattr(self, 'thermal_picker_rows', ())) if original is not None and section != 'workloads' else ()
        old_values = {f.key: f.value for f in old_fields}
        for setting in self.stage_configuration_fields:
            effective = setting.value if setting.key.startswith('thermal_ui_') else _stage_setting_value(edit.profile.stages[index], setting)
            value = setting_value_text(effective)
            suffix = ""
            if original is not None and not setting.key.startswith('thermal_ui_'):
                old = _stage_setting_value(original.stages[index], setting)
                if old != effective:
                    suffix = f" (profile default: {old!r}; overridden)"
            if setting.key == 'thermal_ui_enabled':value = 'On' if effective else 'Off'
            elif setting.option_labels:
                raw = str(effective).lower() if isinstance(effective, bool) else str(effective)
                if raw in setting.options:value = setting.option_labels[setting.options.index(raw)]
            if original is not None and setting.key.startswith('thermal_ui_'):
                old = old_values.get(setting.key, effective)
                if old != effective:suffix = ' (run override)'
            rows.append(f"{setting.label}: {value or '(none)'}{suffix}")
        title = "Run-only Stage Configuration" if self.stage_configuration_for_run else "Stage Configuration"
        if section != 'workloads':title = 'Thermal Assist' + (' — Advanced' if section == 'thermal_advanced' else ' — Drives' if section == 'thermal_drives' else ' — Per-drive' if section == 'thermal_per_drive' else '')
        self.query_one("#sidebar-title").update(title)
        await self._replace_sidebar_labels(self.query_one("#items"), rows, selected_index=0, focus=True)
        self._wrap_stage_configuration_rows()
        self._set_detail((detail + "\n\n" if detail else "") + f"{title} — stage {index + 1}\n"
            + ("Changes affect this pending run only; the profile file is never saved.\n" if self.stage_configuration_for_run
               else "Changes remain unsaved until Save or Save As.\n")
            + "Select a setting and press Enter. Only settings applicable to enabled workloads/backends are offered.\n"
            + "Hardware readiness, memory budgets and runtime safety are still checked before execution.\n\n"
            + (self._thermal_configuration_help(edit.profile.stages[index], section) if section != 'workloads' else 'Storage Thermal Assist has its own configuration screen. No activity is started here.'))

    def _wrap_stage_configuration_rows(self):
        # Scope wrapping to this screen and its option pickers. Long drive
        # names/capacities remain readable on the existing narrow sidebar.
        view = self.query_one('#items')
        if callable(getattr(view, 'query', None)):
            for item in view.query('ListItem'):
                item.styles.height = 'auto'
                for label in item.query('Label'):
                    label.styles.width = '1fr'
                    label.styles.height = 'auto'

    @staticmethod
    def _thermal_configuration_help(stage, section):
        from .lvs_storage_thermal_configuration import help_text
        from .lvs_profile_report_text import storage_thermal_request_text
        return storage_thermal_request_text(stage.modules.storage_thermal) + '\n\n' + help_text(section)

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
        navigation = {'thermal_ui_open': 'thermal', 'thermal_ui_advanced': 'thermal_advanced',
                      'thermal_ui_perdrive': 'thermal_per_drive'}
        if setting.key in navigation:
            self.stage_configuration_section = navigation[setting.key]
            detail = ''
            if setting.key == 'thermal_ui_perdrive':
                try:self.thermal_picker_rows = self.service.thermal_drive_choices()
                except (OSError, ValueError, RuntimeError) as exc:
                    self.thermal_picker_rows = [];detail = f'Drive discovery unavailable: {exc}'
            await self._show_stage_configuration(detail)
            return
        self.stage_configuration_key = setting.key
        if setting.options:
            spec = SetupPickerSpec(key="configuration:" + setting.key, title=setting.label,
                                   options=list(setting.options), current=str(setting.value).lower()
                                   if isinstance(setting.value, bool) else str(setting.value))
            if setting.key == 'thermal_ui_targets':
                spec = replace(spec, current=self._stage_configuration_edit().profile.stages[self.stage_configuration_index].modules.storage_thermal.selection)
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
            self._wrap_stage_configuration_rows()
        else:
            from .lvs_stage_configuration import setting_value_text
            self._apply_input_state(tui_input_state("__profile_configuration_value", value=setting_value_text(setting.value),
                placeholder=setting.label, detail=f"{setting.label}. Enter a valid value; Esc cancels."))

    async def _commit_stage_configuration(self, value: str) -> None:
        if self.stage_configuration_key == 'thermal_ui_budget_mode' and value == 'manual':
            module = self._stage_configuration_edit().profile.stages[self.stage_configuration_index].modules.storage_thermal
            if module.budget_mode == 'automatic':
                await self._show_stage_configuration()
                self.stage_configuration_key = 'thermal_ui_manual_caps'
                self._apply_input_state(tui_input_state('__profile_configuration_value',
                    placeholder='Total IOPS / MiB/s', detail='Enter both manual caps, for example 128 / 8. Esc cancels.'))
                return
        if self.stage_configuration_key == 'thermal_ui_targets' and value == 'individual':
            try:
                self.thermal_picker_rows = self.service.thermal_drive_choices()
                self.stage_configuration_section = 'thermal_drives'
                await self._show_stage_configuration('Choose drives by model and capacity. No devices are opened.')
            except (OSError, ValueError, RuntimeError) as exc:
                await self._show_stage_configuration(f'Drive discovery unavailable: {exc}')
            return
        try:
            edit = self._stage_configuration_edit()
            result = self.service.apply_stage_configuration(edit, self.stage_configuration_index,
                                                            self.stage_configuration_key, value, **(dict(thermal_rows=getattr(self, 'thermal_picker_rows', ())) if self.stage_configuration_key.startswith('thermal_ui_') else {}))
        except Exception as exc:
            detail = f"Setting unchanged: {exc}"
        else:
            if self.stage_configuration_for_run:
                self.run_setup.profile, self.run_setup.labels = edit.profile, edit.labels
            self.confirm_run = False
            detail = f"Updated: {result!r}"
        await self._show_stage_configuration(detail)

    async def _leave_stage_configuration(self) -> None:
        section = getattr(self, 'stage_configuration_section', 'workloads')
        if section != 'workloads':
            self.stage_configuration_section = ('thermal_advanced' if section == 'thermal_per_drive' else
                                                'thermal' if section != 'thermal' else 'workloads')
            await self._show_stage_configuration()
            return
        if self.stage_configuration_for_run:
            await self._show_run_setup_sidebar()
        else:
            await self._show_profile_edit()
