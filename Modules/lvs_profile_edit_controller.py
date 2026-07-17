#!/usr/bin/env python3
"""Frontend-neutral profile edit mutation and action dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Optional

from .lvs_profile_editor import ProfileEditor
from .lvs_service_models import ProfileEditState


@dataclass(frozen=True)
class ProfileStageAction:
    key: str
    label: str


@dataclass
class ProfileEditMutationResult:
    labels: List[str]
    value: Any = None
    changed: bool = True


class ProfileEditController:
    """Applies profile mutations without depending on terminal or widget APIs."""

    STAGE_ACTIONS = (
        ProfileStageAction("detail", "Show stage details"),
        ProfileStageAction("label", "Edit label"),
        ProfileStageAction("duration", "Edit duration"),
        ProfileStageAction("toggle", "Toggle enabled"),
        ProfileStageAction("cpu_instruction", "Edit CPU instruction set"),
        ProfileStageAction("cpu_threads", "Edit CPU threads"),
        ProfileStageAction("memory_allocation", "Edit memory allocation percent"),
        ProfileStageAction("gpu_target", "Edit GPU target mode"),
        ProfileStageAction("gpu_backend", "Edit 3D backend preference"),
        ProfileStageAction("gpu_mode", "Edit 3D mode"),
        ProfileStageAction("gpu_intensity", "Edit 3D intensity"),
        ProfileStageAction("gpu_compute_variant", "Edit 3D compute variant"),
        ProfileStageAction("gpu_allocation", "Edit 3D VRAM allocation percent"),
        ProfileStageAction("vram_backend", "Edit VRAM backend preference"),
        ProfileStageAction("vram_allocation", "Edit VRAM allocation percent"),
        ProfileStageAction("strict", "Cycle stage strict threshold warnings override"),
        ProfileStageAction("back", "Back"),
    )

    def __init__(self, profile_editor: ProfileEditor) -> None:
        self.profile_editor = profile_editor

    def stage_action(self, selection: Any) -> Optional[ProfileStageAction]:
        try:
            return self.STAGE_ACTIONS[int(str(selection).strip()) - 1]
        except (TypeError, ValueError, IndexError):
            return None

    def normalize_labels(self, profile: Any, labels: List[str]) -> List[str]:
        return self.profile_editor.normalize_labels(profile, labels)

    def add_stage(
        self,
        profile: Any,
        labels: List[str],
        stage: Any,
        label: str,
        *,
        position: Optional[int] = None,
    ) -> ProfileEditMutationResult:
        _, updated = self.profile_editor.add_stage(profile, labels, stage, label, position=position)
        return ProfileEditMutationResult(updated, stage)

    def remove_stage(self, profile: Any, labels: List[str], index: int) -> ProfileEditMutationResult:
        _, updated = self.profile_editor.remove_stage(profile, labels, index)
        return ProfileEditMutationResult(updated, index)

    def cycle_profile_strict(self, profile: Any, labels: List[str]) -> ProfileEditMutationResult:
        value = self.profile_editor.cycle_profile_strict_threshold_warnings(profile)
        return ProfileEditMutationResult(self.normalize_labels(profile, labels), value)

    def set_profile_menu_group(self, profile: Any, labels: List[str], value: str) -> ProfileEditMutationResult:
        selected = self.profile_editor.set_profile_menu_group(profile, value)
        return ProfileEditMutationResult(self.normalize_labels(profile, labels), selected)

    def cycle_profile_menu_group(
        self,
        profile: Any,
        labels: List[str],
        menu_group_keys: Iterable[str],
    ) -> ProfileEditMutationResult:
        keys = [str(item or "custom") for item in menu_group_keys] or ["custom"]
        current = str(profile.menu_group or "custom")
        try:
            index = keys.index(current)
        except ValueError:
            index = -1
        return self.set_profile_menu_group(profile, labels, keys[(index + 1) % len(keys)])

    @staticmethod
    def stage_action_error(stage: Any, action: str) -> str:
        if action == "duration" and stage.modules.storage_benchmark.enabled:
            return "Storage Benchmark is completion-based and has no stage duration."
        if action in {"cpu_instruction", "cpu_threads"} and not stage.modules.cpu.enabled:
            return "CPU module is not enabled on this stage."
        if action == "memory_allocation" and not stage.modules.memory.enabled:
            return "Memory module is not enabled on this stage."
        if action == "gpu_target" and not (stage.modules.gpu_3d.enabled or stage.modules.vram.enabled):
            return "No GPU workload is enabled on this stage."
        if action in {"gpu_backend", "gpu_mode", "gpu_intensity", "gpu_compute_variant", "gpu_allocation"} and not stage.modules.gpu_3d.enabled:
            return "3D module is not enabled on this stage."
        if action in {"vram_backend", "vram_allocation"} and not stage.modules.vram.enabled:
            return "VRAM module is not enabled on this stage."
        return ""

    def apply_stage_action(
        self,
        profile: Any,
        labels: List[str],
        index: int,
        action: str,
        value: Any = None,
        *,
        secondary_value: Any = None,
    ) -> ProfileEditMutationResult:
        if index < 0 or index >= len(profile.stages):
            raise IndexError("stage index out of range")
        labels = self.normalize_labels(profile, labels)
        stage = profile.stages[index]
        error = self.stage_action_error(stage, action)
        if error:
            raise ValueError(error)
        changed: Any
        if action == "label":
            labels = self.profile_editor.set_stage_label(profile, labels, index, str(value or ""))
            changed = labels[index]
        elif action == "duration":
            changed = self.profile_editor.set_stage_duration(profile, index, int(value))
        elif action == "toggle":
            changed = self.profile_editor.toggle_stage_enabled(profile, index)
        elif action == "cpu_instruction":
            changed = self.profile_editor.set_cpu_instruction_set(stage, str(value))
        elif action == "cpu_threads":
            changed = self.profile_editor.set_cpu_threads(stage, str(value))
        elif action == "memory_instruction":
            if not stage.modules.memory.enabled:
                raise ValueError("Memory module is not enabled on this stage.")
            changed = self.profile_editor.set_memory_instruction_set(stage, str(value))
        elif action == "memory_allocation":
            changed = self.profile_editor.set_memory_allocation_percent(stage, int(value))
        elif action == "gpu_target":
            changed = self.profile_editor.set_gpu_target_mode(stage, str(value))
        elif action == "gpu_backend":
            changed = self.profile_editor.set_gpu_backend_preference(stage, str(value))
        elif action == "vram_backend":
            changed = self.profile_editor.set_vram_backend_preference(stage, str(value))
        elif action == "gpu_mode":
            changed = self.profile_editor.set_gpu_3d_mode(stage, str(value))
        elif action == "gpu_intensity":
            changed = self.profile_editor.set_gpu_intensity(stage, str(value))
        elif action == "gpu_compute_variant":
            changed = self.profile_editor.set_gpu_compute_variant(stage, str(value))
        elif action == "gpu_allocation":
            changed = self.profile_editor.set_gpu_3d_allocation_percent(stage, int(value))
        elif action == "vram_allocation":
            changed = self.profile_editor.set_vram_allocation_percent(stage, int(value))
        elif action == "trim":
            self.profile_editor.set_stage_trim(profile, index, int(value), int(secondary_value))
            changed = stage
        elif action == "strict":
            changed = self.profile_editor.cycle_stage_strict_threshold_warnings(stage)
        else:
            raise ValueError(f"Unsupported profile stage action: {action}")
        return ProfileEditMutationResult(labels, changed)

    def add_stage_to_edit(
        self,
        edit: ProfileEditState,
        stage: Any,
        label: str,
        *,
        position: Optional[int] = None,
    ) -> ProfileEditMutationResult:
        result = self.add_stage(edit.profile, edit.labels, stage, label, position=position)
        edit.labels = result.labels
        edit.dirty = True
        return result

    def remove_stage_from_edit(self, edit: ProfileEditState, index: int) -> ProfileEditMutationResult:
        result = self.remove_stage(edit.profile, edit.labels, index)
        edit.labels = result.labels
        edit.dirty = True
        return result

    def apply_picker(self, edit: ProfileEditState, index: int, key: str, selected: str) -> ProfileEditMutationResult:
        stage = edit.profile.stages[index]
        action = str(key or "")
        if action == "backend":
            action = "gpu_backend" if stage.modules.gpu_3d.enabled else "vram_backend"
        action_map = {
            "gpu_target": "gpu_target",
            "intensity": "gpu_intensity",
            "compute_variant": "gpu_compute_variant",
            "cpu_instruction": "cpu_instruction",
            "memory_instruction": "memory_instruction",
        }
        action = action_map.get(action, action)
        result = self.apply_stage_action(edit.profile, edit.labels, index, action, selected)
        edit.labels = result.labels
        edit.dirty = True
        return result

    def apply_input(
        self,
        edit: ProfileEditState,
        field: str,
        value: str,
        *,
        stage_index: Optional[int] = None,
        trim_start: Optional[int] = None,
    ) -> ProfileEditMutationResult:
        normalized = str(field or "")
        if normalized == "__profile_name":
            changed = self.profile_editor.set_profile_name(edit.profile, value)
            result = ProfileEditMutationResult(self.normalize_labels(edit.profile, edit.labels), changed)
        elif normalized == "__profile_description":
            changed = self.profile_editor.set_profile_menu_description(edit.profile, value)
            result = ProfileEditMutationResult(self.normalize_labels(edit.profile, edit.labels), changed)
        else:
            if stage_index is None:
                raise ValueError("Select a stage row first.")
            action_map = {
                "__profile_stage_duration": "duration",
                "__profile_stage_label": "label",
                "__profile_stage_vram_allocation": "vram_allocation",
                "__profile_stage_memory_allocation": "memory_allocation",
            }
            if normalized == "__profile_stage_trim_end":
                if trim_start is None:
                    trim_start = int(edit.profile.stages[stage_index].normalization.trim_start_seconds)
                result = self.apply_stage_action(
                    edit.profile,
                    edit.labels,
                    stage_index,
                    "trim",
                    max(0, int(trim_start)),
                    secondary_value=max(0, int(float(value or "0"))),
                )
            elif normalized in action_map:
                action = action_map[normalized]
                parsed: Any = value
                if action in {"duration", "vram_allocation", "memory_allocation"}:
                    parsed = int(float(value or "0"))
                result = self.apply_stage_action(edit.profile, edit.labels, stage_index, action, parsed)
            else:
                raise ValueError(f"Unsupported profile edit input: {field}")
        edit.labels = result.labels
        edit.dirty = True
        return result
