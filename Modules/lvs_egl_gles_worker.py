from __future__ import annotations

import json
import textwrap
from typing import Any, Dict, Optional


def build_egl_gles_workload_script(
    mode: str,
    target_vram_bytes: int = 0,
    worker_params: Optional[Dict[str, Any]] = None,
) -> str:
    mode_value = json.dumps(mode)
    target_value = int(target_vram_bytes)
    params = dict(worker_params or {})
    surface_size = max(256, int(params.get("surface_size", 1024 if mode == "gpu_3d" else 512)))
    draw_count = max(1, int(params.get("draw_count", 96 if mode == "gpu_3d" else 8)))
    shader_iterations = max(4, int(params.get("shader_iterations", 24)))
    texture_side_hint = max(1024, int(params.get("texture_side", 4096)))
    clear_passes = max(1, int(params.get("clear_passes", 1)))
    ramp_step_seconds = max(0.0, float(params.get("ramp_step_seconds", 0.0) or 0.0))
    start_load_fraction = max(0.15, min(1.0, float(params.get("start_load_fraction", 1.0) or 1.0)))
    target_vendor = str(params.get("target_vendor", "") or "")
    target_name = str(params.get("target_name", "") or "")
    target_slot = str(params.get("target_slot", "") or "")
    target_id = str(params.get("target_id", "") or "")
    result_file = json.dumps(str(params.get("result_file", "") or ""))
    return textwrap.dedent(
        f"""
        import atexit
        import ctypes
        import ctypes.util
        import json
        import math
        import os
        import signal
        import sys
        import time

        MODE = {mode_value}
        TARGET_VRAM_BYTES = {target_value}
        SURFACE_SIZE = {surface_size}
        DRAW_COUNT = {draw_count}
        SHADER_ITERATIONS = {shader_iterations}
        TEXTURE_SIDE_HINT = {texture_side_hint}
        CLEAR_PASSES = {clear_passes}
        RAMP_STEP_SECONDS = {ramp_step_seconds}
        START_LOAD_FRACTION = {start_load_fraction}
        TARGET_VENDOR = {json.dumps(target_vendor)}
        TARGET_NAME = {json.dumps(target_name)}
        TARGET_SLOT = {json.dumps(target_slot)}
        TARGET_ID = {json.dumps(target_id)}
        RESULT_FILE = {result_file}
        EGL = ctypes.CDLL(ctypes.util.find_library("EGL"))
        GLES = ctypes.CDLL(ctypes.util.find_library("GLESv2"))
        EGLDisplay = ctypes.c_void_p
        EGLConfig = ctypes.c_void_p
        EGLContext = ctypes.c_void_p
        EGLSurface = ctypes.c_void_p
        EGLint = ctypes.c_int
        EGLenum = ctypes.c_uint
        EGLBoolean = ctypes.c_uint
        GLuint = ctypes.c_uint
        GLint = ctypes.c_int
        GLfloat = ctypes.c_float
        GLsizei = ctypes.c_int
        GLbitfield = ctypes.c_uint
        GLcharP = ctypes.c_char_p
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
        GL_VERTEX_SHADER = 0x8B31
        GL_FRAGMENT_SHADER = 0x8B30
        GL_COMPILE_STATUS = 0x8B81
        GL_LINK_STATUS = 0x8B82
        GL_ARRAY_BUFFER = 0x8892
        GL_STATIC_DRAW = 0x88E4
        GL_FLOAT = 0x1406
        GL_FALSE = 0
        GL_TRUE = 1
        GL_TRIANGLES = 0x0004
        GL_COLOR_BUFFER_BIT = 0x00004000
        GL_TEXTURE_2D = 0x0DE1
        GL_RGBA = 0x1908
        GL_UNSIGNED_BYTE = 0x1401
        GL_TEXTURE_MIN_FILTER = 0x2801
        GL_TEXTURE_MAG_FILTER = 0x2800
        GL_LINEAR = 0x2601
        GL_TEXTURE_WRAP_S = 0x2802
        GL_TEXTURE_WRAP_T = 0x2803
        GL_CLAMP_TO_EDGE = 0x812F
        GL_FRAMEBUFFER = 0x8D40
        GL_COLOR_ATTACHMENT0 = 0x8CE0
        GL_FRAMEBUFFER_COMPLETE = 0x8CD5
        GL_RENDERER = 0x1F01
        GL_MAX_TEXTURE_SIZE = 0x0D33
        GL_NO_ERROR = 0
        GL_SCISSOR_TEST = 0x0C11

        def as_text(value):
            if not value:
                return ""
            if isinstance(value, bytes):
                return value.decode("utf-8", "ignore")
            return str(value)

        def fail(message, code=1):
            print(message, file=sys.stderr)
            raise SystemExit(code)

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
                return EGLDisplay(0), {{}}
            target_nodes = {{
                norm_node(os.environ.get("LVS_EGL_TARGET_CARD_NODE", "")),
                norm_node(os.environ.get("LVS_EGL_TARGET_RENDER_NODE", "")),
            }}
            target_nodes.discard("")
            if not target_nodes:
                return EGLDisplay(0), {{}}
            query_devices_addr = EGL.eglGetProcAddress(b"eglQueryDevicesEXT")
            query_device_string_addr = EGL.eglGetProcAddress(b"eglQueryDeviceStringEXT")
            if not query_devices_addr or not query_device_string_addr:
                return EGLDisplay(0), {{}}
            EGLDeviceEXT = ctypes.c_void_p
            QueryDevices = ctypes.CFUNCTYPE(EGLBoolean, EGLint, ctypes.POINTER(EGLDeviceEXT), ctypes.POINTER(EGLint))
            QueryDeviceString = ctypes.CFUNCTYPE(ctypes.c_char_p, EGLDeviceEXT, EGLint)
            query_devices = QueryDevices(query_devices_addr)
            query_device_string = QueryDeviceString(query_device_string_addr)
            count = EGLint()
            devices = (EGLDeviceEXT * 64)()
            if not query_devices(64, devices, ctypes.byref(count)):
                return EGLDisplay(0), {{}}
            for index in range(max(0, int(count.value))):
                device = devices[index]
                drm_node = as_text(query_device_string(device, EGL_DRM_DEVICE_FILE_EXT))
                render_node = as_text(query_device_string(device, EGL_DRM_RENDER_NODE_FILE_EXT))
                node_matches = {{
                    norm_node(drm_node),
                    norm_node(render_node),
                }}
                node_matches.discard("")
                if not target_nodes.intersection(node_matches):
                    continue
                display = get_platform_display(EGL_PLATFORM_DEVICE_EXT, device, None)
                if display:
                    return display, {{
                        "index": index,
                        "drm_device_file": drm_node,
                        "drm_render_node": render_node,
                        "selection": "egl_device",
                    }}
            return EGLDisplay(0), {{}}

        def renderer_matches_target(renderer_text):
            renderer_text = str(renderer_text or "").lower()
            target_vendor = str(TARGET_VENDOR or "").lower().strip()
            target_name = str(TARGET_NAME or "").lower().strip()
            if not target_vendor:
                return True
            vendor_aliases = {{
                "amd": ["amd", "radeon", "radeonsi", "radv"],
                "nvidia": ["nvidia", "geforce", "quadro", "rtx", "tesla"],
                "intel": ["intel", "arc", "iris"],
            }}
            aliases = vendor_aliases.get(target_vendor, [target_vendor])
            vendor_match = any(alias in renderer_text for alias in aliases)
            if not vendor_match:
                return False
            if not target_name:
                return True
            tokens = [
                token
                for token in __import__("re").split(r"[^a-z0-9]+", target_name)
                if len(token) >= 3 and token not in {{target_vendor, "gpu", "graphics"}}
            ]
            if not tokens:
                return True
            return any(token in renderer_text for token in tokens)

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
        GLES.glViewport.argtypes = [GLint, GLint, GLsizei, GLsizei]
        GLES.glClearColor.argtypes = [GLfloat, GLfloat, GLfloat, GLfloat]
        GLES.glClear.argtypes = [GLbitfield]
        GLES.glCreateShader.argtypes = [ctypes.c_uint]
        GLES.glCreateShader.restype = GLuint
        GLES.glShaderSource.argtypes = [GLuint, GLsizei, ctypes.POINTER(GLcharP), ctypes.POINTER(GLint)]
        GLES.glCompileShader.argtypes = [GLuint]
        GLES.glGetShaderiv.argtypes = [GLuint, ctypes.c_uint, ctypes.POINTER(GLint)]
        GLES.glCreateProgram.restype = GLuint
        GLES.glAttachShader.argtypes = [GLuint, GLuint]
        GLES.glLinkProgram.argtypes = [GLuint]
        GLES.glGetProgramiv.argtypes = [GLuint, ctypes.c_uint, ctypes.POINTER(GLint)]
        GLES.glUseProgram.argtypes = [GLuint]
        GLES.glGenBuffers.argtypes = [GLsizei, ctypes.POINTER(GLuint)]
        GLES.glBindBuffer.argtypes = [ctypes.c_uint, GLuint]
        GLES.glBufferData.argtypes = [ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_uint]
        GLES.glGetAttribLocation.argtypes = [GLuint, GLcharP]
        GLES.glGetAttribLocation.restype = GLint
        GLES.glEnableVertexAttribArray.argtypes = [GLuint]
        GLES.glVertexAttribPointer.argtypes = [GLuint, GLint, ctypes.c_uint, ctypes.c_ubyte, GLsizei, ctypes.c_void_p]
        GLES.glGetUniformLocation.argtypes = [GLuint, GLcharP]
        GLES.glGetUniformLocation.restype = GLint
        GLES.glUniform1f.argtypes = [GLint, GLfloat]
        GLES.glDrawArrays.argtypes = [ctypes.c_uint, GLint, GLsizei]
        GLES.glFinish.argtypes = []
        GLES.glEnable.argtypes = [ctypes.c_uint]
        GLES.glDisable.argtypes = [ctypes.c_uint]
        GLES.glScissor.argtypes = [GLint, GLint, GLsizei, GLsizei]
        GLES.glGenTextures.argtypes = [GLsizei, ctypes.POINTER(GLuint)]
        GLES.glBindTexture.argtypes = [ctypes.c_uint, GLuint]
        GLES.glTexParameteri.argtypes = [ctypes.c_uint, ctypes.c_uint, GLint]
        GLES.glTexImage2D.argtypes = [ctypes.c_uint, GLint, GLint, GLsizei, GLsizei, GLint, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
        GLES.glGenFramebuffers.argtypes = [GLsizei, ctypes.POINTER(GLuint)]
        GLES.glBindFramebuffer.argtypes = [ctypes.c_uint, GLuint]
        GLES.glFramebufferTexture2D.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, GLuint, GLint]
        GLES.glCheckFramebufferStatus.argtypes = [ctypes.c_uint]
        GLES.glCheckFramebufferStatus.restype = ctypes.c_uint
        GLES.glGetIntegerv.argtypes = [ctypes.c_uint, ctypes.POINTER(GLint)]
        GLES.glReadPixels.argtypes = [GLint, GLint, GLsizei, GLsizei, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
        GLES.glGetError.argtypes = []
        GLES.glGetError.restype = ctypes.c_uint

        display, selected_egl_device = query_egl_device_display(get_platform_display)
        if not display:
            selected_egl_device = {{"selection": "surfaceless"}}
            display = get_platform_display(EGL_PLATFORM_SURFACELESS_MESA, None, None) if get_platform_display else EGL.eglGetDisplay(ctypes.c_void_p(0))
        major = EGLint()
        minor = EGLint()
        if not display or not EGL.eglInitialize(display, ctypes.byref(major), ctypes.byref(minor)):
            if selected_egl_device.get("selection") == "egl_device":
                selected_egl_device["fallback_reason"] = "eglInitialize failed for matched EGLDevice"
                selected_egl_device["selection"] = "surfaceless_after_egl_device_init_failed"
                display = get_platform_display(EGL_PLATFORM_SURFACELESS_MESA, None, None) if get_platform_display else EGL.eglGetDisplay(ctypes.c_void_p(0))
                if not display or not EGL.eglInitialize(display, ctypes.byref(major), ctypes.byref(minor)):
                    fail("eglInitialize failed", 10)
            else:
                fail("eglInitialize failed", 10)
        if not EGL.eglBindAPI(EGL_OPENGL_ES_API):
            fail("eglBindAPI failed", 11)
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
            fail("eglChooseConfig failed", 12)
        surf_attrs = (EGLint * 5)(EGL_WIDTH, SURFACE_SIZE, EGL_HEIGHT, SURFACE_SIZE, EGL_NONE)
        surface = EGL.eglCreatePbufferSurface(display, config, surf_attrs)
        ctx_attrs = (EGLint * 3)(EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE)
        context = EGL.eglCreateContext(display, config, EGL_NO_CONTEXT, ctx_attrs)
        if not surface or not context or not EGL.eglMakeCurrent(display, surface, surface, context):
            fail("eglMakeCurrent failed", 13)
        renderer = as_text(GLES.glGetString(GL_RENDERER)).lower()
        if any(token in renderer for token in ("llvmpipe", "softpipe", "swrast", "software rasterizer")):
            fail("software renderer detected: " + renderer, 14)
        if selected_egl_device.get("selection") != "egl_device" and not renderer_matches_target(renderer):
            fail(
                "egl renderer mismatch for target "
                + str(TARGET_ID or TARGET_SLOT or TARGET_VENDOR)
                + ": "
                + renderer,
                15,
            )

        state = {{
            "error_count": 0,
            "verification_passes": 0,
            "render_verification_passes": 0,
            "marker_verification_passes": 0,
            "vram_verification_passes": 0,
            "gl_error_count": 0,
            "draw_mismatch_count": 0,
            "marker_mismatch_count": 0,
            "vram_mismatch_count": 0,
            "stalled_frame_count": 0,
            "draw_checksum_stall_count": 0,
            "last_draw_checksum": None,
            "last_draw_sample_checksums": [],
            "last_marker_sample": [],
            "last_error": "",
            "allocated_textures": 0,
            "target_texture_count": 0,
            "allocated_vram_bytes": 0,
            "bytes_per_texture": 0,
            "allocation_shortfall_bytes": 0,
            "target_vendor": TARGET_VENDOR,
            "target_name": TARGET_NAME,
            "target_slot": TARGET_SLOT,
            "target_id": TARGET_ID,
            "renderer": renderer,
            "egl_selected_device": selected_egl_device,
            "egl_device_exact_match": selected_egl_device.get("selection") == "egl_device",
        }}
        sample_w = 4
        sample_h = 4
        pixel_buffer = (ctypes.c_ubyte * (sample_w * sample_h * 4))()
        main_framebuffer = GLuint()
        main_texture = GLuint()

        def sample_origin(width, height, salt=0):
            width = max(sample_w, int(width))
            height = max(sample_h, int(height))
            if not salt:
                x = width // 2 - sample_w // 2
                y = height // 2 - sample_h // 2
                return max(0, x), max(0, y)
            x_span = max(1, width - sample_w)
            y_span = max(1, height - sample_h)
            x = (width // 5 + int(salt) * 37) % x_span
            y = (height // 7 + int(salt) * 53) % y_span
            return x, y

        def checksum_pixels(width, height, salt=0):
            sample_x, sample_y = sample_origin(width, height, salt)
            GLES.glReadPixels(sample_x, sample_y, sample_w, sample_h, GL_RGBA, GL_UNSIGNED_BYTE, pixel_buffer)
            return sum((index + 1) * int(value) for index, value in enumerate(pixel_buffer))

        def pixel_bytes():
            return [int(value) for value in pixel_buffer]

        def record_error(message):
            state["error_count"] += 1
            state["last_error"] = message

        def record_gl_errors(context):
            while True:
                code = int(GLES.glGetError())
                if code == GL_NO_ERROR:
                    return
                state["gl_error_count"] += 1
                record_error(f"OpenGL error 0x{{code:04x}} during {{context}}")

        def clamp_byte(value):
            scaled = int(round(max(0.0, min(1.0, float(value))) * 255.0))
            return max(0, min(255, scaled))

        def read_rgba_sample(width, height, salt=0):
            sample_x, sample_y = sample_origin(width, height, salt)
            GLES.glReadPixels(sample_x, sample_y, sample_w, sample_h, GL_RGBA, GL_UNSIGNED_BYTE, pixel_buffer)
            return pixel_bytes()

        def read_rgba_at(x, y):
            sample_x = max(0, int(x))
            sample_y = max(0, int(y))
            GLES.glReadPixels(sample_x, sample_y, sample_w, sample_h, GL_RGBA, GL_UNSIGNED_BYTE, pixel_buffer)
            return pixel_bytes()

        def approx_channel(actual, expected, tolerance=4):
            return abs(int(actual) - int(expected)) <= tolerance

        def clear_color_channels(phase, offset=0.0):
            return [
                clamp_byte(abs(math.sin(phase + offset))),
                clamp_byte(abs(math.sin(phase + offset + 1.0))),
                clamp_byte(abs(math.sin(phase + offset + 2.0))),
                255,
            ]

        def marker_origin(frame_index):
            marker_size = 16
            span = max(1, SURFACE_SIZE - marker_size - sample_w)
            x = (int(frame_index) * 97 + SURFACE_SIZE // 11) % span
            y = (int(frame_index) * 131 + SURFACE_SIZE // 13) % span
            return x, y, marker_size

        def verify_dynamic_marker(frame_index):
            x, y, marker_size = marker_origin(frame_index)
            expected = clear_color_channels(frame_index * 0.113, 0.37)
            GLES.glEnable(GL_SCISSOR_TEST)
            GLES.glScissor(x, y, marker_size, marker_size)
            GLES.glClearColor(expected[0] / 255.0, expected[1] / 255.0, expected[2] / 255.0, 1.0)
            GLES.glClear(GL_COLOR_BUFFER_BIT)
            GLES.glDisable(GL_SCISSOR_TEST)
            actual = read_rgba_at(x + marker_size // 2, y + marker_size // 2)[:4]
            state["verification_passes"] += 1
            state["render_verification_passes"] += 1
            state["marker_verification_passes"] += 1
            state["last_marker_sample"] = actual
            if not all(approx_channel(actual[index], expected[index]) for index in range(4)):
                state["marker_mismatch_count"] += 1
                record_error(
                    "dynamic marker verification failed: "
                    + f"expected={{expected}} actual={{actual}}"
                )
            record_gl_errors("dynamic marker verification")

        def current_load_fraction(started_monotonic):
            if RAMP_STEP_SECONDS <= 0:
                return 1.0
            elapsed = max(0.0, time.monotonic() - started_monotonic)
            progress = min(1.0, elapsed / max(0.001, RAMP_STEP_SECONDS * 3.0))
            return min(1.0, START_LOAD_FRACTION + (1.0 - START_LOAD_FRACTION) * progress)

        def verify_clear_surface(phase, offset=0.0):
            expected = clear_color_channels(phase, offset)
            actual = read_rgba_sample(SURFACE_SIZE, SURFACE_SIZE)[:4]
            state["verification_passes"] += 1
            state["render_verification_passes"] += 1
            if not all(approx_channel(actual[index], expected[index]) for index in range(4)):
                state["draw_mismatch_count"] += 1
                record_error(
                    "surface clear verification failed: "
                    + f"expected={{expected}} actual={{actual}}"
                )
                return None
            sample_checksums = [
                checksum_pixels(SURFACE_SIZE, SURFACE_SIZE, 0),
                checksum_pixels(SURFACE_SIZE, SURFACE_SIZE, 17),
                checksum_pixels(SURFACE_SIZE, SURFACE_SIZE, 43),
            ]
            return sum((index + 1) * value for index, value in enumerate(sample_checksums))

        def verify_draw_activity(clear_checksum, frame_index):
            verify_dynamic_marker(frame_index)
            sample_checksums = [
                checksum_pixels(SURFACE_SIZE, SURFACE_SIZE, 0),
                checksum_pixels(SURFACE_SIZE, SURFACE_SIZE, frame_index + 17),
                checksum_pixels(SURFACE_SIZE, SURFACE_SIZE, frame_index + 43),
            ]
            checksum = sum((index + 1) * value for index, value in enumerate(sample_checksums))
            state["verification_passes"] += 1
            state["render_verification_passes"] += 1
            if checksum <= 0:
                state["draw_mismatch_count"] += 1
                record_error("draw readback checksum was zero")
            elif clear_checksum is not None and checksum == clear_checksum:
                state["draw_mismatch_count"] += 1
                record_error("draw pass did not modify the render target")
            if state["last_draw_checksum"] == checksum:
                state["stalled_frame_count"] += 1
                state["draw_checksum_stall_count"] += 1
            else:
                state["stalled_frame_count"] = 0
            state["last_draw_checksum"] = checksum
            state["last_draw_sample_checksums"] = sample_checksums
            return checksum

        def verify_vram_texture(phase, texture, texture_index, width, height):
            GLES.glBindFramebuffer(GL_FRAMEBUFFER, vram_framebuffer)
            GLES.glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture, 0)
            GLES.glViewport(0, 0, width, height)
            expected = clear_color_channels(phase, texture_index * 0.1)
            actual = read_rgba_sample(width, height)[:4]
            state["verification_passes"] += 1
            state["vram_verification_passes"] += 1
            if not all(approx_channel(actual[index], expected[index]) for index in range(4)):
                state["vram_mismatch_count"] += 1
                record_error(
                    "vram texture verification failed: "
                    + f"texture={{texture_index}} expected={{expected}} actual={{actual}}"
                )
            record_gl_errors(f"vram verification texture {{texture_index}}")

        def write_result():
            if not RESULT_FILE:
                return
            payload = {{
                "kind": "gpu",
                "mode": MODE,
                "status": "error" if state["error_count"] else "ok",
                "renderer": renderer,
                "frames": globals().get("frame", 0),
                "verification_passes": state["verification_passes"],
                "render_verification_passes": state["render_verification_passes"],
                "marker_verification_passes": state["marker_verification_passes"],
                "vram_verification_passes": state["vram_verification_passes"],
                "error_count": state["error_count"],
                "gl_error_count": state["gl_error_count"],
                "draw_mismatch_count": state["draw_mismatch_count"],
                "marker_mismatch_count": state["marker_mismatch_count"],
                "vram_mismatch_count": state["vram_mismatch_count"],
                "draw_checksum_stall_count": state["draw_checksum_stall_count"],
                "stalled_frame_count": state["stalled_frame_count"],
                "last_draw_sample_checksums": state["last_draw_sample_checksums"],
                "last_marker_sample": state["last_marker_sample"],
                "last_error": state["last_error"],
                "target_vram_bytes": TARGET_VRAM_BYTES,
                "allocated_textures": state["allocated_textures"],
                "target_texture_count": state["target_texture_count"],
                "allocated_vram_bytes": state["allocated_vram_bytes"],
                "bytes_per_texture": state["bytes_per_texture"],
                "allocation_shortfall_bytes": state["allocation_shortfall_bytes"],
                "active_load_fraction": state.get("active_load_fraction"),
                "active_draw_count": state.get("active_draw_count"),
                "active_clear_passes": state.get("active_clear_passes"),
                "active_target_texture_count": state.get("active_target_texture_count"),
                "active_target_vram_bytes": state.get("active_target_vram_bytes"),
                "surface_size": SURFACE_SIZE,
                "draw_count": DRAW_COUNT,
                "shader_iterations": SHADER_ITERATIONS,
                "texture_side_hint": TEXTURE_SIDE_HINT,
                "clear_passes": CLEAR_PASSES,
            }}
            try:
                with open(RESULT_FILE, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2)
            except Exception:
                pass

        atexit.register(write_result)

        vertex_src = b"attribute vec2 a_pos; uniform float u_phase; varying highp vec2 v_uv; void main(){{ v_uv = a_pos * 0.5 + 0.5; vec2 wobble = vec2(sin((a_pos.y + u_phase) * 3.0), cos((a_pos.x - u_phase) * 2.0)) * 0.015; gl_Position = vec4(a_pos + wobble, 0.0, 1.0); }}"
        fragment_src = b"precision highp float; varying highp vec2 v_uv; uniform float u_phase; void main(){{ highp vec2 p = (v_uv * 2.0 - 1.0) * 1.25; highp float acc = 0.0; highp float wave = 0.0; for (int i = 0; i < {shader_iterations}; ++i) {{ highp float fi = float(i) * 0.173; highp vec2 q = p * (1.0 + fi * 0.11) + vec2(sin(u_phase * 0.13 + fi), cos(u_phase * 0.17 - fi)) * 0.35; acc += sin(q.x * q.y * 9.0 + u_phase * (0.7 + fi)); wave += cos(length(q) * (12.0 + fi * 0.5) - u_phase * 0.9); p = vec2(q.x * 0.81 - q.y * 0.59, q.x * 0.59 + q.y * 0.81); }} highp float r = abs(sin(acc * 0.21 + u_phase * 0.15)); highp float g = abs(sin(wave * 0.19 + u_phase * 0.11 + 1.2)); highp float b = abs(sin((acc + wave) * 0.13 - u_phase * 0.09 + 2.4)); gl_FragColor = vec4(r, g, b, 1.0); }}"

        def compile_shader(shader_type, source):
            shader = GLES.glCreateShader(shader_type)
            src = GLcharP(source)
            GLES.glShaderSource(shader, 1, ctypes.byref(src), None)
            GLES.glCompileShader(shader)
            status = GLint()
            GLES.glGetShaderiv(shader, GL_COMPILE_STATUS, ctypes.byref(status))
            if status.value != GL_TRUE:
                fail("shader compile failed", 20)
            return shader

        program = GLES.glCreateProgram()
        vs = compile_shader(GL_VERTEX_SHADER, vertex_src)
        fs = compile_shader(GL_FRAGMENT_SHADER, fragment_src)
        GLES.glAttachShader(program, vs)
        GLES.glAttachShader(program, fs)
        GLES.glLinkProgram(program)
        link_status = GLint()
        GLES.glGetProgramiv(program, GL_LINK_STATUS, ctypes.byref(link_status))
        if link_status.value != GL_TRUE:
            fail("program link failed", 21)
        GLES.glUseProgram(program)

        vertices = (GLfloat * 6)(-1.0, -1.0, 3.0, -1.0, -1.0, 3.0)
        vbo = GLuint()
        GLES.glGenBuffers(1, ctypes.byref(vbo))
        GLES.glBindBuffer(GL_ARRAY_BUFFER, vbo)
        GLES.glBufferData(GL_ARRAY_BUFFER, ctypes.sizeof(vertices), ctypes.cast(vertices, ctypes.c_void_p), GL_STATIC_DRAW)
        a_pos = GLES.glGetAttribLocation(program, b"a_pos")
        u_phase = GLES.glGetUniformLocation(program, b"u_phase")
        GLES.glEnableVertexAttribArray(a_pos)
        GLES.glVertexAttribPointer(a_pos, 2, GL_FLOAT, GL_FALSE, 0, None)
        GLES.glViewport(0, 0, SURFACE_SIZE, SURFACE_SIZE)

        GLES.glGenTextures(1, ctypes.byref(main_texture))
        GLES.glBindTexture(GL_TEXTURE_2D, main_texture)
        GLES.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        GLES.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        GLES.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        GLES.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        GLES.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, SURFACE_SIZE, SURFACE_SIZE, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
        GLES.glGenFramebuffers(1, ctypes.byref(main_framebuffer))
        GLES.glBindFramebuffer(GL_FRAMEBUFFER, main_framebuffer)
        GLES.glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, main_texture, 0)
        if GLES.glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
            fail("main framebuffer incomplete", 15)
        GLES.glViewport(0, 0, SURFACE_SIZE, SURFACE_SIZE)

        textures = []
        vram_framebuffer = GLuint()
        tex_side = 0
        if MODE == "vram":
            GLES.glGenFramebuffers(1, ctypes.byref(vram_framebuffer))
            GLES.glBindFramebuffer(GL_FRAMEBUFFER, vram_framebuffer)
            max_texture_size = GLint()
            GLES.glGetIntegerv(GL_MAX_TEXTURE_SIZE, ctypes.byref(max_texture_size))
            tex_side = min(TEXTURE_SIDE_HINT, max_texture_size.value) if max_texture_size.value > 0 else TEXTURE_SIDE_HINT
            tex_side = 4096 if tex_side >= 4096 else max(1024, tex_side or 2048)
            bytes_per_texture = tex_side * tex_side * 4
            target = max(64 * 1024 * 1024, TARGET_VRAM_BYTES)
            texture_count = max(1, min(512, (target + bytes_per_texture - 1) // bytes_per_texture))
            state["bytes_per_texture"] = bytes_per_texture
            state["target_texture_count"] = texture_count
            GLES.glBindFramebuffer(GL_FRAMEBUFFER, main_framebuffer)
            GLES.glViewport(0, 0, SURFACE_SIZE, SURFACE_SIZE)

        running = True
        def stop(*_):
            global running
            running = False
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        frame = 0
        started_monotonic = time.monotonic()
        while running:
            phase = frame * 0.03
            load_fraction = current_load_fraction(started_monotonic)
            current_draw_count = max(4, min(DRAW_COUNT, int(round(DRAW_COUNT * load_fraction))))
            current_clear_passes = max(1, min(CLEAR_PASSES, int(round(CLEAR_PASSES * load_fraction))))
            state["active_load_fraction"] = round(load_fraction, 3)
            state["active_draw_count"] = current_draw_count
            state["active_clear_passes"] = current_clear_passes
            if MODE == "vram" and textures:
                for _ in range(current_clear_passes):
                    for index, texture in enumerate(textures):
                        GLES.glBindFramebuffer(GL_FRAMEBUFFER, vram_framebuffer)
                        GLES.glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture, 0)
                        GLES.glViewport(0, 0, tex_side, tex_side)
                        GLES.glClearColor(abs(math.sin(phase + index * 0.1)), abs(math.sin(phase + 1.0)), abs(math.sin(phase + 2.0)), 1.0)
                        GLES.glClear(GL_COLOR_BUFFER_BIT)
                record_gl_errors("vram clear passes")
                if frame % 180 == 0:
                    verification_indexes = sorted({{0, len(textures) // 2, len(textures) - 1}})
                    for verification_index in verification_indexes:
                        verify_vram_texture(phase, textures[verification_index], verification_index, tex_side, tex_side)
            GLES.glBindFramebuffer(GL_FRAMEBUFFER, main_framebuffer)
            GLES.glViewport(0, 0, SURFACE_SIZE, SURFACE_SIZE)
            GLES.glClearColor(abs(math.sin(phase)), abs(math.sin(phase + 1.0)), abs(math.sin(phase + 2.0)), 1.0)
            GLES.glClear(GL_COLOR_BUFFER_BIT)
            clear_checksum = None
            if frame % 120 == 0:
                clear_checksum = verify_clear_surface(phase)
            GLES.glUniform1f(u_phase, phase)
            if MODE == "vram":
                desired_texture_count = max(1, min(state["target_texture_count"], int(round(state["target_texture_count"] * load_fraction))))
                state["active_target_texture_count"] = desired_texture_count
                state["active_target_vram_bytes"] = desired_texture_count * state["bytes_per_texture"]
                while len(textures) < desired_texture_count:
                    texture = GLuint()
                    GLES.glGenTextures(1, ctypes.byref(texture))
                    GLES.glBindFramebuffer(GL_FRAMEBUFFER, vram_framebuffer)
                    GLES.glBindTexture(GL_TEXTURE_2D, texture)
                    GLES.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
                    GLES.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
                    GLES.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
                    GLES.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
                    GLES.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, tex_side, tex_side, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
                    GLES.glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture, 0)
                    if GLES.glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
                        record_error("framebuffer became incomplete during VRAM allocation")
                        break
                    GLES.glViewport(0, 0, tex_side, tex_side)
                    GLES.glClearColor(0.25, 0.5, 0.75, 1.0)
                    GLES.glClear(GL_COLOR_BUFFER_BIT)
                    textures.append(texture)
                    state["allocated_textures"] = len(textures)
                    state["allocated_vram_bytes"] = len(textures) * state["bytes_per_texture"]
                    state["allocation_shortfall_bytes"] = max(0, TARGET_VRAM_BYTES - state["allocated_vram_bytes"])
                    record_gl_errors("vram allocation")
                GLES.glBindFramebuffer(GL_FRAMEBUFFER, main_framebuffer)
                GLES.glViewport(0, 0, SURFACE_SIZE, SURFACE_SIZE)
            for _ in range(current_draw_count):
                GLES.glDrawArrays(GL_TRIANGLES, 0, 3)
            GLES.glFinish()
            record_gl_errors("main draw")
            if frame % 120 == 0:
                verify_draw_activity(clear_checksum, frame)
            frame += 1
            if frame % 60 == 0:
                write_result()
            time.sleep(0.001)
        """
    ).strip()

