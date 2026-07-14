#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import ctypes
import json
import math
import signal
import struct
import time

from vulkan_transfer_worker import (
    VK_ACCESS_HOST_READ_BIT,
    VK_ACCESS_SHADER_WRITE_BIT,
    VK_ACCESS_TRANSFER_READ_BIT,
    VK_ACCESS_TRANSFER_WRITE_BIT,
    VK_BUFFER_USAGE_TRANSFER_DST_BIT,
    VK_BUFFER_USAGE_TRANSFER_SRC_BIT,
    VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
    VK_COMMAND_BUFFER_LEVEL_PRIMARY,
    VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT,
    VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT,
    VK_DEPENDENCY_BY_REGION_BIT,
    VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
    VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
    VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT,
    VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,
    VK_NULL_HANDLE,
    VK_PIPELINE_BIND_POINT_COMPUTE,
    VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
    VK_PIPELINE_STAGE_HOST_BIT,
    VK_PIPELINE_STAGE_TRANSFER_BIT,
    VK_QUEUE_COMPUTE_BIT,
    VK_QUEUE_FAMILY_IGNORED,
    VK_SHADER_STAGE_COMPUTE_BIT,
    VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER,
    VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
    VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
    VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
    VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
    VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,
    VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,
    VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
    VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
    VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
    VK_STRUCTURE_TYPE_FENCE_CREATE_INFO,
    VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
    VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
    VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
    VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,
    VK_TRUE,
    VkApplicationInfo,
    VkBufferMemoryBarrier,
    VkBufferCopy,
    VkCommandBufferAllocateInfo,
    VkCommandBufferBeginInfo,
    VkCommandPoolCreateInfo,
    VkComputePipelineCreateInfo,
    VkDescriptorBufferInfo,
    VkDescriptorPoolCreateInfo,
    VkDescriptorPoolSize,
    VkDescriptorSetAllocateInfo,
    VkDescriptorSetLayoutBinding,
    VkDescriptorSetLayoutCreateInfo,
    VkDeviceCreateInfo,
    VkDeviceQueueCreateInfo,
    VkFenceCreateInfo,
    VkPipelineLayoutCreateInfo,
    VkPipelineShaderStageCreateInfo,
    VkShaderModuleCreateInfo,
    VkSubmitInfo,
    VkWriteDescriptorSet,
    check,
    create_buffer,
    enumerate_devices,
    load_vulkan,
    make_instance,
    parse_properties,
    resolve_vulkan_library,
    score_device,
)

VK_ACCESS_SHADER_READ_BIT = 0x00000020


def _words_for_string(value: str) -> list[int]:
    raw = value.encode("utf-8") + b"\0"
    while len(raw) % 4:
        raw += b"\0"
    return [int.from_bytes(raw[index : index + 4], "little") for index in range(0, len(raw), 4)]


def _inst(opcode: int, operands: list[int]) -> list[int]:
    return [((1 + len(operands)) << 16) | opcode, *operands]


def normalize_kernel_variant(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"stress", "stress_hash", "hash_stress", "compute_stress"}:
        return "stress_hash"
    if normalized in {"memory", "memory_mix", "stateful", "stateful_memory"}:
        return "stateful_memory"
    return "hash"


def kernel_round_limit(kernel_variant: str) -> int:
    variant = normalize_kernel_variant(kernel_variant)
    if variant == "stress_hash":
        return 192
    return 64


def kernel_dispatch_repeats(kernel_variant: str) -> int:
    variant = normalize_kernel_variant(kernel_variant)
    if variant == "stress_hash":
        return 4
    return 1


def resolve_dispatch_repeats(kernel_variant: str, requested_repeats: int = 0) -> int:
    variant = normalize_kernel_variant(kernel_variant)
    if variant != "stress_hash":
        return 1
    requested = int(requested_repeats or 0)
    if requested > 0:
        return max(1, min(8, requested))
    return kernel_dispatch_repeats(variant)


