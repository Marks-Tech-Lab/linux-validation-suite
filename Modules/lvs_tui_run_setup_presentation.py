"""Textual-free run setup presentation helpers for the optional TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional, Tuple

from .lvs_tui_view_models import setup_action_row_label, setup_history_row_label


RUN_SETUP_SIDEBAR_TITLE = "Run Setup"
RUN_SETUP_HISTORY_SIDEBAR_TITLE = "Setup History"
RUN_SETUP_STAGE_INPUT_COMPLETE = "complete"
RUN_SETUP_STAGE_INPUT_TRIM_END = "trim_end_input"
RUN_SETUP_STAGE_INPUT_COMPLETE_TRIM = "complete_trim"
RUN_SETUP_STAGE_INPUT_NOOP = "noop"


@dataclass(frozen=True)
class TuiRunSetupSidebarPresentation:
    title: str
    rows: Tuple[str, ...]
    selected_index: Optional[int]
    detail: str


@dataclass(frozen=True)
class TuiRunSetupInputPresentation:
    pending_field: str
    value: str
    blank_default: str
    placeholder: str
    detail: str


@dataclass(frozen=True)
class TuiRunSetupHistoryPresentation:
    title: str
    rows: Tuple[str, ...]
    selected_index: Optional[int]
    detail: str


@dataclass(frozen=True)
class TuiRunSetupStageInputTransition:
    action: str
    start: Optional[int] = None
    end: Optional[int] = None
    next_field: str = ""
    next_label: str = ""
    next_value: str = ""
    next_blank_default: str = ""


def _parse_nonnegative_int(value: object, fallback: int) -> int:
    try:
        return max(0, int(float(str(value or "").strip())))
    except Exception:
        return int(fallback)


def run_setup_detail_presentation(overview: str, action_detail: str = "") -> str:
    base = str(overview or "")
    if "Recall previous setup:" not in base:
        base += "\n\nRecall previous setup: press H or select Load previous setup from the left list."
    detail = str(action_detail or "")
    return base + f"\n\n{detail}" if detail else base


def run_setup_sidebar_presentation(
    *,
    actions: Iterable[Any],
    overview: str,
    selected_index: int = 0,
) -> TuiRunSetupSidebarPresentation:
    rows = tuple(setup_action_row_label(action) for action in actions)
    clamped_index: Optional[int] = None
    if rows:
        clamped_index = min(max(0, int(selected_index)), len(rows) - 1)
    return TuiRunSetupSidebarPresentation(
        title=RUN_SETUP_SIDEBAR_TITLE,
        rows=rows,
        selected_index=clamped_index,
        detail=run_setup_detail_presentation(overview),
    )


def run_setup_history_presentation(
    *,
    entries: Iterable[Any],
    setup_summary: str,
    selected_index: int = 0,
) -> TuiRunSetupHistoryPresentation:
    rows = tuple(setup_history_row_label(entry) for entry in entries)
    clamped_index: Optional[int] = None
    if rows:
        clamped_index = min(max(0, int(selected_index)), len(rows) - 1)
    return TuiRunSetupHistoryPresentation(
        title=RUN_SETUP_HISTORY_SIDEBAR_TITLE,
        rows=rows,
        selected_index=clamped_index,
        detail=(
            str(setup_summary or "")
            + "\n\nLoad Previous Run Setup\n"
            "Use Up/Down and Enter to recall a setup. Press Esc to return without changing.\n"
            "Wall wattage is not recalled and will still be entered after the run."
        ),
    )


def run_setup_no_history_detail(setup_summary: str) -> str:
    return str(setup_summary or "") + "\n\nNo previous run setup history is available yet."


def run_setup_history_prompt_presentation(
    *,
    setup_summary: str,
    entry_count: int,
) -> TuiRunSetupHistoryPresentation:
    count = max(0, int(entry_count))
    plural = "setup" if count == 1 else "setups"
    return TuiRunSetupHistoryPresentation(
        title="Recall Setup?",
        rows=("Recall previous setup", "Skip recall"),
        selected_index=0,
        detail=(
            str(setup_summary or "")
            + "\n\nRecall Previous Run Setup\n"
            f"{count} previous run {plural} available.\n\n"
            "Choose Recall previous setup to review and apply one before continuing. "
            "Choose Skip recall to continue with the current profile defaults.\n"
            "This mirrors the CLI recall prompt shown after choosing a test profile."
        ),
    )


def run_setup_history_loaded_detail(setup_summary: str) -> str:
    return (
        str(setup_summary or "")
        + "\n\nPrevious run setup loaded. Wall wattage will still be collected after this run."
    )


def run_setup_history_confirm_presentation(
    *,
    entry: Any,
    setup_summary: str,
) -> TuiRunSetupHistoryPresentation:
    label = setup_history_row_label(entry)
    return TuiRunSetupHistoryPresentation(
        title="Recall Setup?",
        rows=("Apply selected setup", "Cancel"),
        selected_index=0,
        detail=(
            str(setup_summary or "")
            + "\n\nRecall Previous Run Setup\n"
            "Selected:\n"
            f"{label}\n\n"
            "Choose Apply selected setup to copy this previous run setup into the current run review. "
            "Choose Cancel or press Esc to return without changing.\n"
            "Wall wattage is not recalled and will still be entered after the run."
        ),
    )


def run_setup_stage_input_transition(
    *,
    field: str,
    value: object,
    pending_trim_start: Optional[int],
    default_trim_start: int,
    default_trim_end: int,
) -> TuiRunSetupStageInputTransition:
    if field in {"stage_duration", "segment_label"}:
        return TuiRunSetupStageInputTransition(action=RUN_SETUP_STAGE_INPUT_COMPLETE)
    if field == "trim_start":
        start = _parse_nonnegative_int(value, int(default_trim_start))
        current_end = int(default_trim_end)
        return TuiRunSetupStageInputTransition(
            action=RUN_SETUP_STAGE_INPUT_TRIM_END,
            start=start,
            next_field="trim_end",
            next_label="Trim end seconds",
            next_value=str(current_end),
            next_blank_default=str(current_end),
        )
    if field == "trim_end":
        end = _parse_nonnegative_int(value, int(default_trim_end))
        start = int(pending_trim_start) if pending_trim_start is not None else int(default_trim_start)
        return TuiRunSetupStageInputTransition(
            action=RUN_SETUP_STAGE_INPUT_COMPLETE_TRIM,
            start=start,
            end=end,
        )
    return TuiRunSetupStageInputTransition(action=RUN_SETUP_STAGE_INPUT_NOOP)


def run_setup_input_presentation(
    *,
    field: str,
    spec: Any,
    setup_summary: str,
) -> TuiRunSetupInputPresentation:
    label = str(getattr(spec, "label", field))
    return TuiRunSetupInputPresentation(
        pending_field=str(field),
        value=str(getattr(spec, "initial_value", "")),
        blank_default=str(getattr(spec, "blank_default", "")),
        placeholder=f"Enter {label} and press Enter, or Esc to cancel",
        detail=(
            str(setup_summary or "")
            + f"\n\nEditing: {label}. Type the value below and press Enter. Press Esc to cancel."
        ),
    )
