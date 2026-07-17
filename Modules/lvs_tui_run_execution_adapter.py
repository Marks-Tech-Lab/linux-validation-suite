from __future__ import annotations

"""Textual TUI run execution and post-run adapter methods."""

import asyncio
import threading
from pathlib import Path

from Modules.lvs_run_executor import RunExecutionError
from Modules.lvs_run_progress import RunProgressEvent
from Modules.lvs_service_models import FrontendActionSpec
from Modules.lvs_tui_input_state import tui_input_state
from Modules.lvs_tui_post_run_flow import (
    POST_RUN_ACTION_COMPLETE,
    POST_RUN_ACTION_FAILED,
    POST_RUN_ACTION_UPLOAD_PROMPT,
    POST_RUN_ACTION_WALL_WATTAGE,
    TuiPostRunPromptSpec,
    post_run_completion_transition,
    post_run_prompt_presentation,
    post_run_skip_upload_base_text,
    post_run_upload_prompt_spec,
    post_run_wall_wattage_prompt_spec,
    should_prompt_for_post_run_upload,
)
from Modules.lvs_tui_run_presentation import (
    initial_run_active_presentation,
    locked_post_run_upload_text,
    locked_post_run_wall_wattage_text,
    locked_run_detail_text,
    post_run_operator_presentation,
    run_confirmation_presentation,
)
from Modules.lvs_tui_run_execution_flow import (
    apply_run_output_line,
    interaction_locked,
    run_execution_error_text,
    run_progress_text,
    run_success_thread_text,
    tail_text,
    upload_active_detail,
    upload_finish_result,
    upload_not_ready_detail,
    upload_thread_failure_text,
    upload_workflow_detail,
    uploaded_result_dir,
)
from Modules.lvs_tui_view_models import profile_row_label


