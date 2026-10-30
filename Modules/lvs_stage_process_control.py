from __future__ import annotations

import subprocess
import time
import json
import math
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from Modules.lvs_external_process_evidence import executable_version, resolve_executable_path
from Modules.lvs_gpu_worker_plan import GpuWorkerSpec, gpu_allocation_environment
from Modules.lvs_stage_launch_plan import StageLaunchCommand
from Modules.lvs_native_binary_provenance import begin_native_executable, observe_process_executable


PYTHON_CPU_FALLBACK_SHUTDOWN_TIMEOUT_SECONDS = 10.0
NATIVE_MEMORY_SHUTDOWN_BASE_SECONDS = 10.0
NATIVE_MEMORY_SHUTDOWN_SECONDS_PER_GIB = 0.25
NATIVE_MEMORY_SHUTDOWN_MAX_SECONDS = 120.0
VULKAN_COMPUTE_CLEANUP_SECONDS = 5.0
VULKAN_COMPUTE_FALLBACK_SECONDS = 15.0
VULKAN_COMPUTE_SHUTDOWN_MAX_SECONDS = 60.0
VULKAN_RESULT_MAX_BYTES = 2 * 1024 * 1024


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
    termination_requested_iso: str = ""
    shutdown_timeout_seconds: Optional[float] = None
    shutdown_timed_out: bool = False
    forced_kill: bool = False
    shutdown_error: str = ""
    system_memory_plan: Optional[Dict[str, Any]] = None
    native_executable_provenance: Optional[Dict[str, Any]] = None
    native_executable_path: str = ""
    termination_requested_monotonic: Optional[float] = None
    shutdown_evidence: Optional[Dict[str, Any]] = None


def _command_option_int(command: List[str], option: str) -> int:
    try:
        index = command.index(option)
        return max(0, int(command[index + 1]))
    except (ValueError, IndexError, TypeError):
        return 0


def is_native_memory_worker(entry: StageProcess) -> bool:
    command = list(getattr(entry, "command", []) or [])
    executable = Path(str(command[0])).name if command else ""
    return getattr(entry, "kind", "") == "memory" and executable.startswith("memory_stress_helper")


def native_memory_shutdown_timeout_seconds(entry: StageProcess, default_seconds: float = 5.0) -> float:
    """Return a bounded cleanup grace scaled to the native mapping size."""
    command = list(getattr(entry, "command", []) or [])
    allocation_bytes = _command_option_int(command, "--bytes")
    plan = getattr(entry, "system_memory_plan", None)
    if isinstance(plan, dict):
        for key in ("assigned_target_bytes", "target_bytes", "requested_bytes"):
            try:
                allocation_bytes = max(allocation_bytes, int(plan.get(key) or 0))
            except (TypeError, ValueError):
                continue
    allocation_gib = allocation_bytes / float(1024 ** 3)
    scaled = NATIVE_MEMORY_SHUTDOWN_BASE_SECONDS + allocation_gib * NATIVE_MEMORY_SHUTDOWN_SECONDS_PER_GIB
    return min(
        NATIVE_MEMORY_SHUTDOWN_MAX_SECONDS,
        max(float(default_seconds), scaled),
    )


def is_vulkan_compute_worker(entry: StageProcess) -> bool:
    spec = getattr(entry, "gpu_spec", None)
    script = Path(__file__).resolve().parents[1] / "native/vulkan_compute_worker.py"
    return (getattr(entry, "kind", "") in {"gpu", "gpu_3d", "vram"}
            and getattr(spec, "backend", "") == "python_vulkan_compute"
            and any(Path(str(arg)).name == "vulkan_compute_worker.py" and Path(str(arg)).resolve() == script
                    for arg in entry.command))


