#!/usr/bin/env python3
"""Shared run-flow decisions for frontends."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .lvs_run_launch import RunLaunchRequest
from .lvs_run_preflight import PreflightReadiness, ProfileReadiness, RunPreflightManager
from .lvs_service_models import RunSetupState


@dataclass
class ProfileValidationDecision:
    readiness: ProfileReadiness
    errors: list[str]
    warnings: list[str]

    @property
    def blocked(self) -> bool:
        return bool(self.errors)


@dataclass
class RunPreflightDecision:
    readiness: ProfileReadiness
    preflight: PreflightReadiness
    errors: list[str]
    warnings: list[str]

    @property
    def report(self) -> dict:
        return self.preflight.report

    @property
    def skipped_stage_count(self) -> int:
        return self.preflight.skipped_stage_count

    @property
    def report_dir(self) -> Optional[Path]:
        return self.preflight.report_dir

    @property
    def runnable(self) -> bool:
        return bool(self.report.get("runnable"))

    @property
    def blocked(self) -> bool:
        return not self.runnable


@dataclass
class RunPreflightActionSummary:
    errors: list[str]
    warnings: list[str]
    blocked: bool
    report_dir: Optional[Path]
    runnable_stage_count: int
    skipped_stage_count: int
    skip_notice: Optional[str]


@dataclass
class PreparedRunFlow:
    readiness: ProfileReadiness
    setup: RunSetupState
    preflight_decision: RunPreflightDecision
    preflight_action: RunPreflightActionSummary
    launch_request: RunLaunchRequest


def build_run_preflight_action_summary(decision: RunPreflightDecision) -> RunPreflightActionSummary:
    report = decision.report if isinstance(decision.report, dict) else {}
    runnable_stage_count = int(report.get("runnable_stage_count", 0) or 0)
    skipped_stage_count = int(decision.skipped_stage_count or 0)
    skip_notice = None
    if skipped_stage_count > 0:
        skip_notice = (
            f"Proceeding with {runnable_stage_count} runnable stage(s); "
            f"{skipped_stage_count} stage(s) will be skipped for this run."
        )
    return RunPreflightActionSummary(
        errors=list(decision.errors),
        warnings=list(decision.warnings),
        blocked=decision.blocked,
        report_dir=decision.report_dir,
        runnable_stage_count=runnable_stage_count,
        skipped_stage_count=skipped_stage_count,
        skip_notice=skip_notice,
    )


class RunFlowCoordinator:
    """Coordinate profile validation and preflight decisions."""

    def __init__(self, preflight_manager: RunPreflightManager) -> None:
        self.preflight_manager = preflight_manager

    def inspect_profile(self, profile_path: Path) -> ProfileValidationDecision:
        readiness = self.preflight_manager.inspect_profile(profile_path)
        return self.profile_validation_decision(readiness)

    def profile_validation_decision(self, readiness: ProfileReadiness) -> ProfileValidationDecision:
        validation = readiness.validation if isinstance(readiness.validation, dict) else {}
        return ProfileValidationDecision(
            readiness=readiness,
            errors=list(validation.get("errors") or []),
            warnings=list(validation.get("warnings") or []),
        )

    def preflight_for_run(
        self,
        readiness: ProfileReadiness,
        *,
        save_blocked_report: bool = True,
    ) -> RunPreflightDecision:
        preflight = self.preflight_manager.run_preflight(
            readiness,
            save_blocked_report=save_blocked_report,
        )
        validation = preflight.report.get("validation") if isinstance(preflight.report.get("validation"), dict) else {}
        return RunPreflightDecision(
            readiness=readiness,
            preflight=preflight,
            errors=list(validation.get("errors") or []),
            warnings=list(validation.get("warnings") or []),
        )

    def prepare_setup_run(
        self,
        readiness: ProfileReadiness,
        setup: RunSetupState,
        *,
        save_blocked_report: bool = True,
    ) -> PreparedRunFlow:
        preflight_decision = self.preflight_for_run(
            readiness,
            save_blocked_report=save_blocked_report,
        )
        return PreparedRunFlow(
            readiness=readiness,
            setup=setup,
            preflight_decision=preflight_decision,
            preflight_action=build_run_preflight_action_summary(preflight_decision),
            launch_request=RunLaunchRequest.from_setup(setup),
        )
