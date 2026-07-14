from __future__ import annotations

import contextlib
import io
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .lvs_cli_screen import clear_cli_screen
from .lvs_result_artifact_view import result_artifact_choice_text


class ResultCliPromptMixin:
    """CLI menu, selection, and output-capture helpers for result workflows."""

    def results_menu(self) -> None:
        while True:
            clear_cli_screen()
            print("\nResults / Reports")
            print("Normal result workflow")
            print("1. QA Review Result Folder")
            print("2. Inspect Result Artifacts")
            print("3. Validate Result Folder")
            print("4. Pre-Import Sanity Check")
            print("5. Compare Result Folders")
            print("")
            print("Batch / inventory tools")
            print("6. Results Inventory")
            print("7. Validate All Completed Results")
            print("8. Pre-Import Sanity Check All Completed Results")
            print("9. Back")
            choice = self._input("Select: ").strip()
            if choice == "1":
                self.result_qa_review()
            elif choice == "2":
                self.result_artifact_details()
            elif choice == "3":
                self.result_validation()
            elif choice == "4":
                self.pre_import_sanity()
            elif choice == "5":
                self.result_comparison()
            elif choice == "6":
                self.results_inventory()
            elif choice == "7":
                self.result_validation_all()
            elif choice == "8":
                self.pre_import_sanity_all()
            elif choice == "9":
                return

    def print_result_choices(self, candidates: List[Path], heading: str = "Available result folders") -> None:
        print(
            result_artifact_choice_text(
                candidates,
                item_for_path=self.result_inventory_item,
                heading=heading,
            ),
            end="",
        )

    def _confirm_result_action(self, prompt: str) -> bool:
        return self._input(prompt).strip().lower() in {"y", "yes"}

    def _select_result_candidate(
        self,
        candidates: List[Path],
        prompt: str,
        invalid_message: Optional[str] = "Invalid selection.",
    ) -> Optional[Path]:
        choice = self._input(prompt).strip()
        try:
            return candidates[int(choice) - 1]
        except Exception:
            if invalid_message:
                print(invalid_message)
            return None

    def _capture_result_body(
        self,
        callback: Callable[..., Dict[str, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Tuple[str, Dict[str, Any]]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            payload = callback(*args, **kwargs)
        return output.getvalue(), payload
