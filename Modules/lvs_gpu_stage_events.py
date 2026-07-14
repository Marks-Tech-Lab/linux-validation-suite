#!/usr/bin/env python3
"""GPU stage-level stability event builders."""

from __future__ import annotations

import statistics
from typing import Any, Callable, Dict

from Modules.lvs_stability_events import create_stability_event, threshold_run_seconds


def _sample_values(samples: list[Any], key: str) -> list[float]:
    values: list[float] = []
    for sample in samples:
        sample_values = getattr(sample, "values", {})
        if not isinstance(sample_values, dict):
            continue
        value = sample_values.get(key)
        if value is not None:
            values.append(float(value))
    return values


def vram_target_attainment_events(
    *,
    worker_results: list[Dict[str, Any]],
    samples: list[Any],
    stage_name: str,
    stage_duration_seconds: float,
) -> list[Dict[str, Any]]:
    events: list[Dict[str, Any]] = []
    if not worker_results:
        return events

    for payload in worker_results:
        if str(payload.get("kind") or "").lower() != "gpu":
            continue
        if str(payload.get("mode") or payload.get("workload") or "").lower() != "vram":
            continue

        target_id = str(payload.get("target_id") or payload.get("card") or "unknown gpu")
        gpu_index = payload.get("gpu_index")
        try:
            gpu_index = int(gpu_index)
        except Exception:
            gpu_index = None

        target_bytes = int(
            payload.get("active_target_vram_bytes")
            or payload.get("target_vram_bytes")
            or 0
        )
        allocated_bytes = int(payload.get("allocated_vram_bytes") or 0)
        shortfall_bytes = (
            max(0, target_bytes - allocated_bytes)
            if target_bytes > 0
            else int(payload.get("allocation_shortfall_bytes") or 0)
        )
        target_gib = round(target_bytes / float(1024 ** 3), 2) if target_bytes > 0 else None
        allocated_gib = round(allocated_bytes / float(1024 ** 3), 2) if allocated_bytes > 0 else None
        ratio = (float(allocated_bytes) / float(target_bytes)) if target_bytes > 0 and allocated_bytes > 0 else None

        observed_vram_values: list[float] = []
        if gpu_index is not None:
            observed_vram_values = _sample_values(samples, f"gpu_{gpu_index}_vram_used_gb")
        observed_max = round(max(observed_vram_values), 2) if observed_vram_values else None

        severity = ""
        message = ""
        category = "gpu_vram_target_attainment"
        verification_passes = int(payload.get("verification_passes") or 0)
        if target_bytes > 0 and ratio is not None and ratio < 0.6:
            severity = "error"
            message = (
                f"target GPU {target_id} only allocated {allocated_gib}GB of the requested {target_gib}GB VRAM target"
            )
        elif target_bytes > 0 and ratio is not None and ratio < 0.85:
            severity = "warning"
            message = (
                f"target GPU {target_id} only allocated {allocated_gib}GB of the requested {target_gib}GB VRAM target"
            )
        elif target_gib and observed_max is not None and observed_max < target_gib * 0.6:
            severity = "warning"
            if ratio is not None and ratio >= 0.85 and verification_passes > 0:
                category = "gpu_vram_telemetry_discrepancy"
                message = (
                    f"target GPU {target_id} allocated and verified {allocated_gib}GB of a {target_gib}GB VRAM target, "
                    + f"but OS telemetry reported only {observed_max}GB peak VRAM use"
                )
            else:
                message = (
                    f"target GPU {target_id} reported only {observed_max}GB peak VRAM use during a {target_gib}GB VRAM stage"
                )

        metric_key = f"gpu_{gpu_index}_vram_used_gb" if gpu_index is not None else "gpu_vram_used_gb"
        if severity and message:
            events.append(
                create_stability_event(
                    category,
                    severity,
                    stage_name,
                    metric_key,
                    message,
                    {
                        "gpu_index": gpu_index,
                        "target_id": target_id,
                        "target_vram_bytes": target_bytes,
                        "allocated_vram_bytes": allocated_bytes,
                        "allocation_shortfall_bytes": shortfall_bytes,
                        "target_vram_gib": target_gib,
                        "allocated_vram_gib": allocated_gib,
                        "allocation_ratio": round(ratio, 4) if ratio is not None else None,
                        "observed_vram_used_max_gb": observed_max,
                        "verification_passes": verification_passes,
                        "allocation_verified": bool(ratio is not None and ratio >= 0.85 and verification_passes > 0),
                        "target_attainment": "worker_verified" if ratio is not None and ratio >= 0.85 and verification_passes > 0 else "telemetry_reported",
                    },
                )
            )

        device_class = str(payload.get("device_class") or "").strip().lower()
        verification_threshold = 1
        if device_class == "discrete":
            verification_threshold = 3
        elif target_bytes > 0:
            verification_threshold = 2
        if target_bytes > 0 and verification_passes < verification_threshold:
            interval_seconds = payload.get("verification_interval_seconds")
            phase = str(payload.get("phase") or "")
            qualifier = "no" if verification_passes <= 0 else f"only {verification_passes}"
            events.append(
                create_stability_event(
                    "gpu_vram_verification_coverage",
                    "warning",
                    stage_name,
                    metric_key,
                    (
                        f"target GPU {target_id} completed the VRAM stage with {qualifier} readback verification "
                        + f"pass{'es' if verification_passes != 1 else ''}; allocation succeeded but integrity coverage was thin"
                    ),
                    {
                        "gpu_index": gpu_index,
                        "target_id": target_id,
                        "device_class": device_class,
                        "target_vram_bytes": target_bytes,
                        "allocated_vram_bytes": allocated_bytes,
                        "verification_passes": verification_passes,
                        "verification_threshold": verification_threshold,
                        "verification_interval_seconds": interval_seconds,
                        "phase": phase,
                        "stage_duration_seconds": round(stage_duration_seconds, 2),
                    },
                )
            )
    return events


