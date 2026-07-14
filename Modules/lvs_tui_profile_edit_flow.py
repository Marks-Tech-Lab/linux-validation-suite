#!/usr/bin/env python3
"""Deterministic profile-edit flow helpers for TUI and future frontends."""

from __future__ import annotations

from typing import Any, Sequence


def selected_profile_edit_stage_index(
    items: Sequence[Any],
    selected_index: int,
    *,
    edit_present: bool,
) -> int | None:
    """Return the selected profile stage index, or ``None`` for non-stage rows."""
    if not edit_present or selected_index < 0 or selected_index >= len(items):
        return None
    item = items[selected_index]
    if getattr(item, "kind", "") != "stage":
        return None
    return getattr(item, "index", None)


def normalized_profile_edit_input_value(value: object) -> str:
    return str(value or "").strip()


def profile_edit_trim_start_value(
    field: str,
    value: object,
    *,
    pending_stage_index: int | None,
) -> int | None:
    """Parse the first trim input step when the selected stage is still active."""
    if field != "__profile_stage_trim_start" or pending_stage_index is None:
        return None
    return max(0, int(float(normalized_profile_edit_input_value(value) or "0")))
