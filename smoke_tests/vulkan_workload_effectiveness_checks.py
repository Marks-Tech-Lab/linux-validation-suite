#!/usr/bin/env python3
"""Deterministic Vulkan workload-effectiveness and instrumentation checks."""

from __future__ import annotations

import ctypes
import ast
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native"
if str(NATIVE) not in sys.path:
    sys.path.insert(0, str(NATIVE))

from vulkan_compute_worker import (  # noqa: E402
    VkQueryPoolCreateInfo,
    compute_dispatch_dimensions,
    compute_shader_spirv,
    configure_optional_timestamp_query_prototypes,
    next_submission_batch_iterations,
    select_compute_local_size,
    timed_action_due,
    validate_generated_compute_spirv_structure,
)
from vulkan_transfer_worker import parse_properties  # noqa: E402

from Modules.lvs_compat_export_gpu import build_gpu_worker_validation_detail
from Modules.lvs_gpu_worker_params import (
    vulkan_compute_dispatch_repeats,
    vulkan_compute_rounds,
)
from Modules.lvs_profile_loader import ProfileLoader
from Modules.lvs_profile_validation import ProfileValidator
from Modules.lvs_segment_gpu_worker_summary import GpuWorkerStateSummaryBuilder
from Modules.lvs_worker_integrity import worker_result_successful


def _worker_payload() -> dict:
    return {
        "kind": "gpu",
        "mode": "gpu_3d",
        "backend": "python_vulkan_compute",
        "worker_version": "vulkan_compute_stress_hash_v8",
        "kernel_variant": "stress_hash",
        "workload_purpose": "compute_stress_candidate",
        "suite_verification": "compute_readback",
        "status": "ok",
        "verification_passes": 12,
        "verification_readback_count": 12,
        "initial_verification_completed": True,
        "final_verification_completed": True,
        "compute_mismatch_count": 0,
        "saturation_result": False,
        "power_saturation_expected": False,
        "compute_rounds": 160,
        "effective_compute_rounds": 160,
        "dependent_compute_rounds": 160,
        "independent_dispatch_repetitions": 48,
        "queue_submission_count": 100,
        "compute_dispatch_count": 4800,
        "command_buffer_record_count": 14,
        "command_buffer_reuse_count": 86,
        "fence_wait_elapsed_seconds": 7.5,
        "result_write_count": 9,
        "worker_cpu_seconds": 0.8,
        "submission_batch_iterations": 8,
        "submission_batch_iterations_max": 8,
        "workgroup_local_size": [256, 1, 1],
        "dispatch_group_count": [49152, 2, 1],
        "gpu_timestamp_status": "measured",
        "gpu_timestamp_reason": "queue_timestamp_queries_supported",
        "gpu_timestamp_elapsed_seconds": 7.2,
        "startup_checkpoint": "initial_hardware_readback_completed",
        "startup_complete": True,
        "fault_diagnostics_enabled": True,
    }


