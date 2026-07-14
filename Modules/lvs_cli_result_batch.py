from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


class ResultCliBatchMixin:
    """CLI workflows for batch result validation and pre-import checks."""

    def result_validation_all(self) -> None:
        candidates = self.result_validation_candidates()
        if not candidates:
            print("No result folders with parsed_results_custom.json were found.")
            return

        text, payload = self._capture_result_body(self.result_validation_all_body, candidates, save_individual=False)
        print(text, end="")
        if self._confirm_result_action("Save batch validation report? [y/N]: "):
            report_dir = self.write_result_validation_batch_report(text, payload)
            print(f"Batch validation report: {report_dir}")
        if self._confirm_result_action("Refresh per-folder validation reports too? [y/N]: "):
            refreshed = self.write_individual_result_validation_reports(candidates)
            print(f"Refreshed validation reports: {refreshed}")

    def write_result_validation_report(self, result_dir: Path) -> Dict[str, Any]:
        return self.result_report_renderer().write_validation_report(result_dir)

    def write_individual_result_validation_reports(self, candidates: List[Path]) -> int:
        refreshed = 0
        for result_dir in candidates:
            try:
                self.write_result_validation_report(result_dir)
                refreshed += 1
            except Exception:
                continue
        return refreshed

    def result_validation_all_body(self, candidates: List[Path], save_individual: bool = False) -> Dict[str, Any]:
        rendered = self.result_report_renderer().validation_batch(candidates, save_individual=save_individual)
        print(rendered.text, end="")
        return rendered.payload

    def write_result_validation_batch_report(self, text: str, payload: Dict[str, Any]) -> Path:
        return self.launcher.result_validation.write_batch_validation_report(text, payload)

    def pre_import_sanity_all(self) -> None:
        candidates = self.result_validation_candidates()
        if not candidates:
            print("No result folders with parsed_results_custom.json were found.")
            return

        text, payload = self._capture_result_body(self.pre_import_sanity_all_body, candidates)
        print(text, end="")
        report_dir = self.write_pre_import_sanity_batch_report(text, payload)
        print(f"Batch pre-import sanity report: {report_dir}")

    def pre_import_sanity_all_body(self, candidates: List[Path]) -> Dict[str, Any]:
        rendered = self.result_report_renderer().pre_import_batch(candidates)
        print(rendered.text, end="")
        return rendered.payload

    def write_pre_import_sanity_batch_report(self, text: str, payload: Dict[str, Any]) -> Path:
        return self.launcher.pre_import_sanity.write_batch_report(text, payload)
