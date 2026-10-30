"""Reporting-only VRAM readback/allocation facts; never physical residency proof."""
from __future__ import annotations

from typing import Any

from .lvs_worker_integrity import worker_result_successful, worker_verification_required


def is_vram_worker(payload: dict[str, Any]) -> bool:
    return (payload.get("kind") == "gpu"
            and (payload.get("mode") or payload.get("workload")) == "vram")


def _bytes(payload: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        if key in payload:
            value = payload[key]
            return value if type(value) is int and value >= 0 else None
    return None


def _readback_passes(payload: dict[str, Any]) -> int | None:
    # EGL's aggregate includes render/marker checks, not just texture readback.
    key = ("vram_verification_passes" if payload.get("suite_verification") == "render_readback"
           or payload.get("backend") == "python_egl_gles2" else "verification_passes")
    value = payload.get(key)
    return value if type(value) is int and value >= 0 else None


def vram_readback_status(payload: dict[str, Any]) -> str:
    """Positive counts are observations, not proof of error-free verification.

    Existing runtime predicates retain their legacy semantics. This stricter
    presentation assessment needs an applicable readback method, successful
    worker evidence and explicit zero errors. Missing legacy fields stay unknown.
    """
    if not is_vram_worker(payload):
        return "insufficient_evidence"
    for key, value in payload.items():
        if key in {"error_count", "gl_error_count", "verification_failures"} or key.endswith("_mismatch_count"):
            if type(value) is not int or value != 0:
                return "failed_or_incomplete"
        if key in {"last_error", "first_error", "first_error_record", "mismatch_details", "errors"}:
            if value not in (None, "", {}, []):
                return "failed_or_incomplete"
        if (key == "first_error_kind" and value != "") or (key == "first_error_recorded" and value is not False):
            return "failed_or_incomplete"
        if key in {"verification_complete", "verification_satisfied", "initial_verification_completed",
                   "periodic_verification_completed", "final_verification_completed", "cleanup_complete",
                   "vram_verification_satisfied"}:
            if value is not True:
                return "failed_or_incomplete"
    if str(payload.get("status") or "").lower() in {"error", "fail", "failed", "crashed", "aborted"}:
        return "failed_or_incomplete"
    if "observed_exit_code" in payload and (type(payload["observed_exit_code"]) is not int or payload["observed_exit_code"] != 0):
        return "failed_or_incomplete"
    method = payload.get("suite_verification")
    applicable = (method in ("render_readback", "memory_readback", "transfer_readback", "compute_readback", "readback")
                  or payload.get("backend") in ("python_egl_gles2", "python_opencl", "python_vulkan_transfer"))
    if payload.get("verification_required") is False:
        return "failed_or_incomplete" if applicable else "not_required"
    passes = _readback_passes(payload)
    if (not applicable or not worker_verification_required(payload)
            or type(payload.get("error_count")) is not int
            or type(passes) is not int or passes <= 0):
        return "insufficient_evidence"
    return "verified" if worker_result_successful(payload) else "failed_or_incomplete"


def vram_allocation_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    """Separate commanded targets, objects, sampled readback and commitment.

    No current readback worker proves exhaustive byte coverage. In particular,
    allocated/actual_allocated byte counters do not attest physical residency.
    """
    status = vram_readback_status(payload)
    return {
        "allocation_safety": payload.get("allocation_safety"),
        "materialized_target_bytes": _bytes(payload, "materialized_target_bytes"),
        "allocation_feasibility": payload.get("allocation_feasibility"),
        "planned_allocation_feasibility": payload.get("planned_allocation_feasibility"),
        "allocation_timing_evidence": payload.get("allocation_timing_evidence"),
        "allocation_progress_evidence": payload.get("allocation_progress_evidence"),
        "egl_selected_device": payload.get("egl_selected_device"),
        "egl_device_exact_match": payload.get("egl_device_exact_match"),
        "requested_target_bytes": _bytes(payload, "requested_target_bytes", "target_vram_bytes", "target_buffer_bytes"),
        "assigned_target_bytes": _bytes(payload, "assigned_target_bytes", "target_vram_bytes", "target_buffer_bytes"),
        "active_target_bytes": _bytes(payload, "active_target_vram_bytes"),
        "nominal_allocated_bytes": _bytes(payload, "nominal_allocated_texture_bytes", "allocated_vram_bytes", "buffer_bytes", "buffer_allocation_bytes"),
        "actual_allocated_bytes": _bytes(payload, "actual_allocated_bytes"),
        "readback_verification_status": status,
        "readback_verification_passes": _readback_passes(payload),
        "verification_coverage": "sampled_not_exhaustive" if status == "verified" else "not_established",
        "verified_coverage_bytes": None,
        "physical_commitment_known": (payload.get("physical_commitment_known") is True
                                      and _bytes(payload, "physical_committed_bytes") is not None),
        "physical_committed_bytes": (_bytes(payload, "physical_committed_bytes")
                                     if payload.get("physical_commitment_known") is True else None),
    }
