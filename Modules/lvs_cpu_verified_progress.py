"""Versioned, supplementary verified FP32 work evidence (never an exit verdict).

Native CLOCK_MONOTONIC and Python time.monotonic share the Linux boot clock.
Rates use publication timestamps, not configured cadence or snapshot row count.
No work is interpolated across trims, stale publications, or missing records.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from Modules.lvs_worker_integrity import worker_verification_satisfied, verified_fp32_worker, sve_thread_geometry_valid

CONTRACT = "neon_fp32_fma_progress_v1"
UINT64_MAX = (1 << 64) - 1


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("nonfinite or nonnumeric timestamp")
    try:
        converted = float(value)
    except OverflowError as error:
        raise ValueError("timestamp overflow") from error
    if not math.isfinite(converted):
        raise ValueError("nonfinite timestamp")
    return converted


def _counter(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= UINT64_MAX:
        raise ValueError("invalid uint64 counter")
    return value


def analyze_verified_progress(worker: dict, window: Any) -> dict:
    """Stream a sidecar in O(threads) memory; retain summaries, not growing history."""
    start = float(window.started_monotonic) + float(window.trim_start_seconds)
    end = float(window.ended_monotonic) - float(window.trim_end_seconds)
    kernel = worker.get("kernel_flavor")
    sve = (kernel == "sve_fp32_fma" or worker.get("verification_contract") == "sve_fp32_fma_v1"
           or worker.get("requested_kernel_flavor") == "sve_fp32_fma")
    contract = "sve_fp32_fma_progress_v1" if sve else CONTRACT
    result = {
        "contract": contract, "quality": "insufficient", "reasons": [],
        "window_start_monotonic_seconds": start, "window_end_monotonic_seconds": end,
        "throughput_unit": "fully_verified_arithmetic_blocks_per_second",
        "boundary_policy": "both_publication_endpoints_inside_trimmed_interval_no_interpolation",
        "clock": "linux_CLOCK_MONOTONIC", "snapshots": 0,
        "clock_correlation_notices": [], "maximum_clock_pair_uncertainty_seconds": 0.0,
        "analysis_intent": getattr(window, "analysis_intent", "legacy_unspecified"),
        "minimum_usable_seconds": getattr(window, "analysis_minimum_usable_seconds", None),
        "final_snapshot_complete": False, "threads": [],
        "last_snapshot_state": None, "last_observed_aggregate_verified_blocks": None,
        "observed_exit_code": worker.get("observed_exit_code"),
        "aggregate_blocks_per_second": None, "aggregate_interval_rate": None,
        "telemetry_analysis_quality": (getattr(window, "analysis_evidence", {}) or {}).get("quality", "not_assessed"),
        "correlation": "publication monotonic timestamps share the raw telemetry and stage time base",
        "saturation_assessed": False,
    }
    reasons: list[str] = result["reasons"]
    def issue(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    metadata = worker.get("verified_progress")
    if not isinstance(metadata, dict) or metadata.get("contract") != contract:
        result["quality"] = "not_assessed"
        issue("no recognized progress contract; historical work is not retrospectively assessed")
        return result
    path = metadata.get("path")
    if not path and worker.get("result_path"):
        path = str(worker["result_path"]) + ".progress.jsonl"
    result["path"] = str(path or "")
    if end <= start:
        result["quality"] = "invalid"
        issue("invalid actual trimmed interval")
        return result
    if metadata.get("persistence_error"):
        issue("native progress persistence failed")
    targets = metadata.get("target_cpu_ids") or worker.get("target_cpu_ids") or []
    if (not isinstance(targets, list) or not targets
            or any(type(cpu) is not int or cpu < 0 for cpu in targets)
            or len(set(targets)) != len(targets)):
        issue("missing or inconsistent targeted CPU identities")
        return result
    states = {cpu: {"cpu_id": cpu, "intervals": 0, "verified_block_delta": 0,
                   "observed_seconds": 0.0, "min_blocks_per_second": None,
                   "max_blocks_per_second": None, "stalled_intervals": 0,
                   "max_publication_gap_seconds": 0.0,
                   "last_observed_verified_blocks": 0,
                   "last_publication_monotonic_seconds": None,
                   "first_half": {"blocks": 0, "seconds": 0.0},
                   "second_half": {"blocks": 0, "seconds": 0.0}} for cpu in targets}
    details = worker.get("threads_detail")
    geometries = {d["affinity_target_cpu"]: d for d in (details if isinstance(details, list) else [])
                  if isinstance(d, dict) and type(d.get("affinity_target_cpu")) is int}
    if sve and any(not sve_thread_geometry_valid(geometries.get(cpu, {})) for cpu in targets):
        issue("invalid or missing authoritative SVE per-thread geometry")
        return result
    previous = None
    first_offset = None
    last_state = None
    initial_seen = False
    interval_rates = {"count": 0, "minimum": None, "maximum": None, "sum": 0.0}
    try:
        if not path:
            raise OSError("progress path missing")
        with Path(path).open(encoding="utf-8") as stream:
            for line in stream:
                # A native fault can leave an unterminated last record. Never use it.
                if not line.endswith("\n"):
                    issue("truncated progress record")
                    break
                try:
                    row = json.loads(line)
                    if row.get("contract") != contract or row.get("kernel_flavor") != kernel or row.get("operation_family") != "fp32_fused_multiply_add":
                        raise ValueError("wrong kernel or progress contract")
                    seq = _counter(row.get("sequence"))
                    if type(row.get("pid")) is not int or row["pid"] <= 0:
                        raise ValueError("invalid worker PID")
                    timestamp = _number(row.get("monotonic_seconds"))
                    realtime = _number(row.get("realtime_seconds"))
                    uncertainty = _number(row.get("clock_pair_uncertainty_seconds"))
                    if uncertainty < 0:
                        raise ValueError("negative clock correlation uncertainty")
                    result["maximum_clock_pair_uncertainty_seconds"] = max(
                        result["maximum_clock_pair_uncertainty_seconds"], uncertainty)
                    if worker.get("process_pid") is not None and row.get("pid") != worker["process_pid"]:
                        raise ValueError("wrong worker PID")
                    if previous and row.get("pid") != previous["pid"]:
                        raise ValueError("worker identity changed")
                    offset = realtime - timestamp
                    if first_offset is None:
                        first_offset = offset
                    elif abs(offset - first_offset) > 0.1:
                        notice = "realtime clock changed; use shared monotonic timestamps, not UTC interpolation"
                        if notice not in result["clock_correlation_notices"]:
                            result["clock_correlation_notices"].append(notice)
                    threads = row.get("threads")
                    if not isinstance(threads, list) or len(threads) != len(targets):
                        raise ValueError("missing thread publication")
                    mapping = {}
                    for index, thread in enumerate(threads):
                        cpu = thread.get("cpu_id")
                        if thread.get("thread_index") != index or cpu not in states or cpu in mapping:
                            raise ValueError("thread/CPU identity mismatch")
                        count = _counter(thread.get("verified_blocks"))
                        _counter(thread.get("error_count"))
                        if any(type(thread.get(flag)) is not bool for flag in
                               ("initial_verified", "periodic_verified", "final_verified", "affinity_applied")):
                            raise ValueError("missing or nonboolean verification/affinity flag")
                        published = _number(thread.get("published_monotonic_seconds"))
                        if published < 0 or published > timestamp + 0.001:
                            raise ValueError("invalid publication timestamp")
                        if count and (not thread.get("initial_verified") or not thread.get("affinity_applied") or thread.get("observed_cpu") != cpu):
                            raise ValueError("unverified work or invalid affinity")
                        if thread.get("error_count"):
                            issue("worker reported arithmetic/affinity failure")
                        if sve and count:
                            geometry = geometries.get(cpu, {})
                            if (thread.get("vector_length_bytes") != geometry.get("vector_length_bytes")
                                    or thread.get("active_fp32_lanes") != geometry.get("active_fp32_lanes")
                                    or not geometry.get("active_fp32_lanes")):
                                raise ValueError("SVE vector length changed or differs from verified worker")
                        mapping[cpu] = thread
                    if sum(_counter(t["verified_blocks"]) for t in threads) != _counter(row.get("aggregate_verified_blocks")):
                        raise ValueError("aggregate counter differs from per-thread counters")
                    state = row.get("state")
                    if state not in {"startup", "initial", "ongoing", "interrupted", "final_complete", "failed"}:
                        raise ValueError("unknown snapshot state")
                    if result["snapshots"] == 0 and (state != "startup" or seq != 0):
                        issue("missing startup snapshot")
                    if state == "initial":
                        if not all(t.get("initial_verified") for t in threads):
                            raise ValueError("incomplete initial verification")
                        initial_seen = True
                    if last_state in {"final_complete", "failed"}:
                        raise ValueError("records after terminal snapshot")
                    current = {"mapping": mapping, "timestamp": timestamp, "sequence": seq, "pid": row.get("pid")}
                    if previous:
                        gap = timestamp - previous["timestamp"]
                        if gap <= 0 or seq <= previous["sequence"]:
                            raise ValueError("timestamp or sequence regression")
                        sequence_gap = seq != previous["sequence"] + 1
                        if sequence_gap:
                            issue("missing snapshot sequence")
                        if gap > 6.0:
                            issue("snapshot gap exceeds three expected intervals")
                        rates = []
                        for cpu, thread in mapping.items():
                            prior = previous["mapping"][cpu]
                            count, old = thread["verified_blocks"], prior["verified_blocks"]
                            right, left = thread["published_monotonic_seconds"], prior["published_monotonic_seconds"]
                            if count < old or right < left or (right == left and count != old):
                                raise ValueError("counter regression/reset or incoherent publication")
                            if start <= timestamp <= end and timestamp - right > 6.0:
                                issue(f"stale publication for CPU {cpu}")
                            if not (start <= left < right <= end):
                                continue
                            elapsed = right - left
                            stats = states[cpu]
                            stats["max_publication_gap_seconds"] = max(stats["max_publication_gap_seconds"], elapsed)
                            if elapsed > 6.0 or gap > 6.0 or sequence_gap:
                                issue(f"unobserved work interval for CPU {cpu}")
                                continue
                            rate = (count - old) / elapsed
                            stats["intervals"] += 1
                            stats["verified_block_delta"] += count - old
                            stats["observed_seconds"] += elapsed
                            stats["stalled_intervals"] += int(count == old)
                            midpoint = (start + end) / 2
                            half = "first_half" if right <= midpoint else "second_half" if left >= midpoint else None
                            if half:
                                stats[half]["blocks"] += count - old
                                stats[half]["seconds"] += elapsed
                            stats["min_blocks_per_second"] = rate if stats["min_blocks_per_second"] is None else min(stats["min_blocks_per_second"], rate)
                            stats["max_blocks_per_second"] = rate if stats["max_blocks_per_second"] is None else max(stats["max_blocks_per_second"], rate)
                            rates.append(rate)
                        if len(rates) == len(targets):
                            rate = sum(rates)
                            interval_rates["count"] += 1
                            interval_rates["sum"] += rate
                            interval_rates["minimum"] = rate if interval_rates["minimum"] is None else min(interval_rates["minimum"], rate)
                            interval_rates["maximum"] = rate if interval_rates["maximum"] is None else max(interval_rates["maximum"], rate)
                    if state == "final_complete":
                        if not all(t.get("initial_verified") and t.get("periodic_verified") and t.get("final_verified") and not t.get("error_count") for t in threads):
                            raise ValueError("incomplete terminal thread verification")
                        details = worker.get("threads_detail") or []
                        if len(details) != len(threads) or any(t["verified_blocks"] != d.get("arithmetic_verified_blocks") for t, d in zip(threads, details)):
                            raise ValueError("final progress differs from authoritative worker result")
                        result["final_snapshot_complete"] = True
                    previous = current
                    last_state = state
                    result["last_snapshot_state"] = state
                    result["last_observed_aggregate_verified_blocks"] = row["aggregate_verified_blocks"]
                    for cpu, thread in mapping.items():
                        states[cpu]["last_observed_verified_blocks"] = thread["verified_blocks"]
                        states[cpu]["last_publication_monotonic_seconds"] = thread["published_monotonic_seconds"]
                    result["snapshots"] += 1
                except (ValueError, TypeError, KeyError, AttributeError) as error:
                    issue(f"invalid progress record: {error}")
                    previous = None  # Never bridge corrupt or truncated evidence.
    except (OSError, UnicodeError, TypeError, ValueError) as error:
        issue(f"progress unavailable: {error}")
    if not initial_seen:
        issue("missing initial verification snapshot")
    if last_state != "final_complete" or not result["final_snapshot_complete"]:
        issue("missing final complete snapshot")
    if "snapshot_count" in metadata and metadata["snapshot_count"] != result["snapshots"]:
        issue("snapshot count differs from authoritative worker metadata")
    if not worker_verification_satisfied(worker) or worker.get("observed_exit_code") != 0:
        issue("authoritative worker verification and clean process exit are not established")
    duration = end - start
    minimum = getattr(window, "analysis_minimum_usable_seconds", None)
    if minimum is not None and duration < float(minimum):
        issue("actual trimmed interval is below authored duration requirement")
    for cpu, stats in states.items():
        seconds = stats["observed_seconds"]
        stats["coverage_fraction"] = min(1.0, seconds / duration)
        stats["blocks_per_second"] = stats["verified_block_delta"] / seconds if seconds else None
        for half in ("first_half", "second_half"):
            summary = stats[half]
            summary["blocks_per_second"] = summary["blocks"] / summary["seconds"] if summary["seconds"] else None
        # These are derived lane arithmetic operations, NOT measured instructions.
        lanes = geometries.get(cpu, {}).get("active_fp32_lanes", 0) if sve else 4
        stats["derived_stress_lane_fma_count"] = stats["verified_block_delta"] * lanes * 8 * 256
        stats["derived_witness_lane_fma_count"] = stats["verified_block_delta"] * 4
        if sve:
            stats["active_fp32_lanes"] = lanes
            stats["vector_length_bytes"] = geometries.get(cpu, {}).get("vector_length_bytes")
            stats["derived_stress_lane_fmas_per_second"] = stats["blocks_per_second"] * lanes * 8 * 256 if seconds else None
        if stats["intervals"] < 2 or stats["coverage_fraction"] < 0.8:
            issue(f"insufficient post-trim progress coverage for CPU {cpu}")
        if stats["stalled_intervals"]:
            issue(f"stalled verified work observed for CPU {cpu}")
        result["threads"].append(stats)
    if all(s["blocks_per_second"] is not None for s in states.values()):
        result["aggregate_blocks_per_second"] = sum(s["blocks_per_second"] for s in states.values())
        if sve:
            result["derived_stress_lane_fmas_per_second"] = sum(s["derived_stress_lane_fmas_per_second"] for s in states.values())
    if interval_rates["count"]:
        result["aggregate_interval_rate"] = {
            "count": interval_rates["count"], "minimum": interval_rates["minimum"],
            "maximum": interval_rates["maximum"], "average": interval_rates["sum"] / interval_rates["count"],
            "semantics": "sum of independently timed per-thread interval rates; publication endpoints may differ",
        }
    if result["telemetry_analysis_quality"] != "sufficient":
        issue("stage telemetry analysis is not sufficient for correlated sustained interpretation")
    result["quality"] = "insufficient" if reasons else "sufficient"
    return result


def attach_verified_progress(window: Any) -> None:
    for worker in getattr(window, "worker_results", []):
        if verified_fp32_worker(worker) and "verified_progress" in worker:
            worker["verified_progress_analysis"] = analyze_verified_progress(worker, window)
