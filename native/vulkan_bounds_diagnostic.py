#!/usr/bin/env python3
"""Opt-in, bounded NVIDIA startup observation; never a stress-validation PASS."""
from __future__ import annotations

import argparse
import ctypes as C
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import vulkan_compute_worker as p
import vulkan_transfer_worker as t
from Modules.lvs_vulkan_identity import canonical_pci_slot, normalize_device_uuid
from Modules.lvs_linux_memory import read_linux_memory_snapshot
from Modules.lvs_system_memory_budget import system_memory_budget_bytes
from Modules.lvs_runtime_memory_guard import (RuntimeMemoryClaims, initialize_runtime_memory_guard,
    update_runtime_memory_guard, runtime_memory_stop_required, _write_json_atomic)
from Modules.lvs_source_provenance import collect_source_provenance
from Modules.lvs_source_review import source_identity

LARGE_BYTES, SMALL_BYTES = 3 * 1024**3, 1024**3
OUTPUT_BYTES, RECORD_WORDS, MAGIC = 16384, 12, 0x4C565344
LOGICAL_WORDS = 1101009 * 256  # Recorded first RTX dispatch; probe dispatch is one group.
CLAIM_BYTES = LARGE_BYTES + 1024**2  # Conservatively protect even device memory.
CONTRACT = "linux_validation_suite.vulkan_bounds_startup_diagnostic"


def instructions(blob):
    words = struct.unpack(f"<{len(blob)//4}I", blob)
    result, offset = [], 5
    while offset < len(words):
        size, opcode = words[offset] >> 16, words[offset] & 65535
        if not size or offset + size > len(words):
            raise ValueError("invalid SPIR-V instruction")
        result.append((opcode, list(words[offset+1:offset+size])))
        offset += size
    return list(words[:5]), result


def diagnostic_shader(local_size):
    """Instrument the emitted production shader; retain its indexing/guards/body.

    Binding 0: 3 GiB; binding 1: 1 GiB of the SAME buffer; binding 2: small
    independent output. Every actual probe invocation records observations
    BEFORE the production guard. A separate compile-time local-size bound
    protects output, independent of push constants and either queried length.
    """
    if type(local_size) is not int or not 2 <= local_size <= 256:
        raise ValueError("diagnostic local size must cover word 1 and fit output")
    header, ops = instructions(p.compute_shader_spirv(7, "stateful_memory", local_size))
    # Reproduce the former driver query, retaining current production indexing
    # and arithmetic. This diagnostic must continue to observe the driver bug.
    ops = [(68, [3, 48, 9, 0]) if op == 61 and a[:2] == [3, 48] else (op, a)
           for op, a in ops]
    lengths = [a for op, a in ops if op == 68]
    compares = [a for op, a in ops if op == 176]
    combined = [a for op, a in ops if op == 167]
    if len(lengths) != 1 or len(compares) != 2 or len(combined) != 1:
        raise ValueError("production bounds ABI changed; diagnostic needs review")
    uint, length_id, data_id, member = lengths[0]
    boolean, logical_guard, gid, logical = compares[0]
    _, length_guard, length_gid, compared_length = compares[1]
    _, large_guard, and_left, and_right = combined[0]
    if (member != 0 or length_gid != gid or compared_length != length_id
            or [and_left, and_right] != [logical_guard, length_guard]):
        raise ValueError("unrecognized production bounds expression")
    data_pointer = next(a[0] for op, a in ops if op == 59 and a[1] == data_id)
    word_pointer = next(a[0] for op, a in ops if op == 32 and a[1:] == [2, uint])
    next_id = header[3]
    def new():
        nonlocal next_id
        value = next_id
        next_id += 1
        return value
    constants = {a[2]: a[1] for op, a in ops if op == 43 and a[0] == uint}
    declarations, annotations = [], []
    def constant(value):
        if value not in constants:
            constants[value] = new()
            declarations.append((43, [uint, constants[value], value]))
        return constants[value]
    zero, one = constant(0), constant(1)
    short_id, output_id = new(), new()
    for identifier, binding in ((short_id, 1), (output_id, 2)):
        annotations += [(71, [identifier, 34, 0]), (71, [identifier, 33, binding])]
        declarations.append((59, [data_pointer, identifier, 2]))
    small_length, small_guard, both_small, output_guard, merge, body = [new() for _ in range(6)]
    inserted = [(68, [uint, small_length, short_id, 0]),
                (176, [boolean, small_guard, gid, small_length]),
                (167, [boolean, both_small, logical_guard, small_guard]),
                (176, [boolean, output_guard, gid, constant(local_size)]),
                (247, [merge, 0]), (250, [output_guard, body, merge]), (248, [body])]
    base = new()
    inserted.append((132, [uint, base, gid, constant(RECORD_WORDS)]))
    def as_uint(condition):
        identifier = new()
        inserted.append((169, [uint, identifier, condition, one, zero]))
        return identifier
    marker = new()
    inserted.append((198, [uint, marker, gid, constant(0xA5A55A5A)]))
    values = [constant(MAGIC), gid, logical, length_id, small_length,
              as_uint(logical_guard), as_uint(length_guard), as_uint(large_guard),
              as_uint(small_guard), as_uint(both_small), marker, one]
    for offset, value in enumerate(values):
        index, pointer = new(), new()
        inserted += [(128, [uint, index, base, constant(offset)]),
                     (65, [word_pointer, pointer, output_id, zero, index]), (62, [pointer, value])]
    inserted += [(249, [merge]), (248, [merge])]
    output, decorated, declared, instrumented = [], False, False, False
    for op, operands in ops:
        if op == 19 and not decorated:
            output.extend(annotations); decorated = True
        if op == 54 and not declared:
            output.extend(declarations); declared = True
        if op == 247 and not instrumented:
            output.extend(inserted); instrumented = True
        output.append((op, operands))
    if not (decorated and declared and instrumented):
        raise ValueError("production module layout changed")
    header[3] = next_id
    words = header + [word for op, operands in output for word in p._inst(op, operands)]
    p.validate_generated_compute_spirv_structure(words)
    return struct.pack(f"<{len(words)}I", *words)


