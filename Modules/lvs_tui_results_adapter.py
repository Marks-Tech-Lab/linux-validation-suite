from __future__ import annotations

"""Textual TUI result-view adapter methods."""

from Modules.lvs_tui_result_presentation import (
    qa_result_review_presentation,
    result_artifact_browser_presentation,
    result_selection_required_presentation,
    result_stage_details_presentation,
    result_summary_presentation,
    result_workflow_followup_presentation,
)


class TuiResultsAdapterMixin:
    def _show_result_summary(self, result) -> None:
        try:
            self._set_detail(
                result_summary_presentation(
                    self.service.result_overview_text(result.path),
                    self.service.result_summary_text(result.path),
                    self.service.result_action_help_text(),
                )
            )
        except Exception as exc:
            self._set_detail(f"Unable to load result:\n{result.path}\n\n{exc}")

    def _show_results_inventory(self) -> None:
        try:
            self._set_detail(self.service.results_inventory_text(save=True))
        except Exception as exc:
            self._set_detail(f"Results inventory failed:\n{exc}")

    def _show_result_stage_details(self) -> None:
        if self.selected_result is None:
            self._set_detail(result_selection_required_presentation())
            return
        try:
            self._set_detail(
                result_stage_details_presentation(
                    self.service.result_stage_details_text(self.selected_result.path),
                    self.service.result_action_help_text(),
                )
            )
        except Exception as exc:
            self._set_detail(f"Result stage details failed:\n{exc}")

    def _show_result_qa_review(self) -> None:
        if self.selected_result is None:
            self._set_detail(result_selection_required_presentation())
            return
        try:
            self._set_detail(
                qa_result_review_presentation(
                    self.service.qa_result_review_payload(self.selected_result.path, refresh_summary=False),
                    self.service.result_action_help_text(),
                )
            )
        except Exception as exc:
            self._set_detail(f"QA result review failed:\n{exc}")

    def _show_result_artifact_details(self) -> None:
        if self.selected_result is None:
            self._set_detail(result_selection_required_presentation())
            return
        try:
            self._set_detail(
                result_artifact_browser_presentation(
                    self.selected_result.path,
                    self.service.result_artifact_inventory_item(self.selected_result.path),
                    self.service.result_artifact_detail_text(self.selected_result.path),
                    self.service.result_action_help_text(),
                )
            )
        except Exception as exc:
            self._set_detail(f"Result artifact details failed:\n{exc}")

    def _begin_result_comparison(self) -> None:
        if self.selected_result is None:
            self._set_detail(result_selection_required_presentation())
            return
        self.comparison_target_result = self.selected_result
        self._set_detail(
            "Result Comparison\n"
            "=================\n\n"
            f"Comparison result: {self.selected_result.name}\n\n"
            "Select the baseline result folder from the list.\n\n"
            "Next: highlight a baseline and press Enter to compare."
        )

    def _show_result_comparison_candidate(self, baseline_result) -> None:
        target = getattr(self, "comparison_target_result", None)
        if target is None:
            return
        self._set_detail(
            "Result Comparison\n"
            "=================\n\n"
            f"Comparison result: {target.name}\n"
            f"Baseline candidate: {baseline_result.name}\n\n"
            "Press Enter to compare these result folders.\n\n"
            "Next: read the comparison, then return to QA review for the result."
        )

    def _complete_result_comparison(self, baseline_result) -> None:
        target = getattr(self, "comparison_target_result", None)
        if target is None:
            self._set_detail("Select a comparison result first.")
            return
        try:
            payload = self.service.compare_result_payload(baseline_result.path, target.path)
            self.comparison_target_result = None
            self.selected_result = target
            self._set_detail(
                result_workflow_followup_presentation(
                    self.service.result_comparison_text(payload),
                    self.service.result_action_help_text(),
                    context="comparison",
                )
            )
        except Exception as exc:
            self.comparison_target_result = None
            self._set_detail(f"Result comparison failed:\n{exc}")

    def _validate_selected_result(self) -> None:
        if self.selected_result is None:
            self._set_detail(result_selection_required_presentation())
            return
        try:
            self._set_detail(
                result_workflow_followup_presentation(
                    self.service.validate_result_text(self.selected_result.path, save=True),
                    self.service.result_action_help_text(),
                    context="validation",
                )
            )
        except Exception as exc:
            self._set_detail(f"Result validation failed:\n{exc}")

    def _validate_all_results(self) -> None:
        try:
            self._set_detail(
                result_workflow_followup_presentation(
                    self.service.validate_all_results_text(save=True),
                    self.service.result_action_help_text(),
                    context="validation_batch",
                )
            )
        except Exception as exc:
            self._set_detail(f"Batch result validation failed:\n{exc}")

    def _pre_import_selected_result(self) -> None:
        if self.selected_result is None:
            self._set_detail(result_selection_required_presentation())
            return
        try:
            self._set_detail(
                result_workflow_followup_presentation(
                    self.service.pre_import_sanity_text(self.selected_result.path, save=True),
                    self.service.result_action_help_text(),
                    context="pre_import",
                )
            )
        except Exception as exc:
            self._set_detail(f"Pre-import sanity check failed:\n{exc}")

    def _pre_import_all_results(self) -> None:
        try:
            self._set_detail(
                result_workflow_followup_presentation(
                    self.service.pre_import_sanity_all_text(save=True),
                    self.service.result_action_help_text(),
                    context="pre_import_batch",
                )
            )
        except Exception as exc:
            self._set_detail(f"Batch pre-import sanity check failed:\n{exc}")
