"""Textual-free post-run prompt specs for the optional TUI frontend."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Tuple


UPLOAD_PROMPT_OPTIONS: Tuple[str, str] = ("Upload to Google Drive", "Skip upload")
POST_RUN_ACTION_FAILED = "failed"
POST_RUN_ACTION_WALL_WATTAGE = "wall_wattage"
POST_RUN_ACTION_UPLOAD_PROMPT = "upload_prompt"
POST_RUN_ACTION_COMPLETE = "complete"


@dataclass(frozen=True)
class TuiPostRunPromptSpec:
    pending_field: str
    placeholder: str
    status: str
    detail: str
    enabled: bool = True
    focus: bool = True
    view_mode: str = ""
    sidebar_title: str = ""
    sidebar_options: Tuple[str, ...] = ()
    selected_index: int = 0


@dataclass(frozen=True)
class TuiPostRunPromptPresentation:
    pending_field: str
    placeholder: str
    detail: str
    enabled: bool
    focus: bool
    status: str
    view_mode: str
    sidebar_title: str
    sidebar_options: Tuple[str, ...]
    selected_index: int


@dataclass(frozen=True)
class TuiPostRunCompletionTransition:
    action: str
    status: str
    detail: str


def post_run_prompt_presentation(spec: TuiPostRunPromptSpec) -> TuiPostRunPromptPresentation:
    return TuiPostRunPromptPresentation(
        pending_field=spec.pending_field,
        placeholder=spec.placeholder,
        detail=spec.detail,
        enabled=spec.enabled,
        focus=spec.focus,
        status=spec.status,
        view_mode=spec.view_mode,
        sidebar_title=spec.sidebar_title,
        sidebar_options=tuple(spec.sidebar_options),
        selected_index=spec.selected_index,
    )


def post_run_completion_transition(
    *,
    result_available: bool,
    completed_text: str,
    prompt_for_wall_wattage: bool,
    prompt_for_upload: bool,
) -> TuiPostRunCompletionTransition:
    text = str(completed_text or "")
    if not result_available:
        return TuiPostRunCompletionTransition(
            action=POST_RUN_ACTION_FAILED,
            status="Run failed",
            detail=text,
        )
    if prompt_for_wall_wattage:
        return TuiPostRunCompletionTransition(
            action=POST_RUN_ACTION_WALL_WATTAGE,
            status="",
            detail=text,
        )
    if prompt_for_upload:
        return TuiPostRunCompletionTransition(
            action=POST_RUN_ACTION_UPLOAD_PROMPT,
            status="",
            detail=text,
        )
    return TuiPostRunCompletionTransition(
        action=POST_RUN_ACTION_COMPLETE,
        status="Run complete",
        detail=text,
    )


def should_prompt_for_post_run_upload(last_run_dir: Any, google_drive_prompt_after_run: bool) -> bool:
    return last_run_dir is not None and bool(google_drive_prompt_after_run)


def post_run_wall_wattage_prompt_spec(
    outcome: Any,
    *,
    placeholder: str = "Enter max wall wattage, or leave blank and press Enter to skip",
) -> TuiPostRunPromptSpec:
    return TuiPostRunPromptSpec(
        pending_field="__post_wall_wattage",
        placeholder=placeholder,
        status=str(getattr(outcome, "status", "") or "Run complete | Waiting for wall wattage"),
        detail=str(getattr(outcome, "text", "") or ""),
    )


def post_run_upload_prompt_spec(outcome: Any) -> TuiPostRunPromptSpec:
    return TuiPostRunPromptSpec(
        pending_field="__post_upload_prompt",
        placeholder="Use the upload choice list, or press Esc to skip.",
        status=str(getattr(outcome, "status", "") or "Run complete | Waiting for upload choice"),
        detail=str(getattr(outcome, "text", "") or ""),
        enabled=False,
        focus=False,
        view_mode="post_run_upload_picker",
        sidebar_title="Upload?",
        sidebar_options=UPLOAD_PROMPT_OPTIONS,
        selected_index=1,
    )


def post_run_skip_upload_base_text(prompt_text: str, fallback_text: str) -> str:
    return str(prompt_text or fallback_text or "Run complete")
