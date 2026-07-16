#!/usr/bin/env python3
"""GPU progress-line formatting helpers."""

from __future__ import annotations

import math
import re
from typing import Any, Dict

from Modules.lvs_gpu_stage_targets import gpu_index_from_metric_key


LIVE_SYSTEM_DEVICE_PROGRESS_LIMIT = 4


def latest_sample_value(telemetry: Any, key: str) -> Any:
    samples = getattr(telemetry, "samples", [])
    if not samples:
        return None
    values = getattr(samples[-1], "values", {})
    return values.get(key) if isinstance(values, dict) else None


def _progress_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _matching_progress_values(values: Dict[str, Any], pattern: str) -> list[float]:
    matched: list[float] = []
    for key, value in values.items():
        if re.fullmatch(pattern, str(key)) is None:
            continue
        number = _progress_number(value)
        if number is not None:
            matched.append(number)
    return matched


def _indexed_progress_values(values: Dict[str, Any], pattern: str) -> list[tuple[int, float]]:
    matched: list[tuple[int, float]] = []
    for key, value in values.items():
        match = re.fullmatch(pattern, str(key))
        number = _progress_number(value)
        if match is not None and number is not None:
            matched.append((int(match.group(1)), number))
    return sorted(matched)


def _cpu_package_clock_values(telemetry: Any, values: Dict[str, Any]) -> dict[int, float]:
    package_clocks: dict[int, list[float]] = {}
    for source in getattr(telemetry, "_cpu_core_clock_sources", []):
        if not isinstance(source, dict):
            continue
        package_match = re.search(r"(?:^|:)package(\d+)(?::|$)", str(source.get("physical_core_key") or ""))
        clock = _progress_number(values.get(str(source.get("key") or "")))
        if package_match is not None and clock is not None:
            package_clocks.setdefault(int(package_match.group(1)), []).append(clock)
    return {
        package_index: sum(clocks) / len(clocks)
        for package_index, clocks in package_clocks.items()
        if clocks
    }