def vulkan_compute_shutdown_policy(entry: StageProcess, now: float) -> Dict[str, Any]:
    """Read bounded current-process evidence; observation cannot authorize success."""
    spec = entry.gpu_spec
    evidence = dict(contract_id="linux_validation_suite.vulkan_compute_shutdown", contract_version=1,
        kind="vulkan_compute_shutdown",
        worker_pid=getattr(entry.process, "pid", None), worker_role=entry.kind,
        backend="python_vulkan_compute", target_id=spec.target_id, physical_gpu_id=spec.physical_gpu_id,
        target_pci_slot=spec.slot, timing_evidence_source="current_process_worker_result",
        observed_cycle_max_seconds=None, timing_evidence_status="rejected",
        compute_allowance_seconds=VULKAN_COMPUTE_FALLBACK_SECONDS - VULKAN_COMPUTE_CLEANUP_SECONDS,
        cleanup_allowance_seconds=VULKAN_COMPUTE_CLEANUP_SECONDS,
        total_allowance_seconds=VULKAN_COMPUTE_FALLBACK_SECONDS,
        maximum_allowance_seconds=VULKAN_COMPUTE_SHUTDOWN_MAX_SECONDS,
        post_kill_reap_allowance_seconds=5.0,
        reason="fallback_unavailable_result", signal_sent=False)
    def number(value):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("invalid_timing")
        return float(value)
    try:
        path = Path(entry.result_path or "")
        command_path = Path(entry.command[entry.command.index("--result-file") + 1])
        if not entry.result_path or path.resolve() != command_path.resolve():
            raise ValueError("result_destination_mismatch")
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > VULKAN_RESULT_MAX_BYTES:
                raise ValueError("invalid_result_file")
            raw = handle.read(VULKAN_RESULT_MAX_BYTES + 1)
        if len(raw) > VULKAN_RESULT_MAX_BYTES:
            raise ValueError("oversized_result")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("malformed_result")
        if (type(evidence["worker_pid"]) is not int or evidence["worker_pid"] <= 0
                or not spec.target_id or not spec.physical_gpu_id
                or type(payload.get("worker_pid")) is not int or payload["worker_pid"] != evidence["worker_pid"]
                or payload.get("backend") != "python_vulkan_compute"
                or payload.get("target_id") != spec.target_id
                or payload.get("physical_gpu_id") != spec.physical_gpu_id
                or payload.get("target_slot", "") != spec.slot
                or payload.get("hardware_device_verified") is not True
                or not isinstance(payload.get("physical_identity_evidence"), dict)
                or payload["physical_identity_evidence"].get("contract_id") != "linux_validation_suite.vulkan_physical_identity"
                or payload["physical_identity_evidence"].get("contract_version") != 1
                or payload["physical_identity_evidence"].get("status") != "verified"):
            raise ValueError("process_or_identity_mismatch")
        if Path(payload.get("worker_result_file", "")).resolve() != path.resolve():
            raise ValueError("result_destination_mismatch")
        published = number(payload.get("last_result_write_started_monotonic_seconds"))
        launched = number(entry.started_monotonic)
        if not launched <= published <= now:
            raise ValueError("publication_outside_process_lifetime")
        cycle = number(payload.get("cycle_latency_max_seconds"))
        last = number(payload.get("cycle_latency_last_seconds"))
        elapsed = number(payload.get("cycle_elapsed_seconds"))
        if (type(payload.get("cycle_count")) is not int or payload["cycle_count"] < 1
                or last > cycle or cycle > elapsed + .001 or elapsed > now - launched + .001):
            raise ValueError("contradictory_cycle_timing")
        if cycle > VULKAN_COMPUTE_SHUTDOWN_MAX_SECONDS:
            raise ValueError("excessive_cycle_timing")
        age = now - published
        maximum_age = min(VULKAN_COMPUTE_SHUTDOWN_MAX_SECONDS,
                          max(5.0, 2 * cycle + VULKAN_COMPUTE_CLEANUP_SECONDS))
        if age > maximum_age:
            raise ValueError("stale_publication")
        total = min(VULKAN_COMPUTE_SHUTDOWN_MAX_SECONDS, 2 * cycle + VULKAN_COMPUTE_CLEANUP_SECONDS)
        evidence.update(observed_cycle_max_seconds=cycle, timing_evidence_status="accepted",
            observed_cycle_count=payload["cycle_count"], requested_compute_allowance_seconds=2 * cycle,
            publication_age_seconds=age, maximum_publication_age_seconds=maximum_age,
            publication_monotonic_seconds=published,
            compute_allowance_seconds=total - VULKAN_COMPUTE_CLEANUP_SECONDS,
            total_allowance_seconds=total,
            reason="capped_observed_cycle_timing" if total < 2 * cycle + VULKAN_COMPUTE_CLEANUP_SECONDS
                   else "observed_cycle_timing")
    except (OSError, ValueError, TypeError, IndexError, OverflowError) as exc:
        # Reasons are bounded policy labels, never raw file contents or paths.
        reason = str(exc) if type(exc) is ValueError else "unavailable_or_malformed_result"
        allowed = {"invalid_timing", "result_destination_mismatch", "invalid_result_file", "oversized_result",
                   "malformed_result", "process_or_identity_mismatch", "publication_outside_process_lifetime",
                   "contradictory_cycle_timing", "excessive_cycle_timing", "stale_publication"}
        evidence["reason"] = "fallback_" + (reason if reason in allowed else "unavailable_or_malformed_result")
    return evidence


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
            family = getattr(planned, "native_helper_family", "")
            if not family and kind in {"cpu", "memory"} and Path(executable_requested).name.startswith(
                    "cpu_stress_helper" if kind == "cpu" else "memory_stress_helper"):
                family = kind
            native_path, native_evidence = (begin_native_executable(cmd, family, command_env)
                                             if family in {"cpu", "memory"} else ("", None))
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
                    env=gpu_allocation_environment(command_env, planned.gpu_spec) if planned.gpu_spec is not None else command_env,
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
                    native_executable_provenance=native_evidence,
                    native_executable_path=native_path,
                )
            )
            if native_evidence is not None:
                observe_process_executable(native_evidence, process)
        except (KeyboardInterrupt, SystemExit):
            # The new optional observation must not enlarge an unowned-child
            # window: register first, then preserve cancellation and cleanup.
            stop_stage_processes(launches)
            raise
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

    def observe_exit(entry, code):
        evidence = entry.shutdown_evidence
        if evidence is not None and code is not None and "exit_observed_monotonic" not in evidence:
            evidence.update(exit_observed_monotonic=monotonic(), exit_observed_iso=now_iso(), exit_code=code)

    def kill_vulkan(entry, message):
        evidence = entry.shutdown_evidence
        if entry.shutdown_timed_out:
            return
        code = entry.process.poll()
        if code is not None:
            observe_exit(entry, code)
            return
        entry.shutdown_timed_out = True
        entry.shutdown_error = message
        evidence.update(kill_requested_monotonic=monotonic(), kill_requested_iso=now_iso())
        try:
            entry.process.kill()
            entry.forced_kill = True
        except Exception as exc:
            evidence["kill_error"] = type(exc).__name__

    def expire_vulkan_deadlines():
        for other in entries:
            evidence = getattr(other, "shutdown_evidence", None)
            if evidence is None or evidence.get("deadline_monotonic") is None:
                continue
            code = other.process.poll()
            if code is not None:
                observe_exit(other, code)
            elif monotonic() >= evidence["deadline_monotonic"]:
                kill_vulkan(other, "Vulkan compute shutdown deadline expired")

    def wait_with_deadlines(entry, deadline):
        # Break a legacy worker's wait only to enforce another Vulkan worker's
        # absolute deadline. The legacy worker retains its original wait budget.
        while True:
            expire_vulkan_deadlines()
            if entry.shutdown_evidence is not None and entry.shutdown_timed_out:
                return
            now = monotonic()
            pending = [other.shutdown_evidence["deadline_monotonic"] for other in entries
                       if other.shutdown_evidence is not None and not other.shutdown_timed_out
                       and other.shutdown_evidence.get("deadline_monotonic") is not None
                       and other.process.poll() is None]
            remaining = max(0.0, deadline - now)
            interval = min(remaining, max(0.0, min(pending) - now)) if pending else remaining
            try:
                entry.process.wait(timeout=interval)
                observe_exit(entry, entry.process.poll())
                return
            except subprocess.TimeoutExpired:
                if monotonic() >= deadline:
                    raise

    for entry in entries:
        try:
            if is_vulkan_compute_worker(entry) and entry.shutdown_evidence is None:
                entry.shutdown_evidence = vulkan_compute_shutdown_policy(entry, monotonic())
            poll = getattr(entry.process, "poll", None)
            if not callable(poll) or poll() is None:
                if entry.shutdown_evidence is not None and entry.termination_requested_monotonic is not None:
                    continue  # repeated stop calls never renew a Vulkan deadline
                entry.expected_termination = True
                entry.termination_requested_iso = now_iso()
                if entry.shutdown_evidence is not None:
                    requested = monotonic()
                    entry.termination_requested_monotonic = requested
                    evidence = entry.shutdown_evidence
                    evidence.update(termination_requested_iso=entry.termination_requested_iso,
                        termination_requested_monotonic=requested,
                        deadline_monotonic=requested + evidence["total_allowance_seconds"])
                    try:
                        evidence["deadline_iso"] = (datetime.fromisoformat(entry.termination_requested_iso)
                            + timedelta(seconds=evidence["total_allowance_seconds"])).isoformat()
                    except (ValueError, TypeError):
                        evidence["deadline_iso"] = None  # monotonic deadline remains authoritative
                entry.process.terminate()
                if entry.shutdown_evidence is not None:
                    entry.shutdown_evidence["signal_sent"] = True
        except Exception as exc:
            if entry.shutdown_evidence is not None:
                entry.shutdown_evidence["signal_error"] = type(exc).__name__
    for entry in entries:
        try:
            command = list(getattr(entry, "command", []) or [])
            is_stress_ng_memory = (
                getattr(entry, "kind", "") == "memory"
                and bool(command)
                and Path(str(command[0])).name == "stress-ng"
            )
            is_python_cpu_fallback = (
                getattr(entry, "kind", "") == "cpu"
                and "-m" in command
                and "Modules.lvs_python_cpu_worker" in command
            )
            # Large VM workers can need more than five seconds to unmap memory
            # and print their final --metrics-brief verification record.
            if entry.shutdown_evidence is not None:
                wait_timeout = entry.shutdown_evidence["total_allowance_seconds"]
            elif is_stress_ng_memory:
                wait_timeout = max(float(timeout_seconds), 30.0)
            elif is_native_memory_worker(entry):
                # Releasing a multi-hundred-GiB mapping can take materially
                # longer than stopping its verification threads. Scale the
                # grace period with the actual allocation, but keep a firm cap
                # so orchestration remains responsive on a wedged worker.
                wait_timeout = native_memory_shutdown_timeout_seconds(entry, timeout_seconds)
            elif is_python_cpu_fallback:
                # The supervisor must stop its multiprocessing children, drain
                # their evidence, and persist the required result before exit.
                wait_timeout = max(
                    float(timeout_seconds),
                    PYTHON_CPU_FALLBACK_SHUTDOWN_TIMEOUT_SECONDS,
                )
            else:
                wait_timeout = timeout_seconds
            entry.shutdown_timeout_seconds = float(wait_timeout)
            if any(other.shutdown_evidence is not None for other in entries):
                now = monotonic()
                evidence = entry.shutdown_evidence
                deadline = evidence.get("deadline_monotonic", now) if evidence is not None else now + wait_timeout
                if evidence is not None:
                    evidence.update(wait_started_monotonic=now, wait_budget_seconds=max(0.0, deadline - now))
                wait_with_deadlines(entry, deadline)
                if entry.shutdown_timed_out and evidence is not None and not evidence.get("reap_attempted"):
                    evidence["reap_attempted"] = True
                    entry.process.wait(timeout=5.0)
            else:
                entry.process.wait(timeout=wait_timeout)
        except Exception as exc:
            if entry.shutdown_evidence is not None:
                kill_vulkan(entry, str(exc))
                if not entry.shutdown_evidence.get("reap_attempted"):
                    entry.shutdown_evidence["reap_attempted"] = True
                    try:
                        entry.process.wait(timeout=5.0)
                    except Exception as reap_error:
                        entry.shutdown_evidence["reap_error"] = type(reap_error).__name__
                else:
                    entry.shutdown_evidence["reap_error"] = type(exc).__name__
            else:
                entry.shutdown_timed_out = True
                entry.shutdown_error = str(exc)
                try:
                    entry.process.kill()
                    entry.forced_kill = True
                    # Reap the child so evidence ingestion sees a durable status.
                    entry.process.wait(timeout=max(1.0, float(timeout_seconds)))
                except Exception:
                    pass
        finally:
            entry.ended_iso = now_iso()
            entry.ended_monotonic = monotonic()
            if entry.shutdown_evidence is not None:
                code = entry.process.poll()
                observe_exit(entry, code)
                entry.shutdown_evidence.update(wait_ended_monotonic=entry.ended_monotonic,
                    shutdown_timed_out=entry.shutdown_timed_out, forced_kill=entry.forced_kill,
                    exit_code=code, outcome="forced_kill" if entry.forced_kill else "timeout" if entry.shutdown_timed_out
                    else "normal_exit" if code == 0 else "nonzero_exit" if code is not None else "exit_unconfirmed")
