#!/usr/bin/env python3
"""Small architecture policy surface for portable CPU fallback execution."""

from __future__ import annotations

import platform
from typing import Any, Dict


X86_CPU_INSTRUCTION_SETS = frozenset({"sse", "avx", "avx2", "avx512"})
ARM64_CPU_INSTRUCTION_SETS = frozenset({"neon"})


def normalize_cpu_architecture(machine: str) -> str:
    normalized = str(machine or "").strip().lower().replace("-", "_")
    if normalized in {"x86_64", "amd64"}:
        return "x86_64"
    if normalized in {"aarch64", "arm64"}:
        return "arm64"
    return normalized or "unknown"


def current_cpu_architecture() -> str:
    return normalize_cpu_architecture(platform.machine())


def native_cpu_helper_binary_name(machine: str) -> str:
    """Keep the established x86 artifact path while isolating ARM builds from stale x86 binaries."""
    return "cpu_stress_helper_arm64" if normalize_cpu_architecture(machine) == "arm64" else "cpu_stress_helper"


def heatsoak_cpu_instruction_set(machine: str) -> str:
    """Preserve the established x86 heatsoak while avoiding an x86-only request on ARM."""
    return "auto" if normalize_cpu_architecture(machine) == "arm64" else "avx"


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
    if architecture == "arm64":
        resolved_mode = "scalar" if requested == "scalar" else "portable"
    else:
        resolved_mode = "approximate"
    return {
        "allowed": True,
        "architecture": architecture,
        "requested_mode": requested,
        "resolved_mode": resolved_mode,
        "reason": "",
    }
