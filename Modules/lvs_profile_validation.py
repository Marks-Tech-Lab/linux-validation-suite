#!/usr/bin/env python3
"""Prompt-free validation policy for validation profiles."""

from __future__ import annotations

from typing import Dict, List

from .lvs_gpu_backend_catalog import OPENCL_COMPUTE_VARIANTS, VULKAN_COMPUTE_VARIANTS
from .lvs_profile_models import StageConfig, ValidationProfile, stage_execution_mode


class ProfileValidator:
    def validate(self, profile: ValidationProfile, labels: List[str]) -> Dict[str, List[str]]:
        errors: List[str] = []
        warnings: List[str] = []

        if not profile.profile_name.strip():
            errors.append("profile_name is required")
        if not profile.stages:
            errors.append("profile must contain at least one stage")
        if len(labels) != len(profile.stages):
            errors.append(f"label count mismatch: {len(labels)} labels for {len(profile.stages)} stages")

        enabled_stage_count = 0
        seen_stage_ids: Dict[str, int] = {}

        for idx, stage in enumerate(profile.stages, start=1):
            stage_ref = f"stage {idx} [{stage.id}]"
            seen_stage_ids[stage.id] = seen_stage_ids.get(stage.id, 0) + 1

            execution_mode = stage_execution_mode(stage)
            if execution_mode == "mixed":
                errors.append(
                    f"{stage_ref} mixes completion-based storage_benchmark with duration-based workloads; "
                    "v1 requires a dedicated storage benchmark stage"
                )
            elif execution_mode == "duration" and (stage.duration_seconds is None or stage.duration_seconds <= 0):
                errors.append(f"{stage_ref} has invalid duration_seconds={stage.duration_seconds}")

            trim_start = stage.normalization.trim_start_seconds
            trim_end = stage.normalization.trim_end_seconds
            if trim_start < 0 or trim_end < 0:
                errors.append(f"{stage_ref} has negative trim values")
            elif execution_mode == "duration" and trim_start + trim_end >= int(stage.duration_seconds or 0):
                errors.append(
                    f"{stage_ref} trim window is impossible: start={trim_start}s end={trim_end}s duration={stage.duration_seconds}s"
                )

            storage = stage.modules.storage_benchmark
            if storage.enabled:
                if storage.profile_id != "storage_kdiskmark_cdm_style_v1":
                    errors.append(f"{stage_ref} has unsupported storage_benchmark.profile_id='{storage.profile_id}'")
                if storage.target_mode not in {"selected_target", "all_internal"}:
                    errors.append(f"{stage_ref} has invalid storage_benchmark.target_mode='{storage.target_mode}'")
                if storage.target_mode == "selected_target" and not str(storage.target_path or "").strip():
                    errors.append(f"{stage_ref} selected_target requires storage_benchmark.target_path")
                if storage.drive_execution != "sequential":
                    errors.append(f"{stage_ref} storage_benchmark.drive_execution must be sequential")
                try:
                    size_valid = 1 <= int(storage.test_size_gib) <= 8
                except (TypeError, ValueError):
                    size_valid = False
                if not size_valid:
                    errors.append(f"{stage_ref} storage_benchmark.test_size_gib must be between 1 and 8")
                try:
                    runs_valid = 1 <= int(storage.runs) <= 9
                except (TypeError, ValueError):
                    runs_valid = False
                if not runs_valid:
                    errors.append(f"{stage_ref} storage_benchmark.runs must be between 1 and 9")
                if storage.target_mode == "all_internal":
                    warnings.append(f"{stage_ref} benchmarks eligible internal drives sequentially")
                if storage.allow_system_drive:
                    warnings.append(f"{stage_ref} explicitly allows benchmarking the root/system drive")

            module_names = self._enabled_module_names(stage)
            if stage.enabled:
                enabled_stage_count += 1
                if not module_names:
                    errors.append(f"{stage_ref} is enabled but has no enabled workloads")
            elif module_names:
                warnings.append(f"{stage_ref} is disabled but still has configured workloads: {', '.join(module_names)}")

            if stage.modules.gpu_3d.enabled:
                compute_variant = str(stage.modules.gpu_3d.compute_variant or "baseline").strip().lower().replace("-", "_").replace(" ", "_")
                backend_preference = str(stage.modules.gpu_3d.backend_preference or "auto").strip().lower()
                vulkan_variants = {"", "baseline", *VULKAN_COMPUTE_VARIANTS.keys(), "memory", "memory_mix", "stateful"}
                opencl_variants = {"", *OPENCL_COMPUTE_VARIANTS.keys()}
                if backend_preference in {"auto", ""}:
                    if compute_variant not in vulkan_variants and compute_variant not in opencl_variants:
                        warnings.append(
                            f"{stage_ref} has unknown auto gpu_3d.compute_variant='{stage.modules.gpu_3d.compute_variant}'; backend defaults will be used"
                        )
                elif backend_preference in {"vulkan", "vulkan_compute", "python_vulkan_compute"}:
                    if compute_variant not in vulkan_variants:
                        warnings.append(
                            f"{stage_ref} has unknown Vulkan gpu_3d.compute_variant='{stage.modules.gpu_3d.compute_variant}'; hash will be used"
                        )
                elif compute_variant not in opencl_variants:
                    warnings.append(
                        f"{stage_ref} has unknown OpenCL gpu_3d.compute_variant='{stage.modules.gpu_3d.compute_variant}'; baseline will be used"
                    )

        if enabled_stage_count == 0:
            errors.append("profile has no enabled stages")

        for stage_id, count in seen_stage_ids.items():
            if count > 1:
                warnings.append(f"duplicate stage id detected: {stage_id}")

        if profile.defaults.telemetry_interval_seconds <= 0:
            errors.append(
                f"telemetry_interval_seconds must be > 0, got {profile.defaults.telemetry_interval_seconds}"
            )
        elif profile.defaults.telemetry_interval_seconds > 10:
            warnings.append(
                f"telemetry_interval_seconds is high ({profile.defaults.telemetry_interval_seconds}); short stages may have sparse samples"
            )

        return {"errors": errors, "warnings": warnings}

    def _enabled_module_names(self, stage: StageConfig) -> List[str]:
        names: List[str] = []
        if stage.modules.cpu.enabled:
            names.append("cpu")
        if stage.modules.memory.enabled:
            names.append("memory")
        if stage.modules.gpu_3d.enabled:
            names.append("gpu_3d")
        if stage.modules.vram.enabled:
            names.append("vram")
        if stage.modules.storage_benchmark.enabled:
            names.append("storage_benchmark")
        return names
