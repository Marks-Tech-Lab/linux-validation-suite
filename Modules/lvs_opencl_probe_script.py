from __future__ import annotations

import textwrap


def build_opencl_probe_script() -> str:
    return textwrap.dedent(
        """
        import ctypes
        import ctypes.util
        import json
        import os

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
        result = {
            "available": False,
            "reason": "",
            "library": lib_name or "",
            "devices": [],
            "platform_count": 0,
            "platforms": [],
        }
        if not lib_name:
            result["reason"] = "OpenCL library not found"
            print(json.dumps(result))
            raise SystemExit(0)

        try:
            cl = ctypes.CDLL(lib_name)
            cl_int = ctypes.c_int
            cl_uint = ctypes.c_uint
            cl_ulong = ctypes.c_ulonglong
            cl_platform_id = ctypes.c_void_p
            cl_device_id = ctypes.c_void_p
            size_t = ctypes.c_size_t
            CL_SUCCESS = 0
            CL_DEVICE_TYPE_GPU = 1 << 2
            CL_PLATFORM_VERSION = 0x0901
            CL_PLATFORM_NAME = 0x0902
            CL_PLATFORM_VENDOR = 0x0903
            CL_DEVICE_VENDOR_ID = 0x1001
            CL_DEVICE_NAME = 0x102B
            CL_DEVICE_VENDOR = 0x102C
            CL_DEVICE_MAX_COMPUTE_UNITS = 0x1002
            CL_DEVICE_MAX_WORK_GROUP_SIZE = 0x1004
            CL_DEVICE_MAX_CLOCK_FREQUENCY = 0x100C
            CL_DEVICE_GLOBAL_MEM_SIZE = 0x101F
            CL_DEVICE_MAX_MEM_ALLOC_SIZE = 0x1010
            CL_DEVICE_PCI_BUS_INFO_KHR = 0x410F

            cl.clGetPlatformIDs.argtypes = [cl_uint, ctypes.POINTER(cl_platform_id), ctypes.POINTER(cl_uint)]
            cl.clGetPlatformIDs.restype = cl_int
            cl.clGetPlatformInfo.argtypes = [cl_platform_id, cl_uint, size_t, ctypes.c_void_p, ctypes.POINTER(size_t)]
            cl.clGetPlatformInfo.restype = cl_int
            cl.clGetDeviceIDs.argtypes = [cl_platform_id, cl_ulong, cl_uint, ctypes.POINTER(cl_device_id), ctypes.POINTER(cl_uint)]
            cl.clGetDeviceIDs.restype = cl_int
            cl.clGetDeviceInfo.argtypes = [cl_device_id, cl_uint, size_t, ctypes.c_void_p, ctypes.POINTER(size_t)]
            cl.clGetDeviceInfo.restype = cl_int

            def get_string(getter, obj, param):
                size = size_t()
                code = getter(obj, param, 0, None, ctypes.byref(size))
                if code != CL_SUCCESS or size.value == 0:
                    return ""
                buf = ctypes.create_string_buffer(size.value)
                code = getter(obj, param, size.value, buf, None)
                if code != CL_SUCCESS:
                    return ""
                return buf.raw.rstrip(b"\\0").decode("utf-8", "ignore")

            def get_ulong(device, param):
                value = cl_ulong()
                code = cl.clGetDeviceInfo(device, param, ctypes.sizeof(value), ctypes.byref(value), None)
                if code != CL_SUCCESS:
                    return 0
                return int(value.value)

            def get_uint(device, param):
                value = cl_uint()
                code = cl.clGetDeviceInfo(device, param, ctypes.sizeof(value), ctypes.byref(value), None)
                if code != CL_SUCCESS:
                    return 0
                return int(value.value)

            def get_size_t(device, param):
                value = size_t()
                code = cl.clGetDeviceInfo(device, param, ctypes.sizeof(value), ctypes.byref(value), None)
                if code != CL_SUCCESS:
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
                if code != CL_SUCCESS:
                    return ""
                return f"{int(value.pci_domain):04x}:{int(value.pci_bus):02x}:{int(value.pci_device):02x}.{int(value.pci_function)}"

            def identity_key(info):
                vendor = str(info.get("vendor", "")).strip().lower()
                name = str(info.get("name", "")).strip().lower()
                mem = int(info.get("global_mem_bytes", 0) or 0)
                bucket = mem // max(1, 256 * 1024 * 1024)
                return f"{vendor}|{name}|{bucket}"

            platform_count = cl_uint()
            code = cl.clGetPlatformIDs(0, None, ctypes.byref(platform_count))
            if code != CL_SUCCESS:
                raise RuntimeError(f"clGetPlatformIDs failed with {code}")
            result["platform_count"] = int(platform_count.value)
            if platform_count.value == 0:
                result["reason"] = "no OpenCL platforms found"
                print(json.dumps(result))
                raise SystemExit(0)
            platforms = (cl_platform_id * platform_count.value)()
            code = cl.clGetPlatformIDs(platform_count, platforms, None)
            if code != CL_SUCCESS:
                raise RuntimeError(f"clGetPlatformIDs(list) failed with {code}")

            devices = []
            platforms_info = []
            gpu_index = 0
            for platform in platforms:
                platform_name = get_string(cl.clGetPlatformInfo, platform, CL_PLATFORM_NAME)
                platform_vendor = get_string(cl.clGetPlatformInfo, platform, CL_PLATFORM_VENDOR)
                platform_version = get_string(cl.clGetPlatformInfo, platform, CL_PLATFORM_VERSION)
                platforms_info.append(
                    {
                        "name": platform_name,
                        "vendor": platform_vendor,
                        "version": platform_version,
                    }
                )
                device_count = cl_uint()
                code = cl.clGetDeviceIDs(platform, CL_DEVICE_TYPE_GPU, 0, None, ctypes.byref(device_count))
                if code != CL_SUCCESS or device_count.value == 0:
                    continue
                platform_devices = (cl_device_id * device_count.value)()
                code = cl.clGetDeviceIDs(platform, CL_DEVICE_TYPE_GPU, device_count, platform_devices, None)
                if code != CL_SUCCESS:
                    continue
                for device in platform_devices:
                    devices.append(
                        {
                            "opencl_index": gpu_index,
                            "platform_name": platform_name,
                            "platform_vendor": platform_vendor,
                            "platform_version": platform_version,
                            "name": get_string(cl.clGetDeviceInfo, device, CL_DEVICE_NAME),
                            "vendor": get_string(cl.clGetDeviceInfo, device, CL_DEVICE_VENDOR),
                            "vendor_id": format(get_uint(device, CL_DEVICE_VENDOR_ID), "04x"),
                            "compute_units": get_uint(device, CL_DEVICE_MAX_COMPUTE_UNITS),
                            "max_work_group_size": get_size_t(device, CL_DEVICE_MAX_WORK_GROUP_SIZE),
                            "max_clock_mhz": get_uint(device, CL_DEVICE_MAX_CLOCK_FREQUENCY),
                            "global_mem_bytes": get_ulong(device, CL_DEVICE_GLOBAL_MEM_SIZE),
                            "max_alloc_bytes": get_ulong(device, CL_DEVICE_MAX_MEM_ALLOC_SIZE),
                            "pci_slot": get_pci_slot(device),
                        }
                    )
                    gpu_index += 1
            identity_counts = {}
            for device in devices:
                key = identity_key(device)
                identity_counts[key] = identity_counts.get(key, 0) + 1
            for device in devices:
                key = identity_key(device)
                device["identity_key"] = key
                device["duplicate_group_size"] = identity_counts.get(key, 1)
            result["devices"] = devices
            result["platforms"] = platforms_info
            result["available"] = bool(devices)
            if not devices:
                result["reason"] = "no OpenCL GPU devices found"
        except Exception as exc:
            result["available"] = False
            result["reason"] = str(exc)

        print(json.dumps(result))
        """
    ).strip()
