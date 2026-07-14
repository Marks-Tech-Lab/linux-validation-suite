#!/usr/bin/env python3
"""CLI diagnostics adapter for dry-run and diagnostic menus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

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
            print("3. Migration / Support")
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
            print("\nMigration / Support")
            print("1. Public-safe Support Summary")
            print("2. Create Private Migration Bundle")
            print("3. Preview Migration Restore")
            print("4. Apply Reviewed Migration Restore")
            print("5. Back")
            choice = host._input("Select: ").strip()
            try:
                if choice == "1":
                    result = host.local_migration_manager.export_public_support()
                    print(result.summary_text, end="")
                elif choice == "2":
                    warning = host._input(
                        "This bundle is NOT public-safe. Type PRIVATE to acknowledge private data: "
                    ).strip()
                    if warning != "PRIVATE":
                        print("Private migration export cancelled.")
                        continue
                    result = host.local_migration_manager.create_private_bundle(
                        acknowledge_private_data=True,
                    )
                    print(result.summary_text, end="")
                elif choice == "3":
                    raw = host._input("Migration bundle folder: ").strip()
                    if raw:
                        print(host.local_migration_manager.preview_restore(Path(raw)).summary_text, end="")
                elif choice == "4":
                    raw = host._input("Migration bundle folder: ").strip()
                    if not raw:
                        continue
                    preview = host.local_migration_manager.preview_restore(Path(raw))
                    print(preview.summary_text, end="")
                    if not preview.valid:
                        continue
                    confirmation = host._input("Type APPLY to perform the reviewed missing-only restore: ").strip()
                    if confirmation != "APPLY":
                        print("Migration restore cancelled; no writes performed.")
                        continue
                    print(host.local_migration_manager.apply_restore(Path(raw), yes=True).summary_text, end="")
                elif choice == "5":
                    return
            except (OSError, ValueError):
                print("Migration operation failed without exposing private file details.")

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
