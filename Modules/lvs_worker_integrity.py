from __future__ import annotations

from typing import Any, Dict, List


_SUCCESS_STATUSES = {"ok", "pass", "passed", "success", "successful"}
_NON_REQUIRED_VERIFICATION_MODES = {"", "none", "not_applicable", "telemetry_only"}


def worker_verification_required(payload: Dict[str, Any]) -> bool:
    if payload.get("kernel_flavor") == "neon_fp32_fma" or payload.get("verification_contract") == "neon_fp32_fma_v1":
        return True
    for key in ("verification_required", "VerificationRequired"):
        if key in payload:
            return bool(payload.get(key))
    mode = str(
        payload.get("suite_verification")
        or payload.get("SuiteVerification")
        or ""
    ).strip().lower()
    return mode not in _NON_REQUIRED_VERIFICATION_MODES


def worker_verification_passes(payload: Dict[str, Any]) -> int:
    try:
        return int(
            payload.get("verification_passes")
            or payload.get("VerificationPasses")
            or payload.get("verify_passes")
            or 0
        )
    except Exception:
        return 0


def worker_verification_satisfied(payload: Dict[str, Any]) -> bool:
    if payload.get("kernel_flavor") == "neon_fp32_fma" or payload.get("verification_contract") == "neon_fp32_fma_v1":
        if not _neon_fp32_fma_verification_satisfied(payload):
            return False
    if not worker_verification_required(payload):
        return True
    if worker_verification_passes(payload) <= 0:
        return False
    if "verification_complete" in payload and not bool(payload.get("verification_complete")):
        return False
    # New workers that explicitly promise bounded initial/final verification
    # must complete both. Historical payloads do not carry these keys and keep
    # their established pass-count contract.
    for snake_key, compat_key in (
        ("initial_verification_completed", "InitialVerificationCompleted"),
        ("final_verification_completed", "FinalVerificationCompleted"),
    ):
        if snake_key in payload or compat_key in payload:
            value = payload.get(snake_key, payload.get(compat_key))
            if value is not None and not bool(value):
                return False
    return True


def _neon_fp32_fma_verification_satisfied(payload: Dict[str, Any]) -> bool:
    """Versioned contract: aggregate counters cannot conceal an unverified core."""
    try:
        targets = payload["target_cpu_ids"]
        details = payload["threads_detail"]
        count = int(payload["requested_thread_count"])
        if (count <= 0 or count != int(payload["actual_worker_count"])
                or len(targets) != count or len(set(targets)) != count
                or len(details) != count or payload.get("verification_complete") is not True
                or payload.get("kernel_flavor") != "neon_fp32_fma"
                or payload.get("verification_contract") != "neon_fp32_fma_v1"
                or payload.get("verification_method") != "integer_binary32_fma_reference"
                or payload.get("operation_family") != "fp32_fused_multiply_add"
                or payload.get("rounding_environment") != "nearest_ties_even_no_flush"
                or payload.get("verification_version") != 1
                or any(payload.get(key) is not True for key in (
                    "initial_verification_completed", "periodic_verification_completed",
                    "final_verification_completed"))
                or int(payload.get("error_count", 0)) != 0):
            return False
        seen = set()
        blocks = 0
        for row in details:
            cpu = row["affinity_target_cpu"]
            if (cpu not in targets or cpu in seen or row.get("observed_cpu") != cpu
                    or row.get("affinity_applied") is not True
                    or row.get("affinity_required") is not True
                    or int(row.get("error_count", 0)) != 0
                    or int(row.get("arithmetic_verified_blocks", 0)) < 3
                    or int(row.get("verify_passes", 0)) != int(row.get("arithmetic_verified_blocks", 0))
                    or any(row.get(key) is not True for key in (
                        "initial_verification_completed", "periodic_verification_completed",
                        "final_verification_completed"))):
                return False
            seen.add(cpu)
            blocks += int(row["arithmetic_verified_blocks"])
        return blocks == int(payload["arithmetic_verified_blocks"]) == worker_verification_passes(payload)
    except (KeyError, TypeError, ValueError):
        return False


def worker_cleanup_satisfied(payload: Dict[str, Any]) -> bool:
    """Historical workers pass; workers declaring cleanup state must finish it."""
    for key in ("cleanup_complete", "CleanupComplete"):
        if key in payload:
            return bool(payload.get(key))
    return True


def worker_result_successful(payload: Dict[str, Any]) -> bool:
    status = str(payload.get("status") or payload.get("Status") or "").strip().lower()
    return status in _SUCCESS_STATUSES and worker_verification_satisfied(payload) and worker_cleanup_satisfied(payload)


def worker_integrity_error_count(worker_results: List[Dict[str, Any]]) -> int:
    error_keys = (
        "error_count",
        "gl_error_count",
        "draw_mismatch_count",
        "vram_mismatch_count",
        "compute_mismatch_count",
        "transfer_mismatch_count",
        "child_failure_count",
    )
    total = 0
    for payload in worker_results:
        payload_error_count = 0
        for key in error_keys:
            try:
                payload_error_count += int(payload.get(key) or 0)
            except Exception:
                continue
        status_failed = str(payload.get("status") or "").lower() in {"error", "failed", "fail"}
        total += payload_error_count
        if status_failed:
            total += 1
        elif payload_error_count <= 0 and (
            not worker_verification_satisfied(payload) or not worker_cleanup_satisfied(payload)
        ):
            total += 1
    return total
