#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import ctypes
import ctypes.util
import json
import os
import signal
import struct
import sys
import time


VK_SUCCESS = 0
VK_TRUE = 1
VK_NULL_HANDLE = None
VK_QUEUE_GRAPHICS_BIT = 0x00000001
VK_QUEUE_COMPUTE_BIT = 0x00000002
VK_QUEUE_TRANSFER_BIT = 0x00000004
VK_BUFFER_USAGE_TRANSFER_SRC_BIT = 0x00000001
VK_BUFFER_USAGE_TRANSFER_DST_BIT = 0x00000002
VK_SHARING_MODE_EXCLUSIVE = 0
VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT = 0x00000001
VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT = 0x00000002
VK_MEMORY_PROPERTY_HOST_COHERENT_BIT = 0x00000004
VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT = 0x00000002
VK_COMMAND_BUFFER_LEVEL_PRIMARY = 0
VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT = 0x00000001
VK_PIPELINE_STAGE_TRANSFER_BIT = 0x00001000
VK_PIPELINE_STAGE_HOST_BIT = 0x00004000
VK_ACCESS_TRANSFER_READ_BIT = 0x00000800
VK_ACCESS_TRANSFER_WRITE_BIT = 0x00001000
VK_ACCESS_SHADER_WRITE_BIT = 0x00000040
VK_ACCESS_HOST_READ_BIT = 0x00002000
VK_DEPENDENCY_BY_REGION_BIT = 0x00000001
VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER = 44
VK_QUEUE_FAMILY_IGNORED = 0xFFFFFFFF
VK_BUFFER_USAGE_STORAGE_BUFFER_BIT = 0x00000020
VK_DESCRIPTOR_TYPE_STORAGE_BUFFER = 7
VK_PIPELINE_BIND_POINT_COMPUTE = 1
VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT = 0x00000800
VK_SHADER_STAGE_COMPUTE_BIT = 0x00000020
VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO = 16
VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO = 18
VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO = 28
VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO = 30
VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO = 32
VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO = 33
VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO = 34
VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET = 35

VK_STRUCTURE_TYPE_APPLICATION_INFO = 0
VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO = 1
VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO = 2
VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO = 3
VK_STRUCTURE_TYPE_SUBMIT_INFO = 4
VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO = 5
VK_STRUCTURE_TYPE_FENCE_CREATE_INFO = 8
VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO = 12
VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO = 39
VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO = 40
VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO = 42
VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2 = 1000059001
VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PCI_BUS_INFO_PROPERTIES_EXT = 1000212000


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


class VkDeviceQueueCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("queueFamilyIndex", ctypes.c_uint32),
        ("queueCount", ctypes.c_uint32),
        ("pQueuePriorities", ctypes.POINTER(ctypes.c_float)),
    ]


class VkDeviceCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("queueCreateInfoCount", ctypes.c_uint32),
        ("pQueueCreateInfos", ctypes.POINTER(VkDeviceQueueCreateInfo)),
        ("enabledLayerCount", ctypes.c_uint32),
        ("ppEnabledLayerNames", ctypes.c_void_p),
        ("enabledExtensionCount", ctypes.c_uint32),
        ("ppEnabledExtensionNames", ctypes.c_void_p),
        ("pEnabledFeatures", ctypes.c_void_p),
    ]


class VkBufferCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("size", ctypes.c_uint64),
        ("usage", ctypes.c_uint32),
        ("sharingMode", ctypes.c_uint32),
        ("queueFamilyIndexCount", ctypes.c_uint32),
        ("pQueueFamilyIndices", ctypes.c_void_p),
    ]


class VkMemoryRequirements(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint64),
        ("alignment", ctypes.c_uint64),
        ("memoryTypeBits", ctypes.c_uint32),
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


class VkMemoryAllocateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("allocationSize", ctypes.c_uint64),
        ("memoryTypeIndex", ctypes.c_uint32),
    ]


class VkExtent3D(ctypes.Structure):
    _fields_ = [("width", ctypes.c_uint32), ("height", ctypes.c_uint32), ("depth", ctypes.c_uint32)]


class VkQueueFamilyProperties(ctypes.Structure):
    _fields_ = [
        ("queueFlags", ctypes.c_uint32),
        ("queueCount", ctypes.c_uint32),
        ("timestampValidBits", ctypes.c_uint32),
        ("minImageTransferGranularity", VkExtent3D),
    ]


class VkPhysicalDevicePCIBusInfoPropertiesEXT(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("pciDomain", ctypes.c_uint32),
        ("pciBus", ctypes.c_uint32),
        ("pciDevice", ctypes.c_uint32),
        ("pciFunction", ctypes.c_uint32),
    ]


class VkPhysicalDeviceProperties2(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("properties", ctypes.c_byte * 8192),
    ]


class VkCommandPoolCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("queueFamilyIndex", ctypes.c_uint32),
    ]


class VkCommandBufferAllocateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("commandPool", ctypes.c_void_p),
        ("level", ctypes.c_uint32),
        ("commandBufferCount", ctypes.c_uint32),
    ]


class VkCommandBufferBeginInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("pInheritanceInfo", ctypes.c_void_p),
    ]


