#!/usr/bin/env python3
"""Small architecture policy surface for portable CPU fallback execution."""

from __future__ import annotations

import platform
from typing import Any, Dict


X86_CPU_INSTRUCTION_SETS = frozenset({"sse", "avx", "avx2", "avx512"})
ARM64_CPU_INSTRUCTION_SETS = frozenset({"neon"})
CPU_INSTRUCTION_INTENTS = frozenset({
    "baseline_vector",
    "high_throughput_vector",
    "highest_verified_vector",
})
X86_NATIVE_POWER_PROBE_KERNEL_ORDER = (
    "avx512_fma",
    "avx512_int",
    "avx2_fma",
    "avx2",
    "avx_fma",
    "avx",
    "sse2",
    "sse2_int",
    "scalar",
)
ARM64_NATIVE_POWER_PROBE_KERNEL_ORDER = ("neon", "scalar")
# Compatibility aliases retained for existing callers and fixtures.
X86_MAX_POWER_KERNEL_ORDER = X86_NATIVE_POWER_PROBE_KERNEL_ORDER
ARM64_MAX_POWER_KERNEL_ORDER = ARM64_NATIVE_POWER_PROBE_KERNEL_ORDER


def normalize_cpu_architecture(machine: str) -> str:
    normalized = str(machine or "").strip().lower().replace("-", "_")
    if normalized in {"x86_64", "amd64"}:
        return "x86_64"
    if normalized in {"aarch64", "arm64"}:
        return "arm64"
    return normalized or "unknown"


def current_cpu_architecture() -> str:
    return normalize_cpu_architecture(platform.machine())


def cpu_max_power_kernel_order(machine: str) -> tuple[str, ...]:
    """Return only implemented kernel candidates for the requested architecture."""
    if normalize_cpu_architecture(machine) == "arm64":
        return ARM64_MAX_POWER_KERNEL_ORDER
    return X86_MAX_POWER_KERNEL_ORDER


def cpu_native_power_probe_kernel_order(machine: str) -> tuple[str, ...]:
    """Truthful additive name for the native candidate/probe order."""
    return cpu_max_power_kernel_order(machine)


