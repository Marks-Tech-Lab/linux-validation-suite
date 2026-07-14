#!/usr/bin/env python3
"""Intel GPU sidecar parser and summary helpers."""

from __future__ import annotations

import json
import re
import statistics
import subprocess
from pathlib import Path
from shutil import which
from typing import Any, Callable, Dict, List, Optional

from Modules.lvs_core import JsonStore, now_local_iso
from Modules.lvs_telemetry_sampling import json_objects_from_text, parse_intel_gpu_top_snapshot


def intel_gpu_top_failure_reason(stderr_text: str, raw_path: Optional[Path] = None) -> str:
    lowered = (stderr_text or "").lower()
    if "permission denied" in lowered and ("cap_perfmon" in lowered or "pmu" in lowered):
        return "intel_gpu_top could not read Intel PMU counters; CAP_PERFMON or a less restrictive perf policy is required"
    if "failed to initialize pmu" in lowered:
        return "intel_gpu_top failed to initialize Intel PMU counters"
    if raw_path is not None:
        if not raw_path.exists():
            return "intel_gpu_top did not create a JSON output file"
        if raw_path.stat().st_size == 0:
            return "intel_gpu_top created an empty JSON output file"
    return "intel_gpu_top produced no parseable JSON samples"


def intel_gpu_top_json_sample_attempt(
    *,
    command_exists: Callable[[str], bool],
    command_env: Callable[[], Dict[str, str]],
    run_command: Callable[..., Any] = subprocess.run,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "command": [],
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "fallback_used": False,
        "error": "",
    }
    if not command_exists("intel_gpu_top"):
        payload["error"] = "intel_gpu_top not found"
        return payload
    commands = [
        ["intel_gpu_top", "-J", "-s", "500", "-n", "2", "-d", "pci:vendor=8086", "-o", "-"],
        ["intel_gpu_top", "-J", "-s", "500", "-n", "2", "-o", "-"],
    ]
    last_payload = dict(payload)
    for index, command in enumerate(commands):
        current = dict(payload)
        current["command"] = command
        current["fallback_used"] = index > 0
        try:
            completed = run_command(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
                env=command_env(),
            )
            current["returncode"] = completed.returncode
            current["stdout"] = completed.stdout or ""
            current["stderr"] = completed.stderr or ""
        except Exception as exc:
            current["error"] = str(exc)
        if current.get("stdout"):
            return current
        last_payload = current
    return last_payload


