#!/usr/bin/env python3
"""Runner-facing OpenCL and Vulkan GPU target resolution helpers."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from Modules.lvs_opencl_targeting import gpu_vendor_matches_text
from Modules.lvs_vulkan_targeting import (
    slot_from_mesa_style_vulkan_uuid as vulkan_slot_from_mesa_uuid,
    vulkan_device_class_from_match,
    vulkan_device_for_target as select_vulkan_device_for_target,
    vulkan_device_pci_slot as select_vulkan_device_pci_slot,
    vulkan_device_score_for_target as score_vulkan_device_for_target,
)


def opencl_device_score_for_target(runner: Any, device: Dict[str, Any], target: Optional[Dict[str, Any]]) -> float:
    if not target:
        return float(int(device.get("opencl_index", 0)) * -0.01)
    score = 0.0
    target_vendor = str(target.get("vendor", "") or "").strip().lower()
    target_vendor_id = runner._normalize_pci_id(str(target.get("vendor_id", "") or ""))
    target_name = str(target.get("name", "") or "").strip().lower()
    target_mem = int(target.get("vram_total") or 0)
    device_vendor = str(device.get("vendor", "") or "").strip().lower()
    platform_vendor = str(device.get("platform_vendor", "") or "").strip().lower()
    device_name = str(device.get("name", "") or "").strip().lower()
    device_vendor_id = runner._normalize_pci_id(str(device.get("vendor_id", "") or ""))
    target_slot = runner._normalize_pci_slot(str(target.get("slot", "") or target.get("target_id", "") or "")).lower()
    device_slot = runner._normalize_pci_slot(str(device.get("pci_slot", "") or "")).lower()
    device_mem = int(device.get("global_mem_bytes", 0) or 0)
    vendor_match = False
    if target_slot and device_slot:
        if target_slot == device_slot:
            score += 2500.0
        else:
            return -1000000.0
    if target_vendor_id and target_vendor_id == device_vendor_id:
        vendor_match = True
        score += 800.0
    if runner._gpu_vendor_matches_text(target_vendor, device_vendor, platform_vendor, device_name):
        vendor_match = True
        score += 400.0
    if runner._gpu_vendor_matches_text(target_vendor, platform_vendor):
        score += 100.0
    if target_vendor and not vendor_match:
        return -1000000.0
    if target_name:
        name_tokens = [
            token
            for token in re.split(r"[^a-z0-9]+", target_name)
            if len(token) >= 3 and token not in {"amd", "intel", "nvidia", "gpu", "graphics"}
        ]
        shared_tokens = [token for token in name_tokens if token in device_name]
        score += min(180.0, float(len(shared_tokens)) * 45.0)
    if target_mem > 0 and device_mem > 0:
        ratio = abs(device_mem - target_mem) / float(max(device_mem, target_mem))
        score += max(0.0, 700.0 * (1.0 - min(1.0, ratio)))
    likely_discrete_ids = {
        str(card.get("target_id", "") or "").strip().lower()
        for card in runner._likely_discrete_gpu_cards(runner._discover_gpu_cards())
    }
    target_id = str(target.get("target_id", "") or "").strip().lower()
    if target_id in likely_discrete_ids and device_mem >= 2 * 1024 ** 3:
        score += 120.0
    if target_id not in likely_discrete_ids and 0 < device_mem < 2 * 1024 ** 3:
        score += 120.0
    try:
        opencl_index = int(device.get("opencl_index", -1))
    except Exception:
        opencl_index = -1
    try:
        target_index = int(target.get("gpu_index", -1))
    except Exception:
        target_index = -1
    if not device_slot and opencl_index >= 0 and opencl_index == target_index:
        score += 75.0
    if int(device.get("duplicate_group_size", 1) or 1) <= 1:
        score += 10.0
    score -= float(int(device.get("opencl_index", 0) or 0)) * 0.01
    return score


def opencl_best_device_for_target(
    runner: Any,
    devices: List[Dict[str, Any]],
    target: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not target or not devices:
        return None
    ranked = sorted(
        ((runner._opencl_device_score_for_target(device, target), device) for device in devices),
        key=lambda item: item[0],
        reverse=True,
    )
    if not ranked:
        return None
    best_score, best_device = ranked[0]
    if best_score < 150.0:
        return None
    if len(ranked) > 1:
        next_score, next_device = ranked[1]
        best_identity = (
            runner._normalize_pci_id(str(best_device.get("vendor_id", "") or "")),
            str(best_device.get("identity_key", "") or ""),
        )
        next_identity = (
            runner._normalize_pci_id(str(next_device.get("vendor_id", "") or "")),
            str(next_device.get("identity_key", "") or ""),
        )
        if best_identity != next_identity and abs(best_score - next_score) < 25.0:
            return None
    target_vendor = str(target.get("vendor", "") or "").strip().lower()
    selected_vendor = str(best_device.get("vendor", "") or "").strip().lower()
    selected_name = str(best_device.get("name", "") or "").strip().lower()
    selected_platform_vendor = str(best_device.get("platform_vendor", "") or "").strip().lower()
    target_vendor_id = runner._normalize_pci_id(str(target.get("vendor_id", "") or ""))
    selected_vendor_id = runner._normalize_pci_id(str(best_device.get("vendor_id", "") or ""))
    if target_vendor_id and selected_vendor_id and target_vendor_id == selected_vendor_id:
        return dict(best_device)
    if target_vendor and not runner._gpu_vendor_matches_text(
        target_vendor,
        selected_vendor,
        selected_name,
        selected_platform_vendor,
    ):
        return None
    return dict(best_device)


def opencl_device_for_target(runner: Any, target: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    devices = list((runner._opencl_gpu_backend().get("devices") or []))
    return runner._opencl_best_device_for_target(devices, target)


def vulkan_device_score_for_target(runner: Any, device: Dict[str, Any], target: Optional[Dict[str, Any]]) -> float:
    cards = runner._discover_gpu_cards()
    likely_discrete_ids = {
        str(card.get("target_id", "") or "").strip().lower()
        for card in runner._likely_discrete_gpu_cards(cards)
    }
    return score_vulkan_device_for_target(
        device,
        target,
        gpu_cards=cards,
        likely_discrete_ids=likely_discrete_ids,
    )


def vulkan_device_pci_slot(runner: Any, device: Dict[str, Any]) -> str:
    return select_vulkan_device_pci_slot(device, runner._discover_gpu_cards())


def slot_from_mesa_style_vulkan_uuid(runner: Any, uuid_text: str) -> str:
    return vulkan_slot_from_mesa_uuid(uuid_text, runner._discover_gpu_cards())


def vulkan_device_for_target(runner: Any, target: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    devices = list((runner._vulkan_runtime_details().get("devices") or []))
    if not devices:
        devices = list((runner._vulkan_native_backend().get("devices") or []))
    cards = runner._discover_gpu_cards()
    likely_discrete_ids = {
        str(card.get("target_id", "") or "").strip().lower()
        for card in runner._likely_discrete_gpu_cards(cards)
    }
    return select_vulkan_device_for_target(
        devices,
        target,
        gpu_cards=cards,
        likely_discrete_ids=likely_discrete_ids,
    )


def vulkan_device_class(runner: Any, target: Optional[Dict[str, Any]]) -> str:
    return vulkan_device_class_from_match(runner._vulkan_device_for_target(target))


def gpu_vendor_matches_text_for_runner(vendor: str, *texts: str) -> bool:
    return gpu_vendor_matches_text(vendor, *texts)
