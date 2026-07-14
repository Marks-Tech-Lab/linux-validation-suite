from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .lvs_service_results import SuiteResultServiceMixin
from .lvs_tui_result_presentation import qa_result_review_presentation


class _CliQaReviewService(SuiteResultServiceMixin):
    """Expose the shared QA payload builder without colliding with CLI menu names."""

    def __init__(self, launcher: Any) -> None:
        self.result_validation = launcher.result_validation
        self.summary_exporter = launcher.summary_exporter
        self.result_comparison = launcher.result_comparison
        self.pre_import_sanity = launcher.pre_import_sanity
        self.result_artifacts = launcher.result_artifacts


class ResultCliSelectedMixin:
    """CLI workflows for selected result folders."""

    def result_artifact_details(self) -> None:
        candidates = self.result_artifact_candidates()
        if not candidates:
            print("No active result artifacts were found.")
            return
        self.print_result_choices(candidates, heading="Available result artifacts")
        result_dir = self._select_result_candidate(candidates, "Choose artifact folder: ")
        if result_dir is None:
            return

        text, payload = self._capture_result_body(self.result_artifact_details_body, result_dir)
        print(text, end="")
        if self._confirm_result_action("Save artifact detail report in this folder? [y/N]: "):
            report_dir = self.launcher.result_artifacts.write_detail_report(result_dir, text, payload)
            print(f"Artifact detail report: {report_dir}")

    def result_artifact_details_body(self, result_dir: Path) -> Dict[str, Any]:
        rendered = self.result_report_renderer().artifact_detail(result_dir)
        print(rendered.text, end="")
        return rendered.payload

    def result_qa_review(self) -> None:
        candidates = self.result_validation_candidates()
        if not candidates:
            print("No result folders with parsed_results_custom.json were found.")
            return
        self.print_result_choices(candidates)
        result_dir = self._select_result_candidate(candidates, "Choose result folder for QA review: ")
        if result_dir is None:
            return

        payload = self.result_qa_review_payload(result_dir)
        print(self.result_qa_review_text(payload), end="")

    def result_qa_review_payload(self, result_dir: Path) -> Dict[str, Any]:
        return _CliQaReviewService(self.launcher).qa_result_review_payload(
            result_dir,
            refresh_summary=False,
        )

    def result_qa_review_text(self, payload: Dict[str, Any]) -> str:
        return qa_result_review_presentation(
            payload,
            "CLI Results actions: run Validation, Pre-Import Sanity, Comparison, or Artifact Detail from this menu.",
            operator_action_hint=(
                "- From the Results / Reports menu, use Validate Result Folder, "
                "Pre-Import Sanity Check, Compare Result Folders, or Inspect Result Artifacts as needed."
            ),
        )

    def result_validation(self) -> None:
        candidates = self.result_validation_candidates()
        if not candidates:
            print("No result folders with parsed_results_custom.json were found.")
            return
        self.print_result_choices(candidates)
        result_dir = self._select_result_candidate(candidates, "Choose result folder: ")
        if result_dir is None:
            return

        text, payload = self._capture_result_body(self.result_validation_body, result_dir)
        print(text, end="")
        if self._confirm_result_action("Save validation report in this result folder? [y/N]: "):
            report_dir = self.launcher.result_validation.write_validation_report(result_dir, text, payload)
            print(f"Result validation report: {report_dir}")

    def result_validation_body(self, result_dir: Path) -> Dict[str, Any]:
        rendered = self.result_report_renderer().validation(result_dir)
        print(rendered.text, end="")
        return rendered.payload

    def result_comparison(self) -> None:
        include_archived = self._input("Include Archived completed results as comparison candidates? [y/N]: ").strip().lower() in {"y", "yes"}
        candidates = self.result_validation_candidates(include_archived=include_archived)
        if len(candidates) < 2:
            scope = "active or archived" if include_archived else "active"
            print(f"At least two {scope} result folders with parsed_results_custom.json are required.")
            return
        self.print_result_choices(candidates)
        baseline_choice = self._input("Choose baseline result folder: ").strip()
        comparison_choice = self._input("Choose comparison result folder: ").strip()
        try:
            baseline = candidates[int(baseline_choice) - 1]
            comparison = candidates[int(comparison_choice) - 1]
        except Exception:
            print("Invalid selection.")
            return
        if baseline == comparison:
            print("Choose two different result folders.")
            return

        text, payload = self._capture_result_body(self.result_comparison_body, baseline, comparison)
        print(text, end="")
        if self._confirm_result_action("Save comparison report in comparison result folder? [y/N]: "):
            report_dir = self.launcher.result_comparison.write_comparison_report(baseline, comparison, text, payload)
            print(f"Result comparison report: {report_dir}")

    def result_comparison_body(self, baseline_dir: Path, comparison_dir: Path) -> Dict[str, Any]:
        rendered = self.result_report_renderer().comparison(baseline_dir, comparison_dir)
        print(rendered.text, end="")
        return rendered.payload

    def pre_import_sanity(self) -> None:
        candidates = self.result_validation_candidates()
        if not candidates:
            print("No result folders with parsed_results_custom.json were found.")
            return
        self.print_result_choices(candidates)
        result_dir = self._select_result_candidate(candidates, "Choose result folder to check: ")
        if result_dir is None:
            return

        renderer = self.result_report_renderer()
        prepared = renderer.prepare_selected_pre_import(result_dir)
        validation_rendered = renderer.selected_pre_import_validation(prepared)
        validation_payload = validation_rendered.payload
        validation_text = validation_rendered.text

        comparison_payload = None
        comparison_text = ""
        if self._confirm_result_action("Compare against a baseline result? [y/N]: "):
            baselines = [path for path in candidates if path != result_dir]
            if not baselines:
                comparison_text = "No other active result folders are available for comparison.\n"
                print(comparison_text, end="")
            else:
                self.print_result_choices(baselines, heading="Available baselines")
                baseline = self._select_result_candidate(
                    baselines,
                    "Choose baseline result folder: ",
                    invalid_message=None,
                )
                if baseline is None:
                    comparison_text = "Invalid baseline selection; comparison skipped.\n"
                    print(comparison_text, end="")
                else:
                    comparison_text, comparison_payload = self._capture_result_body(
                        self.result_comparison_body,
                        baseline,
                        result_dir,
                    )

        rendered = renderer.selected_pre_import(prepared, comparison_payload, comparison_text)
        payload = rendered.payload
        text = rendered.text
        print(text, end="")
        report_dir = self.launcher.pre_import_sanity.write_selected_report(
            result_dir,
            validation_text=validation_text,
            validation_payload=validation_payload,
            pre_import_text=text,
            pre_import_payload=payload,
        )
        print(f"Pre-import sanity report: {report_dir}")
