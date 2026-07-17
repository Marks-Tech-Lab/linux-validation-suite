"""fio capability, command, and JSON normalization for Storage Benchmark v1."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from statistics import fmean
from typing import Any, Callable, Iterable

from .lvs_storage_benchmark_profile import StorageBenchmarkProfile, StorageBenchmarkRow


def storage_benchmark_capability(
    *,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    fio = which("fio")
    result: dict[str, Any] = {
        "status": "unavailable",
        "fio_available": bool(fio),
        "fio_version": None,
        "libaio_available": False,
        "benchmark_mode_available": False,
        "severity": "warn",
        "notes": [],
    }
    if not fio:
        result["notes"].append("fio is not installed (optional for Storage Benchmark).")
        return result
    try:
        version = run([fio, "--version"], capture_output=True, text=True, timeout=10, check=False)
        result["fio_version"] = (version.stdout or version.stderr or "").strip() or None
        engines = run([fio, "--enghelp=libaio"], capture_output=True, text=True, timeout=10, check=False)
        result["libaio_available"] = engines.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        result["notes"].append(f"fio capability check failed: {exc}")
        return result
    if not result["libaio_available"]:
        result["notes"].append("fio libaio engine is unavailable.")
        return result
    result.update(status="available", benchmark_mode_available=True, severity="ok")
    return result


def build_fio_command(
    fio_path: str,
    profile: StorageBenchmarkProfile,
    row: StorageBenchmarkRow,
    *,
    filename: Path,
    output_path: Path,
    job_name: str,
    session_dir: Path,
) -> list[str]:
    resolved_file = filename.resolve(strict=False)
    resolved_session = session_dir.resolve(strict=True)
    if str(resolved_file).startswith("/dev/") or resolved_file.parent != resolved_session:
        raise ValueError("fio filename must be an LVS-owned file in the benchmark session")
    if resolved_file.name not in {"read.bin", "write.bin"}:
        raise ValueError("unexpected benchmark data filename")
    command = [
        fio_path,
        f"--name={job_name}",
        f"--filename={resolved_file}",
        f"--rw={row.operation}",
        f"--bs={row.block_size_bytes}",
        f"--iodepth={row.queue_depth}",
        f"--numjobs={row.threads}",
        f"--ioengine={profile.ioengine}",
        "--direct=1",
        f"--size={profile.test_size_gib * 1024**3}",
        f"--runtime={profile.measure_time_seconds}",
        "--randrepeat=0",
        "--refill_buffers=0",
        "--zero_buffers=0",
        "--end_fsync=1",
        "--group_reporting=1",
        "--percentile_list=95:99",
        "--output-format=json",
        f"--output={output_path}",
    ]
    if row.operation in {"read", "randread"}:
        command.append("--readonly")
    return command


def build_fio_prepare_command(
    fio_path: str,
    profile: StorageBenchmarkProfile,
    *,
    filename: Path,
    output_path: Path,
    session_dir: Path,
) -> list[str]:
    """Build the size-completing write used to initialize read.bin.

    Unlike measured rows, initialization intentionally has no runtime cap: the
    whole file must contain allocated test data before any read result is used.
    """
    resolved_file = filename.resolve(strict=False)
    if resolved_file.parent != session_dir.resolve(strict=True) or resolved_file.name != "read.bin":
        raise ValueError("preparation is restricted to LVS-owned read.bin")
    return [
        fio_path, "--name=lvs_prepare_read", f"--filename={resolved_file}", "--rw=write",
        "--bs=1048576", "--iodepth=8", "--numjobs=1", f"--ioengine={profile.ioengine}",
        "--direct=1", f"--size={profile.test_size_gib * 1024**3}", "--randrepeat=0",
        "--refill_buffers=0", "--zero_buffers=0", "--end_fsync=1", "--group_reporting=1",
        "--output-format=json", f"--output={output_path}",
    ]


def _latency(job_op: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    for key, scale in (("clat_ns", 0.001), ("clat_usec", 1.0), ("clat", 1.0)):
        block = job_op.get(key)
        if not isinstance(block, dict):
            continue
        mean = block.get("mean")
        percentiles = block.get("percentile") or {}
        def pct(prefix: str) -> float | None:
            for raw_key, value in percentiles.items():
                try:
                    if abs(float(raw_key) - float(prefix)) < 0.02:
                        return float(value) * scale
                except (TypeError, ValueError):
                    pass
            return None
        return (float(mean) * scale if mean is not None else None, pct("95"), pct("99"))
    return None, None, None


def parse_fio_json(payload: dict[str, Any], row: StorageBenchmarkRow, *, run_number: int) -> dict[str, Any]:
    jobs = payload.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("fio JSON contains no jobs")
    job = jobs[0]
    error = int(job.get("error") or 0)
    op_key = "read" if row.operation in {"read", "randread"} else "write"
    operation = job.get(op_key) or {}
    if error:
        return {"run_number": run_number, "status": "failed", "fio_error": error, "error": f"fio job error {error}"}
    bw_bytes = operation.get("bw_bytes")
    if bw_bytes is not None:
        mbps = float(bw_bytes) / 1_000_000.0
    elif operation.get("bw") is not None:
        mbps = float(operation["bw"]) * 1024.0 / 1_000_000.0
    else:
        raise ValueError("fio JSON has no bandwidth field")
    mean, p95, p99 = _latency(operation)
    total_ios = operation.get("total_ios")
    if total_ios is None and operation.get("io_bytes") is not None:
        total_ios = float(operation["io_bytes"]) / row.block_size_bytes
    return {
        "run_number": run_number,
        "status": "completed",
        "mb_per_s": mbps,
        "iops": float(operation.get("iops") or 0.0),
        "average_latency_us": mean,
        "p95_latency_us": p95,
        "p99_latency_us": p99,
        "io_count": float(total_ios or 0.0),
        "fio_error": 0,
        "error": None,
    }


def load_fio_result(path: Path, row: StorageBenchmarkRow, *, run_number: int) -> dict[str, Any]:
    return parse_fio_json(json.loads(path.read_text(encoding="utf-8")), row, run_number=run_number)


def aggregate_row(row: StorageBenchmarkRow, results: Iterable[dict[str, Any]], job_name: str) -> dict[str, Any]:
    all_results = list(results)
    good = [item for item in all_results if item.get("status") == "completed"]
    throughputs = [float(item["mb_per_s"]) for item in good]
    weighted = [(float(item["average_latency_us"]), float(item.get("io_count") or 0)) for item in good if item.get("average_latency_us") is not None]
    weight_sum = sum(weight for _, weight in weighted)
    latency = sum(value * weight for value, weight in weighted) / weight_sum if weight_sum else None
    p95 = [float(item["p95_latency_us"]) for item in good if item.get("p95_latency_us") is not None]
    p99 = [float(item["p99_latency_us"]) for item in good if item.get("p99_latency_us") is not None]
    return {
        "test_name": row.test_name,
        "display_name": row.display_name,
        "operation": row.operation,
        "pattern": row.pattern,
        "block_size_bytes": row.block_size_bytes,
        "queue_depth": row.queue_depth,
        "threads": row.threads,
        "successful_runs": len(good),
        "average_mb_per_s": fmean(throughputs) if throughputs else None,
        "best_mb_per_s": max(throughputs) if throughputs else None,
        "worst_mb_per_s": min(throughputs) if throughputs else None,
        "iops": fmean([float(item["iops"]) for item in good]) if good else None,
        "average_latency_us": latency,
        "p95_latency_us": max(p95) if p95 else None,
        "p99_latency_us": max(p99) if p99 else None,
        "latency_percentile_aggregation": "worst_observed_run",
        "fio_job_name": job_name,
        "status": "completed" if len(good) == len(all_results) and good else "failed",
        "error": next((item.get("error") for item in all_results if item.get("error")), None),
        "run_results": all_results,
    }