def target_gpu_utilization_events(
    *,
    target_gpus: Dict[int, Dict[str, Any]],
    samples: list[Any],
    stage_name: str,
    telemetry_interval_seconds: float,
    target_busy_threshold: float,
    target_busy_sustain: float,
    target_mem_busy_threshold: float,
    target_mem_busy_sustain: float,
) -> list[Dict[str, Any]]:
    if (
        target_busy_threshold <= 0.0
        or target_busy_sustain <= 0.0
    ) and (
        target_mem_busy_threshold <= 0.0
        or target_mem_busy_sustain <= 0.0
    ):
        return []
    if not target_gpus or not samples:
        return []

    events: list[Dict[str, Any]] = []
    for gpu_index, target in sorted(target_gpus.items()):
        target_label = target["target_id"]
        workloads = set(target.get("workloads", []))
        if {"gpu_3d"} & workloads and target_busy_threshold > 0.0 and target_busy_sustain > 0.0:
            busy_key = f"gpu_{gpu_index}_busy_percent"
            busy_values = _sample_values(samples, busy_key)
            max_busy = round(max(busy_values), 2) if busy_values else None
            max_busy_run = threshold_run_seconds(samples, busy_key, target_busy_threshold, telemetry_interval_seconds)
            if max_busy_run < target_busy_sustain:
                events.append(
                    create_stability_event(
                        "gpu_target_utilization",
                        "error",
                        stage_name,
                        busy_key,
                        f"target GPU {target_label} did not sustain busy >= {target_busy_threshold}% for {target_busy_sustain}s",
                        {
                            "gpu_index": gpu_index,
                            "target_id": target_label,
                            "workloads": sorted(workloads),
                            "metric": busy_key,
                            "threshold_percent": target_busy_threshold,
                            "required_seconds": target_busy_sustain,
                            "max_busy_percent": max_busy,
                            "max_sustain_seconds": max_busy_run,
                        },
                    )
                )
        if "vram" in workloads and target_mem_busy_threshold > 0.0 and target_mem_busy_sustain > 0.0:
            mem_busy_key = f"gpu_{gpu_index}_memory_busy_percent"
            mem_busy_values = _sample_values(samples, mem_busy_key)
            if not mem_busy_values:
                events.append(
                    create_stability_event(
                        "gpu_target_memory_utilization",
                        "warning",
                        stage_name,
                        mem_busy_key,
                        f"target GPU {target_label} has no memory-busy telemetry for VRAM utilization checks",
                        {
                            "gpu_index": gpu_index,
                            "target_id": target_label,
                            "workloads": sorted(workloads),
                            "metric": mem_busy_key,
                        },
                    )
                )
            else:
                max_mem_busy = round(max(mem_busy_values), 2)
                max_mem_busy_run = threshold_run_seconds(samples, mem_busy_key, target_mem_busy_threshold, telemetry_interval_seconds)
                if max_mem_busy_run < target_mem_busy_sustain:
                    events.append(
                        create_stability_event(
                            "gpu_target_memory_utilization",
                            "error",
                            stage_name,
                            mem_busy_key,
                            f"target GPU {target_label} did not sustain memory busy >= {target_mem_busy_threshold}% for {target_mem_busy_sustain}s",
                            {
                                "gpu_index": gpu_index,
                                "target_id": target_label,
                                "workloads": sorted(workloads),
                                "metric": mem_busy_key,
                                "threshold_percent": target_mem_busy_threshold,
                                "required_seconds": target_mem_busy_sustain,
                                "max_memory_busy_percent": max_mem_busy,
                                "max_sustain_seconds": max_mem_busy_run,
                            },
                        )
                    )
    return events


