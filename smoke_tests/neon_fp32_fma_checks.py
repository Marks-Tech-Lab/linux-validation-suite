"""Exact FP arithmetic oracle, native lifecycle, selection, and integrity checks.

The integer-only native test build exercises lifecycle on any Linux host; it
explicitly reports test_integer_emulation, never actual NEON execution.
"""
from __future__ import annotations

import copy
import ctypes
from fractions import Fraction
import json
import os
from pathlib import Path
import random
import shutil
import signal
import subprocess
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace

from Modules.lvs_cpu_architecture import (
    cpu_instruction_set_policy, cpu_native_power_probe_kernel_order,
    python_cpu_fallback_policy, resolve_cpu_instruction_intent,
)
from Modules.lvs_cpu_execution import build_cpu_command, build_cpu_benchmark_result, parse_cpu_capability_probe, resolve_cpu_execution_policy
from Modules.lvs_cpu_power_selection import power_cpu_candidate_inventory, power_cpu_fallback_order, select_power_cpu_candidate
from Modules.lvs_cpu_targeting import common_kernel_capabilities, select_common_kernel
from Modules.lvs_profile_loader import ProfileLoader
from Modules.lvs_report_helpers import summarize_cpu_memory_worker_results
from Modules.lvs_worker_integrity import worker_verification_satisfied, worker_integrity_error_count
from Modules.lvs_worker_evidence import apply_worker_entry_context

ROOT = Path(__file__).resolve().parents[1]
KERNEL = "neon_fp32_fma"


def _binary32(bits: int) -> Fraction:
    exponent = (bits >> 23) & 255
    assert exponent != 255
    value = Fraction((bits & 0x7fffff) | (0x800000 if exponent else 0))
    power = exponent - 150 if exponent else -149
    value *= Fraction(2) ** power
    return -value if bits >> 31 else value


def _round_binary32(value: Fraction) -> int:
    """Independent rational oracle: exact nearest-even, no host float/FMA."""
    if not value:
        return 0
    sign = 0x80000000 if value < 0 else 0
    value = abs(value)
    exponent = value.numerator.bit_length() - value.denominator.bit_length()
    if value < Fraction(2) ** exponent:
        exponent -= 1
    scaled = value / (Fraction(2) ** max(exponent - 23, -149))
    quotient, remainder = divmod(scaled.numerator, scaled.denominator)
    if remainder * 2 > scaled.denominator or (remainder * 2 == scaled.denominator and quotient & 1):
        quotient += 1
    if exponent < -126:
        return sign | quotient
    if quotient == 1 << 24:
        exponent += 1
        quotient >>= 1
    if exponent > 127:
        return sign | 0x7f800000
    return sign | ((exponent + 127) << 23) | (quotient & 0x7fffff)


def _oracle(a: int, b: int, c: int) -> int:
    return _round_binary32(_binary32(a) * _binary32(b) + _binary32(c))


