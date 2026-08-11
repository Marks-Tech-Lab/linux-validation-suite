#!/usr/bin/env python3
"""Single-snapshot stage system-memory budget planning."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Dict, Iterable, List, Optional

from Modules.lvs_gpu_worker_plan import GpuWorkerSpec
from Modules.lvs_gpu_allocation_plan import plan_gpu_allocation_chunks
from Modules.lvs_runtime_memory_guard import runtime_memory_thresholds


MIB = 1024 ** 2
GIB = 1024 ** 3


@dataclass(frozen=True)
class SystemMemoryConsumer:
    consumer_id: str
    kind: str
    requested_bytes: int
    minimum_viable_bytes: int
    target_id: str = ""
    backend: str = ""
    device_capacity_bytes: int = 0
    original_requested_bytes: int = 0
    target_multiplier: int = 1
    fixed_commitment_bytes: int = 0


def system_memory_safety_reserve_bytes(total_bytes: int) -> int:
    total = max(0, int(total_bytes or 0))
    if total <= 0:
        return 0
    if total <= GIB:
        return min(256 * MIB, max(8 * MIB, total // 4))
    return min(GIB, max(256 * MIB, total // 8))


def system_memory_budget_bytes(total_bytes: int, available_bytes: int) -> Dict[str, int]:
    total = max(0, int(total_bytes or 0))
    available = max(0, int(available_bytes or 0))
    if total > 0:
        available = min(available, total)
    reserve = system_memory_safety_reserve_bytes(total)
    return {
        "system_memory_total_bytes": total,
        "system_memory_available_bytes": available,
        "system_memory_safety_reserve_bytes": reserve,
        "system_memory_budget_bytes": max(0, available - reserve),
    }


def requested_ram_target_bytes(allocation_percent: int, total_bytes: int) -> int:
    percent = max(1, min(95, int(allocation_percent or 0)))
    return max(0, int(max(0, int(total_bytes or 0)) * (percent / 100.0)))


def allocate_system_memory_consumers(
    consumers: Iterable[SystemMemoryConsumer],
    budget_bytes: int,
) -> Dict[str, Any]:
    items = [
        replace(
            consumer,
            requested_bytes=max(0, int(consumer.requested_bytes or 0)),
            minimum_viable_bytes=max(0, int(consumer.minimum_viable_bytes or 0)),
        )
        for consumer in consumers
        if int(consumer.requested_bytes or 0) > 0
    ]
    budget = max(0, int(budget_bytes or 0))
    requested_total = sum(item.requested_bytes for item in items)
    minimum_total = sum(min(item.requested_bytes, item.minimum_viable_bytes) for item in items)
    if not items:
        return {"valid": True, "reason": "no_budgeted_consumers", "allocations": {}, "requested_total_bytes": 0}
    if budget < minimum_total:
        return {
            "valid": False,
            "reason": "insufficient_budget_for_minimum_viable_allocations",
            "allocations": {item.consumer_id: 0 for item in items},
            "requested_total_bytes": requested_total,
            "minimum_total_bytes": minimum_total,
        }
    if requested_total <= budget:
        return {
            "valid": True,
            "reason": "requested_targets_fit",
            "allocations": {item.consumer_id: item.requested_bytes for item in items},
            "requested_total_bytes": requested_total,
            "minimum_total_bytes": minimum_total,
        }

    minima = {item.consumer_id: min(item.requested_bytes, item.minimum_viable_bytes) for item in items}
    remaining = budget - sum(minima.values())
    weights = {item.consumer_id: max(0, item.requested_bytes - minima[item.consumer_id]) for item in items}
    weight_total = sum(weights.values())
    allocations = dict(minima)
    if remaining > 0 and weight_total > 0:
        distributed = 0
        for item in items:
            share = int(remaining * (weights[item.consumer_id] / float(weight_total)))
            allocations[item.consumer_id] += share
            distributed += share
        leftover = remaining - distributed
        for item in sorted(items, key=lambda value: (-weights[value.consumer_id], value.consumer_id)):
            if leftover <= 0:
                break
            capacity = item.requested_bytes - allocations[item.consumer_id]
            if capacity <= 0:
                continue
            addition = min(capacity, leftover)
            allocations[item.consumer_id] += addition
            leftover -= addition
    return {
        "valid": True,
        "reason": "proportional_rebalance_after_minimums",
        "allocations": allocations,
        "requested_total_bytes": requested_total,
        "minimum_total_bytes": minimum_total,
    }


def gpu_worker_system_memory_consumer(
    worker: GpuWorkerSpec,
    *,
    system_pool_bytes: int = 0,
) -> Optional[SystemMemoryConsumer]:
    if worker.gpu_memory_kind not in {"shared", "unknown"} or not worker.system_memory_budget_participation:
        return None
    requested = max(0, int(worker.target_vram_bytes or 0))
    fixed_commitment = max(0, int(worker.system_memory_fixed_commitment_bytes or 0))
    percentage_target_workload = worker.workload == "vram" or worker.compute_variant == "stateful_memory"
    if worker.gpu_memory_kind == "shared" and int(worker.requested_gpu_memory_percent or 0) > 0 and percentage_target_workload:
        percent = max(1, min(95, int(worker.requested_gpu_memory_percent)))
        backend_capacity = max(
            0,
            int(worker.backend_addressable_capacity_bytes or worker.shared_addressable_capacity_bytes or 0),
        )
        if backend_capacity > 0:
            requested = int(backend_capacity * (percent / 100.0))
        else:
            # Unknown total GPU capability: percentage expresses workload
            # intent against the only truthful upper bound, the safe stage
            # pool. This remains explicitly not a proven GPU capacity.
            requested = int(max(0, int(system_pool_bytes or 0)) * (percent / 100.0))
    if requested <= 0 and fixed_commitment <= 0:
        return None
    multiplier = max(1, int(worker.system_memory_commitment_multiplier or 1))
    target_request = requested
    system_commitment = target_request * multiplier + fixed_commitment
    return SystemMemoryConsumer(
        consumer_id=worker.memory_budget_consumer_id,
        kind=(
            "shared_gpu_vram"
            if worker.gpu_memory_kind == "shared" and worker.workload == "vram"
            else "shared_gpu_3d"
            if worker.gpu_memory_kind == "shared"
            else "unknown_gpu_memory_conservative"
        ),
        requested_bytes=system_commitment,
        minimum_viable_bytes=min(requested, max(0, int(worker.minimum_viable_allocation_bytes or 0))) * multiplier + fixed_commitment,
        target_id=worker.target_id,
        backend=worker.backend,
        device_capacity_bytes=max(
            0,
            int(worker.backend_addressable_capacity_bytes or worker.shared_addressable_capacity_bytes or 0),
        ),
        original_requested_bytes=target_request,
        target_multiplier=multiplier,
        fixed_commitment_bytes=fixed_commitment,
    )


def cap_shared_gpu_device_requests(consumers: Iterable[SystemMemoryConsumer]) -> List[SystemMemoryConsumer]:
    """Cap aggregate controlled workers to one known shared-device ceiling."""

    items = list(consumers)
    grouped: Dict[str, List[int]] = {}
    for index, item in enumerate(items):
        if item.kind.startswith("shared_gpu") and item.target_id and item.device_capacity_bytes > 0:
            grouped.setdefault(item.target_id, []).append(index)
    for indexes in grouped.values():
        capacity = min(items[index].device_capacity_bytes for index in indexes)
        requested = sum(
            max(0, (items[index].requested_bytes - items[index].fixed_commitment_bytes) // items[index].target_multiplier)
            for index in indexes
        )
        if requested <= capacity:
            continue
        device_items = [
            replace(
                items[index],
                requested_bytes=max(
                    0,
                    (items[index].requested_bytes - items[index].fixed_commitment_bytes)
                    // items[index].target_multiplier,
                ),
                minimum_viable_bytes=max(
                    0,
                    (items[index].minimum_viable_bytes - items[index].fixed_commitment_bytes)
                    // items[index].target_multiplier,
                ),
            )
            for index in indexes
        ]
        allocation = allocate_system_memory_consumers(device_items, capacity)
        resolved = dict(allocation.get("allocations") or {})
        for index in indexes:
            item = items[index]
            capped_target = max(0, int(resolved.get(item.consumer_id, 0) or 0))
            items[index] = replace(
                item,
                requested_bytes=capped_target * item.target_multiplier + item.fixed_commitment_bytes,
            )
    return items


def build_stage_system_memory_plan(
    *,
    stage: Any,
    gpu_workers: List[GpuWorkerSpec],
    total_bytes: int,
    available_bytes: int,
    memory_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    bounds = system_memory_budget_bytes(total_bytes, available_bytes)
    consumers: List[SystemMemoryConsumer] = []
    if stage.modules.memory.enabled:
        consumers.append(
            SystemMemoryConsumer(
                consumer_id="system_ram",
                kind="system_ram",
                requested_bytes=requested_ram_target_bytes(stage.modules.memory.allocation_percent, total_bytes),
                minimum_viable_bytes=128 * MIB,
                backend="memory",
            )
        )
    unbudgeted_gpu_workers: List[Dict[str, Any]] = []
    for worker in gpu_workers:
        consumer = gpu_worker_system_memory_consumer(
            worker,
            system_pool_bytes=bounds["system_memory_budget_bytes"],
        )
        if consumer is not None:
            consumers.append(consumer)
            if "physical_commitment_unknown" in str(worker.memory_budgetability or ""):
                unbudgeted_gpu_workers.append(
                    {
                        "target_id": worker.target_id,
                        "backend": worker.backend,
                        "reason": worker.memory_budgetability,
                    }
                )
        elif worker.gpu_memory_kind == "shared" and worker.workload == "gpu_3d":
            unbudgeted_gpu_workers.append(
                {
                    "target_id": worker.target_id,
                    "backend": worker.backend,
                    "reason": worker.memory_budgetability or "no_enforceable_byte_target",
                }
            )
    consumers = cap_shared_gpu_device_requests(consumers)
    allocation = allocate_system_memory_consumers(consumers, bounds["system_memory_budget_bytes"])
    allocations = dict(allocation.get("allocations") or {})
    consumer_rows = []
    for consumer in consumers:
        resolved = max(0, int(allocations.get(consumer.consumer_id, 0) or 0))
        consumer_rows.append(
            {
                **asdict(consumer),
                "resolved_bytes": resolved,
                "requested_target_bytes": int(consumer.original_requested_bytes or consumer.requested_bytes),
                "resolved_target_bytes": max(
                    0,
                    (resolved - consumer.fixed_commitment_bytes) // max(1, consumer.target_multiplier),
                ),
                "reduced": resolved < consumer.requested_bytes,
            }
        )
    planned_total = sum(int(row["resolved_bytes"]) for row in consumer_rows)
    device_aggregates: Dict[str, Dict[str, Any]] = {}
    for row in consumer_rows:
        if not str(row["kind"]).startswith(("shared_gpu", "unknown_gpu")):
            continue
        aggregate = device_aggregates.setdefault(
            str(row["target_id"] or "unknown"),
            {"target_id": str(row["target_id"] or ""), "consumer_ids": [], "requested_bytes": 0, "resolved_bytes": 0},
        )
        aggregate["consumer_ids"].append(row["consumer_id"])
        aggregate["requested_bytes"] += int(row.get("original_requested_bytes") or row["requested_bytes"])
        aggregate["resolved_bytes"] += int(row["resolved_target_bytes"])
    return {
        **bounds,
        "mem_available_source": str((memory_snapshot or {}).get("mem_available_source") or "unknown"),
        "mem_available_fallback": bool((memory_snapshot or {}).get("mem_available_fallback")),
        "linux_memory_diagnostics": {
            key: int((memory_snapshot or {}).get(key) or 0)
            for key in (
                "mem_free_bytes",
                "cached_bytes",
                "buffers_bytes",
                "sreclaimable_bytes",
                "shmem_bytes",
                "swap_total_bytes",
                "swap_free_bytes",
            )
        },
        "valid": bool(allocation.get("valid")),
        "resolution_reason": str(allocation.get("reason") or ""),
        "consumers": consumer_rows,
        "allocations": allocations,
        "ram_requested_bytes": next((row["requested_bytes"] for row in consumer_rows if row["consumer_id"] == "system_ram"), 0),
        "ram_target_bytes": int(allocations.get("system_ram", 0) or 0),
        "total_planned_system_memory_bytes": planned_total,
        "remaining_system_memory_headroom_bytes": max(0, bounds["system_memory_budget_bytes"] - planned_total),
        "unbudgeted_shared_gpu_workers": unbudgeted_gpu_workers,
        "shared_gpu_device_aggregates": list(device_aggregates.values()),
        "runtime_memory_guard_policy": {
            "enabled": bool(consumer_rows or unbudgeted_gpu_workers),
            **runtime_memory_thresholds(bounds["system_memory_safety_reserve_bytes"]),
        },
    }


def apply_stage_system_memory_plan(
    workers: Iterable[GpuWorkerSpec],
    plan: Dict[str, Any],
) -> List[GpuWorkerSpec]:
    allocations = dict(plan.get("allocations") or {})
    consumer_rows = {str(row.get("consumer_id") or ""): row for row in plan.get("consumers", [])}
    resolved_workers: List[GpuWorkerSpec] = []
    for worker in workers:
        if not worker.system_memory_budget_participation:
            resolved_workers.append(worker)
            continue
        resolved_commitment = max(0, int(allocations.get(worker.memory_budget_consumer_id, worker.target_vram_bytes) or 0))
        consumer_row = consumer_rows.get(worker.memory_budget_consumer_id, {})
        multiplier = max(1, int(consumer_row.get("target_multiplier") or worker.system_memory_commitment_multiplier or 1))
        fixed_commitment = max(0, int(consumer_row.get("fixed_commitment_bytes") or worker.system_memory_fixed_commitment_bytes or 0))
        resolved = max(0, (resolved_commitment - fixed_commitment) // multiplier)
        truthful_requested = max(
            0,
            int(consumer_row.get("original_requested_bytes") or worker.requested_gpu_memory_target_bytes or 0),
        )
        original_commitment = truthful_requested * multiplier + fixed_commitment
        if resolved < truthful_requested:
            cap_reason = (
                "shared_device_aggregate_capacity_cap"
                if int(consumer_row.get("requested_bytes") or original_commitment) < original_commitment
                else "stage_system_memory_budget_rebalance"
            )
        else:
            cap_reason = worker.target_cap_reason or "requested_target_fit"
        practical_chunk = (
            512 * MIB
            if worker.backend == "python_opencl"
            else 64 * MIB
            if worker.backend == "python_egl_gles2"
            else 0
        )
        chunk_plan = plan_gpu_allocation_chunks(
            target_bytes=resolved,
            max_single_allocation_bytes=worker.max_single_allocation_bytes,
            max_buffer_or_object_bytes=worker.max_buffer_or_object_bytes,
            allocation_granularity_bytes=worker.allocation_granularity_bytes,
            max_allocation_count=worker.max_allocation_count,
            practical_chunk_bytes=practical_chunk,
        )
        resolved_workers.append(
            replace(
                worker,
                target_vram_bytes=resolved,
                requested_gpu_memory_target_bytes=truthful_requested,
                planned_gpu_memory_target_bytes=resolved,
                planned_allocation_chunks=list(chunk_plan["chunks"]),
                planned_allocation_chunk_count=int(chunk_plan["chunk_count"]),
                target_cap_reason=(
                    cap_reason
                ),
            )
        )
    return resolved_workers
