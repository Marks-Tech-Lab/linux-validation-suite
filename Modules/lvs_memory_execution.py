from __future__ import annotations

from typing import List, Optional


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
    effective_available_kb = available_kb or total_kb
    if total_kb <= 0:
        return 512 * 1024 * 1024
    target_kb = int(min(total_kb * (percent / 100.0), effective_available_kb * 0.85))
    return max(128 * 1024 * 1024, target_kb * 1024)


def build_memory_fallback_script(allocation_percent: int) -> str:
    percent = max(1, min(allocation_percent, 95))
    return "\n".join(
        [
            "import signal",
            "import time",
            "buffers = []",
            "def read_meminfo_kb(key):",
            "    try:",
            "        with open('/proc/meminfo', 'r', encoding='utf-8', errors='ignore') as handle:",
            "            for line in handle:",
            "                if line.startswith(key + ':'):",
            "                    return int(line.split(':', 1)[1].strip().split()[0])",
            "    except Exception:",
            "        return 0",
            "    return 0",
            "def stop(*_):",
            "    raise SystemExit(0)",
            "signal.signal(signal.SIGTERM, stop)",
            "signal.signal(signal.SIGINT, stop)",
            "total_kb = read_meminfo_kb('MemTotal')",
            "available_kb = read_meminfo_kb('MemAvailable') or total_kb",
            f"target_kb = int(min(total_kb * ({percent} / 100.0), available_kb * 0.85))",
            "chunk_kb = 256 * 1024",
            "page_size = 4096",
            "remaining_kb = max(0, target_kb)",
            "while remaining_kb > 0:",
            "    size_kb = min(chunk_kb, remaining_kb)",
            "    try:",
            "        block = bytearray(size_kb * 1024)",
            "    except MemoryError:",
            "        break",
            "    for idx in range(0, len(block), page_size):",
            "        block[idx] = 1",
            "    buffers.append(block)",
            "    remaining_kb -= size_kb",
            "while True:",
            "    time.sleep(1)",
        ]
    )


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
        return ["stress-ng", "--vm", "1", "--vm-bytes", f"{allocation_percent}%", "--vm-keep"]
    if not python_runtime:
        return None
    return [python_runtime, "-c", build_memory_fallback_script(allocation_percent)]
