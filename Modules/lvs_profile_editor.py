#!/usr/bin/env python3
"""Prompt-free profile mutation helpers for CLI/TUI/GUI reuse."""

from __future__ import annotations

import math
import re
import time
from copy import deepcopy
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
    ModuleStorageBenchmark,
    ModuleVram,
    StageConfig,
    StageModules,
    StageNormalization,
    ValidationProfile,
)


def format_profile_duration(seconds: Optional[int]) -> str:
    """Render a stored duration without making operators convert seconds."""
    if seconds is None:
        return "Completion-based"
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: List[str] = []
    if hours:
        parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
    if minutes:
        parts.append(f"{minutes} minute" + ("s" if minutes != 1 else ""))
    if secs or not parts:
        parts.append(f"{secs} second" + ("s" if secs != 1 else ""))
    return " ".join(parts)


def parse_profile_duration(value: Any) -> int:
    """Parse seconds or a compact sequence such as ``1h 30m``."""
    text = str(value or "").strip().lower()
    if not text:
        raise ValueError("Duration is required (examples: 90s, 5m, 1h 30m).")
    if re.fullmatch(r"\d+", text):
        total = int(text)
    else:
        compact = re.sub(r"\s+", "", text)
        matches = list(re.finditer(r"(\d+)(h|m|s)", compact))
        if not matches or "".join(match.group(0) for match in matches) != compact:
            raise ValueError("Use seconds or a compact duration such as 90s, 5m, or 1h 30m.")
        factors = {"h": 3600, "m": 60, "s": 1}
        total = sum(int(match.group(1)) * factors[match.group(2)] for match in matches)
    if total <= 0:
        raise ValueError("Duration must be greater than zero.")
    return total