def compute_shader_spirv(compute_rounds: int, kernel_variant: str = "hash") -> bytes:
    # Hand-built SPIR-V for:
    # layout(local_size_x=256) in;
    # layout(std430, binding=0) buffer Data { uint data[]; };
    # void main() {
    #   uint v = gl_GlobalInvocationID.x;              // hash / stress_hash
    #   uint v = data[gl_GlobalInvocationID.x] ^ gid;  // stateful_memory
    #   repeat compute_rounds times:
    #     v ^= v >> 16; v *= 0x7FEB352Du;
    #     v ^= v >> 15; v *= 0x846CA68Bu;
    #     v ^= v >> 16; v += gl_GlobalInvocationID.x;
    #   data[gl_GlobalInvocationID.x] = v;
    # }
    words: list[int] = [0x07230203, 0x00010000, 0, 64, 0]
    words += _inst(17, [1])  # OpCapability Shader
    words += _inst(14, [0, 1])  # OpMemoryModel Logical GLSL450
    words += [((3 + len(_words_for_string("main")) + 1) << 16) | 15, 5, 13, *_words_for_string("main"), 11]
    words += _inst(16, [13, 17, 256, 1, 1])  # OpExecutionMode LocalSize
    words += _inst(71, [11, 11, 28])  # BuiltIn GlobalInvocationId
    words += _inst(71, [6, 6, 4])  # ArrayStride 4
    words += _inst(72, [7, 0, 35, 0])  # member offset
    words += _inst(71, [7, 3])  # BufferBlock
    words += _inst(71, [9, 34, 0])  # DescriptorSet 0
    words += _inst(71, [9, 33, 0])  # Binding 0
    words += _inst(19, [1])  # void
    words += _inst(33, [2, 1])  # function type
    words += _inst(21, [3, 32, 0])  # uint
    words += _inst(23, [4, 3, 3])  # v3uint
    words += _inst(43, [3, 5, 0])  # uint 0
    words += _inst(29, [6, 3])  # runtime array uint
    words += _inst(30, [7, 6])  # struct Data
    words += _inst(32, [8, 2, 7])  # ptr Uniform Data
    words += _inst(59, [8, 9, 2])  # data variable Uniform
    words += _inst(32, [10, 1, 4])  # ptr Input v3uint
    words += _inst(59, [10, 11, 1])  # global invocation id
    words += _inst(32, [12, 2, 3])  # ptr Uniform uint
    words += _inst(43, [3, 17, 16])  # shift 16
    words += _inst(43, [3, 18, 15])  # shift 15
    words += _inst(43, [3, 19, 0x7FEB352D])  # hash multiplier A
    words += _inst(43, [3, 20, 0x846CA68B])  # hash multiplier B
    words += _inst(54, [1, 13, 0, 2])  # function
    words += _inst(248, [14])  # label
    words += _inst(61, [4, 15, 11])  # load gid vector
    words += _inst(81, [3, 16, 15, 0])  # extract x
    variant = normalize_kernel_variant(kernel_variant)
    ptr_id = 0
    if variant == "stateful_memory":
        ptr_id = 21
        loaded_id = 22
        seed_id = 23
        words += _inst(65, [12, ptr_id, 9, 5, 16])  # access data[gid.x]
        words += _inst(61, [3, loaded_id, ptr_id])  # load previous data[gid.x]
        words += _inst(198, [3, seed_id, loaded_id, 16])  # previous ^ gid
        previous = seed_id
        next_id = 24
    else:
        previous = 16
        next_id = 21
    for _ in range(max(1, min(kernel_round_limit(variant), int(compute_rounds)))):
        shift1_id = next_id
        xor1_id = next_id + 1
        mul1_id = next_id + 2
        shift2_id = next_id + 3
        xor2_id = next_id + 4
        mul2_id = next_id + 5
        shift3_id = next_id + 6
        xor3_id = next_id + 7
        add_id = next_id + 8
        words += _inst(194, [3, shift1_id, previous, 17])  # ShiftRightLogical
        words += _inst(198, [3, xor1_id, previous, shift1_id])  # BitwiseXor
        words += _inst(132, [3, mul1_id, xor1_id, 19])  # IMul
        words += _inst(194, [3, shift2_id, mul1_id, 18])  # ShiftRightLogical
        words += _inst(198, [3, xor2_id, mul1_id, shift2_id])  # BitwiseXor
        words += _inst(132, [3, mul2_id, xor2_id, 20])  # IMul
        words += _inst(194, [3, shift3_id, mul2_id, 17])  # ShiftRightLogical
        words += _inst(198, [3, xor3_id, mul2_id, shift3_id])  # BitwiseXor
        words += _inst(128, [3, add_id, xor3_id, 16])  # IAdd original gid
        previous = add_id
        next_id += 9
    bound_id = next_id + 1
    if not ptr_id:
        ptr_id = next_id
        words += _inst(65, [12, ptr_id, 9, 5, 16])  # access data[gid.x]
        bound_id = ptr_id + 1
    words += _inst(62, [ptr_id, previous])  # store
    words += _inst(253, [])  # return
    words += _inst(56, [])  # function end
    words[3] = max(bound_id, ptr_id + 1)
    return b"".join(struct.pack("<I", word) for word in words)


def expected_word(index: int, compute_rounds: int, previous_value: int = 0, kernel_variant: str = "hash") -> int:
    original = int(index) & 0xFFFFFFFF
    variant = normalize_kernel_variant(kernel_variant)
    if variant == "stateful_memory":
        value = (int(previous_value) & 0xFFFFFFFF) ^ original
    else:
        value = original
    for _ in range(max(1, min(kernel_round_limit(variant), int(compute_rounds)))):
        value ^= value >> 16
        value = (value * 0x7FEB352D) & 0xFFFFFFFF
        value ^= value >> 15
        value = (value * 0x846CA68B) & 0xFFFFFFFF
        value ^= value >> 16
        value = (value + original) & 0xFFFFFFFF
    return value


def stateful_memory_buffer_cap(target_vram_total: int, device_local_heap_bytes: int, device_class: str) -> int:
    memory_total = int(target_vram_total or 0) or int(device_local_heap_bytes or 0)
    if memory_total >= 64 * 1024 ** 3:
        return 3584 * 1024 * 1024
    if memory_total >= 32 * 1024 ** 3:
        return 3584 * 1024 * 1024
    if memory_total >= 24 * 1024 ** 3:
        return 3 * 1024 * 1024 * 1024
    if memory_total >= 12 * 1024 ** 3:
        return 1536 * 1024 * 1024
    if memory_total >= 8 * 1024 ** 3:
        return 1024 * 1024 * 1024
    if memory_total >= 2 * 1024 ** 3:
        return 512 * 1024 * 1024
    if memory_total >= 1024 ** 3:
        return 256 * 1024 * 1024
    return 128 * 1024 * 1024


def stateful_memory_total_cap(target_vram_total: int, device_local_heap_bytes: int, device_class: str) -> int:
    memory_total = int(target_vram_total or 0) or int(device_local_heap_bytes or 0)
    if memory_total > 0:
        return max(64 * 1024 * 1024, int(memory_total * 0.9))
    return 512 * 1024 * 1024


