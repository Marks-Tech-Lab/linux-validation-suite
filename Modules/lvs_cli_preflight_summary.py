from __future__ import annotations

from pathlib import Path
from typing import Any


def compact_cli_preflight_summary(
    report: dict[str, Any],
    *,
    report_dir: Path | None = None,
) -> str:
    """Short operator-facing launch preflight summary for normal CLI runs."""

    validation = report.get("validation") if isinstance(report.get("validation"), dict) else {}
    errors = list(validation.get("errors") or [])
    warnings = list(validation.get("warnings") or [])
    plan = list(report.get("plan") or [])
    enabled_count = int(report.get("enabled_stage_count") or 0)
    runnable_count = int(report.get("runnable_stage_count") or 0)
    runnable = bool(report.get("runnable")) if "runnable" in report else runnable_count > 0
    lines = [
        "Run Preflight",
        "-------------",
        f"Runnable: {'yes' if runnable else 'no'}",
        f"Stages: {runnable_count}/{enabled_count} runnable",
        f"Issues: {len(errors)} blocking, {len(warnings)} warning",
    ]
    stage_summaries = []
    for stage in plan:
        stage_errors = list(stage.get("issues") or [])
        stage_warnings = list(stage.get("warnings") or [])
        if not stage_errors and not stage_warnings:
            continue
        label = str(stage.get("label") or stage.get("name") or "Stage")
        stage_summaries.append(f"{label}: {len(stage_errors)} issue(s), {len(stage_warnings)} warning(s)")
    if stage_summaries:
        lines.append("Stage issue summary:")
        lines.extend(f"  - {summary}" for summary in stage_summaries[:8])
        if len(stage_summaries) > 8:
            lines.append(f"  - ... {len(stage_summaries) - 8} more stage(s)")
    if errors:
        lines.append("Blocking issues:")
        lines.extend(f"  [error] {message}" for message in errors[:6])
        if len(errors) > 6:
            lines.append(f"  ... {len(errors) - 6} more blocking issue(s)")
    if warnings and not stage_summaries:
        lines.append("Warning categories:")
        lines.extend(f"  [warn] {message}" for message in warnings[:4])
        if len(warnings) > 4:
            lines.append(f"  ... {len(warnings) - 4} more warning(s)")
    if report_dir is not None:
        lines.append(f"Full blocked-preflight details: {report_dir}")
    else:
        lines.append("Full details: run Dry Run / Diagnostics when detailed backend output is needed.")
    return "\n".join(lines) + "\n"
