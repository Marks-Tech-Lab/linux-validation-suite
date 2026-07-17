from __future__ import annotations

"""Textual TUI event routing and input commit adapter methods."""

from typing import Any

from Modules.lvs_tui_event_flow import (
    button_action,
    event_key,
    index_in_range,
    is_escape_key,
    pending_input_route,
    selected_index,
    setup_input_reset_state,
    setup_input_value,
    view_uses_escape_cancel,
)
from Modules.lvs_tui_navigation_state import tui_navigation_reset
from Modules.lvs_tui_app_actions_flow import SETTINGS_SIDEBAR_ACTIONS


class TuiEventAdapterMixin:
    async def action_refresh(self) -> None:
        if self.view_mode == "results":
            await self.action_show_results()
        elif self.view_mode == "settings":
            await self.action_show_settings()
        elif self.view_mode == "settings_list" and self.setting_list_key:
            await self._open_settings_list(self.setting_list_key)
        else:
            await self.action_show_profiles()

    async def on_button_pressed(self, event: Any) -> None:
        action = button_action(event.button.id)
        if action == "cancel_setup_input":
            if getattr(self, "upload_in_progress", False):
                self._show_locked_interaction_message()
                return
            await self._dispatch_button_action(action)
            return
        if self._interaction_locked():
            self._show_locked_interaction_message()
            return
        await self._dispatch_button_action(action)

    async def _dispatch_button_action(self, action: str) -> None:
        if action == "show_profiles":
            await self.action_show_profiles()
        elif action == "dry_run":
            self.action_dry_run()
        elif action == "dependency_check":
            self.action_dependency_check()
        elif action == "show_migration_support":
            await self.action_show_migration_support()
        elif action == "new_profile":
            await self.action_new_profile()
        elif action == "setup_run":
            await self.action_setup_run()
        elif action == "edit_profile":
            await self.action_edit_profile()
        elif action == "setup_history":
            await self.action_load_setup_history()
        elif action == "run_selected":
            self.action_run_selected()
        elif action == "show_results":
            await self.action_show_results()
        elif action == "show_settings":
            await self.action_show_settings()
        elif action == "show_storage_benchmark_info":
            await self.action_show_storage_benchmark_info()
        elif action.startswith("settings_key:"):
            if self.view_mode == "settings":
                await self._dispatch_settings_key(action.split(":", 1)[1])
        elif action == "refresh":
            await self.action_refresh()
        elif action == "upload_last_result":
            self.action_upload_last_result()
        elif action == "edit_wall_wattage":
            self.action_edit_wall_wattage()
        elif action == "cancel_setup_input":
            await self.action_cancel_setup_input()
        elif action == "quit":
            exit_app = getattr(self, "exit", None)
            if callable(exit_app):
                exit_app()

    async def on_list_view_selected(self, event: Any) -> None:
        if self.run_in_progress or getattr(self, "upload_in_progress", False):
            self._show_locked_interaction_message()
            return
        index = selected_index(event)
        if index is None:
            return
        if self.view_mode == "setup_history":
            if index_in_range(index, self.history_entries):
                await self._select_setup_history_entry(self.history_entries[index])
            return
        if self.view_mode == "setup_history_prompt":
            await self._select_setup_history_prompt(index)
            return
        if self.view_mode == "setup_history_confirm":
            await self._select_setup_history_confirm(index)
            return
        if self.view_mode == "setup_picker":
            if index_in_range(index, self.setup_picker_options):
                await self._select_setup_picker_option(self.setup_picker_options[index])
            return
        if self.view_mode == "post_run_upload_picker":
            await self._select_post_run_upload_option(index)
            return
        if self.view_mode == "setup":
            await self._select_run_setup_action(index)
            return
        if self.view_mode == "profile_edit_picker":
            if index_in_range(index, self.profile_edit_picker_options):
                await self._select_profile_edit_picker_option(self.profile_edit_picker_options[index])
            return
        if self.view_mode == "results":
            if index_in_range(index, self.results):
                result = self.results[index]
                if getattr(self, "comparison_target_result", None) is not None:
                    self._complete_result_comparison(result)
                else:
                    self.selected_result = result
                    self._apply_navigation_reset(tui_navigation_reset(clear_setup_picker=False))
                    self._show_result_summary(self.selected_result)
            return
        if self.view_mode == "settings_list":
            self.setting_list_selected_index = max(0, index)
            return
        if self.view_mode == "settings":
            if index_in_range(index, SETTINGS_SIDEBAR_ACTIONS):
                await self._dispatch_settings_key(SETTINGS_SIDEBAR_ACTIONS[index][0])
            return
        if self.view_mode == "migration_support":
            await self._select_migration_support_action(index)
            return
        if self.view_mode == "profile_edit":
            self.profile_edit_selected_index = max(0, index)
            await self._activate_profile_edit_item(index)
            return
        if index_in_range(index, self.profiles):
            self.selected_profile = self.profiles[index]
            self._apply_navigation_reset(tui_navigation_reset(clear_setup_picker=False))
            if self.view_mode in {"profiles", "setup"}:
                self.run_setup = self.service.create_run_setup(self.selected_profile.path)
                if await self._maybe_prompt_setup_history_recall():
                    return
                await self._show_run_setup_sidebar()
                return
            self._show_profile_summary(self.selected_profile)

    def on_list_view_highlighted(self, event: Any) -> None:
        if self.run_in_progress or getattr(self, "upload_in_progress", False):
            return
        index = selected_index(event)
        if index is None:
            return
        if self.view_mode == "results":
            if index_in_range(index, self.results):
                result = self.results[index]
                if getattr(self, "comparison_target_result", None) is not None:
                    self._show_result_comparison_candidate(result)
                else:
                    self.selected_result = result
                    self._show_result_summary(self.selected_result)
            return
        if self.view_mode == "profiles":
            if index_in_range(index, self.profiles):
                self.selected_profile = self.profiles[index]
                self.confirm_run = False
                self._show_profile_summary(self.selected_profile)
            return
        if self.view_mode == "settings_list":
            self.setting_list_selected_index = max(0, index)
            return
        if self.view_mode == "migration_support":
            return
        if self.view_mode == "profile_edit":
            self.profile_edit_selected_index = max(0, index)
            if self.profile_edit is not None:
                self._set_detail(self.service.profile_edit_summary_text(self.profile_edit))
            return
        if self.view_mode == "setup":
            self._show_run_setup(index)
            return

    async def on_key(self, event: Any) -> None:
        if self.run_in_progress:
            if is_escape_key(event):
                await self.action_cancel_setup_input()
                event.stop()
            return
        if getattr(self, "upload_in_progress", False):
            self._show_locked_interaction_message()
            event.stop()
            return
        if getattr(self, "pending_input_field", None) == "__post_wall_wattage":
            if is_escape_key(event):
                await self.action_cancel_setup_input()
                event.stop()
            return
        if self.view_mode == "results":
            action = self.service.result_action_for_key(event_key(event))
            if action.action == "inventory":
                self._show_results_inventory()
                event.stop()
            elif action.action == "stage_details":
                self._show_result_stage_details()
                event.stop()
            elif action.action == "qa_review":
                self._show_result_qa_review()
                event.stop()
            elif action.action == "artifact_detail":
                self._show_result_artifact_details()
                event.stop()
            elif action.action == "compare_selected":
                self._begin_result_comparison()
                event.stop()
            elif action.action == "validate_selected":
                self._validate_selected_result()
                event.stop()
            elif action.action == "validate_all":
                self._validate_all_results()
                event.stop()
            elif action.action == "pre_import_selected":
                self._pre_import_selected_result()
                event.stop()
            elif action.action == "pre_import_all":
                self._pre_import_all_results()
                event.stop()
            return
        if self.view_mode == "profiles":
            action = self.service.profile_action_for_key(event_key(event))
            if action.action == "audit_profiles":
                self._audit_profiles()
                event.stop()
            elif action.action == "new_profile":
                await self.action_new_profile()
                event.stop()
            elif action.action == "ensure_example_profile":
                await self._ensure_example_profile()
                event.stop()
            return
        if self.view_mode == "settings":
            handled = await self._dispatch_settings_key(event_key(event))
            if handled:
                event.stop()
            return
        if self.view_mode == "settings_list":
            action = self.service.settings_list_action_for_key(event_key(event))
            if action.action == "cancel":
                await self.action_cancel_setup_input()
                event.stop()
            elif action.action == "input":
                self._begin_settings_list_input(action.target)
                event.stop()
            elif action.action == "delete":
                await self._delete_selected_settings_list_item()
                event.stop()
            elif action.action == "restore_defaults":
                await self._restore_settings_list_defaults()
                event.stop()
            return
        if self.view_mode == "profile_edit":
            action = self.service.profile_edit_action_for_key(event_key(event))
            if action.action == "cancel":
                await self._cancel_profile_edit()
                event.stop()
            elif action.action == "save":
                await self._save_profile_edit()
                event.stop()
            elif action.action == "remove_stage":
                await self._remove_selected_profile_stage()
                event.stop()
            elif action.action == "toggle_stage":
                await self._toggle_selected_profile_stage()
                event.stop()
            elif action.action == "input":
                self._begin_profile_stage_input(action.target)
                event.stop()
            elif action.action == "picker":
                await self._open_profile_stage_picker(action.target)
                event.stop()
            return
        if view_uses_escape_cancel(self.view_mode):
            if is_escape_key(event):
                await self.action_cancel_setup_input()
                event.stop()
            return
        if self.view_mode != "setup" or self.run_setup is None:
            return
        key = event_key(event)
        if key in {"escape", "b", "q"} and not self.pending_input_field:
            await self.action_show_profiles()
            event.stop()
            return
        if self.pending_input_field:
            if key == "enter":
                await self._commit_setup_input()
                event.stop()
            elif key == "escape":
                await self.action_cancel_setup_input()
                event.stop()
            return
        action = self.service.setup_action_for_key(key)
        if action.action == "picker":
            await self._open_setup_picker(action.target)
            event.stop()
        elif action.action == "power_limit_picker":
            await self._open_power_limit_picker()
            event.stop()
        elif action.action == "stage_override_picker":
            await self._open_stage_override_picker()
            event.stop()
        elif action.action == "segment_label_picker":
            await self._open_segment_label_picker()
            event.stop()
        elif action.action == "toggle_debug_logging":
            self._handle_sync_run_setup_action(action)
            await self._show_run_setup_sidebar()
            event.stop()
        elif action.action == "input":
            self._begin_setup_input(action.target)
            event.stop()

    async def on_input_submitted(self, event: Any) -> None:
        if event.input.id != "setup-input":
            return
        await self._commit_setup_input()
        event.stop()

    async def action_cancel_setup_input(self) -> None:
        if self.run_in_progress:
            self._show_locked_interaction_message(cancel_requested=True)
            return
        if self.setup_picker_key:
            await self._restore_setup_sidebar()
            return
        if self.view_mode == "post_run_upload_picker":
            await self._skip_post_run_upload_prompt()
            return
        if self.profile_edit_picker_key:
            await self._restore_profile_edit_sidebar()
            return
        if self.view_mode == "settings_list":
            await self.action_show_settings()
            return
        if self.view_mode in {"settings", "storage_benchmark_info"} and not self.pending_input_field:
            await self.action_show_profiles()
            return
        if self.view_mode == "setup_history":
            await self._restore_setup_sidebar()
            return
        if self.view_mode == "setup_history_prompt":
            await self._show_run_setup_sidebar()
            return
        if self.view_mode == "setup_history_confirm":
            await self._restore_setup_sidebar()
            return
        if self.view_mode == "setup":
            await self.action_show_profiles()
            return
        if self.view_mode == "results":
            await self.action_show_profiles()
            return
        if self.view_mode == "migration_support":
            if self.pending_input_field:
                self.pending_migration_bundle_path = None
                self._clear_setup_input()
                await self.action_show_migration_support()
            else:
                await self.action_show_profiles()
            return
        if not self.pending_input_field:
            return
        self._clear_setup_input(focus_items=True)
        if self.view_mode == "setup" and self.run_setup is not None:
            await self._show_run_setup_sidebar()
        elif self.view_mode == "profile_edit" and self.profile_edit is not None:
            await self._show_profile_edit()
        elif self.view_mode == "settings":
            self._set_detail(self.service.settings_summary_text())
        elif self.last_run_dir is not None:
            self._set_detail(self._post_run_operator_text(self.last_run_dir, self._post_run_text(self.last_run_dir)))
            self._set_status("Run complete | Prompt cancelled")

    async def _dispatch_settings_key(self, key: str) -> bool:
        if self.view_mode != "settings":
            return False
        action = self.service.settings_action_for_key(key)
        if action.action == "toggle_environment":
            self._set_detail(self.service.toggle_environment_mode_text())
            self._set_status("Settings updated | Environment mode")
        elif action.action == "input":
            self._begin_settings_input(action.target)
            self._set_status(f"Editing setting | {self.service.settings_input_label(action.target)}")
        elif action.action == "toggle_bool":
            self._set_detail(self.service.toggle_bool_setting_text(action.target))
            self._set_status(f"Settings updated | {action.label}")
        elif action.action == "settings_list":
            await self._open_settings_list(action.target)
        elif action.action == "google_drive_readiness":
            self._set_detail(self.service.google_drive_readiness_text())
            self._set_status("Settings | Google Drive readiness")
        else:
            return False
        return True

    async def _commit_setup_input(self) -> None:
        if not self.pending_input_field:
            return
        input_widget = self.query_one("#setup-input")
        route = pending_input_route(self.pending_input_field)
        if route == "post_wall_wattage":
            if self.last_run_dir is not None and self.last_run_metadata is not None:
                raw_wall_wattage = input_widget.value
                normalized = self.service.save_wall_wattage(
                    self.last_run_dir,
                    self.last_run_metadata,
                    raw_wall_wattage,
                )
                self._clear_setup_input(focus_items=True)
                outcome = self.service.wall_wattage_result_outcome(
                    self.last_run_dir,
                    raw_wall_wattage,
                    normalized,
                    self._post_run_text(self.last_run_dir),
                )
                post_text = outcome.text
                if self._should_post_run_upload_prompt():
                    await self._begin_post_run_upload_prompt(post_text)
                    return
                self._set_detail(self._post_run_operator_text(self.last_run_dir, post_text))
                self._set_status(outcome.status)
            return
        if route == "post_upload_prompt":
            raw = str(input_widget.value or "").strip().lower()
            self._clear_setup_input(focus_items=True)
            if raw in {"y", "yes"}:
                self._start_upload_last_result()
            elif self.last_run_dir is not None:
                outcome = self.service.upload_skipped_outcome(self._post_run_text(self.last_run_dir))
                self._set_detail(
                    self._post_run_operator_text(
                        self.last_run_dir,
                        outcome.text,
                        upload_status="skipped",
                    )
                )
                self._set_status(outcome.status)
            return
        if route == "migration":
            await self._commit_migration_input(self.pending_input_field, input_widget.value)
            return
        if route == "settings" and await self._commit_settings_input(self.pending_input_field, input_widget.value):
            return
        if route == "profile_edit":
            await self._commit_profile_edit_input(self.pending_input_field, input_widget.value)
            return
        if self.run_setup is None:
            return
        value = input_widget.value
        value = setup_input_value(value, self.pending_input_blank_default)
        if route == "power_limit":
            await self._commit_power_limit_input(self.pending_input_field, value)
            return
        if route == "stage_input":
            await self._commit_stage_input(self.pending_input_field, value)
            return
        if route == "fan_type" and str(value or "").strip().lower() == "m":
            self._clear_setup_input()
            self._begin_setup_input("fan_details")
            return
        self._handle_sync_run_setup_input(self.pending_input_field, value)
        self._clear_setup_input(focus_items=True)
        await self._show_run_setup_sidebar()

    def _clear_setup_input(self, *, focus_items: bool = False) -> None:
        self._apply_input_reset_state(setup_input_reset_state())
        self.pending_input_field = None
        self.confirm_run = False
        if focus_items:
            self._focus_items()
