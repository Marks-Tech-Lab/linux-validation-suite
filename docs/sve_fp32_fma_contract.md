# AArch64 SVE FP32/FMA implementation contract

`sve_fp32_fma` is an exact optional native kernel, not a relabelled NEON loop.
The `sve` family resolves only to this kernel. Explicit requests never substitute
scalar, integer NEON, or NEON FP32/FMA. SVE2 is neither required nor implemented.

## Portable build and capability boundary

The normal native-helper build first attempts `-DLVS_CPU_HELPER_ENABLE_SVE` for
the AArch64 CPU helper. Only `native/cpu_sve_kernel.h`'s non-inlined functions
are inside a GCC `target("+sve")` region. There is no global SVE architecture
flag. Scalable vectors never cross the baseline interface: only scalar values
and pointers do. GCC's default scalable-vector-length compilation is retained.
An optional-build failure is recorded separately and retried as a baseline
build, preserving supported scalar/NEON execution. x86 build commands are unchanged.
The helper's readiness also tracks the included header's modification time.

`--print-isa-capabilities` reports raw Linux AT_HWCAP and AT_HWCAP2, optional SVE
compilation, and the calling thread's current PR_SVE_GET_VL result where supported.
Missing HWCAP2 is unavailable, not numeric zero. This query does not configure
VL or discover the maximum/supported set of lengths. Native backend details retain
the probe and optional compiler failure separately from hardware availability.

Linux common HWCAP must expose FP and SVE. Models, MIDR, clocks, topology, and
capacity never authorize execution. Each worker binds to its online/process-allowed
CPU before initialization; failed affinity is fatal. PR_SVE_GET_VL preserves the
thread's inherited state, records bytes/flags/errno, and requires a valid architectural
16..256-byte length in 16-byte units. FP32 lanes are VL bytes / 4. Lengths need
not be powers of two. Every block checks actual `svcntw()` against initialization;
observed CPU checks before/after verification reject unexpected migration.

## Arithmetic and independent verification

Eight independent scalable FP32 accumulators perform 256 fused recurrence rounds:
`x = fma(x, multiplier, addend)`. All active lanes have runtime/thread-dependent,
lane-distinct inputs. Four rotating finite, bounded cases use the existing exact
integer-significand binary32 FMA reference. Expected outputs are precomputed once,
not computed with SVE or host floating-point arithmetic. The reference's bounded
exponent domain and nearest/ties-even/no-flush FPCR requirements remain unchanged.
Every lane is bit-compared; nonfinite values fail. No arbitrary tolerance applies.

Four active SVE fused witnesses include the established fused/unfused cancellation
and rounding cases. Remaining witness lanes have specified merge operands whose
preservation is checked. A predicated store must preserve inactive destinations
and guard words. At minimum VL all four witness lanes are active; larger lengths
exercise an actual inactive tail. No unspecified inactive contents are compared.

All targeted threads must complete initial, subsequent periodic, and final verified
blocks. Only complete arithmetic, witness, predicate, and affinity checks increment
counters. Interrupted blocks are excluded. First error/lane/expected/actual bits
are retained; failures stop the worker. Initial reference preparation is cancellable.
Stress blocks check cancellation every 32 rounds; the final block is bounded.

Working memory is O(actual VL) per thread (about 36 KiB at architectural maximum),
independent of RAM size. No allocation floor, CPU-model rule, or system-memory proxy
sets compute intensity. No publication I/O or lock is present in the arithmetic loop.

## Evidence and compatibility

`sve_fp32_fma_v1` is separate from the unchanged `neon_fp32_fma_v1` contract.
It records actual ISA, operation family, reference method/version, eight chains,
256 rounds, predicate verification method, raw capabilities, and per-thread VL,
lanes, FPCR, affinity, phases, interrupted/completed work, and first errors.
One successful thread or aggregate count cannot conceal incomplete verification.
Compatibility WorkerResults preserve the entire versioned record, including
failed/incomplete records; serialization never repairs or invents evidence.

Both implemented FP32 v1 contracts require explicit native JSON integer zero
error counts for the worker and every required thread. Missing, null, boolean,
string, floating-point, negative, or nonzero counters cannot establish success.
Recorded first errors, arithmetic mismatches, contradictory phases/identities,
or conflicting pass-count aliases reject verification even with zero counters.
Absent first-error records, null/empty objects, and the native empty flat-detail
sentinels remain valid. Optional capability errno or progress-persistence quality
does not itself become an arithmetic mismatch. Negative invalid counters cannot
cancel a blocking integrity failure in reporting. Unversioned historical workers
keep their established interpretation; no native arithmetic is changed by this
evidence correction.

`<result-file>.progress.jsonl` uses `sve_fp32_fma_progress_v1`. It reuses the bounded
O(threads) publisher, monotonic/realtime correlation, exclusive append stream,
startup/initial/ongoing/interrupted/final states, and coarse block-boundary publication.
Snapshots add per-thread VL and active lanes. Counter/identity checks, unclean-exit
rejection, stale/missing/truncated records, final-result reconciliation, and actual
post-trim endpoint calculations reuse the established progress analyzer.

Per-thread derived stress work is `verified_blocks * 8 * active_fp32_lanes * 256`;
four additional active witness lane-FMAs are accounted separately. Aggregate
derived stress lane-FMAs/s sum independently timed per-thread rates, supporting
different VLs without pretending blocks are equal work. These are derived arithmetic
counts, not measured machine instructions or proof of maximum pipeline saturation.
Reports expose quality, per-thread lengths, verified blocks/s, and derived lane work.
Historical NEON records retain their fixed geometry and established interpretation.

