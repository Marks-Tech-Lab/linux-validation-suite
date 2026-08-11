#!/usr/bin/env python3
"""Small architecture policy surface for the portable native memory helper."""

from __future__ import annotations

from .lvs_cpu_architecture import normalize_cpu_architecture


def native_memory_helper_binary_name(machine: str) -> str:
    """Keep established x86 artifacts while isolating ARM from stale x86 binaries."""
    return (
        "memory_stress_helper_arm64"
        if normalize_cpu_architecture(machine) == "arm64"
        else "memory_stress_helper"
    )
