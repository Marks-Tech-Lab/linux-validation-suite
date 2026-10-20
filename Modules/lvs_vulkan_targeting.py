#!/usr/bin/env python3
"""Vulkan device targeting helpers shared by runner/frontends."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set

from .lvs_gpu_identity import normalize_pci_id, normalize_pci_slot, pci_physical_gpu_id
from .lvs_vulkan_identity import normalize_device_uuid, requested_physical_identity, physical_identity_match


def vulkan_device_is_hardware_gpu(device: Dict[str, Any]) -> bool:
    device_type = str(device.get("deviceType", "") or "").strip().lower()
    name = str(device.get("deviceName", "") or "").strip().lower()
    return not (
        "cpu" in device_type
        or any(token in name for token in ("llvmpipe", "lavapipe", "softpipe", "swrast", "software rasterizer"))
    )


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


def vulkan_physical_identity(device: Dict[str, Any], gpu_cards: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    """Join exact NVIDIA device UUIDs to provider PCI evidence, never ordinals.

    Do not infer an NVIDIA identity from another vendor's UUID or from a driver
    UUID/pipeline-cache UUID. Conflicts must not fall through to model scoring.
    """
    cards = list(gpu_cards)
    explicit = normalize_pci_slot(str(device.get("pci_slot", "") or device.get("pciSlot", "") or ""))
    identifier = normalize_device_uuid(device.get("deviceUUID"))
    vendor = normalize_pci_id(device.get("vendorID", ""))
    part = normalize_pci_id(device.get("deviceID", ""))
    matches = [card for card in cards if identifier and vendor == "10de"
               and normalize_device_uuid(card.get("nvidia_uuid")) == identifier]
    slots = {pci_physical_gpu_id(card.get("slot", "")).removeprefix("pci:") for card in matches}
    conflict = len(slots) > 1 or bool(matches and (not all(slots) or any(
        normalize_pci_id(card.get("vendor_id", "")) != vendor
        or (part and normalize_pci_id(card.get("device", "")) != part)
        for card in matches)))
    peers_by_part = [card for card in cards if vendor == "10de"
                     and normalize_pci_id(card.get("vendor_id", "")) == vendor
                     and normalize_pci_id(card.get("device", "")) == part]
    if identifier and peers_by_part and all(normalize_device_uuid(card.get("nvidia_uuid"))
                                           for card in peers_by_part) and not matches:
        conflict = True
    joined = next(iter(slots)) if len(slots) == 1 else ""
    if explicit and not pci_physical_gpu_id(explicit):
        conflict = True
    if explicit and joined and explicit.lower() != joined.lower():
        conflict = True
    if explicit and identifier and vendor == "10de":
        peers = [card for card in cards if normalize_pci_slot(card.get("slot", "")).lower() == explicit.lower()]
        if any(normalize_device_uuid(card.get("nvidia_uuid")) not in ("", identifier) for card in peers):
            conflict = True
    if conflict:
        return {"slot": "", "source": "", "error": "conflicting Vulkan UUID/PCI/provider identity"}
    if explicit or joined:
        return {"slot": explicit or joined, "source": "vulkan_pci" if explicit else "nvidia_device_uuid", "error": ""}
    return {"slot": "", "source": "", "error": ""}


def vulkan_device_pci_slot(device: Dict[str, Any], gpu_cards: Iterable[Dict[str, Any]]) -> str:
    identity = vulkan_physical_identity(device, gpu_cards)
    return "" if identity["error"] else identity["slot"]


def vulkan_target_identity_evidence(device, target, gpu_cards):
    requested = requested_physical_identity(target)
    identity = vulkan_physical_identity(device, gpu_cards)
    evidence = physical_identity_match(requested["uuid"], requested["pci_slot"],
        device.get("deviceUUID", ""), identity["slot"])
    if requested["error"] or identity["error"]:
        evidence.update(status="conflicting_identity", source="", reason=requested["error"] or identity["error"])
    if evidence["status"] == "verified" and identity["source"] == "nvidia_device_uuid":
        evidence["source"] = "nvidia_device_uuid"
    for target_key, device_key in (("vendor_id", "vendorID"), ("device", "deviceID")):
        expected = normalize_pci_id((target or {}).get(target_key, ""))
        actual = normalize_pci_id(device.get(device_key, ""))
        if expected and actual and expected != actual:
            evidence.update(status="conflicting_identity", source="", reason="physical identity contradicts vendor/device evidence")
    return evidence


def vulkan_device_score_for_target(
    device: Dict[str, Any],
    target: Optional[Dict[str, Any]],
    *,
    gpu_cards: Iterable[Dict[str, Any]],
    likely_discrete_ids: Set[str],
) -> float:
    if not target:
        return 0.0
    gpu_cards = list(gpu_cards)
    proof = vulkan_target_identity_evidence(device, target, gpu_cards)
    if proof["status"] != "verified":
        return -1000000.0
    score = 5000.0 if proof["source"] in ("device_uuid", "nvidia_device_uuid") else 2500.0
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
    vendor_aliases = {
        "amd": ("amd", "radeon", "radv", "radeonsi"),
        "intel": ("intel", "iris", "anv"),
        "nvidia": ("nvidia", "geforce", "quadro", "rtx", "tesla"),
        "qualcomm": ("qualcomm", "adreno", "freedreno", "turnip"),
    }
    if target_vendor and any(alias in device_name for alias in vendor_aliases.get(target_vendor, (target_vendor,))):
        score += 40.0
    if target_id in likely_discrete_ids and "discrete" in device_type:
        score += 140.0
    if target_id not in likely_discrete_ids and "integrated" in device_type:
        score += 140.0
    return score


def vulkan_device_for_target(
    devices: Iterable[Dict[str, Any]],
    target: Optional[Dict[str, Any]],
    *,
    gpu_cards: Iterable[Dict[str, Any]],
    likely_discrete_ids: Set[str],
) -> Dict[str, Any]:
    device_list = [device for device in devices if vulkan_device_is_hardware_gpu(device)]
    card_list = list(gpu_cards)
    if not target or not device_list:
        return {
            "available": False,
            "device": None,
            "ambiguous": False,
            "score": 0.0,
        }
    identities = [vulkan_physical_identity(device, card_list) for device in device_list]
    if any(identity["error"] for identity in identities):
        return {"available": False, "device": None, "ambiguous": True, "score": 0.0,
                "identity_status": "conflicting_identity", "reason": "conflicting Vulkan UUID/PCI/provider identity"}
    identifiers = [normalize_device_uuid(device.get("deviceUUID")) for device in device_list]
    identifiers = [identifier for identifier in identifiers if identifier]
    if len(identifiers) != len(set(identifiers)):
        return {"available": False, "device": None, "ambiguous": True, "score": 0.0,
                "identity_status": "ambiguous_identity", "reason": "duplicate Vulkan device UUID requires unique identity"}
    proofs = [vulkan_target_identity_evidence(device, target, card_list) for device in device_list]
    if sum(proof["status"] == "verified" for proof in proofs) > 1:
        return {"available": False, "device": None, "ambiguous": True, "score": 0.0,
                "identity_status": "ambiguous_identity", "reason": "multiple runtime devices claim the requested physical identity"}
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
        proof = next((proof for proof in proofs if proof["status"] in ("missing_evidence", "unknown_identity")), proofs[0])
        return {
            "available": False,
            "device": None,
            "ambiguous": False,
            "score": best_score,
            "identity_status": proof["status"],
            "reason": proof["reason"],
        }
    ambiguous = False
    if len(ranked) > 1:
        next_score, next_device = ranked[1]
        if abs(best_score - next_score) < 1.0:
            best_slot = vulkan_device_pci_slot(best_device, card_list).lower()
            next_slot = vulkan_device_pci_slot(next_device, card_list).lower()
            # A provider-order tie is never physical-identity evidence. Only
            # duplicate observations of the same explicit PCI function are
            # equivalent; otherwise launch must fail closed as ambiguous.
            ambiguous = not (best_slot and best_slot == next_slot)
    selected_device = dict(best_device)
    selected_slot = vulkan_device_pci_slot(selected_device, card_list)
    if selected_slot:
        selected_device["pci_slot"] = selected_slot
    selected_device["identity_match_source"] = vulkan_physical_identity(best_device, card_list)["source"]
    return {
        "available": True,
        "device": selected_device,
        "ambiguous": ambiguous,
        "score": best_score,
        "identity_status": "verified",
        "physical_identity_evidence": vulkan_target_identity_evidence(best_device, target, card_list),
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