class VkBufferCopy(ctypes.Structure):
    _fields_ = [
        ("srcOffset", ctypes.c_uint64),
        ("dstOffset", ctypes.c_uint64),
        ("size", ctypes.c_uint64),
    ]


class VkBufferMemoryBarrier(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("srcAccessMask", ctypes.c_uint32),
        ("dstAccessMask", ctypes.c_uint32),
        ("srcQueueFamilyIndex", ctypes.c_uint32),
        ("dstQueueFamilyIndex", ctypes.c_uint32),
        ("buffer", ctypes.c_void_p),
        ("offset", ctypes.c_uint64),
        ("size", ctypes.c_uint64),
    ]


class VkShaderModuleCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("codeSize", ctypes.c_size_t),
        ("pCode", ctypes.POINTER(ctypes.c_uint32)),
    ]


class VkDescriptorSetLayoutBinding(ctypes.Structure):
    _fields_ = [
        ("binding", ctypes.c_uint32),
        ("descriptorType", ctypes.c_uint32),
        ("descriptorCount", ctypes.c_uint32),
        ("stageFlags", ctypes.c_uint32),
        ("pImmutableSamplers", ctypes.c_void_p),
    ]


class VkDescriptorSetLayoutCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("bindingCount", ctypes.c_uint32),
        ("pBindings", ctypes.POINTER(VkDescriptorSetLayoutBinding)),
    ]


class VkPipelineLayoutCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("setLayoutCount", ctypes.c_uint32),
        ("pSetLayouts", ctypes.POINTER(ctypes.c_void_p)),
        ("pushConstantRangeCount", ctypes.c_uint32),
        ("pPushConstantRanges", ctypes.c_void_p),
    ]


class VkPipelineShaderStageCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("stage", ctypes.c_uint32),
        ("module", ctypes.c_void_p),
        ("pName", ctypes.c_char_p),
        ("pSpecializationInfo", ctypes.c_void_p),
    ]


class VkComputePipelineCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("stage", VkPipelineShaderStageCreateInfo),
        ("layout", ctypes.c_void_p),
        ("basePipelineHandle", ctypes.c_void_p),
        ("basePipelineIndex", ctypes.c_int32),
    ]


class VkDescriptorPoolSize(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("descriptorCount", ctypes.c_uint32),
    ]


class VkDescriptorPoolCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("maxSets", ctypes.c_uint32),
        ("poolSizeCount", ctypes.c_uint32),
        ("pPoolSizes", ctypes.POINTER(VkDescriptorPoolSize)),
    ]


class VkDescriptorSetAllocateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("descriptorPool", ctypes.c_void_p),
        ("descriptorSetCount", ctypes.c_uint32),
        ("pSetLayouts", ctypes.POINTER(ctypes.c_void_p)),
    ]


class VkDescriptorBufferInfo(ctypes.Structure):
    _fields_ = [
        ("buffer", ctypes.c_void_p),
        ("offset", ctypes.c_uint64),
        ("range", ctypes.c_uint64),
    ]


class VkWriteDescriptorSet(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("dstSet", ctypes.c_void_p),
        ("dstBinding", ctypes.c_uint32),
        ("dstArrayElement", ctypes.c_uint32),
        ("descriptorCount", ctypes.c_uint32),
        ("descriptorType", ctypes.c_uint32),
        ("pImageInfo", ctypes.c_void_p),
        ("pBufferInfo", ctypes.POINTER(VkDescriptorBufferInfo)),
        ("pTexelBufferView", ctypes.c_void_p),
    ]


class VkSubmitInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("waitSemaphoreCount", ctypes.c_uint32),
        ("pWaitSemaphores", ctypes.c_void_p),
        ("pWaitDstStageMask", ctypes.c_void_p),
        ("commandBufferCount", ctypes.c_uint32),
        ("pCommandBuffers", ctypes.POINTER(ctypes.c_void_p)),
        ("signalSemaphoreCount", ctypes.c_uint32),
        ("pSignalSemaphores", ctypes.c_void_p),
    ]


class VkFenceCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
    ]


def resolve_vulkan_library() -> str:
    candidates = []
    env_candidate = os.environ.get("VULKAN_LIBRARY_PATH", "").strip()
    if env_candidate:
        candidates.append(env_candidate)
    found = ctypes.util.find_library("vulkan")
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
            "/lib64/libvulkan.so.1",
            "/lib64/libvulkan.so",
        ]
    )
    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            ctypes.CDLL(candidate)
            return candidate
        except Exception:
            continue
    return ""


