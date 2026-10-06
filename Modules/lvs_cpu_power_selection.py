#!/usr/bin/env python3
"""Architecture-aware cross-backend CPU selection for explicit Power Auto stages."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from .lvs_cpu_architecture import normalize_cpu_architecture


POWER_SELECTION_POWER_PROBE = "power_probe"
POWER_SELECTION_THERMAL_FALLBACK = "thermal_validated_fallback"
POWER_SELECTION_ARCHITECTURE_FALLBACK = "architecture_validated_fallback"
POWER_AUTO_VALIDATION_RUNNER_ARM64_NATIVE_FALLBACK = (
    "arm64_power_auto_native_fallback_order"
)
POWER_AUTO_VALIDATION_RUNNERS = frozenset({
    POWER_AUTO_VALIDATION_RUNNER_ARM64_NATIVE_FALLBACK,
})


def power_auto_validation_candidate_availability(
    *,
    validation_runner: str,
    architecture: str,
    actual_availability: Dict[str, bool],
    native_kernel_flavors: Iterable[str],
    selected_native_kernel: str,
) -> Tuple[Dict[str, bool], Dict[str, Any]]:
    """Apply a named hardware-validation scenario without changing production policy."""
    runner = str(validation_runner or "").strip().lower()
    actual = {key: bool(value) for key, value in actual_availability.items()}
    if not runner:
        return actual, {}
    if runner not in POWER_AUTO_VALIDATION_RUNNERS:
        return actual, {
            "runner": runner,
            "scope": "hardware_validation_only",
            "requirements_met": False,
            "requirement_failures": [f"unknown CPU Power Auto validation runner '{runner}'"],
            "actual_candidate_availability": actual,
            "controlled_candidate_availability": actual,
        }

    normalized_architecture = normalize_cpu_architecture(architecture)
    common_kernels = list(dict.fromkeys(
        str(value or "").strip().lower()
        for value in native_kernel_flavors
        if str(value or "").strip()
    ))
    auto_kernel = str(selected_native_kernel or "").strip().lower()
    failures: List[str] = []
    if normalized_architecture != "arm64":
        failures.append("validation runner requires AArch64")
    if not actual.get("cpu_native_helper"):
        failures.append("native CPU helper is unavailable")
    for required_kernel in ("scalar", "neon"):
        if required_kernel not in common_kernels:
            failures.append(f"common native kernel '{required_kernel}' is unavailable")
    if auto_kernel != "neon":
        failures.append(
            f"generic AArch64 auto must resolve to NEON for this validation (resolved '{auto_kernel or 'none'}')"
        )

    controlled = dict(actual)
    controlled["stress_ng"] = False
    controlled["python_fallback"] = False
    if failures:
        controlled["cpu_native_helper"] = False
    return controlled, {
        "runner": runner,
        "scope": "hardware_validation_only",
        "requirements_met": not failures,
        "requirement_failures": failures,
        "architecture": normalized_architecture,
        "common_native_kernels": common_kernels,
        "generic_auto_kernel": auto_kernel,
        "actual_candidate_availability": actual,
        "controlled_candidate_availability": controlled,
        "intentional_exclusions": {
            "stress_ng:matrixprod": "excluded by the hardware-validation runner",
            "python_fallback:pbkdf2": "excluded by the hardware-validation runner",
        },
        "expected_selected_candidate": "cpu_native_helper:scalar",
    }


def _candidate(
    candidate_id: str,
    backend: str,
    workload: str,
    *,
    kernel_flavor: str = "",
    resolved_mode: str = "",
) -> Dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "backend": backend,
        "workload": workload,
        "kernel_flavor": kernel_flavor,
        "resolved_mode": resolved_mode,
    }


def power_cpu_candidate_inventory(
    *,
    architecture: str,
    availability: Dict[str, bool],
    native_kernel_flavors: Iterable[str],
    selected_native_kernel: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Return runnable Power Auto candidates and explicit unavailability evidence."""
    architecture = normalize_cpu_architecture(architecture)
    viable: List[Dict[str, Any]] = []
    unavailable: List[Dict[str, str]] = []
    if availability.get("stress_ng"):
        viable.append(_candidate("stress_ng:matrixprod", "stress_ng", "matrixprod", resolved_mode="approximate"))
    else:
        unavailable.append({
            "candidate_id": "stress_ng:matrixprod",
            "reason": "stress-ng executable is unavailable",
        })
    if availability.get("python_fallback"):
        viable.append(_candidate(
            "python_fallback:pbkdf2",
            "python_fallback",
            "pbkdf2_compare_digest",
            resolved_mode="portable" if architecture == "arm64" else "approximate",
        ))
    else:
        unavailable.append({
            "candidate_id": "python_fallback:pbkdf2",
            "reason": "Python CPU fallback runtime is unavailable",
        })
    native_flavors = list(dict.fromkeys(str(value or "").strip().lower() for value in native_kernel_flavors if value))
    if availability.get("cpu_native_helper") and native_flavors:
        for flavor in native_flavors:
            viable.append(_candidate(
                f"cpu_native_helper:{flavor}",
                "cpu_native_helper",
                "native_verified_kernel",
                kernel_flavor=flavor,
                resolved_mode="neon" if flavor == "neon" else "scalar" if flavor == "scalar" else "",
            ))
    else:
        unavailable.append({
            "candidate_id": "cpu_native_helper:auto",
            "reason": "native CPU helper or a common verified native kernel is unavailable",
        })
    selected = str(selected_native_kernel or "").strip().lower()
    for candidate in viable:
        candidate["native_auto_preferred"] = bool(
            candidate["backend"] == "cpu_native_helper" and candidate["kernel_flavor"] == selected
        )
    return viable, unavailable


