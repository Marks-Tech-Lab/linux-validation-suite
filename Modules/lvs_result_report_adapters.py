#!/usr/bin/env python3
"""Filesystem adapters for result report browsing and summary refresh."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .lvs_core import JsonStore
from .lvs_service_models import FrontendActionSpec, ResultListEntry


RESULT_ACTIONS = {
    "i": FrontendActionSpec("i", "inventory", label="save/show results inventory"),
    "d": FrontendActionSpec("d", "stage_details", label="show selected result stage/GPU details"),
    "e": FrontendActionSpec("e", "qa_review", label="show selected result QA review readiness"),
    "f": FrontendActionSpec("f", "artifact_detail", label="show selected result artifact details"),
    "o": FrontendActionSpec("o", "compare_selected", label="compare selected result against a baseline"),
    "v": FrontendActionSpec("v", "validate_selected", label="validate selected result folder"),
    "a": FrontendActionSpec("a", "validate_all", label="validate all completed result folders"),
    "m": FrontendActionSpec("m", "pre_import_selected", label="pre-import sanity check selected result"),
    "b": FrontendActionSpec("b", "pre_import_all", label="pre-import sanity check all completed results"),
}


def read_result_json(path: Path) -> Dict[str, Any]:
    payload = JsonStore.read(path, {})
    return payload if isinstance(payload, dict) else {}


def list_result_entries(results_dir: Path) -> List[ResultListEntry]:
    if not results_dir.exists():
        return []
    entries: List[ResultListEntry] = []
    for path in sorted(results_dir.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
        if not path.is_dir() or path.name in {"Archived", "Uploaded"}:
            continue
        parsed_path = path / "parsed_results_custom.json"
        manifest_path = path / "run_manifest.json"
        payload = read_result_json(parsed_path) if parsed_path.exists() else read_result_json(manifest_path)
        entries.append(
            ResultListEntry(
                path=path,
                name=path.name,
                verdict=str(
                    payload.get("Verdict")
                    or payload.get("verdict")
                    or payload.get("Result")
                    or payload.get("result")
                    or "-"
                ),
                profile_name=str(
                    payload.get("ProfileName")
                    or payload.get("profile_name")
                    or (payload.get("Metadata") or {}).get("ProfileName")
                    or "-"
                ),
                started=str(payload.get("Started") or payload.get("started") or payload.get("StartTime") or "-"),
            )
        )
    return entries


def result_action_for_key(key: str) -> FrontendActionSpec:
    return RESULT_ACTIONS.get(str(key or "").lower(), FrontendActionSpec(str(key or ""), ""))


def result_action_help_text() -> str:
    descriptions = {
        "i": "save/show results inventory for all retained result folders",
        "d": "show stage/GPU details for the selected result",
        "e": "QA Review: one-screen review/import/compare/escalation readiness",
        "f": "Artifacts: locate parsed results, logs, telemetry, reports, and generated files",
        "o": "Comparison: choose a baseline and compare it with the selected result",
        "v": "Validation: check result/schema/report issues for the selected folder",
        "a": "validate all completed result folders",
        "m": "Pre-Import Sanity: decide whether the selected result is safe to import/review",
        "b": "pre-import sanity check all completed results",
    }
    lines = [
        "TUI Results actions:",
        "Use the selected result unless the action says all completed results.",
    ]
    for action in RESULT_ACTIONS.values():
        lines.append(f"- {action.key.upper()} {descriptions.get(action.key, action.label)}")
    lines.append(
        "QA wrapper note: linux_validation_suite_qa.py is for external automation; "
        "operators should use E/V/M/O/F here for the equivalent TUI workflows."
    )
    return "\n".join(lines)


def result_summary_text(result_dir: Path, summary_exporter: Any) -> str:
    summary_path = result_dir / "run_summary.txt"
    if summary_path.exists():
        return summary_path.read_text(encoding="utf-8", errors="replace")
    parsed_path = result_dir / "parsed_results_custom.json"
    if parsed_path.exists():
        payload = read_result_json(parsed_path)
        return summary_exporter.build(payload)
    return f"No run summary or parsed_results_custom.json found in {result_dir}"


def refresh_run_summary(result_dir: Path, summary_exporter: Any) -> Dict[str, Any]:
    parsed_path = result_dir / "parsed_results_custom.json"
    summary_path = result_dir / "run_summary.txt"
    status = {"summary_path": str(summary_path), "refreshed": False, "error": ""}
    try:
        parsed = read_result_json(parsed_path)
        if not parsed:
            raise ValueError("parsed_results_custom.json is missing or empty")
        summary_path.write_text(summary_exporter.build(parsed), encoding="utf-8")
        status["refreshed"] = True
    except Exception as exc:
        status["error"] = str(exc)
    return status


def completed_result_dirs(entries: List[ResultListEntry]) -> List[Path]:
    return [entry.path for entry in entries if (entry.path / "parsed_results_custom.json").exists()]


def count_entries_by(entries: List[ResultListEntry], field: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for entry in entries:
        value = str(getattr(entry, field, "") or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))
