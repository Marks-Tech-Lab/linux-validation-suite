"""Sequential all-eligible-internal-drives Storage Benchmark workflow."""

from __future__ import annotations

import json
import math
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .lvs_storage_benchmark_profile import STORAGE_BENCHMARK_V1
from .lvs_storage_benchmark_target import (
    LowOccupancyTargetIneligible,
    StorageBenchmarkBatchPlan,
    StorageBenchmarkTarget,
)


LOW_OCCUPANCY_MODE = "all_internal_non_root_low_occupancy"


def _selection_fields(
    target: StorageBenchmarkTarget,
    *,
    target_mode: str,
    max_used_percent: float | None,
) -> dict[str, Any]:
    if target_mode != LOW_OCCUPANCY_MODE:
        return {}
    return {
        "target_mode": target_mode,
        "max_used_percent": max_used_percent,
        "target_used_percent_at_selection": target.used_percent_at_selection,
        "target_total_bytes_at_selection": target.total_bytes_at_selection,
        "target_used_bytes_at_selection": target.used_bytes_at_selection,
        "target_free_bytes_at_selection": target.free_bytes_at_selection,
        "target_selection_phase": target.selection_phase or "execution_recheck",
    }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return payload


def _target_result(
    target: StorageBenchmarkTarget,
    model: str,
    result_dir: Path,
    payload: dict[str, Any],
    *,
    target_mode: str = "",
    max_used_percent: float | None = None,
) -> dict[str, Any]:
    key_rows = [
        {
            "test_name": row.get("test_name"),
            "display_name": row.get("display_name"),
            "average_mb_per_s": row.get("average_mb_per_s"),
        }
        for row in payload.get("rows", [])
        if isinstance(row, dict)
    ]
    result = {
        "device": target.physical_devices[0],
        "model": model,
        "target_path": str(target.target_path),
        "target_workspace_path": str(target.target_path),
        "target_filesystem_type": target.filesystem_type,
        "target_filesystem_policy": target.filesystem_policy,
        "target_is_cow": target.is_cow,
        "target_mapping_source": target.mapping_source,
        "target_physical_devices": list(target.physical_devices),
        "target_resolution_warning": target.resolution_warning or None,
        "result_folder": str(result_dir),
        "verdict": payload.get("verdict"),
        "status": payload.get("status"),
        "key_row_results": key_rows,
        "host_writes_delta_tb": payload.get("host_writes_delta_tb"),
        "host_reads_delta_tb": payload.get("host_reads_delta_tb"),
        "media_errors_delta": payload.get("media_errors_delta"),
        "unsafe_shutdowns_delta": payload.get("unsafe_shutdowns_delta"),
        "warnings": list(payload.get("warnings") or []),
        "errors": list(payload.get("errors") or []),
        "skipped_reason": None,
    }
    result.update(_selection_fields(
        target,
        target_mode=target_mode,
        max_used_percent=max_used_percent,
    ))
    if target_mode == LOW_OCCUPANCY_MODE:
        for key in (
            "target_used_percent_at_selection",
            "target_total_bytes_at_selection",
            "target_used_bytes_at_selection",
            "target_free_bytes_at_selection",
            "target_selection_phase",
        ):
            if key in payload:
                result[key] = payload[key]
    return result


