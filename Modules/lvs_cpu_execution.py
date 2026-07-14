from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional


CPU_MODE_OPTIONS = ("scalar", "sse", "avx", "avx2", "avx512")
CPU_KERNEL_MODE_MAP = {
    "scalar": "scalar",
    "sse2": "sse",
    "sse2_int": "sse",
    "avx": "avx",
    "avx_fma": "avx",
    "avx2": "avx2",
    "avx2_fma": "avx2",
    "avx512_fma": "avx512",
    "avx512_int": "avx512",
}
CPU_KERNEL_FAMILY_CANDIDATES = {
    "scalar": ["scalar"],
    "sse": ["sse2", "sse2_int"],
    "avx": ["avx_fma", "avx"],
    "avx2": ["avx2_fma", "avx2"],
    "avx512": ["avx512_fma", "avx512_int"],
}
CPU_KERNEL_MAX_POWER_ORDER = [
    "avx512_fma",
    "avx512_int",
    "avx2_fma",
    "avx2",
    "avx_fma",
    "avx",
    "sse2",
    "sse2_int",
    "scalar",
]


def normalize_cpu_helper_mode(requested_mode: str) -> str:
    mode = (requested_mode or "auto").strip().lower()
    if mode in CPU_MODE_OPTIONS:
        return mode
    return "auto"


def normalize_cpu_probe_mode(requested_mode: str) -> str:
    return (requested_mode or "auto").strip().lower() or "auto"


def build_cpu_resolved_mode_probe_command(helper_path: str, requested_mode: str) -> List[str]:
    return [helper_path, "--mode", normalize_cpu_probe_mode(requested_mode), "--print-resolved-mode"]


def build_cpu_default_kernel_probe_command(helper_path: str, requested_mode: str) -> List[str]:
    return [helper_path, "--mode", normalize_cpu_probe_mode(requested_mode), "--print-kernel-flavor"]


def build_cpu_kernel_support_probe_command(helper_path: str, kernel_flavor: str) -> List[str]:
    normalized = (kernel_flavor or "").strip().lower()
    return [helper_path, "--kernel-flavor", normalized, "--print-kernel-flavor"]


def parse_cpu_resolved_mode_probe(return_code: int, stdout: str) -> str:
    if return_code != 0:
        return ""
    resolved = (stdout or "").strip().lower()
    if resolved not in CPU_MODE_OPTIONS:
        return ""
    return resolved


def parse_cpu_default_kernel_probe(return_code: int, stdout: str) -> str:
    if return_code != 0:
        return ""
    flavor = (stdout or "").strip().lower()
    if flavor not in CPU_KERNEL_MODE_MAP:
        return ""
    return flavor


def cpu_kernel_support_probe_matches(return_code: int, stdout: str, kernel_flavor: str) -> bool:
    normalized = (kernel_flavor or "").strip().lower()
    return bool(normalized) and return_code == 0 and (stdout or "").strip().lower() == normalized


def cpu_mode_for_kernel_flavor(flavor: str) -> str:
    return CPU_KERNEL_MODE_MAP.get((flavor or "").strip().lower(), "scalar")


def cpu_tuning_policy(requested_mode: str, cpu_power_available: bool) -> str:
    if (requested_mode or "auto").strip().lower() != "auto":
        return "family_locked"
    if cpu_power_available:
        return "max_power"
    return "highest_supported"


def cpu_power_tuning_available(
    *,
    telemetry_collector_factory: Callable[..., Any],
    interval_seconds: float,
    runtime_environment: Dict[str, str],
    privileged_helper_enabled: bool,
) -> bool:
    capabilities = telemetry_collector_factory(
        interval_seconds=interval_seconds,
        runtime_environment=runtime_environment,
        privileged_helper_enabled=privileged_helper_enabled,
    ).detect_capabilities()
    return bool(capabilities.get("cpu_power_w", {}).get("available"))


def cpu_candidate_kernel_flavors(
    *,
    helper_available: bool,
    policy: str,
    resolved_mode: str,
    supports_kernel_flavor: Callable[[str], bool],
) -> List[str]:
    if not helper_available:
        return []
    if policy == "max_power":
        ordered = CPU_KERNEL_MAX_POWER_ORDER
    else:
        ordered = CPU_KERNEL_FAMILY_CANDIDATES.get((resolved_mode or "scalar").strip().lower(), ["scalar"])
    return [flavor for flavor in ordered if supports_kernel_flavor(flavor)]


def build_cpu_execution_base(
    *,
    backend: str,
    requested_mode: str,
    resolved_mode: str,
    kernel_flavor: str,
    tuning_policy: str,
    candidate_kernel_flavors: List[str],
) -> Dict[str, Any]:
    return {
        "backend": backend,
        "requested_mode": requested_mode,
        "resolved_mode": resolved_mode,
        "kernel_flavor": kernel_flavor,
        "tuning_policy": tuning_policy,
        "candidate_kernel_flavors": list(candidate_kernel_flavors),
        "tuned": False,
        "tuned_avg_power_w": None,
        "candidate_results": [],
    }