def power_cpu_fallback_order(architecture: str, candidates: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return the fallback preference when no trustworthy measured-power winner exists."""
    architecture = normalize_cpu_architecture(architecture)
    entries = list(candidates)

    def rank(candidate: Dict[str, Any]) -> tuple[int, str]:
        backend = str(candidate.get("backend") or "")
        flavor = str(candidate.get("kernel_flavor") or "")
        preferred_native = bool(candidate.get("native_auto_preferred"))
        if architecture == "arm64":
            if backend == "stress_ng":
                value = 0
            elif backend == "python_fallback":
                value = 1
            elif backend == "cpu_native_helper" and flavor == "scalar":
                value = 2
            elif preferred_native:
                value = 3
            else:
                value = 4
        else:
            if preferred_native:
                value = 0
            elif backend == "stress_ng":
                value = 1
            elif backend == "python_fallback":
                value = 2
            elif backend == "cpu_native_helper" and flavor == "scalar":
                value = 3
            else:
                value = 4
        return value, str(candidate.get("candidate_id") or "")

    return sorted(entries, key=rank)


def select_power_cpu_candidate(
    *,
    architecture: str,
    viable_candidates: Iterable[Dict[str, Any]],
    unavailable_candidates: Iterable[Dict[str, str]],
    telemetry: Dict[str, Any],
    candidate_results: Iterable[Dict[str, Any]],
    probe_duration_seconds: float,
) -> Dict[str, Any]:
    """Select measured power winner or a truthful architecture-specific fallback."""
    architecture = normalize_cpu_architecture(architecture)
    viable = list(viable_candidates)
    unavailable = list(unavailable_candidates)
    results = list(candidate_results)
    telemetry_available = bool(telemetry.get("available"))
    measured = [
        result
        for result in results
        if result.get("valid")
        and result.get("verification_valid")
        and result.get("meaningful_work")
        and int(result.get("power_sample_count") or 0) > 0
        and float(result.get("avg_cpu_power_w") or 0.0) > 0.0
    ]
    fallback_order = power_cpu_fallback_order(architecture, viable)
    if telemetry_available and measured:
        selected_result = max(measured, key=lambda item: float(item.get("avg_cpu_power_w") or 0.0))
        selected = next(
            (item for item in viable if item.get("candidate_id") == selected_result.get("candidate_id")),
            dict(selected_result),
        )
        mechanism = POWER_SELECTION_POWER_PROBE
        fallback_reason = ""
        telemetry_usable = True
    else:
        selected = fallback_order[0] if fallback_order else {}
        mechanism = (
            POWER_SELECTION_THERMAL_FALLBACK
            if architecture == "arm64"
            else POWER_SELECTION_ARCHITECTURE_FALLBACK
        )
        fallback_reason = (
            "cpu_package_power_telemetry_unavailable"
            if not telemetry_available
            else "cpu_power_probes_unusable_or_failed_verification"
        )
        telemetry_usable = False
    return {
        "architecture": architecture,
        "viable_candidates": viable,
        "unavailable_candidates": unavailable,
        "telemetry": {
            **dict(telemetry),
            "trustworthy_usable": telemetry_usable,
        },
        "probe_duration_seconds": round(float(probe_duration_seconds or 0.0), 3),
        "candidate_results": results,
        "fallback_candidate_order": [
            str(candidate.get("candidate_id") or "") for candidate in fallback_order
        ],
        "selected_candidate": dict(selected),
        "selected_backend": str(selected.get("backend") or "none"),
        "selected_workload": str(selected.get("workload") or ""),
        "selected_kernel_flavor": str(selected.get("kernel_flavor") or ""),
        "selected_isa": (
            str(selected.get("resolved_mode") or "")
            if str(selected.get("backend") or "") == "cpu_native_helper"
            else "not_explicitly_enforced" if selected else ""
        ),
        "selected_resolved_mode": str(selected.get("resolved_mode") or ""),
        "selection_mechanism": mechanism,
        "fallback_reason": fallback_reason,
    }
