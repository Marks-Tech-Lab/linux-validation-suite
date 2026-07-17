#!/usr/bin/env python3
"""Run setup stage override and segment label helpers."""

from __future__ import annotations

from typing import List

from .lvs_service_models import RunSetupState


def stage_override_options(setup: RunSetupState) -> List[str]:
    return [
        "Edit Stage Durations",
        "Edit Trim For All Stages",
        "Toggle Stage Enabled/Disabled",
    ]


def stage_option_values(setup: RunSetupState, mode: str) -> List[str]:
    values: List[str] = []
    for index, stage in enumerate(setup.profile.stages, start=1):
        label = setup.labels[index - 1] if index - 1 < len(setup.labels) else stage.name
        if mode == "duration":
            execution = "completion-based" if stage.modules.storage_benchmark.enabled else f"{stage.duration_seconds}s"
            values.append(f"{index}. {label} [{stage.name}] {execution}")
        elif mode == "toggle":
            state = "enabled" if stage.enabled else "disabled"
            values.append(f"{index}. {label} [{stage.name}] {state}")
        elif mode == "label":
            values.append(f"{index}. {label} [{stage.name}]")
    return values


def set_stage_duration(setup: RunSetupState, stage_index: int, raw_seconds: str) -> None:
    if stage_index < 0 or stage_index >= len(setup.profile.stages):
        return
    if setup.profile.stages[stage_index].modules.storage_benchmark.enabled:
        return
    text = str(raw_seconds or "").strip()
    if not text:
        return
    try:
        seconds = int(float(text))
    except Exception:
        return
    setup.profile.stages[stage_index].duration_seconds = max(1, seconds)


def set_all_stage_trim(setup: RunSetupState, start_seconds: int, end_seconds: int) -> None:
    start = max(0, int(start_seconds))
    end = max(0, int(end_seconds))
    setup.profile.defaults.trim_start_seconds = start
    setup.profile.defaults.trim_end_seconds = end
    for stage in setup.profile.stages:
        stage.normalization.trim_start_seconds = start
        stage.normalization.trim_end_seconds = end


def toggle_stage_enabled(setup: RunSetupState, stage_index: int) -> None:
    if stage_index < 0 or stage_index >= len(setup.profile.stages):
        return
    stage = setup.profile.stages[stage_index]
    stage.enabled = not bool(stage.enabled)


def set_segment_label(setup: RunSetupState, stage_index: int, label: str) -> None:
    if stage_index < 0 or stage_index >= len(setup.profile.stages):
        return
    while len(setup.labels) < len(setup.profile.stages):
        next_stage = setup.profile.stages[len(setup.labels)]
        setup.labels.append(next_stage.name)
    text = str(label or "").strip()
    if text:
        setup.labels[stage_index] = text
