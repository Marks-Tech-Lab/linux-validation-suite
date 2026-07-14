#!/usr/bin/env python3
"""Compact live run presentation for interactive CLI terminals."""

from __future__ import annotations

import os
import sys
from typing import TextIO

from .lvs_run_progress import RunProgressEvent, RunStatusTracker, parse_progress_event, short_status_text


def cli_live_run_supported(stream: TextIO | None = None) -> bool:
    stream = stream or sys.stdout
    try:
        return bool(stream.isatty()) and os.environ.get("TERM", "") != "dumb"
    except Exception:
        return False


class CliLiveRunPresenter:
    """Render repeated progress lines as one compact terminal-updated block."""

    def __init__(self, *, stream: TextIO | None = None, enabled: bool | None = None, width: int = 110) -> None:
        self.stream = stream or sys.stdout
        self.enabled = cli_live_run_supported(self.stream) if enabled is None else bool(enabled)
        self.width = max(50, int(width or 110))
        self.tracker = RunStatusTracker()
        self.completed_stages: list[str] = []
        self.recent_details: list[str] = []
        self._rendered_lines = 0

    def write_line(self, line: str) -> None:
        text = str(line or "").rstrip()
        if not self.enabled:
            print(text, file=self.stream)
            return

        event = parse_progress_event(text)
        if event is not None:
            self._apply_event(event)
            self.render()
            return

        if self._should_show_detail(text):
            self.recent_details.append(short_status_text(text, self.width))
            self.recent_details = self.recent_details[-4:]
            self.render()

    def finish(self) -> None:
        if not self.enabled:
            return
        self.render()
        self.stream.write("\n")
        self.stream.flush()
        self._rendered_lines = 0

    def _apply_event(self, event: RunProgressEvent) -> None:
        self.tracker.update_event(event)
        if event.event_type == "stage-end":
            stage = event.fields.get("stage") or self.tracker.snapshot.stage or "stage"
            actual = event.fields.get("actual") or ""
            verdict = event.fields.get("verdict") or ""
            parts = [stage]
            if verdict:
                parts.append(f"verdict={verdict}")
            if actual:
                parts.append(f"actual={actual}")
            self.completed_stages.append(short_status_text(" | ".join(parts), self.width - 4))
            self.completed_stages = self.completed_stages[-12:]
        elif event.event_type == "stage-abort":
            stage = event.fields.get("stage") or self.tracker.snapshot.stage or "stage"
            reason = event.fields.get("reason") or "aborted"
            self.completed_stages.append(short_status_text(f"{stage} | aborted | {reason}", self.width - 4))
            self.completed_stages = self.completed_stages[-12:]
        elif event.event_type in {"run-error", "operator-stop"}:
            self.recent_details.append(short_status_text(event.raw_line, self.width))
            self.recent_details = self.recent_details[-4:]

    def _should_show_detail(self, text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        return any(token in lowered for token in ("[warn]", "[error]", "failed", "error", "abort", "cancel"))

    def render(self) -> None:
        if not self.enabled:
            return
        lines = self.render_lines()
        self._clear_previous()
        self.stream.write("\n".join(lines))
        self.stream.write("\n")
        self.stream.flush()
        self._rendered_lines = len(lines)

    def render_lines(self) -> list[str]:
        snapshot = self.tracker.snapshot
        lines = [
            "Run Status",
            "==========",
            short_status_text(self.tracker.status_text(limit=self.width), self.width),
        ]
        if snapshot.profile:
            lines.append(short_status_text(f"Profile: {snapshot.profile}", self.width))
        if snapshot.stage:
            active = [f"Active stage: {snapshot.stage}"]
            if snapshot.elapsed:
                active.append(f"elapsed={snapshot.elapsed}")
            if snapshot.remaining:
                active.append(f"remaining={snapshot.remaining}")
            if snapshot.verdict:
                active.append(f"verdict={snapshot.verdict}")
            lines.append(short_status_text(" | ".join(active), self.width))
        if self.completed_stages:
            lines.extend(["", "Completed stages:"])
            lines.extend(f"- {item}" for item in self.completed_stages[-6:])
        if snapshot.latest_event_type:
            lines.extend(["", short_status_text(f"Latest event: {snapshot.latest_event_type}", self.width)])
        if self.recent_details:
            lines.extend(["", "Important output:"])
            lines.extend(f"- {item}" for item in self.recent_details[-4:])
        return lines

    def _clear_previous(self) -> None:
        if self._rendered_lines <= 0:
            return
        self.stream.write(f"\x1b[{self._rendered_lines}A")
        for _ in range(self._rendered_lines):
            self.stream.write("\r\x1b[2K\n")
        self.stream.write(f"\x1b[{self._rendered_lines}A")
