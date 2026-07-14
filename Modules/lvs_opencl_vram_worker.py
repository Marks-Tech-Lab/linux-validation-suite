from __future__ import annotations

import json
import textwrap
from typing import Any, Dict, Optional


def build_opencl_vram_workload_script(
    target_vram_bytes: int,
    target_vendor: str,
    target_vendor_id: str,
    target_name: str,
    target_card: str,
    target_slot: str,
    target_id: str,
    target_gpu_index: int,
    target_vram_total: int,
    worker_params: Optional[Dict[str, Any]] = None,
    result_file: str = "",
) -> str:
    params = worker_params or {}
    compute_units = int(params.get("compute_units", 0) or 0)
    max_work_group_size = int(params.get("max_work_group_size", 0) or 0)
    max_clock_mhz = int(params.get("max_clock_mhz", 0) or 0)
    device_class = str(params.get("device_class", "") or "")
    parallelism_hint = int(params.get("parallelism_hint", 1) or 1)
    ramp_step_seconds = max(0.0, float(params.get("ramp_step_seconds", 0.0) or 0.0))
    start_load_fraction = max(0.15, min(1.0, float(params.get("start_load_fraction", 1.0) or 1.0)))
    safe_mode_enabled = bool(params.get("safe_mode_enabled", False))
    return textwrap.dedent(
        f"""
        import atexit
        import ctypes
        import ctypes.util
        import json
        import os
        import re
        import signal
        import sys
        import time

        TARGET_VRAM_BYTES = {int(target_vram_bytes)}
        TARGET_VENDOR = {json.dumps(target_vendor)}
        TARGET_VENDOR_ID = {json.dumps(target_vendor_id)}
        TARGET_NAME = {json.dumps(target_name)}
        TARGET_CARD = {json.dumps(target_card)}
        TARGET_SLOT = {json.dumps(target_slot)}
        TARGET_ID = {json.dumps(target_id)}
        TARGET_GPU_INDEX = {int(target_gpu_index)}
        TARGET_VRAM_TOTAL = {int(target_vram_total)}
        CAP_COMPUTE_UNITS = {compute_units}
        CAP_MAX_WORK_GROUP_SIZE = {max_work_group_size}
        CAP_MAX_CLOCK_MHZ = {max_clock_mhz}
        DEVICE_CLASS = {device_class!r}
        PARALLELISM_HINT = {parallelism_hint}
        RAMP_STEP_SECONDS = {ramp_step_seconds}
        START_LOAD_FRACTION = {start_load_fraction}
        SAFE_MODE_ENABLED = {safe_mode_enabled!r}
        RESULT_FILE = {json.dumps(result_file)}

        state = {{
            "kind": "gpu",
            "mode": "vram",
            "backend": "python_opencl",
            "status": "ok",
            "error_count": 0,
            "verification_passes": 0,
            "vram_mismatch_count": 0,
            "frames": 0,
            "buffer_count": 0,
            "allocated_vram_bytes": 0,
            "target_vram_bytes": TARGET_VRAM_BYTES,
            "allocation_shortfall_bytes": 0,
            "selection_ambiguous": False,
            "selected_opencl_index": -1,
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
            "target_id": TARGET_ID,
            "target_vendor": TARGET_VENDOR,
            "target_slot": TARGET_SLOT,
            "phase": "initializing",
            "phase_history": [],
            "runtime_target_cap_bytes": 0,
            "phase_limit_bytes": 0,
            "last_successful_bytes": 0,
            "allocation_attempts": 0,
            "allocation_failures": 0,
            "allocation_exhausted": False,
            "allocation_touch_count": 0,
            "max_buffer_count": 0,
            "active_fill_buffer_count": 0,
            "safe_mode_enabled": SAFE_MODE_ENABLED,
        }}

        running = True

        def stop(*_):
            global running
            running = False

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        def record_error(message):
            state["error_count"] += 1
            state["status"] = "error"
            state["last_error"] = message

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
            record_error("OpenCL library not found")
            raise SystemExit(11)

        cl = ctypes.CDLL(lib_name)
        cl_int = ctypes.c_int
        cl_uint = ctypes.c_uint
        cl_ulong = ctypes.c_ulonglong
        cl_bool = ctypes.c_uint
        cl_platform_id = ctypes.c_void_p
        cl_device_id = ctypes.c_void_p
        cl_context = ctypes.c_void_p
        cl_command_queue = ctypes.c_void_p
        cl_mem = ctypes.c_void_p
        cl_program = ctypes.c_void_p
        cl_kernel = ctypes.c_void_p
        size_t = ctypes.c_size_t

        CL_SUCCESS = 0
        CL_TRUE = 1
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
        CL_PROGRAM_BUILD_LOG = 0x1183
        CL_MEM_READ_WRITE = 1 << 0

        cl.clGetPlatformIDs.argtypes = [cl_uint, ctypes.POINTER(cl_platform_id), ctypes.POINTER(cl_uint)]
        cl.clGetPlatformIDs.restype = cl_int
        cl.clGetPlatformInfo.argtypes = [cl_platform_id, cl_uint, size_t, ctypes.c_void_p, ctypes.POINTER(size_t)]
        cl.clGetPlatformInfo.restype = cl_int
        cl.clGetDeviceIDs.argtypes = [cl_platform_id, cl_ulong, cl_uint, ctypes.POINTER(cl_device_id), ctypes.POINTER(cl_uint)]
        cl.clGetDeviceIDs.restype = cl_int
        cl.clGetDeviceInfo.argtypes = [cl_device_id, cl_uint, size_t, ctypes.c_void_p, ctypes.POINTER(size_t)]
        cl.clGetDeviceInfo.restype = cl_int
        cl.clCreateContext.argtypes = [ctypes.c_void_p, cl_uint, ctypes.POINTER(cl_device_id), ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(cl_int)]
        cl.clCreateContext.restype = cl_context
        cl.clCreateCommandQueue.argtypes = [cl_context, cl_device_id, cl_ulong, ctypes.POINTER(cl_int)]
        cl.clCreateCommandQueue.restype = cl_command_queue
        cl.clCreateBuffer.argtypes = [cl_context, cl_ulong, size_t, ctypes.c_void_p, ctypes.POINTER(cl_int)]
        cl.clCreateBuffer.restype = cl_mem
        cl.clCreateProgramWithSource.argtypes = [cl_context, cl_uint, ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(size_t), ctypes.POINTER(cl_int)]
        cl.clCreateProgramWithSource.restype = cl_program
        cl.clBuildProgram.argtypes = [cl_program, cl_uint, ctypes.POINTER(cl_device_id), ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p]
        cl.clBuildProgram.restype = cl_int
        cl.clGetProgramBuildInfo.argtypes = [cl_program, cl_device_id, cl_uint, size_t, ctypes.c_void_p, ctypes.POINTER(size_t)]
        cl.clGetProgramBuildInfo.restype = cl_int
        cl.clCreateKernel.argtypes = [cl_program, ctypes.c_char_p, ctypes.POINTER(cl_int)]
        cl.clCreateKernel.restype = cl_kernel
        cl.clSetKernelArg.argtypes = [cl_kernel, cl_uint, size_t, ctypes.c_void_p]
        cl.clSetKernelArg.restype = cl_int
        cl.clEnqueueNDRangeKernel.argtypes = [cl_command_queue, cl_kernel, cl_uint, ctypes.POINTER(size_t), ctypes.POINTER(size_t), ctypes.POINTER(size_t), cl_uint, ctypes.c_void_p, ctypes.c_void_p]
        cl.clEnqueueNDRangeKernel.restype = cl_int
        cl.clEnqueueReadBuffer.argtypes = [cl_command_queue, cl_mem, cl_bool, size_t, size_t, ctypes.c_void_p, cl_uint, ctypes.c_void_p, ctypes.c_void_p]
        cl.clEnqueueReadBuffer.restype = cl_int
        cl.clFinish.argtypes = [cl_command_queue]
        cl.clFinish.restype = cl_int
        cl.clReleaseMemObject.argtypes = [cl_mem]
        cl.clReleaseMemObject.restype = cl_int
        cl.clReleaseKernel.argtypes = [cl_kernel]
        cl.clReleaseKernel.restype = cl_int
        cl.clReleaseProgram.argtypes = [cl_program]
        cl.clReleaseProgram.restype = cl_int
        cl.clReleaseCommandQueue.argtypes = [cl_command_queue]
        cl.clReleaseCommandQueue.restype = cl_int
        cl.clReleaseContext.argtypes = [cl_context]
        cl.clReleaseContext.restype = cl_int

        def check(code, context):
            if int(code) != CL_SUCCESS:
                raise RuntimeError(f"{{context}} failed with OpenCL code {{int(code)}}")

        def get_string(getter, obj, param):
            size = size_t()
            code = getter(obj, param, 0, None, ctypes.byref(size))
            if int(code) != CL_SUCCESS or size.value == 0:
                return ""
            buf = ctypes.create_string_buffer(size.value)
            code = getter(obj, param, size.value, buf, None)
            if int(code) != CL_SUCCESS:
                return ""
            return buf.raw.rstrip(b"\\0").decode("utf-8", "ignore")

        def get_ulong(device, param):
            value = cl_ulong()
            code = cl.clGetDeviceInfo(device, param, ctypes.sizeof(value), ctypes.byref(value), None)
            if int(code) != CL_SUCCESS:
                return 0
            return int(value.value)

        def get_uint(device, param):
            value = cl_uint()
            code = cl.clGetDeviceInfo(device, param, ctypes.sizeof(value), ctypes.byref(value), None)
            if int(code) != CL_SUCCESS:
                return 0
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
            code = cl.clGetDeviceInfo(
                device,
                CL_DEVICE_PCI_BUS_INFO_KHR,
                ctypes.sizeof(value),
                ctypes.byref(value),
                None,
            )
            if int(code) != CL_SUCCESS:
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
            preference = 0.0
            if vendor_matches(target_vendor, platform_vendor):
                preference += 220.0
            if target_vendor == "amd":
                if "accelerated parallel processing" in platform_name:
                    preference += 180.0
                if "advanced micro devices" in platform_vendor:
                    preference += 140.0
                if "rusticl" in platform_name:
                    preference -= 80.0
            elif target_vendor == "nvidia":
                if "nvidia" in platform_name or "nvidia" in platform_vendor:
                    preference += 180.0
                if "rusticl" in platform_name:
                    preference -= 40.0
            elif target_vendor == "intel":
                if "intel" in platform_name or "intel" in platform_vendor:
                    preference += 140.0
            return preference

        def device_score(info):
            score = 0.0
            target_vendor_id = str(TARGET_VENDOR_ID or "").strip().lower().removeprefix("0x")
            vendor = str(info.get("vendor", "")).lower()
            name = str(info.get("name", "")).lower()
            vendor_id = str(info.get("vendor_id", "") or "").strip().lower().removeprefix("0x")
            target_slot = normalize_pci_slot(TARGET_SLOT or TARGET_ID)
            device_slot = normalize_pci_slot(info.get("pci_slot", ""))
            vendor_match = False
            if target_slot and device_slot:
                if target_slot == device_slot:
                    score += 2500.0
                else:
                    return -1000000.0
            if target_vendor_id and vendor_id and target_vendor_id == vendor_id:
                vendor_match = True
                score += 320.0
            if vendor_matches(TARGET_VENDOR, vendor, name, str(info.get("platform_vendor", "")).lower()):
                vendor_match = True
                score += 1000.0
            if TARGET_VENDOR and not vendor_match:
                return -1000000.0
            if TARGET_NAME:
                tokens = [
                    token
                    for token in __import__("re").split(r"[^a-z0-9]+", str(TARGET_NAME).lower())
                    if len(token) >= 3 and token not in {{str(TARGET_VENDOR).lower(), "gpu", "graphics"}}
                ]
                score += min(160.0, 40.0 * sum(1 for token in tokens if token in name))
            if TARGET_CARD and TARGET_CARD.lower() in name:
                score += 120.0
            score += platform_preference(info)
            expected = TARGET_VRAM_TOTAL or TARGET_VRAM_BYTES
            mem = int(info.get("global_mem_bytes", 0) or 0)
            if expected > 0 and mem > 0:
                ratio = abs(mem - expected) / float(max(mem, expected))
                score += max(0.0, 600.0 * (1.0 - min(1.0, ratio)))
            if not device_slot and int(info.get("opencl_index", -1)) == TARGET_GPU_INDEX:
                score += 75.0
            score -= float(int(info.get("opencl_index", 0))) * 0.01
            return score

        def pattern_value(word_index, seed, buffer_index):
            value = (int(word_index) ^ ((int(seed) * 2654435761) & 0xFFFFFFFF) ^ (((int(buffer_index) + 1) * 2246822519) & 0xFFFFFFFF)) & 0xFFFFFFFF
            value ^= (value >> 16)
            value = (value * 0x7FEB352D) & 0xFFFFFFFF
            value ^= (value >> 15)
            value = (value * 0x846CA68B) & 0xFFFFFFFF
            value ^= (value >> 16)
            return value & 0xFFFFFFFF

        def current_load_fraction(started_monotonic):
            if RAMP_STEP_SECONDS <= 0:
                return 1.0
            elapsed = max(0.0, time.monotonic() - started_monotonic)
            progress = min(1.0, elapsed / max(0.001, RAMP_STEP_SECONDS * 3.0))
            return min(1.0, START_LOAD_FRACTION + (1.0 - START_LOAD_FRACTION) * progress)

        def current_phase(started_monotonic):
            elapsed = max(0.0, time.monotonic() - started_monotonic)
            if SAFE_MODE_ENABLED:
                allocation_window = max(5.0, RAMP_STEP_SECONDS)
                fill_window = max(10.0, RAMP_STEP_SECONDS * 2.0)
                if DEVICE_CLASS == "discrete":
                    allocation_window = max(12.0, RAMP_STEP_SECONDS * 1.35)
                    fill_window = max(allocation_window + 18.0, RAMP_STEP_SECONDS * 3.5)
                if elapsed < allocation_window:
                    return "allocation_only"
                if elapsed < fill_window:
                    return "fill"
            return "verify"

        def set_phase(name):
            if state.get("phase") == name:
                return
            state["phase"] = name
            history = list(state.get("phase_history") or [])
            history.append({{"phase": name, "timestamp": time.time()}})
            state["phase_history"] = history[-8:]

        def discrete_runtime_target_cap(device_global_mem_bytes, max_alloc_bytes, target_bytes):
            if DEVICE_CLASS != "discrete":
                return max(64 * 1024 * 1024, int(target_bytes))
            caps = [max(256 * 1024 * 1024, int(target_bytes))]
            if device_global_mem_bytes > 0:
                safety_fraction = 0.90 if SAFE_MODE_ENABLED else 0.95
                caps.append(max(256 * 1024 * 1024, int(device_global_mem_bytes * safety_fraction)))
            return max(256 * 1024 * 1024, min(caps))

        def phase_target_limit_bytes(runtime_target_bytes, load_fraction, phase_name):
            limit = max(64 * 1024 * 1024, min(runtime_target_bytes, int(round(runtime_target_bytes * load_fraction))))
            if phase_name == "allocation_only":
                limit = min(limit, max(128 * 1024 * 1024, int(runtime_target_bytes * 0.35)))
            elif phase_name == "fill":
                limit = min(limit, max(256 * 1024 * 1024, int(runtime_target_bytes * 0.70)))
            return max(64 * 1024 * 1024, min(runtime_target_bytes, limit))

        def fill_buffer_count(buffer_count, load_fraction, phase_name):
            if buffer_count <= 0:
                return 0
            if phase_name == "allocation_only":
                return 0
            if phase_name == "fill":
                fraction = max(0.25, min(0.70, load_fraction))
            else:
                fraction = max(0.50, min(1.0, load_fraction))
            count = max(1, min(buffer_count, int(round(buffer_count * fraction))))
            if SAFE_MODE_ENABLED and DEVICE_CLASS == "discrete":
                capacity_hint = max(int(TARGET_VRAM_TOTAL or 0), int(TARGET_VRAM_BYTES or 0))
                fill_cap = 2
                verify_cap = 1
                if capacity_hint >= 64 * 1024 ** 3:
                    fill_cap = 32
                    verify_cap = 24
                elif capacity_hint >= 24 * 1024 ** 3:
                    fill_cap = 12
                    verify_cap = 8
                elif capacity_hint >= 12 * 1024 ** 3:
                    fill_cap = 6
                    verify_cap = 4
                if phase_name == "fill":
                    count = min(count, fill_cap)
                else:
                    count = min(count, verify_cap)
            elif SAFE_MODE_ENABLED:
                count = min(count, 24)
            return count

        context = None
        queue = None
        program = None
        kernel = None
        buffers = []
        buffer_last_seed = []
        buffer_has_data = []
        write_result()

        try:
            platform_count = cl_uint()
            check(cl.clGetPlatformIDs(0, None, ctypes.byref(platform_count)), "clGetPlatformIDs")
            if platform_count.value == 0:
                raise RuntimeError("no OpenCL platforms found")
            platforms = (cl_platform_id * platform_count.value)()
            check(cl.clGetPlatformIDs(platform_count, platforms, None), "clGetPlatformIDs(list)")

            devices = []
            opencl_index = 0
            for platform in platforms:
                platform_name = get_string(cl.clGetPlatformInfo, platform, CL_PLATFORM_NAME)
                platform_vendor = get_string(cl.clGetPlatformInfo, platform, CL_PLATFORM_VENDOR)
                platform_version = get_string(cl.clGetPlatformInfo, platform, CL_PLATFORM_VERSION)
                device_count = cl_uint()
                code = cl.clGetDeviceIDs(platform, CL_DEVICE_TYPE_GPU, 0, None, ctypes.byref(device_count))
                if int(code) != CL_SUCCESS or device_count.value == 0:
                    continue
                platform_devices = (cl_device_id * device_count.value)()
                check(cl.clGetDeviceIDs(platform, CL_DEVICE_TYPE_GPU, device_count, platform_devices, None), "clGetDeviceIDs(list)")
                for device in platform_devices:
                    devices.append(
                        {{
                            "platform": platform,
                            "device": device,
                            "platform_name": platform_name,
                            "platform_vendor": platform_vendor,
                            "platform_version": platform_version,
                            "opencl_index": opencl_index,
                            "name": get_string(cl.clGetDeviceInfo, device, CL_DEVICE_NAME),
                            "vendor": get_string(cl.clGetDeviceInfo, device, CL_DEVICE_VENDOR),
                            "vendor_id": format(get_uint(device, CL_DEVICE_VENDOR_ID), "04x"),
                            "global_mem_bytes": get_ulong(device, CL_DEVICE_GLOBAL_MEM_SIZE),
                            "max_alloc_bytes": get_ulong(device, CL_DEVICE_MAX_MEM_ALLOC_SIZE),
                            "pci_slot": get_pci_slot(device),
                        }}
                    )
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

            ranked = sorted(((device_score(info), info) for info in devices), key=lambda item: item[0], reverse=True)
            if (
                len(ranked) > 1
                and ranked[0][1].get("identity_key") != ranked[1][1].get("identity_key")
                and abs(ranked[0][0] - ranked[1][0]) < 0.5
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
            if best_score <= -999000.0:
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
            state["selected_opencl_index"] = int(selected["opencl_index"])
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
            write_result()

            err = cl_int()
            device_array = (cl_device_id * 1)(cl_device_id(selected["device"]))
            context = cl.clCreateContext(None, 1, device_array, None, None, ctypes.byref(err))
            check(err.value, "clCreateContext")
            queue = cl.clCreateCommandQueue(context, selected["device"], 0, ctypes.byref(err))
            check(err.value, "clCreateCommandQueue")

            source = b'''
            __kernel void fill_pattern(__global uint *buffer, uint seed, uint buffer_index) {{
                size_t gid = get_global_id(0);
                uint value = ((uint)gid) ^ (seed * 2654435761u) ^ ((buffer_index + 1u) * 2246822519u);
                value ^= (value >> 16);
                value *= 0x7FEB352Du;
                value ^= (value >> 15);
                value *= 0x846CA68Bu;
                value ^= (value >> 16);
                buffer[gid] = value;
            }}
            '''
            source_buffer = ctypes.c_char_p(source)
            source_length = size_t(len(source))
            program = cl.clCreateProgramWithSource(context, 1, ctypes.byref(source_buffer), ctypes.byref(source_length), ctypes.byref(err))
            check(err.value, "clCreateProgramWithSource")
            build_code = cl.clBuildProgram(program, 1, device_array, None, None, None)
            if int(build_code) != CL_SUCCESS:
                size = size_t()
                cl.clGetProgramBuildInfo(program, selected["device"], CL_PROGRAM_BUILD_LOG, 0, None, ctypes.byref(size))
                log = ""
                if size.value:
                    buf = ctypes.create_string_buffer(size.value)
                    cl.clGetProgramBuildInfo(program, selected["device"], CL_PROGRAM_BUILD_LOG, size.value, buf, None)
                    log = buf.raw.rstrip(b"\\0").decode("utf-8", "ignore")
                raise RuntimeError(f"clBuildProgram failed: {{log or build_code}}")
            kernel = cl.clCreateKernel(program, b"fill_pattern", ctypes.byref(err))
            check(err.value, "clCreateKernel")

            target_bytes = max(64 * 1024 * 1024, int(TARGET_VRAM_BYTES))
            compute_units = max(1, int(CAP_COMPUTE_UNITS) or 16)
            clock_hint = max(1000, int(CAP_MAX_CLOCK_MHZ) or 1800)
            parallelism_hint = max(1, int(PARALLELISM_HINT) or 1)
            max_alloc = max(64 * 1024 * 1024, int(selected["max_alloc_bytes"]) or 0)
            runtime_target_bytes = min(target_bytes, discrete_runtime_target_cap(int(selected["global_mem_bytes"]), max_alloc, target_bytes))
            state["runtime_target_cap_bytes"] = runtime_target_bytes
            chunk_cap = 128 * 1024 * 1024 if DEVICE_CLASS == "discrete" and SAFE_MODE_ENABLED else 512 * 1024 * 1024
            if DEVICE_CLASS != "discrete":
                chunk_cap = 64 * 1024 * 1024 if SAFE_MODE_ENABLED else 128 * 1024 * 1024
            chunk_bytes = min(max_alloc, chunk_cap, max(64 * 1024 * 1024, target_bytes))
            chunk_bytes -= chunk_bytes % 4096
            if chunk_bytes <= 0:
                chunk_bytes = 64 * 1024 * 1024
            max_buffer_count = max(32, ((runtime_target_bytes + chunk_bytes - 1) // max(4096, chunk_bytes)) + 8)
            if SAFE_MODE_ENABLED and DEVICE_CLASS == "discrete":
                max_buffer_count = min(2048, max(512, max_buffer_count))
            elif SAFE_MODE_ENABLED:
                max_buffer_count = min(1024, max(128, max_buffer_count))
            else:
                max_buffer_count = min(4096, max_buffer_count)
            state["max_buffer_count"] = int(max_buffer_count)
            write_result()

            sample_words = max(256, min(1024, 256 + compute_units * 8 + parallelism_hint * 32 + clock_hint // 80))
            sample_array = (cl_uint * sample_words)()
            started_monotonic = time.monotonic()
            verify_interval_seconds = 0.75
            if SAFE_MODE_ENABLED and DEVICE_CLASS == "discrete":
                verify_interval_seconds = 1.0
            elif SAFE_MODE_ENABLED:
                verify_interval_seconds = 1.25
            fill_interval_seconds = 0.0
            if SAFE_MODE_ENABLED and DEVICE_CLASS == "discrete":
                fill_interval_seconds = 1.0
                capacity_hint = max(int(TARGET_VRAM_TOTAL or 0), int(TARGET_VRAM_BYTES or 0))
                if capacity_hint >= 64 * 1024 ** 3:
                    fill_interval_seconds = 0.05
                elif capacity_hint >= 24 * 1024 ** 3:
                    fill_interval_seconds = 0.1
                elif capacity_hint >= 12 * 1024 ** 3:
                    fill_interval_seconds = 0.25
            last_verify_monotonic = started_monotonic - verify_interval_seconds
            last_fill_monotonic = started_monotonic - fill_interval_seconds
            state["verification_interval_seconds"] = verify_interval_seconds
            state["fill_interval_seconds"] = fill_interval_seconds

            def enqueue_fill(buffer_index, seed_value):
                buffer_handle, buffer_bytes = buffers[buffer_index]
                word_count = max(1, buffer_bytes // 4)
                seed = cl_uint(int(seed_value) & 0xFFFFFFFF)
                buffer_index_arg = cl_uint(buffer_index & 0xFFFFFFFF)
                word_count_size = size_t(word_count)
                check(cl.clSetKernelArg(kernel, 0, ctypes.sizeof(cl_mem), ctypes.byref(buffer_handle)), "clSetKernelArg(buffer)")
                check(cl.clSetKernelArg(kernel, 1, ctypes.sizeof(cl_uint), ctypes.byref(seed)), "clSetKernelArg(seed)")
                check(cl.clSetKernelArg(kernel, 2, ctypes.sizeof(cl_uint), ctypes.byref(buffer_index_arg)), "clSetKernelArg(buffer_index)")
                check(
                    cl.clEnqueueNDRangeKernel(queue, kernel, 1, None, ctypes.byref(word_count_size), None, 0, None, None),
                    "clEnqueueNDRangeKernel",
                )
                buffer_last_seed[buffer_index] = int(seed.value)
                buffer_has_data[buffer_index] = True

            while running:
                load_fraction = current_load_fraction(started_monotonic)
                phase_name = current_phase(started_monotonic)
                set_phase(phase_name)
                desired_target_bytes = phase_target_limit_bytes(runtime_target_bytes, load_fraction, phase_name)
                state["active_load_fraction"] = round(load_fraction, 3)
                state["active_target_vram_bytes"] = desired_target_bytes
                state["phase_limit_bytes"] = desired_target_bytes
                allocation_budget = 1 if SAFE_MODE_ENABLED else 4
                allocations_this_frame = 0
                while (
                    not state["allocation_exhausted"]
                    and state["allocated_vram_bytes"] < desired_target_bytes
                    and len(buffers) < max_buffer_count
                    and allocations_this_frame < allocation_budget
                ):
                    remaining = desired_target_bytes - state["allocated_vram_bytes"]
                    remaining_to_runtime_target = runtime_target_bytes - state["allocated_vram_bytes"]
                    if remaining < chunk_bytes and desired_target_bytes < runtime_target_bytes:
                        break
                    request_bytes = min(chunk_bytes, remaining, remaining_to_runtime_target)
                    request_bytes -= request_bytes % 4096
                    if request_bytes < 4096:
                        break
                    state["allocation_attempts"] += 1
                    buffer_handle = cl_mem(cl.clCreateBuffer(context, CL_MEM_READ_WRITE, request_bytes, None, ctypes.byref(err)))
                    if int(err.value) != CL_SUCCESS or not buffer_handle:
                        state["allocation_failures"] += 1
                        if request_bytes > 64 * 1024 * 1024:
                            chunk_bytes = max(64 * 1024 * 1024, request_bytes // 2)
                            write_result()
                            continue
                        state["allocation_exhausted"] = True
                        write_result()
                        break
                    buffers.append((buffer_handle, request_bytes))
                    buffer_last_seed.append(0)
                    buffer_has_data.append(False)
                    state["buffer_count"] = len(buffers)
                    state["allocated_vram_bytes"] += int(request_bytes)
                    state["last_successful_bytes"] = int(state["allocated_vram_bytes"])
                    allocations_this_frame += 1
                    new_buffer_index = len(buffers) - 1
                    enqueue_fill(new_buffer_index, state["frames"] + 1 + new_buffer_index * 17)
                    check(cl.clFinish(queue), "clFinish")
                    last_fill_monotonic = time.monotonic()
                    state["allocation_touch_count"] += 1
                    write_result()
                state["allocation_shortfall_bytes"] = max(0, target_bytes - state["allocated_vram_bytes"])
                now_monotonic = time.monotonic()
                fill_count = fill_buffer_count(len(buffers), load_fraction, phase_name)
                if (
                    SAFE_MODE_ENABLED
                    and DEVICE_CLASS == "discrete"
                    and phase_name == "verify"
                    and fill_interval_seconds > 0.0
                    and (now_monotonic - last_fill_monotonic) < fill_interval_seconds
                ):
                    fill_count = 0
                state["active_fill_buffer_count"] = fill_count
                if fill_count > 0 and buffers:
                    start_index = int(state["frames"] % max(1, len(buffers)))
                    fill_indexes = [((start_index + offset) % len(buffers)) for offset in range(fill_count)]
                else:
                    fill_indexes = []
                for buffer_index in fill_indexes:
                    enqueue_fill(buffer_index, state["frames"] + 1 + buffer_index * 17)
                if fill_indexes:
                    check(cl.clFinish(queue), "clFinish")
                    last_fill_monotonic = time.monotonic()
                now_monotonic = time.monotonic()
                if (
                    phase_name == "verify"
                    and buffers
                    and (now_monotonic - last_verify_monotonic) >= verify_interval_seconds
                ):
                    if SAFE_MODE_ENABLED and DEVICE_CLASS == "discrete":
                        preferred_index = None
                        for candidate_index in range(len(buffers) - 1, -1, -1):
                            if candidate_index < len(buffer_has_data) and buffer_has_data[candidate_index]:
                                preferred_index = candidate_index
                                break
                        if preferred_index is None:
                            preferred_index = len(buffers) - 1
                        verify_indices = [preferred_index]
                    else:
                        verify_indices = sorted({{0, len(buffers) // 2, len(buffers) - 1}})
                    state["active_verify_indices"] = list(verify_indices)
                    for verify_index in verify_indices:
                        if verify_index >= len(buffer_has_data) or not buffer_has_data[verify_index]:
                            continue
                        buffer_handle, buffer_bytes = buffers[verify_index]
                        sample_bytes = min(buffer_bytes, sample_words * 4)
                        if sample_bytes < 4:
                            continue
                        check(
                            cl.clEnqueueReadBuffer(queue, buffer_handle, CL_TRUE, 0, sample_bytes, ctypes.byref(sample_array), 0, None, None),
                            "clEnqueueReadBuffer",
                        )
                        seed_value = int(buffer_last_seed[verify_index]) & 0xFFFFFFFF
                        words_to_check = sample_bytes // 4
                        for word_index in range(words_to_check):
                            expected = pattern_value(word_index, seed_value, verify_index)
                            actual = int(sample_array[word_index]) & 0xFFFFFFFF
                            if actual != expected:
                                state["vram_mismatch_count"] += 1
                                record_error(
                                    f"OpenCL VRAM mismatch on buffer {{verify_index}} word {{word_index}}: expected={{expected}} actual={{actual}}"
                                )
                                break
                        state["verification_passes"] += 1
                    last_verify_monotonic = now_monotonic
                state["frames"] += 1
                if state["frames"] % 4 == 0:
                    write_result()
                if SAFE_MODE_ENABLED and DEVICE_CLASS == "discrete":
                    time.sleep(0.006)
                elif SAFE_MODE_ENABLED:
                    time.sleep(0.003)
                else:
                    time.sleep(0.002)
        except Exception as exc:
            record_error(str(exc))
            raise SystemExit(12)
        finally:
            for buffer_handle, _ in buffers:
                try:
                    cl.clReleaseMemObject(buffer_handle)
                except Exception:
                    pass
            if kernel is not None:
                try:
                    cl.clReleaseKernel(kernel)
                except Exception:
                    pass
            if program is not None:
                try:
                    cl.clReleaseProgram(program)
                except Exception:
                    pass
            if queue is not None:
                try:
                    cl.clReleaseCommandQueue(queue)
                except Exception:
                    pass
            if context is not None:
                try:
                    cl.clReleaseContext(context)
                except Exception:
                    pass
        """
    ).strip()

