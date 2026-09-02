#!/usr/bin/env python3
"""Focused hardware-free checks for shared CLI/TUI run timing semantics."""

from __future__ import annotations

from pathlib import Path
import inspect
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Modules.lvs_core import format_duration_hms
from Modules.lvs_profile_models import (
    ModuleCpu,
    ModuleStorageBenchmark,
    StageConfig,
    StageModules,
    StageNormalization,
    ValidationProfile,
)
from Modules.lvs_run_progress import RunStatusTracker, parse_progress_event
from Modules.lvs_run_event_presenter import CliRunEventPresenter
from Modules.lvs_run_timing import (
    RunTimingController,
    append_timing_cli_fields,
    calculate_run_timing,
)
from Modules.lvs_tui_run_presentation import (
    active_stage_line_text,
    live_snapshot_detail_text,
    run_progress_detail_text,
    stage_progress_table_text,
)
from Modules.lvs_tui_run_execution_adapter import TuiRunExecutionAdapterMixin
from Modules.lvs_live_telemetry import LiveTelemetrySnapshot
from Modules.lvs_service_run import SuiteRunServiceMixin


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _timed(stage_id: str, seconds: int, *, enabled: bool = True, trim: tuple[int, int] = (0, 0)) -> StageConfig:
    return StageConfig(
        id=stage_id,
        name=stage_id,
        duration_seconds=seconds,
        enabled=enabled,
        modules=StageModules(cpu=ModuleCpu(enabled=True)),
        normalization=StageNormalization(*trim),
    )


def _completion(stage_id: str) -> StageConfig:
    return StageConfig(
        id=stage_id,
        name=stage_id,
        duration_seconds=None,
        modules=StageModules(storage_benchmark=ModuleStorageBenchmark(enabled=True)),
    )


