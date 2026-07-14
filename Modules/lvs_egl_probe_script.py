#!/usr/bin/env python3
"""EGL/GLES renderer probe script builder."""

from __future__ import annotations

import textwrap


def build_egl_probe_script() -> str:
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
