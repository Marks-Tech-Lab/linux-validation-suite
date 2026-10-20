"""Deterministic stall diagnostics; no GPU or deliberate real blocking required."""
from __future__ import annotations

import copy
import io
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from smoke_tests.vulkan_workload_effectiveness_checks import _worker_payload
from vulkan_compute_worker import SlowOperationRecorder, persist_worker_result, register_worker_exit_diagnostics
from Modules.lvs_compat_export_gpu import build_gpu_worker_validation_detail
from Modules.lvs_segment_gpu_worker_summary import GpuWorkerStateSummaryBuilder
from Modules.lvs_worker_integrity import worker_result_successful


class Clock:
    def __init__(self):
        self.mono, self.wall, self.cpu = 100.0, 1792435000.0, 1.0

    def advance(self, seconds, cpu=0.001):
        self.mono += seconds
        self.wall += seconds
        self.cpu += cpu


def _recorder(state=None, capacity=64):
    clock = Clock()
    state = state if state is not None else dict(physical_gpu_id="pci:0000:41:00.0",
        telemetry_gpu_index=0, vulkan_device_index=1, kernel_variant="stress_hash",
        target_id="0000:41:00.0", worker_result_file="worker_results/segment_4_gpu_3d_1.json")
    recorder = SlowOperationRecorder(state, clock=lambda: clock.mono,
        wall_clock=lambda: clock.wall, cpu_clock=lambda: clock.cpu, capacity=capacity)
    return recorder, clock, state


