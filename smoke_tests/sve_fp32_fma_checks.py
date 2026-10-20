"""SVE reference/contract/lifecycle tests; integer emulation is NOT SVE execution."""
from __future__ import annotations

import copy
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from Modules.lvs_cpu_architecture import (
    cpu_instruction_set_policy, python_cpu_fallback_policy, resolve_cpu_instruction_intent,
    cpu_native_power_probe_kernel_order,
)
from Modules.lvs_profile_models import ModuleCpu
from Modules.lvs_workload_cpu_memory import WorkloadCpuMemoryMixin
from Modules.lvs_cpu_execution import (
    normalize_cpu_helper_mode, build_cpu_benchmark_result, parse_cpu_capability_probe,
    resolve_cpu_execution_policy, cpu_candidate_kernel_flavors,
)
from Modules.lvs_cpu_power_selection import power_cpu_fallback_order, power_cpu_candidate_inventory
from Modules.lvs_cpu_targeting import select_common_kernel
from Modules.lvs_cpu_verified_progress import analyze_verified_progress
from Modules.lvs_native_helpers import resolve_native_helper_status, native_helper_binary_ready
from Modules.lvs_worker_evidence import apply_worker_entry_context
from Modules.lvs_worker_integrity import worker_verification_satisfied
from smoke_tests.neon_fp32_fma_checks import ROOT, _compile, _oracle, _export_worker_fixture, _worker_export_round_trip
from smoke_tests.neon_fp32_progress_checks import _fixture, _write

KERNEL = "sve_fp32_fma"


def _sve_fixture() -> dict:
    worker = _export_worker_fixture()
    worker.update(kernel_flavor=KERNEL, mode="sve", verification_contract=KERNEL + "_v1",
        actual_isa="sve", accumulator_chains=8, fma_rounds_per_block=256,
        execution_implementation="aarch64_sve_intrinsics", isa_hwcap=(1 << 22) | 3,
        isa_capability_source="linux_getauxval_at_hwcap_common_set",
        vector_length_source="linux_prctl_pr_sve_get_vl_per_thread",
        predicate_verification="four_active_witnesses_merge_and_guarded_masked_store")
    worker.pop("lanes_per_block", None)
    for index, thread in enumerate(worker["threads_detail"]):
        vl = 16 if index == 0 else 48
        thread.update(vector_length_bytes=vl, active_fp32_lanes=vl // 4,
            vector_length_flags=0, vector_length_errno=0, fpcr=0,
            lanes_per_block=vl * 2, stress_lane_fmas_per_block=vl * 2 * 256,
            witness_lane_fmas_per_block=4)
    return worker


