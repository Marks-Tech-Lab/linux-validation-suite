from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from Modules.lvs_external_process_evidence import executable_version, resolve_executable_path
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
    executable_requested: str = ""
    executable_resolved_path: str = ""
    executable_version: str = ""
    started_iso: str = ""
    started_monotonic: Optional[float] = None
    ended_iso: str = ""
    ended_monotonic: Optional[float] = None
    expected_termination: bool = False
    system_memory_plan: Optional[Dict[str, Any]] = None


def launch_stage_processes_from_plan(
    planned_commands: Iterable[StageLaunchCommand],
    *,
    stage_id: str,
    worker_logs_dir: Optional[Path] = None,
    command_env: Optional[Dict[str, str]] = None,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    version_runner: Callable[..., Any] = subprocess.run,
    now_iso: Callable[[], str] = lambda: datetime.now().astimezone().isoformat(),
    monotonic: Callable[[], float] = time.monotonic,
) -> List[StageProcess]:
    launches: List[StageProcess] = []
    for launch_index, planned in enumerate(planned_commands, start=1):
        kind = planned.kind
        cmd = planned.command
        try:
            executable_requested = str(cmd[0]) if cmd else ""
            is_stress_ng = kind in {"cpu", "memory"} and Path(executable_requested).name == "stress-ng"
            executable_resolved_path = (
                resolve_executable_path(executable_requested, command_env=command_env)
                if is_stress_ng
                else ""
            )
            version = (
                executable_version(
                    executable_resolved_path,
                    command_env=command_env,
                    run_command=version_runner,
                )
                if is_stress_ng
                else ""
            )
            stdout_path = str(worker_logs_dir / f"{stage_id}_{kind}_{launch_index}.stdout.log") if worker_logs_dir else None
            stderr_path = str(worker_logs_dir / f"{stage_id}_{kind}_{launch_index}.stderr.log") if worker_logs_dir else None
            stdout_handle = open(stdout_path, "wb") if stdout_path else subprocess.DEVNULL
            stderr_handle = open(stderr_path, "wb") if stderr_path else subprocess.DEVNULL
            try:
                started_iso = now_iso()
                started_monotonic = monotonic()
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
                    executable_requested=executable_requested if is_stress_ng else "",
                    executable_resolved_path=executable_resolved_path,
                    executable_version=version,
                    started_iso=started_iso,
                    started_monotonic=started_monotonic,
                    system_memory_plan=getattr(planned, "system_memory_plan", None),
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


def stop_stage_processes(
    processes: Iterable[StageProcess],
    timeout_seconds: float = 5,
    *,
    now_iso: Callable[[], str] = lambda: datetime.now().astimezone().isoformat(),
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    entries = list(processes)
    for entry in entries:
        try:
            poll = getattr(entry.process, "poll", None)
            if not callable(poll) or poll() is None:
                entry.expected_termination = True
                entry.process.terminate()
        except Exception:
            pass
    for entry in entries:
        try:
            command = list(getattr(entry, "command", []) or [])
            is_stress_ng_memory = (
                getattr(entry, "kind", "") == "memory"
                and bool(command)
                and Path(str(command[0])).name == "stress-ng"
            )
            # Large VM workers can need more than five seconds to unmap memory
            # and print their final --metrics-brief verification record.
            wait_timeout = max(float(timeout_seconds), 30.0) if is_stress_ng_memory else timeout_seconds
            entry.process.wait(timeout=wait_timeout)
        except Exception:
            try:
                entry.process.kill()
                # Reap the child so evidence ingestion sees a durable status.
                entry.process.wait(timeout=max(1.0, float(timeout_seconds)))
            except Exception:
                pass
        finally:
            entry.ended_iso = now_iso()
            entry.ended_monotonic = monotonic()
