#!/usr/bin/env python3
"""Result-folder inventory, validation, and pre-import report helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .lvs_core import APP_NAME, JsonStore
from .lvs_result_report_adapters import (
    RESULT_ACTIONS as RESULT_ACTION_SPECS,
    completed_result_dirs,
    count_entries_by,
    list_result_entries,
    read_result_json,
    refresh_run_summary,
    result_action_for_key,
    result_action_help_text,
)
from .lvs_result_overview_reports import ResultOverviewReportBuilder
from .lvs_result_report_workflows import (
    build_pre_import_sanity_batch_payload,
    build_pre_import_sanity_payload,
    build_result_validation_batch_payload,
    build_result_validation_payload,
    build_results_inventory_payload,
    manager_pre_import_sanity_batch_text,
    manager_pre_import_text,
    manager_result_validation_batch_text,
    manager_validation_text,
    results_inventory_text_from_payload,
)
from .lvs_service_models import FrontendActionSpec, ResultListEntry
from .lvs_summary_text import SummaryTextBuilder

from .lvs_result_report_text import (
    artifact_detail_text,
    batch_pre_import_sanity_text,
    batch_result_validation_text,
    format_result_metric_number,
    format_result_metric_pair,
    format_result_metric_triplet,
    missing_result_overview_text,
    missing_result_stage_details_text,
    pre_import_batch_line,
    result_action_item_line,
    result_comparison_text,
    result_gpu_highlight_line,
    result_overview_stage_line,
    result_validation_batch_line,
    result_validation_issue_line,
    result_validation_text,
    selected_pre_import_sanity_text,
)


class ResultReportManager:
    """Small result-report facade shared by UI frontends."""

    RESULT_ACTIONS = RESULT_ACTION_SPECS

    def __init__(self, results_dir: Path | str, summary_exporter: SummaryTextBuilder | None = None) -> None:
        self.results_dir = Path(results_dir)
        self.summary_exporter = summary_exporter or SummaryTextBuilder(APP_NAME)
        self.overview_reports = ResultOverviewReportBuilder(self.summary_exporter, self._read_json)

    def list_results(self) -> List[ResultListEntry]:
        return list_result_entries(self.results_dir)

    def result_action_for_key(self, key: str) -> FrontendActionSpec:
        return result_action_for_key(key)

    def result_action_help_text(self) -> str:
        return result_action_help_text()

    def result_summary_text(self, result_dir: Path) -> str:
        return self.overview_reports.result_summary_text(result_dir)

    def result_overview_text(self, result_dir: Path) -> str:
        return self.overview_reports.result_overview_text(result_dir)

    def result_stage_details_text(self, result_dir: Path) -> str:
        return self.overview_reports.result_stage_details_text(result_dir)

    def results_inventory_text(self, save: bool = True) -> str:
        entries = self.list_results()
        payload = build_results_inventory_payload(self.results_dir, entries, self._count_by)
        text = results_inventory_text_from_payload(payload, entries)
        if save:
            report_dir = self.new_report_dir("Results_Inventory")
            JsonStore.write(report_dir / "results_inventory.json", payload)
            (report_dir / "results_inventory.txt").write_text(text, encoding="utf-8")
            text += f"\nSaved: {report_dir}\n"
        return text

    def validate_result_text(self, result_dir: Path, save: bool = True) -> str:
        payload = self.validate_result_payload(result_dir)
        text = self.validation_text(payload)
        if save:
            JsonStore.write(result_dir / "result_validation.json", payload)
            (result_dir / "result_validation.txt").write_text(text, encoding="utf-8")
            text += f"\nSaved: {result_dir / 'result_validation.txt'}\n"
        return text

    def validate_all_results_text(self, save: bool = True) -> str:
        candidates = self.completed_result_dirs()
        items = [self.validate_result_payload(path) for path in candidates]
        payload = build_result_validation_batch_payload(self.results_dir, items)
        text = manager_result_validation_batch_text(payload)
        if save:
            report_dir = self.new_report_dir("Result_Validation_Batch")
            JsonStore.write(report_dir / "result_validation_batch.json", payload)
            (report_dir / "result_validation_batch.txt").write_text(text, encoding="utf-8")
            text += f"\nSaved: {report_dir}\n"
        return text

    def pre_import_sanity_text(self, result_dir: Path, save: bool = True) -> str:
        validation_payload = self.validate_result_payload(result_dir)
        refresh_status = self.refresh_run_summary(result_dir)
        payload = build_pre_import_sanity_payload(result_dir, validation_payload, refresh_status)
        text = self.pre_import_text(payload)
        if save:
            JsonStore.write(result_dir / "pre_import_sanity.json", payload)
            (result_dir / "pre_import_sanity.txt").write_text(text, encoding="utf-8")
            text += f"\nSaved: {result_dir / 'pre_import_sanity.txt'}\n"
        return text

    def pre_import_sanity_all_text(self, save: bool = True) -> str:
        candidates = self.completed_result_dirs()
        items = []
        for path in candidates:
            validation = self.validate_result_payload(path)
            refresh = self.refresh_run_summary(path)
            summary = validation.get("summary") if isinstance(validation.get("summary"), dict) else {}
            items.append(
                {
                    "folder": str(path),
                    "folder_name": path.name,
                    "result": validation.get("result"),
                    "summary": summary,
                    "summary_refresh": refresh,
                }
            )
        payload = build_pre_import_sanity_batch_payload(self.results_dir, items)
        text = manager_pre_import_sanity_batch_text(payload)
        if save:
            report_dir = self.new_report_dir("Pre_Import_Sanity_Batch")
            JsonStore.write(report_dir / "pre_import_sanity_batch.json", payload)
            (report_dir / "pre_import_sanity_batch.txt").write_text(text, encoding="utf-8")
            text += f"\nSaved: {report_dir}\n"
        return text

    def refresh_run_summary(self, result_dir: Path) -> Dict[str, Any]:
        return refresh_run_summary(result_dir, self.summary_exporter)

    def completed_result_dirs(self) -> List[Path]:
        return completed_result_dirs(self.list_results())

    def validate_result_payload(self, result_dir: Path) -> Dict[str, Any]:
        parsed_path = result_dir / "parsed_results_custom.json"
        parsed = self._read_json(parsed_path) if parsed_path.exists() else {}
        return build_result_validation_payload(
            result_dir,
            parsed,
            parsed_path.exists(),
            lambda name: (result_dir / name).exists(),
        )

    def validation_text(self, payload: Dict[str, Any]) -> str:
        return manager_validation_text(payload)

    def pre_import_text(self, payload: Dict[str, Any]) -> str:
        validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
        return manager_pre_import_text(payload, self.validation_text(validation))

    def new_report_dir(self, suffix: str) -> Path:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        report_dir = self.results_dir / f"{timestamp}_{suffix}"
        report_dir.mkdir(parents=True, exist_ok=True)
        return report_dir

    def _count_by(self, entries: List[ResultListEntry], field: str) -> Dict[str, int]:
        return count_entries_by(entries, field)

    def _read_json(self, path: Path) -> Dict[str, Any]:
        return read_result_json(path)
