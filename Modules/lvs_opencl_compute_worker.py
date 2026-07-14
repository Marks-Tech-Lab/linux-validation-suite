from __future__ import annotations

import textwrap
from typing import Any, Dict, Optional


def build_opencl_compute_workload_script(
    *,
    target_vendor: str,
    target_vendor_id: str,
    target_name: str,
    target_card: str,
    target_slot: str,
    target_id: str,
    target_gpu_index: int,
    target_vram_total: int,
    compute_variant: str,
    worker_params: Optional[Dict[str, Any]] = None,
) -> str:
    params = worker_params or {}
    surface_size = int(params.get("surface_size", 1024))
    draw_count = int(params.get("draw_count", 96))
    shader_iterations = int(params.get("shader_iterations", 24))
    compute_units = int(params.get("compute_units", 0) or 0)
    max_work_group_size = int(params.get("max_work_group_size", 0) or 0)
    max_clock_mhz = int(params.get("max_clock_mhz", 0) or 0)
    device_class = str(params.get("device_class", "") or "")
    parallelism_hint = int(params.get("parallelism_hint", 1) or 1)
    ramp_step_seconds = max(0.0, float(params.get("ramp_step_seconds", 0.0) or 0.0))
    start_load_fraction = max(0.15, min(1.0, float(params.get("start_load_fraction", 1.0) or 1.0)))
    safe_mode_enabled = bool(params.get("safe_mode_enabled", False))
    safe_max_load_scale = max(0.75, float(params.get("safe_max_load_scale", 1.0) or 1.0))
    compute_variant = str(compute_variant or "baseline")
    result_file = str(params.get("result_file", ""))
    return textwrap.dedent(
        f"""
        import atexit
        import ctypes
        import ctypes.util
        import json
        import os
        import re
        import signal
        import time

        TARGET_VENDOR = {target_vendor!r}
        TARGET_VENDOR_ID = {target_vendor_id!r}
        TARGET_NAME = {target_name!r}
        TARGET_CARD = {target_card!r}
        TARGET_SLOT = {target_slot!r}
        TARGET_ID = {target_id!r}
        TARGET_GPU_INDEX = {int(target_gpu_index)}
        TARGET_VRAM_TOTAL = {int(target_vram_total)}
        SURFACE_SIZE = {surface_size}
        DRAW_COUNT = {draw_count}
        SHADER_ITERATIONS = {shader_iterations}
        CAP_COMPUTE_UNITS = {compute_units}
        CAP_MAX_WORK_GROUP_SIZE = {max_work_group_size}
        CAP_MAX_CLOCK_MHZ = {max_clock_mhz}
        DEVICE_CLASS = {device_class!r}
        PARALLELISM_HINT = {parallelism_hint}
        RAMP_STEP_SECONDS = {ramp_step_seconds}
        START_LOAD_FRACTION = {start_load_fraction}
        SAFE_MODE_ENABLED = {safe_mode_enabled!r}
        SAFE_MAX_LOAD_SCALE = {safe_max_load_scale}
        COMPUTE_VARIANT = {compute_variant!r}
        RESULT_FILE = {result_file!r}

        CL_DEVICE_TYPE_GPU = 1 << 2
        CL_PLATFORM_VERSION = 0x0901
        CL_PLATFORM_NAME = 0x0902
        CL_PLATFORM_VENDOR = 0x0903
        CL_DEVICE_VENDOR_ID = 0x1001
        CL_DEVICE_NAME = 0x102B
        CL_DEVICE_VENDOR = 0x102C
        CL_DEVICE_GLOBAL_MEM_SIZE = 0x101F
        CL_DEVICE_MAX_MEM_ALLOC_SIZE = 0x1010
        CL_DEVICE_PCI_BUS_INFO_KHR = 0x410F
        CL_MEM_READ_WRITE = 1 << 0
        CL_PROGRAM_BUILD_LOG = 0x1183

        def resolve_opencl_library():
            candidates = []
            env_candidate = os.environ.get("OPENCL_LIBRARY_PATH", "").strip()
            if env_candidate:
                candidates.append(env_candidate)
            found = ctypes.util.find_library("OpenCL")
            if found:
                candidates.append(found)
            candidates.extend(
                [
                    "/usr/lib64/libOpenCL.so.1",
                    "/usr/lib64/libOpenCL.so",
                    "/usr/lib/libOpenCL.so.1",
                    "/usr/lib/libOpenCL.so",
                    "/usr/lib/x86_64-linux-gnu/libOpenCL.so.1",
                    "/usr/lib/x86_64-linux-gnu/libOpenCL.so",
                    "/lib64/libOpenCL.so.1",
                    "/lib64/libOpenCL.so",
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

        lib_name = resolve_opencl_library()
        if not lib_name:
            raise SystemExit("OpenCL library not found")
        CL = ctypes.CDLL(lib_name)

        cl_uint = ctypes.c_uint
        cl_ulong = ctypes.c_ulong
        cl_int = ctypes.c_int
        cl_size_t = ctypes.c_size_t
        cl_platform_id = ctypes.c_void_p
        cl_device_id = ctypes.c_void_p
        cl_context = ctypes.c_void_p
        cl_command_queue = ctypes.c_void_p
        cl_mem = ctypes.c_void_p
        cl_program = ctypes.c_void_p
        cl_kernel = ctypes.c_void_p
        cl_event = ctypes.c_void_p

        CL.clGetPlatformIDs.argtypes = [cl_uint, ctypes.POINTER(cl_platform_id), ctypes.POINTER(cl_uint)]
        CL.clGetPlatformIDs.restype = cl_int
        CL.clGetPlatformInfo.argtypes = [cl_platform_id, cl_uint, cl_size_t, ctypes.c_void_p, ctypes.POINTER(cl_size_t)]
        CL.clGetPlatformInfo.restype = cl_int
        CL.clGetDeviceIDs.argtypes = [cl_platform_id, cl_ulong, cl_uint, ctypes.POINTER(cl_device_id), ctypes.POINTER(cl_uint)]
        CL.clGetDeviceIDs.restype = cl_int
        CL.clGetDeviceInfo.argtypes = [cl_device_id, cl_uint, cl_size_t, ctypes.c_void_p, ctypes.POINTER(cl_size_t)]
        CL.clGetDeviceInfo.restype = cl_int
        CL.clCreateContext.argtypes = [ctypes.c_void_p, cl_uint, ctypes.POINTER(cl_device_id), ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(cl_int)]
        CL.clCreateContext.restype = cl_context
        CL.clCreateCommandQueue.argtypes = [cl_context, cl_device_id, cl_ulong, ctypes.POINTER(cl_int)]
        CL.clCreateCommandQueue.restype = cl_command_queue
        CL.clCreateBuffer.argtypes = [cl_context, cl_ulong, cl_size_t, ctypes.c_void_p, ctypes.POINTER(cl_int)]
        CL.clCreateBuffer.restype = cl_mem
        CL.clCreateProgramWithSource.argtypes = [cl_context, cl_uint, ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(cl_size_t), ctypes.POINTER(cl_int)]
        CL.clCreateProgramWithSource.restype = cl_program
        CL.clBuildProgram.argtypes = [cl_program, cl_uint, ctypes.POINTER(cl_device_id), ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p]
        CL.clBuildProgram.restype = cl_int
        CL.clGetProgramBuildInfo.argtypes = [cl_program, cl_device_id, cl_uint, cl_size_t, ctypes.c_void_p, ctypes.POINTER(cl_size_t)]
        CL.clGetProgramBuildInfo.restype = cl_int
        CL.clCreateKernel.argtypes = [cl_program, ctypes.c_char_p, ctypes.POINTER(cl_int)]
        CL.clCreateKernel.restype = cl_kernel
        CL.clSetKernelArg.argtypes = [cl_kernel, cl_uint, cl_size_t, ctypes.c_void_p]
        CL.clSetKernelArg.restype = cl_int
        CL.clEnqueueNDRangeKernel.argtypes = [cl_command_queue, cl_kernel, cl_uint, ctypes.POINTER(cl_size_t), ctypes.POINTER(cl_size_t), ctypes.POINTER(cl_size_t), cl_uint, ctypes.POINTER(cl_event), ctypes.POINTER(cl_event)]
        CL.clEnqueueNDRangeKernel.restype = cl_int
        CL.clEnqueueReadBuffer.argtypes = [cl_command_queue, cl_mem, cl_uint, cl_size_t, cl_size_t, ctypes.c_void_p, cl_uint, ctypes.POINTER(cl_event), ctypes.POINTER(cl_event)]
        CL.clEnqueueReadBuffer.restype = cl_int
        CL.clFinish.argtypes = [cl_command_queue]
        CL.clFinish.restype = cl_int
        CL.clReleaseMemObject.argtypes = [cl_mem]
        CL.clReleaseMemObject.restype = cl_int
        CL.clReleaseKernel.argtypes = [cl_kernel]
        CL.clReleaseKernel.restype = cl_int
        CL.clReleaseProgram.argtypes = [cl_program]
        CL.clReleaseProgram.restype = cl_int
        CL.clReleaseCommandQueue.argtypes = [cl_command_queue]
        CL.clReleaseCommandQueue.restype = cl_int
        CL.clReleaseContext.argtypes = [cl_context]
        CL.clReleaseContext.restype = cl_int

        state = {{
            "kind": "gpu",
            "mode": "gpu_3d",
            "backend": "python_opencl_compute",
            "compute_variant": COMPUTE_VARIANT,
            "status": "ok",
            "error_count": 0,
            "verification_passes": 0,
            "compute_mismatch_count": 0,
            "kernel_launches": 0,
            "buffer_count": 0,
            "buffer_words": 0,
            "launches_per_cycle": 0,
            "compute_rounds": 0,
            "selection_ambiguous": False,
            "selected_opencl_index": None,
            "selected_device_name": "",
            "selected_device_vendor": "",
            "selected_device_pci_slot": "",
            "selection_candidates": [],
            "device_global_mem_bytes": 0,
            "device_max_alloc_bytes": 0,
            "platform_name": "",
            "platform_vendor": "",
            "platform_version": "",
            "last_error": "",
            "target_vendor": TARGET_VENDOR,
            "target_card": TARGET_CARD,
            "target_slot": TARGET_SLOT,
            "target_id": TARGET_ID,
            "target_gpu_index": TARGET_GPU_INDEX,
            "target_vram_total": TARGET_VRAM_TOTAL,
            "frames": 0,
            "phase": "initializing",
            "phase_history": [],
            "runtime_work_item_cap": 0,
            "runtime_launch_cap": 0,
            "runtime_round_cap": 0,
            "runtime_buffer_count": 0,
            "active_buffer_count": 0,
            "safe_mode_enabled": SAFE_MODE_ENABLED,
            "backend_safety_profile": "",
            "queue_finish_stride": 0,
            "phase_scale_profile": {{}},
            "phase_sleep_profile": {{}},
            "phase_buffer_profile": {{}},
        }}

        def record_error(message):
            state["status"] = "error"
            state["error_count"] += 1
            state["last_error"] = str(message)

        def check(code, context):
            if int(code) != 0:
                raise RuntimeError(f"{{context}} failed with OpenCL code {{int(code)}}")

        def get_string(getter, handle, param):
            size = cl_size_t()
            code = getter(handle, param, 0, None, ctypes.byref(size))
            check(code, f"query size {{param}}")
            if size.value <= 1:
                return ""
            buffer = ctypes.create_string_buffer(size.value)
            code = getter(handle, param, size.value, buffer, None)
            check(code, f"query value {{param}}")
            return buffer.value.decode("utf-8", "ignore").strip()

        def get_ulong(device, param):
            value = cl_ulong()
            code = CL.clGetDeviceInfo(device, param, ctypes.sizeof(value), ctypes.byref(value), None)
            check(code, f"device info {{param}}")
            return int(value.value)

        def get_uint(device, param):
            value = cl_uint()
            code = CL.clGetDeviceInfo(device, param, ctypes.sizeof(value), ctypes.byref(value), None)
            check(code, f"device info {{param}}")
            return int(value.value)

        class cl_device_pci_bus_info_khr(ctypes.Structure):
            _fields_ = [
                ("pci_domain", cl_uint),
                ("pci_bus", cl_uint),
                ("pci_device", cl_uint),
                ("pci_function", cl_uint),
            ]

        def get_pci_slot(device):
            value = cl_device_pci_bus_info_khr()
            code = CL.clGetDeviceInfo(
                device,
                CL_DEVICE_PCI_BUS_INFO_KHR,
                ctypes.sizeof(value),
                ctypes.byref(value),
                None,
            )
            if int(code) != 0:
                return ""
            return f"{{int(value.pci_domain):04x}}:{{int(value.pci_bus):02x}}:{{int(value.pci_device):02x}}.{{int(value.pci_function)}}"

        def normalize_pci_slot(value):
            return str(value or "").strip().lower()

        def identity_key(info):
            vendor = str(info.get("vendor", "")).strip().lower()
            name = str(info.get("name", "")).strip().lower()
            mem = int(info.get("global_mem_bytes", 0) or 0)
            bucket = mem // max(1, 256 * 1024 * 1024)
            return f"{{vendor}}|{{name}}|{{bucket}}"

        def vendor_aliases(vendor):
            normalized = str(vendor or "").strip().lower()
            normalized_id = normalized.removeprefix("0x")
            if normalized in ("amd", "advanced micro devices") or normalized_id == "1002":
                return ("amd", "advanced micro devices", "advanced micro devices, inc.", "ati", "radeon")
            if normalized == "nvidia" or normalized_id == "10de":
                return ("nvidia", "nvidia corporation")
            if normalized == "intel" or normalized_id == "8086":
                return ("intel", "intel(r)", "intel corporation", "intel(r) corporation")
            return (normalized,) if normalized else ()

        def vendor_matches(vendor, *texts):
            aliases = vendor_aliases(vendor)
            haystack = " ".join(str(text or "").strip().lower() for text in texts if str(text or "").strip())
            if not aliases or not haystack:
                return False
            tokens = {{token for token in re.split(r"[^a-z0-9]+", haystack) if token}}
            for alias in aliases:
                alias_text = str(alias or "").strip().lower()
                if not alias_text:
                    continue
                alias_compact = re.sub(r"[^a-z0-9]+", "", alias_text)
                if len(alias_compact) <= 3:
                    if alias_compact in tokens:
                        return True
                    continue
                if alias_text in haystack:
                    return True
            return False

        def platform_preference(info):
            target_vendor = TARGET_VENDOR.lower().strip()
            platform_name = str(info.get("platform_name", "")).lower()
            platform_vendor = str(info.get("platform_vendor", "")).lower()
            preference = 0
            if vendor_matches(target_vendor, platform_vendor):
                preference += 220
            if target_vendor == "amd":
                if "accelerated parallel processing" in platform_name:
                    preference += 180
                if "advanced micro devices" in platform_vendor:
                    preference += 140
                if "rusticl" in platform_name:
                    preference -= 80
            elif target_vendor == "nvidia":
                if "nvidia" in platform_name or "nvidia" in platform_vendor:
                    preference += 180
                if "rusticl" in platform_name:
                    preference -= 40
            elif target_vendor == "intel":
                if "intel" in platform_name or "intel" in platform_vendor:
                    preference += 140
            return preference

        def score_device(info):
            score = 0
            target_vendor = TARGET_VENDOR.lower().strip()
            target_vendor_id = str(TARGET_VENDOR_ID or "").strip().lower().removeprefix("0x")
            vendor = str(info.get("vendor", "")).lower()
            name = str(info.get("name", "")).lower()
            vendor_id = str(info.get("vendor_id", "") or "").strip().lower().removeprefix("0x")
            target_name = str(TARGET_NAME or "").lower().strip()
            target_card = TARGET_CARD.lower().strip()
            target_slot = normalize_pci_slot(TARGET_SLOT or TARGET_ID)
            device_slot = normalize_pci_slot(info.get("pci_slot", ""))
            vendor_match = False
            if target_slot and device_slot:
                if target_slot == device_slot:
                    score += 2500
                else:
                    return -1000000
            if target_vendor_id and vendor_id and target_vendor_id == vendor_id:
                vendor_match = True
                score += 320
            if vendor_matches(target_vendor, vendor, name, str(info.get("platform_vendor", "")).lower()):
                vendor_match = True
                score += 120
            if target_vendor and not vendor_match:
                return -1000000
            if target_name:
                tokens = [
                    token
                    for token in __import__("re").split(r"[^a-z0-9]+", target_name)
                    if len(token) >= 3 and token not in {{target_vendor, "gpu", "graphics"}}
                ]
                score += min(160, 40 * sum(1 for token in tokens if token in name))
            if target_card and target_card in name:
                score += 80
            score += platform_preference(info)
            if TARGET_VRAM_TOTAL and info.get("global_mem_bytes"):
                diff = abs(int(info["global_mem_bytes"]) - int(TARGET_VRAM_TOTAL))
                score += max(0, 60 - min(60, diff // max(1, 256 * 1024 * 1024)))
            score += min(30, int(info.get("global_mem_bytes", 0)) // max(1, 4 * 1024 ** 3))
            if not device_slot and info.get("opencl_index") == TARGET_GPU_INDEX:
                score += 10
            return score

        def rotl32(value, shift):
            value &= 0xFFFFFFFF
            shift = int(shift) & 31
            if shift == 0:
                return value
            return ((value << shift) | (value >> (32 - shift))) & 0xFFFFFFFF

        def expected_word_baseline(index, seed, rounds):
            value = (int(index) ^ int(seed) ^ 0x9E3779B9) & 0xFFFFFFFF
            for offset in range(int(rounds)):
                value = (value * 1664525 + 1013904223 + ((offset ^ seed) & 0xFFFFFFFF)) & 0xFFFFFFFF
                value ^= (value >> 13)
                value &= 0xFFFFFFFF
                value = (value * 1274126177) & 0xFFFFFFFF
                value ^= ((value << 7) & 0xFFFFFFFF)
                value &= 0xFFFFFFFF
            return value

        def expected_word_integer_mix(index, seed, rounds):
            word_index = int(index) & 0xFFFFFFFF
            seed_value = int(seed) & 0xFFFFFFFF
            value = (word_index * 747796405 + seed_value * 2891336453 + 0x9E3779B9) & 0xFFFFFFFF
            lane = (word_index ^ seed_value) & 31
            for offset in range(int(rounds)):
                offset_value = int(offset) & 0xFFFFFFFF
                rotate = ((lane + offset_value) % 31) + 1
                value ^= rotl32((value + (((offset_value + 1) * 0x6D2B79F5) & 0xFFFFFFFF)) & 0xFFFFFFFF, rotate)
                value &= 0xFFFFFFFF
                value = (value * 0x85EBCA6B + 0xC2B2AE35 + (value >> 16)) & 0xFFFFFFFF
                value ^= rotl32((value ^ ((word_index + ((offset_value * 0x27D4EB2D) & 0xFFFFFFFF)) & 0xFFFFFFFF)) & 0xFFFFFFFF, 13)
                value &= 0xFFFFFFFF
            return value

        def expected_word(index, seed, rounds):
            if COMPUTE_VARIANT == "integer_mix":
                return expected_word_integer_mix(index, seed, rounds)
            return expected_word_baseline(index, seed, rounds)

        def verify_buffer(queue, buffer_handle, words, seed, rounds):
            sample_points = sorted(set([0, max(0, words // 3), max(0, (2 * words) // 3), max(0, words - 1)]))
            if not sample_points:
                return
            start_word = min(sample_points)
            span = max(sample_points) - start_word + 1
            readback = (ctypes.c_uint32 * span)()
            offset = start_word * ctypes.sizeof(ctypes.c_uint32)
            code = CL.clEnqueueReadBuffer(
                queue,
                buffer_handle,
                1,
                offset,
                ctypes.sizeof(readback),
                ctypes.byref(readback),
                0,
                None,
                None,
            )
            check(code, "clEnqueueReadBuffer")
            code = CL.clFinish(queue)
            check(code, "clFinish verify")
            for sample_index in sample_points:
                actual = int(readback[sample_index - start_word])
                expected = expected_word(sample_index, seed, rounds)
                if actual != expected:
                    state["compute_mismatch_count"] += 1
                    record_error(f"OpenCL compute mismatch at word {{sample_index}}: expected={{expected}} actual={{actual}}")
                    break
            state["verification_passes"] += 1

        def current_load_fraction(started_monotonic):
            if RAMP_STEP_SECONDS <= 0:
                return 1.0
            elapsed = max(0.0, time.monotonic() - started_monotonic)
            progress = min(1.0, elapsed / max(0.001, RAMP_STEP_SECONDS * 3.0))
            return min(1.0, START_LOAD_FRACTION + (1.0 - START_LOAD_FRACTION) * progress)

        def phase_limits():
            if not SAFE_MODE_ENABLED:
                return 0.0, 0.0
            if DEVICE_CLASS == "discrete":
                warmup_end = max(12.0, RAMP_STEP_SECONDS * 1.0)
                load_end = max(warmup_end + 24.0, RAMP_STEP_SECONDS * 4.0)
                return warmup_end, load_end
            warmup_end = max(8.0, RAMP_STEP_SECONDS * 1.5)
            load_end = max(18.0, RAMP_STEP_SECONDS * 3.0)
            return warmup_end, load_end

        def high_headroom_discrete():
            return DEVICE_CLASS == "discrete" and str(TARGET_VENDOR or "").strip().lower() == "amd" and (
                int(CAP_COMPUTE_UNITS or 0) >= 28 or int(CAP_MAX_CLOCK_MHZ or 0) >= 2400
            )

        def low_headroom_amd_opencl():
            if not SAFE_MODE_ENABLED:
                return False
            if str(TARGET_VENDOR or "").strip().lower() != "amd":
                return False
            if high_headroom_discrete():
                return False
            platform_name = str(state.get("platform_name", "") or "").lower()
            platform_vendor = str(state.get("platform_vendor", "") or "").lower()
            global_mem = int(state.get("device_global_mem_bytes", 0) or 0)
            rusticl_path = "rusticl" in platform_name or "mesa" in platform_vendor
            small_or_shared = DEVICE_CLASS != "discrete" or (global_mem > 0 and global_mem <= 2 * 1024 ** 3)
            return bool(rusticl_path and small_or_shared)

        def queue_finish_stride(phase_name):
            if low_headroom_amd_opencl():
                return 1
            if SAFE_MODE_ENABLED and DEVICE_CLASS != "discrete" and phase_name != "warmup":
                return 2
            return 0

        def current_phase(started_monotonic):
            if not SAFE_MODE_ENABLED:
                return "verify"
            elapsed = max(0.0, time.monotonic() - started_monotonic)
            warmup_end, load_end = phase_limits()
            if elapsed < warmup_end:
                return "warmup"
            if elapsed < load_end:
                return "load"
            return "verify"

        def set_phase(name):
            if state.get("phase") == name:
                return
            state["phase"] = name
            history = list(state.get("phase_history") or [])
            history.append({{"phase": name, "timestamp": time.time()}})
            state["phase_history"] = history[-8:]

        def safe_runtime_limits(work_items, launches_per_cycle, compute_rounds, buffer_count):
            if not SAFE_MODE_ENABLED:
                return work_items, launches_per_cycle, compute_rounds, buffer_count
            if low_headroom_amd_opencl():
                return (
                    min(work_items, 1 << 18),
                    min(launches_per_cycle, 4),
                    min(compute_rounds, 72),
                    1,
                )
            if DEVICE_CLASS == "discrete":
                discrete_compute_scale = 1
                if CAP_COMPUTE_UNITS >= 48:
                    discrete_compute_scale = 3
                elif CAP_COMPUTE_UNITS >= 28:
                    discrete_compute_scale = 2
                safe_scale_factor = max(1.0, min(1.58, 0.94 + SAFE_MAX_LOAD_SCALE * 0.36))
                if COMPUTE_VARIANT == "integer_mix":
                    if high_headroom_discrete():
                        return (
                            min(work_items, 1 << 20),
                            min(launches_per_cycle, 14),
                            min(compute_rounds, 160),
                            min(buffer_count, 2),
                        )
                    return (
                        min(work_items, 1 << 19),
                        min(launches_per_cycle, 8),
                        min(compute_rounds, 96),
                        min(buffer_count, 2),
                    )
                return (
                    min(work_items, int((1 << (19 + min(3, discrete_compute_scale))) * safe_scale_factor)),
                    min(launches_per_cycle, max(12, int(round((11 + discrete_compute_scale * 3) * safe_scale_factor)))),
                    min(compute_rounds, max(128, int(round((112 + discrete_compute_scale * 40) * safe_scale_factor)))),
                    min(buffer_count, 3 + min(2, discrete_compute_scale)),
                )
            return (
                min(work_items, 1 << 18),
                min(launches_per_cycle, 6),
                min(compute_rounds, 72),
                1,
            )

        def phase_scale(phase_name):
            if phase_name == "warmup":
                return 0.3
            if COMPUTE_VARIANT == "integer_mix" and SAFE_MODE_ENABLED and DEVICE_CLASS == "discrete":
                if phase_name == "load":
                    return 0.7 if high_headroom_discrete() else 0.65
                return 0.72 if high_headroom_discrete() else 0.68
            if phase_name == "load":
                if SAFE_MODE_ENABLED and DEVICE_CLASS == "discrete":
                    return 0.9 if high_headroom_discrete() else 0.95
                return 0.8
            if SAFE_MODE_ENABLED and DEVICE_CLASS == "discrete":
                return 0.9 if high_headroom_discrete() else 0.95
            return 0.9 if SAFE_MODE_ENABLED else 1.0

        def phase_sleep_seconds(phase_name):
            if not SAFE_MODE_ENABLED:
                return 0.001
            if DEVICE_CLASS == "discrete":
                if phase_name == "warmup":
                    return 0.001
                if COMPUTE_VARIANT == "integer_mix":
                    if phase_name == "load":
                        return 0.0024 if high_headroom_discrete() else 0.002
                    return 0.0027 if high_headroom_discrete() else 0.0025
                if phase_name == "load":
                    return 0.0008 if high_headroom_discrete() else 0.0006
                return 0.001 if high_headroom_discrete() else 0.0008
            if phase_name == "warmup":
                return 0.002
            if phase_name == "load":
                return 0.0015
            return 0.0018

        def phase_buffer_count(phase_name, runtime_buffer_count, available_buffers):
            if available_buffers <= 0:
                return 0
            if not SAFE_MODE_ENABLED:
                return max(1, min(available_buffers, 1 if phase_name == "warmup" else available_buffers))
            if DEVICE_CLASS == "discrete":
                if phase_name == "warmup":
                    return 1
                if phase_name == "load":
                    reduction = 2 if high_headroom_discrete() else 1
                    if COMPUTE_VARIANT == "integer_mix":
                        return 1
                    target = max(1, runtime_buffer_count - reduction)
                    return max(1, min(available_buffers, target))
                if COMPUTE_VARIANT == "integer_mix":
                    return max(1, min(available_buffers, 2))
                return max(1, min(available_buffers, runtime_buffer_count))
            return 1

        def write_result():
            if not RESULT_FILE:
                return
            try:
                temp_path = RESULT_FILE + ".tmp"
                with open(temp_path, "w", encoding="utf-8") as handle:
                    json.dump(state, handle, indent=2)
                    handle.flush()
                    try:
                        os.fsync(handle.fileno())
                    except Exception:
                        pass
                os.replace(temp_path, RESULT_FILE)
            except Exception:
                pass

        atexit.register(write_result)

        buffers = []
        kernel = None
        program = None
        queue = None
        context = None

        try:
            platform_count = cl_uint()
            code = CL.clGetPlatformIDs(0, None, ctypes.byref(platform_count))
            check(code, "clGetPlatformIDs count")
            if platform_count.value <= 0:
                raise RuntimeError("no OpenCL platforms found")
            platform_ids = (cl_platform_id * platform_count.value)()
            code = CL.clGetPlatformIDs(platform_count.value, platform_ids, None)
            check(code, "clGetPlatformIDs list")

            devices = []
            opencl_index = 0
            for platform_handle in platform_ids:
                platform_name = get_string(CL.clGetPlatformInfo, platform_handle, CL_PLATFORM_NAME)
                platform_vendor = get_string(CL.clGetPlatformInfo, platform_handle, CL_PLATFORM_VENDOR)
                platform_version = get_string(CL.clGetPlatformInfo, platform_handle, CL_PLATFORM_VERSION)
                device_count = cl_uint()
                code = CL.clGetDeviceIDs(platform_handle, CL_DEVICE_TYPE_GPU, 0, None, ctypes.byref(device_count))
                if int(code) != 0 or device_count.value <= 0:
                    continue
                device_ids = (cl_device_id * device_count.value)()
                code = CL.clGetDeviceIDs(platform_handle, CL_DEVICE_TYPE_GPU, device_count.value, device_ids, None)
                check(code, "clGetDeviceIDs list")
                for device_handle in device_ids:
                    info = {{
                        "platform_name": platform_name,
                        "platform_vendor": platform_vendor,
                        "platform_version": platform_version,
                        "device": device_handle,
                        "opencl_index": opencl_index,
                        "name": get_string(CL.clGetDeviceInfo, device_handle, CL_DEVICE_NAME),
                        "vendor": get_string(CL.clGetDeviceInfo, device_handle, CL_DEVICE_VENDOR),
                        "vendor_id": format(get_uint(device_handle, CL_DEVICE_VENDOR_ID), "04x"),
                        "global_mem_bytes": get_ulong(device_handle, CL_DEVICE_GLOBAL_MEM_SIZE),
                        "max_alloc_bytes": get_ulong(device_handle, CL_DEVICE_MAX_MEM_ALLOC_SIZE),
                        "pci_slot": get_pci_slot(device_handle),
                    }}
                    devices.append(info)
                    opencl_index += 1

            if not devices:
                raise RuntimeError("no OpenCL GPU devices found")

            identity_counts = {{}}
            for info in devices:
                key = identity_key(info)
                identity_counts[key] = identity_counts.get(key, 0) + 1
            for info in devices:
                info["identity_key"] = identity_key(info)
                info["duplicate_group_size"] = identity_counts.get(info["identity_key"], 1)

            ranked = sorted(((score_device(info), info) for info in devices), key=lambda item: item[0], reverse=True)
            if (
                len(ranked) >= 2
                and ranked[0][1].get("identity_key") != ranked[1][1].get("identity_key")
                and ranked[0][0] - ranked[1][0] <= 10
            ):
                state["selection_ambiguous"] = True
            state["selection_candidates"] = [
                {{
                    "score": round(float(score), 3),
                    "opencl_index": int(info.get("opencl_index", -1)),
                    "name": info.get("name", ""),
                    "vendor": info.get("vendor", ""),
                    "vendor_id": info.get("vendor_id", ""),
                    "pci_slot": info.get("pci_slot", ""),
                    "global_mem_bytes": int(info.get("global_mem_bytes", 0) or 0),
                }}
                for score, info in ranked[:8]
            ]
            best_score, selected = ranked[0]
            if best_score <= -999000:
                raise RuntimeError(f"no matching OpenCL GPU device found for target {{TARGET_ID or TARGET_SLOT}}")
            target_slot = normalize_pci_slot(TARGET_SLOT or TARGET_ID)
            selected_slot = normalize_pci_slot(selected.get("pci_slot", ""))
            if target_slot and selected_slot and target_slot != selected_slot:
                raise RuntimeError(
                    f"OpenCL selected PCI slot {{selected_slot}} but target is {{target_slot}}"
                )
            if target_slot and not selected_slot and len(devices) > 1 and int(selected.get("opencl_index", -1)) != TARGET_GPU_INDEX:
                raise RuntimeError(
                    f"OpenCL could not verify PCI slot for target {{target_slot}}; selected index {{selected.get('opencl_index', -1)}}"
                )
            device_array = (cl_device_id * 1)(cl_device_id(selected["device"]))
            device = device_array[0]
            state["selected_opencl_index"] = selected["opencl_index"]
            state["selected_device_name"] = selected["name"]
            state["selected_device_vendor"] = selected["vendor"]
            state["selected_device_pci_slot"] = selected.get("pci_slot", "")
            state["device_global_mem_bytes"] = int(selected["global_mem_bytes"])
            state["device_max_alloc_bytes"] = int(selected["max_alloc_bytes"])
            state["platform_name"] = selected["platform_name"]
            state["platform_vendor"] = selected.get("platform_vendor", "")
            state["platform_version"] = selected.get("platform_version", "")
            selected_vendor_text = str(selected.get("vendor", "") or "").lower()
            selected_name_text = str(selected.get("name", "") or "").lower()
            selected_platform_vendor = str(selected.get("platform_vendor", "") or "").lower()
            selected_vendor_id = str(selected.get("vendor_id", "") or "").strip().lower().removeprefix("0x")
            target_vendor_id = str(TARGET_VENDOR_ID or "").strip().lower().removeprefix("0x")
            vendor_ok = bool(target_vendor_id and selected_vendor_id and target_vendor_id == selected_vendor_id)
            if not vendor_ok:
                vendor_ok = vendor_matches(TARGET_VENDOR, selected_vendor_text, selected_name_text, selected_platform_vendor)
            if TARGET_VENDOR and not vendor_ok:
                raise RuntimeError(
                    f"OpenCL selected mismatched device for target {{TARGET_ID}}: {{selected.get('name', '')}}"
                )

            error_code = cl_int()
            context = CL.clCreateContext(None, 1, device_array, None, None, ctypes.byref(error_code))
            check(error_code.value, "clCreateContext")
            queue = CL.clCreateCommandQueue(context, device, 0, ctypes.byref(error_code))
            check(error_code.value, "clCreateCommandQueue")

            if COMPUTE_VARIANT == "integer_mix":
                kernel_source = b'''
                uint rotl32(uint value, uint shift) {{
                    shift &= 31u;
                    return shift == 0u ? value : ((value << shift) | (value >> (32u - shift)));
                }}
                __kernel void compute_pattern(__global uint *out, const uint seed, const uint rounds) {{
                    size_t gid = get_global_id(0);
                    uint word_index = (uint)gid;
                    uint value = word_index * 747796405u + seed * 2891336453u + 0x9E3779B9u;
                    uint lane = (word_index ^ seed) & 31u;
                    for (uint i = 0; i < rounds; ++i) {{
                        uint rotate = ((lane + i) % 31u) + 1u;
                        value ^= rotl32(value + ((i + 1u) * 0x6D2B79F5u), rotate);
                        value = value * 0x85EBCA6Bu + 0xC2B2AE35u + (value >> 16);
                        value ^= rotl32(value ^ (word_index + i * 0x27D4EB2Du), 13u);
                    }}
                    out[gid] = value;
                }}
                '''
            else:
                kernel_source = b'''
                __kernel void compute_pattern(__global uint *out, const uint seed, const uint rounds) {{
                    size_t gid = get_global_id(0);
                    uint value = ((uint)gid) ^ seed ^ 0x9E3779B9u;
                    for (uint i = 0; i < rounds; ++i) {{
                        value = value * 1664525u + 1013904223u + (i ^ seed);
                        value ^= (value >> 13);
                        value *= 1274126177u;
                        value ^= (value << 7);
                    }}
                    out[gid] = value;
                }}
                '''
            source_ptr = ctypes.c_char_p(kernel_source)
            source_length = cl_size_t(len(kernel_source))
            program = CL.clCreateProgramWithSource(context, 1, ctypes.byref(source_ptr), ctypes.byref(source_length), ctypes.byref(error_code))
            check(error_code.value, "clCreateProgramWithSource")
            build_code = CL.clBuildProgram(program, 1, device_array, None, None, None)
            if int(build_code) != 0:
                log_size = cl_size_t()
                CL.clGetProgramBuildInfo(program, device, CL_PROGRAM_BUILD_LOG, 0, None, ctypes.byref(log_size))
                build_log = b""
                if log_size.value:
                    log_buffer = ctypes.create_string_buffer(log_size.value)
                    CL.clGetProgramBuildInfo(program, device, CL_PROGRAM_BUILD_LOG, log_size.value, log_buffer, None)
                    build_log = log_buffer.value
                raise RuntimeError("OpenCL build failed: " + build_log.decode("utf-8", "ignore"))

            kernel = CL.clCreateKernel(program, b"compute_pattern", ctypes.byref(error_code))
            check(error_code.value, "clCreateKernel")

            compute_units = max(1, int(CAP_COMPUTE_UNITS) or 16)
            parallelism_hint = max(1, int(PARALLELISM_HINT) or 1)
            work_group_hint = max(64, int(CAP_MAX_WORK_GROUP_SIZE) or 256)
            clock_hint = max(1000, int(CAP_MAX_CLOCK_MHZ) or 1800)
            compute_multiplier = max(1, min(3, compute_units // 16 if compute_units > 0 else 1))
            work_items = max(1 << 20, min(1 << 25, SURFACE_SIZE * SURFACE_SIZE * compute_multiplier))
            launches_per_cycle = max(8, min(48, (DRAW_COUNT // 4) + min(8, compute_units // 8) + min(4, parallelism_hint)))
            compute_rounds = max(48, min(768, SHADER_ITERATIONS * 8 + min(96, compute_units * 3) + min(48, clock_hint // 100)))
            buffer_words = max(1 << 20, min(1 << 24, max(work_items, work_group_hint * max(8, compute_units) * 32)))
            max_alloc = int(selected["max_alloc_bytes"]) or 0
            if max_alloc > 0:
                buffer_bytes = min(buffer_words * ctypes.sizeof(ctypes.c_uint32), max_alloc)
            else:
                buffer_bytes = buffer_words * ctypes.sizeof(ctypes.c_uint32)
            buffer_words = max(1, buffer_bytes // ctypes.sizeof(ctypes.c_uint32))
            work_items = min(work_items, buffer_words)
            base_buffer_count = 2 if DEVICE_CLASS != "discrete" else 4
            buffer_count = min(6, max(base_buffer_count, base_buffer_count + min(1, parallelism_hint - 1) + min(1, compute_units // 40)))
            runtime_work_items, runtime_launches, runtime_rounds, runtime_buffer_count = safe_runtime_limits(
                work_items,
                launches_per_cycle,
                compute_rounds,
                buffer_count,
            )
            if low_headroom_amd_opencl():
                state["backend_safety_profile"] = "amd_low_headroom_opencl"
            state["buffer_count"] = buffer_count
            state["buffer_words"] = buffer_words
            state["launches_per_cycle"] = launches_per_cycle
            state["compute_rounds"] = compute_rounds
            state["runtime_work_item_cap"] = int(runtime_work_items)
            state["runtime_launch_cap"] = int(runtime_launches)
            state["runtime_round_cap"] = int(runtime_rounds)
            state["runtime_buffer_count"] = int(runtime_buffer_count)

            for _ in range(runtime_buffer_count):
                buffer_handle = cl_mem(CL.clCreateBuffer(context, CL_MEM_READ_WRITE, buffer_bytes, None, ctypes.byref(error_code)))
                check(error_code.value, "clCreateBuffer")
                buffers.append(buffer_handle)

            write_result()
            running = True

            def stop(*_args):
                global running
                running = False

            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)

            frame = 0
            started_monotonic = time.monotonic()
            warmup_phase_seconds, load_phase_until_seconds = phase_limits()
            state["phase_schedule"] = {{
                "warmup_end_seconds": round(float(warmup_phase_seconds), 3),
                "load_end_seconds": round(float(load_phase_until_seconds), 3),
            }}
            state["phase_scale_profile"] = {{
                "warmup": round(float(phase_scale("warmup")), 3),
                "load": round(float(phase_scale("load")), 3),
                "verify": round(float(phase_scale("verify")), 3),
            }}
            state["phase_sleep_profile"] = {{
                "warmup": round(float(phase_sleep_seconds("warmup")), 6),
                "load": round(float(phase_sleep_seconds("load")), 6),
                "verify": round(float(phase_sleep_seconds("verify")), 6),
            }}
            state["phase_buffer_profile"] = {{
                "warmup": int(phase_buffer_count("warmup", runtime_buffer_count, len(buffers))),
                "load": int(phase_buffer_count("load", runtime_buffer_count, len(buffers))),
                "verify": int(phase_buffer_count("verify", runtime_buffer_count, len(buffers))),
            }}
            verify_interval_seconds = 1.5 if SAFE_MODE_ENABLED and DEVICE_CLASS == "discrete" else (1.75 if SAFE_MODE_ENABLED else 0.75)
            last_verify_monotonic = started_monotonic - verify_interval_seconds
            state["verification_interval_seconds"] = verify_interval_seconds
            while running:
                load_fraction = current_load_fraction(started_monotonic)
                phase_name = current_phase(started_monotonic)
                set_phase(phase_name)
                scaled_fraction = max(0.2, min(1.0, load_fraction * phase_scale(phase_name)))
                current_launches = max(1, min(runtime_launches, int(round(runtime_launches * scaled_fraction))))
                current_rounds = max(24, min(runtime_rounds, int(round(runtime_rounds * scaled_fraction))))
                minimum_safe_work_items = (1 << 16) if SAFE_MODE_ENABLED and DEVICE_CLASS == "discrete" else ((1 << 14) if SAFE_MODE_ENABLED else (1 << 16))
                current_work_items = max(
                    max(minimum_safe_work_items, work_group_hint * (2 if SAFE_MODE_ENABLED else 4)),
                    min(runtime_work_items, int(round(runtime_work_items * scaled_fraction))),
                )
                current_global_size = cl_size_t(max(1, current_work_items))
                current_buffer_count = phase_buffer_count(phase_name, runtime_buffer_count, len(buffers))
                state["active_load_fraction"] = round(load_fraction, 3)
                state["active_launches_per_cycle"] = current_launches
                state["active_compute_rounds"] = current_rounds
                state["active_work_items"] = int(current_global_size.value)
                state["active_buffer_count"] = current_buffer_count
                finish_stride = queue_finish_stride(phase_name)
                state["queue_finish_stride"] = int(finish_stride)
                for launch_index in range(current_launches):
                    buffer_handle = buffers[launch_index % current_buffer_count]
                    seed_value = cl_uint((frame * launches_per_cycle + launch_index + 1) & 0xFFFFFFFF)
                    rounds_value = cl_uint(current_rounds)
                    code = CL.clSetKernelArg(kernel, 0, ctypes.sizeof(cl_mem), ctypes.byref(buffer_handle))
                    check(code, "clSetKernelArg buffer")
                    code = CL.clSetKernelArg(kernel, 1, ctypes.sizeof(seed_value), ctypes.byref(seed_value))
                    check(code, "clSetKernelArg seed")
                    code = CL.clSetKernelArg(kernel, 2, ctypes.sizeof(rounds_value), ctypes.byref(rounds_value))
                    check(code, "clSetKernelArg rounds")
                    code = CL.clEnqueueNDRangeKernel(queue, kernel, 1, None, ctypes.byref(current_global_size), None, 0, None, None)
                    check(code, "clEnqueueNDRangeKernel")
                    state["kernel_launches"] += 1
                    if finish_stride and ((launch_index + 1) % finish_stride == 0):
                        code = CL.clFinish(queue)
                        check(code, "clFinish chunk")
                    if (
                        phase_name == "verify"
                        and launch_index == current_launches - 1
                        and (time.monotonic() - last_verify_monotonic) >= verify_interval_seconds
                    ):
                        verify_buffer(queue, buffer_handle, int(current_global_size.value), int(seed_value.value), current_rounds)
                        last_verify_monotonic = time.monotonic()
                code = CL.clFinish(queue)
                check(code, "clFinish")
                frame += 1
                state["frames"] = frame
                if frame % 16 == 0:
                    write_result()
                time.sleep(phase_sleep_seconds(phase_name))
        except Exception as exc:
            record_error(str(exc))
            raise SystemExit(1)
        finally:
            for buffer_handle in buffers:
                try:
                    CL.clReleaseMemObject(buffer_handle)
                except Exception:
                    pass
            if kernel:
                try:
                    CL.clReleaseKernel(kernel)
                except Exception:
                    pass
            if program:
                try:
                    CL.clReleaseProgram(program)
                except Exception:
                    pass
            if queue:
                try:
                    CL.clReleaseCommandQueue(queue)
                except Exception:
                    pass
            if context:
                try:
                    CL.clReleaseContext(context)
                except Exception:
                    pass
        """
    ).strip()