def run_run_timing_checks() -> None:
    for seconds, expected in (
        (23 * 3600 + 55 * 60 + 33, "23:55:33"),
        (24 * 3600 + 5 * 60 + 12, "24:05:12"),
        (48 * 3600, "48:00:00"),
        (120 * 3600 + 15 * 60 + 9, "120:15:09"),
    ):
        _assert(format_duration_hms(seconds) == expected, f"duration must not wrap: {expected}")

    profile = ValidationProfile(
        "PL Validation 24hr",
        stages=[_timed("CPU", 3600), _timed("GPU (3D + VRAM)", 5400)],
    )
    anchors = []
    controller = RunTimingController(0.0, publish=anchors.append)
    controller.configure(profile, ["CPU", "GPU (3D + VRAM)"])
    controller.prepare_stage(1)
    preparing = controller.snapshot(82_800.0)
    _assert(preparing.stage_elapsed_seconds is None, "preparing stage has no stale elapsed")
    _assert(preparing.estimated_run_remaining_seconds == 5400.0, "preparing includes full stage")

    now = 23 * 3600 + 55 * 60 + 33
    controller.start_stage(1, now - (55 * 60 + 33))
    photographed = controller.snapshot(now)
    _assert(format_duration_hms(photographed.run_elapsed_seconds) == "23:55:33", "24-hour case run elapsed")
    _assert(format_duration_hms(photographed.stage_elapsed_seconds or 0) == "00:55:33", "24-hour case stage elapsed")
    _assert(format_duration_hms(photographed.stage_remaining_seconds or 0) == "00:34:27", "24-hour case stage remaining")
    _assert(
        format_duration_hms(photographed.estimated_run_remaining_seconds or 0) == "00:34:27",
        "24-hour case estimated run remaining",
    )

    progress_line = (
        "2026-09-02T00:00:00-04:00 | stage=GPU (3D + VRAM) | "
        "elapsed=00:55:33 | remaining=00:34:27"
    )
    cli_line = append_timing_cli_fields(progress_line, photographed)
    _assert("elapsed=00:55:33 | remaining=00:34:27" in cli_line, "legacy CLI stage fields remain ordered")
    _assert("run_elapsed=23:55:33" in cli_line, "CLI adds run elapsed")
    _assert("est_run_remaining=00:34:27" in cli_line, "CLI adds estimated remaining")
    event = parse_progress_event(cli_line)
    _assert(event is not None and event.fields["elapsed"] == "00:55:33", "parser keeps stage elapsed")
    _assert(event.fields["run_elapsed"] == "23:55:33", "parser accepts additive run elapsed")

    tracker = RunStatusTracker()
    tracker.update_event(event)
    detail = run_progress_detail_text(
        profile_name=profile.profile_name,
        status_snapshot=tracker.snapshot,
        phase_line=cli_line,
        events=tracker.events,
        output_lines=[],
        timing_snapshot=photographed,
    )
    _assert("Run elapsed: 23:55:33" in detail, "TUI Current Status uses run elapsed")
    _assert("Est. remaining: 00:34:27" in detail, "TUI Current Status uses estimated remaining")
    _assert("\nElapsed: 00:55:33" not in detail, "TUI has no prominent generic stage elapsed")
    _assert("elapsed=00:55:33" in active_stage_line_text(tracker.snapshot, tracker.events), "active line keeps stage elapsed")
    _assert("remaining=00:34:27" in stage_progress_table_text(tracker.events), "stage table keeps stage remaining")

    telemetry_detail = live_snapshot_detail_text(
        LiveTelemetrySnapshot(sequence=1, sampled_monotonic=now, interval_seconds=2.0, state="running"),
        timing_snapshot=photographed,
    )
    _assert("Run elapsed: 23:55:33" in telemetry_detail, "telemetry detail keeps run timing visible")

    tracker.update_line("[phase] 2026-09-02T01:00:00-04:00 | stage-end | stage=GPU | verdict=pass")
    _assert(active_stage_line_text(tracker.snapshot, tracker.events) == "Active: between stages", "completed stage is not left active")
    tracker.update_line("[phase] 2026-09-02T01:00:01-04:00 | stage-start | stage=Next | planned=00:10:00")
    _assert(not tracker.snapshot.elapsed and not tracker.snapshot.remaining, "stage transition clears legacy timing")
    _assert(not tracker.snapshot.stage_elapsed and not tracker.snapshot.stage_remaining, "stage transition clears explicit timing")
    tracker.update_line("[phase] 2026-09-02T01:00:02-04:00 | cpu-tune-start | stage=Next | policy=power_auto")
    _assert("Next | preparing" in active_stage_line_text(tracker.snapshot, tracker.events), "CPU tuning does not show prior stage active")

    skipped_profile = ValidationProfile("Skipped", stages=[_timed("off", 500, enabled=False), _timed("on", 300)])
    skipped = RunTimingController(10.0)
    skipped.configure(skipped_profile, ["Off", "On"])
    skipped.prepare_stage(1)
    _assert(skipped.snapshot(20.0).estimated_run_remaining_seconds == 300.0, "disabled stage contributes zero")

    completion_profile = ValidationProfile("Completion", stages=[_timed("timed", 60), _completion("storage")])
    unknown = RunTimingController(0.0)
    unknown.configure(completion_profile, ["Timed", "Storage"])
    unknown.prepare_stage(0)
    unknown.start_stage(0, 0.0)
    unknown_snapshot = unknown.snapshot(10.0)
    _assert(unknown_snapshot.estimated_run_remaining_seconds is None, "future completion stage makes estimate unknown")
    _assert(unknown_snapshot.estimated_run_remaining_status == "unknown", "unknown reason retained")
    unknown.end_stage(0)
    unknown.prepare_stage(1)
    unknown.start_stage(1, 60.0)
    _assert(unknown.snapshot(70.0).estimated_run_remaining_status == "unknown", "current completion stage remains unknown")
    _assert("est_run_remaining=unknown" in append_timing_cli_fields("progress", unknown.snapshot(70.0)), "CLI unknown token")
    unknown_detail = run_progress_detail_text(
        profile_name="Completion", status_snapshot=RunStatusTracker().snapshot,
        phase_line="", events=[], output_lines=[], timing_snapshot=unknown.snapshot(70.0),
    )
    _assert("Est. remaining: Unknown" in unknown_detail, "TUI unknown estimate label")

    sequence = RunTimingController(0.0)
    sequence_profile = ValidationProfile(
        "Sequence", stages=[_timed("first", 60), _timed("middle", 120), _timed("final", 180)]
    )
    sequence.configure(sequence_profile, ["First", "Middle", "Final"])
    sequence.prepare_stage(0)
    sequence.start_stage(0, 10.0)
    _assert(sequence.snapshot(30.0).estimated_run_remaining_seconds == 340.0, "first stage includes all future stages")
    sequence.end_stage(0)
    sequence.prepare_stage(1)
    _assert(sequence.snapshot(30.0).estimated_run_remaining_seconds == 300.0, "between stages includes full next stage")
    sequence.start_stage(1, 30.0)
    _assert(sequence.snapshot(60.0).estimated_run_remaining_seconds == 270.0, "middle stage estimate")
    sequence.end_stage(1)
    sequence.prepare_stage(2)
    sequence.start_stage(2, 60.0)
    _assert(sequence.snapshot(120.0).estimated_run_remaining_seconds == 120.0, "final stage estimate")

    overrun = RunTimingController(0.0)
    overrun.configure(ValidationProfile("Overrun", stages=[_timed("stage", 10, trim=(3, 4))]), ["Stage"])
    overrun.prepare_stage(0)
    overrun.start_stage(0, 0.0)
    overrun_snapshot = overrun.snapshot(15.0)
    _assert(overrun_snapshot.stage_remaining_seconds == 0.0, "stage remaining clamps at zero")
    _assert(overrun_snapshot.estimated_run_remaining_seconds == 0.0, "run estimate clamps at zero")
    _assert(overrun_snapshot.stage_elapsed_seconds == 15.0, "normalization trims do not alter live elapsed")

    overrun.finish(15.0, lifecycle="completed")
    completed = overrun.snapshot(1000.0)
    _assert(completed.run_elapsed_seconds == 15.0, "completion freezes elapsed")
    _assert(completed.estimated_run_remaining_seconds == 0.0, "completion remaining is zero")
    overrun.finish(15.0, lifecycle="aborted", remaining_status="aborted")
    aborted = overrun.snapshot(1000.0)
    _assert(aborted.estimated_run_remaining_seconds is None, "abort stops numeric estimate")
    _assert(aborted.estimated_run_remaining_status == "aborted", "abort status retained")
    overrun.finish(15.0, lifecycle="stopped", remaining_status="stopped")
    _assert(overrun.snapshot(1000.0).estimated_run_remaining_status == "stopped", "failure stops estimate")

    presenter_lines = []
    presenter = CliRunEventPresenter(
        started_iso="2026-09-02T00:00:00-04:00",
        emit=presenter_lines.append,
        timing_snapshot=lambda: photographed,
    )
    presenter.stage_start(
        "GPU (3D + VRAM)", "2026-09-02T23:00:00-04:00", "GPU", "01:30:00",
        "2026-09-03T00:30:00-04:00", "", "",
    )
    _assert("run_elapsed=23:55:33" in presenter_lines[0], "CLI phase event uses shared run timing")
    _assert("est_run_remaining=00:34:27" in presenter_lines[0], "CLI phase event uses shared estimate")

    class FakeTui(TuiRunExecutionAdapterMixin):
        def __init__(self) -> None:
            self.run_status_tracker = RunStatusTracker()
            self.run_in_progress = True
            self.refreshed = 0

        def _refresh_run_detail(self) -> None:
            self.refreshed += 1

    fake_tui = FakeTui()
    fake_tui._append_run_timing_anchor(anchors[-1])
    _assert(fake_tui.run_timing_snapshot is not None, "TUI calculates timing from core anchor")
    _assert(fake_tui.refreshed == 1, "timing anchor refreshes TUI without a progress line")

    app_source = (ROOT / "Modules/lvs_tui_app.py").read_text(encoding="utf-8")
    timing_source = (ROOT / "Modules/lvs_run_timing.py").read_text(encoding="utf-8")
    _assert("set_interval(2.0, self._refresh_live_system_pane)" in app_source, "existing two-second TUI timer retained")
    _assert("textual" not in timing_source.lower(), "core timing source stays Textual-free")
    _assert("trim_start" not in timing_source and "trim_end" not in timing_source, "timing model ignores analysis trims")
    _assert(
        "live_timing_callback" in inspect.signature(SuiteRunServiceMixin.run_profile_capture_output).parameters,
        "service exposes optional timing callback",
    )


if __name__ == "__main__":
    run_run_timing_checks()
    print("PASS run timing checks")
