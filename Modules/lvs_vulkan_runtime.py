#!/usr/bin/env python3
"""Vulkan runtime discovery shared by runner, diagnostics, and QA frontends."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from .lvs_backend_readiness import build_vulkan_native_backend_payload


def merge_vulkan_device_inventories(
    runtime_devices: List[Dict[str, Any]],
    native_devices: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Combine vulkaninfo identity with native core allocation capabilities."""
    merged: List[Dict[str, Any]] = []
    unused_native = list(native_devices)
    for runtime_device in runtime_devices:
        runtime_key = (
            int(runtime_device.get("index", -1) or 0),
            str(runtime_device.get("vendorID", "") or "").lower(),
            str(runtime_device.get("deviceID", "") or "").lower(),
            str(runtime_device.get("deviceName", "") or "").lower(),
        )
        match_index = next(
            (
                index
                for index, native_device in enumerate(unused_native)
                if (
                    int(native_device.get("index", -1) or 0),
                    str(native_device.get("vendorID", "") or "").lower(),
                    str(native_device.get("deviceID", "") or "").lower(),
                    str(native_device.get("deviceName", "") or "").lower(),
                )
                == runtime_key
            ),
            None,
        )
        if match_index is None:
            merged.append(dict(runtime_device))
            continue
        native_device = unused_native.pop(match_index)
        combined = dict(runtime_device)
        for key in (
            "device_local_heap_bytes",
            "max_storage_buffer_range_bytes",
            "max_memory_allocation_count",
            "driverVersionRaw",
        ):
            value = native_device.get(key)
            if value not in (None, ""):
                combined[key] = value
        combined["identity_inventory_source"] = str(runtime_device.get("source") or "vulkaninfo")
        combined["allocation_capability_source"] = str(native_device.get("source") or "libvulkan")
        merged.append(combined)
    merged.extend(dict(device) for device in unused_native)
    return merged


def vulkan_memory_limits_from_properties_bytes(raw: bytes) -> Dict[str, int]:
    """Read the fixed Vulkan 1.x core limits relevant to LVS allocations.

    VkPhysicalDeviceProperties has a 292-byte field prefix followed by four
    bytes of ABI padding before the 8-byte-aligned VkPhysicalDeviceLimits.
    Within limits, maxStorageBufferRange and
    maxMemoryAllocationCount are uint32 members at offsets 28 and 36.
    Vulkan core exposes no maximum size for one VkDeviceMemory allocation.
    """

    if len(raw) < 336:
        return {"max_storage_buffer_range_bytes": 0, "max_memory_allocation_count": 0}
    limits_offset = 296
    return {
        "max_storage_buffer_range_bytes": int.from_bytes(raw[limits_offset + 28 : limits_offset + 32], "little"),
        "max_memory_allocation_count": int.from_bytes(raw[limits_offset + 36 : limits_offset + 40], "little"),
    }