def _run(binary: Path, root: Path, cpus: list[int], *, vl: int = 16, fail: bool = False) -> dict:
    path = root / (str(time.monotonic_ns()) + ".json")
    env = dict(os.environ, LVS_TEST_SVE_VL_BYTES=str(vl))
    process = subprocess.Popen([str(binary), "--kernel-flavor", KERNEL, "--threads", str(len(cpus)),
        "--cpu-ids", ",".join(map(str, cpus)), "--result-file", str(path)], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        if not fail:
            deadline = time.monotonic() + 10
            sidecar = Path(str(path) + ".progress.jsonl")
            while time.monotonic() < deadline and process.poll() is None:
                if sidecar.exists() and '"state":"initial"' in sidecar.read_text():
                    time.sleep(0.25)
                    break
                time.sleep(0.02)
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
        out, err = process.communicate(timeout=15)
        assert process.returncode == (4 if fail else 0), (process.returncode, out, err)
        worker = json.loads(path.read_text())
        worker.update(observed_exit_code=process.returncode, process_pid=process.pid, result_path=str(path))
        assert worker_verification_satisfied(worker) is not fail, worker
        return worker
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


def run_sve_fp32_fma_checks() -> None:
    cpus = sorted(os.sched_getaffinity(0))[:2]
    source = ROOT / "native/cpu_stress_helper.c"
    with TemporaryDirectory(prefix="lvs-sve-") as temporary:
        root = Path(temporary)
        library_path = root / "reference.so"
        _compile(library_path, ROOT / "smoke_tests/native_fp32_fma_reference_check.c",
                 "-shared", "-fPIC", "-DLVS_CPU_HELPER_TEST_SVE")
        library = ctypes.CDLL(str(library_path))
        library.sve_reference_case.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_int,
                                                ctypes.POINTER(ctypes.c_uint32)]
        # Independent Fraction oracle, including lanes beyond the NEON domain.
        for lanes in (4, 8, 12, 64):
            output = (ctypes.c_uint32 * (lanes * 8))()
            assert library.sve_reference_case(3, 2, lanes, output) == 1
            for lane in range(lanes * 8):
                mix = (3 * 1664525 + lane * 1013904223 + 2 * 69069) & 0xffffffff
                value = 0x3f000000 | (mix & 0x3fffff)
                a = 0x3f7f0000 | ((mix >> 5) & 0xffff)
                b = 0x3a800000 | ((mix >> 9) & 0x3fffff) | (0x80000000 if lane & 1 else 0)
                for _ in range(256):
                    value = _oracle(value, a, b)
                assert output[lane] == value
                assert library.scalable_lane_check(lanes, lane) == lane

        baseline = root / "baseline"
        _compile(baseline, source)
        if os.uname().machine not in {"aarch64", "arm64"}:
            for args in (["--mode", "sve"], ["--kernel-flavor", KERNEL]):
                assert subprocess.run([str(baseline), *args, "--print-kernel-flavor"], capture_output=True).returncode == 3
        probe = subprocess.run([str(baseline), "--print-isa-capabilities"], capture_output=True, text=True, check=True)
        assert "hwcap2" in json.loads(probe.stdout)

        emulated = root / "emulated"
        _compile(emulated, source, "-DLVS_CPU_HELPER_TEST_SVE")
        probe = subprocess.run([str(emulated), "--print-supported-kernels"], capture_output=True, text=True, check=True)
        assert KERNEL in parse_cpu_capability_probe(0, probe.stdout)
        for vl in (16, 32, 48, 256):
            valid = _run(emulated, root, cpus[:1], vl=vl)
            assert valid["execution_implementation"] == "test_integer_emulation"
            assert valid["actual_isa"] == "test_integer_emulation"
            thread = valid["threads_detail"][0]
            assert thread["active_fp32_lanes"] == vl // 4
            assert thread["stress_lane_fmas_per_block"] == vl * 2 * 256
            assert thread["arithmetic_verified_blocks"] >= 3
            rows = [json.loads(line) for line in Path(str(valid["result_path"]) + ".progress.jsonl").read_text().splitlines()]
            assert rows[0]["state"] == "startup" and rows[-1]["state"] == "final_complete"
            assert rows[-1]["aggregate_verified_blocks"] == valid["arithmetic_verified_blocks"]
            assert rows[-1]["threads"][0]["vector_length_bytes"] == vl
            assert build_cpu_benchmark_result(kernel_flavor=KERNEL, samples=[1.0], result_payload=valid, return_code=0)["valid"]
        for vl in (-1, 0, 15, 17, 272):
            invalid = _run(emulated, root, cpus[:1], vl=vl, fail=True)
            assert invalid["threads_detail"][0]["first_error"]["kind"] in {"sve_vl_query", "sve_vl_invalid"}
        for macro in ("CORRUPT_FP32_LANE", "NONFINITE_FP32_LANE", "UNFUSED_FP32", "BAD_SVE_MASK",
                      "BAD_SVE_MERGE", "BAD_FPCR", "MIGRATION"):
            binary = root / macro
            _compile(binary, source, "-DLVS_CPU_HELPER_TEST_SVE", "-DLVS_CPU_HELPER_TEST_" + macro)
            invalid = _run(binary, root, cpus[:1], vl=48, fail=True)
            assert invalid["error_count"] > 0 and not invalid["verification_complete"]
            assert not build_cpu_benchmark_result(kernel_flavor=KERNEL, samples=[1000], result_payload=invalid, return_code=0)["valid"]
        for missing in ("FP", "SVE"):
            binary = root / missing
            _compile(binary, source, "-DLVS_CPU_HELPER_TEST_SVE", "-DLVS_CPU_HELPER_TEST_DISABLE_" + missing)
            assert subprocess.run([str(binary), "--kernel-flavor", KERNEL, "--print-kernel-flavor"], capture_output=True).returncode == 3
        interrupted = root / "interrupted"
        _compile(interrupted, source, "-DLVS_CPU_HELPER_TEST_SVE", "-DLVS_CPU_HELPER_TEST_INTERRUPT_FP32_BLOCK")
        evidence = _run(interrupted, root, cpus[:1])
        assert evidence["threads_detail"][0]["interrupted_arithmetic_blocks"] == 1
        assert evidence["arithmetic_verified_blocks"] == 3, "interrupted block must never count as verified work"
        _run(emulated, root, [max(os.sched_getaffinity(0)) + 10000], fail=True)
        if len(cpus) > 1:
            differing = root / "differing"
            _compile(differing, source, "-DLVS_CPU_HELPER_TEST_SVE", "-DLVS_CPU_HELPER_TEST_SVE_DIFFERING_VL")
            valid = _run(differing, root, cpus)
            assert [t["vector_length_bytes"] for t in valid["threads_detail"]] == [32, 48]
            partial = root / "partial"
            _compile(partial, source, "-DLVS_CPU_HELPER_TEST_SVE", "-DLVS_CPU_HELPER_TEST_THREAD_START_FAILURE")
            invalid = _run(partial, root, cpus, fail=True)
            assert invalid["actual_worker_count"] == 1 and invalid["requested_thread_count"] == 2

        # Missing optional compiler support must not disable baseline compilation.
        source_copy = root / "cpu_stress_helper.c"
        source_copy.write_text("fixture")
        output = root / "cpu_stress_helper_arm64"
        calls = []
        def compile_fixture(command: list[str]) -> SimpleNamespace:
            calls.append(command)
            if "-DLVS_CPU_HELPER_ENABLE_SVE" in command:
                return SimpleNamespace(returncode=1, stderr="unsupported target extension", stdout="")
            output.write_text("fixture")
            output.chmod(0o700)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        status = resolve_native_helper_status(source=source_copy, binary=output, compiler="gcc",
            reason_label="CPU", build_runner=compile_fixture)
        assert status["available"] and status["sve_build"]["status"] == "unavailable"
        assert len(calls) == 2 and "-march" not in " ".join(calls[0])
        header = source_copy.with_name("cpu_sve_kernel.h")
        header.write_text("changed optional region")
        os.utime(header, (output.stat().st_mtime + 1, output.stat().st_mtime + 1))
        assert not native_helper_binary_ready(source_copy, output)

    assert normalize_cpu_helper_mode(KERNEL) == "sve"
    assert normalize_cpu_helper_mode("sve") == "sve"
    for request in (KERNEL, "sve"):
        assert cpu_instruction_set_policy("arm64", request)["allowed"]
        assert not cpu_instruction_set_policy("x86_64", request)["allowed"]
        assert not python_cpu_fallback_policy("arm64", request)["allowed"]
        assert select_common_kernel(architecture="arm64", requested_mode=request, common_flavors=["neon", "scalar"]) == ""
        assert select_common_kernel(architecture="arm64", requested_mode=request, common_flavors=[KERNEL]) == KERNEL
    common = ["scalar", "neon", "neon_fp32_fma", KERNEL]
    assert resolve_cpu_instruction_intent("arm64", "baseline_vector", common)["resolved_kernel_flavor"] == "neon"
    assert resolve_cpu_instruction_intent("arm64", "high_throughput_vector", common)["resolved_kernel_flavor"] == "neon_fp32_fma"
    assert resolve_cpu_instruction_intent("arm64", "highest_verified_vector", common)["resolved_kernel_flavor"] == "neon_fp32_fma"
    assert not resolve_cpu_instruction_intent("arm64", "highest_verified_vector", [KERNEL])["resolved_kernel_flavor"]
    for policy in ("max_power", "capabilities", "family_locked"):
        implicit = cpu_candidate_kernel_flavors(helper_available=True, policy=policy, resolved_mode="neon",
            supports_kernel_flavor=lambda flavor: flavor in common, architecture="arm64")
        assert KERNEL not in implicit and "neon" in implicit
    assert cpu_candidate_kernel_flavors(helper_available=True, policy="family_locked", resolved_mode="sve",
        supports_kernel_flavor=lambda flavor: flavor in common, architecture="arm64") == [KERNEL]
    viable, unavailable = power_cpu_candidate_inventory(architecture="arm64", availability={"cpu_native_helper": True},
        native_kernel_flavors=common, selected_native_kernel=KERNEL)
    assert all(candidate["kernel_flavor"] != KERNEL for candidate in viable)
    assert any(candidate["candidate_id"] == "cpu_native_helper:" + KERNEL and "experimental" in candidate["reason"] for candidate in unavailable)
    assert select_common_kernel(architecture="arm64", requested_mode="auto", common_flavors=common) == "neon"
    candidates = [dict(candidate_id=k, backend="cpu_native_helper", kernel_flavor=k) for k in common]
    order = power_cpu_fallback_order("arm64", candidates)
    assert order[-1]["kernel_flavor"] == KERNEL
    assert cpu_native_power_probe_kernel_order("aarch64") == ("neon", "scalar", "neon_fp32_fma")
    class Runner(WorkloadCpuMemoryMixin):
        def _cpu_machine(self):
            return "arm64"
        def _cpu_target_plan(self, cpu):
            return {"target_cpu_ids": [2, 19], "requested_thread_count": 2, "actual_worker_count": 2}
        def _cpu_helper_supported_kernel_flavors(self, cpu_id=None):
            return common
        def _cpu_helper_status(self):
            return {"available": True}
    plan = Runner()._cpu_capability_plan(ModuleCpu(enabled=True, instruction_set=KERNEL))
    assert plan["selected_kernel_flavor"] == KERNEL and plan["target_cpu_ids"] == [2, 19]
    assert plan["capability_scope"] == "linux_aarch64_hwcap_common_set"
    cache = {}
    for _ in range(2):
        execution = resolve_cpu_execution_policy(backend="cpu_native_helper", requested_mode="sve",
            resolved_mode="sve", kernel_flavor=KERNEL, tuning_policy="family_locked",
            candidate_kernel_flavors=[KERNEL], tune_max_power=True, worker_count=lambda: (2, 19),
            power_tuning_available=lambda: True, benchmark_candidate=lambda _: {}, tuning_cache=cache)
        assert execution["kernel_flavor"] == KERNEL and cache == {}
    missing = {}
    apply_worker_entry_context(missing, SimpleNamespace(command=["helper", "--kernel-flavor", KERNEL]))
    assert missing["verification_contract"] == KERNEL + "_v1" and not worker_verification_satisfied(missing)


