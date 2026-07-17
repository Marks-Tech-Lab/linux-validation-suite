"""Standalone, file-backed Storage Benchmark v1 workflow."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .lvs_fio_backend import (
    aggregate_row,
    build_fio_command,
    build_fio_prepare_command,
    load_fio_result,
    storage_benchmark_capability,
)
from .lvs_storage_benchmark_profile import STORAGE_BENCHMARK_V1, storage_benchmark_execution_rows
from .lvs_storage_benchmark_target import (
    GIB,
    StorageBenchmarkBatchPlan,
    StorageBenchmarkTarget,
    StorageTargetResolver,
)
from .lvs_storage_health import StorageHealthEnricher
from .lvs_storage_inventory import build_storage_device_entry, read_text_sysfs
from .lvs_telemetry_collector import TelemetryCollector


class BenchmarkCancelled(RuntimeError):
    pass


class DirectIoUnsupported(RuntimeError):
    pass


class _NoTelemetry:
    def __init__(self, interval_seconds: float) -> None:
        self.interval_seconds = interval_seconds
        self.samples: list[Any] = []
        self._storage_temp_sources: list[dict[str, Any]] = []

    def collect_once(self) -> None:
        return

    def write_csv(self, _path: Path) -> None:
        return


class StorageBenchmarkService:
    def __init__(
        self,
        results_dir: Path,
        *,
        runtime_environment: dict[str, str] | None = None,
        privileged_helper_enabled: bool = False,
        resolver: StorageTargetResolver | None = None,
        telemetry_factory: Callable[..., Any] = TelemetryCollector,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self.results_dir = Path(results_dir)
        self.runtime_environment = dict(runtime_environment or {})
        self.privileged_helper_enabled = privileged_helper_enabled
        self.resolver = resolver or StorageTargetResolver()
        self.telemetry_factory = telemetry_factory
        self.which = which

    def capability(self) -> dict[str, Any]:
        return storage_benchmark_capability(which=self.which)

    def preflight(self, target_path: Path, *, test_size_gib: int, root_confirmation: str | None = None) -> StorageBenchmarkTarget:
        return self.resolver.resolve(target_path, test_size_gib=test_size_gib, root_confirmation=root_confirmation)

    def discover_all_eligible(
        self, *, test_size_gib: int, root_confirmation: str | None = None
    ) -> StorageBenchmarkBatchPlan:
        return self.resolver.discover_all_eligible(
            test_size_gib=test_size_gib,
            root_confirmation=root_confirmation,
        )

    def run_all_internal(self, plan: StorageBenchmarkBatchPlan, **kwargs: Any) -> Path:
        from .lvs_storage_benchmark_batch import run_all_internal
        return run_all_internal(self, plan, **kwargs)

    @staticmethod
    def estimated_maximum_written_gib(test_size_gib: int, runs: int) -> int:
        return int(test_size_gib) * (1 + 4 * int(runs))

    def _health(self, block_name: str) -> dict[str, Any]:
        block_dir = Path("/sys/block") / block_name
        try:
            entry = build_storage_device_entry(block_dir)
            enrichment = StorageHealthEnricher(
                read_sysfs=read_text_sysfs,
                privileged_helper_enabled=self.privileged_helper_enabled,
            ).enrich(block_dir, entry)
            # Do not persist serial/vendor raw data in benchmark health snapshots.
            return {
                "device": f"/dev/{block_name}",
                "is_internal": enrichment.get("is_internal"),
                "is_removable": enrichment.get("is_removable"),
                "is_usb": enrichment.get("is_usb"),
                "storage_health": enrichment.get("storage_health") or {},
            }
        except Exception as exc:
            return {"device": f"/dev/{block_name}", "storage_health": {"query_status": "unavailable", "query_notes": [str(exc)]}}

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @staticmethod
    def _new_file(path: Path, size: int) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            if hasattr(os, "posix_fallocate"):
                os.posix_fallocate(descriptor, 0, size)
            else:
                os.ftruncate(descriptor, size)
        finally:
            os.close(descriptor)

    def _make_session(self, target: StorageBenchmarkTarget, size: int) -> tuple[Path, str]:
        token = uuid.uuid4().hex
        session = target.target_path / f".lvs-storage-benchmark-{token}"
        session.mkdir(mode=0o700)
        marker = {"contract_id": "lvs.storage_benchmark.session", "token": token, "target_stat_device": target.stat_device,
                  "expected_files": ["read.bin", "write.bin", ".lvs-session.json"]}
        try:
            self._write_json(session / ".lvs-session.json", marker)
            self._new_file(session / "read.bin", size)
            self._new_file(session / "write.bin", size)
        except Exception:
            for name in ("read.bin", "write.bin", ".lvs-session.json"):
                path = session / name
                if path.exists() and path.is_file() and path.stat().st_uid == os.getuid():
                    path.unlink()
            if session.exists() and not any(session.iterdir()):
                session.rmdir()
            raise
        return session, token

    def _cleanup(self, session: Path, token: str, target: StorageBenchmarkTarget) -> None:
        self.resolver.revalidate(target)
        marker_path = session / ".lvs-session.json"
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        expected = {"read.bin", "write.bin", ".lvs-session.json"}
        if (
            marker.get("token") != token
            or marker.get("target_stat_device") != target.stat_device
            or set(marker.get("expected_files") or []) != expected
        ):
            raise RuntimeError("cleanup safety violation: invalid session marker")
        actual = {item.name for item in session.iterdir()}
        if (
            not actual.issubset(expected)
            or session.parent.resolve() != target.target_path
            or session.stat().st_dev != target.stat_device
            or any(item.stat().st_dev != target.stat_device for item in session.iterdir())
        ):
            raise RuntimeError("cleanup safety violation: unexpected session contents or location")
        if session.stat().st_uid != os.getuid() or any(item.stat().st_uid != os.getuid() for item in session.iterdir()):
            raise RuntimeError("cleanup safety violation: ownership changed")
        for name in ("read.bin", "write.bin", ".lvs-session.json"):
            path = session / name
            if path.exists():
                path.unlink()
        session.rmdir()

    @staticmethod
    def _run_process(command: list[str], cancel: threading.Event, telemetry: Any) -> int:
        process = subprocess.Popen(command, start_new_session=True)
        interval = max(0.25, float(getattr(telemetry, "interval_seconds", 5)))
        last_sample = getattr(telemetry, "_lvs_storage_benchmark_last_sample", None)
        next_sample = (float(last_sample) + interval) if last_sample is not None else 0.0
        try:
            while process.poll() is None:
                if cancel.is_set():
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=3)
                    raise BenchmarkCancelled("operator cancellation")
                now = time.monotonic()
                if now >= next_sample:
                    try:
                        telemetry.collect_once()
                        telemetry._lvs_storage_benchmark_last_sample = now
                    except Exception:
                        pass
                    next_sample = now + interval
                time.sleep(0.1)
            return int(process.returncode or 0)
        except KeyboardInterrupt as exc:
            cancel.set()
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
            raise BenchmarkCancelled("operator cancellation") from exc

    @staticmethod
    def _fio_job_errors(path: Path) -> list[int]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return [int(job.get("error") or 0) for job in payload.get("jobs", []) if isinstance(job, dict)]
        except Exception:
            return []

    @staticmethod
    def _temperature_summary(telemetry: Any, block_name: str) -> tuple[float | None, float | None, float | None]:
        keys = {
            str(source.get("key"))
            for source in getattr(telemetry, "_storage_temp_sources", [])
            if source.get("block_name") == block_name and source.get("key")
        }
        values: list[float] = []
        for sample in getattr(telemetry, "samples", []):
            candidates = [float(value) for key, value in sample.values.items() if key in keys and value is not None]
            if candidates:
                values.append(max(candidates))
        return (values[0], max(values), values[-1]) if values else (None, None, None)

    @staticmethod
    def _hardware_temperature_warning_c(telemetry: Any, block_name: str) -> float | None:
        thresholds: list[float] = []
        for source in getattr(telemetry, "_storage_temp_sources", []):
            if source.get("block_name") != block_name or not source.get("path"):
                continue
            input_path = Path(str(source["path"]))
            for suffix in ("_max", "_crit"):
                threshold_path = input_path.with_name(input_path.name.replace("_input", suffix))
                try:
                    value = float(threshold_path.read_text(encoding="utf-8").strip()) / 1000.0
                except (OSError, ValueError):
                    continue
                if value > 0:
                    thresholds.append(value)
                    break
        return min(thresholds) if thresholds else None

    @staticmethod
    def _counter_delta(before: dict[str, Any], after: dict[str, Any], key: str) -> float | int | None:
        old = (before.get("storage_health") or {}).get(key)
        new = (after.get("storage_health") or {}).get(key)
        if old is None or new is None:
            return None
        delta = new - old
        return delta if delta >= 0 else None

    @staticmethod
    def _summary(result: dict[str, Any]) -> str:
        lines = [result["profile_name"], f"Verdict: {result['verdict']}", f"Target device: {result['target_device']}", ""]
        for row in result.get("rows", []):
            speed = row.get("average_mb_per_s")
            lines.append(f"{row['display_name']}: {speed:.2f} MB/s" if speed is not None else f"{row['display_name']}: {row['status']}")
        if result.get("warnings"):
            lines.extend(["", "Warnings:", *[f"- {item}" for item in result["warnings"]]])
        if result.get("errors"):
            lines.extend(["", "Errors:", *[f"- {item}" for item in result["errors"]]])
        return "\n".join(lines) + "\n"

    def run(
        self,
        target_path: Path,
        *,
        test_size_gib: int = 1,
        runs: int = 5,
        root_confirmation: str | None = None,
        confirmed: bool = False,
        cancel_event: threading.Event | None = None,
        progress: Callable[[dict[str, Any]], None] | None = None,
        result_dir: Path | None = None,
    ) -> Path:
        if not confirmed:
            raise ValueError("storage benchmark requires explicit confirmation")
        profile = STORAGE_BENCHMARK_V1.with_overrides(test_size_gib=test_size_gib, runs=runs)
        target = self.preflight(target_path, test_size_gib=test_size_gib, root_confirmation=root_confirmation)
        capability = self.capability()
        started = datetime.now(timezone.utc)
        stamp = started.astimezone().strftime("%Y-%m-%d_%H-%M-%S")
        device_label = target.primary_block_name.replace("/", "_")
        if result_dir is None:
            result_dir = self.results_dir / f"{stamp}_Storage_Benchmark_{device_label}"
            suffix = 2
            while result_dir.exists():
                result_dir = self.results_dir / f"{stamp}_Storage_Benchmark_{device_label}_{suffix}"
                suffix += 1
        else:
            result_dir = Path(result_dir)
        result_dir.mkdir(parents=True, exist_ok=False)
        raw_dir = result_dir / "raw_fio"
        raw_dir.mkdir(mode=0o700)
        manifest = {
            "contract_id": "lvs.storage_benchmark.manifest",
            "contract_version": 1,
            "kind": "storage_benchmark",
            "status": "active",
            "started": started.isoformat(),
            "target_workspace_path": str(target.target_path),
            "target_filesystem_type": target.filesystem_type,
            "target_filesystem_policy": target.filesystem_policy,
            "target_is_cow": target.is_cow,
            "target_mapping_source": target.mapping_source,
            "target_physical_devices": list(target.physical_devices),
            "target_resolution_warning": target.resolution_warning or None,
            "artifacts": [],
        }
        self._write_json(result_dir / "storage_benchmark_manifest.json", manifest)
        warnings: list[str] = []
        errors: list[str] = []
        if target.is_system_drive:
            warnings.append("Benchmark target is the root/system drive.")
        if target.resolution_warning:
            warnings.append(target.resolution_warning)
        before = self._health(target.primary_block_name)
        self._write_json(result_dir / "storage_health_before.json", before)
        before_query = (before.get("storage_health") or {}).get("query_status")
        if before_query not in {"available", "partial"}:
            warnings.append("SMART/storage health was unavailable before the benchmark.")
        elif before_query == "partial":
            warnings.append("SMART/storage health coverage was partial before the benchmark.")
        cancel = cancel_event or threading.Event()
        status = "completed"
        verdict = "WARN" if warnings else "PASS"
        try:
            telemetry = self.telemetry_factory(
                interval_seconds=profile.interval_seconds,
                runtime_environment=self.runtime_environment,
                privileged_helper_enabled=self.privileged_helper_enabled,
            )
        except Exception as exc:
            telemetry = _NoTelemetry(profile.interval_seconds)
            warnings.append(f"Structured storage temperature telemetry is unavailable: {exc}")
            if verdict == "PASS":
                verdict = "WARN"
        session: Path | None = None
        token = ""
        rows: list[dict[str, Any]] = []
        fio_path = self.which("fio")
        try:
            if (before.get("storage_health") or {}).get("smart_health") == "failed":
                status, verdict = "failed", "FAIL"
                errors.append("SMART health reports failed before the benchmark; fio was not started.")
            elif not capability.get("benchmark_mode_available") or not fio_path:
                status, verdict = "unavailable", "WARN"
                warnings.extend(capability.get("notes") or ["fio/libaio is unavailable."])
            else:
                session, token = self._make_session(target, profile.test_size_gib * GIB)
                # Fully initialize the read file using the same direct fio backend.
                prep_output = raw_dir / "prepare_read_file.json"
                prep_command = build_fio_prepare_command(
                    fio_path, profile, filename=session / "read.bin", output_path=prep_output, session_dir=session
                )
                self.resolver.revalidate(target)
                if progress:
                    progress({"phase": "prepare", "message": "Initializing benchmark read file"})
                prep_exit = self._run_process(prep_command, cancel, telemetry)
                prep_errors = self._fio_job_errors(prep_output)
                if 22 in prep_errors:
                    raise DirectIoUnsupported(
                        f"direct I/O is unsupported for {target.mount_point}; buffered fallback is disabled"
                    )
                if prep_exit != 0 or not prep_errors or any(prep_errors):
                    raise RuntimeError("fio failed while initializing read.bin")
                execution_rows = storage_benchmark_execution_rows(profile)
                for execution_index, row in enumerate(execution_rows):
                    row_index = profile.rows.index(row)
                    self.resolver.revalidate(target)
                    run_results = []
                    job_name = f"lvs_{row.test_name}"
                    for run_number in range(1, profile.runs + 1):
                        if cancel.is_set():
                            raise BenchmarkCancelled("operator cancellation")
                        self.resolver.revalidate(target)
                        raw_name = f"{row_index + 1:02d}_{row.test_name}_run_{run_number:02d}.json"
                        raw_path = raw_dir / raw_name
                        filename = session / ("read.bin" if row.operation in {"read", "randread"} else "write.bin")
                        command = build_fio_command(fio_path, profile, row, filename=filename, output_path=raw_path,
                                                    job_name=job_name, session_dir=session)
                        if progress:
                            progress({"phase": "benchmark", "row": row.display_name, "run": run_number, "runs": profile.runs})
                        exit_code = self._run_process(command, cancel, telemetry)
                        if exit_code:
                            job_errors = self._fio_job_errors(raw_path)
                            if 22 in job_errors:
                                raise DirectIoUnsupported(
                                    f"direct I/O is unsupported for {target.mount_point}; buffered fallback is disabled"
                                )
                            run_results.append({"run_number": run_number, "status": "failed", "fio_error": exit_code,
                                                "error": f"fio exited with status {exit_code}", "raw_fio_path": f"raw_fio/{raw_name}"})
                            break
                        parsed = load_fio_result(raw_path, row, run_number=run_number)
                        parsed["raw_fio_path"] = f"raw_fio/{raw_name}"
                        run_results.append(parsed)
                        if parsed["status"] != "completed":
                            break
                    aggregated = aggregate_row(row, run_results, job_name)
                    rows.append(aggregated)
                    if aggregated["status"] != "completed":
                        raise RuntimeError(aggregated.get("error") or f"fio failed for {row.display_name}")
                    if execution_index < len(execution_rows) - 1:
                        deadline = time.monotonic() + profile.interval_seconds
                        while time.monotonic() < deadline:
                            if cancel.wait(min(0.25, deadline - time.monotonic())):
                                raise BenchmarkCancelled("operator cancellation")
        except (BenchmarkCancelled, KeyboardInterrupt) as exc:
            status, verdict = "cancelled", "CANCELLED"
            warnings.append(str(exc) or "operator cancellation")
        except DirectIoUnsupported as exc:
            status, verdict = "unsupported", "WARN"
            warnings.append(str(exc))
        except Exception as exc:
            status, verdict = "failed", "FAIL"
            errors.append(str(exc))
        finally:
            if session is not None and session.exists():
                try:
                    self._cleanup(session, token, target)
                except Exception as exc:
                    status, verdict = "failed", "FAIL"
                    errors.append(str(exc))
        after = self._health(target.primary_block_name)
        try:
            self.resolver.revalidate(target)
        except Exception as exc:
            status, verdict = "failed", "FAIL"
            errors.append(str(exc))
        self._write_json(result_dir / "storage_health_after.json", after)
        media_delta = self._counter_delta(before, after, "media_errors")
        unsafe_delta = self._counter_delta(before, after, "unsafe_shutdowns")
        writes_delta = self._counter_delta(before, after, "host_writes_tb")
        reads_delta = self._counter_delta(before, after, "host_reads_tb")
        for counter in ("host_writes_tb", "host_reads_tb", "media_errors", "unsafe_shutdowns"):
            old_value = (before.get("storage_health") or {}).get(counter)
            new_value = (after.get("storage_health") or {}).get(counter)
            if old_value is not None and new_value is not None and new_value < old_value:
                warnings.append(f"{counter} decreased; delta is unavailable because the device counter reset or wrapped.")
                if verdict == "PASS":
                    verdict = "WARN"
        after_query = (after.get("storage_health") or {}).get("query_status")
        if after_query not in {"available", "partial"}:
            if not any("health was unavailable" in item for item in warnings):
                warnings.append("SMART/storage health was unavailable after the benchmark.")
        elif after_query == "partial":
            warnings.append("SMART/storage health coverage was partial after the benchmark.")
        if warnings and verdict == "PASS":
            verdict = "WARN"
        if (after.get("storage_health") or {}).get("smart_health") == "failed":
            verdict, status = "FAIL", "failed"
            errors.append("SMART health reports failed after the benchmark.")
        if media_delta is not None and media_delta > 0:
            verdict, status = "FAIL", "failed"
            errors.append("Storage media error counter increased.")
        if unsafe_delta is not None and unsafe_delta > 0:
            warnings.append("Unsafe shutdown counter increased.")
            if verdict == "PASS":
                verdict = "WARN"
        temp_start, temp_max, temp_end = self._temperature_summary(telemetry, target.primary_block_name)
        hardware_temp_warning = self._hardware_temperature_warning_c(telemetry, target.primary_block_name)
        if temp_max is not None and hardware_temp_warning is not None and temp_max >= hardware_temp_warning:
            warnings.append(
                f"Storage temperature reached {temp_max:.1f} C, at or above the hardware-provided "
                f"{hardware_temp_warning:.1f} C warning threshold."
            )
            if verdict == "PASS":
                verdict = "WARN"
        row_by_name = {row.get("test_name"): row for row in rows}
        rows = [row_by_name[row.test_name] for row in profile.rows if row.test_name in row_by_name]
        if getattr(telemetry, "samples", []):
            telemetry.write_csv(result_dir / "storage_telemetry.csv")
        ended = datetime.now(timezone.utc)
        result = {
            "contract_id": "lvs.storage_benchmark", "contract_version": 1, "kind": "storage_benchmark",
            "profile_id": profile.profile_id, "profile_name": profile.profile_name,
            "backend": "fio", "backend_version": capability.get("fio_version"),
            "started": started.isoformat(), "ended": ended.isoformat(), "status": status, "verdict": verdict,
            "target_path": str(target.target_path), "target_mount_point": str(target.mount_point),
            "target_device": target.mount_source, "target_physical_devices": list(target.physical_devices),
            "target_workspace_path": str(target.target_path),
            "target_filesystem_type": target.filesystem_type,
            "target_filesystem_policy": target.filesystem_policy,
            "target_is_cow": target.is_cow,
            "target_mapping_source": target.mapping_source,
            "target_resolution_warning": target.resolution_warning or None,
            "target_is_system_drive": target.is_system_drive, "test_size_gib": profile.test_size_gib, "runs": profile.runs,
            "measure_time_seconds": profile.measure_time_seconds, "interval_seconds": profile.interval_seconds,
            "direct_io": profile.direct_io, "ioengine": profile.ioengine, "test_data": profile.test_data,
            "result_unit": profile.result_unit,
            "temp_start_c": temp_start, "temp_max_c": temp_max, "temp_end_c": temp_end,
            "host_writes_delta_tb": writes_delta, "host_reads_delta_tb": reads_delta,
            "media_errors_delta": media_delta, "unsafe_shutdowns_delta": unsafe_delta,
            "rows": rows, "warnings": warnings, "errors": errors,
        }
        self._write_json(result_dir / "storage_benchmark.json", result)
        (result_dir / "storage_benchmark_summary.txt").write_text(self._summary(result), encoding="utf-8")
        manifest.update(status=status, ended=ended.isoformat(), verdict=verdict,
                        artifacts=sorted(str(path.relative_to(result_dir)) for path in result_dir.rglob("*") if path.is_file()))
        self._write_json(result_dir / "storage_benchmark_manifest.json", manifest)
        return result_dir
