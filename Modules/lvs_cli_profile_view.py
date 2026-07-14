from __future__ import annotations

from pathlib import Path
from typing import Any, List

from .lvs_profile_edit_view import (
    profile_stage_detail_lines,
    stage_enabled_module_names,
    strict_threshold_override_text,
    vram_backend_candidates_for_preference,
    vram_backend_description,
    vram_backend_display_name,
)
from .lvs_profile_models import StageConfig, ValidationProfile


class ProfileCliViewMixin:
    """CLI profile and stage detail presentation adapters."""

    def _print_profile_detail(self, profile: ValidationProfile, labels: List[str]) -> None:
        self.editor.print_profile_detail(profile, labels)

    def _profile_detail_lines(self, profile: ValidationProfile, labels: List[str]) -> List[str]:
        return self.editor.profile_detail_lines(profile, labels)

    def _print_profile_edit_validation(self, profile: ValidationProfile, labels: List[str]) -> None:
        self.editor.print_profile_edit_validation(profile, labels)

    def _print_profile_edit_dry_run(
        self,
        profile_path: Path,
        profile: ValidationProfile,
        labels: List[str],
    ) -> None:
        self.editor.print_profile_edit_dry_run(profile_path, profile, labels)

    def _print_stage_detail(self, stage: StageConfig, label: str) -> None:
        print("\n".join(self._stage_detail_lines(stage, label)))

    def _stage_detail_lines(self, stage: StageConfig, label: str) -> List[str]:
        return profile_stage_detail_lines(
            stage,
            label,
            normalize_gpu_preference=self.workload_runner._normalize_gpu_3d_backend_preference,
            gpu_target_summary=self.workload_runner._gpu_target_summary,
            normalize_gpu_intensity=self.workload_runner._normalize_gpu_3d_intensity,
            gpu_preference_catalog=self.workload_runner._gpu_3d_backend_preference_catalog,
            normalize_vram_preference=self.workload_runner._normalize_vram_backend_preference,
        )

    def _stage_enabled_module_names(self, stage: StageConfig) -> List[str]:
        return stage_enabled_module_names(stage)

    def _vram_backend_candidates_for_preference(self, preference: str) -> List[str]:
        return vram_backend_candidates_for_preference(
            preference,
            normalize_preference=self.workload_runner._normalize_vram_backend_preference,
        )

    def _vram_backend_display_name(self, backend: str) -> str:
        return vram_backend_display_name(backend)

    def _vram_backend_description(self, backend: str) -> str:
        return vram_backend_description(backend)

    def _stage_gpu_target_mode_text(self, stage: StageConfig) -> str:
        if stage.modules.vram.enabled:
            return self.workload_runner._gpu_target_summary(stage.modules.vram.gpus)
        if stage.modules.gpu_3d.enabled:
            return self.workload_runner._gpu_target_summary(stage.modules.gpu_3d.gpus)
        return "-"

    def _stage_gpu_backend_text(self, stage: StageConfig) -> str:
        gpu_3d = self.workload_runner._normalize_gpu_3d_backend_preference(stage.modules.gpu_3d.backend_preference) if stage.modules.gpu_3d.enabled else "-"
        vram = self.workload_runner._normalize_vram_backend_preference(stage.modules.vram.backend_preference) if stage.modules.vram.enabled else "-"
        if stage.modules.gpu_3d.enabled and stage.modules.vram.enabled:
            return f"3d={gpu_3d},vram={vram}"
        if stage.modules.gpu_3d.enabled:
            return f"3d={gpu_3d}"
        if stage.modules.vram.enabled:
            return f"vram={vram}"
        return "-"

    def _stage_gpu_profile_text(self, stage: StageConfig) -> str:
        if not stage.modules.gpu_3d.enabled:
            return "-"
        mode = str(stage.modules.gpu_3d.mode or "steady").strip().lower() or "steady"
        intensity = self.workload_runner._normalize_gpu_3d_intensity(stage.modules.gpu_3d.intensity)
        preference = self.workload_runner._normalize_gpu_3d_backend_preference(stage.modules.gpu_3d.backend_preference)
        if preference == "opencl":
            variant = self.workload_runner._normalize_opencl_compute_variant(stage.modules.gpu_3d.compute_variant)
            return f"{mode}/{intensity}/{variant}"
        if preference == "vulkan_compute":
            variant = self.workload_runner._normalize_vulkan_compute_variant(stage.modules.gpu_3d.compute_variant)
            return f"{mode}/{intensity}/{variant}"
        return f"{mode}/{intensity}"

    def _strict_threshold_override_text(self, value: Any) -> str:
        return strict_threshold_override_text(value)
