from __future__ import annotations

from typing import Any, Dict, List


_SUCCESS_STATUSES = {"ok", "pass", "passed", "success", "successful"}
_NON_REQUIRED_VERIFICATION_MODES = {"", "none", "not_applicable", "telemetry_only"}
from .lvs_cpu_architecture import VNNI_CPU_KERNELS

VERIFIED_FP32_KERNELS = frozenset({"neon_fp32_fma", "sve_fp32_fma"})


def verified_fp32_worker(payload: Dict[str, Any]) -> bool:
    kernel = payload.get("kernel_flavor")
    contract = payload.get("verification_contract")
    requested = payload.get("requested_kernel_flavor")
    return ((isinstance(kernel, str) and kernel in VERIFIED_FP32_KERNELS)
            or (isinstance(contract, str) and contract in {f"{k}_v1" for k in VERIFIED_FP32_KERNELS})
            or requested == "sve_fp32_fma")


def verified_vnni_worker(payload: Dict[str, Any]) -> bool:
    return any(isinstance(payload.get(key), str) and payload[key] in VNNI_CPU_KERNELS
               for key in ("kernel_flavor", "requested_kernel_flavor")) or (
        isinstance(payload.get("verification_contract"), str)
        and payload["verification_contract"] in {f"{k}_v1" for k in VNNI_CPU_KERNELS})


def worker_verification_required(payload: Dict[str, Any]) -> bool:
    if verified_fp32_worker(payload) or verified_vnni_worker(payload):
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
    if verified_vnni_worker(payload) and not _verified_vnni_satisfied(payload):
        return False
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
    for key in ("allocation_claim_cleanup_error", "AllocationClaimCleanupError"):
        if key in payload and payload[key] not in (None, ""):
            return False
    for key in ("cleanup_complete", "CleanupComplete"):
        if key in payload and not bool(payload[key]):
            return False
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
                payload_error_count += max(0, value) if verified_fp32_worker(payload) or verified_vnni_worker(payload) else value
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


def _verified_vnni_satisfied(payload: Dict[str, Any]) -> bool:
    """Exact v1 all-thread signed/unsigned dot-product contract; no FP32 claims."""
    try:
        kernel = payload["kernel_flavor"]
        count, targets, rows = payload["requested_thread_count"], payload["target_cpu_ids"], payload["threads_detail"]
        flags = ("initial_verification_completed", "periodic_verification_completed", "final_verification_completed")
        if (kernel not in VNNI_CPU_KERNELS or payload.get("requested_kernel_flavor", kernel) != kernel
                or payload.get("verification_contract") != f"{kernel}_v1"
                or type(payload.get("verification_version")) is not int or payload["verification_version"] != 1
                or payload.get("verification_required") is not True
                or payload.get("verification_complete") is not True
                or payload.get("verification_method") != "wide_integer_dot_reference_modulo_2_32"
                or payload.get("operation_family") != "u8_s8_dot_product_accumulate"
                or payload.get("accumulator_chains") != 8 or payload.get("dot_rounds_per_block") != 256
                or payload.get("products_per_lane") != 4
                or payload.get("active_int32_lanes") != (8 if kernel == "avx_vnni" else 16)
                or type(count) is not int or count <= 0
                or type(payload.get("actual_worker_count")) is not int or payload["actual_worker_count"] != count
                or not isinstance(targets, list) or len(targets) != count
                or any(type(cpu) is not int or cpu < 0 for cpu in targets) or len(set(targets)) != count
                or not isinstance(rows, list) or len(rows) != count
                or not _versioned_fp32_error_free(payload, kernel)
                or any(payload.get(key) is not True for key in flags)
                or any(payload.get(key) != count for key in ("affinity_attempted_count", "affinity_applied_count"))
                or type(payload.get("affinity_failed_count")) is not int or payload["affinity_failed_count"] != 0
                or any(type(payload.get(key)) is not int for key in ("affinity_attempted_count", "affinity_applied_count"))
                or ("observed_exit_code" in payload and
                    (type(payload["observed_exit_code"]) is not int or payload["observed_exit_code"] != 0))):
            return False
        emulated = payload.get("execution_implementation") == "test_integer_emulation"
        if (payload.get("execution_implementation") != ("test_integer_emulation" if emulated else "x86_vnni_intrinsics")
                or payload.get("actual_isa") != ("test_integer_emulation" if emulated else kernel)
                or payload.get("isa_capability_source") != ("test_override" if emulated else "per_cpu_affinity_pinned_cpuid")):
            return False
        total = 0
        for i, row in enumerate(rows):
            blocks = row.get("arithmetic_verified_blocks")
            if (type(row.get("thread_index")) is not int or row["thread_index"] != i
                    or type(row.get("affinity_target_cpu")) is not int or row["affinity_target_cpu"] != targets[i]
                    or type(row.get("observed_cpu")) is not int or row["observed_cpu"] != targets[i]
                    or any(row.get(key) is not True for key in ("affinity_applied", "affinity_required", *flags))
                    or type(blocks) is not int or not 3 <= blocks <= (1 << 64) - 1
                    or type(row.get("verify_passes")) is not int or row["verify_passes"] != blocks
                    or not _versioned_fp32_error_free(row, kernel)):
                return False
            evidence = row.get("vnni_capability")
            if not isinstance(evidence, dict) or any(type(evidence.get(k)) is not int or evidence[k] < 0 for k in (
                "xcr0", "cpuid_7_0_ebx", "cpuid_7_0_ecx", "cpuid_7_max_subleaf", "cpuid_7_1_eax")):
                return False
            if (evidence["xcr0"] > (1 << 64) - 1
                    or any(v > (1 << 32) - 1 for k, v in evidence.items() if k != "xcr0")):
                return False
            if not emulated:
                if evidence["xcr0"] & 6 != 6 or not evidence["cpuid_7_0_ebx"] & (1 << 5):
                    return False
                if kernel == "avx_vnni":
                    if evidence["cpuid_7_max_subleaf"] < 1 or not evidence["cpuid_7_1_eax"] & (1 << 4):
                        return False
                elif (evidence["xcr0"] & 0xe6 != 0xe6 or not evidence["cpuid_7_0_ebx"] & (1 << 16)
                      or not evidence["cpuid_7_0_ecx"] & (1 << 11)):
                    return False
            total += blocks
        return (type(payload.get("arithmetic_verified_blocks")) is int
                and payload["arithmetic_verified_blocks"] == total <= (1 << 64) - 1
                and all(type(payload.get(k)) is int and payload[k] == total for k in ("verify_passes",))
                and all(type(payload[k]) is int and payload[k] == total
                        for k in ("verification_passes", "VerificationPasses") if k in payload))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
