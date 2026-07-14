#!/usr/bin/env python3
"""Strict threshold recommendation warning policy helpers."""

from __future__ import annotations

from typing import Any


def optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disabled"}:
        return False
    return None


def profile_strict_threshold_recommendation_warnings(profile: Any, global_default: bool) -> bool:
    profile_override = optional_bool(profile.defaults.strict_threshold_recommendation_warnings)
    if profile_override is not None:
        return profile_override
    return bool(global_default)


def stage_strict_threshold_recommendation_warnings(
    profile: Any,
    stage: Any,
    global_default: bool,
) -> bool:
    stage_override = optional_bool(stage.strict_threshold_recommendation_warnings)
    if stage_override is not None:
        return stage_override
    return profile_strict_threshold_recommendation_warnings(profile, global_default)


def strict_threshold_warning_scope(profile: Any) -> str:
    profile_override = optional_bool(profile.defaults.strict_threshold_recommendation_warnings)
    stage_overrides = [
        stage
        for stage in profile.stages
        if optional_bool(stage.strict_threshold_recommendation_warnings) is not None
    ]
    if stage_overrides:
        return "stage"
    if profile_override is not None:
        return "profile"
    return "global"