def stress_hash_buffer_cap(target_vram_total: int, device_local_heap_bytes: int, device_class: str) -> int:
    memory_total = int(target_vram_total or 0) or int(device_local_heap_bytes or 0)
    if memory_total >= 48 * 1024 ** 3:
        return 1536 * 1024 * 1024
    if memory_total >= 24 * 1024 ** 3:
        return 1024 * 1024 * 1024
    if memory_total >= 12 * 1024 ** 3:
        return 768 * 1024 * 1024
    if memory_total >= 4 * 1024 ** 3:
        return 512 * 1024 * 1024
    if memory_total >= 1024 ** 3:
        return 256 * 1024 * 1024
    return 128 * 1024 * 1024


def choose_compute_queue_family(vk: ctypes.CDLL, physical_device: ctypes.c_void_p) -> int:
    count = ctypes.c_uint32()
    vk.vkGetPhysicalDeviceQueueFamilyProperties(physical_device, ctypes.byref(count), None)
    if count.value <= 0:
        raise RuntimeError("selected Vulkan device has no queue families")
    from vulkan_transfer_worker import VkQueueFamilyProperties

    props = (VkQueueFamilyProperties * count.value)()
    vk.vkGetPhysicalDeviceQueueFamilyProperties(physical_device, ctypes.byref(count), props)
    best_index = -1
    best_score = -1
    for index in range(count.value):
        if props[index].queueCount <= 0:
            continue
        flags = int(props[index].queueFlags)
        if not (flags & VK_QUEUE_COMPUTE_BIT):
            continue
        score = 100
        if not (flags & 0x00000001):
            score += 20
        if score > best_score:
            best_score = score
            best_index = index
    if best_index < 0:
        raise RuntimeError("selected Vulkan device has no compute-capable queue")
    return best_index