def load_vulkan(library: str) -> ctypes.CDLL:
    vk = ctypes.CDLL(library)
    vk.vkCreateInstance.argtypes = [ctypes.POINTER(VkInstanceCreateInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    vk.vkCreateInstance.restype = ctypes.c_int32
    vk.vkDestroyInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    vk.vkDestroyInstance.restype = None
    vk.vkEnumeratePhysicalDevices.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p)]
    vk.vkEnumeratePhysicalDevices.restype = ctypes.c_int32
    vk.vkGetPhysicalDeviceProperties.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    vk.vkGetPhysicalDeviceProperties.restype = None
    if hasattr(vk, "vkGetPhysicalDeviceProperties2"):
        vk.vkGetPhysicalDeviceProperties2.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(VkPhysicalDeviceProperties2),
        ]
        vk.vkGetPhysicalDeviceProperties2.restype = None
    vk.vkGetPhysicalDeviceMemoryProperties.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkPhysicalDeviceMemoryProperties)]
    vk.vkGetPhysicalDeviceMemoryProperties.restype = None
    vk.vkGetPhysicalDeviceQueueFamilyProperties.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(VkQueueFamilyProperties)]
    vk.vkGetPhysicalDeviceQueueFamilyProperties.restype = None
    vk.vkCreateDevice.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkDeviceCreateInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    vk.vkCreateDevice.restype = ctypes.c_int32
    vk.vkDestroyDevice.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    vk.vkDestroyDevice.restype = None
    vk.vkGetDeviceQueue.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    vk.vkGetDeviceQueue.restype = None
    vk.vkCreateBuffer.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkBufferCreateInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    vk.vkCreateBuffer.restype = ctypes.c_int32
    vk.vkDestroyBuffer.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    vk.vkDestroyBuffer.restype = None
    vk.vkGetBufferMemoryRequirements.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(VkMemoryRequirements)]
    vk.vkGetBufferMemoryRequirements.restype = None
    vk.vkAllocateMemory.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkMemoryAllocateInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    vk.vkAllocateMemory.restype = ctypes.c_int32
    vk.vkFreeMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    vk.vkFreeMemory.restype = None
    vk.vkBindBufferMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint64]
    vk.vkBindBufferMemory.restype = ctypes.c_int32
    vk.vkMapMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    vk.vkMapMemory.restype = ctypes.c_int32
    vk.vkUnmapMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    vk.vkUnmapMemory.restype = None
    vk.vkCreateCommandPool.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkCommandPoolCreateInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    vk.vkCreateCommandPool.restype = ctypes.c_int32
    vk.vkDestroyCommandPool.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    vk.vkDestroyCommandPool.restype = None
    vk.vkAllocateCommandBuffers.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkCommandBufferAllocateInfo), ctypes.POINTER(ctypes.c_void_p)]
    vk.vkAllocateCommandBuffers.restype = ctypes.c_int32
    vk.vkResetCommandBuffer.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    vk.vkResetCommandBuffer.restype = ctypes.c_int32
    vk.vkBeginCommandBuffer.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkCommandBufferBeginInfo)]
    vk.vkBeginCommandBuffer.restype = ctypes.c_int32
    vk.vkEndCommandBuffer.argtypes = [ctypes.c_void_p]
    vk.vkEndCommandBuffer.restype = ctypes.c_int32
    vk.vkCmdFillBuffer.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint32]
    vk.vkCmdFillBuffer.restype = None
    vk.vkCmdCopyBuffer.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(VkBufferCopy)]
    vk.vkCmdCopyBuffer.restype = None
    vk.vkCmdPipelineBarrier.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(VkBufferMemoryBarrier),
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    vk.vkCmdPipelineBarrier.restype = None
    vk.vkCreateFence.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkFenceCreateInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    vk.vkCreateFence.restype = ctypes.c_int32
    vk.vkDestroyFence.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    vk.vkDestroyFence.restype = None
    vk.vkResetFences.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    vk.vkResetFences.restype = ctypes.c_int32
    vk.vkQueueSubmit.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(VkSubmitInfo), ctypes.c_void_p]
    vk.vkQueueSubmit.restype = ctypes.c_int32
    vk.vkWaitForFences.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint32, ctypes.c_uint64]
    vk.vkWaitForFences.restype = ctypes.c_int32
    vk.vkDeviceWaitIdle.argtypes = [ctypes.c_void_p]
    vk.vkDeviceWaitIdle.restype = ctypes.c_int32
    return vk


def check(code: int, context: str) -> None:
    if int(code) != VK_SUCCESS:
        raise RuntimeError(f"{context} failed with Vulkan code {int(code)}")


def normalize_pci_slot(slot: str) -> str:
    text = str(slot or "").strip().lower().removeprefix("pci-")
    if not text:
        return ""
    parts = text.split(":")
    if len(parts) == 3:
        domain = parts[0][-4:].zfill(4)
        return f"{domain}:{parts[1].zfill(2)}:{parts[2]}"
    if len(parts) == 2:
        return f"0000:{parts[0].zfill(2)}:{parts[1]}"
    return text


def read_pci_slot(vk: ctypes.CDLL, physical_device: ctypes.c_void_p) -> str:
    get_properties2 = getattr(vk, "vkGetPhysicalDeviceProperties2", None)
    if get_properties2 is None:
        return ""
    pci = VkPhysicalDevicePCIBusInfoPropertiesEXT(
        VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PCI_BUS_INFO_PROPERTIES_EXT,
        VK_NULL_HANDLE,
        0,
        0,
        0,
        0,
    )
    props2 = VkPhysicalDeviceProperties2(
        VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2,
        ctypes.cast(ctypes.pointer(pci), ctypes.c_void_p),
        (ctypes.c_byte * 8192)(),
    )
    try:
        get_properties2(physical_device, ctypes.byref(props2))
    except Exception:
        return ""
    if int(pci.pciDomain) == 0 and int(pci.pciBus) == 0 and int(pci.pciDevice) == 0 and int(pci.pciFunction) == 0:
        return ""
    return f"{int(pci.pciDomain):04x}:{int(pci.pciBus):02x}:{int(pci.pciDevice):02x}.{int(pci.pciFunction):x}"


