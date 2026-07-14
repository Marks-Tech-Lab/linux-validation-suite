#!/usr/bin/env python3
"""Shared run lifecycle data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class StageWindow:
    stage_id: str
    stage_type: str
    display_name: str
    started_iso: str
    ended_iso: str
    started_monotonic: float
    ended_monotonic: float
    duration_seconds: float
    trim_start_seconds: int
    trim_end_seconds: int
    cpu_backend: str = ""
    cpu_mode_requested: str = ""
    cpu_mode_resolved: str = ""
    cpu_kernel_flavor: str = ""
    cpu_tuning_policy: str = ""
    cpu_tuned_avg_power_w: Optional[float] = None
    gpu_3d_backend_preference: str = ""
    gpu_3d_backend_resolved: str = ""
    vram_backend_preference: str = ""
    vram_backend_resolved: str = ""
    gpu_target_mode: str = ""
    gpu_targets: List[str] = field(default_factory=list)
    gpu_workers_initial: List[Dict[str, Any]] = field(default_factory=list)
    gpu_workers_final: List[Dict[str, Any]] = field(default_factory=list)
    gpu_retune_events: List[Dict[str, Any]] = field(default_factory=list)
    verdict: str = "pass"
    failure_reasons: List[str] = field(default_factory=list)
    error_events: List[Dict[str, Any]] = field(default_factory=list)
    system_faults: List[Dict[str, Any]] = field(default_factory=list)
    worker_results: List[Dict[str, Any]] = field(default_factory=list)
    intel_gpu_top_sidecar: Optional[Dict[str, Any]] = None
    strict_threshold_recommendation_warnings: Optional[bool] = None

    @property
    def analysis_start(self) -> float:
        return self.started_monotonic + self.trim_start_seconds

    @property
    def analysis_end(self) -> float:
        return max(self.analysis_start, self.ended_monotonic - self.trim_end_seconds)
