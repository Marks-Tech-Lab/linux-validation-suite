#!/usr/bin/env python3
"""Shared stage lifecycle adjunct helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set


@dataclass(frozen=True)
class StageLifecycleState:
    internal_gpu_backends: Set[str] = field(default_factory=set)
    intel_gpu_top_sidecar: Optional[Dict[str, Any]] = None


def stage_targets_intel_gpu(
    stage_plan: Dict[str, Any],
    *,
    gpu_target_by_id: Callable[[str], Optional[Dict[str, Any]]],
) -> bool:
    for target in stage_plan.get("gpu_target_details") or []:
        if str(target.get("vendor") or "").strip().lower() == "intel":
            return True
        if str(target.get("driver") or "").strip().lower() in {"i915", "xe"}:
            return True
    for worker in stage_plan.get("gpu_workers") or []:
        if str(worker.get("slot") or ""):
            target_id = str(worker.get("target_id") or worker.get("slot") or "")
            target = gpu_target_by_id(target_id)
            if target and str(target.get("vendor") or "").strip().lower() == "intel":
                return True
    return False


def start_stage_lifecycle(
    *,
    profile_name: str,
    stage_id: str,
    stage_name: str,
    run_dir: Path,
    stage_plan: Dict[str, Any],
    gpu_backends: Set[str],
    gpu_targets: List[str],
    gpu_target_by_id: Callable[[str], Optional[Dict[str, Any]]],
    write_gpu_safety_marker: Callable[..., None],
    start_intel_gpu_top_sidecar: Callable[..., Optional[Dict[str, Any]]],
) -> StageLifecycleState:
    internal_gpu_backends = set(gpu_backends)
    if internal_gpu_backends:
        write_gpu_safety_marker(
            profile_name=profile_name,
            stage_name=stage_name,
            gpu_backends=sorted(internal_gpu_backends),
            gpu_targets=gpu_targets,
            run_dir=run_dir,
        )
    intel_gpu_top_sidecar = (
        start_intel_gpu_top_sidecar(
            stage_id=stage_id,
            stage_name=stage_name,
            run_dir=run_dir,
        )
        if stage_targets_intel_gpu(stage_plan, gpu_target_by_id=gpu_target_by_id)
        else None
    )
    return StageLifecycleState(
        internal_gpu_backends=internal_gpu_backends,
        intel_gpu_top_sidecar=intel_gpu_top_sidecar,
    )


def stop_stage_lifecycle(
    state: StageLifecycleState,
    *,
    stop_intel_gpu_top_sidecar: Callable[[Optional[Dict[str, Any]]], Optional[Dict[str, Any]]],
    clear_gpu_safety_marker: Callable[[], None],
) -> Optional[Dict[str, Any]]:
    sidecar_summary = stop_intel_gpu_top_sidecar(state.intel_gpu_top_sidecar)
    if state.internal_gpu_backends:
        clear_gpu_safety_marker()
    return sidecar_summary
