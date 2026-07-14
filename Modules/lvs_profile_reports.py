#!/usr/bin/env python3
"""Profile inventory, summary, audit, and dry-run report helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List

from .lvs_core import APP_NAME, APP_VERSION, now_local_iso
from .lvs_profile_audit import ProfileAuditPayloadBuilder, profile_audit_stage_item as build_profile_audit_stage_item
from .lvs_profile_report_artifacts import ProfileReportArtifactWriter, safe_report_name as build_safe_report_name
from .lvs_profile_report_text import (
    diagnostics_summary_text as build_diagnostics_summary_text,
    dry_run_plan_line,
    dry_run_summary_text as build_dry_run_summary_text,
    legacy_profile_audit_text,
    preflight_summary_text as build_preflight_summary_text,
    profile_audit_item_line,
    profile_audit_item_status,
    profile_execution_cpu_line,
    profile_execution_gpu_3d_line,
    profile_execution_gpu_detail_lines,
    profile_execution_memory_line,
    profile_execution_stage_header_line,
    profile_execution_stage_status,
    profile_execution_summary_lines as build_profile_execution_summary_lines,
    profile_execution_trim_line,
    profile_execution_vram_line,
    profile_summary_text as build_profile_summary_text,
)
from .lvs_result_reports import ResultReportManager
from .lvs_service_models import FrontendActionSpec, ProfileListEntry, RunSetupState


class ProfileReportManager:
    """Frontend-safe profile reporting helpers."""

    PROFILE_ACTIONS = {
        "a": FrontendActionSpec("a", "audit_profiles", label="audit all profiles"),
        "n": FrontendActionSpec("n", "new_profile", label="create a new profile"),
        "e": FrontendActionSpec("e", "ensure_example_profile", label="ensure example profile exists"),
    }

    def __init__(self, profile_loader: Any, validator: Any, result_reports: ResultReportManager) -> None:
        self.profile_loader = profile_loader
        self.validator = validator
        self.result_reports = result_reports
        self.profile_audit_builder = ProfileAuditPayloadBuilder(profile_loader)
        self.artifact_writer = ProfileReportArtifactWriter(profile_loader, result_reports)

    def profile_action_for_key(self, key: str) -> FrontendActionSpec:
        normalized = str(key or "").lower()
        return self.PROFILE_ACTIONS.get(normalized, FrontendActionSpec(normalized, ""))

    def list_profiles(self) -> List[ProfileListEntry]:
        entries: List[ProfileListEntry] = []
        for path in self.profile_loader.list_profiles():
            metadata = self.profile_loader.profile_menu_metadata(path)
            group = str(metadata.get("menu_group") or "custom")
            entries.append(
                ProfileListEntry(
                    path=path,
                    name=path.name,
                    menu_group=group,
                    menu_group_label=self.profile_loader.menu_group_label(group),
                )
            )
        return entries

    def profile_summary_text(self, profile_path: Path) -> str:
        profile = self.profile_loader.load_profile(profile_path)
        labels = self.profile_loader.load_segment_labels(profile_path, profile)
        return build_profile_summary_text(
            profile_path,
            profile,
            labels,
            self.profile_loader.menu_group_label,
        )

    def profile_audit_text(self, save: bool = True) -> str:
        payload = self.profile_audit_builder.legacy_profile_audit_payload(self.validator)
        text = legacy_profile_audit_text(payload)
        if save:
            report_dir = self.save_profile_audit_report(text, payload)
            text += f"\nSaved: {report_dir}\n"
        return text

    def profile_audit_payload(
        self,
        dry_run_builder: Callable[[Path, Any, List[str]], Dict[str, Any]],
    ) -> Dict[str, Any]:
        return self.profile_audit_builder.profile_audit_payload(dry_run_builder)

    def profile_audit_payload_item(
        self,
        profile_path: Path,
        dry_run_builder: Callable[[Path, Any, List[str]], Dict[str, Any]],
    ) -> Dict[str, Any]:
        return self.profile_audit_builder.profile_audit_payload_item(profile_path, dry_run_builder)

    @staticmethod
    def profile_audit_stage_item(stage: Dict[str, Any]) -> Dict[str, Any]:
        return build_profile_audit_stage_item(stage)

    def profile_audit_summary_text(self, payload: Dict[str, Any]) -> str:
        counts = payload.get("counts") or {}
        lines: List[str] = [
            "",
            "Profile Audit",
            "=============",
            f"Profiles folder: {payload.get('profiles_dir')}",
            (
                "Profiles: "
                + f"{counts.get('profiles', 0)} total, {counts.get('runnable', 0)} runnable, "
                + f"{counts.get('blocked', 0)} blocked"
            ),
            f"Validation: {counts.get('validation_errors', 0)} error(s), {counts.get('validation_warnings', 0)} warning(s)",
        ]
        for item in payload.get("profiles") or []:
            name = item.get("profile_name") or item.get("profile_file")
            status = "runnable" if item.get("runnable") else "blocked"
            if not item.get("loaded"):
                status = "load_failed"
            lines.extend(["", f"- {name} ({item.get('profile_file')}): {status}"])
            if item.get("loaded"):
                lines.append(
                    f"  stages: {item.get('runnable_stage_count', 0)}/{item.get('enabled_stage_count', 0)} runnable"
                )
            if item.get("validation_error_count") or item.get("validation_warning_count"):
                lines.append(
                    f"  validation: {item.get('validation_error_count', 0)} error(s), "
                    + f"{item.get('validation_warning_count', 0)} warning(s)"
                )
            for error in list(item.get("errors") or [])[:6]:
                lines.append(f"  [error] {error}")
            if len(item.get("errors") or []) > 6:
                lines.append(f"  ... {len(item.get('errors') or []) - 6} more error(s)")
            for warning in list(item.get("warnings") or [])[:6]:
                lines.append(f"  [warn] {warning}")
            if len(item.get("warnings") or []) > 6:
                lines.append(f"  ... {len(item.get('warnings') or []) - 6} more warning(s)")
            blocked_stages = [
                stage for stage in item.get("stages") or []
                if stage.get("enabled") and not stage.get("runnable")
            ]
            for stage in blocked_stages[:4]:
                label = stage.get("label") or stage.get("stage_id") or "stage"
                lines.append(f"  blocked stage: {label}")
                for issue in list(stage.get("issues") or [])[:3]:
                    lines.append(f"    [issue] {issue}")
            if len(blocked_stages) > 4:
                lines.append(f"  ... {len(blocked_stages) - 4} more blocked stage(s)")
        lines.append("")
        return "\n".join(lines) + "\n"

    def save_profile_audit_report(self, text: str, payload: Dict[str, Any]) -> Path:
        return self.artifact_writer.save_profile_audit_report(text, payload)

    def dry_run_summary_text(
        self,
        profile_path: Path,
        report: Dict[str, Any],
        setup: RunSetupState | None = None,
        save: bool = False,
    ) -> str:
        text = build_dry_run_summary_text(profile_path, report)
        if save:
            report_dir = self.save_dry_run_report(profile_path, report, setup=setup, summary_text=text)
            text += f"\n\nSaved diagnostics: {report_dir}\n"
        return text

    def save_dry_run_report(
        self,
        profile_path: Path,
        report: Dict[str, Any],
        setup: RunSetupState | None = None,
        summary_text: str = "",
    ) -> Path:
        return self.artifact_writer.save_dry_run_report(profile_path, report, setup=setup, summary_text=summary_text)

    def safe_report_name(self, value: str) -> str:
        return build_safe_report_name(value)

    def save_cli_diagnostics_report(
        self,
        profile_path: Path,
        profile: Any,
        labels: List[str],
        report: Dict[str, Any],
        *,
        summary_text: str = "",
    ) -> Path:
        return self.artifact_writer.save_cli_diagnostics_report(
            profile_path,
            profile,
            labels,
            report,
            summary_text=summary_text or self.diagnostics_summary_text(report),
        )

    def save_cli_preflight_report(
        self,
        profile_path: Path,
        profile: Any,
        labels: List[str],
        preflight: Dict[str, Any],
        *,
        runtime_environment: Dict[str, Any] | None = None,
        backends: Dict[str, Any] | None = None,
        backend_details: Dict[str, Any] | None = None,
        summary_text: str = "",
    ) -> Path:
        return self.artifact_writer.save_cli_preflight_report(
            profile_path,
            profile,
            labels,
            preflight,
            runtime_environment=runtime_environment,
            backends=backends,
            backend_details=backend_details,
            summary_text=summary_text or self.preflight_summary_text(preflight),
        )

    def diagnostics_summary_text(self, report: Dict[str, Any]) -> str:
        return build_diagnostics_summary_text(report)

    def preflight_summary_text(self, report: Dict[str, Any]) -> str:
        return build_preflight_summary_text(report)

    def profile_execution_summary_lines(self, report: Dict[str, Any]) -> List[str]:
        return build_profile_execution_summary_lines(report)

    def _write_profile_used(self, report_dir: Path, profile: Any, labels: List[str]) -> None:
        self.artifact_writer.write_profile_used(report_dir, profile, labels)
