from __future__ import annotations

import textwrap
from typing import Any, Dict, List, Optional


def build_external_gpu_supervisor_script(
    *,
    backend: str,
    child_command: List[str],
    child_env: Optional[Dict[str, str]],
    target: Optional[Dict[str, Any]],
    target_process_count: int,
    ramp_step_seconds: float,
    start_load_fraction: float,
    resolved_device_name: str = "",
    selection_ambiguous: bool = False,
    result_file: str = "",
) -> str:
    return textwrap.dedent(
        f"""
        import atexit
        import json
        import os
        import signal
        import subprocess
        import time

        BACKEND = {backend!r}
        CHILD_COMMAND = {child_command!r}
        CHILD_ENV = {dict(child_env or {})!r}
        TARGET_ID = {str((target or {{}}).get("target_id", "") or "")!r}
        TARGET_SLOT = {str((target or {{}}).get("slot", "") or "")!r}
        TARGET_CARD = {str((target or {{}}).get("card", "") or "")!r}
        TARGET_GPU_INDEX = {int((target or {{}}).get("gpu_index", 0) or 0)}
        TARGET_PROCESS_COUNT = {max(1, int(target_process_count))}
        RAMP_STEP_SECONDS = {max(0.0, float(ramp_step_seconds))}
        START_LOAD_FRACTION = {max(0.15, min(1.0, float(start_load_fraction)))}
        RESULT_FILE = {result_file!r}
        RESOLVED_DEVICE_NAME = {resolved_device_name!r}
        SELECTION_AMBIGUOUS = {bool(selection_ambiguous)!r}
        IS_COMPATIBILITY_BACKEND = {backend in {"vkcube", "glxgears"}!r}
        MAX_CHILD_FAILURES = {1 if backend in {"vkcube", "glxgears"} else 3}

        state = {{
            "kind": "gpu",
            "mode": "gpu_3d",
            "backend": BACKEND,
            "backend_api_family": "Vulkan" if BACKEND in {{"vkmark", "vkcube"}} else "OpenGL",
            "suite_scaling_mode": "process_parallel",
            "suite_verification": "telemetry_only",
            "status": "ok",
            "error_count": 0,
            "frames": 0,
            "target_id": TARGET_ID,
            "slot": TARGET_SLOT,
            "card": TARGET_CARD,
            "gpu_index": TARGET_GPU_INDEX,
            "target_process_count": TARGET_PROCESS_COUNT,
            "active_process_count": 0,
            "launched_process_count": 0,
            "child_failure_count": 0,
            "active_load_fraction": 0.0,
            "resolved_device_name": RESOLVED_DEVICE_NAME,
            "selection_ambiguous": SELECTION_AMBIGUOUS,
            "last_error": "",
            "compatibility_backend": IS_COMPATIBILITY_BACKEND,
        }}

        children = []
        running = True

        def record_error(message):
            state["error_count"] += 1
            state["status"] = "warning" if IS_COMPATIBILITY_BACKEND else "error"
            state["last_error"] = str(message)

        def current_load_fraction(started_monotonic):
            if RAMP_STEP_SECONDS <= 0:
                return 1.0
            elapsed = max(0.0, time.monotonic() - started_monotonic)
            progress = min(1.0, elapsed / max(0.001, RAMP_STEP_SECONDS * 3.0))
            return min(1.0, START_LOAD_FRACTION + (1.0 - START_LOAD_FRACTION) * progress)

        def desired_process_count(started_monotonic):
            fraction = current_load_fraction(started_monotonic)
            desired = max(1, min(TARGET_PROCESS_COUNT, int(round(TARGET_PROCESS_COUNT * fraction))))
            return desired, fraction

        def stop(*_args):
            global running
            running = False

        def write_result():
            if not RESULT_FILE:
                return
            try:
                with open(RESULT_FILE, "w", encoding="utf-8") as handle:
                    json.dump(state, handle, indent=2)
            except Exception:
                pass

        def reap_children():
            global running
            active = []
            for proc in children:
                code = proc.poll()
                if code is None:
                    active.append(proc)
                    continue
                state["child_failure_count"] += 1
                record_error(f"child process exited early with code {{code}}")
                if state["child_failure_count"] >= MAX_CHILD_FAILURES:
                    running = False
            children[:] = active

        def spawn_child():
            env = os.environ.copy()
            env.update(CHILD_ENV)
            proc = subprocess.Popen(
                CHILD_COMMAND,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            children.append(proc)
            state["launched_process_count"] += 1

        def stop_children(force=False):
            for proc in children:
                try:
                    if force:
                        proc.kill()
                    else:
                        proc.terminate()
                except Exception:
                    pass
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                remaining = [proc for proc in children if proc.poll() is None]
                if not remaining:
                    break
                time.sleep(0.1)
            for proc in children:
                if proc.poll() is None:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            children[:] = []

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        atexit.register(write_result)

        started_monotonic = time.monotonic()
        try:
            while running:
                reap_children()
                if not running:
                    break
                desired, fraction = desired_process_count(started_monotonic)
                while running and len(children) < desired:
                    try:
                        spawn_child()
                    except Exception as exc:
                        record_error(exc)
                        running = False
                        break
                    time.sleep(max(0.25, RAMP_STEP_SECONDS * 0.25 if RAMP_STEP_SECONDS > 0 else 0.25))
                state["active_load_fraction"] = round(fraction, 3)
                state["active_process_count"] = len(children)
                state["frames"] += 1
                if state["frames"] % 4 == 0:
                    write_result()
                time.sleep(1.0)
        finally:
            stop_children(force=False)
        """
    ).strip()
