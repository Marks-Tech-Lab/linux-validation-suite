#!/usr/bin/env python3
"""Worker evidence file helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from Modules.lvs_stability_events import create_stability_event


def read_log_tail(path: Optional[str], max_chars: int = 4000) -> str:
    if not path:
        return ""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def apply_worker_entry_context(
    payload: Dict[str, Any],
    entry: Any,
    *,
    return_code: Optional[int] = None,
    stdout_tail: str = "",
    stderr_tail: str = "",
) -> Dict[str, Any]:
    if getattr(entry, "result_path", None) and "result_path" not in payload:
        payload["result_path"] = str(entry.result_path)
    if "kind" not in payload:
        payload["kind"] = getattr(entry, "kind", "")
    gpu_spec = getattr(entry, "gpu_spec", None)
    if gpu_spec is not None:
        payload.setdefault("backend", getattr(gpu_spec, "backend", ""))
        payload.setdefault("backend_api_family", getattr(gpu_spec, "backend_api_family", ""))
        payload.setdefault("suite_scaling_mode", getattr(gpu_spec, "suite_scaling_mode", ""))
        payload.setdefault("suite_verification", getattr(gpu_spec, "suite_verification", ""))
        payload.setdefault("profile_mode", getattr(gpu_spec, "profile_mode", ""))
        payload.setdefault("profile_intensity", getattr(gpu_spec, "profile_intensity", ""))
        payload.setdefault("workload", getattr(gpu_spec, "workload", ""))
        payload.setdefault("gpu_index", getattr(gpu_spec, "gpu_index", 0))
        payload.setdefault("card", getattr(gpu_spec, "card", ""))
        payload.setdefault("slot", getattr(gpu_spec, "slot", ""))
        payload.setdefault("target_id", getattr(gpu_spec, "target_id", ""))
        payload.setdefault("target_vram_bytes", getattr(gpu_spec, "target_vram_bytes", 0))
        payload.setdefault("tuning_step", getattr(gpu_spec, "tuning_step", 0))
        payload.setdefault("process_count", getattr(gpu_spec, "process_count", 0))
        payload.setdefault("resolved_device_name", getattr(gpu_spec, "resolved_device_name", ""))
        payload.setdefault("selection_ambiguous", getattr(gpu_spec, "selection_ambiguous", False))
        payload.setdefault("device_class", getattr(gpu_spec, "device_class", ""))
    if getattr(entry, "stdout_path", None):
        payload.setdefault("stdout_path", entry.stdout_path)
    if getattr(entry, "stderr_path", None):
        payload.setdefault("stderr_path", entry.stderr_path)
    if return_code is not None:
        payload["observed_exit_code"] = int(return_code)
        if return_code < 0:
            payload["observed_exit_signal"] = int(-return_code)
        if return_code != 0:
            reported_status = str(payload.get("status") or "").strip()
            if reported_status.lower() not in {"error", "crashed", "aborted"}:
                payload["reported_status"] = reported_status or "ok"
                payload["status"] = "crashed"
            payload["error_count"] = max(1, int(payload.get("error_count") or 0))
            if not str(payload.get("last_error") or "").strip():
                kind = str(getattr(entry, "kind", payload.get("kind", "worker")) or "worker")
                payload["last_error"] = f"{kind} worker exited early with code {return_code}"
            if stdout_tail:
                payload["stdout_tail"] = stdout_tail
            if stderr_tail:
                payload["stderr_tail"] = stderr_tail
    if stdout_tail:
        payload.setdefault("stdout_tail", stdout_tail)
    if stderr_tail:
        payload.setdefault("stderr_tail", stderr_tail)
    return payload


def fallback_worker_payload(
    entry: Any,
    return_code: int,
    *,
    stdout_tail: str = "",
    stderr_tail: str = "",
) -> Dict[str, Any]:
    kind = str(getattr(entry, "kind", "") or "")
    payload: Dict[str, Any] = {
        "kind": kind,
        "status": "crashed" if return_code != 0 else "ok",
        "error_count": 1 if return_code != 0 else 0,
        "observed_exit_code": int(return_code),
        "last_error": f"{kind} worker exited early with code {return_code}" if return_code != 0 else "",
    }
    return apply_worker_entry_context(
        payload,
        entry,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
    )


def worker_result_events_from_payload(
    payload: Dict[str, Any],
    display_name: str,
    *,
    entry_kind: str = "",
    backend_name: str = "",
    backend_load_class: str = "",
) -> list[Dict[str, Any]]:
    events: list[Dict[str, Any]] = []
    compatibility_backend = (
        str(payload.get("kind") or "").lower() == "gpu"
        and str(backend_load_class or "") == "compatibility"
    )
    telemetry_only_backend = str(payload.get("suite_verification") or "").strip().lower() == "telemetry_only"
    kind = payload.get("kind", entry_kind)
    observed_exit_code = payload.get("observed_exit_code")
    if observed_exit_code not in (None, 0):
        events.append(
            create_stability_event(
                "worker_exit",
                "warning" if compatibility_backend else "error",
                display_name,
                kind,
                (
                    f"compatibility backend worker exited early with code {observed_exit_code}"
                    if compatibility_backend
                    else f"{kind} worker exited early with code {observed_exit_code}"
                ),
                payload,
            )
        )
        return events
    error_count = int(payload.get("error_count") or 0)
    status = str(payload.get("status") or "").lower()
    if status == "error" or error_count > 0:
        if telemetry_only_backend:
            child_failures = int(payload.get("child_failure_count") or error_count or 0)
            events.append(
                create_stability_event(
                    "backend_runtime_failure",
                    "warning" if compatibility_backend else "error",
                    display_name,
                    kind,
                    (
                        f"compatibility backend '{backend_name or kind}' reported {child_failures} child process failures"
                        if compatibility_backend
                        else f"external backend '{backend_name or kind}' reported {child_failures} child process failures"
                    ),
                    payload,
                )
            )
            return events
        events.append(
            create_stability_event(
                "verification_error",
                "error",
                display_name,
                kind,
                f"{kind} worker reported {error_count} verification errors",
                payload,
            )
        )
        return events
    shortfall_bytes = int(payload.get("allocation_shortfall_bytes") or 0)
    target_vram_bytes = int(
        payload.get("active_target_vram_bytes")
        or payload.get("target_vram_bytes")
        or 0
    )
    allocated_vram_bytes = int(payload.get("allocated_vram_bytes") or payload.get("buffer_allocation_bytes") or 0)
    if target_vram_bytes > 0:
        shortfall_bytes = max(0, target_vram_bytes - allocated_vram_bytes)
    if shortfall_bytes > 0 and target_vram_bytes > 0 and shortfall_bytes >= int(target_vram_bytes * 0.05):
        events.append(
            create_stability_event(
                "allocation_shortfall",
                "warning",
                display_name,
                kind,
                f"{payload.get('backend', kind)} allocated less VRAM than requested",
                payload,
            )
        )
    if payload.get("selection_ambiguous"):
        events.append(
            create_stability_event(
                "device_selection",
                "warning",
                display_name,
                kind,
                f"{payload.get('backend', kind)} device selection was ambiguous",
                payload,
            )
        )
    return events