def live_system_progress_parts(telemetry: Any) -> list[str]:
    """Format already-collected non-GPU values for the active-run progress event."""
    samples = getattr(telemetry, "samples", [])
    if not samples:
        return []
    values = getattr(samples[-1], "values", {})
    if not isinstance(values, dict):
        return []

    parts: list[str] = []
    package_temps = _matching_progress_values(values, r"cpu_package_\d+_temp_c")
    cpu_temp_c = max(package_temps) if package_temps else _progress_number(values.get("cpu_temp_c"))
    if cpu_temp_c is not None:
        parts.append(f"cpu_package_temp_c={round(cpu_temp_c, 2)}")

    cpu_power_w = _progress_number(values.get("cpu_power_w"))
    if cpu_power_w is None:
        package_powers = _matching_progress_values(values, r"cpu_package_\d+_power_w")
        cpu_power_w = sum(package_powers) if package_powers else None
    if cpu_power_w is not None:
        parts.append(f"cpu_package_power_w={round(cpu_power_w, 2)}")

    cpu_clock_mhz = _progress_number(values.get("cpu_clock_mhz"))
    if cpu_clock_mhz is None:
        core_clocks = _matching_progress_values(values, r"cpu_core_\d+_clock_mhz")
        cpu_clock_mhz = sum(core_clocks) / len(core_clocks) if core_clocks else None
    if cpu_clock_mhz is not None:
        parts.append(f"cpu_clock_mhz={round(cpu_clock_mhz, 2)}")

    package_temps_indexed = dict(_indexed_progress_values(values, r"cpu_package_(\d+)_temp_c"))
    package_powers_indexed = dict(_indexed_progress_values(values, r"cpu_package_(\d+)_power_w"))
    package_clocks_indexed = _cpu_package_clock_values(telemetry, values)
    package_indexes = sorted(set(package_temps_indexed) | set(package_powers_indexed) | set(package_clocks_indexed))
    if package_indexes:
        parts.append(f"cpu_package_count={len(package_indexes)}")
        for package_index in package_indexes[:LIVE_SYSTEM_DEVICE_PROGRESS_LIMIT]:
            for metric, metric_values in (
                ("temp_c", package_temps_indexed),
                ("power_w", package_powers_indexed),
                ("clock_mhz", package_clocks_indexed),
            ):
                if package_index in metric_values:
                    parts.append(
                        f"cpu_package_{package_index}_{metric}={round(metric_values[package_index], 2)}"
                    )

    memory_used_gib = _progress_number(values.get("memory_used_gb"))
    if memory_used_gib is not None:
        # The collector's legacy field is calculated using 1024**3 units.
        parts.append(f"memory_used_gib={round(memory_used_gib, 2)}")
    memory_total_gib = _progress_number(getattr(telemetry, "memory_total_gib", None))
    if memory_total_gib is not None and memory_total_gib > 0:
        parts.append(f"memory_total_gib={round(memory_total_gib, 2)}")
        if memory_used_gib is not None and memory_used_gib >= 0:
            used_percent = min(100.0, (memory_used_gib / memory_total_gib) * 100.0)
            parts.append(f"memory_used_percent={round(used_percent, 1)}")

    memory_temps_indexed = _indexed_progress_values(values, r"memory_module_(\d+)_temp_c")
    memory_temps = [value for _index, value in memory_temps_indexed]
    if memory_temps:
        parts.append(f"memory_module_temp_c={round(max(memory_temps), 2)}")
        parts.append(f"memory_module_temp_count={len(memory_temps_indexed)}")
        for module_index, temp_c in memory_temps_indexed[:LIVE_SYSTEM_DEVICE_PROGRESS_LIMIT]:
            parts.append(f"memory_module_{module_index}_temp_c={round(temp_c, 2)}")

    storage_temps_indexed = _indexed_progress_values(values, r"storage_drive_(\d+)_temp_c")
    storage_temps = [value for _index, value in storage_temps_indexed]
    if storage_temps:
        parts.append(f"storage_temp_c={round(max(storage_temps), 2)}")
        parts.append(f"storage_drive_temp_count={len(storage_temps_indexed)}")
        for drive_index, temp_c in storage_temps_indexed[:LIVE_SYSTEM_DEVICE_PROGRESS_LIMIT]:
            parts.append(f"storage_drive_{drive_index}_temp_c={round(temp_c, 2)}")
    return parts


def gpu_metric_progress_parts(
    values: Dict[str, Any],
    gpu_index: int,
    *,
    include_memory_clock: bool = False,
    vram_total_bytes: int = 0,
) -> list[str]:
    metric_specs = [
        (f"gpu_{gpu_index}_busy_percent", "busy", "%"),
        (f"gpu_{gpu_index}_memory_busy_percent", "mem_busy", "%"),
        (f"gpu_{gpu_index}_power_w", "pwr", "W"),
        (f"gpu_{gpu_index}_temp_core_c", "temp", "C"),
        (f"gpu_{gpu_index}_clock_mhz", "clk", "MHz"),
        (f"gpu_{gpu_index}_fan_percent", "fan_percent", "%"),
    ]
    if include_memory_clock:
        metric_specs.append((f"gpu_{gpu_index}_memory_clock_mhz", "mclk", "MHz"))
    metric_specs.append((f"gpu_{gpu_index}_vram_used_gb", "vram", "GB"))
    parts: list[str] = []
    for key, label, suffix in metric_specs:
        value = values.get(key)
        if value is not None:
            parts.append(f"{label}={round(float(value), 2)}{suffix}")
    if int(vram_total_bytes or 0) > 0:
        total_gib = int(vram_total_bytes) / float(1024 ** 3)
        parts.append(f"gpu_vram_total_gib={round(total_gib, 2)}")
        used_gib = _progress_number(values.get(f"gpu_{gpu_index}_vram_used_gb"))
        if used_gib is not None and used_gib >= 0:
            used_percent = min(100.0, (used_gib / total_gib) * 100.0)
            parts.append(f"gpu_vram_used_percent={round(used_percent, 1)}")
    return parts


def target_gpu_metric_progress_parts(
    telemetry: Any,
    gpu_index: int,
    *,
    vram_total_bytes: int = 0,
) -> list[str]:
    samples = getattr(telemetry, "samples", [])
    if not samples:
        return []
    values = getattr(samples[-1], "values", {})
    if not isinstance(values, dict):
        return []
    return gpu_metric_progress_parts(
        values,
        gpu_index,
        include_memory_clock=True,
        vram_total_bytes=vram_total_bytes,
    )