def normalize_cpu_instruction_intent(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in CPU_INSTRUCTION_INTENTS else ""


def resolve_cpu_instruction_intent(
    machine: str,
    instruction_intent: str,
    common_kernel_flavors: Any,
) -> Dict[str, Any]:
    """Resolve a generic operator SIMD intent against the complete target set."""
    architecture = normalize_cpu_architecture(machine)
    intent = normalize_cpu_instruction_intent(instruction_intent)
    common = {
        str(value or "").strip().lower()
        for value in (common_kernel_flavors or ())
        if value
    }
    if not intent or architecture not in {"x86_64", "arm64"}:
        candidates = ()
    elif architecture == "arm64":
        candidates = ("neon",)
    elif intent == "baseline_vector":
        candidates = ("sse2", "sse2_int")
    elif intent == "high_throughput_vector":
        candidates = ("avx2_fma", "avx2")
    elif intent == "highest_verified_vector":
        candidates = tuple(
            flavor for flavor in X86_NATIVE_POWER_PROBE_KERNEL_ORDER if flavor != "scalar"
        )
    else:
        candidates = ()
    selected = next((flavor for flavor in candidates if flavor in common), "")
    resolved_isa = (
        "neon" if selected == "neon"
        else "sse" if selected.startswith("sse2")
        else "avx512" if selected.startswith("avx512")
        else "avx2" if selected.startswith("avx2")
        else "avx" if selected.startswith("avx")
        else ""
    )
    reason = ""
    if not intent:
        reason = f"unknown CPU instruction intent '{instruction_intent}'"
    elif architecture not in {"x86_64", "arm64"}:
        reason = f"CPU instruction intent '{intent}' is not implemented for architecture '{architecture}'"
    elif not selected:
        reason = (
            f"CPU instruction intent '{intent}' has no common native vector implementation "
            "across the complete target CPU set"
        )
    return {
        "requested_instruction_intent": intent or str(instruction_intent or ""),
        "architecture": architecture,
        "resolution_mechanism": "architecture_instruction_intent",
        "required_backend": "cpu_native_helper",
        "candidate_kernel_flavors": list(candidates),
        "common_kernel_flavors": sorted(common),
        "resolved_backend": "cpu_native_helper" if selected else "none",
        "resolved_isa": resolved_isa,
        "resolved_kernel_flavor": selected,
        "tier_collapse": bool(architecture == "arm64" and intent == "high_throughput_vector" and selected == "neon"),
        "tier_collapse_reason": (
            "AArch64 baseline_vector and high_throughput_vector both resolve to the currently verified NEON tier"
            if architecture == "arm64" and intent == "high_throughput_vector" and selected == "neon"
            else ""
        ),
        "fail_closed_reason": reason,
    }


def native_cpu_helper_binary_name(machine: str) -> str:
    """Keep the established x86 artifact path while isolating ARM builds from stale x86 binaries."""
    return "cpu_stress_helper_arm64" if normalize_cpu_architecture(machine) == "arm64" else "cpu_stress_helper"


def heatsoak_cpu_instruction_set(machine: str) -> str:
    """Use the highest ISA proven safe across the heatsoak target CPU set."""
    del machine
    return "auto"


def cpu_instruction_set_policy(machine: str, instruction_set: str) -> Dict[str, Any]:
    """Reject architecture-incompatible explicit CPU ISA requests before backend selection."""
    architecture = normalize_cpu_architecture(machine)
    requested = str(instruction_set or "auto").strip().lower() or "auto"
    if architecture == "arm64" and requested in X86_CPU_INSTRUCTION_SETS:
        return {
            "allowed": False,
            "architecture": architecture,
            "requested_mode": requested,
            "reason": (
                f"CPU instruction set '{requested}' is an x86 ISA and is not available on ARM64"
            ),
        }
    if architecture != "arm64" and requested in ARM64_CPU_INSTRUCTION_SETS:
        return {
            "allowed": False,
            "architecture": architecture,
            "requested_mode": requested,
            "reason": (
                f"CPU instruction set '{requested}' is an ARM64 ISA and is not available on "
                f"{architecture}"
            ),
        }
    return {
        "allowed": True,
        "architecture": architecture,
        "requested_mode": requested,
        "reason": "",
    }


def python_cpu_fallback_policy(machine: str, instruction_set: str) -> Dict[str, Any]:
    instruction_policy = cpu_instruction_set_policy(machine, instruction_set)
    architecture = str(instruction_policy["architecture"])
    requested = str(instruction_policy["requested_mode"])
    if not instruction_policy["allowed"]:
        return {
            "allowed": False,
            "architecture": architecture,
            "requested_mode": requested,
            "resolved_mode": "",
            "reason": f"{instruction_policy['reason']} through the Python CPU fallback",
        }
    if requested in ARM64_CPU_INSTRUCTION_SETS:
        return {
            "allowed": False,
            "architecture": architecture,
            "requested_mode": requested,
            "resolved_mode": "",
            "reason": (
                f"CPU instruction set '{requested}' requires the ARM64 native CPU helper "
                "and is not available through the Python CPU fallback"
            ),
        }
    if requested != "auto":
        return {
            "allowed": False,
            "architecture": architecture,
            "requested_mode": requested,
            "resolved_mode": "",
            "reason": (
                f"CPU instruction set '{requested}' is not enforced by the generic Python CPU fallback; "
                "use the native CPU helper for an explicit ISA request"
            ),
        }
    if architecture == "arm64":
        resolved_mode = "portable"
    else:
        resolved_mode = "approximate"
    return {
        "allowed": True,
        "architecture": architecture,
        "requested_mode": requested,
        "resolved_mode": resolved_mode,
        "reason": "",
    }
