#!/usr/bin/env python3
"""Frontend-safe run progress line helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .lvs_core import format_duration_hms

from .lvs_run_lifecycle import phase_line


@dataclass
class RunProgressEvent:
    raw_line: str
    timestamp: str = ""
    event_type: str = ""
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class RunStatusSnapshot:
    active: bool = False
    status: str = "idle"
    latest_line: str = ""
    latest_event_type: str = ""
    profile: str = ""
    stage: str = ""
    verdict: str = ""
    elapsed: str = ""
    remaining: str = ""
    stage_elapsed: str = ""
    stage_remaining: str = ""
    run_elapsed: str = ""
    est_run_remaining: str = ""
    manual_abort_requested: bool = False


def normalize_progress_line(line: object) -> str:
    return str(line or "").rstrip()


def is_phase_progress_line(line: object) -> bool:
    text = normalize_progress_line(line)
    return bool(text) and (
        text.startswith("[phase]")
        or text.startswith("[heatsoak]")
        or " | stage=" in text
        or " | stage-" in text
        or " | run-" in text
    )


def short_status_text(text: object, limit: int = 96) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."


def latest_phase_line(lines: Iterable[object]) -> str:
    latest = ""
    for line in lines:
        text = normalize_progress_line(line)
        if is_phase_progress_line(text):
            latest = text
    return latest


def parse_progress_event(line: object) -> RunProgressEvent | None:
    text = normalize_progress_line(line)
    if not is_phase_progress_line(text):
        return None
    if text.startswith("[heatsoak]"):
        fields = _parse_key_value_parts(part.strip() for part in text.replace("[heatsoak]", "", 1).split(" | "))
        return RunProgressEvent(raw_line=text, event_type="heatsoak-progress", fields=fields)
    parts = [part.strip() for part in text.split(" | ")]
    timestamp = ""
    event_type = ""
    fields: dict[str, str] = {}
    if parts and parts[0].startswith("[phase]"):
        timestamp = parts[0].replace("[phase]", "", 1).strip()
        if len(parts) > 1:
            event_type = parts[1]
        field_parts = parts[2:]
    else:
        if parts:
            timestamp = parts[0]
        if len(parts) > 1 and "=" not in parts[1]:
            event_type = parts[1]
            field_parts = parts[2:]
        else:
            event_type = "stage-progress"
            field_parts = parts[1:]
    fields = _parse_key_value_parts(field_parts)
    return RunProgressEvent(raw_line=text, timestamp=timestamp, event_type=event_type, fields=fields)


def _parse_key_value_parts(parts: Iterable[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in parts:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        if key:
            fields[key] = value.strip()
    return fields


def progress_line(timestamp: str, event_type: str, **fields: object) -> str:
    return phase_line(timestamp, event_type, **fields)


class RunStatusTracker:
    """Small frontend-neutral state machine fed by phase/progress output."""

    def __init__(self) -> None:
        self.snapshot = RunStatusSnapshot()
        self.events: list[RunProgressEvent] = []

    def reset(self) -> None:
        self.snapshot = RunStatusSnapshot()
        self.events = []

    def update_line(self, line: object) -> RunProgressEvent | None:
        event = parse_progress_event(line)
        if event is not None:
            self.update_event(event)
        return event

    def update_event(self, event: RunProgressEvent) -> RunStatusSnapshot:
        if self.events and self.events[-1].raw_line == event.raw_line:
            return self.snapshot
        self.events.append(event)
        self.events = self.events[-500:]
        snapshot = self.snapshot
        snapshot.latest_line = event.raw_line
        snapshot.latest_event_type = event.event_type
        event_type = event.event_type
        fields = event.fields
        if fields.get("profile"):
            snapshot.profile = fields["profile"]
        if fields.get("stage"):
            snapshot.stage = fields["stage"]
        if fields.get("verdict"):
            snapshot.verdict = fields["verdict"]
        if fields.get("elapsed"):
            snapshot.elapsed = fields["elapsed"]
        if fields.get("remaining"):
            snapshot.remaining = fields["remaining"]
        if fields.get("run_elapsed"):
            snapshot.run_elapsed = fields["run_elapsed"]
        if fields.get("est_run_remaining"):
            snapshot.est_run_remaining = fields["est_run_remaining"]
        if event_type == "run-start":
            snapshot.active = True
            snapshot.status = "run_active"
            snapshot.profile = fields.get("profile", snapshot.profile)
            snapshot.verdict = ""
        elif event_type == "stage-start":
            snapshot.active = True
            snapshot.status = "stage_active"
            snapshot.stage = fields.get("stage", snapshot.stage)
            snapshot.elapsed = ""
            snapshot.remaining = ""
            snapshot.stage_elapsed = ""
            snapshot.stage_remaining = ""
        elif event_type == "stage-progress":
            snapshot.active = True
            snapshot.status = "stage_active"
            snapshot.stage = fields.get("stage", snapshot.stage)
            snapshot.elapsed = fields.get("elapsed", snapshot.elapsed)
            snapshot.remaining = fields.get("remaining", snapshot.remaining)
            snapshot.stage_elapsed = fields.get("elapsed", snapshot.stage_elapsed)
            snapshot.stage_remaining = fields.get("remaining", snapshot.stage_remaining)
        elif event_type == "stage-skip":
            snapshot.status = "stage_skipped"
            snapshot.stage = fields.get("stage", snapshot.stage)
        elif event_type == "cpu-tune-start":
            snapshot.active = True
            snapshot.status = "cpu_tuning"
            snapshot.stage = fields.get("stage", snapshot.stage)
            snapshot.elapsed = ""
            snapshot.remaining = ""
            snapshot.stage_elapsed = ""
            snapshot.stage_remaining = ""
        elif event_type == "cpu-tune-end":
            snapshot.status = "cpu_tuned"
            snapshot.stage = fields.get("stage", snapshot.stage)
        elif event_type == "gpu-retune":
            snapshot.active = True
            snapshot.status = "gpu_retuning"
            snapshot.stage = fields.get("stage", snapshot.stage)
        elif event_type == "operator-stop":
            snapshot.active = True
            snapshot.status = "manual_abort_requested"
            snapshot.manual_abort_requested = True
            snapshot.stage = fields.get("stage", snapshot.stage)
        elif event_type == "heatsoak-start":
            snapshot.active = True
            snapshot.status = "heatsoak_active"
            snapshot.stage = "Heatsoak"
            snapshot.verdict = ""
        elif event_type == "heatsoak-progress":
            snapshot.active = True
            snapshot.status = "heatsoak_active"
            snapshot.stage = "Heatsoak"
            snapshot.elapsed = fields.get("elapsed", snapshot.elapsed)
        elif event_type == "heatsoak-end":
            snapshot.active = False
            snapshot.status = "heatsoak_complete"
            snapshot.stage = "Heatsoak"
            snapshot.verdict = fields.get("verdict", snapshot.verdict)
        elif event_type == "heatsoak-cancel":
            snapshot.active = False
            snapshot.status = "heatsoak_cancelled"
            snapshot.stage = "Heatsoak"
            snapshot.verdict = fields.get("verdict", "cancelled")
        elif event_type == "stage-abort":
            snapshot.active = True
            snapshot.status = "stage_aborted"
            snapshot.stage = fields.get("stage", snapshot.stage)
            snapshot.verdict = "aborted"
        elif event_type == "stage-end":
            snapshot.active = True
            snapshot.status = "stage_complete"
            snapshot.stage = fields.get("stage", snapshot.stage)
            snapshot.elapsed = ""
            snapshot.remaining = ""
            snapshot.stage_elapsed = ""
            snapshot.stage_remaining = ""
        elif event_type == "run-end":
            snapshot.active = False
            snapshot.status = "run_complete"
            snapshot.elapsed = fields.get("elapsed", snapshot.elapsed)
            snapshot.remaining = fields.get("remaining", "")
            snapshot.run_elapsed = fields.get("run_elapsed", fields.get("elapsed", snapshot.run_elapsed))
            snapshot.est_run_remaining = fields.get("est_run_remaining", "00:00:00")
            snapshot.verdict = fields.get("verdict", snapshot.verdict)
        elif event_type == "run-error":
            snapshot.active = False
            snapshot.status = "run_failed"
            snapshot.verdict = fields.get("verdict", "failed")
        return snapshot

    def status_text(self, limit: int = 96) -> str:
        snapshot = self.snapshot
        if snapshot.status == "idle":
            return "Idle"
        parts = [snapshot.status.replace("_", " ")]
        if snapshot.stage:
            parts.append(snapshot.stage)
        if snapshot.verdict:
            parts.append(f"verdict={snapshot.verdict}")
        if snapshot.elapsed:
            parts.append(f"stage_elapsed={snapshot.elapsed}")
        if snapshot.remaining:
            parts.append(f"stage_remaining={snapshot.remaining}")
        if snapshot.run_elapsed:
            parts.append(f"run_elapsed={snapshot.run_elapsed}")
        if snapshot.est_run_remaining:
            parts.append(f"est_run_remaining={snapshot.est_run_remaining}")
        return short_status_text(" | ".join(parts), limit=limit)


def _remaining_display(timing_snapshot: Any) -> str:
    status = str(getattr(timing_snapshot, "estimated_run_remaining_status", "") or "")
    if status:
        return status.replace("_", " ").title()
    remaining = getattr(timing_snapshot, "estimated_run_remaining_seconds", None)
    return format_duration_hms(remaining) if remaining is not None else "Unknown"


def run_timing_detail_lines(timing_snapshot: Any) -> list[str]:
    if timing_snapshot is None:
        return []
    return [
        f"Run elapsed: {format_duration_hms(timing_snapshot.run_elapsed_seconds)}",
        f"Est. remaining: {_remaining_display(timing_snapshot)}",
    ]


def run_status_detail_text(snapshot: RunStatusSnapshot, timing_snapshot: Any = None) -> str:
    lines = [
        f"Status: {snapshot.status.replace('_', ' ')}",
    ]
    if snapshot.profile:
        lines.append(f"Profile: {snapshot.profile}")
    if snapshot.stage:
        lines.append(f"Stage: {snapshot.stage}")
    if snapshot.verdict:
        lines.append(f"Verdict: {snapshot.verdict}")
    if timing_snapshot is not None:
        lines.extend(run_timing_detail_lines(timing_snapshot))
    else:
        if snapshot.elapsed:
            scope = "Run" if snapshot.status in {"run_complete", "run_failed"} else (
                "Heatsoak" if snapshot.status.startswith("heatsoak") else "Stage"
            )
            lines.append(f"{scope} elapsed: {snapshot.elapsed}")
        if snapshot.remaining:
            scope = "Heatsoak" if snapshot.status.startswith("heatsoak") else "Stage"
            lines.append(f"{scope} remaining: {snapshot.remaining}")
    if snapshot.manual_abort_requested:
        lines.append("Manual stop requested: yes")
    if snapshot.latest_event_type:
        lines.append(f"Latest event: {snapshot.latest_event_type}")
    return "\n".join(lines)


def run_event_history_text(events: Iterable[RunProgressEvent], limit: int = 8) -> str:
    selected = list(events)[-max(1, int(limit)):]
    if not selected:
        return "Recent Events\n-------------\n(no structured events yet)"
    lines = ["Recent Events", "-------------"]
    for event in selected:
        lines.append(f"- {_event_summary(event)}")
    return "\n".join(lines)


def _event_summary(event: RunProgressEvent) -> str:
    label = event.event_type.replace("_", " ").replace("-", " ") or "event"
    fields = event.fields or {}
    details = []
    for key in (
        "profile", "stage", "target", "workload", "verdict", "elapsed", "remaining",
        "run_elapsed", "est_run_remaining", "minutes", "action", "error",
    ):
        value = fields.get(key)
        if value:
            details.append(f"{key}={value}")
    if not details and event.timestamp:
        details.append(event.timestamp)
    return f"{label}: " + (", ".join(details) if details else event.raw_line)
