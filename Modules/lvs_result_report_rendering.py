from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .lvs_cli_compat import RunSummaryTextExporter
from .lvs_result_artifact_view import result_artifact_inventory_text
from .lvs_result_report_text import (
    artifact_detail_text,
    batch_pre_import_sanity_text,
    batch_result_validation_text,
    result_comparison_text,
    result_validation_text,
    selected_pre_import_sanity_text,
)


@dataclass(frozen=True)
class RenderedResultReport:
    text: str
    payload: Dict[str, Any]


class ResultReportRenderService:
    """Build result/report payloads and text without CLI prompts."""

    def __init__(
        self,
        *,
        result_artifacts: Any,
        result_validation: Any,
        result_comparison: Any,
        pre_import_sanity: Any,
        dependency_summary_builder: Optional[Callable[[Dict[str, Any], Optional[Path]], str]] = None,
        summary_exporter: Optional[Any] = None,
    ) -> None:
        self.result_artifacts = result_artifacts
        self.result_validation = result_validation
        self.result_comparison = result_comparison
        self.pre_import_sanity = pre_import_sanity
        self.dependency_summary_builder = dependency_summary_builder
        self.summary_exporter = summary_exporter or RunSummaryTextExporter()

    def inventory(self) -> RenderedResultReport:
        payload = self.result_artifacts.inventory_payload()
        return RenderedResultReport(result_artifact_inventory_text(payload), payload)

    def artifact_detail(self, result_dir: Path) -> RenderedResultReport:
        prepared = self.result_artifacts.prepare_detail_report(result_dir)
        text = artifact_detail_text(
            prepared,
            dependency_summary_builder=self.dependency_summary_builder,
        )
        payload = self.result_artifacts.complete_detail_report(prepared)
        return RenderedResultReport(text, payload)

    def validation(self, result_dir: Path) -> RenderedResultReport:
        payload = self.validation_payload(result_dir)
        return RenderedResultReport(result_validation_text(payload), payload)

    def validation_payload(self, result_dir: Path) -> Dict[str, Any]:
        return self.result_validation.validate_result_folder(result_dir, self.summary_exporter)

    def validation_batch(self, candidates: List[Path], *, save_individual: bool = False) -> RenderedResultReport:
        payload = self.result_validation.validate_batch(
            candidates,
            validate_one=self.validation_payload,
            write_one=self.write_validation_report,
            save_individual=save_individual,
        )
        return RenderedResultReport(batch_result_validation_text(payload), payload)

    def write_validation_report(self, result_dir: Path) -> Dict[str, Any]:
        rendered = self.validation(result_dir)
        self.result_validation.write_validation_report(result_dir, rendered.text, rendered.payload)
        return rendered.payload

    def comparison(self, baseline_dir: Path, comparison_dir: Path) -> RenderedResultReport:
        payload = self.result_comparison.compare_result_folders(baseline_dir, comparison_dir)
        return RenderedResultReport(result_comparison_text(payload), payload)

    def pre_import_batch(
        self,
        candidates: Optional[List[Path]] = None,
        *,
        save_individual_validation: bool = False,
    ) -> RenderedResultReport:
        payload = self.pre_import_sanity.run_batch(
            candidates,
            save_individual_validation=save_individual_validation,
        )
        return RenderedResultReport(batch_pre_import_sanity_text(payload), payload)

    def prepare_selected_pre_import(self, result_dir: Path) -> Dict[str, Any]:
        return self.pre_import_sanity.prepare_selected(result_dir)

    def selected_pre_import_validation(self, prepared: Dict[str, Any]) -> RenderedResultReport:
        payload = prepared["validation"]
        return RenderedResultReport(result_validation_text(payload), payload)

    def selected_pre_import(
        self,
        prepared: Dict[str, Any],
        comparison_payload: Optional[Dict[str, Any]] = None,
        comparison_text: str = "",
    ) -> RenderedResultReport:
        payload = self.pre_import_sanity.complete_selected(prepared, comparison_payload)
        return RenderedResultReport(selected_pre_import_sanity_text(payload, comparison_text), payload)
