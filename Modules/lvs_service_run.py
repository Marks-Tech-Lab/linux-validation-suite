from __future__ import annotations

"""Run setup, launch, heatsoak, and post-run facade methods for shared services."""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .lvs_profile_models import StageConfig
from .lvs_run_launch import RunLaunchRequest
from .lvs_run_metadata import RunMetadata
from .lvs_run_setup_controller import RunSetupActionController, RunSetupPromptCallbacks, RunSetupReviewController
from .lvs_service_models import (
    CycleSetupResult,
    FrontendActionSpec,
    RunResult,
    RunSetupHistoryEntry,
    RunSetupState,
    SetupInputSpec,
    SetupPickerSpec,
)


class SuiteRunServiceMixin:
    """Prompt-free run setup/execution methods shared by TUI, GUI, and QA callers."""

    def default_run_metadata(self, profile_path: Path, description: str = "") -> RunMetadata:
        return self.run_setup_manager.default_run_metadata(profile_path, description=description)

    def create_run_setup(self, profile_path: Path) -> RunSetupState:
        return self.run_setup_manager.create_run_setup(profile_path)

    def run_setup_history_entries(self) -> List[RunSetupHistoryEntry]:
        return self.run_setup_manager.run_setup_history_entries()

    def apply_run_setup_history_entry(self, setup: RunSetupState, entry: RunSetupHistoryEntry) -> None:
        self.run_setup_manager.apply_run_setup_history_entry(setup, entry)

    def save_run_setup_history(self, setup: RunSetupState) -> None:
        self.run_setup_manager.save_run_setup_history(
            setup.profile_path,
            setup.profile,
            setup.metadata,
            heatsoak_minutes=setup.heatsoak_minutes,
        )

    def option_values(self, key: str) -> List[str]:
        return self.run_setup_manager.option_values(key)

    def setup_input_spec(
        self,
        field: str,
        *,
        label: str = "",
        blank_default: str = "",
        initial_value: str = "",
    ) -> SetupInputSpec:
        return self.run_setup_manager.input_spec(
            field,
            label=label,
            blank_default=blank_default,
            initial_value=initial_value,
        )

    def setup_option_picker_spec(self, setup: RunSetupState, key: str) -> SetupPickerSpec:
        return self.run_setup_manager.option_picker_spec(setup, key)

    def setup_power_limit_vendor_picker_spec(self) -> SetupPickerSpec:
        return self.run_setup_manager.power_limit_vendor_picker_spec()

    def setup_amd_power_limit_type_picker_spec(self) -> SetupPickerSpec:
        return self.run_setup_manager.amd_power_limit_type_picker_spec()

    def setup_stage_override_picker_spec(self, setup: RunSetupState) -> SetupPickerSpec:
        return self.run_setup_manager.stage_override_picker_spec(setup)

    def setup_segment_label_picker_spec(self, setup: RunSetupState) -> SetupPickerSpec:
        return self.run_setup_manager.segment_label_picker_spec(setup)

    def setup_stage_duration_picker_spec(self, setup: RunSetupState) -> SetupPickerSpec:
        return self.run_setup_manager.stage_duration_picker_spec(setup)

    def setup_stage_toggle_picker_spec(self, setup: RunSetupState) -> SetupPickerSpec:
        return self.run_setup_manager.stage_toggle_picker_spec(setup)

    def setup_input_field_for_key(self, key: str) -> str:
        return self.run_setup_manager.input_field_for_key(key)

    def setup_picker_key_for_key(self, key: str) -> str:
        return self.run_setup_manager.picker_key_for_key(key)

    def setup_action_for_key(self, key: str) -> FrontendActionSpec:
        return self.run_setup_manager.setup_action_for_key(key)

    def setup_action_specs(self, setup: Optional[RunSetupState] = None) -> List[FrontendActionSpec]:
        return self.run_setup_manager.setup_action_specs(setup)

    def setup_action_detail_text(self, setup: RunSetupState, action: FrontendActionSpec) -> str:
        return self.run_setup_manager.setup_action_detail_text(setup, action)

    def cycle_setup_option(self, setup: RunSetupState, key: str) -> str:
        return self.run_setup_manager.cycle_setup_option(setup, key)

    def cycle_setup_option_result(self, setup: RunSetupState, key: str) -> CycleSetupResult:
        return self.run_setup_manager.cycle_setup_option_result(setup, key)

    def select_setup_option_result(self, setup: RunSetupState, key: str, selected: str) -> CycleSetupResult:
        return self.run_setup_manager.select_setup_option_result(setup, key, selected)

    def set_setup_field(self, setup: RunSetupState, key: str, value: str) -> None:
        self.run_setup_manager.set_setup_field(setup, key, value)

    def toggle_advanced_debug_logging(self, setup: RunSetupState) -> bool:
        return self.run_setup_manager.toggle_advanced_debug_logging(setup)

    def finalize_run_metadata(self, setup: RunSetupState, profile_path: Path) -> RunMetadata:
        return self.run_setup_manager.finalize_run_metadata(setup)

    def run_setup_summary_text(self, setup: RunSetupState) -> str:
        return self.run_setup_manager.run_setup_summary_text(setup)

    def run_setup_overview_text(self, setup: RunSetupState) -> str:
        return self.run_setup_manager.run_setup_overview_text(setup)

    def stage_override_options(self, setup: RunSetupState) -> List[str]:
        return self.run_setup_manager.stage_override_options(setup)

    def stage_option_values(self, setup: RunSetupState, mode: str) -> List[str]:
        return self.run_setup_manager.stage_option_values(setup, mode)

    def set_stage_duration(self, setup: RunSetupState, stage_index: int, raw_seconds: str) -> None:
        self.run_setup_manager.set_stage_duration(setup, stage_index, raw_seconds)

    def set_all_stage_trim(self, setup: RunSetupState, start_seconds: int, end_seconds: int) -> None:
        self.run_setup_manager.set_all_stage_trim(setup, start_seconds, end_seconds)

    def toggle_stage_enabled(self, setup: RunSetupState, stage_index: int) -> None:
        self.run_setup_manager.toggle_stage_enabled(setup, stage_index)

    def set_segment_label(self, setup: RunSetupState, stage_index: int, label: str) -> None:
        self.run_setup_manager.set_segment_label(setup, stage_index, label)

    def create_run_setup_action_controller(
        self,
        callbacks: RunSetupPromptCallbacks,
    ) -> RunSetupActionController:
        return RunSetupActionController(self.run_setup_manager, callbacks)

    def create_run_setup_review_controller(
        self,
        setup: RunSetupState,
        callbacks: RunSetupPromptCallbacks,
    ) -> RunSetupReviewController:
        return RunSetupReviewController(self.run_setup_manager, setup, callbacks)

    def run_profile_capture_output(
        self,
        profile_path: Path,
        metadata: Optional[RunMetadata] = None,
        heatsoak_minutes: float = 0.0,
        setup: Optional[RunSetupState] = None,
        output_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[Any], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        operator_stop_source: str = "cli",
    ) -> RunResult:
        if setup is not None:
            request = RunLaunchRequest(
                profile_path=profile_path,
                metadata=metadata,
                heatsoak_minutes=heatsoak_minutes,
                setup=setup,
            )
            return self.run_launcher.run_prepared_capture(
                request,
                output_callback=output_callback,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                operator_stop_source=operator_stop_source,
            )
        return self.run_launcher.run_capture(
            profile_path,
            metadata=metadata,
            heatsoak_minutes=heatsoak_minutes,
            setup=setup,
            output_callback=output_callback,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
            operator_stop_source=operator_stop_source,
        )

    def build_heatsoak_stage(self, duration_seconds: int) -> StageConfig:
        return self.heatsoak_manager.build_heatsoak_stage(duration_seconds)

    def run_heatsoak_if_requested(self, minutes: float, **kwargs: Any) -> bool:
        return self.heatsoak_manager.run_heatsoak_if_requested(minutes, **kwargs)

    def normalize_wall_wattage(self, raw: str) -> str:
        return self.post_run_manager.normalize_wall_wattage(raw)

    def save_wall_wattage(self, result_dir: Path, metadata: RunMetadata, raw: str) -> str:
        return self.post_run_manager.save_wall_wattage(result_dir, metadata, raw)

    def handle_wall_wattage_input(self, result_dir: Path, metadata: RunMetadata, raw: str) -> Any:
        return self.post_run_manager.handle_wall_wattage_input(result_dir, metadata, raw)

    def run_complete_outcome(self, result_dir: Path) -> Any:
        return self.post_run_manager.run_complete_outcome(
            result_dir,
            self.result_summary_text(result_dir),
        )

    def wall_wattage_prompt_outcome(self, result_dir: Path, completed_text: str = "") -> Any:
        return self.post_run_manager.wall_wattage_prompt_outcome(result_dir, completed_text)

    def wall_wattage_result_outcome(self, result_dir: Path, raw: str, normalized: str, base_text: str) -> Any:
        return self.post_run_manager.wall_wattage_result_outcome(result_dir, raw, normalized, base_text)

    def upload_prompt_outcome(self, result_dir: Path, completed_text: str = "") -> Any:
        return self.post_run_manager.upload_prompt_outcome(result_dir, completed_text)

    def upload_skipped_outcome(self, base_text: str) -> Any:
        return self.post_run_manager.upload_skipped_outcome(base_text)

    def upload_result_outcome(self, payload: Dict[str, Any]) -> Any:
        return self.post_run_manager.upload_result_outcome(payload)

    def apply_run_metadata_update(self, result_dir: Path, metadata: RunMetadata) -> None:
        self.post_run_manager.apply_run_metadata_update(result_dir, metadata)

    def google_drive_readiness(self) -> Dict[str, Any]:
        return self.post_run_manager.google_drive_readiness()

    def upload_result_folder(self, result_dir: Path) -> Dict[str, Any]:
        return self.post_run_manager.upload_result_folder(result_dir)

    def attempt_upload_result_folder(self, result_dir: Path, readiness: Optional[Dict[str, Any]] = None) -> Any:
        return self.post_run_manager.attempt_upload_result_folder(result_dir, readiness)

    def upload_result_summary_text(self, payload: Dict[str, Any]) -> str:
        return self.post_run_manager.upload_result_summary_text(payload)
