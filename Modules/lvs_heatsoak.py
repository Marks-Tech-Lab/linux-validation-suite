#!/usr/bin/env python3
"""Heatsoak orchestration helpers for UI frontends."""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from .lvs_advanced_debug import AdvancedDebugLogger
from .lvs_core import format_duration_hms, now_local_iso
from .lvs_profile_models import (
    ModuleCpu,
    ModuleGpu3D,
    StageConfig,
    StageModules,
    StageNormalization,
)
from .lvs_settings import DEFAULT_STAGE_PROGRESS_INTERVAL_SECONDS


class HeatsoakManager:
    """Builds and runs the unlogged pre-test heatsoak stage."""

    def __init__(self, orchestrator: Any) -> None:
        self.orchestrator = orchestrator

    def build_heatsoak_stage(self, duration_seconds: int) -> StageConfig:
        return StageConfig(
            id="heatsoak",
            name="Combined",
            duration_seconds=max(1, int(duration_seconds)),
            enabled=True,
            modules=StageModules(
                cpu=ModuleCpu(
                    enabled=True,
                    mode="extreme",
                    load="steady",
                    instruction_set="avx",
                    threads="all",
                    priority="high",
                ),
                gpu_3d=ModuleGpu3D(
                    enabled=True,
                    mode="steady",
                    intensity="extreme",
                    gpus="all",
                    backend_preference="auto",
                    compute_variant="stress_hash",
                ),
            ),
            normalization=StageNormalization(0, 0),
        )

    def run_heatsoak_if_requested(
        self,
        minutes: float,
        *,
        advanced_debug: Optional[AdvancedDebugLogger] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> bool:
        minutes = float(minutes or 0.0)
        if minutes <= 0:
            return True
        duration_seconds = max(1, int(round(minutes * 60.0)))
        heatsoak_started_iso = now_local_iso()
        if advanced_debug:
            advanced_debug.capture_heatsoak_start(
                timestamp_iso=heatsoak_started_iso,
                duration_seconds=duration_seconds,
            )
        stage = self.build_heatsoak_stage(duration_seconds)
        runner = self.orchestrator.workload_runner
        diagnostics = runner.stage_diagnostics(stage, "Heatsoak")
        commands = list(diagnostics.get("commands") or [])
        if not commands:
            print("\nHeatsoak requested, but no heatsoak workloads are runnable on this system. Continuing to logged test.")
            if advanced_debug:
                advanced_debug.capture_heatsoak_end(
                    timestamp_iso=now_local_iso(),
                    since_iso=heatsoak_started_iso,
                    verdict="no_runnable_workers",
                )
            return True
        if diagnostics.get("issues"):
            print("\nHeatsoak precheck:")
            for issue in list(diagnostics.get("issues") or [])[:8]:
                print(f"  [warn] {issue}")
            print("Heatsoak will run any launchable CPU/GPU workers and then continue to the logged test.")
        print(
            "\nStarting heatsoak: "
            + f"{format_duration_hms(duration_seconds)} | Power Test (3D Auto + AVX, all CPUs/GPUs)"
        )
        print("Heatsoak is not written to the result folder or compatibility export.")
        stage_processes = runner.launch_stage_processes(stage, result_dir=None)
        if not stage_processes:
            print("No heatsoak processes launched. Continuing to logged test.")
            if advanced_debug:
                advanced_debug.capture_heatsoak_end(
                    timestamp_iso=now_local_iso(),
                    since_iso=heatsoak_started_iso,
                    verdict="no_processes_launched",
                )
            return True
        verdict = "completed"
        start = time.monotonic()
        next_progress = start + min(DEFAULT_STAGE_PROGRESS_INTERVAL_SECONDS, max(1.0, duration_seconds))
        try:
            while True:
                if cancel_check is not None and cancel_check():
                    verdict = "cancelled"
                    print("Heatsoak cancellation requested.")
                    return False
                elapsed = time.monotonic() - start
                if elapsed >= duration_seconds:
                    break
                finished = [entry for entry in stage_processes if entry.process.poll() is not None]
                if finished and len(finished) == len(stage_processes):
                    print("All heatsoak workers exited before the requested duration. Continuing to logged test.")
                    verdict = "workers_exited_early"
                    break
                now = time.monotonic()
                if now >= next_progress:
                    remaining = max(0.0, duration_seconds - elapsed)
                    print(
                        f"[heatsoak] elapsed={format_duration_hms(elapsed)} | remaining={format_duration_hms(remaining)}"
                    )
                    next_progress += DEFAULT_STAGE_PROGRESS_INTERVAL_SECONDS
                time.sleep(1.0)
        except KeyboardInterrupt:
            verdict = "interrupted"
            print("Heatsoak interrupted.")
            return False
        finally:
            runner.stop_stage_processes(stage_processes)
            if advanced_debug:
                advanced_debug.capture_heatsoak_end(
                    timestamp_iso=now_local_iso(),
                    since_iso=heatsoak_started_iso,
                    verdict=verdict,
                )
        print("Heatsoak complete. Starting logged test.")
        return True