def run_vulkan_padded_dispatch_checks() -> None:
    """Interpret emitted shader control flow, indexing and memory operations.

    This is a deliberately limited SPIR-V interpreter, not a driver/compiler
    or a complete SPIR-V validator. Unknown function instructions fail tests.
    """
    import vulkan_compute_worker as worker

    def decode(blob):
        words = struct.unpack(f"<{len(blob)//4}I", blob)
        result, offset = [], 5
        while offset < len(words):
            count, op = words[offset] >> 16, words[offset] & 65535
            result.append((op, words[offset+1:offset+count]))
            offset += count
        return result

    def execute(program, dims, invocation, logical_words, buffer_words, seed):
        x, y, _z = dims
        row = x * local
        globals_ = (invocation % row, (invocation // row) % y, invocation // (row * y))
        values, builtins, reads, writes = {}, {}, [], []
        labels = {args[0]: i for i, (op, args) in enumerate(program) if op == 248}
        function_start = 0
        for i, (op, args) in enumerate(program):
            if op == 71 and args[1] == 11: builtins[args[0]] = args[2]
            if op == 43: values[args[1]] = args[2]
            if op == 59:
                values[args[1]] = ("input", builtins[args[1]]) if args[2] == 1 else ("buffer" if args[2] == 2 else "push",)
            if op == 54:
                function_start = i + 1
                break
        pc = function_start
        while True:
            op, a = program[pc]
            pc += 1
            if op in (248, 247): continue
            if op == 253: return reads, writes
            if op == 249: pc = labels[a[0]]; continue
            if op == 250: pc = labels[a[1] if values[a[0]] else a[2]]; continue
            if op == 61:
                pointer = values[a[2]]
                if pointer[0] == "input": value = globals_ if pointer[1] == 28 else dims
                elif pointer[0] == "push": value = (logical_words, buffer_words)[pointer[1]]
                else:
                    index = pointer[1]
                    assert 0 <= index < buffer_words
                    reads.append(index); value = seed(index)
                values[a[1]] = value
            elif op == 81: values[a[1]] = values[a[2]][a[3]]
            elif op == 65:
                base = values[a[2]]
                if base[0] == "buffer":
                    assert values[a[3]] == 0
                    index = values[a[4]]
                    assert 0 <= index < buffer_words, "out-of-bounds pointer formed"
                    values[a[1]] = ("buffer", index)
                else:
                    member = [values[index] for index in a[3:]]
                    assert member in ([0], [1])
                    values[a[1]] = ("push", member[0])
            elif op == 68:
                assert values[a[2]] == ("buffer",) and a[3] == 0
                values[a[1]] = buffer_words
            elif op in (128, 132, 194, 198, 176, 167):
                left, right = values[a[2]], values[a[3]]
                value = {128: lambda: left+right, 132: lambda: left*right,
                         194: lambda: left >> right, 198: lambda: left ^ right,
                         176: lambda: left < right, 167: lambda: left and right}[op]()
                values[a[1]] = value if op in (176, 167) else value & 0xFFFFFFFF
            elif op == 62:
                pointer = values[a[0]]
                assert pointer[0] == "buffer" and 0 <= pointer[1] < buffer_words
                writes.append((pointer[1], values[a[1]]))
            else: raise AssertionError(f"unhandled emitted function instruction {op}")

    cases = [(17, 1, [8, 3, 1]), (7*4, 4, [2, 2, 2]), (17*4-1, 4, [4, 3, 2]),
             (65535*256, 256, [65535]*3), (65536*256, 256, [65535]*3),
             (71453*256, 256, [65535]*3), (25_165_824, 256, [65535]*3),
             (805_306_368, 256, [2147483647, 65535, 65535]),
             (0xFFFFFFFF, 1, [0xFFFFFFFF, 1, 1]), (0xFFFFFFFF, 256, [65535]*3)]
    for count, local, limits in cases:
        gx, gy, gz, credited = compute_dispatch_dimensions(count, local, limits)
        assert credited == count
        assert all(0 < n <= cap for n, cap in zip((gx, gy, gz), limits))
        scheduled = gx*gy*gz*local
        assert count <= scheduled <= 1 << 32
        for variant in ("hash", "stress_hash", "stateful_memory"):
            program = decode(compute_shader_spirv(2, variant, local))
            row, plane = gx*local, gx*gy*local
            probes = range(scheduled) if scheduled < 100 else sorted(i for i in {
                0, count-1, count, scheduled-1, row-1, row, row+1, plane-1, plane, plane+1}
                if 0 <= i < scheduled)
            all_writes = []
            seed = lambda i: (i*17+3) & 0xFFFFFFFF
            buffer_words = min(0xFFFFFFFF, count+2)
            for invocation in probes:
                reads, writes = execute(program, (gx, gy, gz), invocation, count, buffer_words, seed)
                assert len(writes) == int(invocation < count)
                if writes:
                    assert writes == [(invocation, worker.expected_word(invocation, 2, seed(invocation), variant))]
                    assert reads == ([invocation] if variant == "stateful_memory" else [])
                else: assert not reads
                all_writes.extend(index for index, _ in writes)
            assert len(all_writes) == len(set(all_writes))
            if scheduled < 100: assert sorted(all_writes) == list(range(count))
            # An erroneous oversized logical bound cannot bypass descriptor bounds.
            reads, writes = execute(program, (gx, gy, gz), count-1, count, count-1, seed)
            assert not reads and not writes
    # Physical NVIDIA reproduction: the former OpArrayLength returned zero
    # for a 3 GiB descriptor. Production must emit no query, and must execute
    # word 1 using the independently validated two-word host bounds instead.
    local = 256
    program = decode(compute_shader_spirv(7, "stateful_memory", local))
    assert not any(op == 68 for op, _ in program)
    reads, writes = execute(program, (1101009, 1, 1), 1,
                            281858304, 805306368, lambda _: 0)
    assert reads == [1] and writes == [(1, 1003605230)]
    assert tuple(worker.dispatch_bounds_constants(281858304, 3*1024**3)) == (281858304, 805306368)
    for logical, size in ((0, 4), (2, 4), (1, 3), (1, 0), (1, 1 << 34), (True, 4)):
        try: worker.dispatch_bounds_constants(logical, size)
        except RuntimeError: pass
        else: raise AssertionError("invalid descriptor/dispatch bounds accepted")
    # Descriptor range is bound from the exact same record as the pushed
    # capacity, rather than the possibly larger VkMemoryRequirements size.
    host_tree = ast.parse((NATIVE / "vulkan_compute_worker.py").read_text())
    descriptor = next(n for n in ast.walk(host_tree) if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "buffer_info" for t in n.targets))
    record = {"buffer": ctypes.c_void_p(99), "size": 3*1024**3}
    env_descriptor = dict(VkDescriptorBufferInfo=worker.VkDescriptorBufferInfo, record=record)
    exec(compile(ast.Module(body=[descriptor], type_ignores=[]), "<descriptor>", "exec"), env_descriptor)
    assert env_descriptor["buffer_info"].range == record["size"]
    assert compute_dispatch_dimensions(805_306_368, 256, [2147483647, 65535, 65535]) == (
        3_145_728, 1, 1, 805_306_368)
    for bad in [(0, 256, [65535]*3), (1 << 32, 256, [65535]*3),
                (17, 1, [2, 2, 2]), (100, 0, [65535]*3), (100, 1, [0, 1, 1]),
                (0xFFFFFFFF, 7, [0xFFFFFFFF]*3)]:
        try: compute_dispatch_dimensions(*bad)
        except RuntimeError: pass
        else: raise AssertionError("invalid/overflowing dispatch accepted")

    # Execute the production command-recording statements with the real ctypes
    # ABI: shader push member offset/size and the host logical count must agree.
    tree = ast.parse((NATIVE / "vulkan_compute_worker.py").read_text())
    push_call = next(n for n in ast.walk(tree) if isinstance(n, ast.Expr)
                     and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
                     and n.value.func.attr == "vkCmdPushConstants")
    calls = []
    class Vk:
        def vkCmdPushConstants(self, _cmd, _layout, flags, offset, size, ptr):
            calls.append((flags, offset, size, tuple(ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint32 * 2)).contents)))
    def assignment(name):
        return next(n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
    env = dict(vk=Vk(), command_buffer=1, pipeline_layout=2, VK_SHADER_STAGE_COMPUTE_BIT=32,
               ctypes=ctypes, active_words=71453*256, active_record={"size": 3*1024**3},
               dispatch_bounds_constants=worker.dispatch_bounds_constants,
               VkPushConstantRange=worker.VkPushConstantRange,
               VkPipelineLayoutCreateInfo=worker.VkPipelineLayoutCreateInfo,
               VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO=worker.VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
               VK_NULL_HANDLE=worker.VK_NULL_HANDLE, set_layouts=(ctypes.c_void_p*1)(1))
    body = [assignment("push_range"), assignment("pipeline_layout_info"), assignment("logical_words"), push_call]
    exec(compile(ast.Module(body=body, type_ignores=[]), "<actual-push-command>", "exec"), env)
    assert calls == [(32, 0, 8, (71453*256, 805306368))]
    assert ctypes.sizeof(worker.VkPushConstantRange) == 12
    info = env["pipeline_layout_info"]
    assert info.pushConstantRangeCount == 1
    bound_range = ctypes.cast(info.pPushConstantRanges, ctypes.POINTER(worker.VkPushConstantRange)).contents
    assert (bound_range.stageFlags, bound_range.offset, bound_range.size) == (32, 0, 8)


def run_vulkan_workload_effectiveness_checks() -> None:
    # Legal geometry follows the device limits and uses a second dimension
    # without issuing invocations past the allocated buffer.
    assert select_compute_local_size(1024, [1024, 1024, 64]) == 256
    assert select_compute_local_size(128, [64, 64, 64]) == 64
    assert compute_dispatch_dimensions(25_165_824, 256, [65_535, 65_535, 65_535]) == (
        49_152,
        2,
        1,
        25_165_824,
    )
    assert compute_dispatch_dimensions(24 * 256, 256, [4, 3, 2]) == (4, 3, 2, 24 * 256)
    assert compute_dispatch_dimensions(17 * 256, 256, [8, 3, 1]) == (6, 3, 1, 17 * 256)

    # The shader advertises the selected local size and supports linearized
    # two-dimensional workgroups; generated variants remain valid SPIR-V blobs.
    for variant in ("hash", "stress_hash", "stateful_memory"):
        blob = compute_shader_spirv(16, variant, 128)
        assert blob[:4] == b"\x03\x02\x23\x07"
        assert struct.pack("<I", 128) in blob

        # Module declarations, including the selected-local-size constant,
        # must precede OpFunction.  The physically observed NVIDIA crash was
        # triggered by handing the driver a constant in the function section.
        words = list(struct.unpack(f"<{len(blob) // 4}I", blob))
        validate_generated_compute_spirv_structure(words)
        function_word = next(
            index for index in range(5, len(words)) if (words[index] & 0xFFFF) == 54
        )
        invalid_words = words[: function_word + 5] + [0x0004002B, 3, words[3], 1] + words[function_word + 5 :]
        invalid_words[3] += 1
        try:
            validate_generated_compute_spirv_structure(invalid_words)
        except RuntimeError as exc:
            assert "after OpFunction" in str(exc)
        else:
            raise AssertionError("late SPIR-V constant must fail before Vulkan pipeline creation")

    # The query-pool ABI is stable on the supported 64-bit hosts, and missing
    # optional entry points disable timestamps without blocking compute.
    assert ctypes.sizeof(VkQueryPoolCreateInfo) == 32
    assert VkQueryPoolCreateInfo.pNext.offset == 8
    assert VkQueryPoolCreateInfo.flags.offset == 16
    assert VkQueryPoolCreateInfo.pipelineStatistics.offset == 28

    class MissingTimestampFunctions:
        pass

    assert not configure_optional_timestamp_query_prototypes(MissingTimestampFunctions())

    class FakeFunction:
        argtypes = None
        restype = None

    class TimestampFunctions:
        vkCreateQueryPool = FakeFunction()
        vkDestroyQueryPool = FakeFunction()
        vkCmdResetQueryPool = FakeFunction()
        vkCmdWriteTimestamp = FakeFunction()
        vkGetQueryPoolResults = FakeFunction()

    timestamp_functions = TimestampFunctions()
    assert configure_optional_timestamp_query_prototypes(timestamp_functions)
    assert timestamp_functions.vkCreateQueryPool.restype is ctypes.c_int32
    assert timestamp_functions.vkGetQueryPoolResults.restype is ctypes.c_int32

    # Batching is bounded, ramp-aware, and responds conservatively to measured
    # batch latency without relying on a utilization target.
    assert next_submission_batch_iterations(1, 0.005, full_load=False) == 1
    assert next_submission_batch_iterations(1, 0.005, full_load=True) == 2
    assert next_submission_batch_iterations(8, 0.2, full_load=True) == 4
    assert next_submission_batch_iterations(8, 0.05, full_load=True) == 8

    # Verification and persistence cadence is elapsed-time based, including
    # explicit initial/final forcing; it is independent of frame rate.
    assert timed_action_due(0.0, 0.01, 0.75)
    assert not timed_action_due(10.0, 10.1, 0.75)
    assert timed_action_due(10.0, 10.75, 0.75)
    assert timed_action_due(10.0, 10.1, 0.75, required=True)

    # Compute intensity derives from capability evidence, not memory class or
    # dedicated-memory capacity. High-compute shared devices get the same
    # rounds/repetitions as an equivalent discrete capability fixture.
    shared = {"capability": {"device_class": "integrated", "compute_units": 48, "load_scale": 2.2}}
    discrete = {"capability": {"device_class": "discrete", "compute_units": 48, "load_scale": 2.2}}
    low_end = {"capability": {"device_class": "integrated", "compute_units": 8, "load_scale": 0.8}}
    shared_rounds = vulkan_compute_rounds(
        shared, profile_intensity_factor=1.0, normalized_variant="stress_hash", safe_mode_enabled=True
    )
    discrete_rounds = vulkan_compute_rounds(
        discrete, profile_intensity_factor=1.0, normalized_variant="stress_hash", safe_mode_enabled=True
    )
    assert shared_rounds == discrete_rounds == 160
    assert vulkan_compute_rounds(
        low_end, profile_intensity_factor=1.0, normalized_variant="stress_hash", safe_mode_enabled=True
    ) < shared_rounds
    assert vulkan_compute_dispatch_repeats(
        {"vram_total": 0}, normalized_variant="stress_hash", capability=shared["capability"]
    ) == 6
    assert vulkan_compute_dispatch_repeats(
        {"vram_total": 64 * 1024**3}, normalized_variant="stress_hash", capability=low_end["capability"]
    ) == 3

    # Core Vulkan property offsets preserve raw limit evidence, including
    # timestamp availability, without Python binding assumptions.
    raw = bytearray(8192)
    raw[8:12] = (0x10DE).to_bytes(4, "little")
    raw[16:20] = (1).to_bytes(4, "little")
    raw[20:24] = b"GPU\0"
    limits = 296
    for offset, value in zip((220, 224, 228), (65535, 32768, 1024)):
        raw[limits + offset : limits + offset + 4] = value.to_bytes(4, "little")
    raw[limits + 232 : limits + 236] = (1024).to_bytes(4, "little")
    for offset, value in zip((236, 240, 244), (1024, 1024, 64)):
        raw[limits + offset : limits + offset + 4] = value.to_bytes(4, "little")
    raw[limits + 420 : limits + 424] = (1).to_bytes(4, "little")
    struct.pack_into("<f", raw, limits + 424, 1.0)

    class FakeVulkan:
        def vkGetPhysicalDeviceProperties(self, _device, destination):
            ctypes.memmove(destination, bytes(raw), len(raw))

    properties = parse_properties(FakeVulkan(), ctypes.c_void_p(), 0)
    assert properties["max_compute_work_group_count"] == [65535, 32768, 1024]
    assert properties["max_compute_work_group_invocations"] == 1024
    assert properties["max_compute_work_group_size"] == [1024, 1024, 64]
    assert properties["timestamp_compute_and_graphics"] is True
    assert properties["timestamp_period_nanoseconds"] == 1.0

    # New verification completion fields are authoritative when present;
    # historical pass-count-only payloads retain compatibility.
    complete = _worker_payload()
    assert worker_result_successful(complete)
    incomplete = dict(complete, final_verification_completed=False)
    assert not worker_result_successful(incomplete)
    crashed_during_startup = dict(
        complete,
        status="initializing",
        startup_complete=False,
        verification_passes=0,
        verification_readback_count=0,
        initial_verification_completed=False,
        final_verification_completed=False,
    )
    assert not worker_result_successful(crashed_during_startup)
    legacy = {key: value for key, value in complete.items() if "verification_completed" not in key}
    assert worker_result_successful(legacy)

    detail = build_gpu_worker_validation_detail(
        stage_name="GPU",
        stage_type="3D Adaptive",
        stage_verdict="PASS",
        payload=complete,
        backend_name="python_vulkan_compute",
        device_name="GPU",
    )
    assert detail["WorkloadPurpose"] == "compute_stress_candidate"
    assert detail["SaturationResult"] is False
    assert detail["EffectiveComputeRounds"] == 160
    assert detail["IndependentDispatchRepetitions"] == 48
    assert detail["GpuTimestampStatus"] == "measured"
    assert detail["StartupCheckpoint"] == "initial_hardware_readback_completed"
    assert detail["StartupComplete"] is True
    summary = GpuWorkerStateSummaryBuilder().summary(SimpleNamespace(worker_results=[complete]))
    assert summary["Workers"][0]["QueueSubmissionCount"] == 100
    assert summary["Workers"][0]["FinalVerificationCompleted"] is True
    assert summary["Workers"][0]["StartupComplete"] is True

    profile_path = (
        ROOT
        / "profiles"
        / "Archived"
        / "2026 Hardware Validation"
        / "05 Final Remediation and Confirmation"
        / "GPU Vulkan Saturation Effectiveness Validation.json"
    )
    loader = ProfileLoader(ROOT / "profiles")
    profile = loader.load_profile(profile_path)
    stage = profile.stages[0]
    assert stage.duration_seconds == 660
    assert stage.normalization.trim_start_seconds == 60
    assert stage.normalization.trim_end_seconds == 30
    assert stage.analysis.intent == "sustained"
    assert stage.analysis.minimum_usable_seconds == 540
    assert stage.modules.gpu_3d.compute_variant == "stress_hash"
    assert stage.gpu_evaluation is None
    validation = ProfileValidator().validate(
        profile,
        loader.load_segment_labels(profile_path, profile),
    )
    assert validation["errors"] == []

    worker_source = (NATIVE / "vulkan_compute_worker.py").read_text(encoding="utf-8")
    assert 'state["frames"] % 3' not in worker_source
    assert 'state["frames"] % 10' not in worker_source
    assert '"saturation_result": True' not in worker_source
    assert '"power_saturation_expected": True' not in worker_source
    assert 'faulthandler.enable(all_threads=True)' in worker_source
    assert '"pipeline_created"' in worker_source
    assert '"initial_hardware_readback_completed"' in worker_source


if __name__ == "__main__":
    run_vulkan_workload_effectiveness_checks()
    print("vulkan workload effectiveness checks: PASS")
