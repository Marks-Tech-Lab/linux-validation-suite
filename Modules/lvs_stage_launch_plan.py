from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from Modules.lvs_gpu_worker_plan import GpuWorkerSpec
from Modules.lvs_system_memory_budget import apply_stage_system_memory_plan


@dataclass
class StageLaunchCommand:
    kind: str
    command: List[str]
    gpu_spec: Optional[GpuWorkerSpec] = None
    result_path: Optional[str] = None
    system_memory_plan: Optional[Dict[str, Any]] = None


def build_stage_launch_commands(
    runner: Any,
    stage: Any,
    cpu_kernel_flavor: str = "",
    worker_results_dir: Optional[Path] = None,
    stage_memory_plan: Optional[Dict[str, Any]] = None,
    resolved_gpu_workers: Optional[List[GpuWorkerSpec]] = None,
) -> List[StageLaunchCommand]:
    commands: List[StageLaunchCommand] = []
    legacy_runner_adapter = False
    if not stage.enabled:
        return commands
    if stage_memory_plan is None or resolved_gpu_workers is None:
        preliminary_gpu_workers = runner._gpu_worker_specs(stage)
        planner = getattr(runner, "_stage_system_memory_plan", None)
        if callable(planner):
            stage_memory_plan = planner(stage, preliminary_gpu_workers)
        else:
            legacy_runner_adapter = True
            stage_memory_plan = {
                "valid": True,
                "resolution_reason": "legacy_runner_adapter",
                "ram_target_bytes": 0,
                "allocations": {},
            }
        gpu_workers = apply_stage_system_memory_plan(preliminary_gpu_workers, stage_memory_plan)
    else:
        gpu_workers = list(resolved_gpu_workers)
    if not stage_memory_plan.get("valid", True):
        return commands
    if stage.modules.cpu.enabled:
        cpu_result_path = str(worker_results_dir / f"{stage.id}_cpu.json") if worker_results_dir else ""
        cpu_cmd = runner._cpu_command(stage.modules.cpu, cpu_kernel_flavor, cpu_result_path)
        if cpu_cmd:
            commands.append(StageLaunchCommand("cpu", cpu_cmd, None, cpu_result_path or None, stage_memory_plan))
    if stage.modules.memory.enabled:
        mem_result_path = str(worker_results_dir / f"{stage.id}_memory.json") if worker_results_dir else ""
        if legacy_runner_adapter:
            mem_cmd = runner._memory_command(stage.modules.memory, mem_result_path)
        else:
            mem_cmd = runner._memory_command(
                stage.modules.memory,
                mem_result_path,
                resolved_target_bytes=int(stage_memory_plan.get("ram_target_bytes") or 0),
            )
        if mem_cmd:
            commands.append(StageLaunchCommand("memory", mem_cmd, None, mem_result_path or None, stage_memory_plan))
    for worker_index, worker in enumerate(gpu_workers, start=1):
        result_path = str(worker_results_dir / f"{stage.id}_{worker.workload}_{worker_index}.json") if worker_results_dir else None
        materialized = runner._materialize_gpu_worker(worker, result_path)
        commands.append(
            StageLaunchCommand(
                materialized.workload,
                materialized.command,
                materialized,
                result_path,
                stage_memory_plan,
            )
        )
    return commands
