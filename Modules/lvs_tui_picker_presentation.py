"""Textual-free picker presentation helpers for the optional TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

from .lvs_tui_view_models import picker_row_labels


@dataclass(frozen=True)
class TuiPickerPresentation:
    key: str
    title: str
    options: Tuple[str, ...]
    labels: Tuple[str, ...]
    selected_index: int
    detail: str
    view_mode: str


@dataclass(frozen=True)
class TuiPickerOpenPresentation:
    picker: TuiPickerPresentation
    key: str
    options: Tuple[str, ...]
    confirm_run: bool = False
    stage_index: Optional[int] = None


def setup_picker_presentation(spec: Any, setup_summary: str) -> TuiPickerPresentation:
    labels, selected_index = picker_row_labels(getattr(spec, "options", ()), getattr(spec, "current", ""))
    title = str(getattr(spec, "title", "") or "")
    return TuiPickerPresentation(
        key=str(getattr(spec, "key", "") or ""),
        title=title,
        options=tuple(str(option) for option in getattr(spec, "options", ()) or ()),
        labels=tuple(labels),
        selected_index=selected_index,
        detail=(
            str(setup_summary)
            + f"\n\nChoosing: {title}\n"
            "Use Up/Down and Enter to select. Press Esc to return without changing."
        ),
        view_mode="setup_picker",
    )


def setup_picker_open_presentation(spec: Any, setup_summary: str) -> TuiPickerOpenPresentation:
    picker = setup_picker_presentation(spec, setup_summary)
    return TuiPickerOpenPresentation(
        picker=picker,
        key=picker.key,
        options=picker.options,
        confirm_run=False,
    )


def profile_edit_picker_presentation(spec: Any, profile_summary: str) -> TuiPickerPresentation:
    labels, selected_index = picker_row_labels(getattr(spec, "options", ()), getattr(spec, "current", ""))
    title = str(getattr(spec, "title", "") or "")
    return TuiPickerPresentation(
        key=str(getattr(spec, "key", "") or ""),
        title=title,
        options=tuple(str(option) for option in getattr(spec, "options", ()) or ()),
        labels=tuple(labels),
        selected_index=selected_index,
        detail=(
            str(profile_summary)
            + f"\n\nChoosing: {title}\n"
            "Use Up/Down and Enter to select. Press Esc to return without changing."
        ),
        view_mode="profile_edit_picker",
    )


def profile_edit_picker_open_presentation(
    spec: Any,
    profile_summary: str,
    *,
    stage_index: Optional[int],
) -> TuiPickerOpenPresentation:
    picker = profile_edit_picker_presentation(spec, profile_summary)
    return TuiPickerOpenPresentation(
        picker=picker,
        key=picker.key,
        options=picker.options,
        stage_index=stage_index,
    )
