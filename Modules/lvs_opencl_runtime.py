#!/usr/bin/env python3
"""OpenCL runtime probing and backend aggregation shared across frontends."""

from __future__ import annotations

import json
import subprocess
from typing import Any, Callable, Dict, List, Optional

from .lvs_backend_readiness import build_opencl_backend_payload
from .lvs_gpu_backend_catalog import OPENCL_COMPUTE_VARIANTS


def probe_opencl_runtime_context(
    *,
    context_name: str,
    extra_env: Optional[Dict[str, str]],
    python_runtime: str,
    probe_script: str,
    command_env: Callable[..., Dict[str, str]],
    run_command: Callable[..., Any] = subprocess.run,
) -> Dict[str, Any]:
    selected_env = dict(extra_env or {})
    if not python_runtime:
        return {
            "available": False,
            "reason": "python runtime unavailable",
            "devices": [],
            "library": "",
            "platform_count": 0,
            "platforms": [],
            "context": context_name,
            "selected_env": selected_env,
        }
    try:
        completed = run_command(
            [python_runtime, "-c", probe_script],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=command_env(selected_env, unset_keys=["RUSTICL_ENABLE", "OCL_ICD_VENDORS"]),
        )
    except Exception as exc:
        return {
            "available": False,
            "reason": f"probe failed: {exc}",
            "devices": [],
            "library": "",
            "platform_count": 0,
            "platforms": [],
            "context": context_name,
            "selected_env": selected_env,
        }

    stdout = (completed.stdout or "").strip()
    try:
        payload = json.loads(stdout) if stdout else {}
    except Exception:
        payload = {}
    devices = payload.get("devices") or []
    available = bool(payload.get("available")) and bool(devices)
    reason = str(payload.get("reason", "") or "")
    if not available and not reason:
        if completed.returncode != 0:
            reason = (completed.stderr or stdout or "OpenCL probe failed").strip()
        else:
            reason = "OpenCL GPU devices unavailable"
    return {
        "available": available,
        "reason": reason,
        "devices": devices,
        "library": str(payload.get("library", "") or ""),
        "platform_count": int(payload.get("platform_count", 0) or 0),
        "platforms": payload.get("platforms") or [],
        "context": context_name,
        "selected_env": selected_env,
    }


def discover_opencl_backend(
    *,
    probe_attempt: Callable[[str, Optional[Dict[str, str]]], Dict[str, Any]],
    runtime_context_candidates: Callable[[Optional[Dict[str, Any]]], List[Dict[str, Any]]],
    gpu_cards: List[Dict[str, Any]],
    discover_icds: Callable[[], List[Dict[str, Any]]],
    best_device_for_target: Callable[[List[Dict[str, Any]], Dict[str, Any]], Optional[Dict[str, Any]]],
    env_candidates_for_target: Callable[[Dict[str, Any], List[Dict[str, Any]]], List[Dict[str, Any]]],
    device_identity_key: Callable[[Dict[str, Any], Optional[Dict[str, str]]], tuple],
    append_probe_devices: Callable[[List[Dict[str, Any]], Dict[str, Any], Dict[str, str], set], None],
) -> Dict[str, Any]:
    probe_attempts: List[Dict[str, Any]] = []
    native_probe = probe_attempt("native", {})
    probe_attempts.append(native_probe)
    selected_probe = native_probe
    if not native_probe["available"]:
        for candidate in runtime_context_candidates(native_probe)[1:]:
            probe = probe_attempt(candidate["context"], candidate["env"])
            probe_attempts.append(probe)
            selected_probe = probe
            if probe["available"]:
                break

    all_devices: List[Dict[str, Any]] = [
        dict(
            device,
            required_env=dict(selected_probe.get("selected_env") or {}),
            probe_context=str(selected_probe.get("context", "native") or "native"),
        )
        for device in (selected_probe.get("devices") or [])
    ]
    seen_devices = {
        device_identity_key(device, device.get("required_env") or {})
        for device in all_devices
    }

    icds = discover_icds()
    attempted_envs = {
        tuple(sorted((str(key), str(value)) for key, value in (attempt.get("selected_env") or {}).items()))
        for attempt in probe_attempts
    }
    for card in gpu_cards:
        if best_device_for_target(all_devices, card):
            continue
        for candidate in env_candidates_for_target(card, icds):
            env_key = tuple(sorted((str(key), str(value)) for key, value in candidate["env"].items()))
            if env_key in attempted_envs:
                continue
            attempted_envs.add(env_key)
            probe = probe_attempt(candidate["context"], candidate["env"])
            probe_attempts.append(probe)
            append_probe_devices(all_devices, probe, candidate["env"], seen_devices)
            if best_device_for_target(all_devices, card):
                break

    return build_opencl_backend_payload(
        selected_probe=selected_probe,
        probe_attempts=probe_attempts,
        devices=all_devices,
    )


def opencl_compute_safety_profile(safe_mode_enabled: bool) -> Dict[str, Any]:
    enabled = bool(safe_mode_enabled)
    return {
        "safe_mode_enabled": enabled,
        "high_headroom_discrete_cap": {
            "enabled": enabled,
            "applies_when": {
                "vendor": "AMD",
                "device_class": "discrete",
                "compute_units_gte": 28,
                "or_max_clock_mhz_gte": 2400,
            },
            "load_phase_scale": 0.9,
            "verify_phase_scale": 0.9,
            "load_phase_sleep_seconds": 0.0008,
            "verify_phase_sleep_seconds": 0.001,
            "load_phase_buffer_reduction": 2,
            "reason": "Conservative maintained cap for higher-headroom AMD discrete OpenCL targets to reduce amdgpu compute-ring reset risk on current Linux stacks.",
        },
        "integer_mix_high_headroom_discrete_cap": {
            "enabled": enabled,
            "status": OPENCL_COMPUTE_VARIANTS.get("integer_mix", {}).get("status", "experimental"),
            "applies_when": {
                "compute_variant": "integer_mix",
                "vendor": "AMD",
                "device_class": "discrete",
                "compute_units_gte": 28,
                "or_max_clock_mhz_gte": 2400,
            },
            "work_items_cap": 1 << 20,
            "launches_per_cycle_cap": 14,
            "compute_rounds_cap": 160,
            "runtime_buffers_cap": 2,
            "load_phase_scale": 0.7,
            "verify_phase_scale": 0.72,
            "load_phase_sleep_seconds": 0.0024,
            "verify_phase_sleep_seconds": 0.0027,
            "load_phase_buffers": 1,
            "verify_phase_buffers_max": 2,
            "reason": "Validated experimental cap based on a prior amdgpu compute-ring reset followed by repeated stable 90-second passes near the baseline dGPU power plateau.",
        },
    }