def run_fp32_error_evidence_checks() -> None:
    """Mutate real v1 records; reject before AND after the full artifact path."""
    cases = 0
    with TemporaryDirectory(prefix="lvs-fp32-errors-") as temporary:
        root = Path(temporary)
        for fixture in (_sve_fixture, _export_worker_fixture):
            valid = fixture()
            assert worker_verification_satisfied(valid)
            mutations = []
            # Every required thread, not only the first, must provide evidence.
            for location in (-1, 0, 1):
                def target(p: dict, location: int = location) -> dict:
                    return p if location == -1 else p["threads_detail"][location]
                mutations.append(lambda p, target=target: target(p).pop("error_count"))
                for value in (None, False, True, "0", "invalid", -1, 0.0, 0.5, 1, {}, [], 1 << 64):
                    mutations.append(lambda p, target=target, value=value: target(p).update(error_count=value))
                for error in (
                    {"first_error": {"kind": "fp32_fma_mismatch", "expected": 1, "actual": 2}},
                    {"first_error": {"kind": "sve_masked_store"}},
                    {"first_error": "fp32_fma_mismatch"},
                    {"first_error": False},
                    {"first_error_recorded": True},
                    {"first_error_kind": "fp32_fma_mismatch"},
                    {"first_error_lane": 0}, {"first_error_lane": 12},
                    {"first_error_expected": 1}, {"first_error_actual": 1},
                    {"first_error_iteration": 1}, {"fp32_fma_mismatch": True},
                    {"compute_mismatch_count": 1}, {"verification_failures": 1},
                    {"nonfinite_count": 1}, {"errors": ["arithmetic mismatch"]},
                    {"error": "affinity failure"}, {"status": "failed"},
                    {"verification_evidence": {"details": {"first_error": {"kind": "fp32_fma_mismatch"}}}},
                    {"verification_evidence": {"final_verification_completed": False}},
                    {"verification_complete": False},
                    {"verification_evidence": {"kernel_flavor": "scalar"}},
                    {"verification_evidence": {"verification_contract": "other_v1"}},
                ):
                    mutations.append(lambda p, target=target, error=error: target(p).update(copy.deepcopy(error)))
                for phase in ("initial", "periodic", "final"):
                    key = phase + "_verification_completed"
                    mutations.append(lambda p, target=target, key=key: target(p).pop(key))
                    for value in (False, None, 1, "true"):
                        mutations.append(lambda p, target=target, key=key, value=value: target(p).update({key: value}))
            mutations.extend((
                lambda p: p.update(arithmetic_verified_blocks=11),
                lambda p: p["threads_detail"][1].update(arithmetic_verified_blocks=8),
                lambda p: p["threads_detail"][1].update(verify_passes=8),
                lambda p: p["threads_detail"][1].update(affinity_applied=False),
                lambda p: p["threads_detail"].pop(),
                lambda p: p.update(kernel_flavor="scalar"),
                lambda p: p.update(verification_contract="other_v1"),
                lambda p: p.update(requested_kernel_flavor="scalar"),
                lambda p: p.pop("kernel_flavor"),
                lambda p: p.pop("verification_contract"),
                lambda p: p.update(verification_version=True),
                lambda p: p.update(verification_passes=11),
                lambda p: p.update(VerificationPasses=11),
            ))
            records = [valid]
            for mutate in mutations:
                invalid = copy.deepcopy(valid)
                mutate(invalid)
                assert not worker_verification_satisfied(invalid), invalid
                records.append(invalid)
            # Empty sentinels emitted by native results/progress are not errors.
            for empty in (
                {"first_error": None}, {"first_error": {}},
                {"first_error_recorded": False, "first_error_kind": "", "first_error_lane": -1},
                {"first_error_kind": "", "first_error_lane": 0, "first_error_expected": 0,
                 "first_error_actual": 0, "first_error_iteration": 0},
                {"isa_hwcap2": None, "isa_hwcap2_errno": 2},
                {"verified_progress": {"persistence_error": True}},
            ):
                allowed = copy.deepcopy(valid)
                allowed.update(copy.deepcopy(empty))
                allowed["threads_detail"][0].update(copy.deepcopy(empty))
                assert worker_verification_satisfied(allowed), allowed
                records.append(allowed)
            for record in records:
                directory = root / str(cases)
                directory.mkdir()
                try:
                    # Unrecognized historical NEON contracts retain their
                    # frozen projection, but must STILL reject after export.
                    legacy_projection = (fixture is _export_worker_fixture
                        and record.get("verification_contract") != "neon_fp32_fma_v1")
                    _worker_export_round_trip(record, directory, legacy_projection=legacy_projection)
                except AssertionError as exc:
                    raise AssertionError(f"round-trip case {cases}: {record!r}") from exc
                cases += 1
            # JSON forbids these counters; the checker also rejects them directly.
            for value in (float("nan"), float("inf")):
                assert not worker_verification_satisfied(dict(valid, error_count=value))
        # Unversioned historical worker interpretation is deliberately unchanged.
        for kernel in ("scalar", "neon", "sse", "avx2"):
            historical = dict(kind="cpu", kernel_flavor=kernel, status="ok",
                              verification_required=True, verify_passes=1)
            assert worker_verification_satisfied(historical)
    print(f"PASS FP32 error evidence: {cases} complete artifact round trips (SVE and NEON v1)")


