from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .lvs_result_artifact_view import result_artifact_inventory_text
from .lvs_result_report_rendering import ResultReportRenderService


class ResultCliInventoryMixin:
    """Result facade delegates and inventory workflow helpers."""

    def result_validation_candidates(self, include_archived: bool = False) -> List[Path]:
        return self.launcher.result_validation.result_candidates(include_archived=include_archived)

    def result_artifact_candidates(self) -> List[Path]:
        return self.launcher.result_artifacts.candidates()

    def result_report_renderer(self) -> ResultReportRenderService:
        return ResultReportRenderService(
            result_artifacts=self.launcher.result_artifacts,
            result_validation=self.launcher.result_validation,
            result_comparison=self.launcher.result_comparison,
            pre_import_sanity=self.launcher.pre_import_sanity,
            dependency_summary_builder=self.dependency_check_summary_text,
        )

    def results_inventory(self) -> None:
        text, payload = self._capture_result_body(self.results_inventory_body)
        print(text, end="")
        if self._confirm_result_action("Save results inventory log? [y/N]: "):
            report_dir = self.launcher.result_artifacts.write_inventory_report(text, payload)
            print(f"Results inventory report: {report_dir}")

    def safe_json_read(self, path: Path) -> Dict[str, Any]:
        return self.launcher.result_artifacts.safe_json_read(path)

    def results_inventory_body(self) -> Dict[str, Any]:
        rendered = self.result_report_renderer().inventory()
        print(rendered.text, end="")
        return rendered.payload

    def result_inventory_item(self, result_dir: Path) -> Dict[str, Any]:
        return self.launcher.result_artifacts.inventory_item(result_dir)

    def result_artifact_file_names(self, result_dir: Path) -> List[str]:
        return self.launcher.result_artifacts.artifact_file_names(result_dir)

    def print_results_inventory(self, payload: Dict[str, Any]) -> None:
        print(result_artifact_inventory_text(payload), end="")

    def refresh_run_summary(self, result_dir: Path) -> Dict[str, Any]:
        return self.launcher.pre_import_sanity.refresh_run_summary(result_dir)

    def dependency_check_summary_text(self, payload: Dict[str, Any], report_dir: Optional[Path] = None) -> str:
        return self._diagnostics_cli_adapter().dependency_check_summary_text(payload, report_dir)
