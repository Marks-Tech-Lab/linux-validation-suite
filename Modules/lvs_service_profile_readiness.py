from __future__ import annotations

"""Profile presentation, dry-run, and readiness facade methods for shared services."""

from pathlib import Path
from typing import Any, Dict, List, Optional

from .lvs_profile_models import StageConfig, ValidationProfile
from .lvs_run_flow import PreparedRunFlow, ProfileValidationDecision, RunPreflightDecision
from .lvs_run_preflight import PreflightReadiness, ProfileReadiness
from .lvs_service_models import FrontendActionSpec, ProfileListEntry, RunSetupState
from .lvs_profile_edit_view import (
    profile_detail_lines as build_profile_detail_lines,
    profile_dry_run_preview_text as build_profile_dry_run_preview_text,
    profile_stage_detail_lines as build_profile_stage_detail_lines,
)


class SuiteProfileReadinessServiceMixin:
    """Prompt-free profile presentation/readiness methods shared by frontends."""

    def list_profiles(self) -> List[ProfileListEntry]:
        return self.profile_reports.list_profiles()

    def profile_summary_text(self, profile_path: Path) -> str:
        return self.profile_reports.profile_summary_text(profile_path)

    def profile_stage_detail_text(self, stage: StageConfig, label: str) -> str:
        lines = build_profile_stage_detail_lines(
            stage,
            label,
            normalize_gpu_preference=self.orchestrator.workload_runner._normalize_gpu_3d_backend_preference,
            gpu_target_summary=self.orchestrator.workload_runner._gpu_target_summary,
            normalize_gpu_intensity=self.orchestrator.workload_runner._normalize_gpu_3d_intensity,
            gpu_preference_catalog=self.orchestrator.workload_runner._gpu_3d_backend_preference_catalog,
            normalize_vram_preference=self.orchestrator.workload_runner._normalize_vram_backend_preference,
        )
        return "\n".join(lines)

    def profile_detail_text(self, profile: ValidationProfile, labels: List[str]) -> str:
        lines = build_profile_detail_lines(
            profile,
            labels,
            menu_group_label=self.profile_loader.menu_group_label,
            stage_detail_lines=lambda stage, label: self.profile_stage_detail_text(stage, label).splitlines(),
        )
        return "\n".join(lines)

    def profile_dry_run_preview_text(self, report: Dict[str, Any]) -> str:
        return build_profile_dry_run_preview_text(
            report,
            self.profile_reports.profile_execution_summary_lines(report),
        )

    def profile_action_for_key(self, key: str) -> FrontendActionSpec:
        return self.profile_reports.profile_action_for_key(key)

    def dry_run_profile(self, profile_path: Path, setup: Optional[RunSetupState] = None) -> Dict[str, Any]:
        readiness = (
            self.run_preflight_manager.inspect_profile_context(profile_path, setup.profile, setup.labels)
            if setup is not None
            else self.run_preflight_manager.inspect_profile(profile_path)
        )
        return self.run_preflight_manager.run_preflight(readiness).report

    def inspect_profile_readiness(self, profile_path: Path) -> ProfileReadiness:
        return self.run_preflight_manager.inspect_profile(profile_path)

    def inspect_profile_run_flow(self, profile_path: Path) -> ProfileValidationDecision:
        return self.run_flow.inspect_profile(profile_path)

    def inspect_setup_run_flow(self, setup: RunSetupState) -> ProfileValidationDecision:
        readiness = self.run_preflight_manager.inspect_profile_context(
            setup.profile_path,
            setup.profile,
            setup.labels,
        )
        return self.run_flow.profile_validation_decision(readiness)

    def run_preflight_readiness(
        self,
        readiness: ProfileReadiness,
        *,
        save_blocked_report: bool = False,
    ) -> PreflightReadiness:
        return self.run_preflight_manager.run_preflight(
            readiness,
            save_blocked_report=save_blocked_report,
        )

    def run_preflight_decision(
        self,
        readiness: ProfileReadiness,
        *,
        save_blocked_report: bool = False,
    ) -> RunPreflightDecision:
        return self.run_flow.preflight_for_run(
            readiness,
            save_blocked_report=save_blocked_report,
        )

    def run_setup_preflight_decision(
        self,
        setup: RunSetupState,
        *,
        save_blocked_report: bool = False,
    ) -> RunPreflightDecision:
        readiness = self.run_preflight_manager.inspect_profile_context(
            setup.profile_path,
            setup.profile,
            setup.labels,
        )
        return self.run_flow.preflight_for_run(
            readiness,
            save_blocked_report=save_blocked_report,
        )

    def prepare_setup_run_flow(
        self,
        setup: RunSetupState,
        *,
        save_blocked_report: bool = False,
    ) -> PreparedRunFlow:
        readiness = self.run_preflight_manager.inspect_profile_context(
            setup.profile_path,
            setup.profile,
            setup.labels,
        )
        return self.run_flow.prepare_setup_run(
            readiness,
            setup,
            save_blocked_report=save_blocked_report,
        )

    def dry_run_summary_text(
        self,
        profile_path: Path,
        setup: Optional[RunSetupState] = None,
        save: bool = False,
    ) -> str:
        report = self.dry_run_profile(profile_path, setup=setup)
        return self.profile_reports.dry_run_summary_text(profile_path, report, setup=setup, save=save)

    def save_dry_run_report(
        self,
        profile_path: Path,
        report: Dict[str, Any],
        setup: Optional[RunSetupState] = None,
        summary_text: str = "",
    ) -> Path:
        return self.profile_reports.save_dry_run_report(
            profile_path,
            report,
            setup=setup,
            summary_text=summary_text,
        )
