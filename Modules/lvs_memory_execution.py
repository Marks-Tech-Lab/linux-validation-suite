from __future__ import annotations

from typing import List, Optional

from Modules.lvs_system_memory_budget import system_memory_budget_bytes
from Modules.lvs_python_memory_worker import python_memory_fallback_script


def memory_worker_count(threads: str, total_cpu_count: int) -> int:
    total = max(1, total_cpu_count or 1)
    normalized = (threads or "all").strip().lower()
    if not normalized or normalized == "all":
        return total
    try:
        requested = int(normalized)
    except Exception:
        return total
    return max(1, min(requested, total))


def memory_target_bytes(allocation_percent: int, total_kb: int, available_kb: int) -> int:
    percent = max(1, min(allocation_percent, 95))
    if total_kb <= 0:
        return 0
    requested_bytes = int(total_kb * 1024 * (percent / 100.0))
    budget = system_memory_budget_bytes(total_kb * 1024, max(0, int(available_kb or 0)) * 1024)["system_memory_budget_bytes"]
    return max(0, min(requested_bytes, budget))


def build_memory_fallback_script(target_bytes: int, result_file: str = "") -> str:
    return python_memory_fallback_script(target_bytes, result_file)


def build_memory_command(
    *,
    helper_available: bool,
    helper_path: str,
    target_bytes: int,
    worker_count: int,
    allocation_percent: int,
    stress_ng_available: bool,
    python_runtime: str,
    result_file: str = "",
) -> Optional[List[str]]:
    if helper_available:
        cmd = [
            helper_path,
            "--bytes",
            str(target_bytes),
            "--threads",
            str(worker_count),
        ]
        if result_file:
            cmd.extend(["--result-file", result_file])
        return cmd
    if stress_ng_available:
        return ["stress-ng", "--vm", "1", "--vm-bytes", str(max(0, int(target_bytes or 0))), "--vm-keep"]
    if not python_runtime:
        return None
    return [python_runtime, "-c", build_memory_fallback_script(target_bytes, result_file)]