def parse_vulkaninfo_summary(
    stdout: str,
    stderr: str = "",
    returncode: int = 0,
) -> Dict[str, Any]:
    details: Dict[str, Any] = {
        "available": False,
        "path": "vulkaninfo",
        "instance_version": "",
        "devices": [],
        "reason": "",
    }
    text = stdout or ""
    if stderr:
        text = text + ("\n" if text else "") + stderr
    version_match = re.search(r"Vulkan Instance Version:\s*([^\n]+)", text)
    if version_match:
        details["instance_version"] = version_match.group(1).strip()

    current: Optional[Dict[str, Any]] = None
    devices: List[Dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        gpu_match = re.match(r"GPU(\d+):", line.strip())
        if gpu_match:
            if current:
                devices.append(current)
            current = {"index": int(gpu_match.group(1))}
            continue
        if current is None:
            continue
        attr_match = re.match(r"\s*([A-Za-z0-9_]+)\s*=\s*(.+)", line)
        if attr_match:
            current[attr_match.group(1).strip()] = attr_match.group(2).strip()
    if current:
        devices.append(current)

    details["devices"] = devices
    details["available"] = bool(devices)
    if returncode != 0:
        error_text = (stderr or stdout or "vulkaninfo failed").strip()
        if devices:
            details["reason"] = f"vulkaninfo returned nonzero exit, but device inventory was recovered: {error_text}"
        else:
            details["reason"] = error_text
    elif not devices:
        details["reason"] = "no Vulkan physical devices found"
    return details


def collect_vulkan_runtime_details(
    *,
    command_exists: Callable[[str], bool],
    command_env: Callable[[], Dict[str, str]],
    run_command: Callable[..., Any] = subprocess.run,
) -> Dict[str, Any]:
    if not command_exists("vulkaninfo"):
        return {
            "available": False,
            "path": "",
            "instance_version": "",
            "devices": [],
            "reason": "vulkaninfo not found",
        }
    try:
        completed = run_command(
            ["vulkaninfo", "--summary"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
            env=command_env(),
        )
    except Exception as exc:
        return {
            "available": False,
            "path": "vulkaninfo",
            "instance_version": "",
            "devices": [],
            "reason": f"vulkaninfo failed: {exc}",
        }
    return parse_vulkaninfo_summary(
        completed.stdout or "",
        completed.stderr or "",
        int(completed.returncode),
    )


def resolve_vulkan_library(
    *,
    environment: Optional[Mapping[str, str]] = None,
    find_library: Callable[[str], Optional[str]] = ctypes.util.find_library,
    load_library: Callable[[str], Any] = ctypes.CDLL,
) -> str:
    candidates: List[str] = []
    env_candidate = (os.environ if environment is None else environment).get("VULKAN_LIBRARY_PATH", "").strip()
    if env_candidate:
        candidates.append(env_candidate)
    found = find_library("vulkan")
    if found:
        candidates.append(found)
    candidates.extend(
        [
            "/usr/lib64/libvulkan.so.1",
            "/usr/lib64/libvulkan.so",
            "/usr/lib/libvulkan.so.1",
            "/usr/lib/libvulkan.so",
            "/usr/lib/x86_64-linux-gnu/libvulkan.so.1",
            "/usr/lib/x86_64-linux-gnu/libvulkan.so",
            "/usr/lib/aarch64-linux-gnu/libvulkan.so.1",
            "/usr/lib/aarch64-linux-gnu/libvulkan.so",
            "/lib/aarch64-linux-gnu/libvulkan.so.1",
            "/lib/aarch64-linux-gnu/libvulkan.so",
            "/lib64/libvulkan.so.1",
            "/lib64/libvulkan.so",
        ]
    )
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            load_library(candidate)
            return candidate
        except Exception:
            continue
    return ""


def collect_vulkan_native_physical_devices(
    library: str,
    *,
    load_library: Callable[[str], Any] = ctypes.CDLL,
) -> Dict[str, Any]:
    if not library:
        return {"available": False, "devices": [], "reason": "Vulkan loader library not found"}
    try:
        vk = load_library(library)
        VkInstance = ctypes.c_void_p
        VkPhysicalDevice = ctypes.c_void_p

        class VkApplicationInfo(ctypes.Structure):
            _fields_ = [
                ("sType", ctypes.c_uint32),
                ("pNext", ctypes.c_void_p),
                ("pApplicationName", ctypes.c_char_p),
                ("applicationVersion", ctypes.c_uint32),
                ("pEngineName", ctypes.c_char_p),
                ("engineVersion", ctypes.c_uint32),
                ("apiVersion", ctypes.c_uint32),
            ]

        class VkInstanceCreateInfo(ctypes.Structure):
            _fields_ = [
                ("sType", ctypes.c_uint32),
                ("pNext", ctypes.c_void_p),
                ("flags", ctypes.c_uint32),
                ("pApplicationInfo", ctypes.POINTER(VkApplicationInfo)),
                ("enabledLayerCount", ctypes.c_uint32),
                ("ppEnabledLayerNames", ctypes.c_void_p),
                ("enabledExtensionCount", ctypes.c_uint32),
                ("ppEnabledExtensionNames", ctypes.c_void_p),
            ]

        class VkMemoryType(ctypes.Structure):
            _fields_ = [("propertyFlags", ctypes.c_uint32), ("heapIndex", ctypes.c_uint32)]

        class VkMemoryHeap(ctypes.Structure):
            _fields_ = [("size", ctypes.c_uint64), ("flags", ctypes.c_uint32)]

        class VkPhysicalDeviceMemoryProperties(ctypes.Structure):
            _fields_ = [
                ("memoryTypeCount", ctypes.c_uint32),
                ("memoryTypes", VkMemoryType * 32),
                ("memoryHeapCount", ctypes.c_uint32),
                ("memoryHeaps", VkMemoryHeap * 16),
            ]

        vk.vkCreateInstance.argtypes = [ctypes.POINTER(VkInstanceCreateInfo), ctypes.c_void_p, ctypes.POINTER(VkInstance)]
        vk.vkCreateInstance.restype = ctypes.c_int32
        vk.vkEnumeratePhysicalDevices.argtypes = [VkInstance, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(VkPhysicalDevice)]
        vk.vkEnumeratePhysicalDevices.restype = ctypes.c_int32
        vk.vkGetPhysicalDeviceProperties.argtypes = [VkPhysicalDevice, ctypes.c_void_p]
        vk.vkGetPhysicalDeviceProperties.restype = None
        vk.vkGetPhysicalDeviceMemoryProperties.argtypes = [
            VkPhysicalDevice,
            ctypes.POINTER(VkPhysicalDeviceMemoryProperties),
        ]
        vk.vkGetPhysicalDeviceMemoryProperties.restype = None
        vk.vkDestroyInstance.argtypes = [VkInstance, ctypes.c_void_p]
        vk.vkDestroyInstance.restype = None

        app_info = VkApplicationInfo(0, None, b"Linux Validation Suite", 1, b"linux-validation-suite", 1, (1 << 22))
        create_info = VkInstanceCreateInfo(1, None, 0, ctypes.pointer(app_info), 0, None, 0, None)
        instance = VkInstance()
        code = int(vk.vkCreateInstance(ctypes.byref(create_info), None, ctypes.byref(instance)))
        if code != 0 or not instance:
            return {"available": False, "devices": [], "reason": f"vkCreateInstance failed with code {code}"}
        try:
            count = ctypes.c_uint32()
            code = int(vk.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), None))
            if code != 0:
                return {"available": False, "devices": [], "reason": f"vkEnumeratePhysicalDevices(count) failed with code {code}"}
            if count.value <= 0:
                return {"available": False, "devices": [], "reason": "no Vulkan physical devices found"}
            device_array = (VkPhysicalDevice * count.value)()
            code = int(vk.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), device_array))
            if code != 0:
                return {"available": False, "devices": [], "reason": f"vkEnumeratePhysicalDevices(list) failed with code {code}"}
            type_names = {
                0: "VK_PHYSICAL_DEVICE_TYPE_OTHER",
                1: "VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU",
                2: "VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU",
                3: "VK_PHYSICAL_DEVICE_TYPE_VIRTUAL_GPU",
                4: "VK_PHYSICAL_DEVICE_TYPE_CPU",
            }
            devices: List[Dict[str, Any]] = []
            for index, device in enumerate(device_array[: count.value]):
                props = ctypes.create_string_buffer(8192)
                vk.vkGetPhysicalDeviceProperties(device, ctypes.byref(props))
                raw = props.raw
                memory_limits = vulkan_memory_limits_from_properties_bytes(raw)
                api_version = int.from_bytes(raw[0:4], "little")
                device_type = int.from_bytes(raw[16:20], "little")
                memory_props = VkPhysicalDeviceMemoryProperties()
                vk.vkGetPhysicalDeviceMemoryProperties(device, ctypes.byref(memory_props))
                device_local_heap_bytes = sum(
                    int(memory_props.memoryHeaps[heap_index].size)
                    for heap_index in range(int(memory_props.memoryHeapCount))
                    if int(memory_props.memoryHeaps[heap_index].flags) & 0x1
                )
                devices.append(
                    {
                        "index": index,
                        "apiVersion": f"{(api_version >> 22) & 0x3FF}.{(api_version >> 12) & 0x3FF}.{api_version & 0xFFF}",
                        "driverVersionRaw": int.from_bytes(raw[4:8], "little"),
                        "vendorID": f"0x{int.from_bytes(raw[8:12], 'little'):04x}",
                        "deviceID": f"0x{int.from_bytes(raw[12:16], 'little'):04x}",
                        "deviceType": type_names.get(device_type, str(device_type)),
                        "deviceName": raw[20:276].split(b"\0", 1)[0].decode("utf-8", "ignore"),
                        "device_local_heap_bytes": device_local_heap_bytes,
                        **memory_limits,
                        "source": "libvulkan",
                    }
                )
            return {"available": True, "devices": devices, "reason": ""}
        finally:
            try:
                vk.vkDestroyInstance(instance, None)
            except Exception:
                pass
    except Exception as exc:
        return {"available": False, "devices": [], "reason": str(exc)}


