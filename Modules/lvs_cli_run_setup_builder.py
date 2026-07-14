from __future__ import annotations

from pathlib import Path
from typing import List

from .lvs_profile_models import ValidationProfile
from .lvs_run_metadata import RunMetadata
from .lvs_run_setup_controller import RunSetupPromptCallbacks, RunSetupReviewController
from .lvs_service_models import RunSetupState


class RunSetupBuilderMixin:
    """Build CLI run setup state and shared review controller wiring."""

    def _create_run_setup_state(
        self,
        profile_path: Path,
        profile: ValidationProfile,
        labels: List[str],
    ) -> RunSetupState:
        metadata = RunMetadata(
            dept=self.settings_manager.settings.suite_department,
            description=profile.profile_name,
        )
        setup = RunSetupState(
            profile_path=profile_path,
            metadata=metadata,
            profile=profile,
            labels=labels,
            heatsoak_minutes=self._pending_heatsoak_value(),
        )
        if self._feature_enabled("run_setup_history"):
            setup.metadata = self._maybe_recall_run_setup_history(setup.metadata)
            recalled_heatsoak = self._recalled_heatsoak_minutes()
            if recalled_heatsoak is not None:
                setup.heatsoak_minutes = max(0.0, float(recalled_heatsoak or 0.0))
        return setup

    def _pending_heatsoak_value(self) -> float:
        source = getattr(getattr(self, "launcher", None), "_pending_heatsoak_minutes", None)
        if source is None:
            source = getattr(self, "_pending_heatsoak_minutes", 0.0)
        return float(source or 0.0)

    def _update_pending_heatsoak_minutes(self, minutes: float) -> None:
        value = float(minutes or 0.0)
        self._pending_heatsoak_minutes = value
        launcher = getattr(self, "launcher", None)
        if launcher is not None:
            launcher._pending_heatsoak_minutes = value

    def _run_setup_prompt_callbacks(self) -> RunSetupPromptCallbacks:
        return RunSetupPromptCallbacks(
            load_history=self._maybe_recall_run_setup_history,
            stage_overrides=self._run_overrides_menu,
            edit_labels=self._maybe_edit_labels,
            select_case_sku=self._select_case_sku,
            select_psu_rating=self._select_psu_rating,
            select_cpu_cooler=self._select_cpu_cooler,
            enter_power_limit=self._enter_power_limit,
            enter_description=self._enter_description,
            enter_heatsoak_minutes=self._enter_heatsoak_minutes,
            enter_psu_wattage=self._enter_psu_wattage,
            enter_fan_type=self._enter_fan_type,
            enter_fan_details=self._enter_fan_details,
            enter_raw=lambda label: self._input(f"{label}: ").strip(),
            normalize_labels=self.profile_cli._normalize_profile_labels,
            department=lambda: self.settings_manager.settings.suite_department,
            update_pending_heatsoak=self._update_pending_heatsoak_minutes,
            recalled_heatsoak=self._recalled_heatsoak_minutes,
            notify=print,
        )

    def _build_run_setup_review_controller(self, setup: RunSetupState) -> RunSetupReviewController:
        return RunSetupReviewController(
            self.run_setup_manager,
            setup,
            self._run_setup_prompt_callbacks(),
        )
