#!/usr/bin/env python3
"""Deterministic Vulkan workload-effectiveness and instrumentation checks."""

from __future__ import annotations

import ctypes
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
    try:
        compute_dispatch_dimensions(17 * 256, 256, [8, 3, 1])
    except RuntimeError:
        pass
    else:
        raise AssertionError("unrepresentable dispatch must fail closed")

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
