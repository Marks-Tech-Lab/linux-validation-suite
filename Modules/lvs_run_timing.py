#!/usr/bin/env python3
"""UI-neutral live validation-run timing state and calculations."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from threading import Lock
from typing import Any, Callable, Optional

from .lvs_core import format_duration_hms
from .lvs_profile_models import stage_execution_mode


@dataclass(frozen=True)
class RunTimingStage:
    profile_index: int
    stage_id: str
    label: str
    duration_seconds: Optional[float]


@dataclass(frozen=True)
class RunTimingAnchor:
    run_started_monotonic: float
    stages: tuple[RunTimingStage, ...] = ()
    lifecycle: str = "initializing"
    current_stage_position: Optional[int] = None
    next_stage_position: int = 0
    stage_started_monotonic: Optional[float] = None
    terminal_elapsed_seconds: Optional[float] = None
    terminal_remaining_status: str = ""


@dataclass(frozen=True)
class RunTimingSnapshot:
    lifecycle: str
    run_elapsed_seconds: float
    estimated_run_remaining_seconds: Optional[float]
    estimated_run_remaining_status: str
    current_stage_id: str = ""
    current_stage_label: str = ""
    stage_elapsed_seconds: Optional[float] = None
    stage_remaining_seconds: Optional[float] = None


def _finite_duration(value: object) -> Optional[float]:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    return duration if math.isfinite(duration) and duration >= 0.0 else None


def calculate_run_timing(anchor: RunTimingAnchor, now_monotonic: float) -> RunTimingSnapshot:
    """Calculate one immutable timing snapshot without consulting wall time."""
    now = float(now_monotonic)
    run_elapsed = (
        max(0.0, float(anchor.terminal_elapsed_seconds))
        if anchor.terminal_elapsed_seconds is not None
        else max(0.0, now - float(anchor.run_started_monotonic))
    )
    position = anchor.current_stage_position
    stage = anchor.stages[position] if position is not None and 0 <= position < len(anchor.stages) else None
    stage_elapsed: Optional[float] = None
    stage_remaining: Optional[float] = None
    if stage is not None and anchor.lifecycle == "running" and anchor.stage_started_monotonic is not None:
        stage_elapsed = max(0.0, now - float(anchor.stage_started_monotonic))
        if stage.duration_seconds is not None:
            stage_remaining = max(0.0, float(stage.duration_seconds) - stage_elapsed)

    if anchor.terminal_elapsed_seconds is not None:
        remaining = 0.0 if not anchor.terminal_remaining_status else None
        remaining_status = anchor.terminal_remaining_status
    elif not anchor.stages:
        remaining = None
        remaining_status = "unknown"
    else:
        start = max(0, min(int(anchor.next_stage_position), len(anchor.stages)))
        remaining = 0.0
        remaining_status = ""
        for future_position in range(start, len(anchor.stages)):
            future = anchor.stages[future_position]
            if future.duration_seconds is None:
                remaining = None
                remaining_status = "unknown"
                break
            if future_position == position and anchor.lifecycle == "running":
                remaining += float(stage_remaining or 0.0)
            else:
                remaining += float(future.duration_seconds)

    return RunTimingSnapshot(
        lifecycle=anchor.lifecycle,
        run_elapsed_seconds=run_elapsed,
        estimated_run_remaining_seconds=remaining,
        estimated_run_remaining_status=remaining_status,
        current_stage_id=stage.stage_id if stage else "",
        current_stage_label=stage.label if stage else "",
        stage_elapsed_seconds=stage_elapsed,
        stage_remaining_seconds=stage_remaining,
    )


def timing_cli_fields(snapshot: RunTimingSnapshot) -> dict[str, str]:
    remaining = snapshot.estimated_run_remaining_status or (
        format_duration_hms(snapshot.estimated_run_remaining_seconds)
        if snapshot.estimated_run_remaining_seconds is not None
        else "unknown"
    )
    return {
        "run_elapsed": format_duration_hms(snapshot.run_elapsed_seconds),
        "est_run_remaining": remaining.lower(),
    }


def append_timing_cli_fields(line: str, snapshot: RunTimingSnapshot) -> str:
    fields = timing_cli_fields(snapshot)
    return f"{line} | run_elapsed={fields['run_elapsed']} | est_run_remaining={fields['est_run_remaining']}"


class RunTimingController:
    """Own lifecycle anchors while frontends consume immutable copies."""

    def __init__(
        self,
        run_started_monotonic: float,
        *,
        publish: Optional[Callable[[RunTimingAnchor], None]] = None,
    ) -> None:
        self._lock = Lock()
        self._anchor = RunTimingAnchor(run_started_monotonic=float(run_started_monotonic))
        self._publish_callback = publish
        self._publish(self._anchor)

    def anchor(self) -> RunTimingAnchor:
        with self._lock:
            return self._anchor

    def snapshot(self, now_monotonic: float) -> RunTimingSnapshot:
        return calculate_run_timing(self.anchor(), now_monotonic)

    def configure(self, effective_profile: Any, labels: list[str]) -> None:
        stages: list[RunTimingStage] = []
        for profile_index, stage in enumerate(effective_profile.stages):
            if not bool(getattr(stage, "enabled", False)):
                continue
            mode = stage_execution_mode(stage)
            duration = _finite_duration(getattr(stage, "duration_seconds", None)) if mode == "duration" else None
            stages.append(
                RunTimingStage(
                    profile_index=profile_index,
                    stage_id=str(getattr(stage, "id", "") or ""),
                    label=str(labels[profile_index] if profile_index < len(labels) else getattr(stage, "name", "") or ""),
                    duration_seconds=duration,
                )
            )
        self._replace(stages=tuple(stages), lifecycle="between_stages", next_stage_position=0)

    def prepare_stage(self, profile_index: int) -> None:
        if self.anchor().terminal_elapsed_seconds is not None:
            return
        position = self._position(profile_index)
        if position is None:
            return
        self._replace(
            lifecycle="preparing",
            current_stage_position=position,
            next_stage_position=position,
            stage_started_monotonic=None,
        )

    def start_stage(self, profile_index: int, stage_started_monotonic: float) -> None:
        if self.anchor().terminal_elapsed_seconds is not None:
            return
        position = self._position(profile_index)
        if position is None:
            return
        self._replace(
            lifecycle="running",
            current_stage_position=position,
            next_stage_position=position,
            stage_started_monotonic=float(stage_started_monotonic),
        )

    def end_stage(self, profile_index: int) -> None:
        if self.anchor().terminal_elapsed_seconds is not None:
            return
        position = self._position(profile_index)
        if position is None:
            return
        self._replace(
            lifecycle="between_stages",
            current_stage_position=None,
            next_stage_position=position + 1,
            stage_started_monotonic=None,
        )

    def finish(self, elapsed_seconds: float, *, lifecycle: str, remaining_status: str = "") -> None:
        self._replace(
            lifecycle=lifecycle,
            current_stage_position=None,
            next_stage_position=len(self.anchor().stages),
            stage_started_monotonic=None,
            terminal_elapsed_seconds=max(0.0, float(elapsed_seconds)),
            terminal_remaining_status=str(remaining_status or ""),
        )

    def terminate(self, now_monotonic: float, *, lifecycle: str, remaining_status: str) -> None:
        elapsed = max(0.0, float(now_monotonic) - self.anchor().run_started_monotonic)
        self.finish(elapsed, lifecycle=lifecycle, remaining_status=remaining_status)

    def _position(self, profile_index: int) -> Optional[int]:
        for position, stage in enumerate(self.anchor().stages):
            if stage.profile_index == profile_index:
                return position
        return None

    def _replace(self, **changes: object) -> None:
        with self._lock:
            self._anchor = replace(self._anchor, **changes)
            anchor = self._anchor
        self._publish(anchor)

    def _publish(self, anchor: RunTimingAnchor) -> None:
        if self._publish_callback is None:
            return
        try:
            self._publish_callback(anchor)
        except Exception:
            # Presentation subscribers must never affect validation execution.
            return