def parse_properties(vk: ctypes.CDLL, physical_device: ctypes.c_void_p, index: int) -> dict:
    props = ctypes.create_string_buffer(8192)
    vk.vkGetPhysicalDeviceProperties(physical_device, ctypes.byref(props))
    raw = props.raw
    api_version = int.from_bytes(raw[0:4], "little")
    driver_version = int.from_bytes(raw[4:8], "little")
    vendor_id = int.from_bytes(raw[8:12], "little")
    device_id = int.from_bytes(raw[12:16], "little")
    device_type = int.from_bytes(raw[16:20], "little")
    name = raw[20:276].split(b"\0", 1)[0].decode("utf-8", "ignore")
    type_names = {
        0: "other",
        1: "integrated",
        2: "discrete",
        3: "virtual",
        4: "cpu",
    }
    return {
        "index": index,
        "api_version": f"{(api_version >> 22) & 0x3FF}.{(api_version >> 12) & 0x3FF}.{api_version & 0xFFF}",
        "driver_version_raw": driver_version,
        "vendor_id": f"{vendor_id:04x}",
        "device_id": f"{device_id:04x}",
        "device_type": type_names.get(device_type, str(device_type)),
        "device_name": name,
        "pci_slot": read_pci_slot(vk, physical_device),
    }


def score_device(info: dict, args: argparse.Namespace) -> float:
    score = 0.0
    target_vendor_id = (args.target_vendor_id or "").lower().removeprefix("0x")
    target_device_id = (args.target_device_id or "").lower().removeprefix("0x")
    target_vendor = (args.target_vendor or "").lower()
    target_index = int(args.target_gpu_index)
    target_slot = normalize_pci_slot(args.target_slot or args.target_id or "")
    device_slot = normalize_pci_slot(info.get("pci_slot", ""))
    name = str(info.get("device_name", "")).lower()
    if target_slot and device_slot:
        if target_slot == device_slot:
            score += 2500.0
        else:
            return -1000000.0
    if target_vendor_id and target_vendor_id == info.get("vendor_id"):
        score += 500.0
    if target_device_id and target_device_id == info.get("device_id"):
        score += 900.0
    if target_vendor and target_vendor in name:
        score += 50.0
    if str(args.device_class or "").lower() == str(info.get("device_type") or "").lower():
        score += 90.0
    if int(info.get("index", -1)) == target_index:
        score += 20.0
    if str(info.get("device_type")) == "cpu" or "llvmpipe" in name:
        score -= 10000.0
    return score


def make_instance(vk: ctypes.CDLL) -> ctypes.c_void_p:
    app_info = VkApplicationInfo(
        VK_STRUCTURE_TYPE_APPLICATION_INFO,
        VK_NULL_HANDLE,
        b"Linux Validation Suite",
        1,
        b"linux-validation-suite",
        1,
        (1 << 22),
    )
    create_info = VkInstanceCreateInfo(
        VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
        VK_NULL_HANDLE,
        0,
        ctypes.pointer(app_info),
        0,
        VK_NULL_HANDLE,
        0,
        VK_NULL_HANDLE,
    )
    instance = ctypes.c_void_p()
    check(vk.vkCreateInstance(ctypes.byref(create_info), None, ctypes.byref(instance)), "vkCreateInstance")
    return instance


def enumerate_devices(vk: ctypes.CDLL, instance: ctypes.c_void_p) -> list:
    count = ctypes.c_uint32()
    check(vk.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), None), "vkEnumeratePhysicalDevices(count)")
    if count.value <= 0:
        raise RuntimeError("no Vulkan physical devices found")
    devices = (ctypes.c_void_p * count.value)()
    check(vk.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), devices), "vkEnumeratePhysicalDevices(list)")
    return [devices[index] for index in range(count.value)]


def choose_queue_family(vk: ctypes.CDLL, physical_device: ctypes.c_void_p) -> int:
    count = ctypes.c_uint32()
    vk.vkGetPhysicalDeviceQueueFamilyProperties(physical_device, ctypes.byref(count), None)
    if count.value <= 0:
        raise RuntimeError("selected Vulkan device has no queue families")
    props = (VkQueueFamilyProperties * count.value)()
    vk.vkGetPhysicalDeviceQueueFamilyProperties(physical_device, ctypes.byref(count), props)
    best_index = -1
    best_score = -1
    for index in range(count.value):
        if props[index].queueCount <= 0:
            continue
        flags = int(props[index].queueFlags)
        if not (flags & (VK_QUEUE_TRANSFER_BIT | VK_QUEUE_COMPUTE_BIT | VK_QUEUE_GRAPHICS_BIT)):
            continue
        score = 0
        if flags & VK_QUEUE_TRANSFER_BIT:
            score += 30
        if flags & VK_QUEUE_COMPUTE_BIT:
            score += 20
        if flags & VK_QUEUE_GRAPHICS_BIT:
            score += 10
        if score > best_score:
            best_score = score
            best_index = index
    if best_index < 0:
        raise RuntimeError("selected Vulkan device has no usable transfer/compute/graphics queue")
    return best_index


