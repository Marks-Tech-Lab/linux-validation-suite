#!/usr/bin/env python3
"""GPU stage target detail shaping helpers."""

from __future__ import annotations

from typing import Any, Dict, Iterable


def gpu_index_from_metric_key(key: str) -> int:
    try:
        return int(str(key).removeprefix("gpu_").split("_", 1)[0])
    except Exception:
        return 0


def stage_target_gpu_details_from_processes(stage_processes: Iterable[Any]) -> Dict[int, Dict[str, Any]]:
    targets: Dict[int, Dict[str, Any]] = {}
    for entry in stage_processes:
        spec = getattr(entry, "gpu_spec", None)
        if spec is None:
            continue
        gpu_index = int(getattr(spec, "gpu_index", 0))
        target = targets.setdefault(
            gpu_index,
            {
                "gpu_index": gpu_index,
                "target_id": getattr(spec, "target_id", None) or getattr(spec, "card", None) or f"gpu{gpu_index}",
                "workloads": [],
                "backends": [],
                "device_class": str(getattr(spec, "device_class", "") or ""),
            },
        )
        workload = str(getattr(spec, "workload", "") or "").strip()
        backend = str(getattr(spec, "backend", "") or "").strip()
        if workload and workload not in target["workloads"]:
            target["workloads"].append(workload)
        if backend and backend not in target["backends"]:
            target["backends"].append(backend)
    return targets


def stage_target_gpu_details_from_worker_dicts(workers: Iterable[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    targets: Dict[int, Dict[str, Any]] = {}
    for worker in workers:
        try:
            gpu_index = int(worker.get("gpu_index", 0))
        except Exception:
            gpu_index = 0
        target = targets.setdefault(
            gpu_index,
            {
                "gpu_index": gpu_index,
                "target_id": str(worker.get("target_id", "") or worker.get("card", "") or f"gpu{gpu_index}"),
                "workloads": [],
                "backends": [],
                "device_class": str(worker.get("device_class", "") or ""),
            },
        )
        workload = str(worker.get("workload", "") or "").strip()
        backend = str(worker.get("backend", "") or "").strip()
        if workload and workload not in target["workloads"]:
            target["workloads"].append(workload)
        if backend and backend not in target["backends"]:
            target["backends"].append(backend)
    return targets
