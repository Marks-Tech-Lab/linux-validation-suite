from __future__ import annotations

"""Textual TUI run-setup adapter methods.

These methods keep the TUI run-setup picker/input flow separate from the
Textual shell. They still update widgets through the host app, but all setup
mutation is delegated to ``SuiteAppService`` and its shared controllers.
"""

from typing import Optional

from Modules.lvs_service_models import FrontendActionSpec, RunSetupHistoryEntry, SetupPickerSpec
from Modules.lvs_tui_input_state import tui_input_state
from Modules.lvs_tui_navigation_state import tui_navigation_reset
from Modules.lvs_tui_picker_presentation import setup_picker_open_presentation
from Modules.lvs_tui_run_setup_flow import (
    normalize_power_watts,
    power_limit_amd_type_transition,
    power_limit_input_transition,
    power_limit_vendor_transition,
    prepared_run_readiness_text,
    run_setup_input_callbacks,
    run_setup_passthrough_callbacks,
    run_setup_readiness_text,
    stage_index_from_option,
)
from Modules.lvs_tui_run_setup_presentation import (
    RUN_SETUP_STAGE_INPUT_COMPLETE_TRIM,
    RUN_SETUP_STAGE_INPUT_TRIM_END,
    run_setup_detail_presentation,
    run_setup_history_confirm_presentation,
    run_setup_history_loaded_detail,
    run_setup_history_presentation,
    run_setup_history_prompt_presentation,
    run_setup_input_presentation,
    run_setup_no_history_detail,
    run_setup_sidebar_presentation,
    run_setup_stage_input_transition,
)