def find_memory_type(memory_props: VkPhysicalDeviceMemoryProperties, bits: int, required: int, preferred: int = 0) -> int:
    fallback = -1
    for index in range(int(memory_props.memoryTypeCount)):
        if not (bits & (1 << index)):
            continue
        flags = int(memory_props.memoryTypes[index].propertyFlags)
        if (flags & required) != required:
            continue
        if preferred and (flags & preferred) == preferred:
            return index
        if fallback < 0:
            fallback = index
    if fallback >= 0:
        return fallback
    raise RuntimeError(f"no Vulkan memory type matched required flags 0x{required:x}")


def create_buffer(vk, device, memory_props, size, usage, required_flags, preferred_flags=0):
    buffer_info = VkBufferCreateInfo(
        VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        VK_NULL_HANDLE,
        0,
        int(size),
        int(usage),
        VK_SHARING_MODE_EXCLUSIVE,
        0,
        VK_NULL_HANDLE,
    )
    buffer_handle = ctypes.c_void_p()
    check(vk.vkCreateBuffer(device, ctypes.byref(buffer_info), None, ctypes.byref(buffer_handle)), "vkCreateBuffer")
    req = VkMemoryRequirements()
    vk.vkGetBufferMemoryRequirements(device, buffer_handle, ctypes.byref(req))
    memory_type = find_memory_type(memory_props, int(req.memoryTypeBits), required_flags, preferred_flags)
    alloc_info = VkMemoryAllocateInfo(
        VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
        VK_NULL_HANDLE,
        int(req.size),
        int(memory_type),
    )
    memory = ctypes.c_void_p()
    try:
        check(vk.vkAllocateMemory(device, ctypes.byref(alloc_info), None, ctypes.byref(memory)), "vkAllocateMemory")
        check(vk.vkBindBufferMemory(device, buffer_handle, memory, 0), "vkBindBufferMemory")
    except Exception:
        if memory:
            vk.vkFreeMemory(device, memory, None)
        vk.vkDestroyBuffer(device, buffer_handle, None)
        raise
    return buffer_handle, memory, int(req.size), memory_type


