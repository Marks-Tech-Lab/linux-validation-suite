#!/usr/bin/env python3
"""CLI diagnostics adapter for dry-run and diagnostic menus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .lvs_migration_ux import (
    bundle_candidate_detail,
    destructive_action_count,
    migration_plan_text,
    resolution_label,
    successful_apply_text,
    unresolved_actions,
)
from .lvs_profile_models import ValidationProfile


class DiagnosticsCliAdapter:
    """Terminal-facing diagnostics workflow wrapper.

    Backend dry-run/report behavior remains on the existing orchestrator and
    profile report services; this class owns only the CLI selection and output
    flow.
    """

    def __init__(self, host: Any) -> None:
        self.host = host

    def diagnostics_menu(self) -> None:
        host = self.host
        while True:
            print("\nDiagnostics / Dependencies")
            print("1. Dry Run / Diagnostics")
            print("2. Dependency Check")
            print("3. Support / Migrate LVS State")
            print("4. Audit Profiles")
            print("5. Back")
            choice = host._input("Select: ").strip()
            if choice == "1":
                self.dry_run_diagnostics()
            elif choice == "2":
                self.dependency_check()
            elif choice == "3":
                self.migration_support_menu()
            elif choice == "4":
                host._profile_audit()
            elif choice == "5":
                return

    def migration_support_menu(self) -> None:
        host = self.host
        while True:
            print("\nSupport / Migrate LVS State")
            print("1. Create Public-Safe Support Summary")
            print("2. Export LVS State (Private Bundle)")
            print("3. Preview LVS State Migration")
            print("4. Apply LVS State Migration")
            print("5. Back")
            choice = host._input("Select: ").strip()
            try:
                if choice == "1":
                    result = host.local_migration_manager.export_public_support()
                    print(result.summary_text, end="")
                elif choice == "2":
                    preview = host.local_migration_manager.preview_private_bundle_export()
                    print(preview["summary_text"], end="")
                    warning = host._input(
                        "Type PRIVATE to acknowledge this bundle is not public-safe and create it: "
                    ).strip()
                    if warning != "PRIVATE":
                        print("Private migration export cancelled.")
                        continue
                    upload = preview.get("summary", {}).get("upload", {})
                    include_credentials = False
                    if upload.get("configured") and upload.get("credentials_available"):
                        print("Configured upload credentials were found.")
                        print("Including them makes this bundle contain SECRET authentication material.")
                        print("1. Include credentials")
                        print("2. Exclude credentials — destination upload will require relinking")
                        print("3. Cancel")
                        credential_choice = host._input("Select: ").strip()
                        if credential_choice == "1":
                            include_credentials = True
                        elif credential_choice == "2":
                            include_credentials = False
                        else:
                            print("Private migration export cancelled.")
                            continue
                    elif upload.get("configured"):
                        print("Configured upload credentials could not be exported safely.")
                        continuation = host._input(
                            "Type EXCLUDE to continue with an incomplete bundle, or press Enter to cancel: "
                        ).strip()
                        if continuation != "EXCLUDE":
                            print("Private migration export cancelled.")
                            continue
                    result = host.local_migration_manager.create_private_bundle(
                        acknowledge_private_data=True,
                        include_upload_credentials=include_credentials,
                    )
                    print(result.summary_text, end="")
                    follow_up = host._input("Type PREVIEW to preview this new bundle, or press Enter to return: ").strip()
                    if follow_up == "PREVIEW":
                        restored = host.local_migration_manager.preview_restore(result.bundle_dir)
                        print(migration_plan_text(restored.plan, include_details=True), end="")
                elif choice == "3":
                    bundle_path = self._choose_migration_bundle()
                    if bundle_path is not None:
                        preview = host.local_migration_manager.preview_restore(bundle_path)
                        print(migration_plan_text(preview.plan, include_details=True), end="")
                elif choice == "4":
                    bundle_path = self._choose_migration_bundle()
                    if bundle_path is None:
                        continue
                    preview = host.local_migration_manager.preview_restore(bundle_path)
                    resolutions: dict[str, str] = {}
                    print(migration_plan_text(preview.plan), end="")
                    resolved = self._resolve_migration_conflicts(bundle_path, preview, resolutions)
                    if resolved is None:
                        continue
                    preview, resolutions = resolved
                    if not preview.valid or not preview.plan.get("apply_ready", True):
                        continue
                    print(migration_plan_text(preview.plan), end="")
                    if destructive_action_count(preview.plan):
                        destructive = host._input(
                            "This plan replaces destination content. Type REPLACE to confirm destructive choices: "
                        ).strip()
                        if destructive != "REPLACE":
                            print("Migration restore cancelled; no writes performed.")
                            continue
                    confirmation = host._input("Type APPLY to perform this final reviewed plan: ").strip()
                    if confirmation != "APPLY":
                        print("Migration restore cancelled; no writes performed.")
                        continue
                    result = host.local_migration_manager.apply_restore(
                        bundle_path, yes=True, resolutions=resolutions,
                    )
                    print(
                        successful_apply_text(result.plan)
                        if result.applied else migration_plan_text(result.plan, include_details=True),
                        end="",
                    )
                elif choice == "5":
                    return
            except (OSError, ValueError):
                print("Migration operation failed safely. Review the selected bundle and configured migration paths.")

    def _choose_migration_bundle(self) -> Path | None:
        host = self.host
        candidates = host.local_migration_manager.discover_bundles()
        print("\nAvailable migration bundles:")
        if not candidates:
            print("  none found in the configured bundle directory")
        for index, candidate in enumerate(candidates, start=1):
            print(f"{index}. {candidate.row_label}")
        external_index = len(candidates) + 1
        print(f"{external_index}. Enter external bundle path")
        print(f"{external_index + 1}. Back")
        raw = host._input("Select: ").strip()
        try:
            selected = int(raw)
        except ValueError:
            print("Invalid migration bundle selection.")
            return None
        if selected == external_index:
            external = host._input("External migration bundle folder: ").strip()
            return Path(external).expanduser() if external else None
        if selected == external_index + 1:
            return None
        if 1 <= selected <= len(candidates):
            candidate = candidates[selected - 1]
            print(bundle_candidate_detail(candidate))
            if not candidate.valid:
                print("This bundle cannot be applied.")
                return None
            return candidate.path
        print("Invalid migration bundle selection.")
        return None

    def _resolve_migration_conflicts(
        self,
        bundle_path: Path,
        preview: Any,
        resolutions: dict[str, str],
    ) -> tuple[Any, dict[str, str]] | None:
        host = self.host
        while preview.valid and not preview.plan.get("apply_ready", False):
            conflicts = unresolved_actions(preview.plan)
            if not conflicts:
                print(migration_plan_text(preview.plan, include_details=True), end="")
                return None
            action = conflicts[0]
            allowed = list(action.get("allowed_resolutions") or [])
            print(f"\nConflict: {action.get('logical_item')} ({action.get('content_class')})")
            print(str(action.get("safe_summary") or action.get("reason_code")))
            for index, resolution in enumerate(allowed, start=1):
                print(f"{index}. {resolution_label(action, resolution)}")
            print(f"{len(allowed) + 1}. Cancel")
            raw = host._input("Select resolution: ").strip()
            try:
                selected = int(raw)
            except ValueError:
                print("Invalid conflict resolution selection.")
                continue
            if selected == len(allowed) + 1:
                print("Migration restore cancelled; no writes performed.")
                return None
            if not 1 <= selected <= len(allowed):
                print("Invalid conflict resolution selection.")
                continue
            resolution = allowed[selected - 1]
            if resolution == "replace_destination":
                confirmation = host._input("Type REPLACE to confirm this destructive resolution: ").strip()
                if confirmation != "REPLACE":
                    print("Destructive resolution not selected.")
                    continue
            resolutions[str(action.get("action_id"))] = resolution
            preview = host.local_migration_manager.preview_restore(bundle_path, resolutions=resolutions)
            if any(error.get("error_code") in {
                    "DESTINATION_CHANGED_AFTER_PREVIEW", "RESOLUTION_ACTION_UNKNOWN"
                }
                for error in preview.plan.get("errors", []) if isinstance(error, dict)):
                resolutions.clear()
                print("Destination state changed. A new migration preview is required.")
                return None
        return preview, resolutions

    def dry_run_diagnostics(self) -> None:
        host = self.host
        profiles = host.profile_loader.list_profiles()
        if not profiles:
            print("No profiles found.")
            return
        print("\nAvailable profiles:")
        for idx, path in enumerate(profiles, start=1):
            print(f"{idx}. {host._profile_choice_text(path)}")
        raw = host._input("Choose profile: ").strip()
        try:
            profile_path = profiles[int(raw) - 1]
        except Exception:
            print("Invalid selection.")
            return
        profile = host.profile_loader.load_profile(profile_path)
        labels = host.profile_loader.load_segment_labels(profile_path, profile)
        host._ensure_privileged_helper_ready("diagnostics")
        report = host.orchestrator.dry_run(profile_path, profile, labels)
        label_source_info = host.profile_loader.inspect_segment_label_source(profile_path, profile)
        report["label_source"] = label_source_info
        if label_source_info["issues"]:
            report["validation"]["warnings"].extend(label_source_info["issues"])
        report_dir = self.write_diagnostics_report(profile_path, profile, labels, report)
        print("\nDiagnostics saved:")
        print(f"  folder: {report_dir}")
        print(f"  summary: {report_dir / 'diagnostics_summary.txt'}")
        print(f"  full JSON: {report_dir / 'diagnostics.json'}")
        self.print_diagnostics_summary(report)
        show_full = host._input("Print full diagnostics JSON to terminal? [y/N]: ").strip().lower()
        if show_full in {"y", "yes"}:
            print("\nDiagnostics:")
            print(json.dumps(report, indent=2))

    def write_diagnostics_report(
        self,
        profile_path: Path,
        profile: ValidationProfile,
        labels: List[str],
        report: Dict[str, Any],
    ) -> Path:
        return self.host.profile_reports.save_cli_diagnostics_report(
            profile_path,
            profile,
            labels,
            report,
            summary_text=self.diagnostics_summary_text(report),
        )

    def diagnostics_summary_text(self, report: Dict[str, Any]) -> str:
        return self.host.profile_reports.diagnostics_summary_text(report)

    def print_diagnostics_summary(self, report: Dict[str, Any]) -> None:
        print(self.diagnostics_summary_text(report), end="")

    def dependency_check(self) -> None:
        host = self.host
        host._ensure_privileged_helper_ready("Dependency Check")
        result = host.dependency_reports.run_dependency_check(
            host.settings_manager.settings.results_dir,
            sudo_noninteractive_ready=host._sudo_noninteractive_ready,
            memory_module_has_identity=self.memory_module_has_identity,
        )
        print(result.summary_text, end="")
        print(f"Dependency check log: {result.report_dir}")
        print(f"Dependency check summary: {result.report_dir / 'dependency_check_summary.txt'}")
        show_full = host._input("Print full dependency check to terminal? [y/N]: ").strip().lower()
        if show_full in {"y", "yes"}:
            print(result.detail_text, end="")

    def memory_module_has_identity(self, module: Dict[str, Any]) -> bool:
        return any(
            str(module.get(key) or "").strip()
            for key in ("display_part_number", "part_number", "PartNumber", "RawPartNumber")
        )

    def dependency_check_summary_text(self, payload: Dict[str, Any], report_dir: Optional[Path] = None) -> str:
        return self.host.dependency_reports.dependency_check_summary_text(payload, report_dir)
