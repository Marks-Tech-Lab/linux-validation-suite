from __future__ import annotations

from typing import Any, Dict, List


_SUCCESS_STATUSES = {"ok", "pass", "passed", "success", "successful"}
_NON_REQUIRED_VERIFICATION_MODES = {"", "none", "not_applicable", "telemetry_only"}


def worker_verification_required(payload: Dict[str, Any]) -> bool:
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
            or 0
        )
    except Exception:
        return 0


def worker_verification_satisfied(payload: Dict[str, Any]) -> bool:
    return not worker_verification_required(payload) or worker_verification_passes(payload) > 0


def worker_result_successful(payload: Dict[str, Any]) -> bool:
    status = str(payload.get("status") or payload.get("Status") or "").strip().lower()
    return status in _SUCCESS_STATUSES and worker_verification_satisfied(payload)


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
        elif payload_error_count <= 0 and not worker_verification_satisfied(payload):
            total += 1
    return total
