"""Strict UUID representation and optional baseline-safe Vulkan ID queries.

deviceUUID is an API-interoperability identifier, not pipelineCacheUUID.
NVIDIA's GPU- prefix is textual framing; UUID bytes retain network/display order
(never UUID.bytes_le). MIG/legacy opaque IDs are deliberately not converted.
"""
from __future__ import annotations

import ctypes
import re
import uuid

from .lvs_gpu_identity import pci_physical_gpu_id


def normalize_device_uuid(value):
    text = str(value or "").strip().lower()
    if text.startswith("gpu-"):
        text = text[4:]
    if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text):
        return ""
    return text if uuid.UUID(text).int else ""


def canonical_pci_slot(value):
    return pci_physical_gpu_id(str(value or "").removeprefix("pci:")).removeprefix("pci:")


def requested_physical_identity(target):
    """Retain independently discovered target IDs, never candidate similarity."""
    target = target or {}
    uuids = [target.get(key) for key in ("nvidia_uuid", "target_device_uuid", "vulkan_device_uuid")
             if target.get(key) not in (None, "")]
    raw_slots = [target.get("slot")] if target.get("slot") else []
    for key in ("target_id", "physical_gpu_id"):
        value = target.get(key, "")
        if canonical_pci_slot(value) or (key == "physical_gpu_id" and str(value).startswith("pci:")):
            raw_slots.append(value)
    normalized = {normalize_device_uuid(value) for value in uuids}
    slots = {canonical_pci_slot(value) for value in raw_slots}
    invalid = "" in normalized or "" in slots or len(normalized) > 1 or len(slots) > 1
    return {"uuid": next(iter(normalized), ""), "pci_slot": next(iter(slots), ""),
            "error": "conflicting or malformed requested physical identity" if invalid else ""}


def physical_identity_match(target_uuid, target_slot, device_uuid, device_slot):
    """Positive proof is mandatory; absence of contradiction is not proof.

    PCI-only execution is valid when UUID discovery is unavailable, but any
    simultaneously available UUID/PCI contradiction overrides other matches.
    """
    tu, du = normalize_device_uuid(target_uuid), normalize_device_uuid(device_uuid)
    tp, dp = canonical_pci_slot(target_slot), canonical_pci_slot(device_slot)
    evidence = {"contract_id": "linux_validation_suite.vulkan_physical_identity",
                "contract_version": 1, "kind": "vulkan_physical_identity",
                "status": "missing_evidence", "source": "", "reason": "",
                "target_uuid": tu, "target_pci_slot": tp,
                "selected_uuid": du, "selected_pci_slot": dp}
    malformed = any(raw not in (None, "") and not normalized for raw, normalized in
                    ((target_uuid, tu), (device_uuid, du), (target_slot, tp), (device_slot, dp)))
    if malformed or (tu and du and tu != du) or (tp and dp and tp != dp):
        evidence.update(status="conflicting_identity", reason="malformed or conflicting physical UUID/PCI evidence")
    elif tu and du and tu == du:
        evidence.update(status="verified", source="device_uuid")
    elif tp and dp and tp == dp:
        evidence.update(status="verified", source="pci_bus_info")
    elif not tu and not tp:
        evidence.update(status="unknown_identity", reason="requested physical identity is unknown")
    else:
        evidence["reason"] = "runtime physical UUID/PCI evidence is missing or cannot establish the requested identity"
    return evidence


class PhysicalDeviceIDProperties(ctypes.Structure):
    _fields_ = [("sType", ctypes.c_uint32), ("pNext", ctypes.c_void_p),
                ("deviceUUID", ctypes.c_uint8 * 16), ("driverUUID", ctypes.c_uint8 * 16),
                ("deviceLUID", ctypes.c_uint8 * 8), ("deviceNodeMask", ctypes.c_uint32),
                ("deviceLUIDValid", ctypes.c_uint32)]


class PhysicalDeviceProperties2(ctypes.Structure):
    _fields_ = [("sType", ctypes.c_uint32), ("pNext", ctypes.c_void_p),
                ("properties", ctypes.c_uint64 * 1024)]


def supports_pci_bus_info(vk, physical_device):
    """Do not query an optional device extension merely because a symbol exists."""
    fn = getattr(vk, "vkEnumerateDeviceExtensionProperties", None)
    if fn is None:
        return False
    class ExtensionProperties(ctypes.Structure):
        _fields_ = [("extensionName", ctypes.c_char * 256), ("specVersion", ctypes.c_uint32)]
    fn.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
    fn.restype = ctypes.c_int32
    count = ctypes.c_uint32()
    if fn(physical_device, None, ctypes.byref(count), None) != 0 or not count.value:
        return False
    extensions = (ExtensionProperties * count.value)()
    if fn(physical_device, None, ctypes.byref(count), extensions) != 0:
        return False
    return any(bytes(item.extensionName) == b"VK_EXT_pci_bus_info" for item in extensions[:count.value])


def identity_instance_api_version(vk):
    """Request at most 1.1, retaining 1.0 compatibility on older loaders."""
    try:
        fn = vk.vkEnumerateInstanceVersion
        fn.argtypes = [ctypes.POINTER(ctypes.c_uint32)]
        fn.restype = ctypes.c_int32
        version = ctypes.c_uint32()
        if fn(ctypes.byref(version)) == 0 and version.value >= ((1 << 22) | (1 << 12)):
            return (1 << 22) | (1 << 12)
    except (AttributeError, TypeError):
        pass
    return 1 << 22


def read_device_uuid(vk, physical_device, instance_api_version, device_api_version):
    """Only use core properties2 when both instance and device support 1.1."""
    if min(instance_api_version, device_api_version) < ((1 << 22) | (1 << 12)):
        return ""
    fn = getattr(vk, "vkGetPhysicalDeviceProperties2", None)
    if fn is None:
        return ""
    ids = PhysicalDeviceIDProperties(1000071004, None)
    props = PhysicalDeviceProperties2(1000059001, ctypes.cast(ctypes.pointer(ids), ctypes.c_void_p))
    # c_void_p avoids coupling the two callers' equivalent properties2 types.
    fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    fn.restype = None
    fn(physical_device, ctypes.byref(props))
    return normalize_device_uuid(str(uuid.UUID(bytes=bytes(ids.deviceUUID))))
