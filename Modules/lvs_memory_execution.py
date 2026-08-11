from __future__ import annotations

from typing import List, Optional

from Modules.lvs_system_memory_budget import system_memory_budget_bytes
from Modules.lvs_python_memory_worker import python_memory_fallback_script


MEMORY_BACKEND_PREFERENCES = ("auto", "native", "stress_ng", "python_fallback")


def normalize_memory_backend_preference(value: str) -> str:
    normalized = str(value or "auto").strip().lower().replace("-", "_") or "auto"
    return normalized if normalized in MEMORY_BACKEND_PREFERENCES else "auto"


def select_memory_backend(
    preference: str,
    *,
    helper_available: bool,
    stress_ng_available: bool,
    python_runtime: str,
) -> str:
    availability = {
        "native": bool(helper_available),
        "stress_ng": bool(stress_ng_available),
        "python_fallback": bool(python_runtime),
    }
    normalized = normalize_memory_backend_preference(preference)
    if normalized != "auto":
        return normalized if availability[normalized] else "none"
    for candidate in ("native", "stress_ng", "python_fallback"):
        if availability[candidate]:
            return candidate
    return "none"


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
    backend_preference: str = "auto",
) -> Optional[List[str]]:
    selected = select_memory_backend(
        backend_preference,
        helper_available=helper_available,
        stress_ng_available=stress_ng_available,
        python_runtime=python_runtime,
    )
    if selected == "native":
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
    if selected == "stress_ng":
        return ["stress-ng", "--vm", "1", "--vm-bytes", str(max(0, int(target_bytes or 0))), "--vm-keep"]
    if selected != "python_fallback":
        return None
    return [python_runtime, "-c", build_memory_fallback_script(target_bytes, result_file)]
