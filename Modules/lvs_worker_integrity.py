from __future__ import annotations

from typing import Any, Dict, List


_SUCCESS_STATUSES = {"ok", "pass", "passed", "success", "successful"}
_NON_REQUIRED_VERIFICATION_MODES = {"", "none", "not_applicable", "telemetry_only"}
VERIFIED_FP32_KERNELS = frozenset({"neon_fp32_fma", "sve_fp32_fma"})


def verified_fp32_worker(payload: Dict[str, Any]) -> bool:
    kernel = payload.get("kernel_flavor")
    contract = payload.get("verification_contract")
    requested = payload.get("requested_kernel_flavor")
    return ((isinstance(kernel, str) and kernel in VERIFIED_FP32_KERNELS)
            or (isinstance(contract, str) and contract in {f"{k}_v1" for k in VERIFIED_FP32_KERNELS})
            or requested == "sve_fp32_fma")


def worker_verification_required(payload: Dict[str, Any]) -> bool:
    if verified_fp32_worker(payload):
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
    if verified_fp32_worker(payload):
        if not _verified_fp32_fma_verification_satisfied(payload):
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


def _zero_error_counter(value: Any) -> bool:
    # bool is an int subclass; coercion would also accept "0", False, and 0.0.
    # Native v1 counters are uint64 JSON integers, not optional observations.
    return type(value) is int and value == 0


def _fp32_error_details_absent(value: Any, kernel: str) -> bool:
    """Reject recorded errors, including nested contradictory error details.

    Native successful results omit first_error; optional null/empty objects are
    unambiguous empty sentinels. Progress-style flat details use kind="", zero
    expected/actual/iteration and lane 0; result-style no-error lane is -1.
    Capability errno and supplementary analysis/persistence quality are NOT
    arithmetic errors and are deliberately not inferred from arbitrary names.
    """
    if isinstance(value, list):
        return all(_fp32_error_details_absent(item, kernel) for item in value)
    if not isinstance(value, dict):
        return True
    for key, item in value.items():
        if key in {"kernel_flavor", "requested_kernel_flavor"}:
            if item != kernel:
                return False
        elif key == "verification_contract":
            if item != f"{kernel}_v1":
                return False
        elif key in {"verification_complete", "initial_verification_completed",
                     "periodic_verification_completed", "final_verification_completed"}:
            if item is not True:
                return False
        elif key in {"first_error", "first_error_record", "mismatch_details"}:
            if item is not None and not (type(item) is dict and not item):
                return False
        elif key == "first_error_recorded":
            if item is not False:
                return False
        elif key == "first_error_kind":
            if type(item) is not str or item != "":
                return False
        elif key == "first_error_lane":
            if type(item) is not int or not (item == -1 or (item == 0 and value.get("first_error_kind") == "")):
                return False
        elif key in {"first_error_expected", "first_error_actual", "first_error_iteration"}:
            if not _zero_error_counter(item):
                return False
        elif (key in {"error_count", "ErrorCount", "verification_failures", "nonfinite_count", "affinity_error_code"}
              or key.endswith("_mismatch_count") or key.endswith("_error_count")):
            if not _zero_error_counter(item):
                return False
        elif key in {"arithmetic_mismatch", "fp32_fma_mismatch", "mismatch"}:
            if item is not False and item is not None:
                return False
        elif key in {"verification_errors", "arithmetic_errors"}:
            if type(item) is not list or item:
                return False
        elif key in {"error", "last_error", "error_details"}:
            if item is not None and item != "" and not (type(item) is dict and not item):
                return False
        elif key == "errors":
            if type(item) is not list or item:
                return False
        if not _fp32_error_details_absent(item, kernel):
            return False
    return True


def _versioned_fp32_error_free(record: Dict[str, Any], kernel: str) -> bool:
    """Required error evidence for both implemented FP32 v1 contracts only."""
    if not _zero_error_counter(record.get("error_count")):
        return False
    if "status" in record and str(record["status"]).strip().lower() not in _SUCCESS_STATUSES:
        return False
    return _fp32_error_details_absent(record, kernel)


