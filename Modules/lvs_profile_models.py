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
class StageModules:
    cpu: ModuleCpu = field(default_factory=ModuleCpu)
    memory: ModuleMemory = field(default_factory=ModuleMemory)
    gpu_3d: ModuleGpu3D = field(default_factory=ModuleGpu3D)
    vram: ModuleVram = field(default_factory=ModuleVram)


@dataclass
class StageConfig:
    id: str
    name: str
    duration_seconds: int
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
