from __future__ import annotations

"""Profile editing/creation facade methods for shared frontend services."""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .lvs_core import now_local_iso
from .lvs_profile_creation import (
    ProfileBuildResult,
    ProfileCreationRequest,
    ProfileStageDraft,
    ProfileStageInsertResult,
)
from .lvs_profile_models import StageConfig, StageModules, ValidationProfile
from .lvs_profile_save import ProfileSavePreparation
from .lvs_service_models import (
    FrontendActionSpec,
    ProfileCopySelectionState,
    ProfileEditItem,
    ProfileEditState,
    SetupInputSpec,
    SetupPickerSpec,
)


class SuiteProfileServiceMixin:
    """Prompt-free profile edit/create methods shared by TUI, GUI, and QA callers."""

    def create_profile_edit(self, profile_path: Path) -> ProfileEditState:
        profile = self.profile_loader.load_profile(profile_path)
        labels = self.profile_loader.load_segment_labels(profile_path, profile)
        labels = self.profile_editor.normalize_labels(profile, labels)
        return ProfileEditState(profile_path=profile_path, profile=profile, labels=labels)

    def create_new_profile_edit(self, profile_name: str = "New Profile") -> ProfileEditState:
        name = re.sub(r"\s+", " ", str(profile_name or "").strip()) or "New Profile"
        profile_path = self._unique_profile_path(name)
        result = self.profile_creation.build_profile(ProfileCreationRequest(
            profile_name=name,
            menu_group="custom",
            telemetry_interval_seconds=self.settings.sample_interval_seconds,
            trim_start_seconds=self.settings.trim_start_seconds,
            trim_end_seconds=self.settings.trim_end_seconds,
            stages=[],
        ))
        return ProfileEditState(
            profile_path=profile_path,
            profile=result.profile,
            labels=result.labels,
            dirty=True,
            is_new=True,
        )

    def create_profile_copy_edit(
        self,
        source_path: Path,
        profile_name: str,
        selected_stage_indices: List[int],
    ) -> ProfileEditState:
        source = self.profile_loader.load_profile(source_path)
        return self._copied_profile_edit(source, profile_name, selected_stage_indices)

    def create_profile_save_as_edit(
        self,
        edit: ProfileEditState,
        profile_name: str,
        selected_stage_indices: List[int],
    ) -> ProfileEditState:
        return self._copied_profile_edit(edit.profile, profile_name, selected_stage_indices)

    def create_profile_copy_selection(
        self,
        edit: ProfileEditState,
        *,
        mode: str,
    ) -> ProfileCopySelectionState:
        return ProfileCopySelectionState(edit, str(mode), list(range(len(edit.profile.stages))))

    def toggle_profile_copy_stage(self, selection: ProfileCopySelectionState, index: int) -> None:
        if index < 0 or index >= len(selection.source_edit.profile.stages):
            raise IndexError("stage index out of range")
        values = set(selection.selected_stage_indices)
        values.symmetric_difference_update({index})
        selection.selected_stage_indices = sorted(values)

    def set_all_profile_copy_stages(self, selection: ProfileCopySelectionState, selected: bool) -> None:
        selection.selected_stage_indices = (
            list(range(len(selection.source_edit.profile.stages))) if selected else []
        )

    def finish_profile_copy_selection(
        self,
        selection: ProfileCopySelectionState,
        profile_name: str,
    ) -> ProfileEditState:
        if not selection.selected_stage_indices:
            raise ValueError("Select at least one stage to continue.")
        return self.create_profile_save_as_edit(
            selection.source_edit,
            profile_name,
            selection.selected_stage_indices,
        )

    def _copied_profile_edit(
        self,
        source: ValidationProfile,
        profile_name: str,
        selected_stage_indices: List[int],
    ) -> ProfileEditState:
        name = re.sub(r"\s+", " ", str(profile_name or "").strip())
        if not name:
            raise ValueError("New profile name is required.")
        profile = self.profile_editor.copy_profile(source, name, list(selected_stage_indices))
        path = self._unique_profile_path(name)
        labels = self.profile_editor.normalize_labels(profile, [])
        return ProfileEditState(
            profile_path=path,
            profile=profile,
            labels=labels,
            dirty=True,
            is_new=True,
        )

    def _unique_profile_path(self, profile_name: str) -> Path:
        stem = re.sub(r"[^A-Za-z0-9_. -]+", "_", str(profile_name or "New Profile")).strip(" ._")
        stem = stem or "New Profile"
        base = Path(self.settings.profiles_dir)
        candidate = base / f"{stem}.json"
        if not candidate.exists():
            return candidate
        for index in range(2, 1000):
            candidate = base / f"{stem} {index}.json"
            if not candidate.exists():
                return candidate
        return base / f"{stem} {now_local_iso().replace(':', '-')}.json"

    def profile_edit_summary_text(self, edit: ProfileEditState) -> str:
        return self.profile_edit_presenter.summary_text(edit)

    def profile_edit_items(self, edit: ProfileEditState) -> List[ProfileEditItem]:
        return self.profile_edit_presenter.items(edit)

    def profile_edit_action_for_key(self, key: str) -> FrontendActionSpec:
        return self.profile_edit_presenter.profile_edit_action_for_key(key)

    def profile_menu_group_keys(self) -> List[str]:
        return [str(item.get("key") or "custom") for item in self.profile_loader.menu_groups]

    def profile_edit_option_values(self, key: str) -> List[str]:
        return self.profile_edit_presenter.option_values(key)

    def profile_stage_picker_spec(self, edit: ProfileEditState, stage_index: int, key: str) -> SetupPickerSpec:
        return self.profile_edit_presenter.stage_picker_spec(edit, stage_index, key)

    def profile_stage_input_spec(self, edit: ProfileEditState, stage_index: int, field: str) -> SetupInputSpec:
        return self.profile_edit_presenter.stage_input_spec(edit, stage_index, field)

    def profile_stage_templates(self) -> List[Dict[str, Any]]:
        return self.profile_editor.stage_templates()

    def cycle_profile_menu_group(self, edit: ProfileEditState) -> str:
        result = self.profile_edit_controller.cycle_profile_menu_group(
            edit.profile,
            edit.labels,
            self.profile_menu_group_keys(),
        )
        edit.labels = result.labels
        edit.dirty = True
        return str(result.value)

    def apply_profile_edit_picker(
        self,
        edit: ProfileEditState,
        stage_index: int,
        key: str,
        selected: str,
    ) -> Any:
        return self.profile_edit_controller.apply_picker(edit, stage_index, key, selected).value

    def apply_profile_edit_input(
        self,
        edit: ProfileEditState,
        field: str,
        value: str,
        *,
        stage_index: Optional[int] = None,
        trim_start: Optional[int] = None,
    ) -> Any:
        result = self.profile_edit_controller.apply_input(
            edit,
            field,
            value,
            stage_index=stage_index,
            trim_start=trim_start,
        )
        if field == "__profile_name" and edit.is_new:
            edit.profile_path = self._unique_profile_path(edit.profile.profile_name)
        return result.value

    def apply_profile_storage_action(self, edit: ProfileEditState, stage_index: int, action: str) -> Any:
        result = self.profile_edit_controller.apply_stage_action(
            edit.profile,
            edit.labels,
            stage_index,
            action,
        )
        edit.labels = result.labels
        edit.dirty = True
        return result.value

    def save_profile_edit(self, edit: ProfileEditState) -> str:
        preparation = self.profile_save.prepare(edit.profile, edit.labels)
        edit.labels = preparation.labels
        self.profile_save.save(edit.profile_path, preparation)
        edit.dirty = False
        self.reload()
        return f"Profile saved: {edit.profile_path}"

    def prepare_profile_save(self, profile: ValidationProfile, labels: List[str]) -> ProfileSavePreparation:
        return self.profile_save.prepare(profile, labels)

    def save_prepared_profile(
        self,
        profile_path: Path,
        preparation: ProfileSavePreparation,
        *,
        allow_errors: bool = False,
    ) -> Path:
        return self.profile_save.save(profile_path, preparation, allow_errors=allow_errors)

    def normalize_profile_labels(self, profile: ValidationProfile, labels: List[str]) -> List[str]:
        return self.profile_editor.normalize_labels(profile, labels)

    def create_profile_stage(
        self,
        profile: ValidationProfile,
        test_type: str,
        duration_seconds: int = 300,
        modules: Any = None,
        stage_id: str = "",
        enabled: bool = True,
    ) -> StageConfig:
        return self.profile_editor.create_stage(
            profile,
            test_type=test_type,
            duration_seconds=duration_seconds,
            modules=modules,
            stage_id=stage_id,
            enabled=enabled,
        )

    def create_profile_stage_from_template(
        self,
        profile: ValidationProfile,
        template_key: str,
        duration_seconds: int = 300,
    ) -> tuple[StageConfig, str]:
        return self.profile_editor.template_stage(profile, template_key, duration_seconds=duration_seconds)

    def profile_stage_guided_allocation_fields(self, stage: StageConfig) -> List[str]:
        return self.profile_editor.guided_allocation_fields(stage)

    def profile_stage_guided_allocation_percent(self, stage: StageConfig, field: str) -> int:
        return self.profile_editor.guided_allocation_percent(stage, field)

    def apply_profile_stage_guided_allocation(self, stage: StageConfig, field: str, value: str) -> int:
        return self.profile_editor.apply_guided_allocation_percent(stage, field, value)

    def build_profile_stage_modules(self, test_type: str, **options: Any) -> StageModules:
        return self.profile_editor.build_stage_modules(test_type, **options)

    def build_profile(self, request: ProfileCreationRequest) -> ProfileBuildResult:
        return self.profile_creation.build_profile(request)

    def insert_profile_stage(
        self,
        profile: ValidationProfile,
        labels: List[str],
        draft: ProfileStageDraft,
        position: Optional[int] = None,
    ) -> ProfileStageInsertResult:
        return self.profile_creation.insert_stage(profile, labels, draft, position=position)

    def add_profile_stage(
        self,
        profile: ValidationProfile,
        labels: List[str],
        stage: StageConfig,
        label: str,
        position: Optional[int] = None,
    ) -> List[str]:
        return self.profile_edit_controller.add_stage(
            profile,
            labels,
            stage,
            label,
            position=position,
        ).labels

    def add_profile_stage_to_edit(
        self,
        edit: ProfileEditState,
        stage: StageConfig,
        label: str,
        position: Optional[int] = None,
    ) -> List[str]:
        return self.profile_edit_controller.add_stage_to_edit(
            edit,
            stage,
            label,
            position=position,
        ).labels

    def remove_profile_stage(self, profile: ValidationProfile, labels: List[str], index: int) -> List[str]:
        return self.profile_edit_controller.remove_stage(profile, labels, index).labels

    def remove_profile_stage_from_edit(self, edit: ProfileEditState, index: int) -> List[str]:
        return self.profile_edit_controller.remove_stage_from_edit(edit, index).labels

    def duplicate_profile_stage_in_edit(self, edit: ProfileEditState, index: int) -> int:
        result = self.profile_edit_controller.duplicate_stage_in_edit(edit, index)
        return int(result.value)

    def move_profile_stage_in_edit(self, edit: ProfileEditState, index: int, offset: int) -> int:
        result = self.profile_edit_controller.move_stage_in_edit(edit, index, offset)
        return int(result.value)

    def toggle_profile_edit_stage_enabled(self, edit: ProfileEditState, index: int) -> bool:
        result = self.profile_edit_controller.apply_stage_action(
            edit.profile,
            edit.labels,
            index,
            "toggle",
        )
        edit.labels = result.labels
        edit.dirty = True
        return bool(result.value)

    def cycle_profile_edit_strict_threshold_warnings(self, edit: ProfileEditState) -> Optional[bool]:
        result = self.profile_edit_controller.cycle_profile_strict(edit.profile, edit.labels)
        edit.labels = result.labels
        edit.dirty = True
        return result.value

    def set_profile_menu_group(self, profile: ValidationProfile, menu_group: str) -> str:
        return self.profile_editor.set_profile_menu_group(profile, menu_group)

    def set_profile_name(self, profile: ValidationProfile, name: str) -> str:
        return self.profile_editor.set_profile_name(profile, name)

    def set_profile_menu_description(self, profile: ValidationProfile, description: str) -> str:
        return self.profile_editor.set_profile_menu_description(profile, description)

    def cycle_profile_strict_threshold_warnings(self, profile: ValidationProfile) -> Optional[bool]:
        return self.profile_editor.cycle_profile_strict_threshold_warnings(profile)

    def cycle_stage_strict_threshold_warnings(self, stage: StageConfig) -> Optional[bool]:
        return self.profile_editor.cycle_stage_strict_threshold_warnings(stage)

    def set_profile_stage_label(
        self,
        profile: ValidationProfile,
        labels: List[str],
        index: int,
        label: str,
    ) -> List[str]:
        return self.profile_editor.set_stage_label(profile, labels, index, label)

    def set_profile_stage_duration(self, profile: ValidationProfile, index: int, duration_seconds: int) -> int:
        return self.profile_editor.set_stage_duration(profile, index, duration_seconds)

    def set_profile_stage_trim(
        self,
        profile: ValidationProfile,
        index: int,
        trim_start_seconds: int,
        trim_end_seconds: int,
    ) -> StageConfig:
        self.profile_editor.set_stage_trim(profile, index, trim_start_seconds, trim_end_seconds)
        return profile.stages[index]

    def toggle_profile_stage_enabled(self, profile: ValidationProfile, index: int) -> bool:
        return self.profile_editor.toggle_stage_enabled(profile, index)

    def set_profile_stage_gpu_target_mode(self, stage: StageConfig, mode: str) -> str:
        return self.profile_editor.set_gpu_target_mode(stage, mode)

    def set_profile_stage_cpu_instruction_set(self, stage: StageConfig, instruction_set: str) -> str:
        return self.profile_editor.set_cpu_instruction_set(stage, instruction_set)

    def set_profile_stage_cpu_threads(self, stage: StageConfig, threads: str) -> str:
        return self.profile_editor.set_cpu_threads(stage, threads)

    def set_profile_stage_memory_instruction_set(self, stage: StageConfig, instruction_set: str) -> str:
        return self.profile_editor.set_memory_instruction_set(stage, instruction_set)

    def set_profile_stage_gpu_backend_preference(self, stage: StageConfig, backend_preference: str) -> str:
        return self.profile_editor.set_gpu_backend_preference(stage, backend_preference)

    def set_profile_stage_vram_backend_preference(self, stage: StageConfig, backend_preference: str) -> str:
        return self.profile_editor.set_vram_backend_preference(stage, backend_preference)

    def set_profile_stage_gpu_3d_mode(self, stage: StageConfig, mode: str) -> str:
        return self.profile_editor.set_gpu_3d_mode(stage, mode)

    def set_profile_stage_gpu_intensity(self, stage: StageConfig, intensity: str) -> str:
        return self.profile_editor.set_gpu_intensity(stage, intensity)

    def set_profile_stage_gpu_compute_variant(self, stage: StageConfig, compute_variant: str) -> str:
        return self.profile_editor.set_gpu_compute_variant(stage, compute_variant)

    def set_profile_stage_memory_allocation_percent(self, stage: StageConfig, value: int) -> int:
        return self.profile_editor.set_memory_allocation_percent(stage, value)

    def set_profile_stage_gpu_3d_allocation_percent(self, stage: StageConfig, value: int) -> int:
        return self.profile_editor.set_gpu_3d_allocation_percent(stage, value)

    def set_profile_stage_vram_allocation_percent(self, stage: StageConfig, value: int) -> int:
        return self.profile_editor.set_vram_allocation_percent(stage, value)
