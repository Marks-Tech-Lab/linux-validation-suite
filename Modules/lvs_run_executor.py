#!/usr/bin/env python3
"""Run execution wrapper for UI frontends."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Callable, Optional

from .lvs_core import now_local_iso
from .lvs_run_execution_context import CallbackStringIO, build_heatsoak_debug, build_profile_run_context
from .lvs_run_lifecycle import phase_line
from .lvs_run_progress import RunProgressEvent, RunStatusSnapshot, RunStatusTracker, parse_progress_event
from .lvs_run_metadata import RunMetadata
from .lvs_service_models import RunResult, RunSetupState


class RunExecutionError(RuntimeError):
    """Carries captured service-run context when execution raises."""

    def __init__(
        self,
        message: str,
        *,
        output: str,
        metadata: RunMetadata,
        progress_events: list[RunProgressEvent],
        run_status: RunStatusSnapshot,
        run_dir: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.output = output
        self.metadata = metadata
        self.progress_events = progress_events
        self.run_status = run_status
        self.run_dir = run_dir


class RunExecutor:
    """Captures CLI-style run output while delegating actual execution."""

    def __init__(
        self,
        *,
        settings: Any,
        profile_loader: Any,
        orchestrator: Any,
        default_run_metadata: Callable[[Path], RunMetadata],
        ensure_enhanced_telemetry_ready: Callable[[], bool],
        run_heatsoak_if_requested: Callable[..., bool],
    ) -> None:
        self.settings = settings
        self.profile_loader = profile_loader
        self.orchestrator = orchestrator
        self.default_run_metadata = default_run_metadata
        self.ensure_enhanced_telemetry_ready = ensure_enhanced_telemetry_ready
        self.run_heatsoak_if_requested = run_heatsoak_if_requested

    def run_profile_capture_output(
        self,
        profile_path: Path,
        metadata: Optional[RunMetadata] = None,
        heatsoak_minutes: float = 0.0,
        setup: Optional[RunSetupState] = None,
        output_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[RunProgressEvent], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        operator_stop_source: str = "cli",
    ) -> RunResult:
        context = self._profile_run_context(profile_path, metadata, setup)
        profile = context.profile
        labels = context.labels
        run_metadata = context.metadata
        progress_events: list[RunProgressEvent] = []
        progress_tracker = RunStatusTracker()

        def capture_line(line: str) -> None:
            if output_callback:
                output_callback(line)
            event = parse_progress_event(line)
            if event is not None:
                progress_events.append(event)
                progress_tracker.update_event(event)
                if progress_callback:
                    progress_callback(event)

        def cancelled() -> bool:
            return bool(cancel_check is not None and cancel_check())

        output = CallbackStringIO(capture_line)
        run_dir = None
        try:
            with contextlib.redirect_stdout(output):
                self.ensure_enhanced_telemetry_ready()
                if cancelled():
                    output.write(phase_line(now_local_iso(), "operator-stop", source=operator_stop_source) + "\n")
                    raise RuntimeError("run cancelled before workload start")
                heatsoak_debug = None
                heatsoak_requested = float(heatsoak_minutes or 0.0) > 0
                if float(heatsoak_minutes or 0.0) > 0 and bool(getattr(run_metadata, "advanced_debug_logging", False)):
                    run_dir, heatsoak_debug = build_heatsoak_debug(self.orchestrator, profile.profile_name)
                if heatsoak_requested:
                    output.write(
                        phase_line(
                            now_local_iso(),
                            "heatsoak-start",
                            minutes=f"{float(heatsoak_minutes or 0.0):g}",
                        )
                        + "\n"
                    )
                if cancelled():
                    output.write(phase_line(now_local_iso(), "operator-stop", source=operator_stop_source) + "\n")
                    raise RuntimeError("run cancelled before heatsoak start")
                if not self.run_heatsoak_if_requested(
                    heatsoak_minutes,
                    advanced_debug=heatsoak_debug,
                    cancel_check=cancel_check,
                ):
                    if heatsoak_requested:
                        output.write(
                            phase_line(now_local_iso(), "heatsoak-cancel", verdict="cancelled")
                            + "\n"
                        )
                    raise RuntimeError("run cancelled during heatsoak")
                if heatsoak_requested:
                    output.write(
                        phase_line(now_local_iso(), "heatsoak-end", verdict="completed")
                        + "\n"
                    )
                if cancelled():
                    output.write(phase_line(now_local_iso(), "operator-stop", source=operator_stop_source) + "\n")
                    raise RuntimeError("run cancelled before validation stages")
                run_dir = self.orchestrator.run(
                    profile_path,
                    profile,
                    labels,
                    run_metadata,
                    run_dir=run_dir,
                    cancel_check=cancel_check,
                    operator_stop_source=operator_stop_source,
                )
        except Exception as exc:
            output.write(
                phase_line(
                    now_local_iso(),
                    "run-error",
                    verdict="failed",
                    error=type(exc).__name__,
                )
                + "\n"
            )
            raise RunExecutionError(
                str(exc),
                output=output.getvalue(),
                metadata=run_metadata,
                progress_events=progress_events,
                run_status=progress_tracker.snapshot,
                run_dir=run_dir,
            ) from exc
        return RunResult(
            run_dir=run_dir,
            output=output.getvalue(),
            metadata=run_metadata,
            progress_events=progress_events,
            run_status=progress_tracker.snapshot,
        )

    def run_profile_direct(
        self,
        profile_path: Path,
        metadata: Optional[RunMetadata] = None,
        heatsoak_minutes: float = 0.0,
        setup: Optional[RunSetupState] = None,
        heatsoak_debug_callback: Optional[Callable[[Path], None]] = None,
    ) -> Optional[Path]:
        """Run a profile without output capture, for the CLI path."""
        context = self._profile_run_context(profile_path, metadata, setup)
        profile = context.profile
        labels = context.labels
        run_metadata = context.metadata

        self.ensure_enhanced_telemetry_ready()
        run_dir = None
        heatsoak_debug = None
        if float(heatsoak_minutes or 0.0) > 0 and bool(getattr(run_metadata, "advanced_debug_logging", False)):
            run_dir, heatsoak_debug = build_heatsoak_debug(self.orchestrator, profile.profile_name)
            if run_dir is not None and heatsoak_debug_callback is not None:
                heatsoak_debug_callback(run_dir / "advanced_debug" / "heatsoak")
        if not self.run_heatsoak_if_requested(heatsoak_minutes, advanced_debug=heatsoak_debug):
            return None
        return self.orchestrator.run(profile_path, profile, labels, run_metadata, run_dir=run_dir)

    def _profile_run_context(
        self,
        profile_path: Path,
        metadata: Optional[RunMetadata],
        setup: Optional[RunSetupState],
    ):
        return build_profile_run_context(
            profile_path,
            metadata,
            setup,
            settings=self.settings,
            profile_loader=self.profile_loader,
            default_run_metadata=self.default_run_metadata,
        )
