"""Textual-free settings presentation helpers for the optional TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple


@dataclass(frozen=True)
class TuiSettingsListPresentation:
    title: str
    values: Tuple[str, ...]
    selected_index: Optional[int]
    detail: str


@dataclass(frozen=True)
class TuiSettingsListInputPresentation:
    pending_field: str
    value: str
    placeholder: str
    detail: str
    selected_index: Optional[int]


@dataclass(frozen=True)
class TuiSettingsInputPresentation:
    pending_field: str
    value: str
    placeholder: str
    detail: str


SETTINGS_NUMERIC_FIELDS = frozenset({"sample_interval_seconds", "trim_start_seconds", "trim_end_seconds"})


def settings_input_presentation(
    *,
    field: str,
    label: str,
    value: object,
    summary: str,
) -> TuiSettingsInputPresentation | None:
    if field == "department":
        pending_field = "__settings_department"
    elif field in SETTINGS_NUMERIC_FIELDS:
        pending_field = f"__settings_numeric:{field}"
    else:
        return None
    return TuiSettingsInputPresentation(
        pending_field=pending_field,
        value="" if value is None else str(value),
        placeholder=f"Enter {label} and press Enter, or Esc to cancel",
        detail=str(summary) + f"\n\nEditing: {label}. Type the value below and press Enter. Press Esc to cancel.",
    )


def settings_list_presentation(
    *,
    title: str,
    values: Iterable[str],
    selected_index: int,
    summary: str,
    detail: str = "",
) -> TuiSettingsListPresentation:
    rows = tuple(str(value) for value in values)
    clamped_index: Optional[int] = None
    if rows:
        clamped_index = min(max(0, int(selected_index)), len(rows) - 1)
    return TuiSettingsListPresentation(
        title=str(title),
        values=rows,
        selected_index=clamped_index,
        detail=str(detail or summary),
    )


def settings_list_input_presentation(
    *,
    mode: str,
    title: str,
    values: Iterable[str],
    selected_index: int,
    summary: str,
) -> TuiSettingsListInputPresentation | None:
    rows = tuple(str(value) for value in values)
    if mode == "add":
        action = "Adding"
        return TuiSettingsListInputPresentation(
            pending_field="__settings_list_add",
            value="",
            placeholder=f"Add item to {title}, then press Enter",
            detail=str(summary) + f"\n\n{action}: type the value below and press Enter. Press Esc to cancel.",
            selected_index=None,
        )
    if not rows:
        return None
    clamped_index = min(max(0, int(selected_index)), len(rows) - 1)
    action = "Renaming"
    return TuiSettingsListInputPresentation(
        pending_field="__settings_list_rename",
        value=rows[clamped_index],
        placeholder=f"Rename selected {title} item, then press Enter",
        detail=str(summary) + f"\n\n{action}: type the value below and press Enter. Press Esc to cancel.",
        selected_index=clamped_index,
    )
