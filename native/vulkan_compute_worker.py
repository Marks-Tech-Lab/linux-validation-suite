#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import ctypes
from contextlib import contextmanager
import faulthandler
import json
import math
import os
import signal
import struct
import sys
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from Modules.lvs_runtime_memory_guard import claim_runtime_allocation_growth, release_runtime_allocation_claim
from Modules.lvs_vulkan_memory_policy import (
    stateful_memory_buffer_cap,
    stateful_memory_buffer_count_limit,
    stateful_memory_total_cap,
)

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
    select_physical_device,
    native_identity_evidence,
    PhysicalIdentitySelectionError,
    vulkan_failure_reason,
)

VK_ACCESS_SHADER_READ_BIT = 0x00000020


class SlowOperationRecorder:
    """Bounded host timings, not GPU execution or proof of a scheduler stall.

    No event-time I/O. Ordinary results carry completed observations; one
    terminal log record also retains timings of the last result write itself.
    """

    OPERATIONS = frozenset({
        "result_persistence", "result_open", "result_serialization_and_write",
        "result_flush", "result_fsync", "result_close", "result_replace",
        "command_record", "queue_submit", "fence_wait", "gpu_timestamp_retrieval",
        "verification_readback", "loop_prepare", "loop_state_updates",
        "sleep_yield", "device_wait_idle", "unaccounted_loop_gap",
    })

    def __init__(self, state, *, clock=time.monotonic, wall_clock=time.time,
                 cpu_clock=time.process_time, threshold_seconds=1.0, capacity=64):
        if threshold_seconds <= 0 or capacity <= 0:
            raise ValueError("slow-operation diagnostic bounds must be positive")
        self.state = state
        self.clock, self.wall_clock, self.cpu_clock = clock, wall_clock, cpu_clock
        self.origin = clock()
        self.wall_origin = wall_clock()
        self.pending = []
        self.last_finish = self.origin
        self.track_gaps = False
        self.evidence = state["slow_operation_evidence"] = {
            "contract_id": "linux_validation_suite.gpu_worker_slow_operations",
            "contract_version": 1,
            "kind": "gpu_worker_slow_operations",
            "status": "enabled",
            "semantics": "host_elapsed_including_io_and_descheduling_not_gpu_execution_time",
            "gap_semantics": "unscoped_host_interval_cause_unknown_not_proof_of_scheduler_interruption",
            "wall_time_basis": "initial_unix_monotonic_correlation_plus_observed_event_end",
            "clock_origin_monotonic_seconds": self.origin,
            "clock_origin_unix_seconds": self.wall_origin,
            "threshold_seconds": float(threshold_seconds),
            "threshold_role": "diagnostic_only_not_a_performance_requirement",
            "record_capacity": int(capacity),
            "event_count": 0, "overwritten_record_count": 0,
            "records": [], "operation_summary": {}, "slowest_by_operation": {},
        }

    def _record(self, operation, start, end, cpu_elapsed, outcome):
        elapsed = max(0.0, end - start)
        summary = self.evidence["operation_summary"].setdefault(operation, {
            "count": 0, "total_elapsed_seconds": 0.0, "max_elapsed_seconds": 0.0,
            "slow_count": 0, "exception_count": 0,
        })
        summary["count"] += 1
        summary["total_elapsed_seconds"] += elapsed
        summary["max_elapsed_seconds"] = max(summary["max_elapsed_seconds"], elapsed)
        summary["exception_count"] += outcome != "completed"
        if elapsed < self.evidence["threshold_seconds"] and outcome == "completed":
            return
        summary["slow_count"] += elapsed >= self.evidence["threshold_seconds"]
        self.evidence["event_count"] += 1
        record = {
            "sequence": self.evidence["event_count"], "operation": operation,
            "started_monotonic_seconds": start, "ended_monotonic_seconds": end,
            "started_unix_seconds": self.wall_origin + start - self.origin,
            "ended_unix_seconds": self.wall_origin + end - self.origin,
            "observed_end_unix_seconds": self.wall_clock(),
            "elapsed_seconds": elapsed, "process_cpu_seconds": cpu_elapsed,
            "outcome": outcome, "worker_pid": os.getpid(),
            "physical_gpu_id": self.state.get("physical_gpu_id", ""),
            "target_id": self.state.get("target_id", ""),
            "worker_result_file": self.state.get("worker_result_file", ""),
            "telemetry_gpu_index": self.state.get("telemetry_gpu_index"),
            "vulkan_device_index": self.state.get("vulkan_device_index"),
            "kernel_variant": self.state.get("kernel_variant", ""),
            "cycle_count": self.state.get("cycle_count", 0),
            "queue_submission_count": self.state.get("queue_submission_count", 0),
            "verification_passes": self.state.get("verification_passes", 0),
            "submission_batch_iterations": self.state.get("submission_batch_iterations", 1),
        }
        records = self.evidence["records"]
        records.append(record)
        if len(records) > self.evidence["record_capacity"]:
            records.pop(0)
            self.evidence["overwritten_record_count"] += 1
        previous = self.evidence["slowest_by_operation"].get(operation)
        if previous is None or elapsed > previous["elapsed_seconds"]:
            self.evidence["slowest_by_operation"][operation] = record

    def begin(self, operation):
        if operation not in self.OPERATIONS:
            raise ValueError("unknown bounded slow-operation name")
        now = self.clock()
        if self.track_gaps and not self.pending and now - self.last_finish >= self.evidence["threshold_seconds"]:
            self._record("unaccounted_loop_gap", self.last_finish, now, None, "completed")
        token = (operation, now, self.cpu_clock())
        self.pending.append(token)
        return token

    def finish(self, token, outcome="completed"):
        end = self.clock()
        self.pending.remove(token)
        self._record(token[0], token[1], end, max(0.0, self.cpu_clock() - token[2]), outcome)
        if not self.pending:
            # Include time spent in diagnostic bookkeeping in the next
            # unscoped interval; do not hide a deschedule inside the recorder.
            self.last_finish = end

    @contextmanager
    def measure(self, operation):
        token = self.begin(operation)
        try:
            yield
        except BaseException as exc:
            self.finish(token, f"exception:{type(exc).__name__}")
            raise
        else:
            self.finish(token)

    def call(self, operation, function, *args):
        with self.measure(operation):
            return function(*args)

    def fail_pending(self):
        for token in list(reversed(self.pending)):
            self.finish(token, "exception")

    def emit_terminal(self, stream):
        # One bounded record after cleanup, never one log/write per event.
        # This includes the final result write, which cannot describe its own
        # completed duration in the JSON it was still writing.
        stream.write(json.dumps({"event": "gpu_worker_slow_operation_diagnostics",
                                 "evidence": self.evidence,
                                 "result_write_error_count": self.state.get("result_write_error_count", 0),
                                 "last_result_write_error": self.state.get("last_result_write_error")}) + "\n")
        stream.flush()


def persist_worker_result(path, state, recorder, *, force=False):
    """Keep the existing atomic replacement and forced durability policy."""
    with recorder.measure("result_persistence"):
        handle = recorder.call("result_open", open, path + ".tmp", "w", -1, "utf-8")
        try:
            with recorder.measure("result_serialization_and_write"):
                json.dump(state, handle, indent=2)
            recorder.call("result_flush", handle.flush)
            if force:
                recorder.call("result_fsync", os.fsync, handle.fileno())
        finally:
            recorder.call("result_close", handle.close)
        recorder.call("result_replace", os.replace, path + ".tmp", path)