def _verified_fp32_fma_verification_satisfied(payload: Dict[str, Any]) -> bool:
    """Versioned contract: aggregate counters cannot conceal an unverified core."""
    try:
        targets = payload["target_cpu_ids"]
        details = payload["threads_detail"]
        kernel = payload.get("kernel_flavor")
        sve = kernel == "sve_fp32_fma"
        count = int(payload["requested_thread_count"])
        if (count <= 0 or count != int(payload["actual_worker_count"])
                or len(targets) != count or len(set(targets)) != count
                or len(details) != count or payload.get("verification_complete") is not True
                or kernel not in VERIFIED_FP32_KERNELS
                or payload.get("requested_kernel_flavor", kernel) != kernel
                or payload.get("verification_contract") != f"{kernel}_v1"
                or payload.get("verification_method") != "integer_binary32_fma_reference"
                or payload.get("operation_family") != "fp32_fused_multiply_add"
                or payload.get("rounding_environment") != "nearest_ties_even_no_flush"
                or payload.get("verification_version") != 1
                or type(payload.get("verification_version")) is not int
                or any(payload.get(key) is not True for key in (
                    "initial_verification_completed", "periodic_verification_completed",
                    "final_verification_completed"))
                or not _versioned_fp32_error_free(payload, kernel)):
            return False
        if sve:
            expected_isa = "test_integer_emulation" if payload.get("execution_implementation") == "test_integer_emulation" else "sve"
            expected_vl_source = "test_override" if expected_isa == "test_integer_emulation" else "linux_prctl_pr_sve_get_vl_per_thread"
            if (payload.get("actual_isa") != expected_isa or payload.get("accumulator_chains") != 8
                    or payload.get("fma_rounds_per_block") != 256
                    or payload.get("vector_length_source") != expected_vl_source
                    or payload.get("predicate_verification") != "four_active_witnesses_merge_and_guarded_masked_store"):
                return False
            if (not isinstance(targets, list) or any(type(cpu) is not int or cpu < 0 for cpu in targets)
                    or type(payload.get("requested_thread_count")) is not int
                    or type(payload.get("actual_worker_count")) is not int
                    or type(payload.get("arithmetic_verified_blocks")) is not int
                    or not 0 <= payload["arithmetic_verified_blocks"] <= (1 << 64) - 1
                    or type(payload.get("verify_passes")) is not int
                    or payload.get("affinity_attempted_count") != count
                    or payload.get("affinity_applied_count") != count
                    or payload.get("affinity_failed_count") != 0):
                return False
            if payload.get("execution_implementation") != "test_integer_emulation":
                hwcap = payload.get("isa_hwcap")
                if (type(hwcap) is not int or hwcap & ((1 << 22) | 1) != ((1 << 22) | 1)
                        or payload.get("isa_capability_source") != "linux_getauxval_at_hwcap_common_set"
                        or payload.get("execution_implementation") != "aarch64_sve_intrinsics"):
                    return False
        seen = set()
        blocks = 0
        for index, row in enumerate(details):
            cpu = row["affinity_target_cpu"]
            if (cpu not in targets or cpu in seen or row.get("observed_cpu") != cpu
                    or row.get("affinity_applied") is not True
                    or row.get("affinity_required") is not True
                    or not _versioned_fp32_error_free(row, kernel)
                    or int(row.get("arithmetic_verified_blocks", 0)) < 3
                    or int(row.get("verify_passes", 0)) != int(row.get("arithmetic_verified_blocks", 0))
                    or any(row.get(key) is not True for key in (
                        "initial_verification_completed", "periodic_verification_completed",
                        "final_verification_completed"))):
                return False
            if sve and not sve_thread_geometry_valid(row):
                return False
            if sve and (row.get("thread_index") != index or targets[index] != cpu
                        or type(row.get("arithmetic_verified_blocks")) is not int
                        or not 3 <= row["arithmetic_verified_blocks"] <= (1 << 64) - 1
                        or type(row.get("verify_passes")) is not int):
                return False
            seen.add(cpu)
            blocks += int(row["arithmetic_verified_blocks"])
        if blocks != int(payload["arithmetic_verified_blocks"]) or blocks != worker_verification_passes(payload):
            return False
        # Native verify_passes is authoritative. Optional historical aliases
        # must agree, rather than letting truthiness precedence hide conflict.
        return all(type(payload[key]) is int and payload[key] == blocks
                   for key in ("verify_passes", "verification_passes", "VerificationPasses") if key in payload)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def sve_thread_geometry_valid(row: Dict[str, Any]) -> bool:
    """Validate authored geometry, never trust arbitrary operation multipliers."""
    vl = row.get("vector_length_bytes")
    lanes = row.get("active_fp32_lanes")
    fpcr = row.get("fpcr")
    return (type(vl) is int and 16 <= vl <= 256 and vl % 16 == 0
            and type(lanes) is int and lanes == vl // 4
            and type(row.get("vector_length_flags")) is int and row["vector_length_flags"] >= 0
            and row.get("vector_length_errno") == 0
            and row.get("lanes_per_block") == lanes * 8
            and row.get("stress_lane_fmas_per_block") == lanes * 8 * 256
            and row.get("witness_lane_fmas_per_block") == 4
            and type(fpcr) is int and fpcr >= 0
            and fpcr & ((3 << 22) | (1 << 24) | (31 << 8) | (1 << 15)) == 0)


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
                value = int(payload.get(key) or 0)
                # Invalid negative v1 counters cannot cancel the blocking
                # verification failure (or another worker's real errors).
                payload_error_count += max(0, value) if verified_fp32_worker(payload) else value
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
