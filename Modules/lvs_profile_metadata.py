#!/usr/bin/env python3
"""Native stage metadata and legacy result compatibility classification."""

from __future__ import annotations

from typing import Any, Dict, Optional


LEGACY_BUCKET_CATEGORIES = frozenset({"Power", "SSE", "AVX", "3D"})
_SSE_INSTRUCTION_SETS = frozenset({"sse"})
_AVX_INSTRUCTION_SETS = frozenset({"avx", "avx2", "avx512"})


def stage_display_label(stage: Any) -> str:
    """Return the canonical operator label, falling back only for old objects."""
    return str(getattr(stage, "display_label", "") or getattr(stage, "name", "") or "").strip()


def derive_legacy_bucket_category(stage: Any) -> Optional[str]:
    """Derive the frozen historical result bucket from structured workloads.

    This is reporting compatibility metadata only. It never participates in
    workload selection or instruction-set resolution.
    """
    modules = getattr(stage, "modules", None)
    if modules is None:
        return None
    cpu = getattr(modules, "cpu", None)
    memory = getattr(modules, "memory", None)
    gpu_3d = getattr(modules, "gpu_3d", None)
    vram = getattr(modules, "vram", None)
    storage = getattr(modules, "storage_benchmark", None)
    cpu_enabled = bool(cpu and getattr(cpu, "enabled", False))
    memory_enabled = bool(memory and getattr(memory, "enabled", False))
    gpu_enabled = bool(gpu_3d and getattr(gpu_3d, "enabled", False))
    vram_enabled = bool(vram and getattr(vram, "enabled", False))
    storage_enabled = bool(storage and getattr(storage, "enabled", False))

    # Completion stages and mixed completion/duration definitions have no
    # Power/SSE/AVX/3D compatibility slot.
    if storage_enabled:
        return None

    # Power must win over the otherwise GPU-shaped stage, but only for the
    # validated CPU power-auto + GPU combination.
    explicit_power_auto = bool(getattr(cpu, "power_auto", False))
    legacy_power_shape = (
        str(getattr(cpu, "mode", "") or "").strip().lower() == "extreme"
        and str(getattr(cpu, "load", "") or "").strip().lower() == "steady"
        and str(getattr(cpu, "instruction_set", "") or "").strip().lower() in {"", "auto"}
        and not str(getattr(cpu, "instruction_intent", "") or "").strip()
        and str(getattr(gpu_3d, "intensity", "") or "").strip().lower() == "extreme"
    )
    if (
        cpu_enabled
        and (explicit_power_auto or legacy_power_shape)
        and gpu_enabled
        and not memory_enabled
        and not vram_enabled
    ):
        return "Power"

    # A standalone GPU validation workload (optionally paired with VRAM), or a
    # standalone VRAM validation workload, occupies the historical 3D slot.
    if not cpu_enabled and not memory_enabled and (gpu_enabled or vram_enabled):
        return "3D"

    # CPU+GPU combinations which are not the validated Power shape are
    # ambiguous. CPU-vector classification permits RAM or VRAM companions but
    # not a simultaneous 3D workload.
    if not cpu_enabled or gpu_enabled or explicit_power_auto:
        return None

    intent = str(getattr(cpu, "instruction_intent", "") or "").strip().lower()
    instruction_set = str(getattr(cpu, "instruction_set", "") or "").strip().lower()
    category: Optional[str] = None
    if intent == "baseline_vector":
        category = "SSE" if instruction_set in {"", "auto"} else None
    elif intent in {"high_throughput_vector", "highest_verified_vector"}:
        category = "AVX" if instruction_set in {"", "auto"} else None
    elif intent:
        return None
    elif instruction_set in _SSE_INSTRUCTION_SETS:
        category = "SSE"
    elif instruction_set in _AVX_INSTRUCTION_SETS:
        category = "AVX"
    if category is None or not memory_enabled:
        return category

    memory_instruction_set = str(getattr(memory, "instruction_set", "") or "").strip().lower()
    if memory_instruction_set in {"", "auto"}:
        return category
    if category == "SSE" and memory_instruction_set in _SSE_INSTRUCTION_SETS:
        return category
    if category == "AVX" and memory_instruction_set in _AVX_INSTRUCTION_SETS:
        return category
    return None


def stage_result_metadata(stage: Any, display_label: Optional[str] = None) -> Dict[str, Any]:
    """Build additive native metadata for one configured/executed stage."""
    return {
        "stage_id": str(getattr(stage, "id", "") or ""),
        "display_label": str(display_label or stage_display_label(stage)).strip(),
        "legacy_bucket_category": derive_legacy_bucket_category(stage),
        "legacy_bucket_category_source": "lvs_derived",
    }
