from __future__ import annotations

"""Frontend-neutral helpers for active TUI run execution state."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List

from Modules.lvs_run_progress import is_phase_progress_line, run_event_history_text, run_status_detail_text, short_status_text
from Modules.lvs_tui_run_presentation import run_progress_detail_text


def tail_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return "... output truncated ...\n" + text[-limit:]


def interaction_locked(run_in_progress: bool, pending_input_field: str | None) -> bool:
    return bool(run_in_progress or pending_input_field)


def run_progress_text(
    *,
    profile_name: str,
    status_snapshot: Any,
    phase_line: str,
    events: List[Any],
    output_lines: List[str],
) -> str:
    return run_progress_detail_text(
        profile_name=profile_name,
        status_snapshot=status_snapshot,
        phase_line=phase_line,
        events=events,
        output_lines=output_lines,
    )


@dataclass(frozen=True)
class RunOutputUpdate:
    output_lines: List[str]
    phase_line: str
    status_text: str
    is_progress: bool


def apply_run_output_line(
    *,
    line: str,
    output_lines: List[str],
    phase_line: str,
    status_snapshot: Any,
    tracker_status_text: str,
    limit: int = 80,
) -> RunOutputUpdate | None:
    text = str(line or "").rstrip()
    if not text:
        return None
    if not is_phase_progress_line(text):
        next_lines = [*output_lines, text][-limit:]
        return RunOutputUpdate(next_lines, phase_line, tracker_status_text, False)
    status_text = tracker_status_text
    if getattr(status_snapshot, "status", "") == "idle":
        status_text = short_status_text(text, 96)
    return RunOutputUpdate(list(output_lines)[-limit:], text, status_text, True)


def run_success_thread_text(service: Any, result: Any, output_limit: int = 2000) -> str:
    final_status = ""
    if result.run_status is not None:
        final_status = (
            "\n\nFinal structured status:\n"
            "------------------------\n"
            f"{run_status_detail_text(result.run_status)}\n\n"
            f"{run_event_history_text(result.progress_events, limit=8)}"
        )
    return (
        service.run_complete_outcome(result.run_dir).text
        + final_status
        + "\n\nCaptured output tail:\n"
        f"{tail_text(result.output, output_limit)}"
    )


def run_execution_error_text(exc: Any, output_limit: int = 2000) -> str:
    text = (
        "Run failed\n"
        "==========\n\n"
        f"{exc}\n\n"
        "Final structured status:\n"
        "------------------------\n"
        f"{run_status_detail_text(exc.run_status)}\n\n"
        f"{run_event_history_text(exc.progress_events, limit=8)}"
    )
    if exc.output:
        text += "\n\nCaptured output tail:\n" + tail_text(exc.output, output_limit)
    return text


def upload_not_ready_detail(result_dir: Any, readiness: Any) -> str:
    payload = readiness if isinstance(readiness, dict) else {}
    missing = ", ".join(str(item) for item in payload.get("missing") or []) or "unknown"
    return (
        "Google Drive Upload Not Ready\n"
        "=============================\n\n"
        f"Result folder: {result_dir}\n"
        f"Missing: {missing}\n"
        f"Credential path: {payload.get('credential_path') or '-'}"
    )


def upload_active_detail(result_dir: Any) -> str:
    return (
        "Google Drive Upload\n"
        "===================\n\n"
        f"Uploading: {result_dir}\n\n"
        "This can take a while."
    )


def upload_workflow_detail(
    *,
    title: str,
    result_dir: Any,
    status: str,
    body: str,
) -> str:
    return (
        f"{title}\n"
        f"{'=' * len(str(title or 'Upload'))}\n\n"
        f"Result folder: {result_dir or '-'}\n"
        f"Status: {status or '-'}\n\n"
        f"{str(body or '').strip()}\n\n"
        "Operator Next Steps\n"
        "-------------------\n"
        "- Use the left-side choices when prompted.\n"
        "- Press Esc/Back to skip an upload prompt.\n"
        "- After upload completes, review the status and latest result folder here."
    )


def upload_thread_failure_text(exc: Exception) -> str:
    return f"Google Drive upload failed:\n{exc}"


def upload_finish_result(payload: Any, fallback_text: str, service: Any) -> tuple[str, str, Any]:
    if isinstance(payload, dict) and payload:
        outcome = service.upload_result_outcome(payload)
        return outcome.status, outcome.text, outcome
    result = str(payload.get("result") or "failed") if isinstance(payload, dict) else "failed"
    return f"Google Drive upload {result}", fallback_text, None


def uploaded_result_dir(payload: Any) -> Path | None:
    if not isinstance(payload, dict):
        return None
    moved_to = payload.get("moved_to")
    return Path(str(moved_to)) if moved_to else None