class TuiRunSetupAdapterMixin:
    def _show_run_setup(self, action_index: Optional[int] = None) -> None:
        if self.run_setup is None:
            self._set_detail("Select a profile first.")
            return
        action_detail = ""
        if (
            action_index is not None
            and 0 <= action_index < len(self.setup_actions)
        ):
            action_detail = self.service.setup_action_detail_text(
                self.run_setup,
                self.setup_actions[action_index],
            )
        self._set_detail(
            run_setup_detail_presentation(
                self.service.run_setup_overview_text(self.run_setup),
                action_detail,
            )
        )

    def _run_setup_action_controller(self):
        return self.service.create_run_setup_action_controller(
            run_setup_passthrough_callbacks(self.service, self._set_status)
        )

    def _handle_sync_run_setup_action(self, action: FrontendActionSpec):
        if self.run_setup is None:
            return None
        return self._run_setup_action_controller().handle_action(self.run_setup, action)

    def _handle_sync_run_setup_input(self, field: str, value: str):
        if self.run_setup is None:
            return None
        raw_value = str(value or "")
        action = FrontendActionSpec("", "input", field)
        controller = self.service.create_run_setup_action_controller(
            run_setup_input_callbacks(self.service, raw_value, self._set_status)
        )
        return controller.handle_action(self.run_setup, action)

    def _run_confirmation_readiness_text(self) -> str:
        if self.run_setup is None:
            return ""
        return run_setup_readiness_text(self.service, self.run_setup)

    def _prepare_run_confirmation_flow(self, *, save_blocked_report: bool = False):
        if self.run_setup is None:
            return None
        return self.service.prepare_setup_run_flow(
            self.run_setup,
            save_blocked_report=save_blocked_report,
        )

    def _prepared_run_readiness_text(self, prepared_flow) -> str:
        return prepared_run_readiness_text(prepared_flow)

    async def _show_run_setup_sidebar(self) -> None:
        if self.run_setup is None:
            self._set_detail("Select a profile first.")
            return
        self.view_mode = "setup"
        self._apply_navigation_reset(
            tui_navigation_reset(
                clear_confirm_run=False,
                clear_pending_input=False,
                clear_profile_edit_picker=False,
                reset_input_widget=False,
            )
        )
        self.setup_actions = self.service.setup_action_specs(self.run_setup)
        presentation = run_setup_sidebar_presentation(
            actions=self.setup_actions,
            overview=self.service.run_setup_overview_text(self.run_setup),
        )
        self.query_one("#sidebar-title").update(presentation.title)
        list_view = self.query_one("#items")
        await self._replace_sidebar_labels(
            list_view,
            list(presentation.rows),
            selected_index=presentation.selected_index,
        )
        self._set_detail(presentation.detail)
        self._focus_items()

    async def _select_run_setup_action(self, index: int) -> None:
        if self.run_setup is None or index < 0 or index >= len(self.setup_actions):
            return
        action = self.setup_actions[index]
        if action.action == "picker":
            await self._open_setup_picker(action.target)
        elif action.action == "input":
            self._begin_setup_input(action.target)
        elif action.action == "power_limit_picker":
            await self._open_power_limit_picker()
        elif action.action == "stage_override_picker":
            await self._open_stage_override_picker()
        elif action.action == "segment_label_picker":
            await self._open_segment_label_picker()
        elif action.action == "load_history":
            await self.action_load_setup_history()
        elif action.action == "toggle_debug_logging":
            self._handle_sync_run_setup_action(action)
            await self._show_run_setup_sidebar()
        elif action.action == "run_selected":
            self.action_run_selected()
        else:
            self._show_run_setup()

    async def _maybe_prompt_setup_history_recall(self) -> bool:
        if self.run_setup is None:
            return False
        self.history_entries = self.service.run_setup_history_entries()
        self.pending_history_entry = None
        if not self.history_entries:
            return False
        self.view_mode = "setup_history_prompt"
        presentation = run_setup_history_prompt_presentation(
            setup_summary=self.service.run_setup_summary_text(self.run_setup),
            entry_count=len(self.history_entries),
        )
        self.query_one("#sidebar-title").update(presentation.title)
        list_view = self.query_one("#items")
        await self._replace_sidebar_labels(
            list_view,
            list(presentation.rows),
            selected_index=presentation.selected_index,
            focus=True,
        )
        self._set_detail(presentation.detail)
        return True

    async def _select_setup_history_prompt(self, index: int) -> None:
        if self.run_setup is None:
            return
        if index == 0:
            await self._show_setup_history_entries()
            return
        await self._show_run_setup_sidebar()

    async def _show_setup_history_entries(self) -> None:
        if self.run_setup is None:
            return
        if not self.history_entries:
            self.history_entries = self.service.run_setup_history_entries()
        if not self.history_entries:
            await self._show_run_setup_sidebar()
            self._set_detail(run_setup_no_history_detail(self.service.run_setup_summary_text(self.run_setup)))
            return
        self.view_mode = "setup_history"
        presentation = run_setup_history_presentation(
            entries=self.history_entries,
            setup_summary=self.service.run_setup_summary_text(self.run_setup),
        )
        self.query_one("#sidebar-title").update(presentation.title)
        list_view = self.query_one("#items")
        await self._replace_sidebar_labels(
            list_view,
            list(presentation.rows),
            selected_index=presentation.selected_index,
            focus=True,
        )
        self._set_detail(presentation.detail)

    async def _select_setup_history_entry(self, entry: RunSetupHistoryEntry) -> None:
        if self.run_setup is None:
            return
        self.pending_history_entry = entry
        self.view_mode = "setup_history_confirm"
        presentation = run_setup_history_confirm_presentation(
            entry=entry,
            setup_summary=self.service.run_setup_summary_text(self.run_setup),
        )
        self.query_one("#sidebar-title").update(presentation.title)
        list_view = self.query_one("#items")
        await self._replace_sidebar_labels(
            list_view,
            list(presentation.rows),
            selected_index=presentation.selected_index,
            focus=True,
        )
        self._set_detail(presentation.detail)

    async def _select_setup_history_confirm(self, index: int) -> None:
        if self.run_setup is None:
            return
        if index != 0:
            self.pending_history_entry = None
            await self._restore_setup_sidebar()
            return
        entry = self.pending_history_entry
        self.pending_history_entry = None
        if entry is None:
            await self._restore_setup_sidebar()
            return
        self.service.apply_run_setup_history_entry(self.run_setup, entry)
        await self._restore_setup_sidebar()
        self._set_detail(run_setup_history_loaded_detail(self.service.run_setup_summary_text(self.run_setup)))

    def _begin_setup_input(
        self,
        field: str,
        label: Optional[str] = None,
        blank_default: str = "",
        initial_value: str = "",
    ) -> None:
        spec = self.service.setup_input_spec(
            field,
            label=label,
            blank_default=blank_default,
            initial_value=initial_value,
        )
        presentation = run_setup_input_presentation(
            field=field,
            spec=spec,
            setup_summary=self.service.run_setup_summary_text(self.run_setup),
        )
        self._apply_input_state(
            tui_input_state(
                presentation.pending_field,
                value=presentation.value,
                blank_default=presentation.blank_default,
                placeholder=presentation.placeholder,
                detail=presentation.detail,
            )
        )

    async def _open_setup_picker(self, key: str) -> None:
        if self.run_setup is None:
            return
        options = self.service.option_values(key)
        if not options:
            self._show_run_setup()
            return
        spec = self.service.setup_option_picker_spec(self.run_setup, key)
        await self._apply_setup_picker_open_presentation(
            setup_picker_open_presentation(spec, self.service.run_setup_summary_text(self.run_setup))
        )

    async def _open_custom_setup_picker(
        self,
        key: str = "",
        title: str = "",
        options: Optional[list[str]] = None,
        current: str = "",
        spec: Optional[SetupPickerSpec] = None,
    ) -> None:
        if self.run_setup is None:
            return
        picker = spec or SetupPickerSpec(key=key, title=title or key, options=list(options or []), current=current)
        await self._apply_setup_picker_open_presentation(
            setup_picker_open_presentation(picker, self.service.run_setup_summary_text(self.run_setup))
        )

    async def _open_power_limit_picker(self) -> None:
        self.power_limit_parts = {}
        await self._open_custom_setup_picker(spec=self.service.setup_power_limit_vendor_picker_spec())

    async def _open_stage_override_picker(self) -> None:
        if self.run_setup is None:
            return
        await self._open_custom_setup_picker(spec=self.service.setup_stage_override_picker_spec(self.run_setup))

    async def _open_segment_label_picker(self) -> None:
        if self.run_setup is None:
            return
        await self._open_custom_setup_picker(spec=self.service.setup_segment_label_picker_spec(self.run_setup))

    async def _handle_stage_override_choice(self, selected: str) -> None:
        if self.run_setup is None:
            return
        choice = str(selected or "").strip().lower()
        if "duration" in choice:
            await self._open_custom_setup_picker(spec=self.service.setup_stage_duration_picker_spec(self.run_setup))
            return
        if "trim" in choice:
            await self._restore_setup_sidebar()
            self.pending_trim_start = None
            current = int(self.run_setup.profile.defaults.trim_start_seconds)
            self._begin_setup_input(
                "trim_start",
                label="Trim start seconds",
                blank_default=str(current),
                initial_value=str(current),
            )
            return
        if "toggle" in choice or "enabled" in choice:
            await self._open_custom_setup_picker(spec=self.service.setup_stage_toggle_picker_spec(self.run_setup))
            return
        await self._restore_setup_sidebar()

    async def _handle_stage_duration_choice(self, selected: str) -> None:
        index = self._stage_index_from_option(selected)
        if index is None or self.run_setup is None:
            await self._restore_setup_sidebar()
            return
        if self.run_setup.profile.stages[index].modules.storage_benchmark.enabled:
            await self._restore_setup_sidebar()
            self._set_detail("Storage Benchmark is completion-based and has no stage duration.")
            return
        self.pending_stage_index = index
        current = int(self.run_setup.profile.stages[index].duration_seconds)
        await self._restore_setup_sidebar()
        self._begin_setup_input(
            "stage_duration",
            label=f"Stage {index + 1} duration seconds",
            blank_default=str(current),
            initial_value=str(current),
        )

    async def _handle_stage_toggle_choice(self, selected: str) -> None:
        index = self._stage_index_from_option(selected)
        await self._restore_setup_sidebar()
        if index is not None and self.run_setup is not None:
            self.service.toggle_stage_enabled(self.run_setup, index)
            await self._show_run_setup_sidebar()

    async def _handle_segment_label_choice(self, selected: str) -> None:
        index = self._stage_index_from_option(selected)
        if index is None or self.run_setup is None:
            await self._restore_setup_sidebar()
            return
        self.pending_stage_index = index
        current = self.run_setup.labels[index] if index < len(self.run_setup.labels) else ""
        await self._restore_setup_sidebar()
        self._begin_setup_input(
            "segment_label",
            label=f"Stage {index + 1} segment label",
            blank_default=current,
            initial_value=current,
        )

    def _stage_index_from_option(self, selected: str) -> Optional[int]:
        stage_count = len(self.run_setup.profile.stages) if self.run_setup is not None else 0
        return stage_index_from_option(selected, stage_count)

    async def _select_setup_picker_option(self, selected: str) -> None:
        if self.run_setup is None or not self.setup_picker_key:
            return
        key = self.setup_picker_key
        if key == "power_limit_vendor":
            await self._handle_power_limit_vendor(selected)
            return
        if key == "power_limit_amd_type":
            await self._handle_power_limit_amd_type(selected)
            return
        if key == "stage_override":
            await self._handle_stage_override_choice(selected)
            return
        if key == "stage_duration":
            await self._handle_stage_duration_choice(selected)
            return
        if key == "stage_toggle":
            await self._handle_stage_toggle_choice(selected)
            return
        if key == "segment_label":
            await self._handle_segment_label_choice(selected)
            return
        result = self.service.select_setup_option_result(self.run_setup, key, selected)
        await self._restore_setup_sidebar()
        if result.requires_text:
            self._begin_setup_input(
                result.text_field,
                label=result.prompt,
                blank_default=result.blank_default,
            )
            return
        self._show_run_setup()

    async def _handle_power_limit_vendor(self, selected: str) -> None:
        if self.run_setup is None:
            return
        transition = power_limit_vendor_transition(selected)
        if transition.action == "set_metadata":
            self.run_setup.metadata.power_limit_data = transition.metadata_value
            await self._show_run_setup_sidebar()
            return
        await self._restore_setup_sidebar()
        if transition.reset_parts:
            self.power_limit_parts = {}
        if transition.action == "input":
            self._begin_setup_input(
                transition.next_field,
                label=transition.next_label,
                blank_default=transition.next_blank_default,
            )
            return

    async def _handle_power_limit_amd_type(self, selected: str) -> None:
        if self.run_setup is None:
            return
        transition = power_limit_amd_type_transition(selected, self.power_limit_parts)
        self.power_limit_parts.update(transition.parts_update)
        if transition.action == "input":
            await self._restore_setup_sidebar()
            self._begin_setup_input(
                transition.next_field,
                label=transition.next_label,
                blank_default=transition.next_blank_default,
            )
            return
        if transition.action == "set_metadata":
            self.run_setup.metadata.power_limit_data = transition.metadata_value
            await self._show_run_setup_sidebar()

    async def _restore_setup_sidebar(self) -> None:
        await self._show_run_setup_sidebar()

    async def _commit_stage_input(self, field: str, value: str) -> None:
        if self.run_setup is None:
            self._clear_setup_input()
            return
        value = str(value or "").strip()
        transition = run_setup_stage_input_transition(
            field=field,
            value=value,
            pending_trim_start=self.pending_trim_start,
            default_trim_start=int(self.run_setup.profile.defaults.trim_start_seconds),
            default_trim_end=int(self.run_setup.profile.defaults.trim_end_seconds),
        )
        if field == "stage_duration":
            if self.pending_stage_index is not None:
                self.service.set_stage_duration(self.run_setup, self.pending_stage_index, value)
            self.pending_stage_index = None
            self._clear_setup_input()
            self._focus_items()
            await self._show_run_setup_sidebar()
            return
        if field == "segment_label":
            if self.pending_stage_index is not None:
                self.service.set_segment_label(self.run_setup, self.pending_stage_index, value)
            self.pending_stage_index = None
            self._clear_setup_input()
            self._focus_items()
            await self._show_run_setup_sidebar()
            return
        if transition.action == RUN_SETUP_STAGE_INPUT_TRIM_END:
            self.pending_trim_start = transition.start
            self._clear_setup_input()
            self._begin_setup_input(
                transition.next_field,
                label=transition.next_label,
                blank_default=transition.next_blank_default,
                initial_value=transition.next_value,
            )
            return
        if transition.action == RUN_SETUP_STAGE_INPUT_COMPLETE_TRIM:
            self.service.set_all_stage_trim(self.run_setup, int(transition.start or 0), int(transition.end or 0))
            self.pending_trim_start = None
            self._clear_setup_input()
            self._focus_items()
            await self._show_run_setup_sidebar()

    async def _commit_power_limit_input(self, field: str, value: str) -> None:
        if self.run_setup is None:
            return
        transition = power_limit_input_transition(field, value, self.power_limit_parts)
        self._clear_setup_input()
        self.power_limit_parts.update(transition.parts_update)
        if transition.action == "set_metadata":
            self.run_setup.metadata.power_limit_data = transition.metadata_value
            await self._show_run_setup_sidebar()
            return
        if transition.action == "input":
            self._begin_setup_input(
                transition.next_field,
                label=transition.next_label,
                blank_default=transition.next_blank_default,
            )
            return
        if transition.action == "picker" and transition.picker == "amd_power_limit_type":
            await self._open_custom_setup_picker(spec=self.service.setup_amd_power_limit_type_picker_spec())
            return

    def _normalize_power_watts(self, value: str) -> str:
        return normalize_power_watts(value)