def build_vulkan_native_runtime_backend(
    *,
    runtime: Dict[str, Any],
    worker_path: Path,
    library_resolver: Callable[[], str] = resolve_vulkan_library,
    native_inventory_collector: Callable[[str], Dict[str, Any]] = collect_vulkan_native_physical_devices,
    load_library: Callable[[str], Any] = ctypes.CDLL,
) -> Dict[str, Any]:
    library = library_resolver()
    loader_version = ""
    loader_reason = ""
    if library:
        try:
            vk = load_library(library)
            try:
                version_value = ctypes.c_uint32()
                enumerate_version = vk.vkEnumerateInstanceVersion
                enumerate_version.argtypes = [ctypes.POINTER(ctypes.c_uint32)]
                enumerate_version.restype = ctypes.c_int32
                code = int(enumerate_version(ctypes.byref(version_value)))
                if code == 0 and version_value.value:
                    loader_version = f"{(version_value.value >> 22) & 0x3FF}.{(version_value.value >> 12) & 0x3FF}.{version_value.value & 0xFFF}"
                else:
                    loader_reason = f"vkEnumerateInstanceVersion returned {code}"
            except AttributeError:
                loader_version = "1.0-compatible loader"
        except Exception as exc:
            loader_reason = str(exc)
            library = ""
    else:
        loader_reason = "Vulkan loader library not found"

    native_inventory = native_inventory_collector(library)
    merged_runtime = dict(runtime)
    merged_runtime["devices"] = merge_vulkan_device_inventories(
        list(runtime.get("devices") or []),
        list(native_inventory.get("devices") or []),
    )
    return build_vulkan_native_backend_payload(
        runtime=merged_runtime,
        library=library,
        loader_version=loader_version,
        loader_reason=loader_reason,
        native_inventory=native_inventory,
        worker_path=worker_path,
    )
