from __future__ import annotations

"""Top-level Textual TUI view/action adapter methods."""

import threading

from Modules.lvs_tui_navigation_state import tui_navigation_reset
from Modules.lvs_tui_app_actions_flow import profiles_sidebar_state, results_sidebar_state, settings_sidebar_state
from Modules.lvs_tui_picker_presentation import TuiPickerOpenPresentation, TuiPickerPresentation
from Modules.lvs_tui_profile_presentation import profile_summary_presentation
from Modules.lvs_tui_run_setup_presentation import (
    run_setup_no_history_detail,
)
from Modules.lvs_tui_view_models import profile_row_label, result_row_label


class TuiAppActionsAdapterMixin:
    async def _apply_picker_presentation(self, presentation: TuiPickerPresentation) -> None:
        self.view_mode = presentation.view_mode
        self.query_one("#sidebar-title").update(presentation.title)
        list_view = self.query_one("#items")
        await self._replace_sidebar_labels(
            list_view,
            list(presentation.labels),
            selected_index=presentation.selected_index,
            focus=True,
        )
        self._set_detail(presentation.detail)

    async def _apply_setup_picker_open_presentation(self, presentation: TuiPickerOpenPresentation) -> None:
        self.setup_picker_key = presentation.key
        self.setup_picker_options = list(presentation.options)
        self.confirm_run = presentation.confirm_run
        await self._apply_picker_presentation(presentation.picker)

    async def action_show_profiles(self) -> None:
        self.view_mode = "profiles"
        self._set_status("Ready | Profiles")
        self.profiles = self.service.list_profiles()
        self._apply_navigation_reset(tui_navigation_reset(clear_setup_picker=False, clear_selected_result=True))
        presentation = profiles_sidebar_state(
            self.profiles,
            environment_label=self.service.environment_mode_label(),
            row_label=profile_row_label,
        )
        self.query_one("#sidebar-title").update(presentation.title)
        list_view = self.query_one("#items")
        await self._replace_sidebar_labels(
            list_view,
            list(presentation.rows),
            selected_index=presentation.selected_index,
        )
        if presentation.first_item is not None:
            self.selected_profile = presentation.first_item
            self._show_profile_summary(self.selected_profile)
            self._focus_items()
        else:
            self.selected_profile = None
            self._set_detail(presentation.empty_detail)

    async def action_show_results(self) -> None:
        self.view_mode = "results"
        self._set_status("Ready | Results")
        self.results = self.service.list_results()
        self._apply_navigation_reset(tui_navigation_reset(clear_setup_picker=False, clear_selected_profile=True))
        presentation = results_sidebar_state(
            self.results,
            row_label=result_row_label,
            selected_path=getattr(self, "last_run_dir", None),
        )
        self.query_one("#sidebar-title").update(presentation.title)
        list_view = self.query_one("#items")
        await self._replace_sidebar_labels(
            list_view,
            list(presentation.rows),
            selected_index=presentation.selected_index,
        )
        if presentation.first_item is not None:
            self.selected_result = presentation.first_item
            self._show_result_summary(self.selected_result)
            self._focus_items()
        else:
            self.selected_result = None
            self._set_detail(presentation.empty_detail)

    async def action_show_settings(self) -> None:
        self.view_mode = "settings"
        self._set_status("Ready | Settings")
        self._apply_navigation_reset(
            tui_navigation_reset(
                clear_setting_list=True,
                clear_selected_profile=True,
                clear_selected_result=True,
            )
        )
        presentation = settings_sidebar_state()
        self.query_one("#sidebar-title").update(presentation.title)
        list_view = self.query_one("#items")
        await self._replace_sidebar_labels(list_view, list(presentation.rows), selected_index=presentation.selected_index)
        self._set_detail(self.service.settings_summary_text())
        self._focus_items()

    def action_dry_run(self) -> None:
        if self.selected_profile is None:
            self._set_detail("Select a profile first.")
            return
        if getattr(self, "dry_run_in_progress", False):
            self._set_detail(
                "Dry Run In Progress\n"
                "===================\n\n"
                "A dry run/readiness check is already running. Results will appear here when it completes."
            )
            return
        self._set_status(f"Running dry run | {self.selected_profile.name}")
        self._apply_navigation_reset(tui_navigation_reset())
        self._set_detail(
            "Dry Run In Progress\n"
            "===================\n\n"
            f"Profile: {self.selected_profile.name}\n\n"
            "Checking profile readiness, backend availability, telemetry coverage, and setup blockers.\n"
            "The result will appear here when the dry run completes."
        )
        self.dry_run_in_progress = True
        profile = self.selected_profile
        setup = self.run_setup if self.run_setup and self.run_setup.profile_path == profile.path else None
        thread = threading.Thread(target=self._dry_run_thread, args=(profile, setup), daemon=True)
        thread.start()

    def _dry_run_thread(self, profile, setup) -> None:
        try:
            text = self.service.dry_run_summary_text(profile.path, setup=setup, save=True)
            status = f"Dry run complete | {profile.name}"
        except Exception as exc:
            text = f"Dry run failed:\n{exc}"
            status = "Dry run failed"
        self.call_from_thread(self._finish_dry_run_from_thread, status, text)

    def _finish_dry_run_from_thread(self, status: str, text: str) -> None:
        self.dry_run_in_progress = False
        self._set_detail(text)
        self._set_status(status)

    def action_dependency_check(self) -> None:
        self._set_status("Checking dependencies")
        self._apply_navigation_reset(tui_navigation_reset())
        self._set_detail("Checking dependencies and telemetry readiness...")
        try:
            self._set_detail(self.service.dependency_summary_text())
            self._set_status("Dependency check complete")
        except Exception as exc:
            self._set_detail(f"Dependency check failed:\n{exc}")
            self._set_status("Dependency check failed")

    async def action_setup_run(self) -> None:
        if self.view_mode != "profiles" or self.selected_profile is None:
            self._set_detail("Select a profile first.")
            return
        self._set_status(f"Run setup | {self.selected_profile.name}")
        self._apply_navigation_reset(tui_navigation_reset())
        if self.run_setup is None or self.run_setup.profile_path != self.selected_profile.path:
            self.run_setup = self.service.create_run_setup(self.selected_profile.path)
        await self._show_run_setup_sidebar()

    async def action_edit_profile(self) -> None:
        if self.selected_profile is None:
            self._set_detail("Select a profile first.")
            return
        self._set_status(f"Editing profile | {self.selected_profile.name}")
        self._apply_navigation_reset(tui_navigation_reset())
        try:
            self.profile_edit = self.service.create_profile_edit(self.selected_profile.path)
            await self._show_profile_edit()
        except Exception as exc:
            self._set_detail(f"Unable to open profile editor:\n{exc}")

    async def action_new_profile(self) -> None:
        self._set_status("Creating new profile")
        self._apply_navigation_reset(tui_navigation_reset(clear_selected_profile=True))
        try:
            self.profile_edit = self.service.create_new_profile_edit()
            self.profile_edit_selected_index = 0
            await self._show_profile_edit("New profile created in memory. Rename it, add stages, then press S to save.")
        except Exception as exc:
            self._set_detail(f"Unable to create profile:\n{exc}")

    async def action_load_setup_history(self) -> None:
        if self.selected_profile is None:
            self._set_detail("Select a profile first.")
            return
        self._set_status("Loading setup history")
        if self.run_setup is None or self.run_setup.profile_path != self.selected_profile.path:
            self.run_setup = self.service.create_run_setup(self.selected_profile.path)
        self.pending_history_entry = None
        self.history_entries = self.service.run_setup_history_entries()
        self._apply_navigation_reset(tui_navigation_reset(clear_setup_picker=False))
        if not self.history_entries:
            await self._show_run_setup_sidebar()
            self._set_detail(run_setup_no_history_detail(self.service.run_setup_summary_text(self.run_setup)))
            return
        await self._show_setup_history_entries()

    def _show_profile_summary(self, profile) -> None:
        try:
            self._set_detail(
                profile_summary_presentation(
                    environment_mode=self.service.environment_mode_label(),
                    enhanced_telemetry=self.service.enhanced_telemetry_label(),
                    profile_summary=self.service.profile_summary_text(profile.path),
                )
            )
        except Exception as exc:
            self._set_detail(f"Unable to load profile:\n{profile.path}\n\n{exc}")

    def _audit_profiles(self) -> None:
        try:
            self._set_detail(self.service.profile_audit_text(save=True))
        except Exception as exc:
            self._set_detail(f"Profile audit failed:\n{exc}")

    async def _ensure_example_profile(self) -> None:
        try:
            text = self.service.ensure_example_profile_text()
            await self.action_show_profiles()
            self._set_detail(text)
        except Exception as exc:
            self._set_detail(f"Ensure example profile failed:\n{exc}")
