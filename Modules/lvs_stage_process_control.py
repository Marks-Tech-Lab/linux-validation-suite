from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from Modules.lvs_gpu_worker_plan import GpuWorkerSpec
from Modules.lvs_stage_launch_plan import StageLaunchCommand


@dataclass
class StageProcess:
    kind: str
    command: List[str]
    process: subprocess.Popen
    gpu_spec: Optional[GpuWorkerSpec] = None
    result_path: Optional[str] = None
    stdout_path: Optional[str] = None
    stderr_path: Optional[str] = None


def launch_stage_processes_from_plan(
    planned_commands: Iterable[StageLaunchCommand],
    *,
    stage_id: str,
    worker_logs_dir: Optional[Path] = None,
    command_env: Optional[Dict[str, str]] = None,
    popen_factory: Callable[..., Any] = subprocess.Popen,
) -> List[StageProcess]:
    launches: List[StageProcess] = []
    for launch_index, planned in enumerate(planned_commands, start=1):
        kind = planned.kind
        cmd = planned.command
        try:
            stdout_path = str(worker_logs_dir / f"{stage_id}_{kind}_{launch_index}.stdout.log") if worker_logs_dir else None
            stderr_path = str(worker_logs_dir / f"{stage_id}_{kind}_{launch_index}.stderr.log") if worker_logs_dir else None
            stdout_handle = open(stdout_path, "wb") if stdout_path else subprocess.DEVNULL
            stderr_handle = open(stderr_path, "wb") if stderr_path else subprocess.DEVNULL
            try:
                process = popen_factory(
                    cmd,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    env=command_env,
                )
            finally:
                if stdout_path and hasattr(stdout_handle, "close"):
                    stdout_handle.close()
                if stderr_path and hasattr(stderr_handle, "close"):
                    stderr_handle.close()
            launches.append(
                StageProcess(
                    kind=kind,
                    command=cmd,
                    process=process,
                    gpu_spec=planned.gpu_spec,
                    result_path=planned.result_path,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                )
            )
        except FileNotFoundError:
            print(f"[warn] Missing tool for command: {' '.join(cmd)}")
        except Exception as exc:
            print(f"[warn] Failed to launch {' '.join(cmd)}: {exc}")
    return launches


def stop_processes(processes: Iterable[Any], timeout_seconds: float = 5) -> None:
    process_list = list(processes)
    for proc in process_list:
        try:
            proc.terminate()
        except Exception:
            pass
    for proc in process_list:
        try:
            proc.wait(timeout=timeout_seconds)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def stop_stage_processes(processes: Iterable[StageProcess], timeout_seconds: float = 5) -> None:
    stop_processes([entry.process for entry in processes], timeout_seconds=timeout_seconds)