def pattern_for_frame(frame: int) -> int:
    value = (0xA5A5A5A5 ^ ((int(frame) + 1) * 0x01010101)) & 0xFFFFFFFF
    return value or 0xFFFFFFFF


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-vendor", default="")
    parser.add_argument("--target-vendor-id", default="")
    parser.add_argument("--target-device-id", default="")
    parser.add_argument("--target-card", default="")
    parser.add_argument("--target-slot", default="")
    parser.add_argument("--target-id", default="")
    parser.add_argument("--target-gpu-index", type=int, default=0)
    parser.add_argument("--target-vram-total", type=int, default=0)
    parser.add_argument("--buffer-bytes", type=int, default=128 * 1024 * 1024)
    parser.add_argument("--ramp-step-seconds", type=float, default=15.0)
    parser.add_argument("--start-load-fraction", type=float, default=0.35)
    parser.add_argument("--result-file", default="")
    parser.add_argument("--device-class", default="")
    parser.add_argument("--profile-mode", default="steady")
    parser.add_argument("--profile-intensity", default="extreme")
    parser.add_argument("--tuning-step", type=int, default=0)
    args = parser.parse_args()

    state = {
        "kind": "gpu",
        "mode": "gpu_3d",
        "backend": "python_vulkan_transfer",
        "worker_version": "vulkan_transfer_barrier_v2",
        "backend_api_family": "Vulkan",
        "suite_scaling_mode": "parametric",
        "suite_verification": "transfer_readback",
        "synchronization_barriers": True,
        "diagnostic_backend": True,
        "saturation_result": False,
        "power_saturation_expected": False,
        "status": "ok",
        "error_count": 0,
        "verification_passes": 0,
        "transfer_mismatch_count": 0,
        "frames": 0,
        "buffer_bytes": 0,
        "requested_buffer_bytes": 0,
        "target_buffer_bytes": 0,
        "buffer_count": 0,
        "buffer_count_limit": 1,
        "buffer_size_min_bytes": 0,
        "buffer_size_max_bytes": 0,
        "buffer_size_avg_bytes": 0,
        "buffer_allocation_bytes": 0,
        "allocation_shortfall_bytes": 0,
        "allocation_strategy": "transfer_fill_copy_single_buffer_device_local",
        "requested_device_local_heap_percent": 0.0,
        "target_device_local_heap_percent": 0.0,
        "buffer_memory_type_index": -1,
        "buffer_memory_type_flags": 0,
        "buffer_memory_heap_index": -1,
        "buffer_device_local_heap_percent": 0.0,
        "staging_memory_type_index": -1,
        "device_local_heap_bytes": 0,
        "device_local_heap_gb": 0.0,
        "active_buffer_bytes": 0,
        "active_buffer_count": 0,
        "active_buffer_index": -1,
        "active_load_fraction": 0.0,
        "verified_buffer_count": 0,
        "verified_buffer_indexes": [],
        "verified_buffer_coverage_percent": 0.0,
        "elapsed_seconds": 0.0,
        "estimated_device_memory_bytes": 0,
        "estimated_device_memory_gb": 0.0,
        "estimated_device_memory_gbps": 0.0,
        "peak_estimated_device_memory_gbps": 0.0,
        "selected_device_name": "",
        "selected_device_vendor_id": "",
        "selected_device_id": "",
        "selected_device_type": "",
        "selected_device_pci_slot": "",
        "selected_vulkan_index": -1,
        "queue_family_index": -1,
        "target_vendor": args.target_vendor,
        "target_vendor_id": args.target_vendor_id,
        "target_device_id": args.target_device_id,
        "target_card": args.target_card,
        "target_slot": args.target_slot,
        "target_id": args.target_id,
        "target_gpu_index": args.target_gpu_index,
        "target_vram_total": args.target_vram_total,
        "profile_mode": args.profile_mode,
        "profile_intensity": args.profile_intensity,
        "tuning_step": args.tuning_step,
        "last_error": "",
    }
    running = True

    def record_error(message):
        state["status"] = "error"
        state["error_count"] += 1
        state["last_error"] = str(message)

    def write_result():
        if not args.result_file:
            return
        try:
            with open(args.result_file, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2)
        except Exception:
            pass

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    atexit.register(write_result)

    library = resolve_vulkan_library()
    if not library:
        record_error("Vulkan loader library not found")
        return 12

    vk = None
    instance = ctypes.c_void_p()
    device = ctypes.c_void_p()
    device_buffer = ctypes.c_void_p()
    device_memory = ctypes.c_void_p()
    staging_buffer = ctypes.c_void_p()
    staging_memory = ctypes.c_void_p()
    command_pool = ctypes.c_void_p()
    fence = ctypes.c_void_p()
    try:
        vk = load_vulkan(library)
        instance = make_instance(vk)
        physical_devices = enumerate_devices(vk, instance)
        infos = [(parse_properties(vk, physical_device, index), physical_device) for index, physical_device in enumerate(physical_devices)]
        ranked = sorted(((score_device(info, args), info, physical_device) for info, physical_device in infos), key=lambda item: item[0], reverse=True)
        score, selected_info, physical_device = ranked[0]
        if score < -1000:
            raise RuntimeError("no non-CPU Vulkan GPU device matched target")
        state.update(
            {
                "selected_device_name": selected_info["device_name"],
                "selected_device_vendor_id": selected_info["vendor_id"],
                "selected_device_id": selected_info["device_id"],
                "selected_device_type": selected_info["device_type"],
                "selected_device_pci_slot": selected_info.get("pci_slot", ""),
                "selected_vulkan_index": selected_info["index"],
            }
        )

        queue_family = choose_queue_family(vk, physical_device)
        state["queue_family_index"] = queue_family
        priority = ctypes.c_float(1.0)
        queue_info = VkDeviceQueueCreateInfo(
            VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
            VK_NULL_HANDLE,
            0,
            queue_family,
            1,
            ctypes.pointer(priority),
        )
        device_info = VkDeviceCreateInfo(
            VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
            VK_NULL_HANDLE,
            0,
            1,
            ctypes.pointer(queue_info),
            0,
            VK_NULL_HANDLE,
            0,
            VK_NULL_HANDLE,
            VK_NULL_HANDLE,
        )
        check(vk.vkCreateDevice(physical_device, ctypes.byref(device_info), None, ctypes.byref(device)), "vkCreateDevice")
        queue = ctypes.c_void_p()
        vk.vkGetDeviceQueue(device, queue_family, 0, ctypes.byref(queue))

        memory_props = VkPhysicalDeviceMemoryProperties()
        vk.vkGetPhysicalDeviceMemoryProperties(physical_device, ctypes.byref(memory_props))
        device_local_heap_bytes = 0
        for heap_index in range(int(memory_props.memoryHeapCount)):
            heap = memory_props.memoryHeaps[heap_index]
            if int(heap.flags) & VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT:
                device_local_heap_bytes += int(heap.size)
        state["device_local_heap_bytes"] = int(device_local_heap_bytes)
        state["device_local_heap_gb"] = round(device_local_heap_bytes / (1024 ** 3), 3) if device_local_heap_bytes else 0.0
        requested_size = max(16 * 1024 * 1024, int(args.buffer_bytes))
        requested_size = min(requested_size, 512 * 1024 * 1024)
        requested_size -= requested_size % 4
        state["requested_buffer_bytes"] = int(args.buffer_bytes)
        if device_local_heap_bytes:
            state["requested_device_local_heap_percent"] = round((int(args.buffer_bytes) / float(device_local_heap_bytes)) * 100.0, 4)
            state["target_device_local_heap_percent"] = round((int(requested_size) / float(device_local_heap_bytes)) * 100.0, 4)

        while requested_size >= 16 * 1024 * 1024:
            try:
                device_buffer, device_memory, device_allocation_bytes, device_memory_type = create_buffer(
                    vk,
                    device,
                    memory_props,
                    requested_size,
                    VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT,
                    0,
                    VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,
                )
                staging_buffer, staging_memory, _, staging_memory_type = create_buffer(
                    vk,
                    device,
                    memory_props,
                    requested_size,
                    VK_BUFFER_USAGE_TRANSFER_DST_BIT,
                    VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
                )
                break
            except Exception:
                if device_buffer:
                    try:
                        vk.vkDestroyBuffer(device, device_buffer, None)
                    except Exception:
                        pass
                    device_buffer = ctypes.c_void_p()
                if device_memory:
                    try:
                        vk.vkFreeMemory(device, device_memory, None)
                    except Exception:
                        pass
                    device_memory = ctypes.c_void_p()
                requested_size //= 2
                requested_size -= requested_size % 4
        if not device_buffer or not staging_buffer:
            raise RuntimeError("unable to allocate Vulkan transfer buffers")
        state["buffer_bytes"] = requested_size
        state["target_buffer_bytes"] = requested_size
        state["buffer_count"] = 1
        state["buffer_size_min_bytes"] = int(requested_size)
        state["buffer_size_max_bytes"] = int(requested_size)
        state["buffer_size_avg_bytes"] = int(requested_size)
        state["buffer_allocation_bytes"] = int(device_allocation_bytes)
        state["allocation_shortfall_bytes"] = 0
        state["buffer_memory_type_index"] = int(device_memory_type)
        state["staging_memory_type_index"] = int(staging_memory_type)
        if 0 <= int(device_memory_type) < int(memory_props.memoryTypeCount):
            memory_type = memory_props.memoryTypes[int(device_memory_type)]
            state["buffer_memory_type_flags"] = int(memory_type.propertyFlags)
            state["buffer_memory_heap_index"] = int(memory_type.heapIndex)
        if device_local_heap_bytes:
            state["buffer_device_local_heap_percent"] = round((int(device_allocation_bytes) / float(device_local_heap_bytes)) * 100.0, 4)

        pool_info = VkCommandPoolCreateInfo(
            VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
            VK_NULL_HANDLE,
            VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT,
            queue_family,
        )
        check(vk.vkCreateCommandPool(device, ctypes.byref(pool_info), None, ctypes.byref(command_pool)), "vkCreateCommandPool")
        alloc_info = VkCommandBufferAllocateInfo(
            VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
            VK_NULL_HANDLE,
            command_pool,
            VK_COMMAND_BUFFER_LEVEL_PRIMARY,
            1,
        )
        command_buffer = ctypes.c_void_p()
        check(vk.vkAllocateCommandBuffers(device, ctypes.byref(alloc_info), ctypes.byref(command_buffer)), "vkAllocateCommandBuffers")
        fence_info = VkFenceCreateInfo(VK_STRUCTURE_TYPE_FENCE_CREATE_INFO, VK_NULL_HANDLE, 0)
        check(vk.vkCreateFence(device, ctypes.byref(fence_info), None, ctypes.byref(fence)), "vkCreateFence")
        fence_array = (ctypes.c_void_p * 1)(fence)
        command_array = (ctypes.c_void_p * 1)(command_buffer)
        started = time.monotonic()
        sample_words = 256
        total_estimated_memory_bytes = 0

        while running:
            elapsed = time.monotonic() - started
            if args.ramp_step_seconds > 0:
                progress = min(1.0, elapsed / max(0.001, args.ramp_step_seconds * 3.0))
                load_fraction = min(1.0, max(0.15, args.start_load_fraction) + (1.0 - max(0.15, args.start_load_fraction)) * progress)
            else:
                load_fraction = 1.0
            active_size = max(4 * 1024 * 1024, int(requested_size * load_fraction))
            active_size -= active_size % 4
            active_size = max(4, min(requested_size, active_size))
            pattern = pattern_for_frame(state["frames"])

            check(vk.vkResetFences(device, 1, fence_array), "vkResetFences")
            check(vk.vkResetCommandBuffer(command_buffer, 0), "vkResetCommandBuffer")
            begin_info = VkCommandBufferBeginInfo(
                VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
                VK_NULL_HANDLE,
                VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT,
                VK_NULL_HANDLE,
            )
            check(vk.vkBeginCommandBuffer(command_buffer, ctypes.byref(begin_info)), "vkBeginCommandBuffer")
            vk.vkCmdFillBuffer(command_buffer, device_buffer, 0, active_size, pattern)
            fill_to_copy_barrier = VkBufferMemoryBarrier(
                VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER,
                VK_NULL_HANDLE,
                VK_ACCESS_TRANSFER_WRITE_BIT,
                VK_ACCESS_TRANSFER_READ_BIT,
                VK_QUEUE_FAMILY_IGNORED,
                VK_QUEUE_FAMILY_IGNORED,
                device_buffer,
                0,
                active_size,
            )
            vk.vkCmdPipelineBarrier(
                command_buffer,
                VK_PIPELINE_STAGE_TRANSFER_BIT,
                VK_PIPELINE_STAGE_TRANSFER_BIT,
                VK_DEPENDENCY_BY_REGION_BIT,
                0,
                VK_NULL_HANDLE,
                1,
                ctypes.byref(fill_to_copy_barrier),
                0,
                VK_NULL_HANDLE,
            )
            region = VkBufferCopy(0, 0, active_size)
            vk.vkCmdCopyBuffer(command_buffer, device_buffer, staging_buffer, 1, ctypes.byref(region))
            copy_to_host_barrier = VkBufferMemoryBarrier(
                VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER,
                VK_NULL_HANDLE,
                VK_ACCESS_TRANSFER_WRITE_BIT,
                VK_ACCESS_HOST_READ_BIT,
                VK_QUEUE_FAMILY_IGNORED,
                VK_QUEUE_FAMILY_IGNORED,
                staging_buffer,
                0,
                active_size,
            )
            vk.vkCmdPipelineBarrier(
                command_buffer,
                VK_PIPELINE_STAGE_TRANSFER_BIT,
                VK_PIPELINE_STAGE_HOST_BIT,
                VK_DEPENDENCY_BY_REGION_BIT,
                0,
                VK_NULL_HANDLE,
                1,
                ctypes.byref(copy_to_host_barrier),
                0,
                VK_NULL_HANDLE,
            )
            check(vk.vkEndCommandBuffer(command_buffer), "vkEndCommandBuffer")
            submit = VkSubmitInfo(
                VK_STRUCTURE_TYPE_SUBMIT_INFO,
                VK_NULL_HANDLE,
                0,
                VK_NULL_HANDLE,
                VK_NULL_HANDLE,
                1,
                command_array,
                0,
                VK_NULL_HANDLE,
            )
            check(vk.vkQueueSubmit(queue, 1, ctypes.byref(submit), fence), "vkQueueSubmit")
            check(vk.vkWaitForFences(device, 1, fence_array, VK_TRUE, 10_000_000_000), "vkWaitForFences")

            if state["frames"] % 3 == 0:
                mapped = ctypes.c_void_p()
                sample_bytes = min(active_size, sample_words * 4)
                check(vk.vkMapMemory(device, staging_memory, 0, sample_bytes, 0, ctypes.byref(mapped)), "vkMapMemory")
                try:
                    raw = ctypes.string_at(mapped, sample_bytes)
                finally:
                    vk.vkUnmapMemory(device, staging_memory)
                expected = struct.pack("<I", pattern)
                for offset in range(0, sample_bytes, 4):
                    if raw[offset : offset + 4] != expected:
                        state["transfer_mismatch_count"] += 1
                        record_error(f"Vulkan transfer mismatch at byte {offset}")
                        break
                state["verification_passes"] += 1
                state["verified_buffer_count"] = 1
                state["verified_buffer_indexes"] = [0]
                state["verified_buffer_coverage_percent"] = 100.0

            state["active_load_fraction"] = round(load_fraction, 3)
            state["active_buffer_bytes"] = active_size
            state["active_buffer_count"] = 1
            state["active_buffer_index"] = 0
            state["frames"] += 1
            state["elapsed_seconds"] = round(max(0.0, time.monotonic() - started), 3)
            total_estimated_memory_bytes += active_size * 2
            state["estimated_device_memory_bytes"] = int(total_estimated_memory_bytes)
            state["estimated_device_memory_gb"] = round(total_estimated_memory_bytes / (1024 ** 3), 3)
            if state["elapsed_seconds"] > 0:
                state["estimated_device_memory_gbps"] = round(
                    total_estimated_memory_bytes / state["elapsed_seconds"] / (1024 ** 3),
                    3,
                )
                state["peak_estimated_device_memory_gbps"] = max(
                    float(state.get("peak_estimated_device_memory_gbps") or 0.0),
                    float(state["estimated_device_memory_gbps"]),
                )
            if state["frames"] % 10 == 0:
                write_result()
            time.sleep(0.001)
        return 0
    except Exception as exc:
        record_error(exc)
        return 12
    finally:
        try:
            if vk and device:
                vk.vkDeviceWaitIdle(device)
        except Exception:
            pass
        for handle, destroy in (
            (fence, "vkDestroyFence"),
            (command_pool, "vkDestroyCommandPool"),
            (staging_buffer, "vkDestroyBuffer"),
            (device_buffer, "vkDestroyBuffer"),
        ):
            if vk and device and handle:
                try:
                    getattr(vk, destroy)(device, handle, None)
                except Exception:
                    pass
        for memory in (staging_memory, device_memory):
            if vk and device and memory:
                try:
                    vk.vkFreeMemory(device, memory, None)
                except Exception:
                    pass
        if vk and device:
            try:
                vk.vkDestroyDevice(device, None)
            except Exception:
                pass
        if vk and instance:
            try:
                vk.vkDestroyInstance(instance, None)
            except Exception:
                pass
        write_result()


if __name__ == "__main__":
    raise SystemExit(main())
