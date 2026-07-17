#!/usr/bin/env python3
"""Profile and stage models shared by CLI, service, TUI, and future GUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .lvs_settings import (
    DEFAULT_SAMPLE_INTERVAL_SECONDS,
    DEFAULT_TRIM_END_SECONDS,
    DEFAULT_TRIM_START_SECONDS,
)


@dataclass
class StageNormalization:
    trim_start_seconds: int = DEFAULT_TRIM_START_SECONDS
    trim_end_seconds: int = DEFAULT_TRIM_END_SECONDS


@dataclass
class ModuleCpu:
    enabled: bool = False
    mode: str = "normal"
    load: str = "steady"
    instruction_set: str = "auto"
    threads: str = "all"
    priority: str = "normal"
    dataset: str = "large"


@dataclass
class ModuleMemory:
    enabled: bool = False
    allocation_percent: int = 80
    instruction_set: str = "auto"
    priority: str = "normal"
    threads: str = "all"


@dataclass
class ModuleGpu3D:
    enabled: bool = False
    mode: str = "steady"
    intensity: str = "extreme"
    gpus: str = "all"
    allocation_percent: int = 0
    priority: str = "normal"
    backend_preference: str = "auto"
    compute_variant: str = "stress_hash"


@dataclass
class ModuleVram:
    enabled: bool = False
    allocation_percent: int = 80
    gpus: str = "all"
    priority: str = "normal"
    backend_preference: str = "auto"


@dataclass
class ModuleStorageBenchmark:
    enabled: bool = False
    profile_id: str = "storage_kdiskmark_cdm_style_v1"
    target_mode: str = "all_internal"
    target_path: str = ""
    drive_execution: str = "sequential"
    test_size_gib: int = 1
    runs: int = 5
    allow_system_drive: bool = False


@dataclass
class StageModules:
    cpu: ModuleCpu = field(default_factory=ModuleCpu)
    memory: ModuleMemory = field(default_factory=ModuleMemory)
    gpu_3d: ModuleGpu3D = field(default_factory=ModuleGpu3D)
    vram: ModuleVram = field(default_factory=ModuleVram)
    storage_benchmark: ModuleStorageBenchmark = field(default_factory=ModuleStorageBenchmark)


@dataclass
class StageConfig:
    id: str
    name: str
    duration_seconds: Optional[int]
    enabled: bool = True
    modules: StageModules = field(default_factory=StageModules)
    normalization: StageNormalization = field(default_factory=StageNormalization)
    strict_threshold_recommendation_warnings: Optional[bool] = None


@dataclass
class ProfileDefaults:
    telemetry_interval_seconds: float = DEFAULT_SAMPLE_INTERVAL_SECONDS
    trim_start_seconds: int = DEFAULT_TRIM_START_SECONDS
    trim_end_seconds: int = DEFAULT_TRIM_END_SECONDS
    strict_threshold_recommendation_warnings: Optional[bool] = None


@dataclass
class ValidationProfile:
    profile_name: str
    profile_type: str = "validation_schedule"
    segment_label_source: Optional[str] = None
    menu_description: str = ""
    menu_group: str = "custom"
    defaults: ProfileDefaults = field(default_factory=ProfileDefaults)
    stages: List[StageConfig] = field(default_factory=list)


def timed_module_names(stage: StageConfig) -> List[str]:
    names: List[str] = []
    modules = getattr(stage, "modules", None)
    if modules is None:
        return names
    for name in ("cpu", "memory", "gpu_3d", "vram"):
        module = getattr(modules, name, None)
        if bool(module and getattr(module, "enabled", False)):
            names.append(name)
    return names


def completion_module_names(stage: StageConfig) -> List[str]:
    storage = getattr(getattr(stage, "modules", None), "storage_benchmark", None)
    return ["storage_benchmark"] if bool(storage and getattr(storage, "enabled", False)) else []


def stage_execution_mode(stage: StageConfig) -> str:
    timed = timed_module_names(stage)
    completion = completion_module_names(stage)
    if completion and not timed:
        return "completion"
    if timed and not completion:
        return "duration"
    if timed and completion:
        return "mixed"
    if getattr(stage, "modules", None) is None:
        return "duration"
    return "empty"
