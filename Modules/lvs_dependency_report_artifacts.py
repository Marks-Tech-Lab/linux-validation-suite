#!/usr/bin/env python3
"""Artifact writers for dependency check reports."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .lvs_core import JsonStore, now_local_iso
from .lvs_dependency_report_text import dependency_check_summary_text


def new_report_dir(results_dir: Path | str, suffix: str) -> Path:
    report_dir = Path(results_dir) / f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{suffix}"
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir


def save_dependency_check_report(
    results_dir: Path | str,
    text: str,
    payload: Dict[str, Any],
    *,
    summary_renderer: Optional[Callable[[Dict[str, Any], Optional[Path]], str]] = None,
) -> Path:
    report_dir = new_report_dir(results_dir, "Dependency_Check")
    saved_payload = dict(payload)
    saved_payload["ended"] = now_local_iso()
    saved_payload["result"] = "Saved"
    JsonStore.write(report_dir / "dependency_check.json", saved_payload)
    (report_dir / "dependency_check.txt").write_text(text, encoding="utf-8")
    renderer = summary_renderer or dependency_check_summary_text
    (report_dir / "dependency_check_summary.txt").write_text(
        renderer(saved_payload, report_dir),
        encoding="utf-8",
    )
    return report_dir
