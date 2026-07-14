#!/usr/bin/env python3
"""Read-only result overview and stage-detail report text helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict

from .lvs_result_report_adapters import result_summary_text
from .lvs_result_report_text import (
    missing_result_overview_text,
    missing_result_stage_details_text,
    result_overview_text_from_payload,
    result_stage_details_text_from_payload,
)


class ResultOverviewReportBuilder:
    """Build result browsing text without inventory/validation side effects."""

    def __init__(self, summary_exporter: Any, read_json: Callable[[Path], Dict[str, Any]]) -> None:
        self.summary_exporter = summary_exporter
        self.read_json = read_json

    def result_summary_text(self, result_dir: Path) -> str:
        return result_summary_text(result_dir, self.summary_exporter)

    def result_overview_text(self, result_dir: Path) -> str:
        parsed_path = result_dir / "parsed_results_custom.json"
        parsed = self.read_json(parsed_path) if parsed_path.exists() else {}
        if not parsed:
            return missing_result_overview_text(result_dir.name)
        return result_overview_text_from_payload(result_dir.name, parsed)

    def result_stage_details_text(self, result_dir: Path) -> str:
        parsed_path = result_dir / "parsed_results_custom.json"
        parsed = self.read_json(parsed_path) if parsed_path.exists() else {}
        if not parsed:
            return missing_result_stage_details_text(result_dir.name)
        return result_stage_details_text_from_payload(result_dir.name, parsed)
