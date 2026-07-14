#!/usr/bin/env python3
"""Frontend-neutral run setup action dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple

from .lvs_run_metadata import RunMetadata
from .lvs_run_setup import RunSetupManager
from .lvs_service_models import FrontendActionSpec, RunSetupState


@dataclass
class RunSetupPromptCallbacks:
    """Frontend adapter callbacks used by the shared run setup controller."""

    load_history: Callable[[RunMetadata], RunMetadata]
    stage_overrides: Callable[[Any], None]
    edit_labels: Callable[[list[str]], list[str]]
    select_case_sku: Callable[[str], str]
    select_psu_rating: Callable[[str], str]
    select_cpu_cooler: Callable[[str], str]
    enter_power_limit: Callable[[str], str]
    enter_description: Callable[[str], str]
    enter_heatsoak_minutes: Callable[[float], float]
    enter_psu_wattage: Callable[[str], str]
    enter_fan_type: Callable[[str, str], Tuple[str, str]]
    enter_fan_details: Callable[[str], str]
    enter_raw: Callable[[str], str]
    normalize_labels: Callable[[Any, list[str]], list[str]]
    department: Callable[[], str]
    update_pending_heatsoak: Callable[[float], None]
    recalled_heatsoak: Callable[[], float | None] = lambda: None
    notify: Callable[[str], None] = lambda _message: None


class RunSetupActionController:
    """Apply run setup actions while keeping frontend prompts pluggable."""

    def __init__(self, manager: RunSetupManager, callbacks: RunSetupPromptCallbacks) -> None:
        self.manager = manager
        self.callbacks = callbacks

    def handle_action(self, setup: RunSetupState, action: FrontendActionSpec) -> Optional[RunMetadata]:
        if action.action == "run_selected":
            self.callbacks.update_pending_heatsoak(float(setup.heatsoak_minutes or 0.0))
            self._normalize_setup(setup)
            return self.manager.finalize_run_metadata(setup)
        if action.action == "load_history":
            setup.metadata = self.callbacks.load_history(setup.metadata)
            recalled_heatsoak = self.callbacks.recalled_heatsoak()
            if recalled_heatsoak is not None:
                setup.heatsoak_minutes = max(0.0, float(recalled_heatsoak or 0.0))
                self.callbacks.update_pending_heatsoak(setup.heatsoak_minutes)
        elif action.action == "toggle_debug_logging":
            enabled = self.manager.toggle_advanced_debug_logging(setup)
            self.callbacks.notify(f"Advanced debug logging {'enabled' if enabled else 'disabled'} for this run.")
        elif action.action == "stage_override_picker":
            self.callbacks.stage_overrides(setup.profile)
        elif action.action == "segment_label_picker":
            setup.labels = self.callbacks.edit_labels(setup.labels)
        elif action.action == "picker":
            self._handle_picker(setup, action)
        elif action.action == "power_limit_picker":
            setup.metadata.power_limit_data = self.callbacks.enter_power_limit(setup.metadata.power_limit_data)
        elif action.action == "input":
            self._handle_input(setup, action)
        else:
            self.callbacks.notify("Unsupported action.")
        self.normalize_setup(setup)
        return None

    def normalize_setup(self, setup: RunSetupState) -> None:
        self._normalize_setup(setup)

    def _handle_picker(self, setup: RunSetupState, action: FrontendActionSpec) -> None:
        if action.target == "case_sku":
            setup.metadata.case_sku = self.callbacks.select_case_sku(setup.metadata.case_sku)
        elif action.target == "psu_rating":
            setup.metadata.psu_rating = self.callbacks.select_psu_rating(setup.metadata.psu_rating)
        elif action.target == "cpu_cooler":
            setup.metadata.cpu_cooler = self.callbacks.select_cpu_cooler(setup.metadata.cpu_cooler)
        else:
            self.callbacks.notify("Unsupported picker action.")

    def _handle_input(self, setup: RunSetupState, action: FrontendActionSpec) -> None:
        if action.target == "description":
            setup.metadata.description = self.callbacks.enter_description(
                setup.metadata.description or setup.profile.profile_name
            )
        elif action.target == "heatsoak_minutes":
            setup.heatsoak_minutes = self.callbacks.enter_heatsoak_minutes(setup.heatsoak_minutes)
            self.callbacks.update_pending_heatsoak(float(setup.heatsoak_minutes or 0.0))
        elif action.target == "psu_wattage":
            setup.metadata.psu_wattage = self.callbacks.enter_psu_wattage(setup.metadata.psu_wattage)
            if not setup.metadata.psu_wattage:
                setup.metadata.psu_rating = ""
        elif action.target == "fan_type":
            setup.metadata.fan_type, setup.metadata.fan_details = self.callbacks.enter_fan_type(
                setup.metadata.fan_type,
                setup.metadata.fan_details,
            )
        elif action.target == "fan_details":
            setup.metadata.fan_details = self.callbacks.enter_fan_details(setup.metadata.fan_details)
        else:
            raw = self.callbacks.enter_raw(str(action.label or action.target))
            self.manager.set_setup_field(setup, action.target, raw)

    def _normalize_setup(self, setup: RunSetupState) -> None:
        setup.metadata.dept = str(self.callbacks.department() or "Production")
        setup.labels = self.callbacks.normalize_labels(setup.profile, setup.labels)


class RunSetupReviewController:
    """Frontend-neutral review-loop state for run setup actions."""

    CANCEL_CHOICES = {"b", "q"}

    def __init__(
        self,
        manager: RunSetupManager,
        setup: RunSetupState,
        callbacks: RunSetupPromptCallbacks,
    ) -> None:
        self.manager = manager
        self.setup = setup
        self.action_controller = RunSetupActionController(manager, callbacks)

    def overview_text(self) -> str:
        return self.manager.run_setup_overview_text(self.setup)

    def action_specs(self) -> list[FrontendActionSpec]:
        return self.manager.setup_action_specs(self.setup)

    def is_cancel_choice(self, raw_choice: str) -> bool:
        return str(raw_choice or "").strip().lower() in self.CANCEL_CHOICES

    def action_for_choice(self, raw_choice: str) -> Optional[FrontendActionSpec]:
        choice = str(raw_choice or "").strip().lower()
        return next((item for item in self.action_specs() if str(item.key).lower() == choice), None)

    def handle_action(self, action: FrontendActionSpec) -> Optional[RunMetadata]:
        return self.action_controller.handle_action(self.setup, action)

    def normalize_setup(self) -> None:
        self.action_controller.normalize_setup(self.setup)