def collect_intel_gpu_top_details(
    *,
    command_exists: Callable[[str], bool],
    command_env: Callable[[], Dict[str, str]],
    run_command: Callable[..., Any] = subprocess.run,
    sample_attempt: Optional[Callable[[], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    details: Dict[str, Any] = {
        "available": False,
        "usable": False,
        "list_available": False,
        "path": "",
        "command": "intel_gpu_top",
        "package_names": ["intel-gpu-tools"],
        "required_for": [
            "Intel GPU busy telemetry when sysfs does not expose gpu_busy_percent",
            "Intel per-engine utilization diagnostics",
        ],
        "devices": [],
        "json_sample_available": False,
        "json_sample_metrics": {},
        "json_sample_command": [],
        "json_sample_returncode": None,
        "json_sample_stdout_excerpt": "",
        "json_sample_stderr_excerpt": "",
        "json_sample_fallback_used": False,
        "reason": "",
        "telemetry_role": "optional Intel PMU telemetry source for busy and engine utilization",
    }
    if not command_exists("intel_gpu_top"):
        details["reason"] = "intel_gpu_top not found"
        return details
    details["available"] = True
    details["path"] = "intel_gpu_top"
    try:
        completed = run_command(
            ["intel_gpu_top", "-L"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env=command_env(),
        )
    except Exception as exc:
        details["reason"] = f"intel_gpu_top -L failed: {exc}"
        return details

    text = (completed.stdout or "").strip()
    if completed.returncode != 0:
        details["reason"] = (completed.stderr or completed.stdout or "intel_gpu_top -L failed").strip()
        return details

    details["list_available"] = True
    details["devices"] = [
        {"raw": line}
        for line in (raw_line.strip() for raw_line in text.splitlines())
        if line
    ]
    try:
        attempt = (
            sample_attempt()
            if sample_attempt is not None
            else intel_gpu_top_json_sample_attempt(
                command_exists=command_exists,
                command_env=command_env,
                run_command=run_command,
            )
        )
        sample_text = str(attempt.get("stdout") or "")
        details["json_sample_command"] = list(attempt.get("command") or [])
        details["json_sample_returncode"] = attempt.get("returncode")
        details["json_sample_stdout_excerpt"] = sample_text[:4000]
        details["json_sample_stderr_excerpt"] = str(attempt.get("stderr") or attempt.get("error") or "")[:4000]
        details["json_sample_fallback_used"] = bool(attempt.get("fallback_used"))
        snapshots = [item for item in json_objects_from_text(sample_text) if isinstance(item, dict)]
        for snapshot in reversed(snapshots):
            metrics = parse_intel_gpu_top_snapshot(snapshot)
            if metrics:
                details["json_sample_available"] = True
                details["json_sample_metrics"] = metrics
                details["usable"] = True
                break
        if not details["json_sample_available"]:
            sample_error = str(attempt.get("stderr") or attempt.get("error") or "")
            if sample_error:
                details["reason"] = intel_gpu_top_failure_reason(sample_error)
            else:
                details["reason"] = "intel_gpu_top is installed, but JSON sample did not expose parseable busy counters"
    except Exception as exc:
        details["reason"] = f"intel_gpu_top JSON sample failed: {exc}"
    return details


def load_intel_gpu_top_objects(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    decoder = json.JSONDecoder()
    objects: List[Dict[str, Any]] = []
    index = 0
    while index < len(text):
        next_obj = text.find("{", index)
        if next_obj < 0:
            break
        try:
            obj, end = decoder.raw_decode(text[next_obj:])
        except Exception:
            index = next_obj + 1
            continue
        if isinstance(obj, dict):
            objects.append(obj)
        index = next_obj + max(1, end)
    return objects


def summarize_numeric_series(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {
            "sample_count": 0,
            "min": None,
            "avg": None,
            "max": None,
            "stddev": None,
            "range": None,
            "samples_at_or_below_1_percent": 0,
            "samples_below_50_percent": 0,
            "samples_below_75_percent": 0,
            "zero_crossing_transitions": 0,
        }
    return {
        "sample_count": len(values),
        "min": round(min(values), 3),
        "avg": round(statistics.mean(values), 3),
        "max": round(max(values), 3),
        "stddev": round(statistics.pstdev(values), 3) if len(values) > 1 else 0.0,
        "range": round(max(values) - min(values), 3),
        "samples_at_or_below_1_percent": sum(1 for value in values if value <= 1.0),
        "samples_below_50_percent": sum(1 for value in values if value < 50.0),
        "samples_below_75_percent": sum(1 for value in values if value < 75.0),
        "zero_crossing_transitions": sum(
            1
            for previous, current in zip(values, values[1:])
            if (previous <= 1.0 < current) or (current <= 1.0 < previous)
        ),
    }


def summarize_intel_gpu_top_sidecar(sidecar: Dict[str, Any]) -> Dict[str, Any]:
    raw_path = Path(sidecar["raw_path"])
    objects = load_intel_gpu_top_objects(raw_path)
    stderr_path = Path(sidecar.get("stderr_path") or "")
    stderr_text = ""
    if stderr_path.exists():
        stderr_text = stderr_path.read_text(encoding="utf-8", errors="ignore").strip()
    reason = ""
    if not objects:
        reason = intel_gpu_top_failure_reason(stderr_text, raw_path)
    engine_values: Dict[str, List[float]] = {}
    aggregate_values: List[float] = []
    for obj in objects:
        engines = obj.get("engines") if isinstance(obj.get("engines"), dict) else {}
        snapshot_values: List[float] = []
        for engine_name, engine_payload in engines.items():
            if not isinstance(engine_payload, dict):
                continue
            busy = engine_payload.get("busy")
            if not isinstance(busy, (int, float)):
                continue
            value = float(busy)
            engine_values.setdefault(str(engine_name), []).append(value)
            snapshot_values.append(value)
        if snapshot_values:
            aggregate_values.append(max(snapshot_values))
    return {
        "available": bool(objects),
        "stage_id": sidecar.get("stage_id"),
        "stage_name": sidecar.get("stage_name"),
        "started": sidecar.get("started"),
        "ended": now_local_iso(),
        "command": list(sidecar.get("command") or []),
        "raw_path": str(raw_path),
        "summary_path": str(sidecar.get("summary_path")),
        "stderr_path": str(sidecar.get("stderr_path")),
        "reason": reason,
        "stderr_excerpt": stderr_text[:2000],
        "object_count": len(objects),
        "aggregate_engine_busy": summarize_numeric_series(aggregate_values),
        "engines": {
            engine_name: summarize_numeric_series(values)
            for engine_name, values in sorted(engine_values.items())
        },
    }


def start_intel_gpu_top_sidecar(
    *,
    stage_id: str,
    stage_name: str,
    run_dir: Path,
    which_func: Callable[[str], Optional[str]] = which,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    now_func: Callable[[], str] = now_local_iso,
    json_writer: Callable[[Path, Dict[str, Any]], None] = JsonStore.write,
) -> Optional[Dict[str, Any]]:
    if not which_func("intel_gpu_top"):
        return None
    sidecar_dir = run_dir / "intel_gpu_top"
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    safe_stage = re.sub(r"[^A-Za-z0-9_.-]+", "_", stage_id or "stage").strip("_") or "stage"
    output_path = sidecar_dir / f"{safe_stage}.json"
    stderr_path = sidecar_dir / f"{safe_stage}.stderr.log"
    stderr_handle = stderr_path.open("w", encoding="utf-8")
    command = [
        "intel_gpu_top",
        "-J",
        "-s",
        "100",
        "-d",
        "pci:vendor=8086",
        "-o",
        str(output_path),
    ]
    try:
        process = popen_factory(
            command,
            stdout=subprocess.DEVNULL,
            stderr=stderr_handle,
            text=True,
        )
    except Exception as exc:
        stderr_handle.close()
        json_writer(
            sidecar_dir / f"{safe_stage}.summary.json",
            {
                "available": False,
                "stage_id": stage_id,
                "stage_name": stage_name,
                "command": command,
                "error": str(exc),
                "raw_path": str(output_path),
                "stderr_path": str(stderr_path),
            },
        )
        return None
    return {
        "process": process,
        "stderr_handle": stderr_handle,
        "stage_id": stage_id,
        "stage_name": stage_name,
        "command": command,
        "raw_path": output_path,
        "stderr_path": stderr_path,
        "summary_path": sidecar_dir / f"{safe_stage}.summary.json",
        "started": now_func(),
    }


def stop_intel_gpu_top_sidecar(
    sidecar: Optional[Dict[str, Any]],
    *,
    summary_builder: Callable[[Dict[str, Any]], Dict[str, Any]] = summarize_intel_gpu_top_sidecar,
    json_writer: Callable[[Path, Dict[str, Any]], None] = JsonStore.write,
) -> Optional[Dict[str, Any]]:
    if not sidecar:
        return None
    process = sidecar.get("process")
    if hasattr(process, "poll"):
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        except Exception:
            pass
    stderr_handle = sidecar.get("stderr_handle")
    try:
        if stderr_handle:
            stderr_handle.close()
    except Exception:
        pass
    summary = summary_builder(sidecar)
    json_writer(Path(sidecar["summary_path"]), summary)
    return summary
