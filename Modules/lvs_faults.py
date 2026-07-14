#!/usr/bin/env python3
"""Linux runtime fault collection helpers."""

from __future__ import annotations

import re
import subprocess
from shutil import which
from datetime import datetime
from typing import Any


def summarize_fault_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    category_counts: dict[str, int] = {}
    for event in events:
        category = str(event.get("category") or "unknown")
        category_counts[category] = category_counts.get(category, 0) + 1
    return {
        "count": len(events),
        "error_count": sum(1 for event in events if event.get("severity") == "error"),
        "warning_count": sum(1 for event in events if event.get("severity") == "warning"),
        "categories": category_counts,
    }


def faults_for_stage_window(faults: list[dict[str, Any]], window: Any) -> list[dict[str, Any]]:
    if not faults:
        return []
    stage_start = datetime.fromisoformat(window.started_iso)
    stage_end = datetime.fromisoformat(window.ended_iso)
    selected: list[dict[str, Any]] = []
    for fault in faults:
        raw_timestamp = str(fault.get("timestamp") or "").strip()
        if not raw_timestamp:
            continue
        try:
            event_time = datetime.fromisoformat(raw_timestamp)
        except Exception:
            continue
        if stage_start <= event_time <= stage_end:
            selected.append(fault)
    return selected


class LinuxFaultCollector:
    PATTERN_DEFS = [
        ("whea", "error", re.compile(r"whea", re.IGNORECASE)),
        ("hardware_error", "error", re.compile(r"\b(hardware error|mce:|machine check|edac)\b", re.IGNORECASE)),
        ("pcie_aer", "error", re.compile(r"\b(aer:|pcie bus error)\b", re.IGNORECASE)),
        ("gpu_reset", "error", re.compile(r"\b(amdgpu|nouveau|i915|xe)\b.*\b(reset|fault|ring timeout|hang)\b", re.IGNORECASE)),
        ("nvidia_xid", "error", re.compile(r"\bNVRM: Xid\b", re.IGNORECASE)),
        ("oom", "warning", re.compile(r"\bout of memory|oom-killer\b", re.IGNORECASE)),
    ]

    def collect(self, started_iso: str, ended_iso: str) -> list[dict[str, Any]]:
        lines = self._read_kernel_lines(started_iso, ended_iso)
        return self._collect_from_lines(lines, source="kernel", boot_scope="current")

    def collect_previous_boot(self) -> list[dict[str, Any]]:
        lines = self._read_previous_boot_kernel_lines()
        return self._collect_from_lines(lines, source="kernel_previous_boot", boot_scope="previous")

    def _read_kernel_lines(self, started_iso: str, ended_iso: str) -> list[str]:
        if self._command_exists("journalctl"):
            try:
                completed = subprocess.run(
                    [
                        "journalctl",
                        "-k",
                        "--since",
                        started_iso,
                        "--until",
                        ended_iso,
                        "--output",
                        "short-iso",
                        "--no-pager",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                if completed.returncode == 0:
                    return [line for line in (completed.stdout or "").splitlines() if line.strip()]
            except Exception:
                pass
        return []

    def _read_previous_boot_kernel_lines(self) -> list[str]:
        if self._command_exists("journalctl"):
            try:
                completed = subprocess.run(
                    [
                        "journalctl",
                        "-b",
                        "-1",
                        "-k",
                        "--output",
                        "short-iso",
                        "--no-pager",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                if completed.returncode == 0:
                    return [line for line in (completed.stdout or "").splitlines() if line.strip()]
            except Exception:
                pass
        return []

    def _collect_from_lines(self, lines: list[str], *, source: str, boot_scope: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for line in lines:
            event = self._classify_line(line, source=source, boot_scope=boot_scope)
            if event:
                events.append(event)
        return events

    def _classify_line(self, line: str, *, source: str, boot_scope: str) -> dict[str, Any] | None:
        for category, severity, pattern in self.PATTERN_DEFS:
            if pattern.search(line):
                return {
                    "timestamp": self._extract_timestamp(line),
                    "category": category,
                    "severity": severity,
                    "source": source,
                    "boot_scope": boot_scope,
                    "message": line.strip(),
                }
        return None

    def _extract_timestamp(self, line: str) -> str:
        match = re.match(r"^(\d{4}-\d{2}-\d{2}[T ][^ ]+)", line)
        if not match:
            return ""
        raw = match.group(1).strip()
        if " " in raw and "T" not in raw:
            raw = raw.replace(" ", "T", 1)
        return raw

    def _command_exists(self, name: str) -> bool:
        return which(name) is not None
