"""Deterministic parent deadlines and recorded-result contracts; no GPU work."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from Modules.lvs_gpu_worker_plan import GpuWorkerSpec
from Modules.lvs_stage_process_control import (StageProcess, stop_stage_processes,
    is_vulkan_compute_worker, vulkan_compute_shutdown_policy,
    VULKAN_COMPUTE_SHUTDOWN_MAX_SECONDS, VULKAN_COMPUTE_FALLBACK_SECONDS)
from Modules.lvs_worker_evidence import apply_worker_entry_context
from Modules.lvs_worker_integrity import worker_result_successful
from Modules.lvs_compat_export_helpers import preserve_legacy_worker_evidence_contract
from Modules.lvs_compat_export_gpu import build_gpu_worker_validation_detail
from Modules.lvs_report_data import compile_report_data
from Modules.lvs_result_report_adapters import result_summary_text
from Modules.lvs_summary_text import SummaryTextBuilder
from Modules.lvs_segment_gpu_worker_summary import GpuWorkerStateSummaryBuilder
from smoke_tests.standalone_report_checks import _build_fixture

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def iso(self):
        return (datetime(2026, 10, 29, tzinfo=timezone.utc) + timedelta(seconds=self.now)).isoformat()


class Process:
    def __init__(self, clock, pid, delay, code=0):
        self.clock, self.pid, self.delay, self.code = clock, pid, delay, code
        self.exit_at = None
        self.returncode = None
        self.waits = []
        self.signals = []
        self.kills = []

    def terminate(self):
        self.signals.append(self.clock.now)
        self.exit_at = None if self.delay is None else self.clock.now + self.delay

    def poll(self):
        if self.returncode is None and self.exit_at is not None and self.clock.now >= self.exit_at:
            self.returncode = self.code
        return self.returncode

    def wait(self, timeout):
        self.waits.append(timeout)
        if self.poll() is not None:
            return self.returncode
        if self.exit_at is not None and self.exit_at <= self.clock.now + timeout:
            self.clock.now = max(self.clock.now, self.exit_at)
            self.returncode = self.code
            return self.returncode
        self.clock.now += timeout
        raise subprocess.TimeoutExpired("fixture", timeout)

    def kill(self):
        self.kills.append(self.clock.now)
        self.returncode = -9


def entry(root, clock, pid=100, role="vram", delay=7.0):
    path = root / f"{pid}.json"
    slot = "0000:00:02.0"
    cmd = [sys.executable, str(ROOT / "native/vulkan_compute_worker.py"), "--result-file", str(path)]
    spec = GpuWorkerSpec(role, "python_vulkan_compute", 1, "card1", slot, slot, cmd,
                         physical_gpu_id="pci:" + slot)
    item = StageProcess(role, cmd, Process(clock, pid, delay), gpu_spec=spec,
                        result_path=str(path), started_monotonic=900.0)
    payload = dict(kind="gpu", mode="gpu_3d", backend="python_vulkan_compute", worker_pid=pid,
        worker_result_file=str(path), target_slot=slot, target_id=slot, physical_gpu_id="pci:" + slot,
        hardware_device_verified=True, physical_identity_evidence={"status": "verified",
            "contract_id": "linux_validation_suite.vulkan_physical_identity", "contract_version": 1},
        last_result_write_started_monotonic_seconds=999.0,
        cycle_count=30, cycle_latency_max_seconds=2.575, cycle_latency_last_seconds=2.4,
        cycle_elapsed_seconds=80.0, status="ok", error_count=0, verification_passes=29,
        initial_verification_completed=True, final_verification_completed=True,
        compute_mismatch_count=0, cleanup_complete=True,
        allocation_claim_cleanup_error="", outstanding_system_memory_claim_bytes=0)
    path.write_text(json.dumps(payload))
    return item, payload


def stop(items, clock):
    stop_stage_processes(items, monotonic=clock.monotonic, now_iso=clock.iso)


def run_vulkan_shutdown_policy_checks():
    with TemporaryDirectory(dir=ROOT) as temporary:
        root = Path(temporary)
        # The actual production initializer and writer supply the identity and
        # publication clock required by the parent, not fixture-only fields.
        import ast
        import time
        import vulkan_compute_worker as worker
        tree = ast.parse((ROOT / "native/vulkan_compute_worker.py").read_text())
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        initializer = next(n.value for n in main.body if isinstance(n, ast.Assign)
                           and any(isinstance(t, ast.Name) and t.id == "state" for t in n.targets))
        fields = {k.value: v for k, v in zip(initializer.keys, initializer.values) if isinstance(k, ast.Constant)}
        pid = eval(compile(ast.Expression(fields["worker_pid"]), "<actual-worker-pid>", "eval"), vars(worker))
        clock = Clock(); clock.now = time.monotonic()
        actual, payload = entry(root, clock, pid=pid)
        actual.started_monotonic = clock.now - 100
        recorder = worker.SlowOperationRecorder(payload)
        payload.update(result_write_count=0, result_write_elapsed_seconds=0., result_write_error_count=0,
                       result_write_interval_target_seconds=1.)
        writer = next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == "write_result")
        wrapper = ast.FunctionDef(name="publish", args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[],
            kw_defaults=[], defaults=[]), decorator_list=[], body=[
            *ast.parse("last_result_write_monotonic = 0.0").body, writer,
            *ast.parse('return write_result("completed", force=True)').body])
        env = dict(vars(worker), state=payload, stalls=recorder,
                   args=SimpleNamespace(result_file=actual.result_path), worker_cpu_started=time.process_time())
        exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])),
                     "<actual-publication>", "exec"), env)
        assert env["publish"]() is True
        assert vulkan_compute_shutdown_policy(actual, time.monotonic())["timing_evidence_status"] == "accepted"

        for role in ("gpu_3d", "vram", "gpu"):
            clock = Clock(); item, payload = entry(root, clock, role=role)
            assert is_vulkan_compute_worker(item)
            stop([item], clock)
            evidence = item.shutdown_evidence
            assert abs(evidence["total_allowance_seconds"] - 10.15) < 1e-8
            assert evidence["reason"] == "observed_cycle_timing"
            assert evidence["termination_requested_monotonic"] == 1000.0
            assert evidence["outcome"] == "normal_exit" and not item.forced_kill
            assert evidence["exit_observed_monotonic"] == 1007.0
            assert abs((datetime.fromisoformat(evidence["deadline_iso"])
                - datetime.fromisoformat(evidence["termination_requested_iso"])).total_seconds() - 10.15) < 1e-8

        clock = Clock(); item, baseline = entry(root, clock)
        cases = [{"worker_pid": 999}, {"backend": "other"}, {"target_id": "other"},
                 {"physical_gpu_id": "pci:0000:01:00.0"}, {"target_slot": "0000:01:00.0"},
                 {"hardware_device_verified": False}, {"physical_identity_evidence": {}},
                 {"physical_identity_evidence": {"status": "verified", "contract_id": "unknown", "contract_version": 1}},
                 {"last_result_write_started_monotonic_seconds": 950.0},
                 {"last_result_write_started_monotonic_seconds": 899.0},
                 {"last_result_write_started_monotonic_seconds": 1001.0},
                 {"cycle_count": 0}, {"cycle_count": True}, {"cycle_elapsed_seconds": 1.0},
                 {"cycle_elapsed_seconds": 200.0}, {"cycle_latency_last_seconds": 3.0},
                 {"worker_result_file": str(root / "wrong.json")}]
        for value in (None, 0, -1, float("nan"), float("inf"), True, "2.5", 10000):
            cases.append({"cycle_latency_max_seconds": value})
        for change in cases:
            Path(item.result_path).write_text(json.dumps({**baseline, **change}))
            evidence = vulkan_compute_shutdown_policy(item, clock.now)
            assert evidence["timing_evidence_status"] == "rejected", change
            assert evidence["total_allowance_seconds"] == VULKAN_COMPUTE_FALLBACK_SECONDS
        for removed in ("worker_pid", "last_result_write_started_monotonic_seconds", "cycle_latency_max_seconds"):
            bad = deepcopy(baseline); bad.pop(removed)
            Path(item.result_path).write_text(json.dumps(bad))
            assert vulkan_compute_shutdown_policy(item, clock.now)["reason"].startswith("fallback_")
        for content in ("{", "[]", "x" * (2 * 1024 * 1024 + 1)):
            Path(item.result_path).write_text(content)
            assert vulkan_compute_shutdown_policy(item, clock.now)["total_allowance_seconds"] == 15.0
        Path(item.result_path).unlink()
        assert vulkan_compute_shutdown_policy(item, clock.now)["total_allowance_seconds"] == 15.0
        Path(item.result_path).symlink_to(root / "absent")
        assert vulkan_compute_shutdown_policy(item, clock.now)["total_allowance_seconds"] == 15.0
        Path(item.result_path).unlink()
        os.mkfifo(item.result_path)
        assert vulkan_compute_shutdown_policy(item, clock.now)["total_allowance_seconds"] == 15.0
        Path(item.result_path).unlink()
        Path(item.result_path).write_text(json.dumps({**baseline, "cycle_latency_max_seconds": 30.0}))
        capped = vulkan_compute_shutdown_policy(item, clock.now)
        assert capped["total_allowance_seconds"] == VULKAN_COMPUTE_SHUTDOWN_MAX_SECONDS == 60.0
        assert capped["reason"] == "capped_observed_cycle_timing"

        # Both workers receive SIGTERM at t=1000; the second gets only the
        # remaining allowance when the first finishes eight seconds later.
        clock = Clock(); first, _ = entry(root, clock, 101, delay=8)
        second, _ = entry(root, clock, 102, delay=9)
        stop([first, second], clock)
        assert first.process.signals == second.process.signals == [1000.0]
        assert abs(second.process.waits[0] - 2.15) < 1e-8
        assert second.shutdown_evidence["deadline_monotonic"] == first.shutdown_evidence["deadline_monotonic"]
        assert not second.shutdown_timed_out
        deadline = second.shutdown_evidence["deadline_monotonic"]
        stop([second], clock)
        assert second.shutdown_evidence["deadline_monotonic"] == deadline
        assert len(second.process.signals) == 1

        # A slow legacy worker cannot postpone killing an expired Vulkan
        # worker. Its own existing thirty-second VM allowance is unchanged.
        clock = Clock(); hung, payload = entry(root, clock, 104, delay=None)
        legacy = StageProcess("memory", ["stress-ng", "--vm", "1"], Process(clock, 105, 25))
        stop([legacy, hung], clock)
        assert abs(hung.process.kills[0] - 1010.15) < 1e-8
        assert hung.shutdown_timed_out and hung.forced_kill and hung.process.returncode == -9
        assert legacy.shutdown_timeout_seconds == 30 and not legacy.forced_kill
        assert clock.now == 1025.0

        # Even failed SIGKILL reaping remains bounded and cannot normalize an
        # earlier completed snapshot into success or invent an exit code.
        clock = Clock(); unreaped, snapshot = entry(root, clock, 109, delay=None)
        unreaped.process.kill = lambda: unreaped.process.kills.append(clock.now)
        stop([unreaped], clock)
        assert abs(clock.now - 1015.15) < 1e-8
        assert unreaped.shutdown_evidence["reap_error"] == "TimeoutExpired"
        normalized = apply_worker_entry_context(snapshot, unreaped, return_code=None)
        assert not worker_result_successful(normalized)
        assert normalized.get("observed_exit_code") is None
        assert normalized["cleanup_complete"] is True  # retained observation, not proof of exit
        waits = len(unreaped.process.waits)
        stop([unreaped], clock)
        assert len(unreaped.process.waits) == waits and abs(clock.now - 1015.15) < 1e-8

        # Missing observations and capped timings remain finite, even hung.
        for missing, cycle, expected in ((True, 2.575, 15.0), (False, 30.0, 60.0)):
            clock = Clock(); stuck, payload = entry(root, clock, 106, delay=None)
            if missing:
                Path(stuck.result_path).unlink()
            else:
                Path(stuck.result_path).write_text(json.dumps({**payload, "cycle_latency_max_seconds": cycle}))
            stop([stuck], clock)
            assert stuck.process.kills == [1000.0 + expected]
            assert stuck.shutdown_evidence["outcome"] == "forced_kill"

        for backend, role, script in (("python_vulkan_transfer", "vram", "vulkan_transfer_worker.py"),
                ("python_opencl", "vram", "other.py"), ("python_vulkan_compute", "external", "vulkan_compute_worker.py")):
            clock = Clock(); other, _ = entry(root, clock, 107, role=role, delay=1)
            other.gpu_spec.backend = backend
            other.command[1] = str(ROOT / "native" / script)
            stop([other], clock)
            assert other.shutdown_evidence is None and other.shutdown_timeout_seconds == 5

        # Real normalization/export/report paths must still reject completed
        # computation with cleanup/publication failures or a forced exit.
        run = root / "run"; run.mkdir(); _build_fixture(run, native="pass")
        manifest = json.loads((run / "run_manifest.json").read_text())
        (run / "run_summary.txt").write_text("Result: Finished\n")
        for failure in (None, "cleanup", "cleanup_zero_exit", "publication", "hang"):
            clock = Clock(); item, payload = entry(root, clock, 108, delay=None if failure == "hang" else 7)
            if failure == "cleanup":
                payload.update(status="error", error_count=1, cleanup_complete=False,
                    allocation_claim_cleanup_error="injected destroy failure", outstanding_system_memory_claim_bytes=4096)
                item.process.code = 13
            if failure == "cleanup_zero_exit":
                payload.update(cleanup_complete=False, allocation_claim_cleanup_error="explicit teardown failure")
            if failure == "publication":
                # The earlier successful snapshot survives, but the actual
                # nonzero process exit must still prevent acceptance.
                item.process.code = 13
            stop([item], clock)
            normalized = apply_worker_entry_context(payload, item, return_code=item.process.returncode)
            good = failure is None
            assert worker_result_successful(normalized) is good
            assert normalized["verification_passes"] == 29
            assert normalized["shutdown_evidence"]["final_worker_result"]["status"] == normalized["status"]
            compat = preserve_legacy_worker_evidence_contract(normalized)
            detail = build_gpu_worker_validation_detail(stage_name="S2", stage_type="GPU", stage_verdict="pass",
                payload=compat, backend_name="python_vulkan_compute", device_name="fixture")
            assert worker_result_successful(detail) is good
            assert detail["ShutdownEvidence"] == normalized["shutdown_evidence"]
            summary = GpuWorkerStateSummaryBuilder().summary(SimpleNamespace(worker_results=[normalized]))
            assert summary["Workers"][0]["ShutdownEvidence"] == normalized["shutdown_evidence"]
            current = deepcopy(manifest); current["stage_windows"][0]["worker_results"] = [normalized]
            (run / "run_manifest.json").write_text(json.dumps(current))
            assert compile_report_data(run)["run"]["report_outcome"] == ("PASS" if good else "FAIL")
            assert ("Result: FAIL" in result_summary_text(run, SummaryTextBuilder())) is (not good)