SVE remains experimental and explicit-only. Spark functional build, instruction,
and execution evidence is now accepted as described below; sustained and broader
vector-length acceptance remain pending. Generic auto, all generic
vector intents (including highest-verified-vector), and Power Auto exclude SVE,
even when hardware capability is present. Capability discovery still reports SVE
and exact `sve`/`sve_fp32_fma` functional requests remain available without fallback.
Baseline-vector and high-throughput-vector preserve their NEON policies.
Tuning involving explicit SVE is not cached across invocations,
because inherited per-thread VL is not a stable pre-execution cache key.

## Validation boundary and future physical acceptance

Local integer-emulation builds are labelled `test_integer_emulation`, including
their actual-ISA field. They test reference, lane rejection, state/lifecycle,
progress, and export contracts, never SVE instruction execution. Deterministic
fixtures cover varying/non-power-of-two VLs and mixed per-thread configurations.

For future hardware acceptance, preserve AArch64 compilation and optimized SVE
disassembly evidence. Use the
normal updated LVS helper build, preserve its compiler/build provenance and SHA-256,
and inspect the actual scalable hot loop (not only witnesses) for fused vector FP32
instructions and retained independent recurrences. Confirm baseline paths remain
free of SVE instructions. Associate that same executable with subsequent normal LVS
execution; do not retrofit provenance onto historical NEON runs.

Spark's captured HWCAP advertises SVE; its functional run observed inherited VL
16 bytes on every thread, not the maximum or the supported set of VLs.
The captured Snapdragon environment lacks HWCAP_SVE and is a negative-capability
target, not proof of SVE execution. Neither machine establishes SVE2 availability.
The active `ARM64 SVE FP32 FMA Functional Confirmation` profile is a required,
120-second native CPU-only functional stage with exact `sve_fp32_fma` selection,
Power Auto disabled, all allowed/online CPUs, two-second telemetry, and 30-second
start/end trims. Profile validity does not authorize execution on non-SVE hosts.
The October 20 Spark functional run and subsequently preserved executable close
the initial Spark functional acceptance, with the association limitation below.
Other systems/vector lengths are not thereby accepted.
No universal throughput, power, thermal, or saturation threshold is introduced.

Prepare and transfer the complete updated LVS test build through the normal
workflow, including `native/cpu_sve_kernel.h`. Let normal LVS diagnostics/runtime
compile the helper; no separately compiled helper is required. On Spark, retain
the native backend's actual helper path, optional SVE build attempt/result,
compiler command/version, capability probe, and per-thread inherited VL evidence.
Dry-run this profile and require the exact kernel with no fallback. Run the normal
functional profile with Advanced Debug, then preserve the actual helper executable,
its SHA-256 and source hashes alongside diagnostics and execution artifacts for
optimized disassembly of `execute_sve_fp32_block` and relevant compiler clones.
Keep the same executable associated with execution, not a later rebuild. Confirm
scalable FP32 fused instructions in the repeated stress recurrences, not only the
witnesses. A failed optional compiler build must remain explicit unsupported-SVE
evidence while baseline kernels stay usable. Snapdragon's captured non-SVE
environment is a negative-capability target, not a positive execution target.

## Completed Spark functional and instruction inspection

The immutable October 20, 2026 functional execution at
`results/2026-10-20_17-15-24_ARM64 SVE FP32 FMA Functional Confirmation` and its
`17-15-23` diagnostics passed on all 20 Spark CPUs. All initial, periodic and
final verification and affinity checks completed, with zero arithmetic errors,
FPCR zero, inherited VL 16 bytes/four FP32 lanes, and exit code zero. There were
2,241,467,524 verified blocks; 12 interrupted blocks were excluded. The functional
trimmed window was 61.102742 seconds, not a long sustained acceptance run.
Observed aggregate verified throughput was 18,513,925.877 blocks/s, derived
151,666,080,780.525 active-lane stress FMAs/s. This does not prove saturation.

On October 21 the preserved `results/cpu_stress_helper_arm64` was inspected,
without rebuilding it, using the installed LLVM 22.1 AArch64 disassembler API.
It is a 74,024-byte AArch64 ELF64 little-endian PIE, GCC 13.3.0, build ID
`f3b34af257e4a9e1284885d3d9000591cc7ac560`, SHA-256
`5916457f945d7b28d19ad7c5aa998c8382b470209de67240646bed26c746d4fc`.
Its preserved mtime is October 20 17:15:21 EDT, consistent with normal compilation
immediately before the captured diagnostics/execution.

`execute_sve_fp32_block` at 0x3444 uses `cntw`, scalable predicated loads/stores,
eight independent `fmla z7.s` through `z0.s` recurrences, a 256-round bound and
32-round cancellation checks. Example at 0x3560:
`fmla z7.s, p0/m, z8.s, z24.s`; the eighth is at 0x35bc.
`execute_sve_witness` at 0x3624 uses a four-lane predicate, merge FMLA and masked
stores. Live worker calls target both functions. Scalable-vector instructions
were confined to these isolated functions in the inspected .text; baseline auto
dispatch retains its HWCAP-gated NEON/scalar path. No hot-loop accumulator spills
or eliminated recurrences were found; one ABI d8 save/restore is outside the loop.
Moves/movprfx are present; this is instruction correctness, not peak efficiency.

The source contract, build metadata, timing and operator-preserved origin strongly
associate this helper with Spark's run. That historical run did not record a
launch-time executable hash: identical executed-binary identity is not
cryptographically established, and original evidence has not been amended.
No repeat functional test is justified by the available evidence. At VL 16 bytes
the witness has no inactive vector tail; larger-VL tails remain fixture-tested.
CPU-specific temperatures, power and throttling remain unavailable/platform-dependent.

New builds automatically capture separate [native executable provenance](native_executable_provenance.md)
at normal launch and completion. This does not retrospectively attest this run.
