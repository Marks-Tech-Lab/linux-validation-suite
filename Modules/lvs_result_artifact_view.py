#!/usr/bin/env python3
"""Shared presentation models for result-artifact inventories and choices."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List


def _batch_count_text(item: Dict[str, Any]) -> str:
    counts = dict(item.get("batch_result_counts") or {})
    return ",".join(f"{key}={value}" for key, value in sorted(counts.items()))


def result_artifact_item_extras(item: Dict[str, Any], *, inventory: bool) -> List[str]:
    extras: List[str] = []
    if item.get("outcome_class"):
        extras.append(f"outcome={item.get('outcome_class')}")
    if inventory and item.get("department_status"):
        status = str(item.get("department_status"))
        if item.get("department_blocking") is not None:
            status += f",blocking={bool(item.get('department_blocking'))}"
        extras.append(f"department={status}")

    kind = item.get("kind")
    if kind == "profile_audit":
        extras.append(
            f"profiles={item.get('stage_count', 0)}, "
            + f"runnable={item.get('runnable_profile_count', 0)}, "
            + f"blocked={item.get('blocked_profile_count', 0)}"
        )
    elif kind == "results_inventory" and not inventory:
        extras.append(f"artifacts={item.get('stage_count', 0)}")
    elif kind == "result_validation_batch":
        extras.append(f"results={item.get('stage_count', 0)}")
        if item.get("batch_result_counts"):
            extras.append(f"batch={_batch_count_text(item)}")
    elif kind == "pre_import_sanity_batch":
        extras.append(f"results={item.get('stage_count', 0)}")
        if inventory:
            extras.append(
                f"summaries={item.get('summary_refreshed', 0)} refreshed/"
                + f"{item.get('summary_refresh_failed', 0)} failed"
            )
        else:
            extras.append(f"summaries={item.get('summary_refreshed', 0)}/{item.get('summary_refresh_failed', 0)}")
        if item.get("batch_result_counts"):
            extras.append(f"batch={_batch_count_text(item)}")
    elif item.get("stage_count"):
        extras.append(f"stages={item.get('stage_count')}")

    if item.get("validation_errors") or item.get("validation_warnings"):
        extras.append(f"validation={item.get('validation_errors', 0)}e/{item.get('validation_warnings', 0)}w")
    if item.get("validation_issue_category_counts"):
        categories = ",".join(
            f"{key}={value}"
            for key, value in sorted(dict(item.get("validation_issue_category_counts") or {}).items())
        )
        extras.append(f"validation_categories={categories}")
    if item.get("action_items"):
        extras.append(f"actions={item.get('action_items')}")
    if item.get("gpu_highlights"):
        extras.append(f"gpu_highlights={item.get('gpu_highlights')}")
    return extras


def result_artifact_choice_label(result_dir: Path, item: Dict[str, Any]) -> str:
    descriptor = item.get("profile_name") or item.get("kind") or "result"
    result = item.get("result") or "unknown"
    parts = [result_dir.name, str(item.get("kind") or "unknown"), str(descriptor), str(result)]
    extras = result_artifact_item_extras(item, inventory=False)
    if extras:
        parts.append(", ".join(extras))
    return " | ".join(part for part in parts if part)


def result_artifact_choice_text(
    candidates: Iterable[Path],
    *,
    item_for_path: Callable[[Path], Dict[str, Any]],
    heading: str = "Available result folders",
    limit: int = 30,
) -> str:
    paths = list(candidates)
    lines = ["", f"{heading}:"]
    for index, path in enumerate(paths[:limit], start=1):
        lines.append(f"{index}. {result_artifact_choice_label(path, item_for_path(path))}")
        lines.append(f"   {path}")
    if len(paths) > limit:
        lines.append(f"... {len(paths) - limit} more result folder(s) not shown.")
    return "\n".join(lines) + "\n"


def result_artifact_inventory_text(payload: Dict[str, Any], *, item_limit: int = 80) -> str:
    counts = payload.get("counts") or {}
    lines = [
        "",
        "Results Inventory",
        "=================",
        f"Results folder: {payload.get('results_dir')}",
        "Excluded root folders: Archived, Uploaded",
        f"Total artifact folders: {counts.get('total', 0)}",
        f"By kind: {counts.get('by_kind') or {}}",
        f"By result: {counts.get('by_result') or {}}",
    ]
    items = list(payload.get("items") or [])
    if not items:
        lines.append("No active result artifacts were found.")
        return "\n".join(lines) + "\n"

    lines.extend(["", "Recent artifacts", "----------------"])
    for item in items[:item_limit]:
        descriptor = item.get("profile_name") or item.get("kind") or "result"
        result = item.get("result") or "unknown"
        extras = result_artifact_item_extras(item, inventory=True)
        suffix = f" | {', '.join(extras)}" if extras else ""
        lines.append(f"- {item.get('folder_name')} | {item.get('kind')} | {descriptor} | {result}{suffix}")
        artifacts = ", ".join(item.get("artifacts") or [])
        if artifacts:
            lines.append(f"  artifacts: {artifacts}")
        for note in item.get("notes") or []:
            lines.append(f"  [note] {note}")
    if len(items) > item_limit:
        lines.append(f"... {len(items) - item_limit} more artifact folder(s) in saved JSON.")
    lines.append("")
    return "\n".join(lines) + "\n"
