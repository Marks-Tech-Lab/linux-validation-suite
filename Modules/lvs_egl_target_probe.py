#!/usr/bin/env python3
"""EGL runtime and targeted probe helpers for GPU backend selection."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from .lvs_backend_readiness import build_egl_backend_payload


def is_software_renderer(renderer: str) -> bool:
    text = str(renderer or "").lower()
    return any(token in text for token in ("llvmpipe", "softpipe", "swrast", "software rasterizer"))


def probe_egl_runtime_backend(
    *,
    python_runtime: str,
    probe_script: str,
    preferred_target: Optional[Dict[str, Any]],
    command_env: Callable[[Optional[Dict[str, str]]], Dict[str, str]],
    software_renderer_check: Callable[[str], bool] = is_software_renderer,
    run_command: Callable[..., Any] = subprocess.run,
    environment: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    if not python_runtime:
        return {
            "available": False,
            "renderer": "",
            "vendor": "",
            "reason": "python runtime unavailable",
        }
    try:
        env = dict(os.environ if environment is None else environment)
        if preferred_target and preferred_target.get("dri_prime"):
            env["DRI_PRIME"] = str(preferred_target["dri_prime"])
        completed = run_command(
            [python_runtime, "-c", probe_script],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
            env=command_env(env),
        )
    except Exception as exc:
        return {
            "available": False,
            "renderer": "",
            "vendor": "",
            "reason": f"probe failed: {exc}",
        }

    stdout = (completed.stdout or "").strip()
    try:
        payload = json.loads(stdout) if stdout else {}
    except Exception:
        payload = {}
    return build_egl_backend_payload(
        payload=payload,
        returncode=completed.returncode,
        stdout=stdout,
        stderr=completed.stderr or "",
        target=preferred_target,
        is_software_renderer=software_renderer_check,
    )


def renderer_matches_gpu_target(
    renderer_text: str,
    target: Optional[Dict[str, Any]],
) -> bool:
    if not target:
        return True
    renderer_text = str(renderer_text or "").lower()
    target_vendor = str(target.get("vendor", "") or "").lower().strip()
    target_name = str(target.get("name", "") or "").lower().strip()
    if not target_vendor:
        return True
    vendor_aliases = {
        "amd": ["amd", "radeon", "radeonsi", "radv"],
        "nvidia": ["nvidia", "geforce", "quadro", "rtx", "tesla"],
        "intel": ["intel", "arc", "iris"],
    }
    aliases = vendor_aliases.get(target_vendor, [target_vendor])
    if not any(alias in renderer_text for alias in aliases):
        return False
    if not target_name:
        return True
    tokens = [
        token
        for token in re.split(r"[^a-z0-9]+", target_name)
        if len(token) >= 3 and token not in {target_vendor, "gpu", "graphics"}
    ]
    if not tokens:
        return True
    return any(token in renderer_text for token in tokens)


def mesa_egl_vendor_json() -> str:
    for directory in (Path("/usr/share/glvnd/egl_vendor.d"), Path("/etc/glvnd/egl_vendor.d")):
        try:
            candidate = directory / "50_mesa.json"
            if candidate.exists():
                return str(candidate)
            for path in sorted(directory.glob("*mesa*.json")):
                if path.exists():
                    return str(path)
        except Exception:
            continue
    return ""


def egl_target_identity_env(runner: Any, target: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not target:
        return {}
    env: Dict[str, str] = {}
    slot = str(target.get("slot", "") or target.get("target_id", "") or "")
    card = str(target.get("card", "") or "")
    if slot:
        env["LVS_EGL_TARGET_SLOT"] = runner._normalize_pci_slot(slot)
    if card:
        card_node = f"/dev/dri/{card}"
        env["LVS_EGL_TARGET_CARD_NODE"] = card_node
        device_path = Path("/sys/class/drm") / card / "device"
        try:
            target_real = device_path.resolve()
        except Exception:
            target_real = None
        if target_real is not None:
            for render in sorted(Path("/sys/class/drm").glob("renderD*")):
                try:
                    if (render / "device").resolve() == target_real:
                        env["LVS_EGL_TARGET_RENDER_NODE"] = f"/dev/dri/{render.name}"
                        break
                except Exception:
                    continue
    return env


def run_egl_target_probe(
    runner: Any,
    target: Dict[str, Any],
    extra_env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    runtime = runner._python_runtime()
    if not runtime:
        return {
            "available": False,
            "renderer": "",
            "vendor": "",
            "reason": "python runtime unavailable",
            "target_id": str(target.get("target_id", "") or ""),
            "target_dri_prime": str(target.get("dri_prime", "") or ""),
            "matched_target": False,
            "selected_env": {**runner._egl_target_identity_env(target), **dict(extra_env or {})},
        }
    selected_env = {**runner._egl_target_identity_env(target), **dict(extra_env or {})}
    try:
        env = os.environ.copy()
        selector = str(target.get("dri_prime", "") or "")
        if selector:
            env["DRI_PRIME"] = selector
        for key, value in selected_env.items():
            env[str(key)] = str(value)
        completed = subprocess.run(
            [runtime, "-c", runner._egl_probe_script()],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
            env=runner._command_env(env),
        )
    except Exception as exc:
        return {
            "available": False,
            "renderer": "",
            "vendor": "",
            "reason": f"probe failed: {exc}",
            "target_id": str(target.get("target_id", "") or ""),
            "target_dri_prime": str(target.get("dri_prime", "") or ""),
            "matched_target": False,
            "selected_env": selected_env,
        }
    stdout = (completed.stdout or "").strip()
    try:
        probe = json.loads(stdout) if stdout else {}
    except Exception:
        probe = {}
    renderer = str(probe.get("renderer", "") or "")
    vendor = str(probe.get("vendor", "") or "")
    available = bool(probe.get("available")) and not runner._is_software_renderer(renderer)
    reason = str(probe.get("reason", "") or "")
    exact_egl_device_match = bool(probe.get("egl_device_exact_match"))
    matched_target = available and (exact_egl_device_match or runner._renderer_matches_gpu_target(renderer, target))
    if not available and not reason:
        if renderer:
            reason = f"software renderer detected: {renderer}"
        elif completed.returncode != 0:
            reason = (completed.stderr or stdout or "EGL probe failed").strip()
        else:
            reason = "EGL hardware renderer unavailable"
    if available and not matched_target:
        reason = (
            f"renderer target mismatch: got '{renderer}' for {target.get('target_id') or target.get('card') or 'GPU'}"
        )
    return {
        "available": available and matched_target,
        "renderer": renderer,
        "vendor": vendor,
        "reason": reason,
        "target_id": str(target.get("target_id", "") or ""),
        "target_dri_prime": str(target.get("dri_prime", "") or ""),
        "matched_target": matched_target,
        "egl_device_exact_match": exact_egl_device_match,
        "egl_selected_device": dict(probe.get("egl_selected_device") or {}),
        "selected_env": selected_env,
    }


def egl_gpu_backend_for_target(runner: Any, target: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not target:
        return dict(runner._egl_gpu_backend())
    cache_key = runner._gpu_target_cache_key(target)
    cached = runner._egl_target_probe_cache.get(cache_key)
    if cached is not None:
        return dict(cached)

    payload = runner._run_egl_target_probe(target, {})
    target_vendor = str(target.get("vendor", "") or "").strip().lower()
    if not payload.get("available") and target_vendor != "nvidia":
        mesa_json = runner._mesa_egl_vendor_json()
        if mesa_json:
            retry = runner._run_egl_target_probe(
                target,
                {"__EGL_VENDOR_LIBRARY_FILENAMES": mesa_json},
            )
            if retry.get("available"):
                retry["fallback_context"] = "mesa_egl_vendor"
                payload = retry
            else:
                payload["retry"] = {
                    "context": "mesa_egl_vendor",
                    "reason": retry.get("reason", ""),
                    "renderer": retry.get("renderer", ""),
                }
    runner._egl_target_probe_cache[cache_key] = payload
    return dict(payload)