def gpu_backend_effectiveness_events(
    *,
    target_gpus: Dict[int, Dict[str, Any]],
    samples: list[Any],
    stage_name: str,
    backend_profile_lookup: Callable[[str], Dict[str, Any]],
    gpu_3d_backend_preference: str = "",
    gpu_3d_backend_resolved: str = "",
) -> list[Dict[str, Any]]:
    if not target_gpus or not samples:
        return []

    events: list[Dict[str, Any]] = []
    for gpu_index, target in sorted(target_gpus.items()):
        workloads = set(target.get("workloads", []))
        if "gpu_3d" not in workloads:
            continue
        backends = [str(backend or "").strip() for backend in target.get("backends", []) if str(backend or "").strip()]
        if not backends:
            continue
        profiles = [backend_profile_lookup(backend) for backend in backends]
        load_classes = {str(profile.get("load_class", "") or "") for profile in profiles if profile}
        if not load_classes:
            continue
        if any(bool(profile.get("recommended_for_saturation")) for profile in profiles):
            continue

        busy_key = f"gpu_{gpu_index}_busy_percent"
        busy_values = _sample_values(samples, busy_key)
        max_busy = round(max(busy_values), 2) if busy_values else None
        avg_busy = round(statistics.mean(busy_values), 2) if busy_values else None
        power_key = f"gpu_{gpu_index}_power_w"
        power_values = _sample_values(samples, power_key)
        max_power = round(max(power_values), 2) if power_values else None
        avg_power = round(statistics.mean(power_values), 2) if power_values else None
        memory_busy_key = f"gpu_{gpu_index}_memory_busy_percent"
        memory_busy_values = _sample_values(samples, memory_busy_key)
        max_memory_busy = round(max(memory_busy_values), 2) if memory_busy_values else None
        avg_memory_busy = round(statistics.mean(memory_busy_values), 2) if memory_busy_values else None
        backend_list = ", ".join(backends)
        target_label = str(target.get("target_id") or f"gpu{gpu_index}")
        device_class = str(target.get("device_class") or "").strip().lower()
        severity = ""
        message = ""
        details = {
            "gpu_index": gpu_index,
            "target_id": target_label,
            "workloads": sorted(workloads),
            "backends": backends,
            "load_classes": sorted(load_classes),
            "metric": busy_key,
            "max_busy_percent": max_busy,
            "avg_busy_percent": avg_busy,
            "max_power_w": max_power,
            "avg_power_w": avg_power,
            "max_memory_busy_percent": max_memory_busy,
            "avg_memory_busy_percent": avg_memory_busy,
            "backend_preference_3d": gpu_3d_backend_preference,
            "backend_resolved_3d": gpu_3d_backend_resolved,
            "device_class": device_class,
        }
        if load_classes <= {"compatibility"} and (max_busy is None or max_busy < 10.0):
            severity = "warning"
            message = (
                f"target GPU {target_label} reached only {max_busy if max_busy is not None else 'no'}% busy "
                + f"with compatibility backend(s) {backend_list}; treat this stage as a smoke test, not a stress result"
            )
        elif "mixed" in load_classes and (max_busy is None or max_busy < 15.0):
            severity = "warning"
            message = (
                f"target GPU {target_label} reached only {max_busy if max_busy is not None else 'no'}% busy "
                + f"with mixed-load backend(s) {backend_list}; this stage did not produce meaningful GPU stress"
            )
        elif "high_load" in load_classes:
            expected_avg_busy = 70.0
            expected_max_busy = 90.0
            if avg_busy is None or max_busy is None:
                severity = "warning"
                message = (
                    f"target GPU {target_label} did not expose enough busy telemetry to judge maintained backend(s) {backend_list}"
                )
                details.update(
                    {
                        "expected_avg_busy_percent": expected_avg_busy,
                        "expected_max_busy_percent": expected_max_busy,
                    }
                )
            elif avg_busy < expected_avg_busy or max_busy < expected_max_busy:
                severity = "warning"
                message = (
                    f"target GPU {target_label} under-drove maintained backend(s) {backend_list}: "
                    + f"avg busy {avg_busy}% / max busy {max_busy}% "
                    + f"(expected roughly avg >= {expected_avg_busy}% and max >= {expected_max_busy}%)"
                )
                details.update(
                    {
                        "expected_avg_busy_percent": expected_avg_busy,
                        "expected_max_busy_percent": expected_max_busy,
                    }
                )
        elif "diagnostic" in load_classes:
            severity = "info"
            if device_class == "discrete" and avg_power is not None and avg_power < 70.0:
                message = (
                    f"target GPU {target_label} validated diagnostic backend(s) {backend_list} with clean telemetry, "
                    + f"but averaged only {avg_power}W; treat this as Vulkan routing/transfer validation, not shader power saturation"
                )
            else:
                message = (
                    f"target GPU {target_label} used diagnostic backend(s) {backend_list}; treat this as API routing/transfer validation, not a saturation result"
                )
            details.update(
                {
                    "diagnostic_backend": True,
                    "saturation_result": False,
                }
            )
        if severity and message:
            events.append(
                create_stability_event(
                    "gpu_backend_effectiveness",
                    severity,
                    stage_name,
                    busy_key,
                    message,
                    details,
                )
            )
    return events