def best_valid_cpu_tuning_candidate(candidate_results: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    best: Optional[Dict[str, Any]] = None
    best_avg: Optional[float] = None
    for result in candidate_results:
        if not result.get("valid"):
            continue
        avg_power = result.get("avg_cpu_power_w")
        if avg_power is None:
            continue
        if best_avg is None or avg_power > best_avg:
            best = result
            best_avg = avg_power
    return best


def apply_single_cpu_kernel_candidate(execution: Dict[str, Any], kernel_flavor: str) -> Dict[str, Any]:
    return {
        **execution,
        "kernel_flavor": kernel_flavor,
        "resolved_mode": cpu_mode_for_kernel_flavor(kernel_flavor),
    }


def apply_tuned_cpu_kernel_candidate(
    execution: Dict[str, Any],
    best: Dict[str, Any],
    candidate_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        **execution,
        "resolved_mode": cpu_mode_for_kernel_flavor(best["kernel_flavor"]),
        "kernel_flavor": best["kernel_flavor"],
        "tuned": True,
        "tuned_avg_power_w": best.get("avg_cpu_power_w"),
        "candidate_results": candidate_results,
    }


def resolve_cpu_execution_policy(
    *,
    backend: str,
    requested_mode: str,
    resolved_mode: str,
    kernel_flavor: str,
    tuning_policy: str,
    candidate_kernel_flavors: List[str],
    tune_max_power: bool,
    worker_count: Callable[[], int],
    power_tuning_available: Callable[[], bool],
    benchmark_candidate: Callable[[str], Dict[str, Any]],
    tuning_cache: Dict[Any, Dict[str, Any]],
) -> Dict[str, Any]:
    candidates = list(candidate_kernel_flavors)
    execution = build_cpu_execution_base(
        backend=backend,
        requested_mode=requested_mode,
        resolved_mode=resolved_mode,
        kernel_flavor=kernel_flavor,
        tuning_policy=tuning_policy,
        candidate_kernel_flavors=candidates,
    )
    if backend != "cpu_native_helper" or not tune_max_power or not candidates:
        return execution
    if not power_tuning_available():
        return execution

    cache_key = (requested_mode, resolved_mode, worker_count(), tuning_policy)
    cached = tuning_cache.get(cache_key)
    if cached is not None:
        return dict(cached)

    if len(candidates) == 1:
        single = apply_single_cpu_kernel_candidate(execution, candidates[0])
        tuning_cache[cache_key] = dict(single)
        return single

    candidate_results = [benchmark_candidate(flavor) for flavor in candidates]
    best = best_valid_cpu_tuning_candidate(candidate_results)
    if best is None:
        resolved = dict(execution)
        resolved["candidate_results"] = candidate_results
        tuning_cache[cache_key] = dict(resolved)
        return resolved

    tuned = apply_tuned_cpu_kernel_candidate(execution, best, candidate_results)
    tuning_cache[cache_key] = dict(tuned)
    return tuned


def cpu_fallback_params(instruction_set: str, mode: str) -> Dict[str, Any]:
    normalized_instruction_set = (instruction_set or "auto").strip().lower()
    normalized_mode = (mode or "normal").strip().lower()
    if normalized_instruction_set == "sse":
        return {"algorithm": "sha256", "iterations": 25000, "payload_bytes": 512 * 1024}
    if normalized_instruction_set in {"avx", "avx2"}:
        return {"algorithm": "sha512", "iterations": 120000, "payload_bytes": 2 * 1024 * 1024}
    if normalized_instruction_set == "avx512" or normalized_mode == "extreme":
        return {"algorithm": "sha512", "iterations": 180000, "payload_bytes": 4 * 1024 * 1024}
    return {"algorithm": "sha512", "iterations": 60000, "payload_bytes": 1024 * 1024}


def build_cpu_fallback_script(instruction_set: str, mode: str, worker_count: int) -> str:
    params = cpu_fallback_params(instruction_set, mode)
    return "\n".join(
        [
            "import hashlib",
            "import multiprocessing as mp",
            "import os",
            "import signal",
            "import time",
            "workers = []",
            f"ALGORITHM = {params['algorithm']!r}",
            f"ITERATIONS = {params['iterations']}",
            f"PAYLOAD_BYTES = {params['payload_bytes']}",
            "def worker(worker_index):",
            "    try:",
            "        if hasattr(os, 'sched_setaffinity'):",
            "            cpu_total = max(1, os.cpu_count() or 1)",
            "            os.sched_setaffinity(0, {worker_index % cpu_total})",
            "    except Exception:",
            "        pass",
            "    seed = bytearray(PAYLOAD_BYTES)",
            "    for idx in range(PAYLOAD_BYTES):",
            "        seed[idx] = (idx + worker_index) & 0xFF",
            "    salt_counter = worker_index + 1",
            "    while True:",
            "        salt = salt_counter.to_bytes(16, 'little', signed=False)",
            "        digest = hashlib.pbkdf2_hmac(ALGORITHM, seed, salt, ITERATIONS, dklen=64)",
            "        seed[:64] = digest",
            "        salt_counter += 1",
            "def stop(*_):",
            "    for proc in workers:",
            "        if proc.is_alive():",
            "            proc.terminate()",
            "    for proc in workers:",
            "        proc.join(timeout=1)",
            "    raise SystemExit(0)",
            "signal.signal(signal.SIGTERM, stop)",
            "signal.signal(signal.SIGINT, stop)",
            f"count = {max(1, worker_count)}",
            "for worker_index in range(count):",
            "    proc = mp.Process(target=worker, args=(worker_index,), daemon=True)",
            "    proc.start()",
            "    workers.append(proc)",
            "while True:",
            "    time.sleep(1)",
        ]
    )


def build_cpu_command(
    *,
    worker_count: int,
    helper_available: bool,
    helper_path: str,
    requested_mode: str,
    instruction_set: str,
    mode: str,
    stress_ng_available: bool,
    python_runtime: str,
    cpu_kernel_flavor: str = "",
    result_file: str = "",
) -> Optional[List[str]]:
    if worker_count <= 0:
        return None
    if helper_available:
        cmd = [
            helper_path,
            "--mode",
            requested_mode,
            "--threads",
            str(worker_count),
        ]
        if cpu_kernel_flavor:
            cmd.extend(["--kernel-flavor", cpu_kernel_flavor])
        if result_file:
            cmd.extend(["--result-file", result_file])
        return cmd
    if stress_ng_available:
        method = "matrixprod"
        if (instruction_set or "").strip().lower() == "sse":
            method = "int64"
        return ["stress-ng", "--cpu", str(worker_count), "--cpu-method", method, "--metrics-brief"]
    if not python_runtime:
        return None
    return [python_runtime, "-c", build_cpu_fallback_script(instruction_set, mode, worker_count)]


def build_cpu_benchmark_result(
    *,
    kernel_flavor: str,
    samples: List[float],
    result_payload: Dict[str, Any],
    return_code: Optional[int],
) -> Dict[str, Any]:
    error_count = int(result_payload.get("error_count") or 0) if result_payload else 0
    status = str(result_payload.get("status") or "").strip().lower()
    valid = bool(result_payload) and return_code in (0, None) and status != "error" and error_count == 0
    return {
        "kernel_flavor": kernel_flavor,
        "avg_cpu_power_w": round(statistics.mean(samples), 2) if samples else None,
        "max_cpu_power_w": round(max(samples), 2) if samples else None,
        "valid": valid,
        "return_code": return_code,
        "status": status,
        "error_count": error_count,
    }


def benchmark_cpu_kernel_candidate(
    *,
    kernel_flavor: str,
    build_command: Callable[[str, str], Optional[List[str]]],
    command_env: Dict[str, str],
    telemetry_collector_factory: Callable[..., Any],
    popen_factory: Callable[..., Any],
    stop_processes: Callable[[List[Any]], None],
    temp_file_factory: Callable[..., Any],
    interval_seconds: float,
    warmup_seconds: float,
    measure_seconds: float,
    runtime_environment: Dict[str, str],
    privileged_helper_enabled: bool,
    stdout_target: Any,
    stderr_target: Any,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Dict[str, Any]:
    telemetry = telemetry_collector_factory(
        interval_seconds=interval_seconds,
        runtime_environment=runtime_environment,
        privileged_helper_enabled=privileged_helper_enabled,
    )
    samples: List[float] = []
    proc = None
    result_path = ""
    try:
        with temp_file_factory(prefix="lvs_cpu_tune_", suffix=".json", delete=False) as result_handle:
            result_path = result_handle.name
        cmd = build_command(kernel_flavor, result_path)
        if cmd is None:
            return {"kernel_flavor": kernel_flavor, "avg_cpu_power_w": None, "max_cpu_power_w": None}
        proc = popen_factory(
            cmd,
            stdout=stdout_target,
            stderr=stderr_target,
            env=command_env,
        )
        warmup_deadline = monotonic() + warmup_seconds
        measure_deadline = warmup_deadline + measure_seconds
        while monotonic() < measure_deadline:
            if proc.poll() is not None:
                break
            telemetry.collect_once()
            sample = telemetry.samples[-1].values.get("cpu_power_w") if telemetry.samples else None
            if monotonic() >= warmup_deadline and sample is not None:
                samples.append(sample)
            sleep(interval_seconds)
    except Exception:
        return {"kernel_flavor": kernel_flavor, "avg_cpu_power_w": None, "max_cpu_power_w": None}
    finally:
        if proc is not None:
            stop_processes([proc])
    return_code = proc.returncode if proc is not None else None
    result_payload: Dict[str, Any] = {}
    if result_path:
        try:
            with open(result_path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                result_payload = loaded
        except Exception:
            result_payload = {}
        try:
            Path(result_path).unlink(missing_ok=True)
        except Exception:
            pass
    return build_cpu_benchmark_result(
        kernel_flavor=kernel_flavor,
        samples=samples,
        result_payload=result_payload,
        return_code=return_code,
    )
