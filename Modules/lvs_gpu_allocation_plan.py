#!/usr/bin/env python3
"""Pure GPU allocation chunk planning shared by capability and worker tests."""

from __future__ import annotations

from typing import Any, Dict, List


def _positive_min(*values: int) -> int:
    candidates = [int(value) for value in values if int(value or 0) > 0]
    return min(candidates) if candidates else 0


def plan_gpu_allocation_chunks(
    *,
    target_bytes: int,
    max_single_allocation_bytes: int = 0,
    max_buffer_or_object_bytes: int = 0,
    allocation_granularity_bytes: int = 1,
    max_allocation_count: int = 0,
    practical_chunk_bytes: int = 0,
) -> Dict[str, Any]:
    """Split one worker target into legal aggregate-bounded allocation requests.

    A zero capability limit means unknown, not zero capability. The final chunk
    is rounded down to the API granularity, so planned bytes never exceed the
    assigned worker target.
    """

    target = max(0, int(target_bytes or 0))
    granularity = max(1, int(allocation_granularity_bytes or 1))
    legal_chunk_limit = _positive_min(
        max_single_allocation_bytes,
        max_buffer_or_object_bytes,
        practical_chunk_bytes,
    )
    if legal_chunk_limit <= 0:
        legal_chunk_limit = target
    legal_chunk_limit -= legal_chunk_limit % granularity
    count_limit = max(0, int(max_allocation_count or 0))
    chunks: List[int] = []
    remaining = target
    while remaining >= granularity and legal_chunk_limit >= granularity:
        if count_limit > 0 and len(chunks) >= count_limit:
            break
        chunk = min(legal_chunk_limit, remaining)
        chunk -= chunk % granularity
        if chunk < granularity:
            break
        chunks.append(chunk)
        remaining -= chunk
    planned = sum(chunks)
    return {
        "target_bytes": target,
        "chunks": chunks,
        "planned_bytes": planned,
        "shortfall_bytes": max(0, target - planned),
        "chunk_count": len(chunks),
        "legal_chunk_limit_bytes": legal_chunk_limit,
        "allocation_granularity_bytes": granularity,
        "max_allocation_count": count_limit,
        "complete": planned == target,
        "cap_reason": (
            "target_fits_constraints"
            if planned == target
            else "allocation_count_limit"
            if count_limit > 0 and len(chunks) >= count_limit
            else "allocation_granularity"
        ),
    }


def allocation_attainment(
    *,
    assigned_target_bytes: int,
    achieved_bytes: int,
    verification_passes: int = 0,
    runtime_failed: bool = False,
) -> Dict[str, Any]:
    """Normalize allocation outcome using LVS's existing 60/85% verdict bands."""

    target = max(0, int(assigned_target_bytes or 0))
    achieved = max(0, min(target, int(achieved_bytes or 0))) if target > 0 else max(0, int(achieved_bytes or 0))
    ratio = (achieved / float(target)) if target > 0 else None
    if runtime_failed:
        outcome = "runtime_failure_after_partial_allocation" if achieved > 0 else "allocation_failed"
        valid = False
    elif target <= 0:
        outcome = "no_assigned_target"
        valid = False
    elif achieved <= 0:
        outcome = "allocation_failed"
        valid = False
    elif ratio is not None and ratio < 0.60:
        outcome = "insufficient_partial_allocation"
        valid = False
    elif ratio is not None and ratio < 0.85:
        outcome = "partial_allocation"
        valid = True
    elif achieved < target:
        outcome = "substantial_partial_allocation"
        valid = True
    else:
        outcome = "full_target_achieved"
        valid = True
    return {
        "assigned_target_bytes": target,
        "actual_allocated_bytes": achieved,
        "allocation_ratio": round(ratio, 6) if ratio is not None else None,
        "allocation_outcome": outcome,
        "allocation_valid": valid,
        "allocation_verified": bool(valid and int(verification_passes or 0) > 0),
    }