def decode_observations(raw, local_size):
    if type(local_size) is not int or not 2 <= local_size <= 256 or len(raw) != OUTPUT_BYTES:
        raise ValueError("incomplete independent readback")
    records = [list(struct.unpack_from("<12I", raw, i*48)) for i in range(local_size)]
    for i, row in enumerate(records):
        if row[0] != MAGIC or row[1] != i or row[10:] != [i ^ 0xA5A55A5A, 1]:
            raise ValueError("independent output marker/index missing or contradictory")
        if any(row[k] not in (0, 1) for k in range(5, 10)):
            raise ValueError("invalid guard observation")
        if row[5:10] != [int(i < row[2]), int(i < row[3]), int(i < row[2] and i < row[3]),
                         int(i < row[4]), int(i < row[2] and i < row[4])]:
            raise ValueError("guard decisions contradict shader-observed values")
        if row[2:5] != records[0][2:5]:
            raise ValueError("bounds differ between probe invocations")
    word1 = struct.unpack_from("<I", raw, OUTPUT_BYTES-4)[0]
    row = records[1]
    if not row[7] and word1 != 0:
        conclusion = "guard_execution_discrepancy"
    elif row[2] != LOGICAL_WORDS:
        conclusion = "push_constant_discrepancy"
    elif row[3] != LARGE_BYTES//4 and row[4] == SMALL_BYTES//4:
        conclusion = "large_range_array_length_discrepancy"
    elif row[3:5] != [LARGE_BYTES//4, SMALL_BYTES//4]:
        conclusion = "descriptor_array_length_discrepancy"
    elif word1 != p.expected_word(1, 7, 0, "stateful_memory"):
        conclusion = "execution_or_visibility_mismatch"
    else:
        conclusion = "expected_values_observed"
    return dict(invocation_records=records, word1=dict(logical_words=row[2], large_array_words=row[3],
        small_array_words=row[4], logical_guard=bool(row[5]), large_length_guard=bool(row[6]),
        large_combined_guard=bool(row[7]), small_length_guard=bool(row[8]),
        small_combined_guard=bool(row[9]), production_value=word1), conclusion=conclusion)


def execute_probe(args, state):
    """One workgroup, one large allocation, no stress loop or allocation ramp."""
    vk, device = None, None
    cleanup, errors, claims = [], [], RuntimeMemoryClaims()
    def keep(function, handle, parent=True):
        cleanup.append(lambda: getattr(vk, function)(device, handle, None) if parent
                       else getattr(vk, function)(handle, None))
    try:
        vk = p.load_vulkan(p.resolve_vulkan_library())
        p.extend_vulkan_prototypes(vk)
        instance = p.make_instance(vk); keep("vkDestroyInstance", instance, False)
        infos = [(p.parse_properties(vk, h, i), h) for i, h in enumerate(p.enumerate_devices(vk, instance))]
        _, info, physical = p.select_physical_device(infos, args)
        if info.get("vendor_id") != "10de":
            raise RuntimeError("diagnostic is restricted to authoritatively identified NVIDIA devices")
        state["physical_identity_evidence"] = p.native_identity_evidence(info, args)
        state["selected_device"] = info
        if info.get("max_storage_buffer_range_bytes", 0) < LARGE_BYTES:
            raise RuntimeError("3 GiB descriptor exceeds reported device limit")
        local = p.select_compute_local_size(info.get("max_compute_work_group_invocations", 0),
                                            info.get("max_compute_work_group_size", []))
        if local < 2 or local*RECORD_WORDS*4 > OUTPUT_BYTES-4:
            raise RuntimeError("insufficient diagnostic workgroup/output capacity")
        state["local_size"] = local
        if runtime_memory_stop_required() or not claims.claim(CLAIM_BYTES, shared_system_memory=True).get("allowed"):
            raise RuntimeError("runtime memory guard denied diagnostic allocation")
        family, _ = p.compute_queue_family_details(vk, physical)
        priority = C.c_float(1.)
        qi = p.VkDeviceQueueCreateInfo(p.VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, None, 0, family, 1, C.pointer(priority))
        di = p.VkDeviceCreateInfo(p.VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, None, 0, 1, C.pointer(qi), 0, None, 0, None, None)
        device = C.c_void_p(); p.check(vk.vkCreateDevice(physical, C.byref(di), None, C.byref(device)), "vkCreateDevice")
        keep("vkDestroyDevice", device, False)
        queue = C.c_void_p(); vk.vkGetDeviceQueue(device, family, 0, C.byref(queue))
        memory = t.VkPhysicalDeviceMemoryProperties(); vk.vkGetPhysicalDeviceMemoryProperties(physical, C.byref(memory))
        large, lm, lb, _ = p.create_buffer(vk, device, memory, LARGE_BYTES,
            p.VK_BUFFER_USAGE_STORAGE_BUFFER_BIT|p.VK_BUFFER_USAGE_TRANSFER_SRC_BIT|p.VK_BUFFER_USAGE_TRANSFER_DST_BIT,
            p.VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)
        keep("vkFreeMemory", lm); keep("vkDestroyBuffer", large)
        out, om, ob, _ = p.create_buffer(vk, device, memory, OUTPUT_BYTES,
            p.VK_BUFFER_USAGE_STORAGE_BUFFER_BIT|p.VK_BUFFER_USAGE_TRANSFER_DST_BIT,
            p.VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|p.VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)
        keep("vkFreeMemory", om); keep("vkDestroyBuffer", out)
        if lb+ob > CLAIM_BYTES:
            raise RuntimeError("diagnostic allocation requirements exceed protected budget")
        state["allocations"] = dict(large_buffer_bytes=LARGE_BYTES, large_requirement_bytes=lb,
            independent_output_bytes=OUTPUT_BYTES, output_requirement_bytes=ob,
            conservative_system_memory_claim_bytes=CLAIM_BYTES,
            physical_residency="not_established", initialized_data_bytes=local*4)
        blob = diagnostic_shader(local)
        state["shader_sha256"] = hashlib.sha256(blob).hexdigest()
        words = (C.c_uint32*(len(blob)//4)).from_buffer_copy(blob)
        si = p.VkShaderModuleCreateInfo(p.VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, None, 0, len(blob), words)
        shader = C.c_void_p(); p.check(vk.vkCreateShaderModule(device, C.byref(si), None, C.byref(shader)), "vkCreateShaderModule")
        keep("vkDestroyShaderModule", shader)
        bindings = (p.VkDescriptorSetLayoutBinding*3)(*[p.VkDescriptorSetLayoutBinding(i, p.VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, p.VK_SHADER_STAGE_COMPUTE_BIT, None) for i in range(3)])
        li = p.VkDescriptorSetLayoutCreateInfo(p.VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, None, 0, 3, bindings)
        layout = C.c_void_p(); p.check(vk.vkCreateDescriptorSetLayout(device, C.byref(li), None, C.byref(layout)), "vkCreateDescriptorSetLayout")
        keep("vkDestroyDescriptorSetLayout", layout)
        layouts = (C.c_void_p*1)(layout); push_range = p.VkPushConstantRange(p.VK_SHADER_STAGE_COMPUTE_BIT, 0, 8)
        pi = p.VkPipelineLayoutCreateInfo(p.VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, None, 0, 1, layouts, 1, C.cast(C.pointer(push_range), C.c_void_p))
        pipeline_layout = C.c_void_p(); p.check(vk.vkCreatePipelineLayout(device, C.byref(pi), None, C.byref(pipeline_layout)), "vkCreatePipelineLayout")
        keep("vkDestroyPipelineLayout", pipeline_layout)
        stage = p.VkPipelineShaderStageCreateInfo(p.VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, None, 0, p.VK_SHADER_STAGE_COMPUTE_BIT, shader, b"main", None)
        ci = p.VkComputePipelineCreateInfo(p.VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, None, 0, stage, pipeline_layout, None, -1)
        pipeline = C.c_void_p(); p.check(vk.vkCreateComputePipelines(device, None, 1, C.byref(ci), None, C.byref(pipeline)), "vkCreateComputePipelines")
        keep("vkDestroyPipeline", pipeline)
        pool_size = p.VkDescriptorPoolSize(p.VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 3)
        dpi = p.VkDescriptorPoolCreateInfo(p.VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, None, 0, 1, 1, C.pointer(pool_size))
        pool = C.c_void_p(); p.check(vk.vkCreateDescriptorPool(device, C.byref(dpi), None, C.byref(pool)), "vkCreateDescriptorPool")
        keep("vkDestroyDescriptorPool", pool)
        ai = p.VkDescriptorSetAllocateInfo(p.VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, None, pool, 1, layouts)
        ds = (C.c_void_p*1)(); p.check(vk.vkAllocateDescriptorSets(device, C.byref(ai), ds), "vkAllocateDescriptorSets")
        for i, (buffer, size) in enumerate(((large, LARGE_BYTES), (large, SMALL_BYTES), (out, OUTPUT_BYTES))):
            bi = p.VkDescriptorBufferInfo(buffer, 0, size)
            write = p.VkWriteDescriptorSet(p.VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, None, ds[0], i, 0, 1, p.VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, None, C.pointer(bi), None)
            vk.vkUpdateDescriptorSets(device, 1, C.byref(write), 0, None)
        cpi = p.VkCommandPoolCreateInfo(p.VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, None, 0, family)
        cp = C.c_void_p(); p.check(vk.vkCreateCommandPool(device, C.byref(cpi), None, C.byref(cp)), "vkCreateCommandPool")
        keep("vkDestroyCommandPool", cp)
        cai = p.VkCommandBufferAllocateInfo(p.VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, None, cp, p.VK_COMMAND_BUFFER_LEVEL_PRIMARY, 1)
        cmd = C.c_void_p(); p.check(vk.vkAllocateCommandBuffers(device, C.byref(cai), C.byref(cmd)), "vkAllocateCommandBuffers")
        fi = p.VkFenceCreateInfo(p.VK_STRUCTURE_TYPE_FENCE_CREATE_INFO, None, 0)
        fence = C.c_void_p(); p.check(vk.vkCreateFence(device, C.byref(fi), None, C.byref(fence)), "vkCreateFence")
        keep("vkDestroyFence", fence)
        begin = p.VkCommandBufferBeginInfo(p.VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, None, 0, None)
        p.check(vk.vkBeginCommandBuffer(cmd, C.byref(begin)), "vkBeginCommandBuffer")
        def barrier(buffer, size, src_access, dst_access, src_stage, dst_stage):
            b = p.VkBufferMemoryBarrier(p.VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER, None, src_access, dst_access,
                p.VK_QUEUE_FAMILY_IGNORED, p.VK_QUEUE_FAMILY_IGNORED, buffer, 0, size)
            vk.vkCmdPipelineBarrier(cmd, src_stage, dst_stage, 0, 0, None, 1, C.byref(b), 0, None)
        vk.vkCmdFillBuffer(cmd, large, 0, local*4, 0)
        vk.vkCmdFillBuffer(cmd, out, 0, OUTPUT_BYTES, 0xCDCDCDCD)
        for buffer, size in ((large, local*4), (out, OUTPUT_BYTES)):
            barrier(buffer, size, p.VK_ACCESS_TRANSFER_WRITE_BIT, p.VK_ACCESS_SHADER_READ_BIT|p.VK_ACCESS_SHADER_WRITE_BIT|p.VK_ACCESS_TRANSFER_WRITE_BIT,
                p.VK_PIPELINE_STAGE_TRANSFER_BIT, p.VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT|p.VK_PIPELINE_STAGE_TRANSFER_BIT)
        vk.vkCmdBindPipeline(cmd, p.VK_PIPELINE_BIND_POINT_COMPUTE, pipeline)
        vk.vkCmdBindDescriptorSets(cmd, p.VK_PIPELINE_BIND_POINT_COMPUTE, pipeline_layout, 0, 1, ds, 0, None)
        logical = p.dispatch_bounds_constants(LOGICAL_WORDS, LARGE_BYTES)
        vk.vkCmdPushConstants(cmd, pipeline_layout, p.VK_SHADER_STAGE_COMPUTE_BIT, 0, C.sizeof(logical), C.byref(logical))
        vk.vkCmdDispatch(cmd, 1, 1, 1)
        barrier(large, local*4, p.VK_ACCESS_SHADER_WRITE_BIT, p.VK_ACCESS_TRANSFER_READ_BIT,
                p.VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, p.VK_PIPELINE_STAGE_TRANSFER_BIT)
        region = p.VkBufferCopy(4, OUTPUT_BYTES-4, 4)
        vk.vkCmdCopyBuffer(cmd, large, out, 1, C.byref(region))
        barrier(out, OUTPUT_BYTES, p.VK_ACCESS_SHADER_WRITE_BIT|p.VK_ACCESS_TRANSFER_WRITE_BIT, p.VK_ACCESS_HOST_READ_BIT,
                p.VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT|p.VK_PIPELINE_STAGE_TRANSFER_BIT, p.VK_PIPELINE_STAGE_HOST_BIT)
        p.check(vk.vkEndCommandBuffer(cmd), "vkEndCommandBuffer")
        if runtime_memory_stop_required(): raise RuntimeError("runtime memory guard stopped diagnostic before submission")
        commands = (C.c_void_p*1)(cmd); fences = (C.c_void_p*1)(fence)
        submit = p.VkSubmitInfo(4, None, 0, None, None, 1, commands, 0, None)
        p.check(vk.vkQueueSubmit(queue, 1, C.byref(submit), fence), "vkQueueSubmit")
        p.check(vk.vkWaitForFences(device, 1, fences, p.VK_TRUE, 5_000_000_000), "vkWaitForFences")
        mapped = C.c_void_p(); p.check(vk.vkMapMemory(device, om, 0, OUTPUT_BYTES, 0, C.byref(mapped)), "vkMapMemory")
        try: raw = C.string_at(mapped, OUTPUT_BYTES)
        finally: vk.vkUnmapMemory(device, om)
        try:
            state["observations"] = decode_observations(raw, local)
        except ValueError:
            # Preserve bounded rejected observations, never turn missing markers
            # into affirmative query/ABI evidence.
            state["invalid_readback_words"] = list(struct.unpack(f"<{OUTPUT_BYTES//4}I", raw))
            raise
        state["status"] = "observed"
    except BaseException as exc:
        state.update(status="error", error=f"{type(exc).__name__}: {exc}")
    finally:
        if vk and device:
            try: p.check(vk.vkDeviceWaitIdle(device), "vkDeviceWaitIdle")
            except Exception as exc: errors.append(str(exc))
        for release in reversed(cleanup):
            try: release()
            except Exception as exc: errors.append(str(exc))
        if not errors: claims.close()
        state.update(cleanup_complete=not errors and not claims.cleanup_error,
                     cleanup_errors=errors, allocation_claim_cleanup_error=claims.cleanup_error,
                     outstanding_system_memory_claim_bytes=claims.outstanding)
        if errors or claims.cleanup_error: state["status"] = "error"


def supervise(process, plan, *, clock=time.monotonic, sleep=time.sleep):
    deadline, reason = clock()+30., ""
    try:
        while process.poll() is None:
            memory = read_linux_memory_snapshot()
            guard = update_runtime_memory_guard(plan, runtime_mem_available_bytes=memory.get("mem_available_bytes", 0),
                timestamp=datetime.now().astimezone().isoformat(), affected_workers=["startup_diagnostic"])
            if guard.get("stage_termination_required") or clock() >= deadline:
                reason = "memory_guard" if guard.get("stage_termination_required") else "deadline"
                break
            sleep(.5)
    except KeyboardInterrupt:
        reason = "interrupted"
    except Exception as exc:
        reason = "monitor_error:"+type(exc).__name__
    if reason:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)
    return reason


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="explicitly authorize this one-workgroup NVIDIA diagnostic")
    parser.add_argument("--target-slot", required=True)
    parser.add_argument("--target-device-uuid", required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--result-dir", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.run or not canonical_pci_slot(args.target_slot) or not normalize_device_uuid(args.target_device_uuid):
        parser.error("--run, an exact PCI slot and an independently known NVIDIA UUID are required")
    args.target_slot = canonical_pci_slot(args.target_slot)
    args.target_device_uuid = normalize_device_uuid(args.target_device_uuid)
    state = dict(contract_id=CONTRACT, contract_version=1, kind="startup_diagnostic", diagnostic_only=True,
        worker_pid=os.getpid(),
        status="starting", stress_acceptance="not_assessed", expected=dict(logical_words=LOGICAL_WORDS,
        large_array_words=LARGE_BYTES//4, small_array_words=SMALL_BYTES//4,
        word1=p.expected_word(1, 7, 0, "stateful_memory")),
        dispatch_groups=[1,1,1], reference_production_groups=[1101009,1,1],
        descriptor_offsets=[0,0,0], descriptor_ranges=[LARGE_BYTES,SMALL_BYTES,OUTPUT_BYTES])
    if args.worker:
        directory = Path(args.result_dir).resolve()
        directory.relative_to((ROOT/"results").resolve())
        manifest = json.loads((directory/"diagnostic_manifest.json").read_text())
        if (manifest.get("contract_id") != CONTRACT or type(manifest.get("contract_version")) is not int
                or manifest["contract_version"] != 1 or manifest.get("diagnostic_only") is not True
                or manifest.get("target_slot") != args.target_slot
                or manifest.get("target_uuid") != args.target_device_uuid
                or (directory/"diagnostic_result.json").exists()):
            raise RuntimeError("invalid, mismatched or previously completed diagnostic directory")
        args.target_vendor_id, args.target_vendor, args.target_device_id = "10de", "NVIDIA", ""
        args.target_device_name, args.device_class, args.target_id = "", "", args.target_slot
        args.physical_gpu_id = "pci:"+args.target_slot
        def stop(*_): raise InterruptedError("diagnostic cancelled")
        signal.signal(signal.SIGTERM, stop)
        execute_probe(args, state)
        _write_json_atomic(directory/"diagnostic_result.json", state)
        return 0 if state["status"] == "observed" else 1
    memory = read_linux_memory_snapshot()
    plan = system_memory_budget_bytes(memory.get("mem_total_bytes", 0), memory.get("mem_available_bytes", 0))
    (ROOT/"results").mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix=datetime.now().strftime("%Y-%m-%d_%H-%M-%S_Vulkan_Bounds_Startup_"), dir=ROOT/"results"))
    manifest = dict(contract_id=CONTRACT, contract_version=1, diagnostic_only=True, started=datetime.now().astimezone().isoformat(),
        target_slot=args.target_slot, target_uuid=args.target_device_uuid, source_provenance=collect_source_provenance(ROOT))
    manifest["system_memory_plan"] = dict(plan)
    _write_json_atomic(directory/"diagnostic_manifest.json", manifest)
    if plan["system_memory_budget_bytes"] < CLAIM_BYTES:
        state.update(status="blocked", error="insufficient system-memory headroom for conservatively protected diagnostic",
                     worker_launched=False, cleanup_complete=True, outstanding_system_memory_claim_bytes=0)
        manifest.update(diagnostic_status="blocked", worker_launched=False,
                        source_changed_during_run=None, ended=datetime.now().astimezone().isoformat())
        _write_json_atomic(directory/"diagnostic_result.json", state)
        _write_json_atomic(directory/"diagnostic_manifest.json", manifest)
        print(directory.relative_to(ROOT)); print("Diagnostic blocked:", state["error"])
        return 1
    plan["consumers"] = [dict(consumer_id="startup_diagnostic", requested_bytes=CLAIM_BYTES)]
    initialize_runtime_memory_guard(plan, directory/"runtime_memory_guard.json")
    env = dict(os.environ, LVS_RUNTIME_MEMORY_GUARD_PATH=str(directory/"runtime_memory_guard.json"))
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "--run", "--worker", "--result-dir", str(directory),
               "--target-slot", args.target_slot, "--target-device-uuid", args.target_device_uuid]
    with (directory/"stdout.log").open("w") as stdout, (directory/"stderr.log").open("w") as stderr:
        try:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stdout, stderr=stderr)
            manifest["worker_pid"] = process.pid
            manifest["stop_reason"] = supervise(process, plan)
            manifest["exit_code"] = process.wait(timeout=5)
        except Exception as exc:
            manifest["supervisor_error"] = f"{type(exc).__name__}: {exc}"
    manifest.update(ended=datetime.now().astimezone().isoformat(), source_provenance_end=collect_source_provenance(ROOT))
    change = source_identity(manifest["source_provenance"], end=manifest["source_provenance_end"])["change_status"]
    manifest["source_changed_during_run"] = {"unchanged_endpoints": False, "changed": True}.get(change)
    try:
        result = json.loads((directory/"diagnostic_result.json").read_text())
        if (result.get("contract_id") != CONTRACT or result.get("worker_pid") != manifest.get("worker_pid")
                or result.get("cleanup_complete") is not True):
            raise ValueError("missing or contradictory terminal evidence")
        manifest["diagnostic_status"] = result.get("status")
        manifest["conclusion"] = result.get("observations", {}).get("conclusion", "unavailable")
    except (OSError, ValueError, TypeError) as exc:
        manifest["diagnostic_status"] = "incomplete"
        manifest["terminal_evidence_error"] = type(exc).__name__
    _write_json_atomic(directory/"diagnostic_manifest.json", manifest)
    print(directory.relative_to(ROOT))
    print("Diagnostic:", manifest["diagnostic_status"], manifest.get("conclusion", "unavailable"), "(not a stress PASS)")
    return 0 if (manifest.get("exit_code") == 0 and not manifest.get("stop_reason")
                 and manifest.get("diagnostic_status") == "observed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