def run_sve_functional_profile_checks() -> None:
    from dataclasses import asdict
    from Modules.lvs_profile_loader import ProfileLoader
    from Modules.lvs_profile_validation import ProfileValidator
    from Modules.lvs_workload_runner import WorkloadRunner

    loader = ProfileLoader(ROOT / "profiles")
    path = ROOT / "profiles/ARM64 SVE FP32 FMA Functional Confirmation.json"
    profile = loader.load_profile(path)
    validator = ProfileValidator()
    labels = loader.load_segment_labels(path, profile)
    assert validator.validate(profile, labels) == {"errors": [], "warnings": []}
    assert profile.require_all_stages_runnable and len(profile.stages) == 1
    stage = profile.stages[0]
    cpu = stage.modules.cpu
    assert stage.duration_seconds == 120 and stage.analysis.intent == "functional"
    assert stage.normalization.trim_start_seconds == stage.normalization.trim_end_seconds == 30
    assert profile.defaults.telemetry_interval_seconds == 2
    assert cpu.enabled and cpu.backend_preference == "native" and cpu.instruction_set == KERNEL
    assert cpu.threads == "all" and cpu.power_auto is False
    assert not any(getattr(stage.modules, name).enabled for name in
                   ("memory", "gpu_3d", "vram", "storage_benchmark"))
    with TemporaryDirectory(prefix="lvs-sve-profile-") as temporary:
        saved = Path(temporary) / path.name
        loader.save_profile(saved, copy.deepcopy(profile), labels)
        restored = loader.load_profile(saved)
        assert asdict(restored) == asdict(profile)
        assert not validator.validate(restored, loader.load_segment_labels(saved, restored))["errors"]

    ids = [2, 9, 19]
    def runner_for(machine: str, kernels: list[str]) -> WorkloadRunner:
        runner = WorkloadRunner()
        runner._cpu_machine = lambda: machine
        runner._cpu_target_plan = lambda _: dict(available_cpu_ids=ids, online_cpu_ids=ids,
            allowed_cpu_ids=ids, target_cpu_ids=ids, requested_thread_count="all", actual_worker_count=len(ids))
        runner._cpu_helper_status = lambda: dict(available=True, path="/fixture/build/cpu_stress_helper", reason="")
        runner._cpu_helper_supported_kernel_flavors = lambda cpu_id=None: list(kernels)
        runner._cpu_power_tuning_available = lambda: False
        runner._python_runtime = lambda: "python3"
        runner._command_exists = lambda _: True
        return runner

    runner = runner_for("arm64", ["scalar", "neon", "neon_fp32_fma", KERNEL])
    execution = runner.resolve_cpu_execution(cpu, tune_max_power=False)
    assert execution["backend"] == "cpu_native_helper" and execution["kernel_flavor"] == KERNEL
    command = runner._cpu_command(cpu, KERNEL, "/fixture/results/cpu.json")
    for option, value in (("--kernel-flavor", KERNEL), ("--mode", "sve"),
                          ("--threads", "3"), ("--cpu-ids", "2,9,19")):
        assert command[command.index(option) + 1] == value, command
    diagnostics = runner.stage_diagnostics(stage, labels[0])
    assert KERNEL in json.dumps(diagnostics), diagnostics
    for machine, kernels in (("arm64", ["scalar", "neon", "neon_fp32_fma"]),
                             ("x86_64", ["scalar", "avx2_fma"])):
        unsupported = runner_for(machine, kernels)
        assert unsupported._cpu_backend_name(cpu) == "none"
        assert unsupported._cpu_command(cpu) is None


