from __future__ import annotations

from typing import List, Optional

from .lvs_cli_compat import BackRequested
from .lvs_cli_screen import clear_cli_screen
from .lvs_profile_models import ValidationProfile
from .lvs_run_metadata import RunMetadata
from .lvs_run_setup_controller import RunSetupReviewController
from .lvs_service_models import RunSetupState


class RunSetupReviewLoopMixin:
    """CLI rendering loop for run setup review actions."""

    def _run_setup_review_loop(
        self,
        review_controller: RunSetupReviewController,
        setup: RunSetupState,
        profile: ValidationProfile,
        labels: List[str],
    ) -> Optional[RunMetadata]:
        while True:
            clear_cli_screen()
            print("\nReview Run Settings")
            print(review_controller.overview_text())
            actions = review_controller.action_specs()
            print("\nActions")
            print("-------")
            for action in actions:
                detail = f": {action.detail}" if str(action.detail or "").strip() else ""
                print(f"{str(action.key).upper()}. {action.label or action.target or action.action}{detail}")
            print("B. Back / Cancel")
            try:
                choice = self._input("Select action: ").strip().lower()
            except BackRequested:
                return None
            if review_controller.is_cancel_choice(choice):
                return None
            action = review_controller.action_for_choice(choice)
            if action is None:
                print("Invalid selection.")
                continue
            try:
                finalized = review_controller.handle_action(action)
                if finalized is not None:
                    labels[:] = list(setup.labels)
                    return finalized
            except BackRequested:
                continue
            finally:
                review_controller.normalize_setup()
                setup.profile = profile
                labels[:] = list(setup.labels)
