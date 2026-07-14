#!/usr/bin/env python3
"""GPU naming and ordering helpers for compatibility exports."""

from __future__ import annotations

from typing import Any, Dict, List

from Modules.lvs_gpu_identity import normalize_pci_slot


def has_meaningful_gpu_value(value: Any) -> bool:
    text = str(value or "").strip()
    if not text or text == "-":
        return False
    return True


def normalize_gpu_interface(value: Any) -> str:
    return normalize_pci_slot(value)


def gpu_device_entry_score(gpu: Dict[str, Any]) -> int:
    score = 0
    if has_meaningful_gpu_value(gpu.get("Memory")):
        score += 8
    if has_meaningful_gpu_value(gpu.get("DriverVersion")):
        score += 4
        driver_text = str(gpu.get("DriverVersion") or "").strip().lower()
        if any(ch.isdigit() for ch in driver_text):
            score += 2
        if driver_text in {"nvidia", "amdgpu", "i915", "xe"}:
            score -= 1
    name = str(gpu.get("Name") or "").strip()
    if name:
        score += 2
        if "[" not in name and "]" not in name:
            score += 1
    chipset = str(gpu.get("Chipset") or "").strip()
    if chipset and not chipset.lower().startswith(("nvidia ", "amd ", "intel ")):
        score += 1
    return score


def merge_gpu_device_entries(
    primary: Dict[str, Any],
    candidate: Dict[str, Any],
    normalized_slot: str,
) -> Dict[str, Any]:
    merged = dict(primary)
    candidate_copy = dict(candidate)
    primary_score = gpu_device_entry_score(primary)
    candidate_score = gpu_device_entry_score(candidate_copy)
    preferred = candidate_copy if candidate_score > primary_score else primary
    merged["Interface"] = normalized_slot
    for key in (
        "Name",
        "GpuModel",
        "MarketingName",
        "PciName",
        "NameSource",
        "RuntimeNameRaw",
        "DeviceClass",
        "DeviceClassSource",
        "DeviceClassConfidence",
        "Card",
        "Chipset",
        "GpuDie",
        "Memory",
        "DriverVersion",
        "DriverDate",
        "CurrentResolution",
        "MaxRefreshRate",
    ):
        preferred_value = preferred.get(key)
        if has_meaningful_gpu_value(preferred_value):
            merged[key] = preferred_value
            continue
        primary_value = primary.get(key)
        candidate_value = candidate_copy.get(key)
        merged[key] = (
            primary_value
            if has_meaningful_gpu_value(primary_value)
            else candidate_value
        )
    return merged


def enumerate_gpu_devices(gpus: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged_by_slot: Dict[str, Dict[str, Any]] = {}
    passthrough: List[Dict[str, Any]] = []
    for gpu in gpus:
        slot = normalize_gpu_interface(gpu.get("Interface"))
        if not slot:
            passthrough.append(dict(gpu))
            continue
        existing = merged_by_slot.get(slot)
        if existing is None:
            merged_by_slot[slot] = dict(gpu)
            merged_by_slot[slot]["Interface"] = slot
            continue
        merged_by_slot[slot] = merge_gpu_device_entries(existing, gpu, slot)

    deduped = list(merged_by_slot.values()) + passthrough
    counts: Dict[str, int] = {}
    for gpu in deduped:
        name = gpu.get("Name", "-")
        counts[name] = counts.get(name, 0) + 1

    seen: Dict[str, int] = {}
    output: List[Dict[str, Any]] = []
    for gpu in deduped:
        name = gpu.get("Name", "-")
        seen[name] = seen.get(name, 0) + 1
        output.append(
            {
                **gpu,
                "DisplayName": f"{name} #{seen[name]}" if counts.get(name, 0) > 1 else name,
            }
        )
    return output
