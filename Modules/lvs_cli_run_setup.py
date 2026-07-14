from __future__ import annotations

"""CLI adapter for run setup/review prompts."""

from pathlib import Path
from typing import Any, List, Optional

from .lvs_profile_models import ValidationProfile
from .lvs_run_metadata import RunMetadata
from .lvs_cli_heatsoak_bridge import HeatsoakBridgeMixin
from .lvs_cli_run_setup_bridges import RunSetupBridgeMixin
from .lvs_cli_run_setup_builder import RunSetupBuilderMixin
from .lvs_cli_run_setup_hardware_prompts import RunSetupHardwarePromptMixin
from .lvs_cli_run_setup_history import RunSetupHistoryMixin
from .lvs_cli_run_setup_prompts import RunSetupPromptMixin
from .lvs_cli_run_setup_review import RunSetupReviewLoopMixin


class RunSetupCliAdapter(
    HeatsoakBridgeMixin,
    RunSetupBridgeMixin,
    RunSetupBuilderMixin,
    RunSetupHistoryMixin,
    RunSetupHardwarePromptMixin,
    RunSetupPromptMixin,
    RunSetupReviewLoopMixin,
):
    def __init__(self, launcher: Any) -> None:
        self.launcher = launcher

    def __getattr__(self, name: str) -> Any:
        return getattr(self.launcher, name)

    def _run_setup_review(
        self,
        profile_path: Path,
        profile: ValidationProfile,
        labels: List[str],
    ) -> Optional[RunMetadata]:
        setup = self._create_run_setup_state(profile_path, profile, labels)
        review_controller = self._build_run_setup_review_controller(setup)
        return self._run_setup_review_loop(review_controller, setup, profile, labels)