def _compile(output: Path, source: Path, *flags: str) -> None:
    compiler = shutil.which("gcc") or shutil.which("cc")
    assert compiler, "native regression requires the normal C compiler"
    result = subprocess.run([compiler, "-O3", "-std=c11", "-pthread", *flags,
                             str(source), "-o", str(output)], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def _run_worker(binary: Path, directory: Path, cpus: list[int], *, expect_failure: bool = False) -> dict:
    result_file = directory / (binary.name + "-" + str(time.monotonic_ns()) + "-result.json")
    process = subprocess.Popen([str(binary), "--kernel-flavor", KERNEL, "--threads", str(len(cpus)),
                                "--cpu-ids", ",".join(map(str, cpus)), "--result-file", str(result_file)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        if not expect_failure:
            time.sleep(0.4)
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=6)
    except BaseException:
        process.kill()
        process.wait()
        raise
    assert process.returncode == (4 if expect_failure else 0), (process.returncode, stdout, stderr)
    return json.loads(result_file.read_text())


def run_neon_fp32_fma_checks() -> None:
    with TemporaryDirectory(prefix="lvs-neon-fp32-") as temporary:
        directory = Path(temporary)
        library_path = directory / "oracle.so"
        _compile(library_path, ROOT / "smoke_tests/native_fp32_fma_reference_check.c", "-shared", "-fPIC")
        library = ctypes.CDLL(str(library_path))
        uint = ctypes.c_uint32
        library.reference_fma.argtypes = [uint, uint, uint, ctypes.POINTER(uint)]
        library.reference_case.argtypes = [uint, ctypes.c_int, ctypes.POINTER(uint)]
        library.lane_check.argtypes = [ctypes.c_int, uint]
        library.environment_check.argtypes = [ctypes.c_uint64]
        assert library.environment_check(0) == 1
        assert library.lost_affinity_check() == 1
        for bit in (22, 23, 24, 8, 9, 10, 11, 12, 15):
            assert library.environment_check(1 << bit) == 0
        def reference(a: int, b: int, c: int) -> int:
            output = uint()
            assert library.reference_fma(a, b, c, ctypes.byref(output)) == 1
            return output.value

        witnesses = [
            (0x3f800001, 0x3f7ffffe, 0xbf800000, 0xa8800000),
            (0x3f800800, 0x3f7ff000, 0xbf800000, 0xb3800000),
            (0x3f800001, 0x3f000000, 0x3f800000, 0x3fc00000),
            (0xbf800001, 0x3f7ffffe, 0x3f800000, 0x28800000),
        ]
        for a, b, c, expected in witnesses:
            assert reference(a, b, c) == expected == _oracle(a, b, c)
        for a, b, c in ((1, 0x3f800000, 1), (0x00800000, 0x3f000000, 0),
                        (0x007fffff, 0x3f800000, 1), (0x3f800001, 0x3f000000, 0xbf000000)):
            assert reference(a, b, c) == _oracle(a, b, c)
        a, b, c, expected = witnesses[0]
        separate = _oracle(_oracle(a, b, 0), 0x3f800000, c)
        assert separate == 0 and expected != separate, "fixture must distinguish fused arithmetic"
        rng = random.Random(731)
        for _ in range(700):
            a, b, c = [rng.getrandbits(32) & 0x803fffff | (rng.randrange(110, 140) << 23) for _ in range(3)]
            assert reference(a, b, c) == _oracle(a, b, c)
        output = uint()
        for nonfinite in (0x7f800000, 0xff800000, 0x7fc00000):
            assert library.reference_fma(nonfinite, 0x3f800000, 0, ctypes.byref(output)) == 0
        assert library.lane_check(-1, 0) == -1
        for lane in range(32):
            for bad in (0, (0x3f000000 + lane) ^ 1, 0x7fc00000, 0x7f800000):
                assert library.lane_check(lane, bad) == lane

        # Independently establish every final lane of all four authored blocks
        # for multiple runtime seeds, not just the witness/canary values.
        for seed in (0, 1, 2, 51, 0xffffffff):
            for which in range(4):
                actual = (uint * 32)()
                assert library.reference_case(seed, which, actual) == 1
                for lane in range(32):
                    mix = (seed * 1664525 + lane * 1013904223 + which * 69069) & 0xffffffff
                    value = 0x3f000000 | (mix & 0x3fffff)
                    multiplier = 0x3f7f0000 | ((mix >> 5) & 0xffff)
                    addend = 0x3a800000 | ((mix >> 9) & 0x3fffff) | (0x80000000 if lane & 1 else 0)
                    for _ in range(256):
                        value = _oracle(value, multiplier, addend)
                    assert actual[lane] == value
                    assert (value >> 23) & 255 != 255

        # Test-only execution never advertises real vector instruction coverage.
        source = ROOT / "native/cpu_stress_helper.c"
        emulated = directory / "emulated"
        _compile(emulated, source, "-DLVS_CPU_HELPER_TEST_FP32_FMA")
        cpus = sorted(os.sched_getaffinity(0))[:2]
        valid = _run_worker(emulated, directory, cpus)
        assert valid["execution_implementation"] == "test_integer_emulation"
        assert valid["isa_capability_source"] == "test_override" and valid["isa_hwcap"] is None
        assert valid["operation_family"] == "fp32_fused_multiply_add"
        assert worker_verification_satisfied(valid)
        assert valid["error_count"] == 0 and valid["canary_passes"] == 0
        assert all(row["arithmetic_verified_blocks"] >= 3 for row in valid["threads_detail"])
        assert build_cpu_benchmark_result(kernel_flavor=KERNEL, samples=[1.0], result_payload=valid, return_code=0)["valid"]
        for code in (None, -9, -11, 4):
            assert not build_cpu_benchmark_result(kernel_flavor=KERNEL, samples=[1.0], result_payload=valid, return_code=code)["valid"]
        assert summarize_cpu_memory_worker_results([{"WorkerResults": [valid]}])["SuccessfulWorkerResultCount"] == 1
        for macro, lane in (("CORRUPT_FP32_LANE", 17), ("NONFINITE_FP32_LANE", 31), ("UNFUSED_FP32", 0)):
            broken = directory / macro.lower()
            _compile(broken, source, "-DLVS_CPU_HELPER_TEST_FP32_FMA", "-DLVS_CPU_HELPER_TEST_" + macro)
            invalid = _run_worker(broken, directory, cpus[:1], expect_failure=True)
            assert invalid["status"] == "error" and not worker_verification_satisfied(invalid)
            assert invalid["threads_detail"][0]["first_error_lane"] == lane
            assert invalid["threads_detail"][0]["first_error"]["kind"] == "fp32_fma_mismatch"
        affinity_failed = _run_worker(emulated, directory, [max(os.sched_getaffinity(0)) + 10000], expect_failure=True)
        assert affinity_failed["affinity_failed_count"] == 1
        assert not affinity_failed["verification_complete"]
        assert affinity_failed["threads_detail"][0]["first_error_lane"] == -1
        partial = directory / "partial_startup"
        _compile(partial, source, "-DLVS_CPU_HELPER_TEST_FP32_FMA", "-DLVS_CPU_HELPER_TEST_THREAD_START_FAILURE")
        # Two targets are needed to inject a failure of the second creation;
        # duplicate IDs are rejected by the normal native argument validator.
        if len(cpus) > 1:
            invalid = _run_worker(partial, directory, cpus, expect_failure=True)
            assert invalid["actual_worker_count"] == 1 and invalid["requested_thread_count"] == 2
            assert not invalid["verification_complete"] and not worker_verification_satisfied(invalid)

        native = directory / "native"
        _compile(native, source)
        if os.uname().machine not in {"aarch64", "arm64"}:
            unsupported = subprocess.run([str(native), "--kernel-flavor", KERNEL, "--print-kernel-flavor"], capture_output=True)
            assert unsupported.returncode == 3
        for missing in ("FP", "ASIMD"):
            binary = directory / ("missing_" + missing)
            _compile(binary, source, "-DLVS_CPU_HELPER_TEST_FP32_FMA", "-DLVS_CPU_HELPER_TEST_DISABLE_" + missing)
            assert subprocess.run([str(binary), "--kernel-flavor", KERNEL, "--print-kernel-flavor"], capture_output=True).returncode == 3
        # Each missing lane/thread/phase fails, even with abundant aggregate passes.
        for mutate in (
            lambda p: p["threads_detail"][0].update(final_verification_completed=False),
            lambda p: p["threads_detail"][0].update(initial_verification_completed=False),
            lambda p: p["threads_detail"][0].update(periodic_verification_completed=False),
            lambda p: p["threads_detail"][0].update(arithmetic_verified_blocks=0),
            lambda p: p["threads_detail"][0].update(affinity_applied=False),
            lambda p: p["threads_detail"][0].update(observed_cpu=-1),
            lambda p: p.update(periodic_verification_completed=False),
            lambda p: p.update(arithmetic_verified_blocks=0),
            lambda p: p.update(actual_worker_count=0),
            lambda p: p.update(threads_detail=[]),
            lambda p: p.pop("verification_method"),
            lambda p: p.update(verification_required=False, verification_complete=False),
        ):
            invalid = copy.deepcopy(valid)
            mutate(invalid)
            assert not worker_verification_satisfied(invalid)
            assert worker_integrity_error_count([invalid]) > 0
            assert not build_cpu_benchmark_result(kernel_flavor=KERNEL, samples=[1.0], result_payload=invalid, return_code=0)["valid"]
            assert summarize_cpu_memory_worker_results([{"worker_results": [invalid]}])["WorkerFailureCount"] == 1
        assert worker_verification_satisfied({"kind": "cpu", "kernel_flavor": "neon", "verify_passes": 1})
        missing = {}
        apply_worker_entry_context(missing, SimpleNamespace(command=["cpu_stress_helper_arm64", "--kernel-flavor", KERNEL]))
        assert not worker_verification_satisfied(missing)

    common = ["scalar", "neon", KERNEL]
    for intent in ("high_throughput_vector", "highest_verified_vector"):
        assert resolve_cpu_instruction_intent("aarch64", intent, common)["resolved_kernel_flavor"] == KERNEL
        assert resolve_cpu_instruction_intent("aarch64", intent, ["scalar", "neon"])["resolved_kernel_flavor"] == "neon"
    assert resolve_cpu_instruction_intent("aarch64", "baseline_vector", common)["resolved_kernel_flavor"] == "neon"
    assert resolve_cpu_instruction_intent("x86_64", "highest_verified_vector", ["avx2_fma"])["resolved_kernel_flavor"] == "avx2_fma"
    assert cpu_instruction_set_policy("aarch64", KERNEL)["allowed"]
    assert not cpu_instruction_set_policy("x86_64", KERNEL)["allowed"]
    assert not python_cpu_fallback_policy("aarch64", KERNEL)["allowed"]
    assert KERNEL in parse_cpu_capability_probe(0, "scalar,neon," + KERNEL)
    assert cpu_native_power_probe_kernel_order("aarch64") == ("neon", "scalar", KERNEL)
    assert select_common_kernel(architecture="arm64", requested_mode=KERNEL, common_flavors=common) == KERNEL
    assert select_common_kernel(architecture="arm64", requested_mode=KERNEL, common_flavors=["scalar", "neon"]) == ""
    assert select_common_kernel(architecture="arm64", requested_mode="auto", common_flavors=common) == "neon"
    assert common_kernel_capabilities([2, 19], {2: common, 19: ["scalar", "neon"]})["common_kernel_flavors"] == ["neon", "scalar"]
    command = build_cpu_command(worker_count=2, helper_available=True, helper_path="helper",
                                requested_mode="neon", instruction_set=KERNEL, mode="extreme",
                                stress_ng_available=False, python_runtime="", cpu_kernel_flavor=KERNEL, target_cpu_ids=[2, 19])
    assert command[command.index("--kernel-flavor") + 1] == KERNEL
    assert command[command.index("--cpu-ids") + 1] == "2,19"
    viable, unavailable = power_cpu_candidate_inventory(architecture="arm64", availability={"cpu_native_helper": True},
                                                        native_kernel_flavors=common, selected_native_kernel="neon")
    assert [p["kernel_flavor"] for p in power_cpu_fallback_order("arm64", viable)] == ["scalar", "neon", KERNEL]
    winner = next(p for p in viable if p["kernel_flavor"] == KERNEL)
    selected = select_power_cpu_candidate(architecture="arm64", viable_candidates=viable, unavailable_candidates=unavailable,
        telemetry={"available": True}, probe_duration_seconds=3,
        candidate_results=[{**winner, "valid": True, "verification_valid": True, "meaningful_work": True,
                            "power_sample_count": 3, "avg_cpu_power_w": 9}])
    assert selected["selected_candidate"]["kernel_flavor"] == KERNEL
    cache = {}
    for flavor in (KERNEL, "neon", KERNEL):
        resolution = resolve_cpu_execution_policy(
            backend="cpu_native_helper", requested_mode="neon", resolved_mode="neon",
            kernel_flavor=flavor, tuning_policy="family_locked", candidate_kernel_flavors=[flavor],
            tune_max_power=True, worker_count=lambda: (2, 19), power_tuning_available=lambda: True,
            benchmark_candidate=lambda _: {}, tuning_cache=cache)
        assert resolution["kernel_flavor"] == flavor

    from Modules.lvs_workload_cpu_memory import WorkloadCpuMemoryMixin
    from Modules.lvs_profile_models import ModuleCpu
    class Runner(WorkloadCpuMemoryMixin):
        def _cpu_machine(self):
            return "arm64"
        def _cpu_target_plan(self, cpu):
            return {"target_cpu_ids": [2, 19], "requested_thread_count": 2, "actual_worker_count": 2}
        def _cpu_helper_supported_kernel_flavors(self, cpu_id=None):
            return common
        def _cpu_helper_status(self):
            return {"available": True}
    runner = Runner()
    cpu = ModuleCpu(enabled=True, instruction_set=KERNEL)
    plan = runner._cpu_capability_plan(cpu)
    assert plan["selected_kernel_flavor"] == KERNEL
    assert plan["capability_scope"] == "linux_aarch64_hwcap_common_set"
    assert plan["target_cpu_ids"] == [2, 19]
    assert runner._cpu_candidate_kernel_flavors(cpu) == [KERNEL]
    runner._cpu_helper_supported_kernel_flavors = lambda cpu_id=None: ["scalar", "neon"]
    assert not runner._cpu_capability_plan(cpu)["selected_kernel_flavor"]

    # Round-trip the existing profile schema, without changing any repository profile.
    with TemporaryDirectory(prefix="lvs-neon-profile-") as directory:
        loader = ProfileLoader(Path(directory))
        from Modules.lvs_profile_editor import ProfileEditor
        from Modules.lvs_profile_validation import ProfileValidator
        profile = loader.load_profile(ROOT / "profiles/Quick Test.json")
        cpu = profile.stages[0].modules.cpu
        cpu.instruction_set = KERNEL
        cpu.instruction_intent = ""
        cpu.power_auto = False
        assert KERNEL in ProfileEditor.CPU_INSTRUCTION_OPTIONS
        path = Path(directory) / "roundtrip.json"
        loader.save_profile(path, profile)
        assert loader.load_profile(path).stages[0].modules.cpu.instruction_set == KERNEL
        assert not ProfileValidator().validate(profile, [str(n) for n in range(len(profile.stages))])["errors"]


def _export_worker_fixture() -> dict:
    """Sparse-CPU, two-thread reproduction of the captured v1 ARM contract."""
    phases = dict(initial_verification_completed=True, periodic_verification_completed=True,
                  final_verification_completed=True)
    details = [dict(thread_index=index, affinity_target_cpu=cpu, observed_cpu=cpu,
                    affinity_attempted=True, affinity_applied=True, affinity_required=True,
                    affinity_error_code=0, verify_passes=blocks, arithmetic_verified_blocks=blocks,
                    error_count=0, canary_passes=0, interrupted_arithmetic_blocks=0,
                    fpcr=0, first_error_lane=-1, **phases)
               for index, (cpu, blocks) in enumerate(((2, 3), (19, 7)))]
    return dict(kind="cpu", status="ok", mode="neon", kernel_flavor=KERNEL,
                threads=2, requested_thread_count=2, actual_worker_count=2, target_cpu_ids=[2, 19],
                capability_scope="linux_aarch64_hwcap_common_set", isa_hwcap=3,
                isa_capability_source="linux_getauxval_at_hwcap_common_set",
                operation_family="fp32_fused_multiply_add", verification_required=True,
                verification_contract="neon_fp32_fma_v1", verification_version=1,
                verification_method="integer_binary32_fma_reference",
                rounding_environment="nearest_ties_even_no_flush",
                execution_implementation="aarch64_neon_intrinsics", verification_complete=True,
                verify_passes=10, arithmetic_verified_blocks=10, lanes_per_block=32,
                fma_rounds_per_block=256, canary_passes=0, error_count=0,
                affinity_attempted_count=2, affinity_applied_count=2, affinity_failed_count=0,
                threads_detail=details, **phases)


def _worker_export_round_trip(worker: dict, run_dir: Path, *, legacy_projection: bool = False) -> dict:
    """Exercise real parser, exporter, and final artifact writer in a temp run."""
    from Modules.lvs_compat_exporter import CompatibilityExporter
    from Modules.lvs_compat_export_helpers import preserve_legacy_worker_evidence_contract
    from Modules.lvs_core import JsonStore
    from Modules.lvs_profile_models import ValidationProfile
    from Modules.lvs_run_artifacts import write_final_run_artifacts
    from Modules.lvs_run_metadata import RunMetadata
    from Modules.lvs_run_models import StageWindow
    from Modules.lvs_segment_parser import SegmentParser
    from Modules.lvs_summary_text import SummaryTextBuilder

    worker_path = run_dir / "native_cpu.json"
    JsonStore.write(worker_path, worker)
    native = JsonStore.read(worker_path, {})
    failed = worker_integrity_error_count([native]) > 0
    window = StageWindow(
        stage_id="fp32", stage_type="CPU", display_name="FP32 export fixture",
        started_iso="2026-10-19T10:00:00+00:00", ended_iso="2026-10-19T10:02:00+00:00",
        started_monotonic=0.0, ended_monotonic=120.0, duration_seconds=120.0,
        trim_start_seconds=30, trim_end_seconds=30, analysis_intent="functional",
        cpu_backend="cpu_native_helper", cpu_mode_requested="sve" if native.get("kernel_flavor") == "sve_fp32_fma" else "neon",
        cpu_mode_resolved="sve" if native.get("kernel_flavor") == "sve_fp32_fma" else "neon",
        cpu_kernel_flavor=native.get("kernel_flavor", KERNEL), worker_results=[native], verdict="fail" if failed else "pass")
    telemetry = SimpleNamespace(samples=[], interval_seconds=2.0, _gpu_sources=[],
                                source_map=lambda: {"fields": {}})
    result = write_final_run_artifacts(
        run_dir=run_dir, manifest_payload={}, app_name="Linux Validation Suite", app_version="0.5.1-alpha",
        profile=ValidationProfile(profile_name="FP32 export fixture"), metadata=RunMetadata(),
        started_iso=window.started_iso, ended_iso=window.ended_iso, total_elapsed=120.0,
        system_info={"Hardware": {"Cpu": {"Name": "ARM fixture"}, "Gpu": [], "Memory": {},
                                  "Motherboard": {}, "Bios": {}, "Storage": []}},
        telemetry=telemetry, stage_windows=[window], executed_plan=[{}], recovery_report={},
        skipped_stages=[], run_aborted=False, keep_raw_telemetry=False,
        export_compatibility_json=True, export_extended_json=True,
        segment_parser=SegmentParser(), exporter=CompatibilityExporter(), summary_exporter=SummaryTextBuilder(),
        stage_sensor_events=lambda _: [], stage_faults=lambda _: [], capture_run_end=lambda **_: None)
    manifest = JsonStore.read(run_dir / "run_manifest.json", {})
    custom = JsonStore.read(run_dir / "parsed_results_custom.json", {})
    extended = JsonStore.read(run_dir / "parsed_results_extended.json", {})
    parsed = result.parser_output
    for evidence in (manifest["stage_windows"][0]["worker_results"][0],
                     parsed["Segments"][0]["WorkerResults"][0],
                     custom["Segments"][0]["WorkerResults"][0],
                     custom["SegmentDetails"]["segment_1"]["worker_results"][0],
                     extended["stage_windows"][0]["worker_results"][0],
                     extended["compatibility_export"]["Segments"][0]["WorkerResults"][0]):
        expected = preserve_legacy_worker_evidence_contract(native) if legacy_projection else native
        assert evidence == native or (legacy_projection and evidence == expected), "export must not filter, repair, or synthesize versioned evidence"
        assert worker_verification_satisfied(evidence) == worker_verification_satisfied(native)
        assert worker_integrity_error_count([evidence]) == worker_integrity_error_count([native])
    assert (result.overall_verdict == "fail") == failed
    assert custom["ReportSummary"]["DepartmentUseSummary"]["WorkerVerified"] is (not failed)
    return custom


def run_neon_fp32_fma_export_checks() -> None:
    from Modules.lvs_compat_export_helpers import preserve_legacy_worker_evidence_contract

    valid = _export_worker_fixture()
    assert worker_verification_satisfied(valid)
    cases = [valid]
    def arithmetic_mismatch(payload: dict) -> None:
        payload.update(error_count=1, status="error", verification_complete=False)
        payload["threads_detail"][0].update(error_count=1, first_error_lane=17,
            final_verification_completed=False, first_error={"kind": "fp32_fma_mismatch",
                "iteration": 1, "expected": 0x3f800000, "actual": 0x7f800000})

    mutations = [
        lambda p: p.pop("threads_detail"),
        lambda p: p["threads_detail"].__setitem__(0, None),
        lambda p: p["threads_detail"][0].pop("affinity_target_cpu"),
        lambda p: p["threads_detail"][0].update(affinity_applied=False),
        lambda p: p["threads_detail"][0].update(observed_cpu=19),
        lambda p: p.update(requested_thread_count=3),
        lambda p: p.update(actual_worker_count=1),
        lambda p: p.update(arithmetic_verified_blocks=11),
        lambda p: p["threads_detail"][0].update(arithmetic_verified_blocks=0),
        lambda p: p.pop("verification_method"),
        lambda p: p.pop("kernel_flavor"),
        lambda p: p.update(kernel_flavor="scalar"),
        lambda p: p.update(verification_complete=False),
        arithmetic_mismatch,
    ]
    for mutate in mutations:
        broken = copy.deepcopy(valid)
        mutate(broken)
        assert not worker_verification_satisfied(broken)
        cases.append(broken)
    for phase in ("initial", "periodic", "final"):
        for per_thread in (True, False):
            broken = copy.deepcopy(valid)
            target = broken["threads_detail"][0] if per_thread else broken
            target[phase + "_verification_completed"] = False
            assert not worker_verification_satisfied(broken)
            cases.append(broken)
    with TemporaryDirectory(prefix="lvs-fp32-export-") as directory:
        for index, worker in enumerate(cases):
            run_dir = Path(directory) / str(index)
            run_dir.mkdir()
            _worker_export_round_trip(worker, run_dir)

    # The recognized record boundary is preserved even when invalid. Envelopes,
    # siblings, older workers, and unrecognized versions still use frozen rules.
    output = preserve_legacy_worker_evidence_contract(valid)
    output["threads_detail"][0]["fpcr"] = 1
    assert valid["threads_detail"][0]["fpcr"] == 0, "export must not alias the source record"
    for flavor in ("neon", "scalar", "avx2_fma"):
        legacy = dict(kind="cpu", status="ok", kernel_flavor=flavor, verify_passes=3,
                      requested_thread_count=1, actual_worker_count=1, target_cpu_ids=[2],
                      verification_method="historical_method", capability_scope="historical",
                      affinity_attempted_count=1, affinity_applied_count=1,
                      threads_detail=[dict(thread_index=0, verify_passes=3,
                          affinity_target_cpu=2, affinity_applied=True, observed_cpu=2)])
        expected = dict(kind="cpu", status="ok", kernel_flavor=flavor, verify_passes=3,
                        threads_detail=[dict(thread_index=0, verify_passes=3)])
        assert preserve_legacy_worker_evidence_contract(legacy) == expected
        mixed = preserve_legacy_worker_evidence_contract({"WorkerResults": [valid, legacy]})
        assert mixed["WorkerResults"] == [valid, expected]
    unknown = {**valid, "verification_contract": "neon_fp32_fma_v2"}
    assert "verification_method" not in preserve_legacy_worker_evidence_contract(unknown)
    missing = {k: v for k, v in valid.items() if k != "verification_contract"}
    assert "verification_contract" not in preserve_legacy_worker_evidence_contract(missing)
    assert not worker_verification_satisfied(preserve_legacy_worker_evidence_contract(missing))


if __name__ == "__main__":
    run_neon_fp32_fma_checks()
    run_neon_fp32_fma_export_checks()
    print("PASS NEON FP32/FMA arithmetic and export checks (no physical ISA claim)")