def _artifact_round_trip(worker, root):
    from Modules.lvs_compat_exporter import CompatibilityExporter
    from Modules.lvs_core import JsonStore
    from Modules.lvs_profile_models import ValidationProfile
    from Modules.lvs_run_artifacts import write_final_run_artifacts
    from Modules.lvs_run_metadata import RunMetadata
    from Modules.lvs_run_models import StageWindow
    from Modules.lvs_segment_parser import SegmentParser
    from Modules.lvs_summary_text import SummaryTextBuilder

    JsonStore.write(root / "native_gpu.json", worker)
    native = JsonStore.read(root / "native_gpu.json", {})
    window = StageWindow(stage_id="gpu", stage_type="Combined", display_name="GPU fixture",
        started_iso="2026-10-19T14:36:42-04:00", ended_iso="2026-10-19T14:46:42-04:00",
        started_monotonic=100.0, ended_monotonic=700.0, duration_seconds=600.0,
        trim_start_seconds=30, trim_end_seconds=30, worker_results=[native], verdict="pass")
    write_final_run_artifacts(run_dir=root, manifest_payload={}, app_name="Linux Validation Suite",
        app_version="0.5.1-alpha", profile=ValidationProfile(profile_name="GPU fixture"), metadata=RunMetadata(),
        started_iso=window.started_iso, ended_iso=window.ended_iso, total_elapsed=600.0,
        system_info={"Hardware": {"Cpu": {"Name": "fixture CPU"}, "Gpu": [], "Memory": {}, "Motherboard": {}, "Bios": {}, "Storage": []}},
        telemetry=SimpleNamespace(samples=[], interval_seconds=2.0, _gpu_sources=[], source_map=lambda: {"fields": {}}),
        stage_windows=[window], executed_plan=[{}], recovery_report={}, skipped_stages=[], run_aborted=False,
        keep_raw_telemetry=False, export_compatibility_json=True, export_extended_json=True,
        segment_parser=SegmentParser(), exporter=CompatibilityExporter(), summary_exporter=SummaryTextBuilder(),
        stage_sensor_events=lambda _: [], stage_faults=lambda _: [], capture_run_end=lambda **_: None)
    expected = worker["slow_operation_evidence"]
    for filename in ("run_manifest.json", "parsed_results_custom.json", "parsed_results_extended.json"):
        found = []
        def inspect(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in ("slow_operation_evidence", "SlowOperationEvidence"):
                        found.append(child)
                    else:
                        inspect(child)
            elif isinstance(value, list):
                for child in value:
                    inspect(child)
        inspect(JsonStore.read(root / filename, {}))
        assert found and all(item == expected for item in found), filename


def run_gpu_slow_operation_checks():
    recorder, clock, state = _recorder()
    # Timing domains and physical identity are explicit, not guessed from clocks.
    for name in sorted(SlowOperationRecorder.OPERATIONS - {"unaccounted_loop_gap"}):
        with recorder.measure(name):
            clock.advance(25)
    evidence = state["slow_operation_evidence"]
    assert len(evidence["records"]) == len(SlowOperationRecorder.OPERATIONS) - 1
    for row in evidence["records"]:
        assert row["ended_monotonic_seconds"] - row["started_monotonic_seconds"] == row["elapsed_seconds"] == 25
        assert row["ended_unix_seconds"] - row["started_unix_seconds"] == 25
        assert row["observed_end_unix_seconds"] == row["ended_unix_seconds"]
        assert 0 < row["process_cpu_seconds"] < 0.01
        assert row["physical_gpu_id"] == "pci:0000:41:00.0" and row["telemetry_gpu_index"] == 0
        assert row["vulkan_device_index"] == 1 and row["worker_result_file"].startswith("worker_results/")
    # Fast normal operations produce no event or event-time output.
    quiet, clock, _ = _recorder()
    with quiet.measure("queue_submit"):
        clock.advance(.002)
    assert quiet.evidence["event_count"] == 0
    # Nested persistence phases must not become false unaccounted gaps.
    quiet.track_gaps = True
    with quiet.measure("result_persistence"):
        with quiet.measure("result_flush"):
            clock.advance(25)
    assert all(x["operation"] != "unaccounted_loop_gap" for x in quiet.evidence["records"])
    clock.advance(30)
    quiet.call("queue_submit", lambda: None)
    gap = quiet.evidence["records"][-1]
    assert gap["operation"] == "unaccounted_loop_gap" and math.isclose(gap["elapsed_seconds"], 30, abs_tol=1e-8)
    assert gap["process_cpu_seconds"] is None
    assert "cause_unknown" in quiet.evidence["gap_semantics"]
    # A delay inside the recorder's bookkeeping must not disappear from gap
    # accounting merely because no Vulkan/file call was active at that point.
    own, own_clock, _ = _recorder()
    own.track_gaps = True
    original_record = own._record
    def delayed_record(*args):
        original_record(*args)
        own_clock.advance(25)
    with patch.object(own, "_record", side_effect=delayed_record):
        own.call("queue_submit", lambda: None)
    own.call("queue_submit", lambda: None)
    assert own.evidence["records"][-1]["operation"] == "unaccounted_loop_gap"
    assert own.evidence["records"][-1]["elapsed_seconds"] == 25
    # Wall-clock steps are visible, not silently absorbed into durations.
    clock.wall += 120
    with quiet.measure("verification_readback"):
        clock.advance(2)
    row = quiet.evidence["records"][-1]
    assert row["elapsed_seconds"] == 2
    assert row["observed_end_unix_seconds"] - row["ended_unix_seconds"] == 120
    # Memory stays bounded on weak devices/long runs; retain the slowest even
    # when its chronological record has rolled out. Aggregates are not additive
    # across nested scopes and must never be presented as GPU-active time.
    bounded, clock, _ = _recorder(capacity=4)
    with bounded.measure("fence_wait"):
        clock.advance(25)
    for _ in range(100):
        with bounded.measure("fence_wait"):
            clock.advance(2)
    assert len(bounded.evidence["records"]) == 4
    assert bounded.evidence["event_count"] == 101 and bounded.evidence["overwritten_record_count"] == 97
    assert bounded.evidence["slowest_by_operation"]["fence_wait"]["elapsed_seconds"] == 25
    assert bounded.evidence["operation_summary"]["fence_wait"]["count"] == 101
    try:
        bounded.begin("unbounded_dynamic_operation_name")
    except ValueError:
        pass
    else:
        raise AssertionError("operation cardinality must be bounded")
    # Exceptions are retained even when fast; bookkeeping never eats them.
    def fail():
        raise OSError("injected persistence failure")
    try:
        bounded.call("result_replace", fail)
    except OSError:
        pass
    else:
        raise AssertionError("error swallowed")
    assert bounded.evidence["records"][-1]["outcome"] == "exception:OSError"
    token = bounded.begin("command_record")
    bounded.fail_pending()
    assert not bounded.pending and bounded.evidence["records"][-1]["operation"] == "command_record"
    # Normal exit's pre-existing fallback write runs BEFORE the terminal log;
    # its own completed timing must not disappear after the log was emitted.
    exiting, exit_clock, _ = _recorder()
    callbacks, output = [], io.StringIO()
    def exit_writer(reason):
        assert reason == "atexit"
        with exiting.measure("result_persistence"):
            exit_clock.advance(25)
    register_worker_exit_diagnostics(exiting, exit_writer, register=callbacks.append, stream=output)
    for callback in reversed(callbacks):
        callback()
    assert json.loads(output.getvalue())["evidence"]["records"][-1]["elapsed_seconds"] == 25

    # Exercise the exact production persistence function; inject latency, not
    # real sleeps. Verify atomic replacement and unchanged durability policy.
    with TemporaryDirectory(prefix="lvs-gpu-stalls-") as temporary:
        path = str(Path(temporary) / "worker.json")
        writer, clock, worker = _recorder(_worker_payload())
        import vulkan_compute_worker as native
        dump = native.json.dump
        replace = native.os.replace
        def slow_dump(*args, **kwargs):
            clock.advance(25)
            return dump(*args, **kwargs)
        def slow_replace(*args):
            clock.advance(3)
            return replace(*args)
        with patch.object(native.json, "dump", side_effect=slow_dump), patch.object(native.os, "replace", side_effect=slow_replace), patch.object(native.os, "fsync") as sync:
            persist_worker_result(path, worker, writer)
            assert sync.call_count == 0, "periodic writes must not gain forced fsync"
            persist_worker_result(path, worker, writer, force=True)
            assert sync.call_count == 1
        assert Path(path).is_file() and not Path(path + ".tmp").exists()
        persisted = json.loads(Path(path).read_text())
        assert worker_result_successful(persisted)
        assert any(r["operation"] == "result_serialization_and_write" and r["elapsed_seconds"] == 25
                   for r in persisted["slow_operation_evidence"]["records"])
        before = Path(path).read_bytes()
        with patch.object(native.os, "replace", side_effect=OSError("injected replace")):
            try:
                persist_worker_result(path, worker, writer)
            except OSError:
                pass
            else:
                raise AssertionError("replacement failure must be observable")
        assert Path(path).read_bytes() == before, "failed replacement corrupted last valid evidence"
        for operation, target, attribute in (("result_serialization_and_write", native.json, "dump"),
                                             ("result_fsync", native.os, "fsync"),
                                             ("result_open", native, "open")):
            with patch.object(target, attribute, side_effect=OSError("injected failure"), create=True):
                try:
                    persist_worker_result(path, worker, writer, force=True)
                except OSError:
                    pass
                else:
                    raise AssertionError(f"{operation} failure was swallowed")
            assert Path(path).read_bytes() == before
            assert writer.evidence["slowest_by_operation"][operation]["operation"] == operation
            assert writer.evidence["operation_summary"][operation]["exception_count"] >= 1
            assert not writer.pending
        # A single terminal record includes the newest failed write itself.
        terminal = io.StringIO()
        writer.emit_terminal(terminal)
        terminal_payload = json.loads(terminal.getvalue())
        assert terminal_payload["event"] == "gpu_worker_slow_operation_diagnostics"
        assert terminal_payload["evidence"]["records"][-1]["operation"] == "result_persistence"
        assert "exception:OSError" == terminal_payload["evidence"]["records"][-1]["outcome"]

    # New evidence survives actual compatibility and parsed worker summaries;
    # missing instrumentation remains unavailable, and does not invent success.
    payload = _worker_payload()
    payload["slow_operation_evidence"] = copy.deepcopy(evidence)
    with TemporaryDirectory(prefix="lvs-gpu-stall-export-") as temporary:
        _artifact_round_trip(payload, Path(temporary))
    def export(worker):
        return build_gpu_worker_validation_detail(stage_name="GPU", stage_type="Combined",
            stage_verdict="pass", payload=worker, backend_name="python_vulkan_compute", device_name="GPU")
    exported = export(payload)
    assert exported["SlowOperationEvidence"] == evidence
    exported["SlowOperationEvidence"]["records"].clear()
    assert payload["slow_operation_evidence"]["records"]
    summary = GpuWorkerStateSummaryBuilder().summary(SimpleNamespace(worker_results=[payload]))
    assert summary["Workers"][0]["SlowOperationEvidence"] == evidence
    legacy = _worker_payload()
    assert export(legacy)["SlowOperationEvidence"] is None
    assert worker_result_successful(legacy)
    for update in (dict(compute_mismatch_count=1, error_count=1, status="error"),
                   dict(final_verification_completed=False)):
        invalid = dict(payload, **update)
        assert not worker_result_successful(invalid), "stall diagnostics must never excuse integrity failure"


if __name__ == "__main__":
    run_gpu_slow_operation_checks()
    print("PASS bounded GPU slow-operation diagnostics and persistence")