def extend_vulkan_prototypes(vk: ctypes.CDLL) -> None:
    vk.vkCreateShaderModule.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkShaderModuleCreateInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    vk.vkCreateShaderModule.restype = ctypes.c_int32
    vk.vkDestroyShaderModule.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    vk.vkDestroyShaderModule.restype = None
    vk.vkCreateDescriptorSetLayout.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkDescriptorSetLayoutCreateInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    vk.vkCreateDescriptorSetLayout.restype = ctypes.c_int32
    vk.vkDestroyDescriptorSetLayout.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    vk.vkDestroyDescriptorSetLayout.restype = None
    vk.vkCreatePipelineLayout.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkPipelineLayoutCreateInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    vk.vkCreatePipelineLayout.restype = ctypes.c_int32
    vk.vkDestroyPipelineLayout.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    vk.vkDestroyPipelineLayout.restype = None
    vk.vkCreateComputePipelines.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(VkComputePipelineCreateInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    vk.vkCreateComputePipelines.restype = ctypes.c_int32
    vk.vkDestroyPipeline.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    vk.vkDestroyPipeline.restype = None
    vk.vkCreateDescriptorPool.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkDescriptorPoolCreateInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    vk.vkCreateDescriptorPool.restype = ctypes.c_int32
    vk.vkDestroyDescriptorPool.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    vk.vkDestroyDescriptorPool.restype = None
    vk.vkAllocateDescriptorSets.argtypes = [ctypes.c_void_p, ctypes.POINTER(VkDescriptorSetAllocateInfo), ctypes.POINTER(ctypes.c_void_p)]
    vk.vkAllocateDescriptorSets.restype = ctypes.c_int32
    vk.vkUpdateDescriptorSets.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(VkWriteDescriptorSet), ctypes.c_uint32, ctypes.c_void_p]
    vk.vkUpdateDescriptorSets.restype = None
    vk.vkCmdBindPipeline.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
    vk.vkCmdBindPipeline.restype = None
    vk.vkCmdBindDescriptorSets.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint32, ctypes.c_void_p]
    vk.vkCmdBindDescriptorSets.restype = None
    vk.vkCmdDispatch.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
    vk.vkCmdDispatch.restype = None
    vk.vkCmdFillBuffer.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint32]
    vk.vkCmdFillBuffer.restype = None
    vk.vkCmdCopyBuffer.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(VkBufferCopy)]
    vk.vkCmdCopyBuffer.restype = None


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
    parser.add_argument("--buffer-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--ramp-step-seconds", type=float, default=15.0)
    parser.add_argument("--start-load-fraction", type=float, default=0.35)
    parser.add_argument("--result-file", default="")
    parser.add_argument("--device-class", default="")
    parser.add_argument("--profile-mode", default="steady")
    parser.add_argument("--profile-intensity", default="extreme")
    parser.add_argument("--tuning-step", type=int, default=0)
    parser.add_argument("--compute-rounds", type=int, default=16)
    parser.add_argument("--kernel-variant", default="hash")
    parser.add_argument("--dispatch-repeats", type=int, default=0)
    args = parser.parse_args()
    resolved_kernel_variant = normalize_kernel_variant(args.kernel_variant)
    resolved_dispatch_repeats = resolve_dispatch_repeats(resolved_kernel_variant, args.dispatch_repeats)
    resolved_compute_rounds = max(1, min(kernel_round_limit(resolved_kernel_variant), int(args.compute_rounds)))

    state = {
        "kind": "gpu",
        "mode": "gpu_3d",
        "backend": "python_vulkan_compute",
        "worker_version": "vulkan_compute_stateful_memory_v19"
        if resolved_kernel_variant == "stateful_memory"
        else (
            "vulkan_compute_stress_hash_v7"
            if resolved_kernel_variant == "stress_hash"
            else "vulkan_compute_hash_v7"
        ),
        "kernel_variant": resolved_kernel_variant,
        "backend_api_family": "Vulkan",
        "suite_scaling_mode": "parametric",
        "suite_verification": "compute_readback",
        "diagnostic_backend": False,
        "saturation_result": True,
        "power_saturation_expected": True,
        "status": "ok",
        "error_count": 0,
        "verification_passes": 0,
        "compute_mismatch_count": 0,
        "frames": 0,
        "buffer_bytes": 0,
        "requested_buffer_bytes": 0,
        "target_buffer_bytes": 0,
        "worker_total_cap_bytes": 0,
        "buffer_count": 0,
        "buffer_count_limit": 32,
        "per_buffer_cap_bytes": 0,
        "buffer_size_min_bytes": 0,
        "buffer_size_max_bytes": 0,
        "buffer_size_avg_bytes": 0,
        "buffer_allocation_bytes": 0,
        "allocation_shortfall_bytes": 0,
        "allocation_strategy": "",
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
        "active_work_items": 0,
        "active_compute_rounds": 0,
        "active_dispatch_repeats": 0,
        "active_load_fraction": 0.0,
        "dispatch_repeats": resolved_dispatch_repeats,
        "verified_buffer_count": 0,
        "verified_buffer_indexes": [],
        "verified_buffer_coverage_percent": 0.0,
        "buffer_dispatch_min": 0,
        "buffer_dispatch_max": 0,
        "buffer_dispatch_avg": 0.0,
        "compute_rounds": resolved_compute_rounds,
        "effective_compute_rounds": resolved_compute_rounds * resolved_dispatch_repeats,
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

    handles = {}
    vk = None
    try:
        library = resolve_vulkan_library()
        if not library:
            raise RuntimeError("Vulkan loader library not found")
        vk = load_vulkan(library)
        extend_vulkan_prototypes(vk)
        instance = make_instance(vk)
        handles["instance"] = instance
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
        queue_family = choose_compute_queue_family(vk, physical_device)
        state["queue_family_index"] = queue_family
        priority = ctypes.c_float(1.0)
        queue_info = VkDeviceQueueCreateInfo(VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, VK_NULL_HANDLE, 0, queue_family, 1, ctypes.pointer(priority))
        device_info = VkDeviceCreateInfo(VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, VK_NULL_HANDLE, 0, 1, ctypes.pointer(queue_info), 0, VK_NULL_HANDLE, 0, VK_NULL_HANDLE, VK_NULL_HANDLE)
        device = ctypes.c_void_p()
        check(vk.vkCreateDevice(physical_device, ctypes.byref(device_info), None, ctypes.byref(device)), "vkCreateDevice")
        handles["device"] = device
        queue = ctypes.c_void_p()
        vk.vkGetDeviceQueue(device, queue_family, 0, ctypes.byref(queue))

        from vulkan_transfer_worker import VkPhysicalDeviceMemoryProperties

        memory_props = VkPhysicalDeviceMemoryProperties()
        vk.vkGetPhysicalDeviceMemoryProperties(physical_device, ctypes.byref(memory_props))
        device_local_heap_bytes = 0
        for heap_index in range(int(memory_props.memoryHeapCount)):
            heap = memory_props.memoryHeaps[heap_index]
            if int(heap.flags) & 0x1:
                device_local_heap_bytes += int(heap.size)
        state["device_local_heap_bytes"] = int(device_local_heap_bytes)
        state["device_local_heap_gb"] = round(device_local_heap_bytes / (1024 ** 3), 3) if device_local_heap_bytes else 0.0
        kernel_variant = resolved_kernel_variant
        if kernel_variant == "stateful_memory":
            per_buffer_cap_bytes = stateful_memory_buffer_cap(args.target_vram_total, device_local_heap_bytes, args.device_class)
            total_cap_bytes = stateful_memory_total_cap(args.target_vram_total, device_local_heap_bytes, args.device_class)
        elif kernel_variant == "stress_hash":
            per_buffer_cap_bytes = stress_hash_buffer_cap(args.target_vram_total, device_local_heap_bytes, args.device_class)
            total_cap_bytes = per_buffer_cap_bytes
        else:
            per_buffer_cap_bytes = 256 * 1024 * 1024
            total_cap_bytes = per_buffer_cap_bytes
        requested_total_size = max(8 * 1024 * 1024, min(total_cap_bytes, int(args.buffer_bytes)))
        requested_total_size -= requested_total_size % 1024
        state["requested_buffer_bytes"] = int(args.buffer_bytes)
        state["worker_total_cap_bytes"] = int(total_cap_bytes)
        state["per_buffer_cap_bytes"] = int(per_buffer_cap_bytes)
        state["buffer_count_limit"] = 32
        state["allocation_strategy"] = (
            "stateful_memory_multi_buffer_device_local"
            if kernel_variant == "stateful_memory"
            else (
                "stress_hash_device_local_single_window"
                if kernel_variant == "stress_hash"
                else "hash_device_local_single_window"
            )
        )
        if device_local_heap_bytes:
            state["requested_device_local_heap_percent"] = round(
                (int(args.buffer_bytes) / float(device_local_heap_bytes)) * 100.0,
                4,
            )
            state["target_device_local_heap_percent"] = round(
                (int(requested_total_size) / float(device_local_heap_bytes)) * 100.0,
                4,
            )
        buffer_records = []
        staging_buffer = ctypes.c_void_p()
        staging_memory = ctypes.c_void_p()
        remaining_size = requested_total_size
        while remaining_size >= 8 * 1024 * 1024 and len(buffer_records) < 32:
            request_size = min(per_buffer_cap_bytes, remaining_size)
            request_size -= request_size % 1024
            allocated = False
            while request_size >= 8 * 1024 * 1024:
                buffer_handle = ctypes.c_void_p()
                buffer_memory = ctypes.c_void_p()
                try:
                    buffer_handle, buffer_memory, buffer_allocation_bytes, buffer_memory_type = create_buffer(
                        vk,
                        device,
                        memory_props,
                        request_size,
                        VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT,
                        0,
                        VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,
                    )
                    buffer_records.append(
                        {
                            "buffer": buffer_handle,
                            "memory": buffer_memory,
                            "size": int(request_size),
                            "allocation_bytes": int(buffer_allocation_bytes),
                            "memory_type": int(buffer_memory_type),
                        }
                    )
                    remaining_size -= request_size
                    allocated = True
                    break
                except Exception:
                    for handle in (buffer_handle,):
                        if handle:
                            try:
                                vk.vkDestroyBuffer(device, handle, None)
                            except Exception:
                                pass
                    for memory in (buffer_memory,):
                        if memory:
                            try:
                                vk.vkFreeMemory(device, memory, None)
                            except Exception:
                                pass
                    request_size //= 2
                    request_size -= request_size % 1024
            if not allocated:
                break
        if not buffer_records:
            raise RuntimeError("unable to allocate Vulkan compute buffers")
        first_record = buffer_records[0]
        requested_size = int(first_record["size"])
        buffer_handle = first_record["buffer"]
        handles["buffers"] = [record["buffer"] for record in buffer_records]
        handles["memories"] = [record["memory"] for record in buffer_records]
        staging_buffer, staging_memory, _, staging_memory_type = create_buffer(
            vk,
            device,
            memory_props,
            4096,
            VK_BUFFER_USAGE_TRANSFER_DST_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
        )
        handles["staging_buffer"] = staging_buffer
        handles["staging_memory"] = staging_memory
        total_buffer_bytes = sum(int(record["size"]) for record in buffer_records)
        total_allocation_bytes = sum(int(record["allocation_bytes"]) for record in buffer_records)
        buffer_sizes = [int(record["size"]) for record in buffer_records]
        state["target_buffer_bytes"] = int(requested_total_size)
        state["buffer_bytes"] = int(total_buffer_bytes)
        state["buffer_count"] = len(buffer_records)
        state["buffer_size_min_bytes"] = int(min(buffer_sizes)) if buffer_sizes else 0
        state["buffer_size_max_bytes"] = int(max(buffer_sizes)) if buffer_sizes else 0
        state["buffer_size_avg_bytes"] = int(sum(buffer_sizes) / len(buffer_sizes)) if buffer_sizes else 0
        state["buffer_allocation_bytes"] = int(total_allocation_bytes)
        state["allocation_shortfall_bytes"] = max(0, int(requested_total_size) - int(total_buffer_bytes))
        state["buffer_memory_type_index"] = int(first_record["memory_type"])
        state["staging_memory_type_index"] = int(staging_memory_type)
        if 0 <= int(first_record["memory_type"]) < int(memory_props.memoryTypeCount):
            memory_type = memory_props.memoryTypes[int(first_record["memory_type"])]
            state["buffer_memory_type_flags"] = int(memory_type.propertyFlags)
            state["buffer_memory_heap_index"] = int(memory_type.heapIndex)
        if device_local_heap_bytes:
            state["buffer_device_local_heap_percent"] = round((int(total_allocation_bytes) / float(device_local_heap_bytes)) * 100.0, 4)

        compute_rounds = resolved_compute_rounds
        dispatch_repeats = resolved_dispatch_repeats
        state["dispatch_repeats"] = dispatch_repeats
        state["effective_compute_rounds"] = compute_rounds * dispatch_repeats
        spirv = compute_shader_spirv(compute_rounds, kernel_variant)
        spirv_words = (ctypes.c_uint32 * (len(spirv) // 4)).from_buffer_copy(spirv)
        shader_info = VkShaderModuleCreateInfo(VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, VK_NULL_HANDLE, 0, len(spirv), ctypes.cast(spirv_words, ctypes.POINTER(ctypes.c_uint32)))
        shader = ctypes.c_void_p()
        check(vk.vkCreateShaderModule(device, ctypes.byref(shader_info), None, ctypes.byref(shader)), "vkCreateShaderModule")
        handles["shader"] = shader

        binding = VkDescriptorSetLayoutBinding(0, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, VK_NULL_HANDLE)
        layout_info = VkDescriptorSetLayoutCreateInfo(VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, VK_NULL_HANDLE, 0, 1, ctypes.pointer(binding))
        set_layout = ctypes.c_void_p()
        check(vk.vkCreateDescriptorSetLayout(device, ctypes.byref(layout_info), None, ctypes.byref(set_layout)), "vkCreateDescriptorSetLayout")
        handles["set_layout"] = set_layout
        set_layouts = (ctypes.c_void_p * 1)(set_layout)
        pipeline_layout_info = VkPipelineLayoutCreateInfo(VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, VK_NULL_HANDLE, 0, 1, set_layouts, 0, VK_NULL_HANDLE)
        pipeline_layout = ctypes.c_void_p()
        check(vk.vkCreatePipelineLayout(device, ctypes.byref(pipeline_layout_info), None, ctypes.byref(pipeline_layout)), "vkCreatePipelineLayout")
        handles["pipeline_layout"] = pipeline_layout
        stage_name = ctypes.c_char_p(b"main")
        stage = VkPipelineShaderStageCreateInfo(VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, VK_NULL_HANDLE, 0, VK_SHADER_STAGE_COMPUTE_BIT, shader, stage_name, VK_NULL_HANDLE)
        pipeline_info = VkComputePipelineCreateInfo(VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, VK_NULL_HANDLE, 0, stage, pipeline_layout, VK_NULL_HANDLE, -1)
        pipeline = ctypes.c_void_p()
        check(vk.vkCreateComputePipelines(device, VK_NULL_HANDLE, 1, ctypes.byref(pipeline_info), None, ctypes.byref(pipeline)), "vkCreateComputePipelines")
        handles["pipeline"] = pipeline

        descriptor_count = max(1, len(buffer_records))
        pool_size = VkDescriptorPoolSize(VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, descriptor_count)
        pool_info = VkDescriptorPoolCreateInfo(VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, VK_NULL_HANDLE, 0, descriptor_count, 1, ctypes.pointer(pool_size))
        descriptor_pool = ctypes.c_void_p()
        check(vk.vkCreateDescriptorPool(device, ctypes.byref(pool_info), None, ctypes.byref(descriptor_pool)), "vkCreateDescriptorPool")
        handles["descriptor_pool"] = descriptor_pool
        set_layouts_alloc = (ctypes.c_void_p * descriptor_count)(*([set_layout] * descriptor_count))
        alloc_info = VkDescriptorSetAllocateInfo(VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, VK_NULL_HANDLE, descriptor_pool, descriptor_count, set_layouts_alloc)
        descriptor_sets_array = (ctypes.c_void_p * descriptor_count)()
        check(vk.vkAllocateDescriptorSets(device, ctypes.byref(alloc_info), descriptor_sets_array), "vkAllocateDescriptorSets")
        descriptor_sets_by_buffer = []
        for record_index, record in enumerate(buffer_records):
            descriptor_set = descriptor_sets_array[record_index]
            descriptor_sets_by_buffer.append((ctypes.c_void_p * 1)(descriptor_set))
            buffer_info = VkDescriptorBufferInfo(record["buffer"], 0, int(record["size"]))
            write = VkWriteDescriptorSet(VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, VK_NULL_HANDLE, descriptor_set, 0, 0, 1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_NULL_HANDLE, ctypes.pointer(buffer_info), VK_NULL_HANDLE)
            vk.vkUpdateDescriptorSets(device, 1, ctypes.byref(write), 0, VK_NULL_HANDLE)

        pool_create = VkCommandPoolCreateInfo(VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, VK_NULL_HANDLE, VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT, queue_family)
        command_pool = ctypes.c_void_p()
        check(vk.vkCreateCommandPool(device, ctypes.byref(pool_create), None, ctypes.byref(command_pool)), "vkCreateCommandPool")
        handles["command_pool"] = command_pool
        cmd_alloc = VkCommandBufferAllocateInfo(VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, VK_NULL_HANDLE, command_pool, VK_COMMAND_BUFFER_LEVEL_PRIMARY, 1)
        command_buffer = ctypes.c_void_p()
        check(vk.vkAllocateCommandBuffers(device, ctypes.byref(cmd_alloc), ctypes.byref(command_buffer)), "vkAllocateCommandBuffers")
        fence_info = VkFenceCreateInfo(VK_STRUCTURE_TYPE_FENCE_CREATE_INFO, VK_NULL_HANDLE, 0)
        fence = ctypes.c_void_p()
        check(vk.vkCreateFence(device, ctypes.byref(fence_info), None, ctypes.byref(fence)), "vkCreateFence")
        handles["fence"] = fence
        fence_array = (ctypes.c_void_p * 1)(fence)
        command_array = (ctypes.c_void_p * 1)(command_buffer)
        if kernel_variant == "stateful_memory":
            for record_index, record in enumerate(buffer_records):
                check(vk.vkResetFences(device, 1, fence_array), f"vkResetFences(init {record_index})")
                check(vk.vkResetCommandBuffer(command_buffer, 0), f"vkResetCommandBuffer(init {record_index})")
                begin = VkCommandBufferBeginInfo(VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, VK_NULL_HANDLE, VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT, VK_NULL_HANDLE)
                check(vk.vkBeginCommandBuffer(command_buffer, ctypes.byref(begin)), f"vkBeginCommandBuffer(init {record_index})")
                vk.vkCmdFillBuffer(command_buffer, record["buffer"], 0, int(record["size"]), 0)
                init_barrier = VkBufferMemoryBarrier(
                    VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER,
                    VK_NULL_HANDLE,
                    VK_ACCESS_TRANSFER_WRITE_BIT,
                    VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT,
                    VK_QUEUE_FAMILY_IGNORED,
                    VK_QUEUE_FAMILY_IGNORED,
                    record["buffer"],
                    0,
                    int(record["size"]),
                )
                vk.vkCmdPipelineBarrier(command_buffer, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_DEPENDENCY_BY_REGION_BIT, 0, VK_NULL_HANDLE, 1, ctypes.byref(init_barrier), 0, VK_NULL_HANDLE)
                check(vk.vkEndCommandBuffer(command_buffer), f"vkEndCommandBuffer(init {record_index})")
                submit = VkSubmitInfo(4, VK_NULL_HANDLE, 0, VK_NULL_HANDLE, VK_NULL_HANDLE, 1, command_array, 0, VK_NULL_HANDLE)
                check(vk.vkQueueSubmit(queue, 1, ctypes.byref(submit), fence), f"vkQueueSubmit(init {record_index})")
                check(vk.vkWaitForFences(device, 1, fence_array, VK_TRUE, 10_000_000_000), f"vkWaitForFences(init {record_index})")

        started = time.monotonic()
        sample_words = 256
        expected_samples = [[0 for _ in range(sample_words)] for _ in buffer_records]
        expected_sample_dispatches = [0 for _ in buffer_records]
        buffer_dispatch_counts = [0 for _ in buffer_records]
        verified_buffer_indexes: set[int] = set()
        verification_cursor = 0
        total_estimated_memory_bytes = 0
        while running:
            elapsed = time.monotonic() - started
            if args.ramp_step_seconds > 0:
                progress = min(1.0, elapsed / max(0.001, args.ramp_step_seconds * 3.0))
                load_fraction = min(1.0, max(0.15, args.start_load_fraction) + (1.0 - max(0.15, args.start_load_fraction)) * progress)
            else:
                load_fraction = 1.0
            active_infos = []
            for record in buffer_records:
                active_buffer_size = int(record["size"])
                active_size = max(1024 * 1024, int(active_buffer_size * load_fraction))
                active_size -= active_size % 1024
                active_words = max(256, active_size // 4)
                groups = max(1, int(math.ceil(active_words / 256.0)))
                active_words = groups * 256
                active_size = min(active_buffer_size, active_words * 4)
                active_infos.append((record, active_size, active_words, groups))
            active_total_size = sum(item[1] for item in active_infos)
            active_total_words = sum(item[2] for item in active_infos)
            max_dispatch_size = max((item[1] for item in active_infos), default=0)
            verify_buffer_index = -1
            if state["frames"] % 3 == 0 and buffer_records:
                verify_buffer_index = verification_cursor % len(buffer_records)
                verification_cursor += 1
            cycle_memory_bytes = 0

            check(vk.vkResetFences(device, 1, fence_array), "vkResetFences(cycle)")
            check(vk.vkResetCommandBuffer(command_buffer, 0), "vkResetCommandBuffer(cycle)")
            begin = VkCommandBufferBeginInfo(VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, VK_NULL_HANDLE, VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT, VK_NULL_HANDLE)
            check(vk.vkBeginCommandBuffer(command_buffer, ctypes.byref(begin)), "vkBeginCommandBuffer(cycle)")
            vk.vkCmdBindPipeline(command_buffer, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline)
            for active_buffer_index, (active_record, active_size, active_words, groups) in enumerate(active_infos):
                active_buffer_handle = active_record["buffer"]
                should_verify = active_buffer_index == verify_buffer_index
                sample_bytes = min(active_size, sample_words * 4)
                vk.vkCmdBindDescriptorSets(command_buffer, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline_layout, 0, 1, descriptor_sets_by_buffer[active_buffer_index], 0, VK_NULL_HANDLE)
                for dispatch_index in range(dispatch_repeats):
                    vk.vkCmdDispatch(command_buffer, groups, 1, 1)
                    if dispatch_index < dispatch_repeats - 1:
                        repeat_barrier = VkBufferMemoryBarrier(
                            VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER,
                            VK_NULL_HANDLE,
                            VK_ACCESS_SHADER_WRITE_BIT,
                            VK_ACCESS_SHADER_WRITE_BIT,
                            VK_QUEUE_FAMILY_IGNORED,
                            VK_QUEUE_FAMILY_IGNORED,
                            active_buffer_handle,
                            0,
                            active_size,
                        )
                        vk.vkCmdPipelineBarrier(command_buffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_DEPENDENCY_BY_REGION_BIT, 0, VK_NULL_HANDLE, 1, ctypes.byref(repeat_barrier), 0, VK_NULL_HANDLE)
                if should_verify:
                    compute_to_copy_barrier = VkBufferMemoryBarrier(
                        VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER,
                        VK_NULL_HANDLE,
                        VK_ACCESS_SHADER_WRITE_BIT,
                        VK_ACCESS_TRANSFER_READ_BIT,
                        VK_QUEUE_FAMILY_IGNORED,
                        VK_QUEUE_FAMILY_IGNORED,
                        active_buffer_handle,
                        0,
                        sample_bytes,
                    )
                    vk.vkCmdPipelineBarrier(command_buffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_DEPENDENCY_BY_REGION_BIT, 0, VK_NULL_HANDLE, 1, ctypes.byref(compute_to_copy_barrier), 0, VK_NULL_HANDLE)
                    region = VkBufferCopy(0, 0, sample_bytes)
                    vk.vkCmdCopyBuffer(command_buffer, active_buffer_handle, staging_buffer, 1, ctypes.byref(region))
                    copy_to_host_barrier = VkBufferMemoryBarrier(
                        VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER,
                        VK_NULL_HANDLE,
                        VK_ACCESS_TRANSFER_WRITE_BIT,
                        VK_ACCESS_HOST_READ_BIT,
                        VK_QUEUE_FAMILY_IGNORED,
                        VK_QUEUE_FAMILY_IGNORED,
                        staging_buffer,
                        0,
                        sample_bytes,
                    )
                    vk.vkCmdPipelineBarrier(command_buffer, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT, VK_DEPENDENCY_BY_REGION_BIT, 0, VK_NULL_HANDLE, 1, ctypes.byref(copy_to_host_barrier), 0, VK_NULL_HANDLE)
                else:
                    compute_to_compute_barrier = VkBufferMemoryBarrier(
                        VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER,
                        VK_NULL_HANDLE,
                        VK_ACCESS_SHADER_WRITE_BIT,
                        VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT,
                        VK_QUEUE_FAMILY_IGNORED,
                        VK_QUEUE_FAMILY_IGNORED,
                        active_buffer_handle,
                        0,
                        active_size,
                    )
                    vk.vkCmdPipelineBarrier(command_buffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_DEPENDENCY_BY_REGION_BIT, 0, VK_NULL_HANDLE, 1, ctypes.byref(compute_to_compute_barrier), 0, VK_NULL_HANDLE)
                cycle_memory_bytes += active_size * (2 if kernel_variant == "stateful_memory" else dispatch_repeats)

            check(vk.vkEndCommandBuffer(command_buffer), "vkEndCommandBuffer(cycle)")
            submit = VkSubmitInfo(4, VK_NULL_HANDLE, 0, VK_NULL_HANDLE, VK_NULL_HANDLE, 1, command_array, 0, VK_NULL_HANDLE)
            check(vk.vkQueueSubmit(queue, 1, ctypes.byref(submit), fence), "vkQueueSubmit(cycle)")
            check(vk.vkWaitForFences(device, 1, fence_array, VK_TRUE, 10_000_000_000), "vkWaitForFences(cycle)")

            for active_buffer_index, (_, active_size, _, _) in enumerate(active_infos):
                should_verify = active_buffer_index == verify_buffer_index
                sample_bytes = min(active_size, sample_words * 4)
                if should_verify:
                    if kernel_variant == "stateful_memory":
                        target_dispatches = buffer_dispatch_counts[active_buffer_index] + 1
                        while expected_sample_dispatches[active_buffer_index] < target_dispatches:
                            for word_index in range(sample_words):
                                expected_samples[active_buffer_index][word_index] = expected_word(
                                    word_index,
                                    compute_rounds,
                                    expected_samples[active_buffer_index][word_index],
                                    kernel_variant,
                                )
                            expected_sample_dispatches[active_buffer_index] += 1
                    mapped = ctypes.c_void_p()
                    check(vk.vkMapMemory(device, staging_memory, 0, sample_bytes, 0, ctypes.byref(mapped)), "vkMapMemory")
                    try:
                        raw = ctypes.string_at(mapped, sample_bytes)
                    finally:
                        vk.vkUnmapMemory(device, staging_memory)
                    for word_index in range(sample_bytes // 4):
                        actual = struct.unpack_from("<I", raw, word_index * 4)[0]
                        if kernel_variant == "stateful_memory":
                            expected = expected_samples[active_buffer_index][word_index]
                        else:
                            expected = expected_word(word_index, compute_rounds, 0, kernel_variant)
                        if actual != expected:
                            state["compute_mismatch_count"] += 1
                            record_error(f"Vulkan compute mismatch at buffer {active_buffer_index} word {word_index}: expected={expected} actual={actual}")
                            break
                    state["verification_passes"] += 1
                    verified_buffer_indexes.add(active_buffer_index)
                buffer_dispatch_counts[active_buffer_index] += dispatch_repeats

            state["active_load_fraction"] = round(load_fraction, 3)
            state["active_buffer_bytes"] = active_total_size
            state["active_dispatch_buffer_bytes"] = max_dispatch_size
            state["active_buffer_count"] = len(buffer_records)
            state["active_buffer_index"] = verify_buffer_index
            state["active_work_items"] = active_total_words
            state["active_compute_rounds"] = compute_rounds
            state["active_dispatch_repeats"] = dispatch_repeats
            state["effective_compute_rounds"] = compute_rounds * dispatch_repeats
            state["verified_buffer_indexes"] = sorted(verified_buffer_indexes)
            state["verified_buffer_count"] = len(verified_buffer_indexes)
            state["verified_buffer_coverage_percent"] = round(
                (len(verified_buffer_indexes) / float(len(buffer_records))) * 100.0,
                4,
            ) if buffer_records else 0.0
            state["buffer_dispatch_min"] = min(buffer_dispatch_counts) if buffer_dispatch_counts else 0
            state["buffer_dispatch_max"] = max(buffer_dispatch_counts) if buffer_dispatch_counts else 0
            state["buffer_dispatch_avg"] = round(
                sum(buffer_dispatch_counts) / float(len(buffer_dispatch_counts)),
                3,
            ) if buffer_dispatch_counts else 0.0
            state["frames"] += 1
            state["elapsed_seconds"] = round(max(0.0, time.monotonic() - started), 3)
            total_estimated_memory_bytes += cycle_memory_bytes
            state["estimated_device_memory_bytes"] = int(total_estimated_memory_bytes)
            state["estimated_device_memory_gb"] = round(state["estimated_device_memory_bytes"] / (1024 ** 3), 3)
            if state["elapsed_seconds"] > 0:
                state["estimated_device_memory_gbps"] = round(
                    state["estimated_device_memory_bytes"] / state["elapsed_seconds"] / (1024 ** 3),
                    3,
                )
                state["peak_estimated_device_memory_gbps"] = max(
                    float(state.get("peak_estimated_device_memory_gbps") or 0.0),
                    float(state["estimated_device_memory_gbps"]),
                )
            if state["frames"] % 10 == 0:
                write_result()
            time.sleep(0.0005)
        return 0
    except Exception as exc:
        record_error(exc)
        return 12
    finally:
        try:
            if vk and handles.get("device"):
                vk.vkDeviceWaitIdle(handles["device"])
        except Exception:
            pass
        if vk and handles.get("device"):
            device = handles["device"]
            destroy_pairs = [
                ("fence", "vkDestroyFence"),
                ("command_pool", "vkDestroyCommandPool"),
                ("descriptor_pool", "vkDestroyDescriptorPool"),
                ("pipeline", "vkDestroyPipeline"),
                ("pipeline_layout", "vkDestroyPipelineLayout"),
                ("set_layout", "vkDestroyDescriptorSetLayout"),
                ("shader", "vkDestroyShaderModule"),
                ("staging_buffer", "vkDestroyBuffer"),
            ]
            for key, fn_name in destroy_pairs:
                handle = handles.get(key)
                if handle:
                    try:
                        getattr(vk, fn_name)(device, handle, None)
                    except Exception:
                        pass
            for handle in handles.get("buffers", []):
                if handle:
                    try:
                        vk.vkDestroyBuffer(device, handle, None)
                    except Exception:
                        pass
            for key in ("staging_memory",):
                if handles.get(key):
                    try:
                        vk.vkFreeMemory(device, handles[key], None)
                    except Exception:
                        pass
            for memory in handles.get("memories", []):
                if memory:
                    try:
                        vk.vkFreeMemory(device, memory, None)
                    except Exception:
                        pass
            try:
                vk.vkDestroyDevice(device, None)
            except Exception:
                pass
        if vk and handles.get("instance"):
            try:
                vk.vkDestroyInstance(handles["instance"], None)
            except Exception:
                pass
        write_result()


if __name__ == "__main__":
    raise SystemExit(main())