def _first_payload_value(payloads: list[Dict[str, Any]], key: str) -> Any:
    for payload in payloads:
        value = payload.get(key)
        if value is not None:
            return value
    return None


def _first_payload_float(payloads: list[Dict[str, Any]], key: str) -> float | None:
    value = _first_payload_value(payloads, key)
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _first_payload_int(payloads: list[Dict[str, Any]], key: str) -> int | None:
    value = _first_payload_value(payloads, key)
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def gpu_vram_total_bytes_from_payloads(payloads: list[Dict[str, Any]]) -> int:
    candidates: list[int] = []
    for payload in payloads:
        for key in ("target_vram_total", "device_global_mem_bytes", "device_local_heap_bytes"):
            try:
                value = int(payload.get(key) or 0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                candidates.append(value)
    return max(candidates, default=0)


def _first_payload_text(payloads: list[Dict[str, Any]], key: str) -> str:
    for payload in payloads:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _planned_candidates(planned_states: list[Dict[str, Any]], key: str, cast: Any) -> list[Any]:
    candidates: list[Any] = []
    for state in planned_states:
        value = state.get(key)
        if value is None:
            continue
        try:
            candidates.append(cast(value))
        except Exception:
            continue
    return candidates


def target_gpu_state_progress_parts(
    live_payloads: list[Dict[str, Any]],
    planned_states: list[Dict[str, Any]],
    *,
    target_vram_total: int = 0,
) -> list[str]:
    state_details: list[str] = []
    load_fraction = _first_payload_float(live_payloads, "active_load_fraction")
    if load_fraction is None:
        load_candidates = _planned_candidates(planned_states, "active_load_fraction", float)
        if load_candidates:
            load_fraction = max(load_candidates)
    if load_fraction is not None:
        state_details.append(f"load={round(load_fraction * 100.0, 1)}%")

    phase_name = _first_payload_text(live_payloads, "phase")
    if not phase_name:
        phase_candidates = [
            str(state.get("active_phase") or "").strip()
            for state in planned_states
            if state.get("active_phase")
        ]
        if phase_candidates:
            phase_name = phase_candidates[0]
    if phase_name:
        state_details.append(f"phase={phase_name}")

    active_vram_target = _first_payload_int(live_payloads, "active_target_vram_bytes")
    if active_vram_target is None:
        vram_candidates = _planned_candidates(planned_states, "active_target_vram_bytes", int)
        if vram_candidates:
            active_vram_target = max(vram_candidates)
    if active_vram_target:
        if target_vram_total > 0:
            state_details.append(
                f"vram_target={round(active_vram_target / (1024 ** 3), 2)}/{round(target_vram_total / (1024 ** 3), 2)}GB"
            )
        else:
            state_details.append(f"vram_target={round(active_vram_target / (1024 ** 3), 2)}GB")

    allocated_vram_bytes = _first_payload_int(live_payloads, "allocated_vram_bytes")
    if allocated_vram_bytes:
        if active_vram_target and active_vram_target > 0:
            state_details.append(
                f"alloc={round(allocated_vram_bytes / (1024 ** 3), 2)}/{round(active_vram_target / (1024 ** 3), 2)}GB"
            )
        else:
            state_details.append(f"alloc={round(allocated_vram_bytes / (1024 ** 3), 2)}GB")

    active_fill_buffers = _first_payload_int(live_payloads, "active_fill_buffer_count")
    if active_fill_buffers is not None:
        state_details.append(f"fill_buf={active_fill_buffers}")

    active_draw = _first_payload_int(live_payloads, "active_draw_count")
    if active_draw is None:
        draw_candidates = _planned_candidates(planned_states, "active_draw_count", int)
        if draw_candidates:
            active_draw = max(draw_candidates)
    if active_draw:
        state_details.append(f"draw={active_draw}")

    active_processes = _first_payload_int(live_payloads, "active_process_count")
    if active_processes:
        target_processes = _first_payload_int(live_payloads, "target_process_count")
        if target_processes and target_processes > 0:
            state_details.append(f"proc={active_processes}/{target_processes}")
        else:
            state_details.append(f"proc={active_processes}")

    active_launches = _first_payload_int(live_payloads, "active_launches_per_cycle")
    if active_launches:
        state_details.append(f"launch={active_launches}")

    active_buffers = _first_payload_int(live_payloads, "active_buffer_count")
    if active_buffers is not None:
        state_details.append(f"comp_buf={active_buffers}")

    active_buffer_bytes = _first_payload_int(live_payloads, "active_buffer_bytes")
    if active_buffer_bytes is None:
        buffer_candidates = _planned_candidates(planned_states, "active_buffer_bytes", int)
        if buffer_candidates:
            active_buffer_bytes = max(buffer_candidates)
    if active_buffer_bytes:
        state_details.append(f"buf={round(active_buffer_bytes / (1024 ** 2), 1)}MB")

    active_compute_rounds = _first_payload_int(live_payloads, "active_compute_rounds")
    if active_compute_rounds is None:
        active_compute_rounds = _first_payload_int(live_payloads, "compute_rounds")
    if active_compute_rounds is None:
        round_candidates = _planned_candidates(planned_states, "active_compute_rounds", int)
        if round_candidates:
            active_compute_rounds = max(round_candidates)
    if active_compute_rounds:
        state_details.append(f"rounds={active_compute_rounds}")
    return state_details


def target_gpu_progress_summary(
    gpu_index: int,
    target: Dict[str, Any],
    metrics: list[str],
    state_details: list[str],
) -> str:
    workload_text = f"[{'+'.join(target['workloads'])}]" if target["workloads"] else ""
    backend_text = f"/{'+'.join(target['backends'])}" if target["backends"] else ""
    summary = f"gpu{gpu_index}@{target['target_id']}{workload_text}{backend_text}"
    if metrics:
        summary += ":" + ",".join(metrics)
    if state_details:
        summary += "|state=" + ",".join(state_details)
    return summary


def stage_gpu_progress_summary(
    target_summaries: list[str],
    other_summary: str = "",
    live_system_parts: list[str] | None = None,
) -> str:
    payload_parts: list[str] = list(live_system_parts or [])
    if target_summaries:
        payload_parts.append("gpu_target=" + " ; ".join(target_summaries))
    if other_summary:
        payload_parts.append(other_summary)
    return " | " + " | ".join(payload_parts) if payload_parts else ""


def other_gpu_progress_summary(telemetry: Any, targets: Dict[int, Dict[str, Any]]) -> str:
    samples = getattr(telemetry, "samples", [])
    if not samples:
        return ""
    latest = getattr(samples[-1], "values", {})
    if not isinstance(latest, dict):
        return ""
    target_indices = set(targets.keys())
    observed_indices = sorted(
        {
            gpu_index_from_metric_key(key)
            for key in latest.keys()
            if str(key).startswith("gpu_")
        }
    )
    summaries: list[str] = []
    for gpu_index in observed_indices:
        if gpu_index in target_indices:
            continue
        busy = latest.get(f"gpu_{gpu_index}_busy_percent")
        mem_busy = latest.get(f"gpu_{gpu_index}_memory_busy_percent")
        power = latest.get(f"gpu_{gpu_index}_power_w")
        temp = latest.get(f"gpu_{gpu_index}_temp_core_c")
        clock = latest.get(f"gpu_{gpu_index}_clock_mhz")
        vram_used = latest.get(f"gpu_{gpu_index}_vram_used_gb")
        if (
            busy is None
            and mem_busy is None
            and power is None
            and temp is None
            and clock is None
            and vram_used is None
        ):
            continue
        if (
            (busy is None or float(busy) < 1.0)
            and (mem_busy is None or float(mem_busy) < 1.0)
            and (power is None or float(power) < 5.0)
            and (vram_used is None or float(vram_used) < 0.05)
        ):
            continue
        metrics = gpu_metric_progress_parts(latest, gpu_index)
        if metrics:
            summaries.append(f"gpu{gpu_index}:" + ",".join(metrics))
    return "gpu_other=" + " ; ".join(summaries) if summaries else ""
