from __future__ import annotations

"""Top-level Textual TUI view/action adapter methods."""

from pathlib import Path
import threading

from Modules.lvs_tui_navigation_state import tui_navigation_reset
from Modules.lvs_tui_app_actions_flow import (
    migration_support_sidebar_state,
    profiles_sidebar_state,
    results_sidebar_state,
    settings_sidebar_state,
)
from Modules.lvs_tui_picker_presentation import TuiPickerOpenPresentation, TuiPickerPresentation
from Modules.lvs_tui_input_state import tui_input_state
from Modules.lvs_migration_ux import (
    bundle_candidate_detail,
    destructive_action_count,
    migration_plan_text,
    resolution_label,
    successful_apply_text,
    unresolved_actions,
)
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

    async def action_show_storage_benchmark_info(self) -> None:
        self.view_mode = "storage_benchmark_info"
        self._set_status("Storage Benchmark | Profile module and standalone utility")
        self._apply_navigation_reset(
            tui_navigation_reset(clear_selected_profile=True, clear_selected_result=True)
        )
        self.query_one("#sidebar-title").update("Storage Benchmark")
        await self._replace_sidebar_labels(
            self.query_one("#items"),
            ["Storage Benchmark profile module"],
            selected_index=0,
        )
        self._set_detail(
            "Storage Benchmark\n"
            "=================\n\n"
            "This KDiskMark/CDM-style fio workflow is available as a completion-based validation profile "
            "module. In Profiles, edit or create a profile and add the Storage Benchmark stage template. "
            "It runs to completion, writes artifacts inside the normal run folder, and then advances to "
            "the next stage.\n\n"
            "A standalone utility also remains available at:\n"
            "Main menu -> Run Tests -> Run Storage Benchmark\n\n"
            "Both paths share the same safety resolver, fio backend, health checks, and artifact writers.\n\n"
            "Press Esc or P to return to Profiles."
        )
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

    async def action_show_migration_support(self) -> None:
        if self.view_mode == "settings":
            await self._open_settings_list("cpu_cooler_options")
            return
        self.view_mode = "migration_support"
        self.pending_migration_bundle_path = None
        self.migration_bundle_candidates = []
        self.migration_bundle_purpose = "preview"
        self.migration_resolutions = {}
        self.migration_preview_result = None
        self.pending_migration_resolution_action = None
        self._set_status("Ready | Support / Migrate LVS State")
        self._apply_navigation_reset(tui_navigation_reset(clear_selected_profile=True, clear_selected_result=True))
        presentation = migration_support_sidebar_state()
        self.query_one("#sidebar-title").update(presentation.title)
        list_view = self.query_one("#items")
        await self._replace_sidebar_labels(list_view, list(presentation.rows), selected_index=0, focus=True)
        self._set_detail(
            "Support / Migrate LVS State\n"
            "===========================\n\n"
            "SUPPORT creates a redacted public-safe summary.\n"
            "MIGRATION exports or restores private LVS settings, active custom profiles, and setup history.\n\n"
            "Private bundles are NOT PUBLIC-SAFE. Results, archived profiles, credentials, hardware state, and sensor logs are excluded."
        )

    async def _select_migration_support_action(self, index: int) -> None:
        if index == 0:
            self._set_status("Writing public-safe support summary")
            try:
                self._set_detail(self.service.public_support_export_text())
                self._set_status("Public-safe support summary complete")
            except Exception as exc:
                self._set_detail(f"Public-safe support summary failed:\n{exc}")
                self._set_status("Public-safe support summary failed")
            return
        if index == 1:
            try:
                export_preview = self.service.preview_private_migration_export()
                preview_text = str(export_preview.get("summary_text") or "")
            except Exception:
                self._set_detail("Migration export inventory could not be prepared safely.")
                self._set_status("Migration export preview failed")
                return
            self._begin_migration_input(
                "__migration_private_ack",
                placeholder="Type PRIVATE to create the private bundle",
                detail=(
                    preview_text
                    + "\nType PRIVATE below to acknowledge and create the bundle. Press Esc to cancel."
                ),
            )
        elif index == 2:
            await self._open_migration_bundle_selection("preview")
        elif index == 3:
            await self._open_migration_bundle_selection("apply")

    async def _open_migration_bundle_selection(self, purpose: str) -> None:
        self.migration_bundle_purpose = purpose
        self.migration_resolutions = {}
        self.pending_migration_bundle_path = None
        try:
            self.migration_bundle_candidates = list(self.service.discover_migration_bundles())
        except Exception:
            self._set_detail("Configured migration bundle directory could not be inspected safely.")
            self._set_status("Migration bundle discovery failed")
            return
        self.view_mode = "migration_bundle_select"
        self.query_one("#sidebar-title").update("Select Migration Bundle")
        rows = [candidate.row_label for candidate in self.migration_bundle_candidates]
        rows.extend(("Enter external bundle path", "Back"))
        await self._replace_sidebar_labels(self.query_one("#items"), rows, selected_index=0, focus=True)
        self._set_detail(
            "Select a discovered bundle or enter an operator-controlled external path.\n"
            "Discovery checks direct children of the configured bundle directory only; it never searches the filesystem."
        )
        self._set_status(f"Migration {purpose} | Select bundle")

    async def _select_migration_bundle(self, index: int) -> None:
        count = len(self.migration_bundle_candidates)
        if 0 <= index < count:
            candidate = self.migration_bundle_candidates[index]
            self._set_detail(bundle_candidate_detail(candidate))
            if not candidate.valid:
                self._set_status("Migration bundle invalid — Apply unavailable")
                return
            await self._preview_selected_migration_bundle(candidate.path, self.migration_bundle_purpose)
            return
        if index == count:
            self._begin_migration_input(
                "__migration_external_path",
                placeholder="External migration bundle folder",
                detail="Enter an external bundle folder path. It will be validated before preview; no filesystem search is performed.",
            )
            return
        await self.action_show_migration_support()

    async def _preview_selected_migration_bundle(self, bundle_path: Path, purpose: str) -> None:
        self.pending_migration_bundle_path = bundle_path
        self.migration_resolutions = {}
        self._set_status("Validating migration bundle")
        try:
            preview = self.service.preview_migration_restore(bundle_path, resolutions={})
        except Exception:
            self._set_detail("Migration preview could not be completed safely. Verify the bundle and configured paths.")
            self._set_status("Migration preview failed")
            return
        self.migration_preview_result = preview
        if purpose == "preview" or not preview.valid:
            detail = migration_plan_text(preview.plan)
            if preview.valid:
                detail += "\nType DETAILS to show field/item actions, or press Esc to return."
                self._begin_migration_input("__migration_preview_details", placeholder="DETAILS", detail=detail)
                self._set_status("Migration preview complete — no writes performed")
            else:
                self._set_detail(detail)
                self._set_status("Migration bundle invalid — Apply unavailable")
            return
        await self._continue_migration_resolution()

    async def _continue_migration_resolution(self) -> None:
        preview = self.migration_preview_result
        if preview is None:
            return
        conflicts = unresolved_actions(preview.plan)
        if conflicts:
            action = conflicts[0]
            self.pending_migration_resolution_action = action
            allowed = list(action.get("allowed_resolutions") or [])
            choices = "\n".join(
                f"{index}. {resolution_label(action, resolution)}"
                + (" — destructive" if resolution == "replace_destination" else "")
                for index, resolution in enumerate(allowed, start=1)
            )
            dependencies = action.get("dependencies") or []
            dependency_text = f"\nDependencies: {', '.join(str(item) for item in dependencies)}" if dependencies else ""
            self._begin_migration_input(
                "__migration_conflict_choice",
                placeholder="Resolution number, or CANCEL",
                detail=(
                    migration_plan_text(preview.plan)
                    + f"\nResolve: {action.get('logical_item')} ({action.get('content_class')})\n"
                    + f"{action.get('safe_summary') or action.get('reason_code')}"
                    + dependency_text + "\n\n" + choices
                ),
            )
            self._set_status(f"Migration blocked — {len(conflicts)} unresolved conflict(s)")
            return
        if not preview.valid or not preview.plan.get("apply_ready", False):
            self._set_detail(migration_plan_text(preview.plan, include_details=True))
            self._set_status("Migration blocked")
            return
        await self._prepare_migration_apply_confirmation()

    async def _prepare_migration_apply_confirmation(self) -> None:
        preview = self.migration_preview_result
        if preview is None:
            return
        destructive = destructive_action_count(preview.plan)
        detail = migration_plan_text(preview.plan)
        if destructive:
            self._begin_migration_input(
                "__migration_destructive_plan_confirm",
                placeholder="Type REPLACE to confirm destructive actions",
                detail=detail + "\nType REPLACE to confirm the selected destructive replacements.",
            )
            self._set_status(f"Migration ready — confirm {destructive} destructive action(s)")
            return
        self._begin_migration_input(
            "__migration_restore_apply_confirm",
            placeholder="Type APPLY to perform the reviewed restore",
            detail=detail + "\nType APPLY to perform this final reviewed plan.",
        )
        self._set_status("Migration READY TO APPLY")

    def _begin_migration_input(self, field: str, *, placeholder: str, detail: str) -> None:
        self._apply_input_state(
            tui_input_state(
                field,
                placeholder=placeholder,
                detail=detail,
            )
        )

    async def _commit_migration_input(self, field: str, value: object) -> None:
        raw = str(value or "").strip()
        if field == "__migration_private_ack":
            self._clear_setup_input(focus_items=True)
            if raw != "PRIVATE":
                self._set_detail("Private migration export cancelled; no bundle was written.")
                self._set_status("Private migration export cancelled")
                return
            self._set_status("Creating private migration bundle")
            try:
                result = self.service.create_private_migration_bundle(acknowledge_private_data=True)
                self.pending_migration_bundle_path = result.bundle_dir
                self._begin_migration_input(
                    "__migration_post_create",
                    placeholder="Type PREVIEW, or press Enter to return",
                    detail=result.summary_text + "\nType PREVIEW to inspect this bundle now.",
                )
                self._set_status("Private migration bundle complete")
            except Exception:
                self._set_detail("Private migration export failed without exposing private file details.")
                self._set_status("Private migration export failed")
            return

        if field == "__migration_post_create":
            bundle_path = self.pending_migration_bundle_path
            self._clear_setup_input(focus_items=True)
            if raw == "PREVIEW" and bundle_path is not None:
                await self._preview_selected_migration_bundle(bundle_path, "preview")
            else:
                await self.action_show_migration_support()
            return

        if field == "__migration_external_path":
            self._clear_setup_input(focus_items=True)
            if not raw:
                await self._open_migration_bundle_selection(self.migration_bundle_purpose)
                return
            await self._preview_selected_migration_bundle(Path(raw).expanduser(), self.migration_bundle_purpose)
            return

        if field == "__migration_preview_details":
            self._clear_setup_input(focus_items=True)
            preview = self.migration_preview_result
            if raw == "DETAILS" and preview is not None:
                self._set_detail(migration_plan_text(preview.plan, include_details=True))
                self._set_status("Migration preview details — no writes performed")
            else:
                await self.action_show_migration_support()
            return

        if field == "__migration_conflict_choice":
            action = self.pending_migration_resolution_action
            if raw.upper() == "CANCEL" or action is None:
                self._clear_setup_input(focus_items=True)
                self._set_detail("Migration cancelled; conflict selections were not applied and no writes were performed.")
                self._set_status("Migration cancelled")
                return
            allowed = list(action.get("allowed_resolutions") or [])
            try:
                resolution = allowed[int(raw) - 1]
            except (ValueError, IndexError):
                await self._continue_migration_resolution()
                return
            if resolution == "replace_destination":
                self._begin_migration_input(
                    "__migration_replace_resolution_confirm",
                    placeholder="Type REPLACE to select destructive replacement",
                    detail="Replace destination is destructive. Type REPLACE to select it, or press Esc to cancel.",
                )
                return
            await self._apply_migration_resolution(str(action.get("action_id")), resolution)
            return

        if field == "__migration_replace_resolution_confirm":
            action = self.pending_migration_resolution_action
            if raw != "REPLACE" or action is None:
                await self._continue_migration_resolution()
                return
            await self._apply_migration_resolution(str(action.get("action_id")), "replace_destination")
            return

        if field == "__migration_destructive_plan_confirm":
            if raw != "REPLACE":
                self._clear_setup_input(focus_items=True)
                self._set_detail("Migration cancelled; no writes were performed.")
                self._set_status("Migration cancelled")
                return
            preview = self.migration_preview_result
            self._begin_migration_input(
                "__migration_restore_apply_confirm",
                placeholder="Type APPLY to perform the reviewed restore",
                detail=migration_plan_text(preview.plan if preview is not None else {})
                + "\nDestructive choices confirmed. Type APPLY to begin the transaction.",
            )
            self._set_status("Migration READY TO APPLY — awaiting APPLY")
            return

        if field in {"__migration_restore_preview_path", "__migration_restore_apply_path"}:
            self._clear_setup_input(focus_items=True)
            if not raw:
                self._set_detail("Migration bundle path is required; no writes were performed.")
                self._set_status("Migration path required")
                return
            purpose = "preview" if field == "__migration_restore_preview_path" else "apply"
            await self._preview_selected_migration_bundle(Path(raw).expanduser(), purpose)
            return

        if field == "__migration_restore_apply_confirm":
            bundle_path = self.pending_migration_bundle_path
            self.pending_migration_bundle_path = None
            self._clear_setup_input(focus_items=True)
            if raw != "APPLY" or bundle_path is None:
                self._set_detail("Migration restore cancelled; no writes were performed.")
                self._set_status("Migration restore cancelled")
                return
            self._set_status("Applying reviewed migration restore")
            try:
                result = self.service.apply_migration_restore(
                    bundle_path, confirmed=True, resolutions=dict(self.migration_resolutions),
                )
                if result.applied:
                    self._set_detail(successful_apply_text(result.plan))
                    self._set_status("Migration applied — RESTART LVS")
                else:
                    errors = [item for item in result.plan.get("errors", []) if isinstance(item, dict)]
                    drift = any(item.get("error_code") in {
                        "DESTINATION_CHANGED_AFTER_PREVIEW", "RESOLUTION_ACTION_UNKNOWN"
                    } for item in errors)
                    self.migration_resolutions = {}
                    self._set_detail(
                        "Destination state changed.\nA new migration preview is required.\n"
                        if drift else migration_plan_text(result.plan, include_details=True)
                    )
                    self._set_status("New migration preview required" if drift else "Migration restore failed")
            except Exception:
                self._set_detail("Migration restore failed safely. Verify the bundle and configured migration paths.")
                self._set_status("Migration restore failed")

    async def _apply_migration_resolution(self, action_id: str, resolution: str) -> None:
        bundle_path = self.pending_migration_bundle_path
        if bundle_path is None:
            return
        self.migration_resolutions[action_id] = resolution
        self._clear_setup_input(focus_items=True)
        try:
            preview = self.service.preview_migration_restore(
                bundle_path, resolutions=dict(self.migration_resolutions),
            )
        except Exception:
            self._set_detail("Migration preview recalculation failed safely; no writes were performed.")
            self._set_status("Migration preview failed")
            return
        errors = [item for item in preview.plan.get("errors", []) if isinstance(item, dict)]
        if any(item.get("error_code") in {"DESTINATION_CHANGED_AFTER_PREVIEW", "RESOLUTION_ACTION_UNKNOWN"}
            for item in errors):
            self.migration_resolutions = {}
            self.migration_preview_result = None
            self._set_detail("Destination state changed.\nA new migration preview is required.")
            self._set_status("New migration preview required")
            return
        self.migration_preview_result = preview
        await self._continue_migration_resolution()

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
        if self.view_mode == "settings":
            self._set_detail(self.service.google_drive_readiness_text())
            self._set_status("Settings | Google Drive readiness")
            return
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

    async def action_copy_profile(self) -> None:
        if self.selected_profile is None:
            self._set_detail("Select a source profile first.")
            return
        try:
            source = self.service.create_profile_edit(self.selected_profile.path)
            self.profile_edit = source
            await self._begin_profile_copy_selection("copy")
        except Exception as exc:
            self._set_detail(f"Unable to copy profile:\n{exc}")

    async def action_new_profile(self) -> None:
        if self.view_mode == "settings_list":
            self._begin_settings_list_input("rename")
            return
        if self.view_mode == "settings":
            self._set_detail(
                self.service.toggle_bool_setting_text("strict_threshold_recommendation_warnings")
            )
            self._set_status("Settings updated | strict threshold recommendation warnings")
            return
        self._set_status("Creating new profile")
        self._apply_navigation_reset(tui_navigation_reset(clear_selected_profile=True))
        try:
            self.profile_edit = self.service.create_new_profile_edit()
            self.profile_edit_selected_index = 0
            await self._show_profile_edit(
                "Blank profile created in memory. Choose its name and group, add stages, then Save when ready."
            )
            self._begin_profile_name_input()
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
