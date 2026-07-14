#!/usr/bin/env python3
"""Shared service/TUI data models for Linux Validation Suite frontends."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List

from .lvs_run_metadata import RunMetadata
from .lvs_run_progress import RunStatusSnapshot


@dataclass
class FrontendActionSpec:
    key: str
    action: str
    target: str = ""
    label: str = ""
    detail: str = ""


@dataclass
class ProfileListEntry:
    path: Path
    name: str
    menu_group: str
    menu_group_label: str


@dataclass
class ProfileEditState:
    profile_path: Path
    profile: Any
    labels: List[str]
    dirty: bool = False


@dataclass
class ProfileEditItem:
    kind: str
    label: str
    index: int | None = None
    template_key: str = ""


@dataclass
class ResultListEntry:
    path: Path
    name: str
    verdict: str
    profile_name: str
    started: str


@dataclass
class RunResult:
    run_dir: Path
    output: str
    metadata: RunMetadata
    progress_events: List[Any] = field(default_factory=list)
    run_status: RunStatusSnapshot | None = None


@dataclass
class RunSetupState:
    profile_path: Path
    metadata: RunMetadata
    profile: Any
    labels: List[str]
    heatsoak_minutes: float = 0.0


@dataclass
class RunSetupHistoryEntry:
    index: int
    saved: str
    profile_name: str
    profile_file: str
    case_sku: str
    description: str
    psu_wattage: str
    metadata: RunMetadata
    heatsoak_minutes: float = 0.0


@dataclass
class CycleSetupResult:
    selected: str
    requires_text: bool = False
    text_field: str = ""
    prompt: str = ""
    blank_default: str = ""


@dataclass
class SetupInputSpec:
    field: str
    label: str
    blank_default: str = ""
    initial_value: str = ""


@dataclass
class SetupPickerSpec:
    key: str
    title: str
    options: List[str]
    current: str = ""