def _batch_summary(payload: dict[str, Any]) -> str:
    low_occupancy = payload.get("target_mode") == LOW_OCCUPANCY_MODE
    lines = [
        (
            "Storage Benchmark - Internal Non-Root Low-Occupancy Drives"
            if low_occupancy else "Storage Benchmark - All Eligible Internal Drives"
        ),
        "===============================================================" if low_occupancy else "================================================",
        "",
        f"Verdict: {payload.get('verdict')}",
        f"Profile: {payload.get('profile_id')}",
        f"Test size: {payload.get('test_size_gib')} GiB",
        f"Runs: {payload.get('runs')}",
        f"Estimated maximum writes: {float(payload.get('estimated_max_writes_tb') or 0):.3f} TB",
        "",
    ]
    if low_occupancy:
        lines.extend([
            f"Maximum selected-filesystem usage: {float(payload.get('max_used_percent') or 0):.2f}%",
            "Occupancy basis: selected writable filesystem/workspace; raw disk contents and unmounted filesystems are not inferred.",
            "Root/system drives: always excluded",
            "",
        ])
    for target in payload.get("targets", []):
        lines.append(
            f"{target.get('device')} ({target.get('model') or 'unknown'}) - "
            f"{target.get('verdict') or target.get('status')}"
        )
        lines.append(f"  Target: {target.get('target_path') or '-'}")
        if low_occupancy:
            used = target.get("target_used_percent_at_selection")
            free = target.get("target_free_bytes_at_selection")
            used_text = f"{float(used):.2f}%" if used is not None else "unavailable"
            free_text = f"{float(free) / 1024**3:.2f} GiB" if free is not None else "unavailable"
            lines.append(
                "  Selection: "
                f"filesystem={target.get('target_filesystem_type') or 'unknown'}, "
                f"used={used_text}"
            )
            lines.append(f"  Free at selection: {free_text}")
        if target.get("result_folder"):
            lines.append(f"  Result: {target.get('result_folder')}")
        if target.get("skipped_reason"):
            lines.append(f"  Skipped: {target.get('skipped_reason')}")
        for row in target.get("key_row_results", []):
            speed = row.get("average_mb_per_s")
            value = f"{float(speed):.2f} MB/s" if speed is not None else "unavailable"
            lines.append(f"  {row.get('display_name')}: {value}")
        deltas = []
        for key, label in (
            ("host_writes_delta_tb", "lifetime host writes (TB)"),
            ("host_reads_delta_tb", "lifetime host reads (TB)"),
            ("media_errors_delta", "media errors"),
            ("unsafe_shutdowns_delta", "unsafe shutdowns"),
        ):
            if target.get(key) is not None:
                deltas.append(f"{label}={target.get(key)}")
        if deltas:
            lines.append("  Health deltas: " + ", ".join(deltas))
        for warning in target.get("warnings", []):
            lines.append(f"  Warning: {warning}")
        for error in target.get("errors", []):
            lines.append(f"  Error: {error}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run_all_internal(
    service: Any,
    plan: StorageBenchmarkBatchPlan,
    *,
    test_size_gib: int,
    runs: int,
    confirmation: str,
    root_confirmation: str | None = None,
    cancel_event: threading.Event | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
    aggregate_dir: Path | None = None,
    embed_per_drive_results: bool = False,
    target_mode: str = "",
    max_used_percent: float | None = None,
) -> Path:
    if confirmation != "BENCHMARK ALL INTERNAL":
        raise ValueError("all-internal benchmark requires typed confirmation: BENCHMARK ALL INTERNAL")
    if target_mode == LOW_OCCUPANCY_MODE:
        try:
            threshold = float(3.0 if max_used_percent is None else max_used_percent)
        except (TypeError, ValueError) as exc:
            raise ValueError("max_used_percent must be a finite number from 0.0 through 100.0") from exc
        if not math.isfinite(threshold) or not 0.0 <= threshold <= 100.0:
            raise ValueError("max_used_percent must be a finite number from 0.0 through 100.0")
        max_used_percent = threshold
    elif any(target.is_system_drive for target in plan.targets) and root_confirmation != "BENCHMARK ROOT":
        raise ValueError("root/system drive requires typed confirmation: BENCHMARK ROOT")
    profile = STORAGE_BENCHMARK_V1.with_overrides(test_size_gib=test_size_gib, runs=runs)
    cancel = cancel_event or threading.Event()
    started = datetime.now(timezone.utc)
    stamp = started.astimezone().strftime("%Y-%m-%d_%H-%M-%S")
    if aggregate_dir is None:
        aggregate_dir = service.results_dir / f"{stamp}_Storage_Benchmark_All_Internal"
        suffix = 2
        while aggregate_dir.exists():
            aggregate_dir = service.results_dir / f"{stamp}_Storage_Benchmark_All_Internal_{suffix}"
            suffix += 1
    else:
        aggregate_dir = Path(aggregate_dir)
    aggregate_dir.mkdir(parents=True, exist_ok=False)

    target_results: list[dict[str, Any]] = []
    runtime_skipped: list[dict[str, Any]] = []
    cancelled = False
    for index, target in enumerate(plan.targets):
        if cancel.is_set():
            cancelled = True
            break
        device = target.physical_devices[0]
        if progress:
            progress({"phase": "batch_target", "device": device, "target_index": index + 1, "target_count": len(plan.targets)})
        try:
            if target_mode == LOW_OCCUPANCY_MODE:
                if target.is_system_drive:
                    raise LowOccupancyTargetIneligible(
                        "root/system drive is always excluded by all_internal_non_root_low_occupancy",
                        target,
                    )
                target = service.revalidate_low_occupancy_target(
                    target,
                    test_size_gib=test_size_gib,
                    max_used_percent=max_used_percent,
                )
            run_options = {
                "test_size_gib": test_size_gib,
                "runs": runs,
                "root_confirmation": root_confirmation,
                "confirmed": True,
                "cancel_event": cancel,
                "progress": (
                    (lambda event, selected=device: progress({**event, "device": selected}))
                    if progress else None
                ),
            }
            if target_mode == LOW_OCCUPANCY_MODE:
                run_options.update({
                    "target_mode": target_mode,
                    "max_used_percent": max_used_percent,
                    "expected_target": target,
                })
            if embed_per_drive_results:
                run_options["result_dir"] = aggregate_dir / target.primary_block_name
            result_dir = service.run(
                target.target_path,
                **run_options,
            )
            json_path = result_dir / "storage_benchmark.json"
            summary_path = result_dir / "storage_benchmark_summary.txt"
            if not json_path.is_file() or not summary_path.is_file():
                raise RuntimeError("per-drive benchmark did not produce both required summary artifacts")
            result_payload = _read_json(json_path)
            target_results.append(_target_result(
                target,
                plan.target_models.get(device, target.primary_block_name),
                result_dir,
                result_payload,
                target_mode=target_mode,
                max_used_percent=max_used_percent,
            ))
            if str(result_payload.get("verdict") or "").upper() == "CANCELLED":
                cancelled = True
                break
        except KeyboardInterrupt:
            cancel.set()
            cancelled = True
            break
        except LowOccupancyTargetIneligible as exc:
            measured = exc.target or target
            skipped_result = {
                "device": device,
                "model": plan.target_models.get(device, target.primary_block_name),
                "target_path": str(measured.target_path),
                "target_workspace_path": str(measured.target_path),
                "target_filesystem_type": measured.filesystem_type or None,
                "target_filesystem_policy": measured.filesystem_policy or None,
                "target_is_cow": measured.is_cow,
                "target_mapping_source": measured.mapping_source or None,
                "target_physical_devices": list(measured.physical_devices),
                "target_resolution_warning": measured.resolution_warning or None,
                "result_folder": None,
                "verdict": "SKIPPED",
                "status": "skipped",
                "key_row_results": [],
                "warnings": [],
                "errors": [],
                "skipped_reason": str(exc),
                "eligible_internal": True,
            }
            skipped_result.update(_selection_fields(
                measured,
                target_mode=target_mode,
                max_used_percent=max_used_percent,
            ))
            runtime_skipped.append(skipped_result)
        except Exception as exc:
            failed_result = {
                "device": device,
                "model": plan.target_models.get(device, target.primary_block_name),
                "target_path": str(target.target_path),
                "target_workspace_path": str(target.target_path),
                "target_filesystem_type": target.filesystem_type,
                "target_filesystem_policy": target.filesystem_policy,
                "target_is_cow": target.is_cow,
                "target_mapping_source": target.mapping_source,
                "target_physical_devices": list(target.physical_devices),
                "target_resolution_warning": target.resolution_warning or None,
                "result_folder": None,
                "verdict": "FAIL",
                "status": "failed",
                "key_row_results": [],
                "warnings": [],
                "errors": [str(exc)],
                "skipped_reason": None,
            }
            failed_result.update(_selection_fields(
                target,
                target_mode=target_mode,
                max_used_percent=max_used_percent,
            ))
            target_results.append(failed_result)

    completed_devices = {
        str(item.get("device")) for item in (*target_results, *runtime_skipped)
    }
    if cancelled:
        for target in plan.targets:
            device = target.physical_devices[0]
            if device in completed_devices:
                continue
            target_results.append({
                "device": device,
                "model": plan.target_models.get(device, target.primary_block_name),
                "target_path": str(target.target_path),
                "target_workspace_path": str(target.target_path),
                "target_filesystem_type": target.filesystem_type,
                "target_filesystem_policy": target.filesystem_policy,
                "target_is_cow": target.is_cow,
                "target_mapping_source": target.mapping_source,
                "target_physical_devices": list(target.physical_devices),
                "target_resolution_warning": target.resolution_warning or None,
                "result_folder": None,
                "verdict": "CANCELLED",
                "status": "cancelled",
                "key_row_results": [],
                "warnings": ["Not started because the batch was cancelled."],
                "errors": [],
                "skipped_reason": None,
            })

    skipped_payload = []
    for item in plan.skipped_targets:
        skipped_item = {
            "device": item.device,
            "model": item.model,
            "target_path": None,
            "target_workspace_path": None,
            "target_filesystem_type": None,
            "target_filesystem_policy": None,
            "target_is_cow": None,
            "target_mapping_source": None,
            "target_physical_devices": [item.device] if item.eligible_internal else [],
            "target_resolution_warning": None,
            "result_folder": None,
            "verdict": "SKIPPED",
            "status": "skipped",
            "key_row_results": [],
            "warnings": [],
            "errors": [],
            "skipped_reason": item.reason,
            "eligible_internal": item.eligible_internal,
        }
        if target_mode == LOW_OCCUPANCY_MODE:
            skipped_item.update({
                "target_mode": target_mode,
                "max_used_percent": max_used_percent,
                "target_path": str(item.target_path) if item.target_path else None,
                "target_workspace_path": str(item.target_path) if item.target_path else None,
                "target_filesystem_type": item.filesystem_type or None,
                "target_filesystem_policy": item.filesystem_policy or None,
                "target_is_cow": item.is_cow,
                "target_mapping_source": item.mapping_source or None,
                "target_resolution_warning": item.resolution_warning or None,
                "target_used_percent_at_selection": item.used_percent_at_selection,
                "target_total_bytes_at_selection": item.total_bytes_at_selection,
                "target_used_bytes_at_selection": item.used_bytes_at_selection,
                "target_free_bytes_at_selection": item.free_bytes_at_selection,
                "target_selection_phase": item.selection_phase or "discovery",
            })
        skipped_payload.append(skipped_item)
    skipped_payload.extend(runtime_skipped)
    target_results.extend(skipped_payload)
    target_results.sort(key=lambda item: str(item.get("device") or ""))

    selected = [item for item in target_results if item.get("status") != "skipped"]
    failed_count = sum(str(item.get("verdict")).upper() == "FAIL" for item in selected)
    warned_count = sum(str(item.get("verdict")).upper() == "WARN" for item in selected)
    cancelled_count = sum(str(item.get("verdict")).upper() == "CANCELLED" for item in selected)
    passed_count = sum(str(item.get("verdict")).upper() == "PASS" for item in selected)
    completed_count = sum(
        bool(item.get("result_folder")) and str(item.get("verdict")).upper() != "CANCELLED"
        for item in selected
    )
    eligible_skipped = any(item.eligible_internal for item in plan.skipped_targets) or bool(runtime_skipped)
    if failed_count:
        verdict, status = "FAIL", "failed"
    elif cancelled or cancelled_count:
        verdict, status = "CANCELLED", "cancelled"
    elif warned_count or eligible_skipped or not plan.targets:
        verdict = "WARN"
        status = "skipped" if target_mode == LOW_OCCUPANCY_MODE and not selected else "completed"
    else:
        verdict, status = "PASS", "completed"
    ended = datetime.now(timezone.utc)
    estimated_gib = service.estimated_maximum_written_gib(test_size_gib, runs) * len(plan.targets)
    payload = {
        "contract_id": "lvs.storage_benchmark_batch",
        "contract_version": 1,
        "kind": "storage_benchmark_batch",
        "started": started.isoformat(),
        "ended": ended.isoformat(),
        "status": status,
        "verdict": verdict,
        "profile_id": profile.profile_id,
        "test_size_gib": profile.test_size_gib,
        "runs": profile.runs,
        "total_targets": len(target_results),
        "completed_targets": completed_count,
        "passed_targets": passed_count,
        "warned_targets": warned_count,
        "failed_targets": failed_count,
        "skipped_targets": skipped_payload,
        "cancelled_targets": cancelled_count,
        "estimated_max_writes_tb": estimated_gib * 1024**3 / 1_000_000_000_000,
        "targets": target_results,
    }
    if target_mode == LOW_OCCUPANCY_MODE:
        payload.update({
            "target_mode": target_mode,
            "max_used_percent": max_used_percent,
            "selection_policy": {
                "occupancy_basis": "selected_writable_filesystem_workspace",
                "max_used_percent": max_used_percent,
                "root_system_drives_excluded": True,
                "unmounted_filesystems_not_measured": True,
            },
        })
    service._write_json(aggregate_dir / "storage_benchmark_all_internal.json", payload)
    (aggregate_dir / "storage_benchmark_all_internal_summary.txt").write_text(
        _batch_summary(payload), encoding="utf-8"
    )
    return aggregate_dir
