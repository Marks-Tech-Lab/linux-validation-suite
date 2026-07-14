#!/usr/bin/env python3
"""Shared run-launch delegation for frontends."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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

    def __init__(self, executor: RunExecutor) -> None:
        self.executor = executor

    def run_direct(
        self,
        profile_path: Path,
        *,
        metadata: Optional[RunMetadata] = None,
        heatsoak_minutes: float = 0.0,
        setup: Optional[RunSetupState] = None,
        heatsoak_debug_callback: Optional[Callable[[Path], None]] = None,
    ) -> Optional[Path]:
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
    ) -> RunResult:
        return self.executor.run_profile_capture_output(
            profile_path,
            metadata=metadata,
            heatsoak_minutes=heatsoak_minutes,
            setup=setup,
            output_callback=output_callback,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
            operator_stop_source=operator_stop_source,
        )

    def run_prepared_capture(
        self,
        request: RunLaunchRequest,
        *,
        output_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[Any], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        operator_stop_source: str = "cli",
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
        )