def _egl_probe_script(self) -> str:
    return textwrap.dedent(
        """
        import ctypes
        import ctypes.util
        import json
        import os

        EGL = ctypes.CDLL(ctypes.util.find_library("EGL"))
        GLES = ctypes.CDLL(ctypes.util.find_library("GLESv2"))
        EGLDisplay = ctypes.c_void_p
        EGLConfig = ctypes.c_void_p
        EGLContext = ctypes.c_void_p
        EGLSurface = ctypes.c_void_p
        EGLint = ctypes.c_int
        EGLenum = ctypes.c_uint
        EGLBoolean = ctypes.c_uint
        EGL_NO_CONTEXT = EGLContext(0)
        EGL_NONE = 0x3038
        EGL_SURFACE_TYPE = 0x3033
        EGL_PBUFFER_BIT = 0x0001
        EGL_RENDERABLE_TYPE = 0x3040
        EGL_OPENGL_ES2_BIT = 0x0004
        EGL_RED_SIZE = 0x3024
        EGL_GREEN_SIZE = 0x3023
        EGL_BLUE_SIZE = 0x3022
        EGL_ALPHA_SIZE = 0x3021
        EGL_DEPTH_SIZE = 0x3025
        EGL_CONTEXT_CLIENT_VERSION = 0x3098
        EGL_WIDTH = 0x3057
        EGL_HEIGHT = 0x3056
        EGL_OPENGL_ES_API = 0x30A0
        EGL_EXTENSIONS = 0x3055
        EGL_PLATFORM_DEVICE_EXT = 0x313F
        EGL_PLATFORM_SURFACELESS_MESA = 0x31DD
        EGL_DRM_DEVICE_FILE_EXT = 0x3233
        EGL_DRM_RENDER_NODE_FILE_EXT = 0x3377
        GL_VENDOR = 0x1F00
        GL_RENDERER = 0x1F01

        def as_text(value):
            if not value:
                return ""
            if isinstance(value, bytes):
                return value.decode("utf-8", "ignore")
            return str(value)

        def norm_node(path):
            text = str(path or "").strip()
            if not text:
                return ""
            try:
                return os.path.realpath(text)
            except Exception:
                return text

        def query_egl_device_display(get_platform_display):
            if not get_platform_display:
                return EGLDisplay(0), {}
            target_nodes = {
                norm_node(os.environ.get("LVS_EGL_TARGET_CARD_NODE", "")),
                norm_node(os.environ.get("LVS_EGL_TARGET_RENDER_NODE", "")),
            }
            target_nodes.discard("")
            if not target_nodes:
                return EGLDisplay(0), {}
            query_devices_addr = EGL.eglGetProcAddress(b"eglQueryDevicesEXT")
            query_device_string_addr = EGL.eglGetProcAddress(b"eglQueryDeviceStringEXT")
            if not query_devices_addr or not query_device_string_addr:
                return EGLDisplay(0), {}
            EGLDeviceEXT = ctypes.c_void_p
            QueryDevices = ctypes.CFUNCTYPE(EGLBoolean, EGLint, ctypes.POINTER(EGLDeviceEXT), ctypes.POINTER(EGLint))
            QueryDeviceString = ctypes.CFUNCTYPE(ctypes.c_char_p, EGLDeviceEXT, EGLint)
            query_devices = QueryDevices(query_devices_addr)
            query_device_string = QueryDeviceString(query_device_string_addr)
            count = EGLint()
            devices = (EGLDeviceEXT * 64)()
            if not query_devices(64, devices, ctypes.byref(count)):
                return EGLDisplay(0), {}
            for index in range(max(0, int(count.value))):
                device = devices[index]
                drm_node = as_text(query_device_string(device, EGL_DRM_DEVICE_FILE_EXT))
                render_node = as_text(query_device_string(device, EGL_DRM_RENDER_NODE_FILE_EXT))
                node_matches = {
                    norm_node(drm_node),
                    norm_node(render_node),
                }
                node_matches.discard("")
                if not target_nodes.intersection(node_matches):
                    continue
                display = get_platform_display(EGL_PLATFORM_DEVICE_EXT, device, None)
                if display:
                    return display, {
                        "index": index,
                        "drm_device_file": drm_node,
                        "drm_render_node": render_node,
                        "selection": "egl_device",
                    }
            return EGLDisplay(0), {}

        result = {"available": False, "vendor": "", "renderer": "", "reason": "", "egl_device_exact_match": False, "egl_selected_device": {}}
        try:
            PFN = ctypes.CFUNCTYPE(EGLDisplay, EGLenum, ctypes.c_void_p, ctypes.POINTER(EGLint))
            EGL.eglGetProcAddress.restype = ctypes.c_void_p
            addr = EGL.eglGetProcAddress(b"eglGetPlatformDisplayEXT")
            get_platform_display = PFN(addr) if addr else None
            EGL.eglGetDisplay.restype = EGLDisplay
            EGL.eglInitialize.argtypes = [EGLDisplay, ctypes.POINTER(EGLint), ctypes.POINTER(EGLint)]
            EGL.eglInitialize.restype = EGLBoolean
            EGL.eglBindAPI.argtypes = [EGLenum]
            EGL.eglBindAPI.restype = EGLBoolean
            EGL.eglChooseConfig.argtypes = [EGLDisplay, ctypes.POINTER(EGLint), ctypes.POINTER(EGLConfig), EGLint, ctypes.POINTER(EGLint)]
            EGL.eglChooseConfig.restype = EGLBoolean
            EGL.eglCreatePbufferSurface.argtypes = [EGLDisplay, EGLConfig, ctypes.POINTER(EGLint)]
            EGL.eglCreatePbufferSurface.restype = EGLSurface
            EGL.eglCreateContext.argtypes = [EGLDisplay, EGLConfig, EGLContext, ctypes.POINTER(EGLint)]
            EGL.eglCreateContext.restype = EGLContext
            EGL.eglMakeCurrent.argtypes = [EGLDisplay, EGLSurface, EGLSurface, EGLContext]
            EGL.eglMakeCurrent.restype = EGLBoolean
            GLES.glGetString.argtypes = [ctypes.c_uint]
            GLES.glGetString.restype = ctypes.c_char_p

            display, selected_device = query_egl_device_display(get_platform_display)
            if not display:
                selected_device = {"selection": "surfaceless"}
                display = get_platform_display(EGL_PLATFORM_SURFACELESS_MESA, None, None) if get_platform_display else EGL.eglGetDisplay(ctypes.c_void_p(0))
            major = EGLint()
            minor = EGLint()
            if not display or not EGL.eglInitialize(display, ctypes.byref(major), ctypes.byref(minor)):
                if selected_device.get("selection") == "egl_device":
                    selected_device["fallback_reason"] = "eglInitialize failed for matched EGLDevice"
                    selected_device["selection"] = "surfaceless_after_egl_device_init_failed"
                    display = get_platform_display(EGL_PLATFORM_SURFACELESS_MESA, None, None) if get_platform_display else EGL.eglGetDisplay(ctypes.c_void_p(0))
                    if not display or not EGL.eglInitialize(display, ctypes.byref(major), ctypes.byref(minor)):
                        raise RuntimeError("eglInitialize failed")
                else:
                    raise RuntimeError("eglInitialize failed")
            if not EGL.eglBindAPI(EGL_OPENGL_ES_API):
                raise RuntimeError("eglBindAPI failed")
            attrs = (EGLint * 15)(
                EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
                EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT,
                EGL_RED_SIZE, 8,
                EGL_GREEN_SIZE, 8,
                EGL_BLUE_SIZE, 8,
                EGL_ALPHA_SIZE, 8,
                EGL_DEPTH_SIZE, 24,
                EGL_NONE,
            )
            config = EGLConfig()
            count = EGLint()
            if not EGL.eglChooseConfig(display, attrs, ctypes.byref(config), 1, ctypes.byref(count)) or not count.value:
                raise RuntimeError("eglChooseConfig failed")
            surf_attrs = (EGLint * 5)(EGL_WIDTH, 16, EGL_HEIGHT, 16, EGL_NONE)
            surface = EGL.eglCreatePbufferSurface(display, config, surf_attrs)
            ctx_attrs = (EGLint * 3)(EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE)
            context = EGL.eglCreateContext(display, config, EGL_NO_CONTEXT, ctx_attrs)
            if not surface or not context or not EGL.eglMakeCurrent(display, surface, surface, context):
                raise RuntimeError("eglMakeCurrent failed")
            result["vendor"] = as_text(GLES.glGetString(GL_VENDOR))
            result["renderer"] = as_text(GLES.glGetString(GL_RENDERER))
            result["egl_selected_device"] = selected_device
            result["egl_device_exact_match"] = selected_device.get("selection") == "egl_device"
            result["available"] = True
        except Exception as exc:
            result["reason"] = str(exc)
        print(json.dumps(result))
        """
    ).strip()
