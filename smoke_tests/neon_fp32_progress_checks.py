"""Normal native-emulation and artifact regressions; never ARM ISA proof."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import signal
import subprocess
from tempfile import NamedTemporaryFile, TemporaryDirectory
import time
from types import SimpleNamespace

from Modules.lvs_cpu_verified_progress import CONTRACT, analyze_verified_progress
from Modules.lvs_worker_evidence import apply_worker_entry_context
from Modules.lvs_worker_integrity import worker_verification_satisfied
from smoke_tests.neon_fp32_fma_checks import (
    ROOT, _compile, _export_worker_fixture, _worker_export_round_trip,
    _run_worker,
)


def _fixture(path: Path) -> tuple[dict, SimpleNamespace, list[dict]]:
    worker = _export_worker_fixture()
    worker.update(process_pid=73, observed_exit_code=0,
                  verified_progress={"contract": CONTRACT, "path": str(path)})
    rows = []
    for index, timestamp in enumerate([100.0, 100.1, *range(102, 121, 2)]):
        final = timestamp == 120
        state = "startup" if index == 0 else "initial" if index == 1 else "final_complete" if final else "ongoing"
        threads = []
        for thread_index, cpu in enumerate(worker["target_cpu_ids"]):
            count = 0 if index == 0 else 1 if index == 1 else int((timestamp - 100) * (thread_index + 1) * 10)
            threads.append(dict(thread_index=thread_index, cpu_id=cpu,
                published_monotonic_seconds=0 if index == 0 else timestamp,
                verified_blocks=count, initial_verified=index > 0, periodic_verified=index > 1,
                final_verified=final, error_count=0, affinity_applied=index > 0, observed_cpu=cpu))
        rows.append(dict(contract=CONTRACT, sequence=index, pid=73, kernel_flavor="neon_fp32_fma",
            operation_family="fp32_fused_multiply_add", state=state, monotonic_seconds=timestamp,
            realtime_seconds=timestamp + 1700000000, clock_pair_uncertainty_seconds=0.00001,
            snapshot_interval_seconds=2.0, threads=threads,
            aggregate_verified_blocks=sum(t["verified_blocks"] for t in threads)))
    total = 0
    for detail, thread in zip(worker["threads_detail"], rows[-1]["threads"]):
        detail.update(arithmetic_verified_blocks=thread["verified_blocks"], verify_passes=thread["verified_blocks"])
        total += thread["verified_blocks"]
    worker.update(arithmetic_verified_blocks=total, verify_passes=total)
    window = SimpleNamespace(started_monotonic=100, ended_monotonic=120,
        trim_start_seconds=2, trim_end_seconds=2, analysis_minimum_usable_seconds=16,
        analysis_evidence={"quality": "sufficient"})
    return worker, window, rows


def _write(path: Path, rows: list[dict], tail: str = "") -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows) + tail)


def run_neon_fp32_progress_checks() -> None:
    with TemporaryDirectory(prefix="lvs-fp32-progress-") as temporary:
        root = Path(temporary)
        path = root / "progress.jsonl"
        worker, window, rows = _fixture(path)
        assert worker_verification_satisfied(worker)
        _write(path, rows)
        result = analyze_verified_progress(worker, window)
        assert result["quality"] == "sufficient", result
        assert result["aggregate_blocks_per_second"] == 30
        assert [r["verified_block_delta"] for r in result["threads"]] == [160, 320]
        assert [r["observed_seconds"] for r in result["threads"]] == [16, 16]
        assert all(r["coverage_fraction"] == 1 for r in result["threads"])
        assert result["aggregate_interval_rate"]["minimum"] == 30
        assert result["threads"][0]["derived_stress_lane_fma_count"] == 160 * 8192
        # Move trims between snapshots. Boundary work is excluded, never estimated.
        shifted = copy.copy(window)
        shifted.trim_start_seconds = shifted.trim_end_seconds = 3
        shifted.analysis_minimum_usable_seconds = 14
        shifted_result = analyze_verified_progress(worker, shifted)
        assert shifted_result["quality"] == "sufficient", shifted_result
        assert shifted_result["threads"][0]["observed_seconds"] == 12
        assert shifted_result["threads"][0]["verified_block_delta"] == 120
        assert shifted_result["aggregate_blocks_per_second"] == 30
        # A real rate decrease remains descriptive, never a fabricated failure.
        varying = copy.deepcopy(rows)
        varying_worker = copy.deepcopy(worker)
        for row in varying:
            timestamp = row["monotonic_seconds"]
            if timestamp > 110:
                for index, thread in enumerate(row["threads"]):
                    thread["verified_blocks"] = int((100 + (timestamp - 110) * 5) * (index + 1))
                row["aggregate_verified_blocks"] = sum(t["verified_blocks"] for t in row["threads"])
        for detail, thread in zip(varying_worker["threads_detail"], varying[-1]["threads"]):
            detail.update(arithmetic_verified_blocks=thread["verified_blocks"], verify_passes=thread["verified_blocks"])
        varying_worker.update(arithmetic_verified_blocks=varying[-1]["aggregate_verified_blocks"],
                              verify_passes=varying[-1]["aggregate_verified_blocks"])
        _write(path, varying)
        variation = analyze_verified_progress(varying_worker, window)
        assert variation["quality"] == "sufficient", variation
        assert variation["threads"][0]["first_half"]["blocks_per_second"] == 10
        assert variation["threads"][0]["second_half"]["blocks_per_second"] == 5
        # Storage and analysis scale with thread count, not CPU numbering/model.
        for count in (1, 512):
            many_rows = copy.deepcopy(rows)
            many_worker = copy.deepcopy(worker)
            targets = [index * 7 + 2 for index in range(count)]
            for row in many_rows:
                template = row["threads"][0]
                row["threads"] = [dict(template, thread_index=index, cpu_id=cpu, observed_cpu=cpu)
                                  for index, cpu in enumerate(targets)]
                row["aggregate_verified_blocks"] = sum(t["verified_blocks"] for t in row["threads"])
            template = many_worker["threads_detail"][0]
            many_worker.update(target_cpu_ids=targets, threads=count, requested_thread_count=count,
                actual_worker_count=count, affinity_attempted_count=count, affinity_applied_count=count,
                threads_detail=[dict(template, thread_index=index, affinity_target_cpu=cpu, observed_cpu=cpu)
                                for index, cpu in enumerate(targets)],
                arithmetic_verified_blocks=count * 200, verify_passes=count * 200)
            for detail in many_worker["threads_detail"]:
                detail.update(arithmetic_verified_blocks=200, verify_passes=200)
            _write(path, many_rows)
            many = analyze_verified_progress(many_worker, window)
            assert many["quality"] == "sufficient", many["reasons"]
            assert len(many["threads"]) == count and many["aggregate_blocks_per_second"] == count * 10

        _write(path, rows)

        # Real rejection checks: every mutation must degrade quality.
        mutations = [
            lambda r: r[4]["threads"].pop(),
            lambda r: r[4].update(aggregate_verified_blocks=0),
            lambda r: r[4]["threads"][0].update(verified_blocks=-1),
            lambda r: r[4]["threads"][0].update(verified_blocks=1 << 64),
            lambda r: r[4]["threads"][0].update(verified_blocks=0),
            lambda r: r[4]["threads"][0].update(initial_verified=False),
            lambda r: r[4]["threads"][0].update(initial_verified="false"),
            lambda r: r[4]["threads"][0].update(affinity_applied=False),
            lambda r: r[4]["threads"][0].update(cpu_id=999),
            lambda r: r[4].update(monotonic_seconds=r[3]["monotonic_seconds"]),
            lambda r: r[4].update(monotonic_seconds=float("nan")),
            lambda r: r[4].update(pid=74),
            lambda r: r[4].update(sequence=1000),
            lambda r: r[4].update(state="unknown"),
            lambda r: r[4]["threads"][0].update(error_count=1),
            lambda r: r[-1]["threads"][0].update(final_verified=False),
            lambda r: r[-1]["threads"][0].update(periodic_verified=False),
            lambda r: r[-1]["threads"][0].update(verified_blocks=999),
            lambda r: r[1].update(state="ongoing"),
            lambda r: r.__delitem__(slice(3, 8)),
            lambda r: r.pop(),
            lambda r: r.pop(0),
        ]
        for mutate in mutations:
            broken = copy.deepcopy(rows)
            mutate(broken)
            _write(path, broken)
            rejected = analyze_verified_progress(worker, window)
            assert rejected["quality"] != "sufficient", (mutate, rejected)
        # Internally consistent zero deltas identify a stalled thread, not a pass.
        stalled = copy.deepcopy(rows)
        for row in stalled[4:7]:
            row["threads"][0].update(verified_blocks=rows[3]["threads"][0]["verified_blocks"],
                                     published_monotonic_seconds=row["monotonic_seconds"])
            row["aggregate_verified_blocks"] = sum(t["verified_blocks"] for t in row["threads"])
        _write(path, stalled)
        assert any("stalled" in reason for reason in analyze_verified_progress(worker, window)["reasons"])
        stale = copy.deepcopy(rows)
        for row in stale[3:9]:
            row["threads"][0] = copy.deepcopy(stale[2]["threads"][0])
            row["aggregate_verified_blocks"] = sum(t["verified_blocks"] for t in row["threads"])
        _write(path, stale)
        assert any("stale" in reason for reason in analyze_verified_progress(worker, window)["reasons"])
        for tail in ('{"sequence":', '{"sequence":1}\n', 'not json\n'):
            _write(path, rows[:-1], tail)
            assert analyze_verified_progress(worker, window)["quality"] == "insufficient"
        _write(path, rows)
        for code in (None, -9, -11, 4):
            broken = copy.deepcopy(worker)
            broken["observed_exit_code"] = code
            assert analyze_verified_progress(broken, window)["quality"] == "insufficient"
        broken = copy.deepcopy(worker)
        broken["verified_progress"]["persistence_error"] = True
        assert analyze_verified_progress(broken, window)["quality"] == "insufficient"
        broken = copy.deepcopy(worker)
        broken["verified_progress"]["snapshot_count"] = 999
        assert analyze_verified_progress(broken, window)["quality"] == "insufficient"
        early = copy.copy(window)
        early.ended_monotonic = 105
        assert analyze_verified_progress(worker, early)["quality"] == "insufficient"
        early.ended_monotonic = 101
        assert analyze_verified_progress(worker, early)["quality"] == "invalid"
        legacy = copy.deepcopy(worker)
        legacy.pop("verified_progress")
        assert analyze_verified_progress(legacy, window)["quality"] == "not_assessed"
        missing = copy.deepcopy(worker)
        missing["verified_progress"]["path"] = str(root / "absent")
        assert analyze_verified_progress(missing, window)["quality"] == "insufficient"

        # Production artifact writer -> manifest -> parser -> compatibility -> report.
        run = root / "roundtrip"
        run.mkdir()
        custom = _worker_export_round_trip(worker, run)
        evidence = custom["Segments"][0]["WorkerResults"][0]
        assert evidence["verified_progress"]["path"] == str(path)
        assert evidence["verified_progress_analysis"]["contract"] == CONTRACT
        from Modules.lvs_report_data import compile_report_data
        from Modules.lvs_report_html import render_report_html
        report = compile_report_data(run)
        assert report["stages"][0]["cpu_verified_progress"]
        assert "Verified CPU work evidence" in render_report_html(report)
        assert "Not a CPU saturation verdict" in render_report_html(report)

        # Exercise the actual publisher, writer, and shutdown on this host using
        # the existing integer-emulation build, explicitly NOT physical NEON.
        binary = root / "emulated"
        _compile(binary, ROOT / "native/cpu_stress_helper.c", "-DLVS_CPU_HELPER_TEST_FP32_FMA")
        cpus = sorted(os.sched_getaffinity(0))[:2]
        output = root / "native.json"
        def launch(result_path: Path) -> subprocess.Popen:
            return subprocess.Popen([str(binary), "--kernel-flavor", "neon_fp32_fma", "--threads", str(len(cpus)),
                "--cpu-ids", ",".join(map(str, cpus)), "--result-file", str(result_path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        process = launch(output)
        try:
            time.sleep(2.7)
            sidecar = Path(str(output) + ".progress.jsonl")
            assert sidecar.is_file() and not output.exists(), "progress must exist before final results"
            live = [json.loads(line) for line in sidecar.read_text().splitlines()]
            assert live[0]["state"] == "startup"
            assert any(row["state"] == "initial" for row in live)
            assert any(row["state"] == "ongoing" for row in live)
            process.send_signal(signal.SIGTERM)
            _, stderr = process.communicate(timeout=8)
            assert process.returncode == 0, stderr
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        native = json.loads(output.read_text())
        assert worker_verification_satisfied(native)
        assert native["execution_implementation"] == "test_integer_emulation"
        snapshots = [json.loads(line) for line in sidecar.read_text().splitlines()]
        assert snapshots[-2]["state"] == "interrupted" and snapshots[-1]["state"] == "final_complete"
        assert native["verified_progress"]["snapshot_count"] == len(snapshots)
        assert native["verified_progress"]["snapshot_write_seconds"] >= 0
        for row in snapshots:
            assert row["aggregate_verified_blocks"] == sum(t["verified_blocks"] for t in row["threads"])
            assert all(t["initial_verified"] for t in row["threads"] if t["verified_blocks"])
        assert snapshots[-1]["aggregate_verified_blocks"] == native["arithmetic_verified_blocks"]
        # Consume an actual native-generated stream using its measured boot clock.
        native["result_path"] = str(output)
        native["observed_exit_code"] = 0
        native["process_pid"] = process.pid
        measured_window = SimpleNamespace(started_monotonic=snapshots[0]["monotonic_seconds"],
            ended_monotonic=snapshots[-1]["monotonic_seconds"], trim_start_seconds=0,
            trim_end_seconds=0, analysis_minimum_usable_seconds=None,
            analysis_evidence={"quality": "sufficient"})
        measured = analyze_verified_progress(native, measured_window)
        assert measured["quality"] == "sufficient", measured
        assert measured["aggregate_blocks_per_second"] > 0
        # Forced death retains partial records but no successful final result.
        crashed_output = root / "killed.json"
        process = launch(crashed_output)
        try:
            time.sleep(0.4)
            process.kill()
            process.communicate(timeout=5)
            assert process.returncode == -signal.SIGKILL and not crashed_output.exists()
            entry = SimpleNamespace(command=[str(binary), "--kernel-flavor", "neon_fp32_fma",
                "--cpu-ids", ",".join(map(str, cpus))],
                result_path=str(crashed_output), kind="cpu", process=process)
            crashed = apply_worker_entry_context({}, entry, return_code=process.returncode)
            assert not worker_verification_satisfied(crashed)
            partial = analyze_verified_progress(crashed, measured_window)
            assert partial["quality"] != "sufficient" and partial["snapshots"] >= 1
            assert len(partial["threads"]) == len(cpus)
            assert not partial["final_snapshot_complete"]
            assert Path(crashed["verified_progress"]["path"]).is_file()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

        interrupted_binary = root / "interrupted_block"
        _compile(interrupted_binary, ROOT / "native/cpu_stress_helper.c",
                 "-DLVS_CPU_HELPER_TEST_FP32_FMA", "-DLVS_CPU_HELPER_TEST_INTERRUPT_FP32_BLOCK")
        interrupted = _run_worker(interrupted_binary, root, cpus[:1])
        assert interrupted["arithmetic_verified_blocks"] == interrupted["verify_passes"] == 3
        assert interrupted["threads_detail"][0]["interrupted_arithmetic_blocks"] == 1
        interrupted_path = next(root.glob("interrupted_block-*-result.json.progress.jsonl"))
        interrupted_rows = [json.loads(line) for line in interrupted_path.read_text().splitlines()]
        assert interrupted_rows[-1]["aggregate_verified_blocks"] == 3, "partial block must not count"
        assert worker_verification_satisfied(interrupted)

        corrupt_binary = root / "corrupt"
        _compile(corrupt_binary, ROOT / "native/cpu_stress_helper.c",
                 "-DLVS_CPU_HELPER_TEST_FP32_FMA", "-DLVS_CPU_HELPER_TEST_CORRUPT_FP32_LANE")
        corrupt = _run_worker(corrupt_binary, root, cpus[:1], expect_failure=True)
        assert corrupt["arithmetic_verified_blocks"] == 0
        corrupt_path = next(root.glob("corrupt-*-result.json.progress.jsonl"))
        corrupt_rows = [json.loads(line) for line in corrupt_path.read_text().splitlines()]
        assert corrupt_rows[-1]["state"] == "failed"
        assert corrupt_rows[-1]["aggregate_verified_blocks"] == 0
        assert corrupt_rows[-1]["threads"][0]["first_error_kind"] == "fp32_fma_mismatch"

        # Temporary tuning probes must not leak the new stage sidecar format.
        from Modules.lvs_cpu_execution import benchmark_cpu_kernel_candidate
        for command_available in (True, False):
            captured = []
            def probe_command(flavor, result_path):
                captured.append(result_path)
                Path(result_path).write_text(json.dumps(_export_worker_fixture()))
                Path(result_path + ".progress.jsonl").write_text("temporary probe evidence\n")
                return ["fixture"] if command_available else None
            benchmark_cpu_kernel_candidate(kernel_flavor="neon_fp32_fma", build_command=probe_command,
                command_env={}, telemetry_collector_factory=lambda **_: SimpleNamespace(samples=[]),
                popen_factory=lambda *_, **__: SimpleNamespace(returncode=0, poll=lambda: 0),
                stop_processes=lambda _: None,
                temp_file_factory=lambda **kwargs: NamedTemporaryFile(dir=root, **kwargs),
                interval_seconds=0.5, warmup_seconds=0, measure_seconds=0, runtime_environment={},
                privileged_helper_enabled=False, stdout_target=None, stderr_target=None)
            assert captured and not Path(captured[0] + ".progress.jsonl").exists()

    # Normal profile loader/validator and platform-independent dry-run planning.
    from Modules.lvs_profile_loader import ProfileLoader
    from Modules.lvs_profile_validation import ProfileValidator
    from Modules.lvs_analysis_quality import planned_analysis_evidence
    loader = ProfileLoader(ROOT / "profiles")
    archive = ROOT / "profiles/Archived/2026 Hardware Validation/07 ARM64 NEON FP32 FMA Acceptance"
    profile_path = archive / "ARM64 NEON FP32 FMA Sustained Effectiveness.json"
    active_profiles = set(loader.list_profiles())
    for name in ("ARM64 NEON FP32 FMA Functional Confirmation.json",
                 "ARM64 NEON FP32 FMA Sustained Effectiveness.json"):
        assert not (ROOT / "profiles" / name).exists()
        assert list((ROOT / "profiles").rglob(name)) == [archive / name]
        assert archive / name not in active_profiles
    profile = loader.load_profile(profile_path)
    labels = loader.load_segment_labels(profile_path, profile)
    assert not ProfileValidator().validate(profile, labels)["errors"]
    assert len(profile.stages) == 1
    stage = profile.stages[0]
    cpu = stage.modules.cpu
    assert stage.duration_seconds == 600 and cpu.instruction_set == "neon_fp32_fma"
    assert cpu.backend_preference == "native" and not cpu.power_auto and cpu.threads == "all"
    assert not any(getattr(stage.modules, name).enabled for name in
                   ("memory", "gpu_3d", "vram", "storage_benchmark"))
    planned = planned_analysis_evidence(stage, profile.defaults.telemetry_interval_seconds)
    assert planned["intent"] == "sustained" and planned["quality"] == "sufficient"
    assert planned["minimum_usable_seconds"] == planned["expected_usable_seconds"] == 480
    assert profile.defaults.telemetry_interval_seconds == 2
    from Modules.lvs_workload_cpu_memory import WorkloadCpuMemoryMixin
    class SupportedArmPlan(WorkloadCpuMemoryMixin):
        def _cpu_machine(self):
            return "arm64"
        def _cpu_target_plan(self, cpu):
            return {"target_cpu_ids": [2, 19], "requested_thread_count": 2, "actual_worker_count": 2}
        def _cpu_helper_status(self):
            return {"available": True, "path": "/fixture/build/cpu_stress_helper_arm64"}
        def _cpu_helper_supported_kernel_flavors(self, cpu_id=None):
            return ["scalar", "neon", "neon_fp32_fma"]
        def _python_runtime(self):
            return ""
        def _cpu_resolved_mode(self, cpu, backend_override=""):
            return "neon"
    runner = SupportedArmPlan()
    command = runner._cpu_command(cpu, result_file="stage_cpu.json")
    assert command[0] == "/fixture/build/cpu_stress_helper_arm64"
    assert command[command.index("--kernel-flavor") + 1] == "neon_fp32_fma"
    assert command[command.index("--cpu-ids") + 1] == "2,19"
    assert command[command.index("--threads") + 1] == "2"
    with TemporaryDirectory(prefix="lvs-fp32-sustained-profile-") as directory:
        saved = Path(directory) / "profile.json"
        loader.save_profile(saved, profile)
        restored = loader.load_profile(saved)
        assert restored.stages[0].analysis.minimum_usable_seconds == 480
        assert restored.stages[0].modules.cpu.instruction_set == "neon_fp32_fma"


if __name__ == "__main__":
    run_neon_fp32_progress_checks()
    print("PASS timestamped verified progress, rejection, persistence, and reporting checks")
