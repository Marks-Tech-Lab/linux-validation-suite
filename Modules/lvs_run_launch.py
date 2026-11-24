#!/usr/bin/env python3
"""Shared run-launch delegation for frontends."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
import json
from pathlib import Path
import threading
from typing import Any, Callable, Optional

from .lvs_run_executor import RunExecutor
from .lvs_run_metadata import RunMetadata
from .lvs_service_models import RunResult, RunSetupState


@dataclass
class RunLaunchRequest:
    profile_path: Path
    metadata: Optional[RunMetadata] = None
    heatsoak_minutes: float = 0.0
    setup: Optional[RunSetupState] = None

    @classmethod
    def from_setup(cls, setup: RunSetupState) -> "RunLaunchRequest":
        return cls(
            profile_path=setup.profile_path,
            metadata=setup.metadata,
            heatsoak_minutes=float(setup.heatsoak_minutes or 0.0),
            setup=setup,
        )


class RunLaunchCoordinator:
    """Launch prepared runs through the shared executor."""

    def __init__(self, executor: RunExecutor, *, state_lock_context: Optional[Callable[[], Any]] = None) -> None:
        self.executor = executor
        self.state_lock_context = state_lock_context or nullcontext

    def prepare_execution(self, request: RunLaunchRequest, *, privilege_manager: Any, authorize: Callable[[], bool], frontend_dispatch=None, status=None):
        """Prepare after effective overrides, with any authorization owned by the frontend."""
        from .lvs_storage_thermal_execution import prepare, release_preparation, key, blocked, schedule
        if request.setup is None:
            raise ValueError('Execution preparation requires the effective run setup')
        if frontend_dispatch is None and threading.current_thread() is not threading.main_thread():
            raise RuntimeError('Execution preparation requires the frontend thread')
        profile = request.setup.profile
        try:
            return prepare(profile, privilege_manager, authorize, frontend_dispatch=frontend_dispatch, status=status)
        except Exception as exc:
            release_preparation(profile)
            plans = {key(s): blocked(dict(configuration=json.loads(key(s))),
                        'Thermal Assist preparation failed: ' + str(exc))
                     for s in profile.stages if s.enabled and s.modules.storage_thermal.enabled}
            profile._thermal_execution_preparation = dict(stages=schedule(profile), plans=plans, lease=None)
            return plans

    def review_execution(self, request: RunLaunchRequest, plans, *, review: Callable[[str], bool]) -> bool:
        """Foreground final review. Returning to setup also serves readiness-only use."""
        from .lvs_storage_thermal_execution import preparation_text, release_preparation, schedule
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError('Execution review requires the frontend thread')
        accepted = False
        try:
            receipt = request.setup.profile.__dict__.get('_thermal_execution_preparation', {})
            if receipt.get('stages') != schedule(request.setup.profile) or receipt.get('plans') != plans:
                release_preparation(request.setup.profile)
                plans = {}  # changed/missing preparation cannot appear eligible
            text = preparation_text(request.setup.profile, plans)
            accepted = not text or review(text) is True
            return accepted
        finally:
            if not accepted:release_preparation(request.setup.profile)

    def run_direct(
        self,
        profile_path: Path,
        *,
        metadata: Optional[RunMetadata] = None,
        heatsoak_minutes: float = 0.0,
        setup: Optional[RunSetupState] = None,
        heatsoak_debug_callback: Optional[Callable[[Path], None]] = None,
    ) -> Optional[Path]:
        with self.state_lock_context():
            return self.executor.run_profile_direct(
                profile_path,
                metadata=metadata,
                heatsoak_minutes=heatsoak_minutes,
                setup=setup,
                heatsoak_debug_callback=heatsoak_debug_callback,
            )

    def run_prepared_direct(
        self,
        request: RunLaunchRequest,
        *,
        heatsoak_debug_callback: Optional[Callable[[Path], None]] = None,
    ) -> Optional[Path]:
        return self.run_direct(
            request.profile_path,
            metadata=request.metadata,
            heatsoak_minutes=request.heatsoak_minutes,
            setup=request.setup,
            heatsoak_debug_callback=heatsoak_debug_callback,
        )

    def run_capture(
        self,
        profile_path: Path,
        *,
        metadata: Optional[RunMetadata] = None,
        heatsoak_minutes: float = 0.0,
        setup: Optional[RunSetupState] = None,
        output_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[Any], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        operator_stop_source: str = "cli",
        live_telemetry_callback: Optional[Callable[[Any], None]] = None,
        live_timing_callback: Optional[Callable[[Any], None]] = None,
    ) -> RunResult:
        with self.state_lock_context():
            return self.executor.run_profile_capture_output(
                profile_path,
                metadata=metadata,
                heatsoak_minutes=heatsoak_minutes,
                setup=setup,
                output_callback=output_callback,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                operator_stop_source=operator_stop_source,
                live_telemetry_callback=live_telemetry_callback,
                live_timing_callback=live_timing_callback,
            )

    def run_prepared_capture(
        self,
        request: RunLaunchRequest,
        *,
        output_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[Any], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        operator_stop_source: str = "cli",
        live_telemetry_callback: Optional[Callable[[Any], None]] = None,
        live_timing_callback: Optional[Callable[[Any], None]] = None,
    ) -> RunResult:
        return self.run_capture(
            request.profile_path,
            metadata=request.metadata,
            heatsoak_minutes=request.heatsoak_minutes,
            setup=request.setup,
            output_callback=output_callback,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
            operator_stop_source=operator_stop_source,
            live_telemetry_callback=live_telemetry_callback,
            live_timing_callback=live_timing_callback,
        )
