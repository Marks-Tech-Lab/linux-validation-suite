#!/usr/bin/env python3
"""Shared run execution context and capture helpers."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .lvs_advanced_debug import AdvancedDebugLogger
from .lvs_run_metadata import RunMetadata
from .lvs_service_models import RunSetupState


class CallbackStringIO:
    """StringIO-compatible capture that forwards complete lines to a callback."""

    def __init__(self, line_callback: Optional[Callable[[str], None]] = None) -> None:
        self._buffer = io.StringIO()
        self._line_callback = line_callback
        self._pending = ""

    def write(self, text: str) -> int:
        value = str(text or "")
        self._buffer.write(value)
        if self._line_callback:
            self._pending += value
            while "\n" in self._pending:
                line, self._pending = self._pending.split("\n", 1)
                self._line_callback(line)
        return len(value)

    def flush(self) -> None:
        return None

    def getvalue(self) -> str:
        if self._line_callback and self._pending.strip():
            self._line_callback(self._pending)
            self._pending = ""
        return self._buffer.getvalue()


@dataclass(frozen=True)
class ProfileRunContext:
    profile: Any
    labels: list[str]
    metadata: RunMetadata


def build_profile_run_context(
    profile_path: Path,
    metadata: Optional[RunMetadata],
    setup: Optional[RunSetupState],
    *,
    settings: Any,
    profile_loader: Any,
    default_run_metadata: Callable[[Path], RunMetadata],
) -> ProfileRunContext:
    profile = setup.profile if setup is not None else profile_loader.load_profile(profile_path)
    labels = setup.labels if setup is not None else profile_loader.load_segment_labels(profile_path, profile)
    run_metadata = metadata or default_run_metadata(profile_path)
    if not str(run_metadata.case_sku or "").strip():
        run_metadata.case_sku = "Unknown"
    if not str(run_metadata.description or "").strip():
        run_metadata.description = profile.profile_name
    if not str(run_metadata.dept or "").strip():
        run_metadata.dept = str(getattr(settings, "suite_department", "") or "Production")
    return ProfileRunContext(profile=profile, labels=list(labels), metadata=run_metadata)


def build_heatsoak_debug(
    orchestrator: Any,
    profile_name: str,
) -> tuple[Optional[Path], Optional[AdvancedDebugLogger]]:
    make_run_dir = getattr(orchestrator, "make_run_dir", None)
    if not callable(make_run_dir):
        return None, None
    run_dir = make_run_dir(profile_name)
    runtime_environment = {}
    workload_runner = getattr(orchestrator, "workload_runner", None)
    if workload_runner is not None and callable(getattr(workload_runner, "runtime_environment", None)):
        runtime_environment = workload_runner.runtime_environment()
    return run_dir, AdvancedDebugLogger(
        run_dir,
        enabled=True,
        runtime_environment=runtime_environment,
        scope="heatsoak",
    )
