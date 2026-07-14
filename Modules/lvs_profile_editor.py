#!/usr/bin/env python3
"""Prompt-free profile mutation helpers for CLI/TUI/GUI reuse."""

from __future__ import annotations

import time
from typing import Any, List, Optional, Tuple

from .lvs_gpu_backend_catalog import (
    GPU_3D_INTENSITY_FACTORS,
    GPU_3D_PREFERENCE_CANDIDATE_MAP,
    OPENCL_COMPUTE_VARIANTS,
    VULKAN_COMPUTE_VARIANTS,
)
from .lvs_profile_loader import ProfileLoader
from .lvs_profile_models import (
    ModuleCpu,
    ModuleGpu3D,
    ModuleMemory,
    ModuleVram,
    StageConfig,
    StageModules,
    StageNormalization,
    ValidationProfile,
)


class ProfileEditor:
    """Pure profile edit operations shared by frontends.

    This class does not prompt, validate, or save. Callers decide how to collect
    user input and when to persist through ProfileLoader.
    """

    CPU_INSTRUCTION_OPTIONS = ["auto", "scalar", "sse", "avx", "avx2", "avx512"]
    MEMORY_INSTRUCTION_OPTIONS = ["auto", "scalar", "sse", "avx", "avx2", "avx512"]
    GPU_TARGET_OPTIONS = ["all", "discrete_all", "primary", "first"]
    GPU_3D_MODE_OPTIONS = ["steady", "variable"]
    VRAM_BACKEND_OPTIONS = ["auto", "opencl", "vulkan", "egl"]
    STAGE_TEMPLATES = [
        {"key": "cpu", "label": "CPU", "stage_type": "CPU", "default_label": "CPU"},
        {"key": "memory", "label": "Memory", "stage_type": "Memory", "default_label": "Memory"},
        {"key": "cpu_ram", "label": "CPU + RAM", "stage_type": "Combined", "default_label": "CPU + RAM"},
        {"key": "gpu_3d", "label": "3D Adaptive", "stage_type": "3D Adaptive", "default_label": "3D Adaptive"},
        {"key": "vram", "label": "VRAM", "stage_type": "VRAM", "default_label": "VRAM"},
        {"key": "cpu_3d", "label": "CPU + 3D", "stage_type": "Combined", "default_label": "CPU + 3D"},
        {"key": "cpu_vram", "label": "CPU + VRAM", "stage_type": "Combined", "default_label": "CPU + VRAM"},
        {"key": "gpu_vram", "label": "3D + VRAM", "stage_type": "Combined", "default_label": "3D + VRAM"},
        {"key": "power_auto", "label": "Power Test (CPU + 3D)", "stage_type": "Combined", "default_label": "Power (CPU + 3D)"},
        {"key": "sse_vram", "label": "SSE + VRAM", "stage_type": "Combined", "default_label": "SSE + VRAM"},
        {"key": "avx_ram", "label": "AVX + RAM", "stage_type": "Combined", "default_label": "AVX (CPU + RAM)"},
    ]

    def gpu_backend_options(self) -> List[str]:
        return list(GPU_3D_PREFERENCE_CANDIDATE_MAP.keys())

    def gpu_intensity_options(self) -> List[str]:
        return list(GPU_3D_INTENSITY_FACTORS.keys())

    def compute_variant_options(self) -> List[str]:
        options: List[str] = []
        for value in list(VULKAN_COMPUTE_VARIANTS.keys()) + list(OPENCL_COMPUTE_VARIANTS.keys()):
            if value not in options:
                options.append(value)
        return options

    def stage_templates(self) -> List[dict]:
        return [dict(item) for item in self.STAGE_TEMPLATES]

    def stage_template(self, key: str) -> dict:
        normalized = str(key or "").strip().lower()
        for item in self.STAGE_TEMPLATES:
            if item["key"] == normalized:
                return dict(item)
        return dict(self.STAGE_TEMPLATES[0])

    def normalize_labels(self, profile: ValidationProfile, labels: List[str]) -> List[str]:
        normalized = list(labels or [])
        while len(normalized) < len(profile.stages):
            index = len(normalized)
            normalized.append(profile.stages[index].name if index < len(profile.stages) else f"Segment {index + 1}")
        if len(normalized) > len(profile.stages):
            normalized = normalized[: len(profile.stages)]
        return normalized

    def next_stage_id(self, profile: ValidationProfile) -> str:
        used = {str(stage.id) for stage in profile.stages}
        for index in range(1, len(profile.stages) + 1000):
            candidate = f"segment_{index}"
            if candidate not in used:
                return candidate
        return f"segment_{int(time.time())}"

    def build_stage_modules(
        self,
        test_type: str,
        *,
        include_cpu: bool = False,
        include_memory: bool = False,
        include_gpu_3d: bool = False,
        include_vram: bool = False,
        gpu_target_mode: str = "all",
        cpu_instruction_set: str = "auto",
        cpu_mode: str = "normal",
        cpu_load: str = "steady",
        cpu_priority: str = "normal",
        cpu_threads: str = "all",
        memory_allocation_percent: int = 80,
        memory_instruction_set: str = "auto",
        gpu_backend_preference: str = "auto",
        gpu_mode: str = "steady",
        gpu_intensity: str = "extreme",
        gpu_compute_variant: str = "stress_hash",
        vram_backend_preference: str = "auto",
        vram_allocation_percent: int = 80,
        clamp_allocations: bool = True,
    ) -> StageModules:
        if test_type == "CPU":
            return StageModules(cpu=ModuleCpu(enabled=True))
        if test_type == "CPU+RAM":
            return StageModules(cpu=ModuleCpu(enabled=True), memory=ModuleMemory(enabled=True, allocation_percent=80))
        if test_type == "Memory":
            return StageModules(memory=ModuleMemory(enabled=True, allocation_percent=80))
        if test_type == "3D Adaptive":
            return StageModules(
                gpu_3d=ModuleGpu3D(
                    enabled=True,
                    mode=gpu_mode or "steady",
                    intensity=gpu_intensity or "extreme",
                    gpus=gpu_target_mode or "all",
                    backend_preference=gpu_backend_preference or "auto",
                    compute_variant=gpu_compute_variant or "stress_hash",
                )
            )
        if test_type == "VRAM":
            return StageModules(
                vram=ModuleVram(
                    enabled=True,
                    allocation_percent=self._clamp_int(vram_allocation_percent, 1, 95, 80),
                    gpus=gpu_target_mode or "all",
                    backend_preference=vram_backend_preference or "auto",
                )
            )
        if test_type == "Linpack":
            return StageModules(cpu=ModuleCpu(enabled=True, mode="extreme", instruction_set="auto"))
        if test_type == "Power Test (CPU + 3D)":
            return self.build_stage_modules(
                "Combined",
                include_cpu=True,
                include_gpu_3d=True,
                cpu_instruction_set="auto",
                cpu_mode="extreme",
                gpu_target_mode=gpu_target_mode,
                gpu_backend_preference=gpu_backend_preference,
                gpu_intensity=gpu_intensity,
                gpu_compute_variant=gpu_compute_variant,
            )
        if test_type == "SSE + VRAM":
            return self.build_stage_modules(
                "Combined",
                include_cpu=True,
                include_vram=True,
                cpu_instruction_set="sse",
                gpu_target_mode=gpu_target_mode,
                vram_backend_preference=vram_backend_preference,
                vram_allocation_percent=90,
            )
        if test_type == "AVX + RAM":
            return self.build_stage_modules(
                "Combined",
                include_cpu=True,
                include_memory=True,
                cpu_instruction_set="avx2",
                memory_instruction_set="avx2",
                memory_allocation_percent=90,
            )

        cpu = ModuleCpu(
            enabled=bool(include_cpu),
            mode=cpu_mode or "normal",
            load=cpu_load or "steady",
            instruction_set=cpu_instruction_set or "auto",
            threads=cpu_threads or "all",
            priority=cpu_priority or "normal",
        )
        memory_default = 90 if include_memory else 80
        memory_allocation = (
            self._clamp_int(memory_allocation_percent, 1, 95, memory_default)
            if clamp_allocations
            else self._parse_int(memory_allocation_percent, memory_default)
        )
        vram_default = 90 if include_vram else 80
        vram_allocation = (
            self._clamp_int(vram_allocation_percent, 1, 95, vram_default)
            if clamp_allocations
            else self._parse_int(vram_allocation_percent, vram_default)
        )
        memory = ModuleMemory(
            enabled=bool(include_memory),
            allocation_percent=memory_allocation,
            instruction_set=memory_instruction_set or "auto",
        )
        gpu = ModuleGpu3D(
            enabled=bool(include_gpu_3d),
            mode=gpu_mode or "steady",
            intensity=gpu_intensity or "extreme",
            gpus=gpu_target_mode or "all",
            backend_preference=gpu_backend_preference or "auto",
            compute_variant=gpu_compute_variant or "stress_hash",
        )
        vram = ModuleVram(
            enabled=bool(include_vram),
            allocation_percent=vram_allocation,
            gpus=gpu_target_mode or "all",
            backend_preference=vram_backend_preference or "auto",
        )
        return StageModules(cpu=cpu, memory=memory, gpu_3d=gpu, vram=vram)

    def template_stage(self, profile: ValidationProfile, key: str, duration_seconds: int = 300) -> Tuple[StageConfig, str]:
        template = self.stage_template(key)
        modules = self._template_modules(str(template["key"]))
        stage = self.create_stage(
            profile,
            test_type=str(template["stage_type"]),
            duration_seconds=duration_seconds,
            modules=modules,
        )
        return stage, str(template["default_label"])

    def _template_modules(self, key: str) -> StageModules:
        if key == "cpu":
            return self.build_stage_modules("CPU")
        if key == "memory":
            return self.build_stage_modules("Memory")
        if key == "cpu_ram":
            return self.build_stage_modules("Combined", include_cpu=True, include_memory=True)
        if key == "gpu_3d":
            return self.build_stage_modules("3D Adaptive")
        if key == "vram":
            return self.build_stage_modules("VRAM")
        if key == "cpu_3d":
            return self.build_stage_modules("Combined", include_cpu=True, include_gpu_3d=True)
        if key == "cpu_vram":
            return self.build_stage_modules("Combined", include_cpu=True, include_vram=True, vram_allocation_percent=90)
        if key == "gpu_vram":
            return self.build_stage_modules(
                "Combined",
                include_gpu_3d=True,
                include_vram=True,
                vram_allocation_percent=90,
            )
        if key == "power_auto":
            return self.build_stage_modules("Power Test (CPU + 3D)")
        if key == "sse_vram":
            return self.build_stage_modules("SSE + VRAM")
        if key == "avx_ram":
            return self.build_stage_modules("AVX + RAM")
        return self.build_stage_modules("CPU")

    def create_stage(
        self,
        profile: ValidationProfile,
        *,
        test_type: str,
        duration_seconds: int = 300,
        modules: Optional[StageModules] = None,
        stage_id: str = "",
        enabled: bool = True,
    ) -> StageConfig:
        return StageConfig(
            id=stage_id or self.next_stage_id(profile),
            name=test_type or "Combined",
            duration_seconds=max(1, int(duration_seconds or 300)),
            enabled=bool(enabled),
            modules=modules or self.build_stage_modules(test_type or "Combined"),
            normalization=StageNormalization(
                profile.defaults.trim_start_seconds,
                profile.defaults.trim_end_seconds,
            ),
        )

    def add_stage(
        self,
        profile: ValidationProfile,
        labels: List[str],
        stage: StageConfig,
        label: str,
        position: Optional[int] = None,
    ) -> Tuple[ValidationProfile, List[str]]:
        normalized = self.normalize_labels(profile, labels)
        insert_index = len(profile.stages) if position is None else max(0, min(len(profile.stages), int(position)))
        profile.stages.insert(insert_index, stage)
        normalized.insert(insert_index, str(label or stage.name or f"Segment {insert_index + 1}"))
        return profile, self.normalize_labels(profile, normalized)

    def remove_stage(
        self,
        profile: ValidationProfile,
        labels: List[str],
        index: int,
    ) -> Tuple[ValidationProfile, List[str]]:
        if len(profile.stages) <= 1:
            raise ValueError("Profiles must keep at least one stage")
        if index < 0 or index >= len(profile.stages):
            raise IndexError("stage index out of range")
        normalized = self.normalize_labels(profile, labels)
        del profile.stages[index]
        if index < len(normalized):
            del normalized[index]
        return profile, self.normalize_labels(profile, normalized)

    def set_profile_menu_group(self, profile: ValidationProfile, menu_group: str) -> str:
        profile.menu_group = ProfileLoader._normalize_menu_group(menu_group)
        return profile.menu_group

    def set_profile_name(self, profile: ValidationProfile, name: str) -> str:
        text = str(name or "").strip()
        profile.profile_name = text or profile.profile_name or "New Profile"
        return profile.profile_name

    def set_profile_menu_description(self, profile: ValidationProfile, description: str) -> str:
        profile.menu_description = str(description or "").strip()
        return profile.menu_description

    def cycle_optional_bool(self, value: Optional[bool]) -> Optional[bool]:
        if value is None:
            return True
        if value is True:
            return False
        return None

    def cycle_profile_strict_threshold_warnings(self, profile: ValidationProfile) -> Optional[bool]:
        profile.defaults.strict_threshold_recommendation_warnings = self.cycle_optional_bool(
            profile.defaults.strict_threshold_recommendation_warnings
        )
        return profile.defaults.strict_threshold_recommendation_warnings

    def cycle_stage_strict_threshold_warnings(self, stage: StageConfig) -> Optional[bool]:
        stage.strict_threshold_recommendation_warnings = self.cycle_optional_bool(
            stage.strict_threshold_recommendation_warnings
        )
        return stage.strict_threshold_recommendation_warnings

    def set_stage_label(self, profile: ValidationProfile, labels: List[str], index: int, label: str) -> List[str]:
        self._require_stage_index(profile, index)
        normalized = self.normalize_labels(profile, labels)
        normalized[index] = str(label or normalized[index]).strip() or normalized[index]
        return normalized

    def set_stage_duration(self, profile: ValidationProfile, index: int, duration_seconds: int) -> int:
        stage = self._stage(profile, index)
        stage.duration_seconds = max(1, int(duration_seconds))
        return stage.duration_seconds

    def set_stage_trim(self, profile: ValidationProfile, index: int, trim_start_seconds: int, trim_end_seconds: int) -> StageNormalization:
        stage = self._stage(profile, index)
        stage.normalization.trim_start_seconds = max(0, int(trim_start_seconds))
        stage.normalization.trim_end_seconds = max(0, int(trim_end_seconds))
        return stage.normalization

    def toggle_stage_enabled(self, profile: ValidationProfile, index: int) -> bool:
        stage = self._stage(profile, index)
        stage.enabled = not stage.enabled
        return stage.enabled

    def set_gpu_target_mode(self, stage: StageConfig, mode: str) -> str:
        normalized = str(mode or "all").strip() or "all"
        if stage.modules.gpu_3d.enabled:
            stage.modules.gpu_3d.gpus = normalized
        if stage.modules.vram.enabled:
            stage.modules.vram.gpus = normalized
        return normalized

    def set_cpu_instruction_set(self, stage: StageConfig, instruction_set: str) -> str:
        normalized = self._normalize_choice(instruction_set, self.CPU_INSTRUCTION_OPTIONS, "auto")
        stage.modules.cpu.instruction_set = normalized
        return normalized

    def set_cpu_threads(self, stage: StageConfig, threads: str) -> str:
        normalized = str(threads or "all").strip().lower() or "all"
        stage.modules.cpu.threads = normalized
        return normalized

    def set_memory_instruction_set(self, stage: StageConfig, instruction_set: str) -> str:
        normalized = self._normalize_choice(instruction_set, self.MEMORY_INSTRUCTION_OPTIONS, "auto")
        stage.modules.memory.instruction_set = normalized
        return normalized

    def set_gpu_backend_preference(self, stage: StageConfig, backend_preference: str) -> str:
        normalized = self._normalize_choice(backend_preference, self.gpu_backend_options(), "auto")
        stage.modules.gpu_3d.backend_preference = normalized
        return normalized

    def set_vram_backend_preference(self, stage: StageConfig, backend_preference: str) -> str:
        normalized = self._normalize_choice(backend_preference, self.VRAM_BACKEND_OPTIONS, "auto")
        stage.modules.vram.backend_preference = normalized
        return normalized

    def set_gpu_3d_mode(self, stage: StageConfig, mode: str) -> str:
        normalized = self._normalize_choice(mode, self.GPU_3D_MODE_OPTIONS, "steady")
        stage.modules.gpu_3d.mode = normalized
        return normalized

    def set_gpu_intensity(self, stage: StageConfig, intensity: str) -> str:
        normalized = self._normalize_choice(intensity, self.gpu_intensity_options(), "extreme")
        stage.modules.gpu_3d.intensity = normalized
        return normalized

    def set_gpu_compute_variant(self, stage: StageConfig, compute_variant: str) -> str:
        normalized = self._normalize_choice(compute_variant, self.compute_variant_options(), "stress_hash")
        stage.modules.gpu_3d.compute_variant = normalized
        return normalized

    def set_memory_allocation_percent(self, stage: StageConfig, value: int) -> int:
        stage.modules.memory.allocation_percent = self._clamp_int(value, 1, 95, stage.modules.memory.allocation_percent)
        return stage.modules.memory.allocation_percent

    def set_gpu_3d_allocation_percent(self, stage: StageConfig, value: int) -> int:
        stage.modules.gpu_3d.allocation_percent = self._clamp_int(value, 0, 95, stage.modules.gpu_3d.allocation_percent)
        return stage.modules.gpu_3d.allocation_percent

    def set_vram_allocation_percent(self, stage: StageConfig, value: int) -> int:
        stage.modules.vram.allocation_percent = self._clamp_int(value, 1, 95, stage.modules.vram.allocation_percent)
        return stage.modules.vram.allocation_percent

    def _stage(self, profile: ValidationProfile, index: int) -> StageConfig:
        self._require_stage_index(profile, index)
        return profile.stages[index]

    def _require_stage_index(self, profile: ValidationProfile, index: int) -> None:
        if index < 0 or index >= len(profile.stages):
            raise IndexError("stage index out of range")

    def _clamp_int(self, value: Any, minimum: int, maximum: int, fallback: int) -> int:
        return max(minimum, min(maximum, self._parse_int(value, fallback)))

    def _parse_int(self, value: Any, fallback: int) -> int:
        try:
            return int(value)
        except Exception:
            return int(fallback)

    def _normalize_choice(self, value: Any, options: List[str], fallback: str) -> str:
        normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        return normalized if normalized in options else fallback