def register_worker_exit_diagnostics(recorder, write_result, *, register=atexit.register, stream=None):
    def emit():
        try:
            recorder.emit_terminal(sys.stderr if stream is None else stream)
        except Exception:
            pass
    # atexit runs in reverse registration order. Include even the existing
    # fallback result write in the single final diagnostic log snapshot.
    register(emit)
    register(lambda: write_result("atexit"))


VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO = 11
VK_QUERY_TYPE_TIMESTAMP = 2
VK_QUERY_RESULT_64_BIT = 0x00000001
VK_QUERY_RESULT_WAIT_BIT = 0x00000002


class VkQueryPoolCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("queryType", ctypes.c_uint32),
        ("queryCount", ctypes.c_uint32),
        ("pipelineStatistics", ctypes.c_uint32),
    ]


def _words_for_string(value: str) -> list[int]:
    raw = value.encode("utf-8") + b"\0"
    while len(raw) % 4:
        raw += b"\0"
    return [int.from_bytes(raw[index : index + 4], "little") for index in range(0, len(raw), 4)]


def _inst(opcode: int, operands: list[int]) -> list[int]:
    return [((1 + len(operands)) << 16) | opcode, *operands]


def validate_generated_compute_spirv_structure(words: list[int]) -> None:
    """Fail closed on generator ordering errors before a driver sees SPIR-V.

    This is deliberately a narrow invariant check for the module emitted in
    this file, not a replacement for a complete SPIR-V validator.  Types,
    constants, and module-scope variables emitted by this generator must all
    precede OpFunction.
    """
    if len(words) < 5 or int(words[0]) != 0x07230203:
        raise RuntimeError("generated compute SPIR-V has an invalid header")
    module_only_opcodes = {19, 21, 23, 29, 30, 32, 33, 43, 59}
    offset = 5
    function_seen = False
    function_end_seen = False
    while offset < len(words):
        instruction = int(words[offset])
        word_count = instruction >> 16
        opcode = instruction & 0xFFFF
        if word_count <= 0 or offset + word_count > len(words):
            raise RuntimeError(
                f"generated compute SPIR-V has an invalid instruction at word {offset}"
            )
        if opcode == 54:  # OpFunction
            function_seen = True
        elif function_seen and opcode in module_only_opcodes:
            raise RuntimeError(
                "generated compute SPIR-V emits a module-scope declaration "
                f"after OpFunction (opcode={opcode}, word={offset})"
            )
        elif opcode == 56:  # OpFunctionEnd
            function_end_seen = True
        offset += word_count
    if not function_seen or not function_end_seen or offset != len(words):
        raise RuntimeError("generated compute SPIR-V has an incomplete function body")


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


def select_compute_local_size(
    max_work_group_invocations: int,
    max_work_group_size: list[int] | tuple[int, ...],
) -> int:
    size_x = int(max_work_group_size[0]) if max_work_group_size else 0
    legal_maximum = min(
        value for value in (int(max_work_group_invocations or 0), size_x) if value > 0
    ) if any(value > 0 for value in (int(max_work_group_invocations or 0), size_x)) else 128
    for candidate in (256, 128, 64, 32, 16, 8, 4, 2, 1):
        if candidate <= legal_maximum:
            return candidate
    return 1


def compute_dispatch_dimensions(
    work_items: int,
    local_size_x: int,
    max_group_counts: list[int] | tuple[int, ...],
) -> tuple[int, int, int, int]:
    local_size = max(1, int(local_size_x or 1))
    total_groups = max(1, int(math.ceil(max(1, int(work_items)) / float(local_size))))
    limits = [max(1, int(value or 0)) for value in list(max_group_counts or [])[:3]]
    while len(limits) < 3:
        limits.append(65535)
    if total_groups <= limits[0]:
        return total_groups, 1, 1, total_groups * local_size
    minimum_y = max(2, int(math.ceil(total_groups / float(limits[0]))))
    for groups_y in range(minimum_y, min(limits[1], total_groups) + 1):
        if total_groups % groups_y:
            continue
        groups_x = total_groups // groups_y
        if groups_x <= limits[0]:
            return groups_x, groups_y, 1, total_groups * local_size
    minimum_z = max(
        2,
        int(math.ceil(total_groups / float(max(1, limits[0] * limits[1])))),
    )
    for groups_z in range(minimum_z, min(limits[2], total_groups) + 1):
        if total_groups % groups_z:
            continue
        remaining_groups = total_groups // groups_z
        minimum_y = max(1, int(math.ceil(remaining_groups / float(limits[0]))))
        for groups_y in range(minimum_y, min(limits[1], remaining_groups) + 1):
            if remaining_groups % groups_y:
                continue
            groups_x = remaining_groups // groups_y
            if groups_x <= limits[0]:
                return groups_x, groups_y, groups_z, total_groups * local_size
    raise RuntimeError(
        "Vulkan compute dispatch cannot be represented exactly within supported "
        "workgroup counts without an out-of-range invocation: "
        f"required_groups={total_groups} limits={limits}"
    )


