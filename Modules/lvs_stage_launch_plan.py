from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from Modules.lvs_gpu_worker_plan import GpuWorkerSpec


@dataclass
class StageLaunchCommand:
    kind: str
    command: List[str]
    gpu_spec: Optional[GpuWorkerSpec] = None
    result_path: Optional[str] = None


def build_stage_launch_commands(
    runner: Any,
    stage: Any,
    cpu_kernel_flavor: str = "",
    worker_results_dir: Optional[Path] = None,
) -> List[StageLaunchCommand]:
    commands: List[StageLaunchCommand] = []
    if not stage.enabled:
        return commands
    if stage.modules.cpu.enabled:
        cpu_result_path = str(worker_results_dir / f"{stage.id}_cpu.json") if worker_results_dir else ""
        cpu_cmd = runner._cpu_command(stage.modules.cpu, cpu_kernel_flavor, cpu_result_path)
        if cpu_cmd:
            commands.append(StageLaunchCommand("cpu", cpu_cmd, None, cpu_result_path or None))
    if stage.modules.memory.enabled:
        mem_result_path = str(worker_results_dir / f"{stage.id}_memory.json") if worker_results_dir else ""
        mem_cmd = runner._memory_command(stage.modules.memory, mem_result_path)
        if mem_cmd:
            commands.append(StageLaunchCommand("memory", mem_cmd, None, mem_result_path or None))
    for worker_index, worker in enumerate(runner._gpu_worker_specs(stage), start=1):
        result_path = str(worker_results_dir / f"{stage.id}_{worker.workload}_{worker_index}.json") if worker_results_dir else None
        materialized = runner._materialize_gpu_worker(worker, result_path)
        commands.append(StageLaunchCommand(materialized.workload, materialized.command, materialized, result_path))
    return commands