def run_sve_progress_export_checks() -> None:
    run_sve_functional_profile_checks()
    worker = _sve_fixture()
    assert worker_verification_satisfied(worker)
    mutations = [
        lambda p: p["threads_detail"].pop(),
        lambda p: p.update(arithmetic_verified_blocks=0),
        lambda p: p.update(verification_contract="neon_fp32_fma_v1"),
        lambda p: p.update(verification_contract=[]),
        lambda p: p.update(isa_hwcap=3),
        lambda p: p.update(accumulator_chains=4),
        lambda p: p["threads_detail"][0].update(active_fp32_lanes=8),
        lambda p: p["threads_detail"][0].update(vector_length_bytes=17),
        lambda p: p["threads_detail"][0].update(vector_length_errno=1),
        lambda p: p["threads_detail"][0].update(stress_lane_fmas_per_block=1),
        lambda p: p["threads_detail"][0].update(fpcr=1 << 24),
        lambda p: p["threads_detail"][0].update(affinity_applied=False),
        lambda p: p["threads_detail"][0].update(observed_cpu=10000),
        lambda p: p["threads_detail"][0].update(error_count=1),
        lambda p: p.update(threads_detail=None),
        lambda p: p.update(threads_detail=[None, None]),
        lambda p: p.update(arithmetic_verified_blocks=1 << 64),
        lambda p: p["threads_detail"][0].update(arithmetic_verified_blocks="7"),
    ]
    for phase in ("initial", "periodic", "final"):
        for per_thread in (False, True):
            def mutate(p: dict, phase: str = phase, per_thread: bool = per_thread) -> None:
                (p["threads_detail"][0] if per_thread else p)[phase + "_verification_completed"] = False
            mutations.append(mutate)
    with TemporaryDirectory(prefix="lvs-sve-evidence-") as temporary:
        root = Path(temporary)
        cases = [worker]
        for reported_kernel, reported_contract in (("neon_fp32_fma", "neon_fp32_fma_v1"), ("scalar", "historical")):
            conflict = copy.deepcopy(worker)
            conflict.update(kernel_flavor=reported_kernel, verification_contract=reported_contract)
            apply_worker_entry_context(conflict, SimpleNamespace(command=["helper", "--kernel-flavor", KERNEL]))
            assert conflict["kernel_flavor"] == reported_kernel
            assert not worker_verification_satisfied(conflict)
            cases.append(conflict)
        for mutate in mutations:
            invalid = copy.deepcopy(worker)
            mutate(invalid)
            assert not worker_verification_satisfied(invalid)
            cases.append(invalid)
        for index, case in enumerate(cases):
            directory = root / str(index)
            directory.mkdir()
            _worker_export_round_trip(case, directory)
        # Missing HWCAP2 does not disqualify SVE (and never establishes SVE2).
        for value in (None, 0):
            assert worker_verification_satisfied(dict(worker, isa_hwcap2=value))

        path = root / "progress.jsonl"
        old, window, rows = _fixture(path)
        worker.update(process_pid=73, observed_exit_code=0,
                      verified_progress={"contract": KERNEL + "_progress_v1", "path": str(path)})
        for row in rows:
            row.update(contract=KERNEL + "_progress_v1", kernel_flavor=KERNEL)
            for detail, thread in zip(worker["threads_detail"], row["threads"]):
                thread.update(vector_length_bytes=detail["vector_length_bytes"], active_fp32_lanes=detail["active_fp32_lanes"])
        for detail, final in zip(worker["threads_detail"], rows[-1]["threads"]):
            detail.update(arithmetic_verified_blocks=final["verified_blocks"], verify_passes=final["verified_blocks"])
        worker.update(arithmetic_verified_blocks=rows[-1]["aggregate_verified_blocks"], verify_passes=rows[-1]["aggregate_verified_blocks"])
        _write(path, rows)
        result = analyze_verified_progress(worker, window)
        assert result["quality"] == "sufficient", result
        assert result["aggregate_blocks_per_second"] == 30
        assert result["derived_stress_lane_fmas_per_second"] == 10 * 8192 + 20 * 24576
        assert [t["active_fp32_lanes"] for t in result["threads"]] == [4, 12]
        many = copy.deepcopy(worker)
        many_rows = copy.deepcopy(rows)
        targets = [7 * index + 2 for index in range(512)]
        template = worker["threads_detail"][0]
        many.update(target_cpu_ids=targets, requested_thread_count=512, actual_worker_count=512,
                    affinity_attempted_count=512, affinity_applied_count=512, affinity_failed_count=0,
                    threads_detail=[dict(template, thread_index=i, affinity_target_cpu=cpu, observed_cpu=cpu)
                                    for i, cpu in enumerate(targets)])
        for row in many_rows:
            thread = row["threads"][0]
            row["threads"] = [dict(thread, thread_index=i, cpu_id=cpu, observed_cpu=cpu) for i, cpu in enumerate(targets)]
            row["aggregate_verified_blocks"] = sum(t["verified_blocks"] for t in row["threads"])
        many.update(arithmetic_verified_blocks=512 * 200, verify_passes=512 * 200)
        for detail in many["threads_detail"]:
            detail.update(arithmetic_verified_blocks=200, verify_passes=200)
        _write(path, many_rows)
        high_core = analyze_verified_progress(many, window)
        assert high_core["quality"] == "sufficient", high_core["reasons"]
        assert high_core["aggregate_blocks_per_second"] == 512 * 10
        for bad_details in (None, [None, None], []):
            assert analyze_verified_progress(dict(worker, threads_detail=bad_details), window)["quality"] != "sufficient"
        for mutation in (
            lambda r: r[3]["threads"][0].update(vector_length_bytes=32),
            lambda r: r[3]["threads"][1].update(active_fp32_lanes=4),
            lambda r: r[3].update(aggregate_verified_blocks=1),
            lambda r: r[3]["threads"][0].update(verified_blocks=0),
            lambda r: r.pop(),
            lambda r: r.__delitem__(slice(3, 8)),
        ):
            invalid_rows = copy.deepcopy(rows)
            mutation(invalid_rows)
            _write(path, invalid_rows)
            assert analyze_verified_progress(worker, window)["quality"] != "sufficient"
        _write(path, rows, '{"truncated":')
        assert analyze_verified_progress(worker, window)["quality"] != "sufficient"
        _write(path, rows)
        assert analyze_verified_progress(dict(worker, observed_exit_code=-9), window)["quality"] != "sufficient"
        short = copy.copy(window)
        short.analysis_minimum_usable_seconds = 60
        assert analyze_verified_progress(worker, short)["quality"] != "sufficient"
        # Same counter history, independent per-thread VL; never use NEON's
        # fixed block geometry for scalable operations.
        assert not worker_verification_satisfied(dict(worker, execution_implementation="other"))


if __name__ == "__main__":
    run_sve_fp32_fma_checks()
    run_fp32_error_evidence_checks()
    run_sve_progress_export_checks()
    print("PASS SVE deterministic/reference tests; ARM instruction execution unverified")
