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

For v0.5.2-alpha SVE remains experimental and explicit-only pending actual ARM
build, instruction-emission, and physical acceptance. Generic auto, all generic
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

Actual AArch64 compilation and optimized SVE disassembly remain required. Use the
normal updated LVS helper build, preserve its compiler/build provenance and SHA-256,
and inspect the actual scalable hot loop (not only witnesses) for fused vector FP32
instructions and retained independent recurrences. Confirm baseline paths remain
free of SVE instructions. Associate that same executable with subsequent normal LVS
execution; do not retrofit provenance onto historical NEON runs.

Spark's captured HWCAP advertises SVE, but its current VL has not been captured.
The captured Snapdragon environment lacks HWCAP_SVE and is a negative-capability
target, not proof of SVE execution. Neither machine establishes SVE2 availability.
The active `ARM64 SVE FP32 FMA Functional Confirmation` profile is a required,
120-second native CPU-only functional stage with exact `sve_fp32_fma` selection,
Power Auto disabled, all allowed/online CPUs, two-second telemetry, and 30-second
start/end trims. Profile validity does not authorize execution on non-SVE hosts.
There is no SVE physical acceptance yet.
Future functional all-thread acceptance must precede sustained effectiveness work.
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