class TuiRunExecutionAdapterMixin:
    async def _apply_post_run_prompt_spec(self, spec: TuiPostRunPromptSpec) -> None:
        presentation = post_run_prompt_presentation(spec)
        if presentation.view_mode:
            self.view_mode = presentation.view_mode
        self._apply_input_state(
            tui_input_state(
                presentation.pending_field,
                placeholder=presentation.placeholder,
                detail=presentation.detail,
                enabled=presentation.enabled,
                focus=presentation.focus,
            )
        )
        if presentation.sidebar_title:
            self.query_one("#sidebar-title").update(presentation.sidebar_title)
        if presentation.sidebar_options:
            list_view = self.query_one("#items")
            await self._replace_sidebar_labels(
                list_view,
                list(presentation.sidebar_options),
                selected_index=presentation.selected_index,
                focus=True,
            )
        self._set_status(presentation.status)

    def action_run_selected(self) -> None:
        if self.view_mode == "settings":
            self._set_detail(self.service.toggle_bool_setting_text("google_drive_move_to_uploaded_on_success"))
            self._set_status("Settings updated | toggle move successful uploads")
            return
        if self.view_mode not in {"profiles", "setup"} or self.selected_profile is None:
            self._set_detail("Select a profile first.")
            return
        if self.run_in_progress:
            self._set_detail("A run is already in progress.")
            return
        if self.run_setup is None or self.run_setup.profile_path != self.selected_profile.path:
            self.run_setup = self.service.create_run_setup(self.selected_profile.path)
        run_action = next(
            (action for action in self.service.setup_action_specs(self.run_setup) if action.action == "run_selected"),
            FrontendActionSpec("u", "run_selected", label="Review and run"),
        )
        self._handle_sync_run_setup_action(run_action)
        if not self.confirm_run:
            try:
                prepared_flow = self._prepare_run_confirmation_flow(save_blocked_report=False)
                readiness_text = self._prepared_run_readiness_text(prepared_flow)
                can_run = not bool(getattr(getattr(prepared_flow, "preflight_action", None), "blocked", False))
            except Exception:
                readiness_text = self._run_confirmation_readiness_text()
                can_run = True
            self.confirm_run = can_run
            presentation = run_confirmation_presentation(
                profile_name=self.selected_profile.name,
                setup_summary=self.service.run_setup_summary_text(self.run_setup),
                readiness_text=readiness_text,
                can_run=can_run,
            )
            self._set_detail(presentation.detail)
            return
        try:
            prepared_flow = self._prepare_run_confirmation_flow(save_blocked_report=True)
            if bool(getattr(getattr(prepared_flow, "preflight_action", None), "blocked", False)):
                self.confirm_run = False
                self._set_detail(
                    run_confirmation_presentation(
                        profile_name=self.selected_profile.name,
                        setup_summary=self.service.run_setup_summary_text(self.run_setup),
                        readiness_text=self._prepared_run_readiness_text(prepared_flow),
                        can_run=False,
                    ).detail
                )
                return
        except Exception as exc:
            self.confirm_run = False
            self._set_detail(f"Run readiness check failed:\n{exc}")
            return
        self.confirm_run = False
        self.run_in_progress = True
        self.run_cancel_requested = False
        self.run_cancel_event.clear()
        profile = self.selected_profile
        self.run_live_lines = []
        self.run_live_profile_name = profile.name
        self.run_live_phase_line = ""
        self.run_status_tracker.reset()
        self.view_mode = "run_active"
        presentation = initial_run_active_presentation(
            profile.name,
            float(self.run_setup.heatsoak_minutes or 0.0) if self.run_setup else 0.0,
        )
        self._set_status(presentation.status)
        self._set_detail(presentation.detail)
        asyncio.create_task(self._show_run_active_sidebar())
        try:
            self.set_timer(0.1, lambda: self._set_detail(self._run_progress_text()))
        except Exception:
            pass
        thread = threading.Thread(target=self._run_profile_thread, args=(profile,), daemon=True)
        thread.start()

    def action_edit_wall_wattage(self) -> None:
        if self.view_mode == "settings":
            self._set_detail(self.service.toggle_bool_setting_text("prompt_for_wall_wattage"))
            self._set_status("Settings updated | wall-wattage prompt")
            return
        if self.last_run_dir is None or self.last_run_metadata is None:
            self._set_detail("No completed TUI run is available for wall-wattage entry yet.")
            return
        outcome = self.service.wall_wattage_prompt_outcome(self.last_run_dir)
        spec = post_run_wall_wattage_prompt_spec(
            outcome,
            placeholder="Enter max wall wattage, for example 850 or 850W, then press Enter",
        )
        self._apply_input_state(
            tui_input_state(
                spec.pending_field,
                placeholder=spec.placeholder,
                detail=spec.detail,
                enabled=spec.enabled,
                focus=spec.focus,
            )
        )
        self._set_status(spec.status)

    def action_upload_last_result(self) -> None:
        if self.view_mode == "settings":
            self._set_detail(self.service.toggle_bool_setting_text("google_drive_prompt_after_run"))
            self._set_status("Settings updated | Google Drive upload prompt")
            return
        self._start_upload_last_result()

    def _start_upload_last_result(self) -> bool:
        if self.last_run_dir is None:
            self._set_detail(self._post_run_operator_text(None, "No completed TUI run is available for upload yet."))
            return False
        if self.upload_in_progress:
            self._set_detail(
                upload_workflow_detail(
                    title="Google Drive Upload",
                    result_dir=self.last_run_dir,
                    status="uploading",
                    body=upload_active_detail(self.last_run_dir),
                )
            )
            return False
        self._set_status("Checking Google Drive readiness")
        readiness = self.service.google_drive_readiness()
        if not readiness.get("ready"):
            self._set_detail(
                upload_workflow_detail(
                    title="Google Drive Upload Not Ready",
                    result_dir=self.last_run_dir,
                    status="not ready",
                    body=upload_not_ready_detail(self.last_run_dir, readiness),
                )
            )
            self._set_status("Google Drive not ready")
            return False
        self.upload_in_progress = True
        self._set_status("Google Drive upload active")
        self._set_detail(
            upload_workflow_detail(
                title="Google Drive Upload",
                result_dir=self.last_run_dir,
                status="uploading",
                body=upload_active_detail(self.last_run_dir),
            )
        )
        thread = threading.Thread(target=self._upload_last_result_thread, args=(self.last_run_dir,), daemon=True)
        thread.start()
        return True

    def _run_profile_thread(self, profile) -> None:
        try:
            metadata = self.run_setup.metadata if self.run_setup is not None else None
            heatsoak_minutes = float(self.run_setup.heatsoak_minutes or 0.0) if self.run_setup is not None else 0.0
            result = self.service.run_profile_capture_output(
                profile.path,
                metadata=metadata,
                heatsoak_minutes=heatsoak_minutes,
                setup=self.run_setup,
                output_callback=lambda line: self.call_from_thread(self._append_run_output_line, line),
                progress_callback=lambda event: self.call_from_thread(self._append_run_progress_event, event),
                cancel_check=self.run_cancel_event.is_set,
                operator_stop_source="tui",
            )
            text = run_success_thread_text(self.service, result)
        except RunExecutionError as exc:
            text = run_execution_error_text(exc)
            result = None
        except Exception as exc:
            text = f"Run failed:\n{exc}"
            result = None
        self.call_from_thread(self._finish_run_from_thread, text, result)

    def _append_run_output_line(self, line: str) -> None:
        self.run_status_tracker.update_line(line)
        update = apply_run_output_line(
            line=line,
            output_lines=self.run_live_lines,
            phase_line=self.run_live_phase_line,
            status_snapshot=self.run_status_tracker.snapshot,
            tracker_status_text=self.run_status_tracker.status_text(96),
        )
        if update is None:
            return
        self.run_live_lines = update.output_lines
        self.run_live_phase_line = update.phase_line
        if update.is_progress:
            self._set_status(f"Run active | {update.status_text}")
        if self.run_in_progress:
            self._set_detail(self._run_progress_text())

    def _append_run_progress_event(self, event: RunProgressEvent) -> None:
        self.run_status_tracker.update_event(event)
        self.run_live_phase_line = event.raw_line
        self._set_status(f"Run active | {self.run_status_tracker.status_text(96)}")
        if self.run_in_progress:
            self._set_detail(self._run_progress_text())

    def _run_progress_text(self) -> str:
        return run_progress_text(
            profile_name=self.run_live_profile_name,
            status_snapshot=self.run_status_tracker.snapshot,
            phase_line=self.run_live_phase_line,
            events=self.run_status_tracker.events,
            output_lines=self.run_live_lines,
        )

    def _request_run_cancel(self) -> None:
        if not self.run_in_progress:
            self._set_status("No active run to cancel")
            return
        if not self.run_cancel_requested:
            self.run_cancel_requested = True
            self.run_cancel_event.set()
        self._set_status("Run cancel requested | stopping safely")
        self._set_detail(
            locked_run_detail_text(
                profile_name=self.run_live_profile_name,
                status_snapshot=self.run_status_tracker.snapshot,
                phase_line=self.run_live_phase_line,
                events=self.run_status_tracker.events,
                cancel_requested=True,
            )
        )

    def _upload_last_result_thread(self, result_dir: Path) -> None:
        try:
            payload = self.service.upload_result_folder(result_dir)
            text = self.service.upload_result_outcome(payload).text
        except Exception as exc:
            payload = {}
            text = upload_thread_failure_text(exc)
        self.call_from_thread(self._finish_upload_from_thread, text, payload)

    def _finish_run_from_thread(self, text: str, result) -> None:
        self.run_in_progress = False
        self.run_cancel_requested = False
        self.run_cancel_event.clear()
        self.confirm_run = False
        if result is not None:
            self.last_run_dir = result.run_dir
            self.last_run_metadata = result.metadata
            if self.run_setup is not None:
                try:
                    self.service.save_run_setup_history(self.run_setup)
                except Exception:
                    pass
        transition = post_run_completion_transition(
            result_available=result is not None,
            completed_text=text,
            prompt_for_wall_wattage=(
                result is not None and bool(getattr(self.service.settings, "prompt_for_wall_wattage", True))
            ),
            prompt_for_upload=(result is not None and self._should_post_run_upload_prompt()),
        )
        if transition.action == POST_RUN_ACTION_WALL_WATTAGE:
            asyncio.create_task(
                self._restore_profiles_sidebar_and_begin_wall_wattage_prompt(transition.detail)
            )
            return
        if transition.action == POST_RUN_ACTION_UPLOAD_PROMPT:
            if self._queue_post_run_upload_prompt(transition.detail):
                return
            transition = post_run_completion_transition(
                result_available=True,
                completed_text=transition.detail,
                prompt_for_wall_wattage=False,
                prompt_for_upload=False,
            )
        if transition.action in {POST_RUN_ACTION_COMPLETE, POST_RUN_ACTION_FAILED}:
            asyncio.create_task(self._restore_profiles_sidebar_after_post_run())
            self._set_status(transition.status)
            self._set_detail(
                self._post_run_operator_text(
                    self.last_run_dir if result is not None else None,
                    transition.detail,
                )
            )

    def _begin_post_run_wall_wattage_prompt(self, completed_text: str) -> None:
        outcome = self.service.wall_wattage_prompt_outcome(self.last_run_dir, completed_text)
        spec = post_run_wall_wattage_prompt_spec(outcome)
        self._apply_input_state(
            tui_input_state(
                spec.pending_field,
                placeholder=spec.placeholder,
                detail=spec.detail,
                enabled=spec.enabled,
                focus=spec.focus,
            )
        )
        self._set_status(spec.status)

    async def _restore_profiles_sidebar_and_begin_wall_wattage_prompt(
        self,
        completed_text: str,
    ) -> None:
        # Sidebar restoration focuses the list, so it must complete before the
        # wall-wattage input takes final focus.
        await self._restore_profiles_sidebar_after_post_run()
        self._begin_post_run_wall_wattage_prompt(completed_text)

    def _should_post_run_upload_prompt(self) -> bool:
        return should_prompt_for_post_run_upload(
            self.last_run_dir,
            bool(getattr(self.service.settings, "google_drive_prompt_after_run", True)),
        )

    def _queue_post_run_upload_prompt(self, completed_text: str) -> bool:
        if not self._should_post_run_upload_prompt():
            return False
        asyncio.create_task(self._begin_post_run_upload_prompt(completed_text))
        return True

    async def _begin_post_run_upload_prompt(self, completed_text: str) -> None:
        if not self._should_post_run_upload_prompt():
            self._set_detail(self._post_run_operator_text(self.last_run_dir, completed_text))
            self._set_status("Run complete")
            return
        self.post_run_upload_prompt_text = completed_text
        outcome = self.service.upload_prompt_outcome(self.last_run_dir, completed_text)
        spec = post_run_upload_prompt_spec(outcome)
        await self._apply_post_run_prompt_spec(spec)
        self._set_detail(
            upload_workflow_detail(
                title="Google Drive Upload Prompt",
                result_dir=self.last_run_dir,
                status=spec.status,
                body=(
                    f"{spec.detail}\n\n"
                    "Choose Upload to Google Drive or Skip upload from the left-side list."
                ),
            )
        )

    async def _select_post_run_upload_option(self, index: int) -> None:
        self.pending_input_field = None
        self.pending_input_blank_default = ""
        if index == 0:
            await self._restore_profiles_sidebar_after_post_run()
            self._start_upload_last_result()
            return
        await self._skip_post_run_upload_prompt()

    async def _skip_post_run_upload_prompt(self) -> None:
        base_text = post_run_skip_upload_base_text(
            self.post_run_upload_prompt_text,
            self._post_run_text(self.last_run_dir) if self.last_run_dir is not None else "Run complete",
        )
        await self._restore_profiles_sidebar_after_post_run()
        outcome = self.service.upload_skipped_outcome(base_text)
        self._set_detail(
            upload_workflow_detail(
                title="Google Drive Upload Skipped",
                result_dir=self.last_run_dir,
                status="skipped",
                body=outcome.text,
            )
        )
        self._set_status(outcome.status)

    async def _restore_profiles_sidebar_after_post_run(self) -> None:
        self.view_mode = "profiles"
        self.pending_input_field = None
        self.pending_input_blank_default = ""
        self.post_run_upload_prompt_text = ""
        self.query_one("#sidebar-title").update(
            f"Profiles | {self.service.environment_mode_label()}"
        )
        list_view = self.query_one("#items")
        self.profiles = self.service.list_profiles()
        selected_index = 0
        for index, profile in enumerate(self.profiles):
            if self.selected_profile and profile.path == self.selected_profile.path:
                selected_index = index
        await self._replace_sidebar_labels(
            list_view,
            [profile_row_label(profile) for profile in self.profiles],
            selected_index=selected_index if self.profiles else None,
        )
        self._focus_items()

    async def _show_run_active_sidebar(self) -> None:
        if not self.run_in_progress:
            return
        presentation = initial_run_active_presentation(self.run_live_profile_name or "-")
        self.query_one("#sidebar-title").update(presentation.sidebar_title)
        list_view = self.query_one("#items")
        await self._replace_sidebar_labels(
            list_view,
            list(presentation.sidebar_rows),
            selected_index=0,
        )

    def _interaction_locked(self) -> bool:
        return interaction_locked(self.run_in_progress, self.pending_input_field) or bool(
            getattr(self, "upload_in_progress", False)
        )

    def _show_locked_interaction_message(self, cancel_requested: bool = False) -> None:
        if self.run_in_progress:
            if cancel_requested:
                self._request_run_cancel()
                return
            self._set_status("Run active | navigation locked")
            self._set_detail(
                locked_run_detail_text(
                    profile_name=self.run_live_profile_name,
                    status_snapshot=self.run_status_tracker.snapshot,
                    phase_line=self.run_live_phase_line,
                    events=self.run_status_tracker.events,
                    cancel_requested=cancel_requested,
                )
            )
            return
        if self.upload_in_progress:
            self._set_status("Google Drive upload active | navigation locked")
            self._set_detail(
                upload_workflow_detail(
                    title="Google Drive Upload",
                    result_dir=self.last_run_dir,
                    status="uploading",
                    body=upload_active_detail(self.last_run_dir or Path("-")),
                )
            )
            return
        if self.pending_input_field == "__post_wall_wattage":
            self._set_status("Run complete | waiting for wall wattage")
            self._set_detail(locked_post_run_wall_wattage_text())
            return
        if self.pending_input_field == "__post_upload_prompt" or self.view_mode == "post_run_upload_picker":
            self._set_status("Run complete | waiting for upload choice")
            self._set_detail(locked_post_run_upload_text())
            return
        if self.pending_input_field:
            self._set_status("Input active")
            self._set_detail("Finish or cancel the active input before changing views.")

    def _finish_upload_from_thread(self, text: str, payload: dict) -> None:
        self.upload_in_progress = False
        moved_to = uploaded_result_dir(payload)
        if moved_to is not None:
            self.last_run_dir = moved_to
        status, detail, _outcome = upload_finish_result(payload, text, self.service)
        self._set_status(status)
        upload_status = ""
        if isinstance(payload, dict) and payload.get("result"):
            upload_status = str(payload.get("result"))
        self._set_detail(
            upload_workflow_detail(
                title="Google Drive Upload Complete",
                result_dir=self.last_run_dir,
                status=upload_status or status,
                body=detail,
            )
        )

    def _post_run_text(self, result_dir: Path) -> str:
        return self.service.run_complete_outcome(result_dir).text

    def _post_run_operator_text(self, result_dir: Path | None, text: str, *, upload_status: str = "") -> str:
        artifact_item = None
        if result_dir is not None:
            try:
                artifact_item = self.service.result_artifact_inventory_item(result_dir)
            except Exception:
                artifact_item = None
        return post_run_operator_presentation(
            text,
            result_dir=result_dir,
            artifact_item=artifact_item,
            upload_status=upload_status,
        )

    def _tail_text(self, text: str, limit: int) -> str:
        return tail_text(text, limit)