class ProfileEditor:
    """Pure profile edit operations shared by frontends.

    This class does not prompt, validate, or save. Callers decide how to collect
    user input and when to persist through ProfileLoader.
    """

    CPU_INSTRUCTION_OPTIONS = ["auto", "scalar", "sse", "avx", "avx2", "avx512", "neon"]
    CPU_INSTRUCTION_INTENT_OPTIONS = ["", "baseline_vector", "high_throughput_vector", "highest_verified_vector"]
    CPU_BACKEND_OPTIONS = ["auto", "native", "stress_ng", "python_fallback"]
    CPU_MODE_OPTIONS = ["normal", "extreme"]
    CPU_LOAD_OPTIONS = ["steady", "variable"]
    MEMORY_INSTRUCTION_OPTIONS = ["auto", "scalar", "sse", "avx", "avx2", "avx512"]
    GPU_TARGET_OPTIONS = ["all", "discrete_all", "primary", "first"]
    GPU_3D_MODE_OPTIONS = ["steady", "variable"]
    VRAM_BACKEND_OPTIONS = ["auto", "opencl", "vulkan", "egl"]
    STAGE_TEMPLATES = [
        {"key": "cpu", "label": "CPU", "stage_type": "CPU", "default_label": "CPU"},
        {"key": "memory", "label": "Memory", "stage_type": "Memory", "default_label": "Memory"},
        {"key": "cpu_ram", "label": "CPU + RAM", "stage_type": "Combined", "default_label": "CPU + RAM"},
        {"key": "power_auto", "label": "Power (CPU + GPU)", "stage_type": "Combined", "default_label": "Power (CPU + GPU)"},
        {"key": "baseline_ram", "label": "Baseline SIMD (CPU + RAM)", "stage_type": "Combined", "default_label": "Baseline SIMD (CPU + RAM)"},
        {"key": "baseline_vram", "label": "Baseline SIMD (CPU + VRAM)", "stage_type": "Combined", "default_label": "Baseline SIMD (CPU + VRAM)"},
        {"key": "baseline_ram_vram", "label": "Baseline SIMD (CPU + RAM/VRAM)", "stage_type": "Combined", "default_label": "Baseline SIMD (CPU + RAM/VRAM)"},
        {"key": "high_throughput_ram", "label": "High-Throughput SIMD (CPU + RAM)", "stage_type": "Combined", "default_label": "High-Throughput SIMD (CPU + RAM)"},
        {"key": "gpu_3d", "label": "GPU (3D)", "stage_type": "3D Adaptive", "default_label": "GPU (3D)"},
        {"key": "gpu_vram", "label": "GPU (3D + VRAM)", "stage_type": "Combined", "default_label": "GPU (3D + VRAM)"},
        {"key": "vram", "label": "VRAM", "stage_type": "VRAM", "default_label": "VRAM"},
        {"key": "storage_benchmark", "label": "Storage Benchmark", "stage_type": "Storage Benchmark", "default_label": "Storage Benchmark"},
        {"key": "custom_advanced", "label": "Custom / Advanced", "stage_type": "Combined", "default_label": "Custom Stage"},
    ]
    LEGACY_STAGE_TEMPLATES = [
        {"key": "cpu_3d", "label": "CPU + GPU", "stage_type": "Combined", "default_label": "CPU + GPU"},
        {"key": "cpu_vram", "label": "CPU + VRAM", "stage_type": "Combined", "default_label": "CPU + VRAM"},
    ]
    TEMPLATE_ALIASES = {"sse_vram": "baseline_vram", "avx_ram": "high_throughput_ram"}

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
        normalized = self.TEMPLATE_ALIASES.get(normalized, normalized)
        for item in self.STAGE_TEMPLATES + self.LEGACY_STAGE_TEMPLATES:
            if item["key"] == normalized:
                return dict(item)
        return dict(self.STAGE_TEMPLATES[0])

    def normalize_labels(self, profile: ValidationProfile, labels: List[str]) -> List[str]:
        supplied = list(labels or [])
        normalized: List[str] = []
        for index, stage in enumerate(profile.stages):
            value = supplied[index] if index < len(supplied) else stage.display_label
            stage.display_label = str(value or stage.display_label or stage.name or f"Segment {index + 1}").strip()
            normalized.append(stage.display_label)
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
        cpu_instruction_intent: str = "",
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
        if test_type == "Storage Benchmark":
            return StageModules(storage_benchmark=ModuleStorageBenchmark(enabled=True))
        if test_type == "Power Test (CPU + 3D)":
            modules = self.build_stage_modules(
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
            modules.cpu.power_auto = True
            return modules
        if test_type == "SSE + VRAM":
            return self.build_stage_modules(
                "Combined",
                include_cpu=True,
                include_vram=True,
                cpu_instruction_intent="baseline_vector",
                gpu_target_mode=gpu_target_mode,
                vram_backend_preference=vram_backend_preference,
                vram_allocation_percent=90,
            )
        if test_type == "AVX + RAM":
            return self.build_stage_modules(
                "Combined",
                include_cpu=True,
                include_memory=True,
                cpu_instruction_intent="high_throughput_vector",
                memory_instruction_set="auto",
                memory_allocation_percent=90,
            )

        cpu = ModuleCpu(
            enabled=bool(include_cpu),
            mode=cpu_mode or "normal",
            load=cpu_load or "steady",
            instruction_set=cpu_instruction_set or "auto",
            instruction_intent=cpu_instruction_intent or "",
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
            return self.build_stage_modules(
                "Combined", include_memory=True, memory_allocation_percent=90
            )
        if key == "cpu_ram":
            return self.build_stage_modules("Combined", include_cpu=True, include_memory=True, memory_allocation_percent=90)
        if key == "gpu_3d":
            return self.build_stage_modules("3D Adaptive")
        if key == "vram":
            return self.build_stage_modules(
                "Combined", include_vram=True, vram_allocation_percent=90
            )
        if key == "gpu_vram":
            return self.build_stage_modules(
                "Combined",
                include_gpu_3d=True,
                include_vram=True,
                vram_allocation_percent=90,
            )
        if key == "cpu_3d":
            return self.build_stage_modules("Combined", include_cpu=True, include_gpu_3d=True)
        if key == "cpu_vram":
            return self.build_stage_modules(
                "Combined", include_cpu=True, include_vram=True, vram_allocation_percent=90
            )
        if key == "power_auto":
            return self.build_stage_modules("Power Test (CPU + 3D)")
        if key in {"baseline_ram", "baseline_vram", "baseline_ram_vram"}:
            return self.build_stage_modules(
                "Combined",
                include_cpu=True,
                include_memory=key in {"baseline_ram", "baseline_ram_vram"},
                include_vram=key in {"baseline_vram", "baseline_ram_vram"},
                cpu_instruction_intent="baseline_vector",
                cpu_mode="normal",
                memory_allocation_percent=90,
                memory_instruction_set="auto",
                vram_allocation_percent=90,
            )
        if key == "high_throughput_ram":
            return self.build_stage_modules(
                "Combined", include_cpu=True, include_memory=True,
                cpu_instruction_intent="high_throughput_vector", cpu_mode="normal",
                memory_instruction_set="auto", memory_allocation_percent=90,
            )
        if key == "storage_benchmark":
            return self.build_stage_modules("Storage Benchmark")
        if key == "custom_advanced":
            return StageModules()
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
        selected_modules = modules or self.build_stage_modules(test_type or "Combined")
        completion_based = bool(selected_modules.storage_benchmark.enabled)
        return StageConfig(
            id=stage_id or self.next_stage_id(profile),
            name=test_type or "Combined",
            duration_seconds=None if completion_based else max(1, int(duration_seconds or 300)),
            display_label=test_type or "Combined",
            enabled=bool(enabled),
            modules=selected_modules,
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
        stage.display_label = str(label or stage.display_label or stage.name or f"Segment {insert_index + 1}")
        normalized.insert(insert_index, stage.display_label)
        return profile, self.normalize_labels(profile, normalized)

    def remove_stage(
        self,
        profile: ValidationProfile,
        labels: List[str],
        index: int,
    ) -> Tuple[ValidationProfile, List[str]]:
        if index < 0 or index >= len(profile.stages):
            raise IndexError("stage index out of range")
        normalized = self.normalize_labels(profile, labels)
        del profile.stages[index]
        if index < len(normalized):
            del normalized[index]
        return profile, self.normalize_labels(profile, normalized)

    def duplicate_stage(self, profile: ValidationProfile, labels: List[str], index: int) -> Tuple[StageConfig, List[str]]:
        self._require_stage_index(profile, index)
        labels = self.normalize_labels(profile, labels)
        duplicate = deepcopy(profile.stages[index])
        duplicate.id = self.next_stage_id(profile)
        profile.stages.insert(index + 1, duplicate)
        labels.insert(index + 1, duplicate.display_label)
        return duplicate, self.normalize_labels(profile, labels)

    def move_stage(self, profile: ValidationProfile, labels: List[str], index: int, offset: int) -> Tuple[int, List[str]]:
        self._require_stage_index(profile, index)
        destination = index + int(offset)
        if destination < 0 or destination >= len(profile.stages):
            return index, self.normalize_labels(profile, labels)
        labels = self.normalize_labels(profile, labels)
        stage = profile.stages.pop(index)
        label = labels.pop(index)
        profile.stages.insert(destination, stage)
        labels.insert(destination, label)
        return destination, self.normalize_labels(profile, labels)

    def copy_profile(
        self,
        source: ValidationProfile,
        profile_name: str,
        selected_stage_indices: List[int],
    ) -> ValidationProfile:
        if not selected_stage_indices:
            raise ValueError("Select at least one stage to copy.")
        selected: List[StageConfig] = []
        for destination_index, source_index in enumerate(selected_stage_indices, start=1):
            if source_index < 0 or source_index >= len(source.stages):
                raise IndexError("stage index out of range")
            stage = deepcopy(source.stages[source_index])
            stage.id = f"segment_{destination_index}"
            selected.append(stage)
        defaults = deepcopy(source.defaults)
        return ValidationProfile(
            profile_name=str(profile_name or "").strip() or "New Profile",
            profile_type=source.profile_type,
            segment_label_source=None,
            menu_description=source.menu_description,
            menu_group=source.menu_group,
            require_all_stages_runnable=source.require_all_stages_runnable,
            defaults=defaults,
            stages=selected,
        )

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
        profile.stages[index].display_label = normalized[index]
        return normalized

    def set_stage_duration(self, profile: ValidationProfile, index: int, duration_seconds: int) -> int:
        stage = self._stage(profile, index)
        stage.duration_seconds = max(1, int(duration_seconds))
        return stage.duration_seconds

    def set_stage_duration_text(self, profile: ValidationProfile, index: int, value: Any) -> int:
        return self.set_stage_duration(profile, index, parse_profile_duration(value))

    def set_cpu_mode(self, stage: StageConfig, mode: str) -> str:
        stage.modules.cpu.mode = self._normalize_choice(mode, ["normal", "extreme"], "normal")
        return stage.modules.cpu.mode

    def set_cpu_load(self, stage: StageConfig, load: str) -> str:
        stage.modules.cpu.load = self._normalize_choice(load, ["steady", "variable"], "steady")
        return stage.modules.cpu.load

    def set_cpu_priority(self, stage: StageConfig, priority: str) -> str:
        stage.modules.cpu.priority = self._normalize_choice(priority, ["normal", "high"], "normal")
        return stage.modules.cpu.priority

    def set_cpu_dataset(self, stage: StageConfig, dataset: str) -> str:
        stage.modules.cpu.dataset = str(dataset or "large").strip() or "large"
        return stage.modules.cpu.dataset

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
        if normalized != "auto":
            stage.modules.cpu.instruction_intent = ""
        return normalized

    def set_cpu_instruction_intent(self, stage: StageConfig, instruction_intent: str) -> str:
        normalized = self._normalize_choice(
            instruction_intent,
            self.CPU_INSTRUCTION_INTENT_OPTIONS,
            "",
        )
        stage.modules.cpu.instruction_intent = normalized
        if normalized:
            stage.modules.cpu.instruction_set = "auto"
        return normalized

    def set_cpu_backend_preference(self, stage: StageConfig, backend_preference: str) -> str:
        normalized = self._normalize_choice(backend_preference, self.CPU_BACKEND_OPTIONS, "auto")
        stage.modules.cpu.backend_preference = normalized
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

    def guided_allocation_fields(self, stage: StageConfig) -> List[str]:
        """Return the numeric allocations enabled by a guided stage draft."""
        fields: List[str] = []
        if stage.modules.memory.enabled:
            fields.append("memory")
        if stage.modules.vram.enabled:
            fields.append("vram")
        return fields

    def guided_allocation_percent(self, stage: StageConfig, field: str) -> int:
        if field == "memory" and stage.modules.memory.enabled:
            return int(stage.modules.memory.allocation_percent)
        if field == "vram" and stage.modules.vram.enabled:
            return int(stage.modules.vram.allocation_percent)
        raise ValueError(f"Guided allocation field is not enabled: {field}")

    def apply_guided_allocation_percent(self, stage: StageConfig, field: str, value: Any) -> int:
        current = self.guided_allocation_percent(stage, field)
        selected = current if not str(value or "").strip() else self._clamp_int(value, 1, 95, current)
        if field == "memory":
            return self.set_memory_allocation_percent(stage, selected)
        return self.set_vram_allocation_percent(stage, selected)

    def cycle_storage_target_mode(self, stage: StageConfig) -> str:
        storage = stage.modules.storage_benchmark
        modes = (
            "all_internal",
            "selected_target",
            "all_internal_non_root_low_occupancy",
        )
        try:
            index = modes.index(storage.target_mode)
        except ValueError:
            index = -1
        storage.target_mode = modes[(index + 1) % len(modes)]
        if storage.target_mode == "all_internal_non_root_low_occupancy":
            storage.allow_system_drive = False
        return storage.target_mode

    def set_storage_target_path(self, stage: StageConfig, value: str) -> str:
        stage.modules.storage_benchmark.target_path = str(value or "").strip()
        return stage.modules.storage_benchmark.target_path

    def set_storage_test_size_gib(self, stage: StageConfig, value: int) -> int:
        stage.modules.storage_benchmark.test_size_gib = self._clamp_int(value, 1, 8, 1)
        return stage.modules.storage_benchmark.test_size_gib

    def set_storage_runs(self, stage: StageConfig, value: int) -> int:
        stage.modules.storage_benchmark.runs = self._clamp_int(value, 1, 9, 5)
        return stage.modules.storage_benchmark.runs

    def set_storage_max_used_percent(self, stage: StageConfig, value: float) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("Storage Benchmark maximum used percent must be finite")
        stage.modules.storage_benchmark.max_used_percent = max(0.0, min(100.0, parsed))
        return stage.modules.storage_benchmark.max_used_percent

    def toggle_storage_allow_system_drive(self, stage: StageConfig) -> bool:
        storage = stage.modules.storage_benchmark
        if storage.target_mode == "all_internal_non_root_low_occupancy":
            storage.allow_system_drive = False
            return False
        storage.allow_system_drive = not bool(storage.allow_system_drive)
        return storage.allow_system_drive

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
