#!/usr/bin/env python3
"""Vulkan device targeting helpers shared by runner/frontends."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set

from .lvs_gpu_identity import normalize_pci_id, normalize_pci_slot


def slot_from_mesa_style_vulkan_uuid(uuid_text: Any, gpu_cards: Iterable[Dict[str, Any]]) -> str:
    match = re.match(r"^00000000-([0-9a-fA-F]{2})00-", str(uuid_text or ""))
    if match is None:
        return ""
    bus = match.group(1).lower()
    candidates = [
        normalize_pci_slot(str(card.get("slot", "") or ""))
        for card in gpu_cards
        if len(str(card.get("slot", "") or "").split(":")) >= 2
        and str(card.get("slot", "") or "").split(":")[1].lower() == bus
    ]
    return candidates[0] if len(candidates) == 1 else ""


def vulkan_device_pci_slot(device: Dict[str, Any], gpu_cards: Iterable[Dict[str, Any]]) -> str:
    explicit = normalize_pci_slot(str(device.get("pci_slot", "") or device.get("pciSlot", "") or ""))
    if explicit:
        return explicit
    cards = list(gpu_cards)
    uuid_slot = slot_from_mesa_style_vulkan_uuid(str(device.get("deviceUUID", "") or ""), cards)
    if uuid_slot:
        return uuid_slot
    vendor = normalize_pci_id(str(device.get("vendorID", "") or ""))
    device_id = normalize_pci_id(str(device.get("deviceID", "") or ""))
    matches = [
        normalize_pci_slot(str(card.get("slot", "") or ""))
        for card in cards
        if normalize_pci_id(str(card.get("vendor_id", "") or "")) == vendor
        and normalize_pci_id(str(card.get("device", "") or "")) == device_id
        and str(card.get("slot", "") or "")
    ]
    return matches[0] if len(matches) == 1 else ""


def vulkan_device_score_for_target(
    device: Dict[str, Any],
    target: Optional[Dict[str, Any]],
    *,
    gpu_cards: Iterable[Dict[str, Any]],
    likely_discrete_ids: Set[str],
) -> float:
    if not target:
        return 0.0
    score = 0.0
    target_vendor_id = str(target.get("vendor_id", "") or "").strip().lower().removeprefix("0x")
    target_device_id = str(target.get("device", "") or "").strip().lower().removeprefix("0x")
    device_vendor_id = str(device.get("vendorID", "") or "").strip().lower().removeprefix("0x")
    device_device_id = str(device.get("deviceID", "") or "").strip().lower().removeprefix("0x")
    target_vendor = str(target.get("vendor", "") or "").strip().lower()
    device_name = str(device.get("deviceName", "") or "").strip().lower()
    device_type = str(device.get("deviceType", "") or "").strip().lower()
    target_slot = normalize_pci_slot(str(target.get("slot", "") or target.get("target_id", "") or "")).lower()
    device_slot = vulkan_device_pci_slot(device, gpu_cards).lower()
    if target_slot and device_slot:
        if target_slot == device_slot:
            score += 2500.0
        else:
            return -1000000.0
    target_id = str(target.get("target_id", "") or "").strip().lower()
    if target_vendor_id and target_vendor_id == device_vendor_id:
        score += 300.0
    if target_device_id and target_device_id == device_device_id:
        score += 500.0
    if target_vendor and target_vendor in device_name:
        score += 40.0
    if target_id in likely_discrete_ids and "discrete" in device_type:
        score += 140.0
    if target_id not in likely_discrete_ids and "integrated" in device_type:
        score += 140.0
    try:
        runtime_index = int(device.get("index", -1))
    except Exception:
        runtime_index = -1
    try:
        target_index = int(target.get("gpu_index", -1))
    except Exception:
        target_index = -1
    if runtime_index >= 0 and runtime_index == target_index:
        score += 30.0
    return score


def vulkan_device_for_target(
    devices: Iterable[Dict[str, Any]],
    target: Optional[Dict[str, Any]],
    *,
    gpu_cards: Iterable[Dict[str, Any]],
    likely_discrete_ids: Set[str],
) -> Dict[str, Any]:
    device_list = list(devices)
    card_list = list(gpu_cards)
    if not target or not device_list:
        return {
            "available": False,
            "device": None,
            "ambiguous": False,
            "score": 0.0,
        }
    ranked = sorted(
        (
            (
                vulkan_device_score_for_target(
                    device,
                    target,
                    gpu_cards=card_list,
                    likely_discrete_ids=likely_discrete_ids,
                ),
                device,
            )
            for device in device_list
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    best_score, best_device = ranked[0]
    if best_score <= 0:
        return {
            "available": False,
            "device": None,
            "ambiguous": False,
            "score": best_score,
        }
    ambiguous = False
    if len(ranked) > 1:
        next_score, next_device = ranked[1]
        if abs(best_score - next_score) < 1.0:
            best_key = (
                str(best_device.get("vendorID", "") or "").strip().lower(),
                str(best_device.get("deviceID", "") or "").strip().lower(),
            )
            next_key = (
                str(next_device.get("vendorID", "") or "").strip().lower(),
                str(next_device.get("deviceID", "") or "").strip().lower(),
            )
            ambiguous = best_key == next_key
    selected_device = dict(best_device)
    selected_slot = vulkan_device_pci_slot(selected_device, card_list)
    if selected_slot:
        selected_device["pci_slot"] = selected_slot
    return {
        "available": True,
        "device": selected_device,
        "ambiguous": ambiguous,
        "score": best_score,
    }


def vulkan_device_class_from_match(match: Dict[str, Any]) -> str:
    if not match.get("available"):
        return ""
    device = dict(match.get("device") or {})
    device_type = str(device.get("deviceType", "") or "").strip().lower()
    if "discrete" in device_type:
        return "discrete"
    if "integrated" in device_type:
        return "integrated"
    return ""
