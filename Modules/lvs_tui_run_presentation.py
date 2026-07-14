"""Textual-free run-active presentation helpers for the optional TUI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from .lvs_run_progress import run_event_history_text, run_status_detail_text, short_status_text


RUN_ACTIVE_SIDEBAR_TITLE = "Run Active"
RUN_ACTIVE_SIDEBAR_ROWS: Tuple[str, str] = (
    "Run in progress\n  navigation locked",
    "Esc / Back\n  request safe cancel",
)


@dataclass(frozen=True)
class TuiRunActivePresentation:
    status: str
    detail: str
    sidebar_title: str = RUN_ACTIVE_SIDEBAR_TITLE
    sidebar_rows: Tuple[str, ...] = RUN_ACTIVE_SIDEBAR_ROWS


@dataclass(frozen=True)
class TuiRunConfirmationPresentation:
    detail: str


def run_confirmation_presentation(
    *,
    profile_name: str,
    setup_summary: str,
    readiness_text: str,
    can_run: bool = True,
) -> TuiRunConfirmationPresentation:
    action_text = (
        "Press Run again, or press U, to start this profile.\n"
        if can_run
        else "Run is blocked. Fix the readiness issues above before starting.\n"
    )
    return TuiRunConfirmationPresentation(
        detail=(
            "Run confirmation\n"
            "================\n\n"
            f"Profile: {profile_name}\n\n"
            f"{setup_summary}\n\n"
            f"{readiness_text}\n\n"
            f"{action_text}"
            "Press Setup, Dry, Results, Profiles, or Refresh to cancel this confirmation.\n\n"
            "After the run, press W to save observed wall wattage or G to upload."
        )
    )


def initial_run_active_presentation(profile_name: str, heatsoak_minutes: float = 0.0) -> TuiRunActivePresentation:
    heatsoak_text = (
        f"Heatsoak: {float(heatsoak_minutes):g} min Power Test will run first.\n"
        if float(heatsoak_minutes or 0.0) > 0
        else ""
    )
    return TuiRunActivePresentation(
        status=f"Run active | {profile_name}",
        detail=(
            "Run In Progress\n"
            "===============\n\n"
            f"Profile: {profile_name}\n\n"
            "Status: active\n"
            f"{heatsoak_text}"
            "The workload runner is executing in the background. Live phase/progress "
            "output will appear here as it is emitted.\n\n"
            "Navigation is locked until the run reaches its post-run prompts.\n"
            "Press Esc or the footer Back action to request safe cancellation. "
            "Active workers are stopped through the same operator-stop path used for manual aborts."
        ),
    )


def _stage_label(fields: dict[str, str]) -> str:
    stage = str(fields.get("stage") or "").strip()
    name = str(fields.get("name") or "").strip()
    if stage and name and name != stage:
        return f"{stage} ({name})"
    return stage or name or "Stage"


def _stage_detail_suffix(fields: dict[str, str], *, include_target: bool = False) -> str:
    details = []
    for field in ("elapsed", "remaining", "verdict", "workload"):
        value = fields.get(field)
        if value:
            details.append(f"{field}={value}")
    if include_target:
        for field in ("target", "gpu_target"):
            value = fields.get(field)
            if value:
                details.append(f"{field}={value}")
                break
    return " | " + " | ".join(details) if details else ""


def _event_stage_status(event_type: str, fields: dict[str, str]) -> str:
    if event_type in {"stage-start", "stage-progress"}:
        return "running"
    if event_type == "stage-end":
        return str(fields.get("verdict") or "complete")
    if event_type == "stage-abort":
        return str(fields.get("verdict") or "aborted")
    if event_type == "stage-skip":
        return "skipped"
    if event_type == "heatsoak-start":
        return "running"
    if event_type == "heatsoak-progress":
        return "running"
    if event_type == "heatsoak-end":
        return str(fields.get("verdict") or "complete")
    if event_type == "heatsoak-cancel":
        return str(fields.get("verdict") or "cancelled")
    return event_type.replace("-", " ") or "event"


def stage_progress_table_text(events: Iterable[object], *, limit: int = 24, width: int = 120) -> str:
    rows: dict[str, str] = {}
    order: list[str] = []
    for event in events:
        event_type = str(getattr(event, "event_type", "") or "")
        fields = getattr(event, "fields", {}) if isinstance(getattr(event, "fields", {}), dict) else {}
        if event_type.startswith("heatsoak"):
            key = "Heatsoak"
            label = "Heatsoak"
        else:
            key = str(fields.get("stage") or "").strip()
            if not key:
                continue
            label = f"Stage {_stage_label(fields)}"
        if key not in order:
            order.append(key)
        status = _event_stage_status(event_type, fields)
        suffix = _stage_detail_suffix(fields)
        rows[key] = short_status_text(f"- {label}: {status}{suffix}", width)
    if not order:
        return "Stage Progress\n--------------\n(waiting for stage progress...)"
    selected = order[-max(1, int(limit)):]
    lines = ["Stage Progress", "--------------"]
    lines.extend(rows[key] for key in selected if key in rows)
    if len(order) > len(selected):
        lines.append(f"... {len(order) - len(selected)} earlier stage(s)")
    return "\n".join(lines)


def active_stage_line_text(status_snapshot: object, events: Iterable[object], *, width: int = 120) -> str:
    snapshot_stage = str(getattr(status_snapshot, "stage", "") or "").strip()
    latest_progress = None
    for event in events:
        if str(getattr(event, "event_type", "") or "") in {"stage-progress", "heatsoak-progress", "stage-start", "heatsoak-start"}:
            latest_progress = event
    if latest_progress is not None:
        event_type = str(getattr(latest_progress, "event_type", "") or "")
        fields = getattr(latest_progress, "fields", {}) if isinstance(getattr(latest_progress, "fields", {}), dict) else {}
        label = "Heatsoak" if event_type.startswith("heatsoak") else _stage_label(fields)
        suffix = _stage_detail_suffix(fields, include_target=True)
        return short_status_text(f"Active: {label} | {_event_stage_status(event_type, fields)}{suffix}", width)
    if snapshot_stage:
        elapsed = str(getattr(status_snapshot, "elapsed", "") or "")
        remaining = str(getattr(status_snapshot, "remaining", "") or "")
        parts = [f"Active: {snapshot_stage}", str(getattr(status_snapshot, "status", "") or "running").replace("_", " ")]
        if elapsed:
            parts.append(f"elapsed={elapsed}")
        if remaining:
            parts.append(f"remaining={remaining}")
        return short_status_text(" | ".join(parts), width)
    return "Active: waiting for stage progress..."


def output_tail_text(output_lines: Iterable[str], *, limit: int = 4, width: int = 120) -> str:
    selected = [short_status_text(line, width) for line in list(output_lines)[-max(0, int(limit)):] if str(line).strip()]
    if not selected:
        return "(no non-progress output yet)"
    return "\n".join(selected)


def run_progress_detail_text(
    *,
    profile_name: str,
    status_snapshot: object,
    phase_line: str,
    events: Iterable[object],
    output_lines: Iterable[str],
) -> str:
    output = output_tail_text(output_lines)
    latest_phase = short_status_text(phase_line or "(waiting for phase output...)", 120)
    return (
        "Run In Progress\n"
        "===============\n\n"
        f"Profile: {profile_name or '-'}\n\n"
        "Current Status\n"
        "--------------\n"
        f"{run_status_detail_text(status_snapshot)}\n"
        f"{active_stage_line_text(status_snapshot, events)}\n"
        f"Latest: {latest_phase}\n\n"
        f"{stage_progress_table_text(events)}\n\n"
        "Output Tail\n"
        "-----------\n"
        f"{output or '(no non-progress output yet)'}"
    )


def locked_run_detail_text(
    *,
    profile_name: str,
    status_snapshot: object,
    phase_line: str,
    events: Iterable[object],
    cancel_requested: bool = False,
) -> str:
    message = (
        "Run In Progress\n"
        "===============\n\n"
        f"Profile: {profile_name or '-'}\n\n"
        "Navigation and edits are locked while the workload is active.\n\n"
        "Press Esc or the footer Back action to request safe cancellation. "
        "Cancellation stops active workers and saves partial run results through the existing operator-stop path.\n\n"
        f"{run_status_detail_text(status_snapshot)}\n"
        f"Latest phase: {phase_line or '(waiting for phase output...)'}\n\n"
        f"{stage_progress_table_text(events)}\n\n"
        f"{run_event_history_text(events, limit=5)}"
    )
    if cancel_requested:
        message += "\n\nCancel requested: stopping active workers and saving partial run results."
    return message


def locked_post_run_wall_wattage_text() -> str:
    return (
        "Run Complete\n"
        "============\n\n"
        "Enter wall wattage in the input field, or leave it blank and press Enter to skip. "
        "Press Esc to cancel this prompt."
    )


def locked_post_run_upload_text() -> str:
    return (
        "Run Complete\n"
        "============\n\n"
        "Choose Upload to Google Drive or Skip upload from the sidebar. "
        "Press Esc to skip this prompt."
    )


def _artifact_status_line(result_dir: Path, artifact_names: set[str], label: str, filename: str) -> str:
    available = filename in artifact_names or (result_dir / filename).exists()
    return f"- {label}: {'available' if available else 'missing'} ({filename})"


def post_run_operator_presentation(
    base_text: str,
    *,
    result_dir: Path | None,
    artifact_item: Dict[str, Any] | None = None,
    upload_status: str = "",
) -> str:
    item = artifact_item if isinstance(artifact_item, dict) else {}
    artifact_names = {str(name) for name in item.get("artifacts") or [] if str(name)}
    lines = ["TUI Post-Run Context", "--------------------"]
    if result_dir is None:
        lines.extend(
            [
                "Result folder: not available",
                "Artifacts: not available",
                "",
                "Operator Next Steps",
                "-------------------",
                "- Review the failure text and captured phase output above.",
                "- No result-folder actions are available until a result folder exists.",
            ]
        )
        lines.extend(["", "Run / Upload Output", "-------------------", str(base_text).rstrip()])
        return "\n".join(lines) + "\n"

    lines.append(f"Latest result folder: {result_dir}")
    if item.get("kind"):
        lines.append(f"Artifact kind: {item.get('kind')}")
    if item.get("result"):
        lines.append(f"Artifact result: {item.get('result')}")
    if upload_status:
        lines.append(f"Upload status: {upload_status}")
    lines.extend(
        [
            "",
            "Artifact Availability",
            "---------------------",
            _artifact_status_line(result_dir, artifact_names, "Parsed results", "parsed_results_custom.json"),
            _artifact_status_line(result_dir, artifact_names, "Run summary", "run_summary.txt"),
            _artifact_status_line(result_dir, artifact_names, "Validation report", "result_validation.json"),
            _artifact_status_line(result_dir, artifact_names, "Pre-import sanity", "pre_import_sanity.json"),
            _artifact_status_line(result_dir, artifact_names, "Telemetry source map", "telemetry_source_map.json"),
            _artifact_status_line(result_dir, artifact_names, "Raw telemetry", "raw_telemetry.csv"),
            "",
            "Operator Next Steps",
            "-------------------",
            "- Press W to add or update observed wall wattage.",
            "- Press G to upload this latest result if Google Drive is configured.",
            "- Open Results to review this latest result, then use E for QA review, F for artifacts, V for validation, or M for pre-import.",
            "",
            "Run / Upload Output",
            "-------------------",
            str(base_text).rstrip(),
        ]
    )
    return "\n".join(lines) + "\n"