def next_submission_batch_iterations(
    current: int,
    observed_seconds: float,
    *,
    full_load: bool,
    maximum: int = 8,
    target_seconds: float = 0.05,
) -> int:
    current_value = max(1, min(int(maximum), int(current or 1)))
    if not full_load or observed_seconds <= 0:
        return 1
    if observed_seconds < target_seconds * 0.5 and current_value < maximum:
        return min(maximum, current_value * 2)
    if observed_seconds > target_seconds * 2.0 and current_value > 1:
        return max(1, current_value // 2)
    return current_value


def timed_action_due(
    last_monotonic: float,
    now_monotonic: float,
    interval_seconds: float,
    *,
    required: bool = False,
) -> bool:
    return bool(
        required
        or last_monotonic <= 0
        or now_monotonic - last_monotonic >= max(0.0, interval_seconds)
    )


def compute_shader_spirv(
    compute_rounds: int,
    kernel_variant: str = "hash",
    local_size_x: int = 256,
) -> bytes:
    # Hand-built SPIR-V for:
    # layout(local_size_x=<selected legal size>) in;
    # layout(std430, binding=0) buffer Data { uint data[]; };
    # void main() {
    #   uint gid = linearized gl_GlobalInvocationID across x/y/z;
    #   uint v = gid;                                  // hash / stress_hash
    #   uint v = data[gid] ^ gid;                      // stateful_memory
    #   repeat compute_rounds times:
    #     v ^= v >> 16; v *= 0x7FEB352Du;
    #     v ^= v >> 15; v *= 0x846CA68Bu;
    #     v ^= v >> 16; v += gl_GlobalInvocationID.x;
    #   data[gl_GlobalInvocationID.x] = v;
    # }
    words: list[int] = [0x07230203, 0x00010000, 0, 64, 0]
    words += _inst(17, [1])  # OpCapability Shader
    words += _inst(14, [0, 1])  # OpMemoryModel Logical GLSL450
    words += [((3 + len(_words_for_string("main")) + 2) << 16) | 15, 5, 13, *_words_for_string("main"), 11, 21]
    words += _inst(16, [13, 17, max(1, int(local_size_x)), 1, 1])  # OpExecutionMode LocalSize
    words += _inst(71, [11, 11, 28])  # BuiltIn GlobalInvocationId
    words += _inst(71, [21, 11, 24])  # BuiltIn NumWorkgroups
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
    words += _inst(59, [10, 21, 1])  # number of workgroups
    words += _inst(32, [12, 2, 3])  # ptr Uniform uint
    words += _inst(43, [3, 17, 16])  # shift 16
    words += _inst(43, [3, 18, 15])  # shift 15
    words += _inst(43, [3, 19, 0x7FEB352D])  # hash multiplier A
    words += _inst(43, [3, 20, 0x846CA68B])  # hash multiplier B
    words += _inst(43, [3, 25, max(1, int(local_size_x))])  # selected local size
    words += _inst(54, [1, 13, 0, 2])  # function
    words += _inst(248, [14])  # label
    words += _inst(61, [4, 15, 11])  # load gid vector
    words += _inst(81, [3, 16, 15, 0])  # extract global x
    words += _inst(61, [4, 22, 21])  # load NumWorkgroups
    words += _inst(81, [3, 23, 22, 0])  # extract workgroup count x
    words += _inst(81, [3, 24, 15, 1])  # extract global y
    words += _inst(132, [3, 26, 23, 25])  # row width in invocations
    words += _inst(132, [3, 27, 24, 26])  # y row offset
    words += _inst(81, [3, 28, 15, 2])  # extract global z
    words += _inst(81, [3, 29, 22, 1])  # extract workgroup count y
    words += _inst(132, [3, 30, 23, 29])  # workgroups per x/y plane
    words += _inst(132, [3, 31, 30, 25])  # invocations per x/y plane
    words += _inst(132, [3, 32, 28, 31])  # z plane offset
    words += _inst(128, [3, 33, 16, 27])  # linear x/y invocation index
    words += _inst(128, [3, 34, 33, 32])  # linear x/y/z invocation index
    original_id = 34
    variant = normalize_kernel_variant(kernel_variant)
    ptr_id = 0
    if variant == "stateful_memory":
        ptr_id = 35
        loaded_id = 36
        seed_id = 37
        words += _inst(65, [12, ptr_id, 9, 5, original_id])  # access data[linear gid]
        words += _inst(61, [3, loaded_id, ptr_id])  # load previous data[gid.x]
        words += _inst(198, [3, seed_id, loaded_id, original_id])  # previous ^ gid
        previous = seed_id
        next_id = 38
    else:
        previous = original_id
        next_id = 35
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
        words += _inst(128, [3, add_id, xor3_id, original_id])  # IAdd original gid
        previous = add_id
        next_id += 9
    bound_id = next_id + 1
    if not ptr_id:
        ptr_id = next_id
        words += _inst(65, [12, ptr_id, 9, 5, original_id])  # access data[linear gid]
        bound_id = ptr_id + 1
    words += _inst(62, [ptr_id, previous])  # store
    words += _inst(253, [])  # return
    words += _inst(56, [])  # function end
    words[3] = max(bound_id, ptr_id + 1)
    validate_generated_compute_spirv_structure(words)
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


def compute_queue_family_details(vk: ctypes.CDLL, physical_device: ctypes.c_void_p) -> tuple[int, dict]:
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
    selected = props[best_index]
    return best_index, {
        "queue_flags": int(selected.queueFlags),
        "queue_count": int(selected.queueCount),
        "timestamp_valid_bits": int(selected.timestampValidBits),
    }


def choose_compute_queue_family(vk: ctypes.CDLL, physical_device: ctypes.c_void_p) -> int:
    return compute_queue_family_details(vk, physical_device)[0]


def configure_optional_timestamp_query_prototypes(vk: ctypes.CDLL) -> bool:
    names = (
        "vkCreateQueryPool",
        "vkDestroyQueryPool",
        "vkCmdResetQueryPool",
        "vkCmdWriteTimestamp",
        "vkGetQueryPoolResults",
    )
    try:
        functions = {name: getattr(vk, name) for name in names}
    except (AttributeError, OSError):
        return False
    functions["vkCreateQueryPool"].argtypes = [ctypes.c_void_p, ctypes.POINTER(VkQueryPoolCreateInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    functions["vkCreateQueryPool"].restype = ctypes.c_int32
    functions["vkDestroyQueryPool"].argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    functions["vkDestroyQueryPool"].restype = None
    functions["vkCmdResetQueryPool"].argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
    functions["vkCmdResetQueryPool"].restype = None
    functions["vkCmdWriteTimestamp"].argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
    functions["vkCmdWriteTimestamp"].restype = None
    functions["vkGetQueryPoolResults"].argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint32]
    functions["vkGetQueryPoolResults"].restype = ctypes.c_int32
    return True


def extend_vulkan_prototypes(vk: ctypes.CDLL) -> dict[str, bool]:
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
    return {
        "timestamp_query_functions": configure_optional_timestamp_query_prototypes(vk),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-vendor", default="")
    parser.add_argument("--target-vendor-id", default="")
    parser.add_argument("--target-device-id", default="")
    parser.add_argument("--target-device-name", default="")
    parser.add_argument("--target-card", default="")
    parser.add_argument("--target-slot", default="")
    parser.add_argument("--target-device-uuid", default="")
    parser.add_argument("--target-id", default="")
    parser.add_argument("--physical-gpu-id", default="")
    parser.add_argument("--target-gpu-index", type=int, default=0)
    parser.add_argument("--vulkan-device-index", type=int, default=-1)
    parser.add_argument("--target-vram-total", type=int, default=0)
    parser.add_argument("--buffer-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--system-memory-fixed-commitment-bytes", type=int, default=1024 * 1024)
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
        "worker_version": "vulkan_compute_stateful_memory_v20"
        if resolved_kernel_variant == "stateful_memory"
        else (
            "vulkan_compute_stress_hash_v8"
            if resolved_kernel_variant == "stress_hash"
            else "vulkan_compute_hash_v8"
        ),
        "kernel_variant": resolved_kernel_variant,
        "backend_api_family": "Vulkan",
        "suite_scaling_mode": "parametric",
        "suite_verification": "compute_readback",
        "diagnostic_backend": False,
        "workload_purpose": (
            "compute_stress_candidate"
            if resolved_kernel_variant == "stress_hash"
            else "memory_path_validation"
            if resolved_kernel_variant == "stateful_memory"
            else "compute_correctness"
        ),
        # Compatibility fields remain boolean, but execution alone is not
        # evidence that physical saturation or power saturation was reached.
        "saturation_result": False,
        "power_saturation_expected": False,
        "status": "initializing",
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
        "allocation_attempts": 0,
        "allocation_failures": 0,
        "allocation_backoff_attempts": [],
        "actual_allocated_bytes": 0,
        "staging_allocation_bytes": 0,
        "system_memory_fixed_commitment_bytes": max(0, int(args.system_memory_fixed_commitment_bytes)),
        "allocation_ratio": 0.0,
        "allocation_outcome": "not_started",
        "allocation_valid": False,
        "runtime_memory_guard_triggered": False,
        "allocation_growth_stopped": False,
        "runtime_memory_guard_details": {},
        "max_single_allocation_bytes": 0,
        "max_buffer_or_object_bytes": 0,
        "max_memory_allocation_count": 0,
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
        "effective_compute_rounds": resolved_compute_rounds,
        "dependent_compute_rounds": resolved_compute_rounds,
        "aggregate_round_work_per_cycle": resolved_compute_rounds * resolved_dispatch_repeats,
        "independent_dispatch_repetitions": resolved_dispatch_repeats,
        "queue_submission_count": 0,
        "compute_dispatch_count": 0,
        "timing_instrumentation_scope": "execution_cycles_after_device_and_buffer_setup",
        "fence_wait_semantics": "host_elapsed_wait_for_submitted_batch_completion_not_gpu_execution_time",
        "command_buffer_record_count": 0,
        "command_buffer_reuse_count": 0,
        "submission_batch_iterations": 1,
        "submission_batch_iterations_max": 1,
        "adaptive_batching_enabled": resolved_kernel_variant == "stress_hash",
        "adaptive_batch_target_seconds": 0.05,
        "command_record_elapsed_seconds": 0.0,
        "queue_submit_elapsed_seconds": 0.0,
        "fence_wait_elapsed_seconds": 0.0,
        "verification_readback_count": 0,
        "verification_readback_elapsed_seconds": 0.0,
        "verification_interval_target_seconds": 0.75,
        "verification_intervals_seconds": [],
        "initial_verification_completed": False,
        "final_verification_completed": False,
        "result_write_count": 0,
        "result_write_elapsed_seconds": 0.0,
        "result_write_interval_target_seconds": 1.0,
        "sleep_yield_count": 0,
        "sleep_yield_elapsed_seconds": 0.0,
        "cycle_count": 0,
        "cycle_elapsed_seconds": 0.0,
        "cycle_latency_last_seconds": 0.0,
        "cycle_latency_min_seconds": None,
        "cycle_latency_max_seconds": 0.0,
        "batch_latency_last_seconds": 0.0,
        "worker_cpu_seconds": 0.0,
        "workgroup_local_size": [0, 1, 1],
        "dispatch_group_count": [0, 1, 1],
        "max_compute_work_group_invocations": 0,
        "max_compute_work_group_size": [0, 0, 0],
        "max_compute_work_group_count": [0, 0, 0],
        "gpu_timestamp_status": "not_assessed",
        "gpu_timestamp_reason": "",
        "gpu_timestamp_semantics": "device_timestamps_between_compute_stage_markers_when_supported",
        "gpu_timestamp_batch_count": 0,
        "gpu_timestamp_elapsed_seconds": 0.0,
        "gpu_timestamp_last_seconds": None,
        "gpu_timestamp_min_seconds": None,
        "gpu_timestamp_max_seconds": None,
        "startup_checkpoint": "worker_process_started",
        "startup_checkpoints": [],
        "startup_complete": False,
        "fault_diagnostics_enabled": False,
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
        "selected_device_uuid": "",
        "target_device_uuid": args.target_device_uuid,
        "selected_vulkan_index": -1,
        "hardware_device_verified": False,
        "device_match_score": 0.0,
        "device_match_ambiguous": False,
        "queue_family_index": -1,
        "target_vendor": args.target_vendor,
        "target_vendor_id": args.target_vendor_id,
        "target_device_id": args.target_device_id,
        "target_device_name": args.target_device_name,
        "target_card": args.target_card,
        "target_slot": args.target_slot,
        "target_id": args.target_id,
        "physical_gpu_id": args.physical_gpu_id,
        "target_gpu_index": args.target_gpu_index,
        "telemetry_gpu_index": args.target_gpu_index,
        "vulkan_device_index": args.vulkan_device_index,
        "target_vram_total": args.target_vram_total,
        "profile_mode": args.profile_mode,
        "profile_intensity": args.profile_intensity,
        "tuning_step": args.tuning_step,
        "last_error": "",
        "failure_reason": "",
    }
    running = True
    worker_cpu_started = time.process_time()
    last_result_write_monotonic = 0.0
    state["worker_result_file"] = args.result_file
    state["result_write_error_count"] = 0
    state["last_result_write_error"] = ""
    stalls = SlowOperationRecorder(state)

    def record_error(message):
        state["status"] = "error"
        state["error_count"] += 1
        state["last_error"] = str(message)
        state["failure_reason"] = vulkan_failure_reason(message)
        write_result("error", force=True)

    def write_result(reason="periodic", *, force=False):
        nonlocal last_result_write_monotonic
        if not args.result_file:
            return
        now = time.monotonic()
        if not timed_action_due(
            last_result_write_monotonic,
            now,
            float(state["result_write_interval_target_seconds"]),
            required=force,
        ):
            return
        started_write = time.perf_counter()
        state["result_write_count"] += 1
        state["last_result_write_reason"] = str(reason)
        state["worker_cpu_seconds"] = round(max(0.0, time.process_time() - worker_cpu_started), 6)
        try:
            persist_worker_result(args.result_file, state, stalls, force=force)
            last_result_write_monotonic = now
            return True
        except Exception as exc:
            state["result_write_error_count"] = int(state.get("result_write_error_count", 0)) + 1
            state["last_result_write_error"] = type(exc).__name__
            return False
        finally:
            state["result_write_elapsed_seconds"] = round(
                float(state["result_write_elapsed_seconds"]) + max(0.0, time.perf_counter() - started_write),
                6,
            )

    def record_startup_checkpoint(name: str, **evidence) -> None:
        entry = {
            "name": str(name),
            "elapsed_seconds": round(max(0.0, time.monotonic() - worker_started_monotonic), 6),
        }
        if evidence:
            entry["evidence"] = evidence
        checkpoints = list(state.get("startup_checkpoints") or [])
        checkpoints.append(entry)
        state["startup_checkpoints"] = checkpoints[-16:]
        state["startup_checkpoint"] = str(name)
        write_result(f"startup:{name}", force=True)

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    register_worker_exit_diagnostics(stalls, write_result)

    worker_started_monotonic = time.monotonic()
    try:
        faulthandler.enable(all_threads=True)
        state["fault_diagnostics_enabled"] = True
    except (RuntimeError, OSError, ValueError):
        state["fault_diagnostics_enabled"] = False
    record_startup_checkpoint("worker_process_started")

    handles = {}
    vk = None
    try:
        library = resolve_vulkan_library()
        if not library:
            raise RuntimeError("Vulkan loader library not found")
        vk = load_vulkan(library)
        prototype_support = extend_vulkan_prototypes(vk)
        record_startup_checkpoint(
            "vulkan_loader_ready",
            timestamp_query_functions=bool(prototype_support.get("timestamp_query_functions")),
        )
        instance = make_instance(vk)
        handles["instance"] = instance
        physical_devices = enumerate_devices(vk, instance)
        record_startup_checkpoint(
            "vulkan_instance_initialized",
            physical_device_count=len(physical_devices),
        )
        infos = [(parse_properties(vk, physical_device, index), physical_device) for index, physical_device in enumerate(physical_devices)]
        score, selected_info, physical_device = select_physical_device(infos, args)
        selected_name = str(selected_info.get("device_name") or "").lower()
        hardware_verified = selected_info.get("device_type") != "cpu" and not any(
            token in selected_name for token in ("llvmpipe", "lavapipe", "softpipe", "swrast", "software rasterizer")
        )
        if not hardware_verified:
            raise RuntimeError("selected Vulkan device is not a hardware GPU")
        state.update(
            {
                "selected_device_name": selected_info["device_name"],
                "selected_device_vendor_id": selected_info["vendor_id"],
                "selected_device_id": selected_info["device_id"],
                "selected_device_type": selected_info["device_type"],
                "selected_device_pci_slot": selected_info.get("pci_slot", ""),
                "selected_device_uuid": selected_info.get("device_uuid", ""),
                "target_device_uuid": args.target_device_uuid,
                "physical_identity_evidence": native_identity_evidence(selected_info, args),
                "selected_vulkan_index": selected_info["index"],
                "hardware_device_verified": True,
                "device_match_score": float(score),
                "device_match_ambiguous": False,
            }
        )
        max_storage_buffer_range = max(0, int(selected_info.get("max_storage_buffer_range_bytes") or 0))
        max_memory_allocation_count = max(0, int(selected_info.get("max_memory_allocation_count") or 0))
        max_compute_work_group_invocations = max(
            1, int(selected_info.get("max_compute_work_group_invocations") or 1)
        )
        max_compute_work_group_size = [
            max(1, int(value or 1))
            for value in list(selected_info.get("max_compute_work_group_size") or [1, 1, 1])[:3]
        ]
        max_compute_work_group_count = [
            max(1, int(value or 1))
            for value in list(selected_info.get("max_compute_work_group_count") or [65535, 65535, 65535])[:3]
        ]
        while len(max_compute_work_group_size) < 3:
            max_compute_work_group_size.append(1)
        while len(max_compute_work_group_count) < 3:
            max_compute_work_group_count.append(65535)
        local_size_x = select_compute_local_size(
            max_compute_work_group_invocations,
            max_compute_work_group_size,
        )
        state["max_buffer_or_object_bytes"] = max_storage_buffer_range
        state["max_memory_allocation_count"] = max_memory_allocation_count
        state["max_compute_work_group_invocations"] = max_compute_work_group_invocations
        state["max_compute_work_group_size"] = max_compute_work_group_size
        state["max_compute_work_group_count"] = max_compute_work_group_count
        state["workgroup_local_size"] = [local_size_x, 1, 1]
        queue_family, queue_family_evidence = compute_queue_family_details(vk, physical_device)
        state["queue_family_index"] = queue_family
        state["queue_family_evidence"] = queue_family_evidence
        record_startup_checkpoint(
            "physical_device_limits_discovered",
            selected_vulkan_index=int(selected_info["index"]),
            local_size_x=local_size_x,
            max_compute_work_group_invocations=max_compute_work_group_invocations,
            max_compute_work_group_size=max_compute_work_group_size,
            max_compute_work_group_count=max_compute_work_group_count,
        )
        priority = ctypes.c_float(1.0)
        queue_info = VkDeviceQueueCreateInfo(VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, VK_NULL_HANDLE, 0, queue_family, 1, ctypes.pointer(priority))
        device_info = VkDeviceCreateInfo(VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, VK_NULL_HANDLE, 0, 1, ctypes.pointer(queue_info), 0, VK_NULL_HANDLE, 0, VK_NULL_HANDLE, VK_NULL_HANDLE)
        device = ctypes.c_void_p()
        check(vk.vkCreateDevice(physical_device, ctypes.byref(device_info), None, ctypes.byref(device)), "vkCreateDevice")
        handles["device"] = device
        queue = ctypes.c_void_p()
        vk.vkGetDeviceQueue(device, queue_family, 0, ctypes.byref(queue))
        record_startup_checkpoint("logical_device_initialized", queue_family_index=queue_family)

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
        if max_storage_buffer_range > 0:
            per_buffer_cap_bytes = min(per_buffer_cap_bytes, max_storage_buffer_range)
        per_buffer_cap_bytes -= per_buffer_cap_bytes % 1024
        requested_total_size = max(8 * 1024 * 1024, min(total_cap_bytes, int(args.buffer_bytes)))
        requested_total_size -= requested_total_size % 1024
        state["requested_buffer_bytes"] = int(args.buffer_bytes)
        state["worker_total_cap_bytes"] = int(total_cap_bytes)
        state["per_buffer_cap_bytes"] = int(per_buffer_cap_bytes)
        buffer_count_limit = stateful_memory_buffer_count_limit(
            requested_total_size,
            per_buffer_cap_bytes,
            max_memory_allocation_count,
        )
        state["buffer_count_limit"] = buffer_count_limit
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
        while remaining_size >= 8 * 1024 * 1024 and len(buffer_records) < buffer_count_limit:
            request_size = min(per_buffer_cap_bytes, remaining_size)
            request_size -= request_size % 1024
            allocated = False
            while request_size >= 8 * 1024 * 1024:
                shared_memory_device = str(args.device_class or "").strip().lower() != "discrete"
                guard_claim = claim_runtime_allocation_growth(
                    request_size,
                    shared_system_memory=shared_memory_device,
                )
                if not guard_claim.get("allowed"):
                    state["runtime_memory_guard_triggered"] = True
                    state["allocation_growth_stopped"] = True
                    state["runtime_memory_guard_details"] = guard_claim
                    state["target_cap_reason"] = "runtime_memory_guard"
                    break
                state["allocation_attempts"] += 1
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
                        prefer_largest_heap=shared_memory_device,
                    )
                    existing_allocation_bytes = sum(int(record["allocation_bytes"]) for record in buffer_records)
                    if shared_memory_device and existing_allocation_bytes + int(buffer_allocation_bytes) > int(args.buffer_bytes):
                        release_runtime_allocation_claim(
                            request_size,
                            shared_system_memory=shared_memory_device,
                        )
                        vk.vkDestroyBuffer(device, buffer_handle, None)
                        vk.vkFreeMemory(device, buffer_memory, None)
                        buffer_handle = ctypes.c_void_p()
                        buffer_memory = ctypes.c_void_p()
                        overage = existing_allocation_bytes + int(buffer_allocation_bytes) - int(args.buffer_bytes)
                        request_size = max(0, request_size - overage)
                        request_size -= request_size % 1024
                        state["allocation_failures"] += 1
                        state["allocation_backoff_attempts"].append(
                            {
                                "requested_bytes": int(request_size + overage),
                                "allocation_requirement_bytes": int(buffer_allocation_bytes),
                                "reason": "shared_system_memory_target_guard",
                            }
                        )
                        continue
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
                except Exception as exc:
                    release_runtime_allocation_claim(
                        request_size,
                        shared_system_memory=shared_memory_device,
                    )
                    state["allocation_failures"] += 1
                    state["allocation_backoff_attempts"].append(
                        {"requested_bytes": int(request_size), "error": str(exc)}
                    )
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
        staging_claim = claim_runtime_allocation_growth(
            4096,
            shared_system_memory=shared_memory_device,
        )
        if not staging_claim.get("allowed"):
            state["runtime_memory_guard_triggered"] = True
            state["allocation_growth_stopped"] = True
            state["runtime_memory_guard_details"] = staging_claim
            state["target_cap_reason"] = "runtime_memory_guard"
            raise RuntimeError("runtime memory guard denied Vulkan staging allocation")
        staging_buffer, staging_memory, staging_allocation_bytes, staging_memory_type = create_buffer(
            vk,
            device,
            memory_props,
            4096,
            VK_BUFFER_USAGE_TRANSFER_DST_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
        )
        handles["staging_buffer"] = staging_buffer
        handles["staging_memory"] = staging_memory
        if shared_memory_device and int(staging_allocation_bytes) > int(args.system_memory_fixed_commitment_bytes):
            raise RuntimeError(
                "Vulkan staging allocation exceeds the stage-planned fixed system-memory commitment"
            )
        total_buffer_bytes = sum(int(record["size"]) for record in buffer_records)
        total_allocation_bytes = sum(int(record["allocation_bytes"]) for record in buffer_records)
        buffer_sizes = [int(record["size"]) for record in buffer_records]
        state["target_buffer_bytes"] = int(args.buffer_bytes)
        state["buffer_bytes"] = int(total_buffer_bytes)
        state["buffer_count"] = len(buffer_records)
        state["buffer_size_min_bytes"] = int(min(buffer_sizes)) if buffer_sizes else 0
        state["buffer_size_max_bytes"] = int(max(buffer_sizes)) if buffer_sizes else 0
        state["buffer_size_avg_bytes"] = int(sum(buffer_sizes) / len(buffer_sizes)) if buffer_sizes else 0
        state["buffer_allocation_bytes"] = int(total_allocation_bytes)
        state["allocation_shortfall_bytes"] = max(0, int(args.buffer_bytes) - int(total_buffer_bytes))
        state["actual_allocated_bytes"] = int(total_allocation_bytes) + int(staging_allocation_bytes)
        state["staging_allocation_bytes"] = int(staging_allocation_bytes)
        allocation_ratio = total_buffer_bytes / float(max(1, int(args.buffer_bytes)))
        state["allocation_ratio"] = round(allocation_ratio, 6)
        state["allocation_outcome"] = (
            "full_target_achieved" if total_buffer_bytes >= int(args.buffer_bytes)
            else "substantial_partial_allocation" if allocation_ratio >= 0.85
            else "partial_allocation" if allocation_ratio >= 0.60
            else "insufficient_partial_allocation"
        )
        state["allocation_valid"] = allocation_ratio >= 0.60
        state["buffer_memory_type_index"] = int(first_record["memory_type"])
        state["staging_memory_type_index"] = int(staging_memory_type)
        if 0 <= int(first_record["memory_type"]) < int(memory_props.memoryTypeCount):
            memory_type = memory_props.memoryTypes[int(first_record["memory_type"])]
            state["buffer_memory_type_flags"] = int(memory_type.propertyFlags)
            state["buffer_memory_heap_index"] = int(memory_type.heapIndex)
        if device_local_heap_bytes:
            state["buffer_device_local_heap_percent"] = round((int(total_allocation_bytes) / float(device_local_heap_bytes)) * 100.0, 4)
        record_startup_checkpoint(
            "buffers_allocated",
            buffer_count=len(buffer_records),
            buffer_bytes=int(total_buffer_bytes),
            staging_allocation_bytes=int(staging_allocation_bytes),
        )

        compute_rounds = resolved_compute_rounds
        dispatch_repeats = resolved_dispatch_repeats
        state["dispatch_repeats"] = dispatch_repeats
        state["effective_compute_rounds"] = compute_rounds
        state["dependent_compute_rounds"] = compute_rounds
        state["aggregate_round_work_per_cycle"] = compute_rounds * dispatch_repeats
        spirv = compute_shader_spirv(compute_rounds, kernel_variant, local_size_x)
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
        record_startup_checkpoint(
            "pipeline_created",
            shader_bytes=len(spirv),
            kernel_variant=kernel_variant,
            compute_rounds=compute_rounds,
        )

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
        timestamp_valid_bits = int(queue_family_evidence.get("timestamp_valid_bits") or 0)
        timestamp_period_ns = float(selected_info.get("timestamp_period_nanoseconds") or 0.0)
        query_pool = ctypes.c_void_p()
        timestamp_compute_supported = bool(selected_info.get("timestamp_compute_and_graphics"))
        timestamp_functions_available = bool(prototype_support.get("timestamp_query_functions"))
        if timestamp_valid_bits > 0 and timestamp_period_ns > 0 and timestamp_compute_supported and timestamp_functions_available:
            query_info = VkQueryPoolCreateInfo(
                VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO,
                VK_NULL_HANDLE,
                0,
                VK_QUERY_TYPE_TIMESTAMP,
                2,
                0,
            )
            query_code = int(vk.vkCreateQueryPool(device, ctypes.byref(query_info), None, ctypes.byref(query_pool)))
            if query_code == 0 and query_pool:
                handles["query_pool"] = query_pool
                state["gpu_timestamp_status"] = "measured"
                state["gpu_timestamp_reason"] = "queue_timestamp_queries_supported"
                state["gpu_timestamp_period_nanoseconds"] = timestamp_period_ns
                state["gpu_timestamp_valid_bits"] = timestamp_valid_bits
            else:
                query_pool = ctypes.c_void_p()
                state["gpu_timestamp_status"] = "unavailable"
                state["gpu_timestamp_reason"] = f"vkCreateQueryPool_failed:{query_code}"
        else:
            state["gpu_timestamp_status"] = "unavailable"
            state["gpu_timestamp_reason"] = (
                "queue_timestamp_valid_bits_zero"
                if timestamp_valid_bits <= 0
                else "timestamp_period_unavailable"
                if timestamp_period_ns <= 0
                else "timestamp_query_functions_unavailable"
                if not timestamp_functions_available
                else "compute_timestamp_commands_unsupported"
            )
        record_startup_checkpoint(
            "descriptors_sync_and_timestamp_initialized",
            timestamp_status=str(state["gpu_timestamp_status"]),
            timestamp_reason=str(state["gpu_timestamp_reason"]),
        )
        fence_array = (ctypes.c_void_p * 1)(fence)
        command_array = (ctypes.c_void_p * 1)(command_buffer)
        if kernel_variant == "stateful_memory":
            for record_index, record in enumerate(buffer_records):
                init_record_token = stalls.begin("command_record")
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
                stalls.finish(init_record_token)
                submit = VkSubmitInfo(4, VK_NULL_HANDLE, 0, VK_NULL_HANDLE, VK_NULL_HANDLE, 1, command_array, 0, VK_NULL_HANDLE)
                stalls.call("queue_submit", lambda: check(vk.vkQueueSubmit(queue, 1, ctypes.byref(submit), fence), f"vkQueueSubmit(init {record_index})"))
                stalls.call("fence_wait", lambda: check(vk.vkWaitForFences(device, 1, fence_array, VK_TRUE, 10_000_000_000), f"vkWaitForFences(init {record_index})"))

        started = time.monotonic()
        sample_words = 256
        expected_samples = [[0 for _ in range(sample_words)] for _ in buffer_records]
        expected_sample_dispatches = [0 for _ in buffer_records]
        buffer_dispatch_counts = [0 for _ in buffer_records]
        verified_buffer_indexes: set[int] = set()
        verification_cursor = 0
        last_verification_monotonic = 0.0
        total_estimated_memory_bytes = 0
        submission_batch_iterations = 1
        cached_command_signature = None
        final_cycle_completed = False
        initial_command_checkpoint_recorded = False
        first_submission_checkpoint_recorded = False
        stalls.track_gaps = True
        stalls.last_finish = time.monotonic()
        while running or not final_cycle_completed:
            prepare_token = stalls.begin("loop_prepare")
            final_cycle = not running
            elapsed = time.monotonic() - started
            if args.ramp_step_seconds > 0:
                progress = min(1.0, elapsed / max(0.001, args.ramp_step_seconds * 3.0))
                load_fraction = min(1.0, max(0.15, args.start_load_fraction) + (1.0 - max(0.15, args.start_load_fraction)) * progress)
            else:
                load_fraction = 1.0
            full_load = load_fraction >= 0.999
            if kernel_variant != "stress_hash" or not full_load:
                submission_batch_iterations = 1
            active_infos = []
            for record in buffer_records:
                active_buffer_size = int(record["size"])
                active_size = max(1024 * 1024, int(active_buffer_size * load_fraction))
                active_size -= active_size % 1024
                requested_words = max(local_size_x, active_size // 4)
                groups_x, groups_y, groups_z, dispatched_words = compute_dispatch_dimensions(
                    requested_words,
                    local_size_x,
                    max_compute_work_group_count,
                )
                active_words = min(active_buffer_size // 4, dispatched_words)
                active_size = active_words * 4
                active_infos.append(
                    (record, active_size, active_words, (groups_x, groups_y, groups_z))
                )
            active_total_size = sum(item[1] for item in active_infos)
            active_total_words = sum(item[2] for item in active_infos)
            max_dispatch_size = max((item[1] for item in active_infos), default=0)
            now = time.monotonic()
            verification_due = timed_action_due(
                last_verification_monotonic,
                now,
                float(state["verification_interval_target_seconds"]),
                required=state["verification_passes"] == 0 or final_cycle,
            )
            verify_buffer_index = -1
            if verification_due and buffer_records:
                verify_buffer_index = verification_cursor % len(buffer_records)
                verification_cursor += 1
            dispatches_per_buffer = dispatch_repeats * submission_batch_iterations
            cycle_memory_bytes = sum(
                active_size
                * (dispatches_per_buffer if kernel_variant != "stateful_memory" else 2 * dispatches_per_buffer)
                for _record, active_size, _active_words, _groups in active_infos
            )
            command_signature = (
                tuple((item[1], item[3]) for item in active_infos),
                dispatches_per_buffer,
                verify_buffer_index,
                bool(query_pool),
            )
            must_record = command_signature != cached_command_signature
            cycle_started = time.perf_counter()

            check(vk.vkResetFences(device, 1, fence_array), "vkResetFences(cycle)")
            stalls.finish(prepare_token)
            if must_record:
                record_token = stalls.begin("command_record")
                record_started = time.perf_counter()
                check(vk.vkResetCommandBuffer(command_buffer, 0), "vkResetCommandBuffer(cycle)")
                begin = VkCommandBufferBeginInfo(
                    VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
                    VK_NULL_HANDLE,
                    0,
                    VK_NULL_HANDLE,
                )
                check(vk.vkBeginCommandBuffer(command_buffer, ctypes.byref(begin)), "vkBeginCommandBuffer(cycle)")
                if query_pool:
                    vk.vkCmdResetQueryPool(command_buffer, query_pool, 0, 2)
                    vk.vkCmdWriteTimestamp(
                        command_buffer,
                        VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                        query_pool,
                        0,
                    )
                vk.vkCmdBindPipeline(command_buffer, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline)
                for active_buffer_index, (active_record, active_size, _active_words, groups) in enumerate(active_infos):
                    active_buffer_handle = active_record["buffer"]
                    should_verify = active_buffer_index == verify_buffer_index
                    sample_bytes = min(active_size, sample_words * 4)
                    vk.vkCmdBindDescriptorSets(command_buffer, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline_layout, 0, 1, descriptor_sets_by_buffer[active_buffer_index], 0, VK_NULL_HANDLE)
                    for dispatch_index in range(dispatches_per_buffer):
                        vk.vkCmdDispatch(command_buffer, groups[0], groups[1], groups[2])
                        if dispatch_index < dispatches_per_buffer - 1:
                            repeat_barrier = VkBufferMemoryBarrier(
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
                if query_pool:
                    vk.vkCmdWriteTimestamp(
                        command_buffer,
                        VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                        query_pool,
                        1,
                    )
                check(vk.vkEndCommandBuffer(command_buffer), "vkEndCommandBuffer(cycle)")
                stalls.finish(record_token)
                if not initial_command_checkpoint_recorded:
                    record_startup_checkpoint(
                        "initial_command_recorded",
                        dispatch_group_count=list(active_infos[0][3]) if active_infos else [0, 1, 1],
                        dispatches_per_buffer=dispatches_per_buffer,
                        verification_copy_recorded=verify_buffer_index >= 0,
                    )
                    initial_command_checkpoint_recorded = True
                cached_command_signature = command_signature
                state["command_buffer_record_count"] += 1
                state["command_record_elapsed_seconds"] = round(
                    float(state["command_record_elapsed_seconds"])
                    + max(0.0, time.perf_counter() - record_started),
                    6,
                )
            else:
                state["command_buffer_reuse_count"] += 1

            submit = VkSubmitInfo(4, VK_NULL_HANDLE, 0, VK_NULL_HANDLE, VK_NULL_HANDLE, 1, command_array, 0, VK_NULL_HANDLE)
            submit_started = time.perf_counter()
            stalls.call("queue_submit", lambda: check(
                vk.vkQueueSubmit(queue, 1, ctypes.byref(submit), fence), "vkQueueSubmit(cycle)"))
            state["queue_submit_elapsed_seconds"] = round(
                float(state["queue_submit_elapsed_seconds"])
                + max(0.0, time.perf_counter() - submit_started),
                6,
            )
            state["queue_submission_count"] += 1
            wait_started = time.perf_counter()
            stalls.call("fence_wait", lambda: check(
                vk.vkWaitForFences(device, 1, fence_array, VK_TRUE, 10_000_000_000), "vkWaitForFences(cycle)"))
            fence_wait_seconds = max(0.0, time.perf_counter() - wait_started)
            if not first_submission_checkpoint_recorded:
                record_startup_checkpoint(
                    "first_queue_submission_completed",
                    fence_wait_seconds=round(fence_wait_seconds, 6),
                )
                first_submission_checkpoint_recorded = True
            state["fence_wait_elapsed_seconds"] = round(
                float(state["fence_wait_elapsed_seconds"]) + fence_wait_seconds,
                6,
            )
            state["compute_dispatch_count"] += dispatches_per_buffer * len(active_infos)

            measured_gpu_seconds = None
            if query_pool:
                timestamp_values = (ctypes.c_uint64 * 2)()
                query_code = int(
                    stalls.call("gpu_timestamp_retrieval", vk.vkGetQueryPoolResults,
                        device,
                        query_pool,
                        0,
                        2,
                        ctypes.sizeof(timestamp_values),
                        ctypes.byref(timestamp_values),
                        ctypes.sizeof(ctypes.c_uint64),
                        VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WAIT_BIT,
                    )
                )
                if query_code == 0:
                    valid_mask = (
                        (1 << timestamp_valid_bits) - 1
                        if 0 < timestamp_valid_bits < 64
                        else (1 << 64) - 1
                    )
                    tick_delta = (int(timestamp_values[1]) - int(timestamp_values[0])) & valid_mask
                    measured_gpu_seconds = tick_delta * timestamp_period_ns / 1_000_000_000.0
                    state["gpu_timestamp_batch_count"] += 1
                    state["gpu_timestamp_last_seconds"] = round(measured_gpu_seconds, 9)
                    state["gpu_timestamp_elapsed_seconds"] = round(
                        float(state["gpu_timestamp_elapsed_seconds"]) + measured_gpu_seconds,
                        9,
                    )
                    previous_min = state.get("gpu_timestamp_min_seconds")
                    state["gpu_timestamp_min_seconds"] = round(
                        measured_gpu_seconds
                        if previous_min is None
                        else min(float(previous_min), measured_gpu_seconds),
                        9,
                    )
                    state["gpu_timestamp_max_seconds"] = round(
                        max(float(state.get("gpu_timestamp_max_seconds") or 0.0), measured_gpu_seconds),
                        9,
                    )
                else:
                    state["gpu_timestamp_status"] = "query_error"
                    state["gpu_timestamp_reason"] = f"vkGetQueryPoolResults_failed:{query_code}"

            for active_buffer_index, (_, active_size, _, _) in enumerate(active_infos):
                should_verify = active_buffer_index == verify_buffer_index
                sample_bytes = min(active_size, sample_words * 4)
                if should_verify:
                    verification_token = stalls.begin("verification_readback")
                    verification_started = time.perf_counter()
                    if kernel_variant == "stateful_memory":
                        target_dispatches = buffer_dispatch_counts[active_buffer_index] + dispatches_per_buffer
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
                    mismatch = None
                    for word_index in range(sample_bytes // 4):
                        actual = struct.unpack_from("<I", raw, word_index * 4)[0]
                        if kernel_variant == "stateful_memory":
                            expected = expected_samples[active_buffer_index][word_index]
                        else:
                            expected = expected_word(word_index, compute_rounds, 0, kernel_variant)
                        if actual != expected:
                            mismatch = (
                                f"Vulkan compute mismatch at buffer {active_buffer_index} "
                                f"word {word_index}: expected={expected} actual={actual}"
                            )
                            break
                    state["verification_readback_count"] += 1
                    state["verification_readback_elapsed_seconds"] = round(
                        float(state["verification_readback_elapsed_seconds"])
                        + max(0.0, time.perf_counter() - verification_started),
                        6,
                    )
                    if mismatch:
                        state["compute_mismatch_count"] += 1
                        raise RuntimeError(mismatch)
                    stalls.finish(verification_token)
                    verified_at = time.monotonic()
                    if last_verification_monotonic > 0:
                        intervals = list(state["verification_intervals_seconds"])
                        intervals.append(round(verified_at - last_verification_monotonic, 6))
                        state["verification_intervals_seconds"] = intervals[-64:]
                    last_verification_monotonic = verified_at
                    state["verification_passes"] += 1
                    if state["verification_passes"] == 1:
                        state["initial_verification_completed"] = True
                        state["startup_complete"] = True
                        state["status"] = "running"
                        record_startup_checkpoint(
                            "initial_hardware_readback_completed",
                            verified_buffer_index=active_buffer_index,
                            verified_words=sample_bytes // 4,
                        )
                    verified_buffer_indexes.add(active_buffer_index)
                    if final_cycle:
                        state["final_verification_completed"] = True
                buffer_dispatch_counts[active_buffer_index] += dispatches_per_buffer

            updates_token = stalls.begin("loop_state_updates")
            cycle_latency = max(0.0, time.perf_counter() - cycle_started)
            state["cycle_count"] += 1
            state["cycle_elapsed_seconds"] = round(
                float(state["cycle_elapsed_seconds"]) + cycle_latency,
                6,
            )
            state["cycle_latency_last_seconds"] = round(cycle_latency, 6)
            previous_min = state.get("cycle_latency_min_seconds")
            state["cycle_latency_min_seconds"] = round(
                cycle_latency if previous_min is None else min(float(previous_min), cycle_latency),
                6,
            )
            state["cycle_latency_max_seconds"] = round(
                max(float(state["cycle_latency_max_seconds"]), cycle_latency),
                6,
            )
            state["batch_latency_last_seconds"] = round(
                measured_gpu_seconds if measured_gpu_seconds is not None else fence_wait_seconds,
                6,
            )
            state["batch_latency_basis"] = (
                "gpu_timestamp" if measured_gpu_seconds is not None else "host_fence_wait"
            )
            state["active_load_fraction"] = round(load_fraction, 3)
            state["active_buffer_bytes"] = active_total_size
            state["active_dispatch_buffer_bytes"] = max_dispatch_size
            state["active_buffer_count"] = len(buffer_records)
            state["active_buffer_index"] = verify_buffer_index
            state["active_work_items"] = active_total_words
            state["active_compute_rounds"] = compute_rounds
            state["active_dispatch_repeats"] = dispatch_repeats
            state["effective_compute_rounds"] = compute_rounds
            state["aggregate_round_work_per_cycle"] = (
                compute_rounds * dispatches_per_buffer * len(active_infos)
            )
            state["independent_dispatch_repetitions"] = dispatches_per_buffer
            state["submission_batch_iterations"] = submission_batch_iterations
            state["submission_batch_iterations_max"] = max(
                int(state["submission_batch_iterations_max"]), submission_batch_iterations
            )
            state["dispatch_group_count"] = list(active_infos[0][3]) if active_infos else [0, 1, 1]
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
            if kernel_variant == "stress_hash" and full_load and not final_cycle:
                timing_basis = measured_gpu_seconds if measured_gpu_seconds is not None else fence_wait_seconds
                new_batch_iterations = next_submission_batch_iterations(
                    submission_batch_iterations,
                    timing_basis,
                    full_load=True,
                )
                if new_batch_iterations != submission_batch_iterations:
                    submission_batch_iterations = new_batch_iterations
                    cached_command_signature = None
            stalls.finish(updates_token)
            write_result("periodic")
            if final_cycle:
                final_cycle_completed = True
            elif kernel_variant != "stress_hash" or not full_load:
                sleep_started = time.perf_counter()
                stalls.call("sleep_yield", time.sleep, 0.0005)
                state["sleep_yield_count"] += 1
                state["sleep_yield_elapsed_seconds"] = round(
                    float(state["sleep_yield_elapsed_seconds"])
                    + max(0.0, time.perf_counter() - sleep_started),
                    6,
                )
        if state["verification_passes"] <= 0 or not state["final_verification_completed"]:
            raise RuntimeError("Vulkan compute worker ended without required initial and final verification")
        state["status"] = "ok"
        write_result("completed", force=True)
        return 0
    except Exception as exc:
        stalls.fail_pending()
        if int(state.get("actual_allocated_bytes") or 0) > 0:
            state["allocation_outcome"] = "runtime_failure_after_partial_allocation"
        else:
            state["allocation_outcome"] = "allocation_failed"
        state["allocation_valid"] = False
        if isinstance(exc, PhysicalIdentitySelectionError):
            state["physical_identity_evidence"] = exc.identity_evidence
        record_error(exc)
        return 12
    finally:
        stalls.fail_pending()
        stalls.track_gaps = False
        try:
            if vk and handles.get("device"):
                stalls.call("device_wait_idle", vk.vkDeviceWaitIdle, handles["device"])
        except Exception:
            pass
        if vk and handles.get("device"):
            device = handles["device"]
            destroy_pairs = [
                ("query_pool", "vkDestroyQueryPool"),
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
        write_result("finalize")


if __name__ == "__main__":
    raise SystemExit(main())
