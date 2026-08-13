from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from Modules.lvs_compat_export_helpers import gpu_worker_backend_name
from Modules.lvs_external_process_evidence import build_stress_ng_cpu_evidence, build_stress_ng_memory_evidence
from Modules.lvs_stability_events import create_stability_event
from Modules.lvs_stage_process_control import StageProcess
from Modules.lvs_worker_evidence import (
    apply_worker_entry_context,
    fallback_worker_payload,
    read_log_tail,
    worker_result_events_from_payload,
)


def fallback_worker_payload_for_entry(
    entry: StageProcess,
    *,
    allow_partial: bool = False,
) -> Optional[Dict[str, Any]]:
    return_code = entry.process.poll()
    if return_code is None or allow_partial:
        return None
    command = list(getattr(entry, "command", []) or [])
    is_python_cpu_fallback = (
        getattr(entry, "kind", "") == "cpu"
        and "-m" in command
        and "Modules.lvs_python_cpu_worker" in command
    )
    is_stress_ng_cpu = (
        getattr(entry, "kind", "") == "cpu"
        and bool(command)
        and Path(str(command[0])).name == "stress-ng"
    )
    is_stress_ng_memory = (
        getattr(entry, "kind", "") == "memory"
        and bool(command)
        and Path(str(command[0])).name == "stress-ng"
    )
    if is_stress_ng_cpu or is_stress_ng_memory:
        stdout_text = read_log_tail(entry.stdout_path, max_chars=1_000_000)
        stderr_text = read_log_tail(entry.stderr_path, max_chars=1_000_000)
        stdout_tail = read_log_tail(entry.stdout_path)
        stderr_tail = read_log_tail(entry.stderr_path)
        evidence_builder = build_stress_ng_cpu_evidence if is_stress_ng_cpu else build_stress_ng_memory_evidence
        payload = evidence_builder(command, "\n".join(value for value in (stdout_text, stderr_text) if value))
        payload = apply_worker_entry_context(
            payload,
            entry,
            return_code=return_code,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
        )
        if entry.result_path:
            try:
                result_path = Path(entry.result_path)
                result_path.parent.mkdir(parents=True, exist_ok=True)
                result_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
                payload["result_path"] = str(result_path)
            except Exception as exc:
                payload["result_write_error"] = str(exc)
        return payload
    if is_python_cpu_fallback and getattr(entry, "result_path", None):
        return apply_worker_entry_context(
            {
                "kind": "cpu",
                "backend": "python_fallback",
                "status": "error",
                "error_count": 1,
                "last_error": "Python CPU fallback did not produce its required worker result file",
                "result_missing": True,
            },
            entry,
            return_code=return_code,
            stdout_tail=read_log_tail(entry.stdout_path),
            stderr_tail=read_log_tail(entry.stderr_path),
        )
    return fallback_worker_payload(
        entry,
        int(return_code),
        stdout_tail=read_log_tail(entry.stdout_path),
        stderr_tail=read_log_tail(entry.stderr_path),
    )


def read_worker_result(
    entry: StageProcess,
    *,
    allow_partial: bool = False,
) -> Optional[Dict[str, Any]]:
    if not entry.result_path:
        return fallback_worker_payload_for_entry(entry, allow_partial=allow_partial)
    path = Path(entry.result_path)
    if not path.exists():
        return fallback_worker_payload_for_entry(entry, allow_partial=allow_partial)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        if allow_partial:
            return None
        return {
            "kind": entry.kind,
            "status": "error",
            "error_count": 1,
            "read_error": str(exc),
            "result_path": str(path),
        }
    if "result_path" not in payload:
        payload["result_path"] = str(path)
    if "kind" not in payload:
        payload["kind"] = entry.kind
    return_code = entry.process.poll()
    stdout_tail = read_log_tail(entry.stdout_path) if return_code not in (None, 0) else ""
    stderr_tail = read_log_tail(entry.stderr_path) if return_code not in (None, 0) else ""
    return apply_worker_entry_context(
        payload,
        entry,
        return_code=return_code,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
    )


def poll_stage_process_failures(
    stage_processes: List[StageProcess],
    display_name: str,
    backend_profile_lookup: Callable[[str], Dict[str, Any]],
) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for entry in stage_processes:
        return_code = entry.process.poll()
        if return_code is None:
            continue
        compatibility_backend = False
        if entry.gpu_spec is not None:
            backend_profile = backend_profile_lookup(entry.gpu_spec.backend)
            compatibility_backend = str(backend_profile.get("load_class", "") or "") == "compatibility"
        if return_code == 0:
            message = (
                "compatibility backend worker exited before the stage completed"
                if compatibility_backend
                else f"{entry.kind} worker exited before the stage completed"
            )
        else:
            message = (
                f"compatibility backend worker exited early with code {return_code}"
                if compatibility_backend
                else f"{entry.kind} worker exited early with code {return_code}"
            )
        events.append(
            create_stability_event(
                "worker_exit",
                "warning" if compatibility_backend else "error",
                display_name,
                entry.kind,
                message,
                {
                    "return_code": return_code,
                    "command": entry.command,
                    "backend": entry.gpu_spec.backend if entry.gpu_spec else "",
                    "target_id": entry.gpu_spec.target_id if entry.gpu_spec else "",
                    "stdout_path": entry.stdout_path or "",
                    "stderr_path": entry.stderr_path or "",
                    "stdout_tail": read_log_tail(entry.stdout_path),
                    "stderr_tail": read_log_tail(entry.stderr_path),
                },
            )
        )
    return events


def worker_result_events(
    stage_processes: List[StageProcess],
    display_name: str,
    backend_profile_lookup: Callable[[str], Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    results: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    for entry in stage_processes:
        payload = read_worker_result(entry)
        if not payload:
            continue
        results.append(payload)
        backend_name = str(payload.get("backend") or gpu_worker_backend_name(payload, vulkan_gpu_3d_backend="python_vulkan_compute") or "").strip()
        backend_profile = backend_profile_lookup(backend_name) if backend_name else {}
        backend_load_class = str(backend_profile.get("load_class", "") or "")
        events.extend(
            worker_result_events_from_payload(
                payload,
                display_name,
                entry_kind=entry.kind,
                backend_name=backend_name,
                backend_load_class=backend_load_class,
            )
        )
    return results, events
