"""Textual-free profile edit presentation helpers for the optional TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional, Tuple

from .lvs_tui_view_models import profile_edit_row_label


@dataclass(frozen=True)
class TuiProfileEditPresentation:
    labels: Tuple[str, ...]
    selected_index: Optional[int]
    detail: str


@dataclass(frozen=True)
class TuiProfileEditInputPresentation:
    pending_field: str
    value: str
    placeholder: str
    detail: str


def profile_edit_presentation(
    items: Iterable[Any],
    selected_index: int,
    summary: str,
    detail_prefix: str = "",
) -> TuiProfileEditPresentation:
    rows = tuple(profile_edit_row_label(item) for item in items)
    clamped_index: Optional[int] = None
    if rows:
        clamped_index = min(max(0, int(selected_index)), len(rows) - 1)
    detail = (str(detail_prefix) + "\n\n" if detail_prefix else "") + str(summary)
    return TuiProfileEditPresentation(labels=rows, selected_index=clamped_index, detail=detail)


def selected_stage_detail_text(profile_summary: str) -> str:
    return (
        str(profile_summary)
        + "\n\nSelected stage. Use D duration, L label, T toggle, Delete remove, "
        "G GPU target, B backend, I intensity, C compute variant, "
        "P CPU instruction, R memory instruction, N trim, V VRAM %, or M memory %. "
        "For Storage Benchmark stages, use the indented storage configuration rows directly below the stage; duration is not applicable."
    )


def profile_edit_text_input_presentation(
    *,
    pending_field: str,
    value: object,
    label: str,
    profile_summary: str,
    placeholder: str = "",
) -> TuiProfileEditInputPresentation:
    label_text = str(label)
    return TuiProfileEditInputPresentation(
        pending_field=str(pending_field),
        value="" if value is None else str(value),
        placeholder=str(placeholder or f"Enter {label_text} and press Enter"),
        detail=(
            str(profile_summary)
            + f"\n\nEditing: {label_text}. Type the value below and press Enter. Press Esc to cancel."
        ),
    )


def profile_edit_description_input_presentation(
    *,
    value: object,
    profile_summary: str,
) -> TuiProfileEditInputPresentation:
    return TuiProfileEditInputPresentation(
        pending_field="__profile_description",
        value="" if value is None else str(value),
        placeholder="Enter profile menu description and press Enter",
        detail=(
            str(profile_summary)
            + "\n\nEditing profile description. Type the value below and press Enter. Press Esc to cancel."
        ),
    )


def profile_edit_name_input_presentation(
    *,
    value: object,
    profile_summary: str,
) -> TuiProfileEditInputPresentation:
    return TuiProfileEditInputPresentation(
        pending_field="__profile_name",
        value="" if value is None else str(value),
        placeholder="Enter profile name and press Enter",
        detail=(
            str(profile_summary)
            + "\n\nEditing profile name. Type the value below and press Enter. Press Esc to cancel."
        ),
    )


def profile_edit_stage_input_presentation(
    *,
    spec: Any,
    profile_summary: str,
) -> TuiProfileEditInputPresentation:
    return profile_edit_text_input_presentation(
        pending_field=getattr(spec, "field", ""),
        value=getattr(spec, "initial_value", ""),
        label=getattr(spec, "label", ""),
        profile_summary=profile_summary,
    )


def profile_edit_updated_detail() -> str:
    return "Profile edit updated."


def profile_edit_failed_detail(error: object, profile_summary: str) -> str:
    return f"Profile edit failed:\n{error}\n\n{profile_summary}"
