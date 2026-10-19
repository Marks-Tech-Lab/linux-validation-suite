# AArch64 NEON FP32/FMA worker contract

`neon_fp32_fma` is distinct from the existing integer `neon` kernel. It can be
selected explicitly with CPU `instruction_set: neon_fp32_fma`, or through the
native helper's exact `--kernel-flavor neon_fp32_fma` argument. ARM
`high_throughput_vector` and `highest_verified_vector` intents prefer it when
the complete target set proves support; `baseline_vector` retains integer
NEON. Generic auto selection and unmeasured Power Auto fallback retain their
existing ordering. Power Auto may measure the new candidate, not assume it is
the highest-power workload.

## Arithmetic and independent verification

Eight independent `float32x4_t` chains each perform 256 dependent `vfmaq_f32`
steps per block (8,192 scalar-lane fused operations). A compiler register
barrier retains every step. Inputs are runtime/thread-seed dependent and
lane-distinct. Four rotating cases have bounded finite states, multiplier
magnitudes below one, and small signed addends. Active case/reference data are
only a few KiB per thread, independent of system RAM. No architecture-wide
compiler flags or model/capacity-derived ISA assumptions are used.

Expected outputs are computed once using integer significands, exact aligned
products/sums, and one binary32 round-to-nearest/ties-even operation per FMA.
This reference has a deliberately bounded exponent-alignment domain and fails
closed outside it. It does not use host floating-point, the SIMD implementation,
or a tolerance. Deterministic tests independently establish all authored output
lanes using Python rational arithmetic, plus rounding/subnormal cases.

Every completed hardware block checks all 32 accumulator lanes, then four
additional fused witnesses. These include `(1+2^-23)*(1-2^-23)-1 = -2^-46`
(bits `a8800000`), which separately rounded multiplication/addition turns into
zero; a second cancellation (`b3800000`), a ties-even result (`3fc00000`), and
positive cancellation (`28800000`). NaN, infinity, or any incorrect bit fails
immediately, preserving the first lane and expected/actual bit patterns.
The existing integer canary is not counted as FP verification.

Each thread requires initial, subsequent periodic, and final checked blocks.
Periodic verification occurs every block, not on an aggregate timer. SIGTERM
interrupts ordinary blocks at most every 32 rounds; after an initial verified
block a final bounded block is checked before exit. A run stopped too early to
complete its per-thread contract fails rather than claiming success.

The required FPCR environment is nearest/ties-even, FP32 flush-to-zero disabled,
and exception traps disabled. The worker checks rather than silently changes
the inherited environment. Ordinary sticky inexact flags are not errors.

## Capability, affinity, and evidence

Linux common HWCAP must expose both FP and ASIMD. MIDR, clocks, core models,
and capacity tiers are never ISA evidence. Target CPUs remain the online /
process-allowed intersection, with sparse IDs preserved. Binding must succeed;
observed CPU checks reject migration outside the singleton target. Missing
capability, failed startup, incomplete verification, or any worker error blocks
success. No fallback silently substitutes another flavor for an exact request.

`verification_contract: neon_fp32_fma_v1` persists operation family, reference
method/version, rounding environment, implementation, arithmetic block counts,
and per-thread affinity / FPCR / phase / mismatch details. Raw worker evidence
is retained in parsed and compatibility `WorkerResults`; historical workers
keep their old contracts. A pass describes verified execution, not sustained
thermal or highest-power behavior.

The legacy-export filter treats a CPU record declaring `neon_fp32_fma_v1` as
an indivisible versioned evidence boundary. It copies the entire record,
including per-thread CPU mappings, affinity, reference method, FPCR, and failure
details, without filtering children or repairing missing/incorrect evidence.
Unversioned and other historical workers retain the established projection.
The verification checker still rejects incomplete or contradictory records;
declaring the contract does not establish success.

## Validation boundary

### Timestamped verified-work evidence

New workers also write `<result-file>.progress.jsonl`, independently of final
results, using the `neon_fp32_fma_progress_v1` contract. One writer flushes and
fsyncs newline-terminated startup, initial, approximately two-second ongoing,
interrupted, and final snapshots. An incomplete last line is not a snapshot.
Creation is exclusive: an old sidecar cannot silently acquire a new run.
Memory use is O(threads), independent of duration; disk use grows with threads
and duration. Persistence failures are explicit, not silently dropped records.

Counters increase only after all accumulator lanes, witnesses, and affinity
checks pass. Workers publish coherent copies under a short mutex at coarse
block boundaries, normally no more often than every 0.25 seconds, plus initial,
final, and error boundaries. Clock-check spacing adapts to block latency;
the vector hot loop has no progress I/O or synchronization. The single writer
copies slots under the mutex and performs I/O after unlocking. The final result
records snapshot count and writer elapsed time (including fsync); this is not
total verification or instrumentation overhead. Very slow blocks/publications
remain observable as gaps, not assumed work. First mismatch evidence is retained.

Native CLOCK_MONOTONIC, stage boundaries, and raw telemetry use the same Linux
boot clock. Each snapshot also pairs realtime with monotonic and records the
pair's uncertainty. UTC jumps do not change monotonic rates. Do not compare
unrelated boots using monotonic values.

The final artifact writer adds `verified_progress_analysis` inside the versioned
worker record. It streams the sidecar in O(threads) memory. It derives per-thread
rates only between actual publication endpoints both inside the trimmed window;
no boundary interpolation or configured-cadence multiplication is used. It
reports per-thread deltas, observed seconds, coverage, rates, first/second-half
rates, interval min/max, and summed independently timed rates. Publication
endpoints can differ between threads; aggregate interval rates disclose this.
Derived lane FMA work is 8192 stress lane operations plus four witness lane
operations per verified block, not a measurement of emitted instructions.

Missing/stale publications, sequence gaps, regressions, bad totals, incomplete
phases, failed affinity, mismatches, absent final evidence, and unclean exits
prevent sufficient progress evidence. Progress gaps over three two-second
intervals are not bridged. At least two observed intervals per thread and 80%
post-trim coverage are required, alongside the authored duration and existing
stage telemetry-quality policy. Rate variation is descriptive, without a minimum
throughput or stability target. Native integrity and stage safety remain separate
and authoritative; partial progress never excuses a crash or proves saturation.
Historical results without this contract are not retrospectively reassessed.

The archived sustained profile is CPU-only, 600 seconds with 60+60 trims and an authored
480-second usable-duration requirement. Review the progress quality and raw
sidecar alongside telemetry and clean all-thread verification, not merely the
stage PASS. Both validated profiles are retained unchanged in
`profiles/Archived/2026 Hardware Validation/07 ARM64 NEON FP32 FMA Acceptance/`:
`ARM64 NEON FP32 FMA Functional Confirmation.json` and
`ARM64 NEON FP32 FMA Sustained Effectiveness.json`. Neither is an active profile.

### Physical and machine-code acceptance

The integer-emulation test build is explicitly marked `test_integer_emulation`.
It tests reference, lifecycle, and rejection behavior, not NEON execution.
For future hardware acceptance, compile optimized on AArch64, inspect disassembly
of `execute_fp32_fma_block` for vector `.4s` fused FP instructions in the hot
loop (not just scalar FMA elsewhere), and execute through normal LVS on available
ARM hardware. Confirm every targeted thread's exact contract, clean termination,
ISA provenance, and safety monitoring. Functional ISA confirmation is separate
from sustained effectiveness/thermal characterization. Spark and Snapdragon
coverage is desirable when available; neither is inferred from local fixtures.

### Completed October 19, 2026 physical acceptance

The 120-second functional and 600-second sustained profiles passed on NVIDIA
GB10 Spark (HP ZGX Nano G1n AI Station) and Snapdragon Oryon (HP OmniBook X
Laptop 14-fe1xxx). This is acceptance of verified execution and sustained
verified-compute effectiveness, not maximum FP32 execution-unit saturation.

The sustained execution evidence is retained locally and ignored:

- Snapdragon: `results/2026-10-19_14-11-44_ARM64 NEON FP32 FMA Sustained Effectiveness`
  with its matching `_Diagnostics` directory.
- Spark: `results/2026-10-19_14-28-06_ARM64 NEON FP32 FMA Sustained Effectiveness`,
  paired with `results/2026-10-19_14-28-05_ARM64 NEON FP32 FMA Sustained Effectiveness_Diagnostics`.

| Observed evidence | Spark | Snapdragon |
| --- | ---: | ---: |
| Verified / targeted threads | 20 / 20 | 8 / 8 |
| Actual stage duration (seconds) | 601.065008 | 600.665426 |
| Actual post-trim interval (seconds) | 481.065008 | 480.665426 |
| Normalized telemetry samples | 217 | 233 |
| Progress snapshots | 301 | 302 |
| Full-worker verified blocks | 9,138,641,794 | 7,587,914,259 |
| Trimmed verified blocks/second | 15,205,646.331204 | 12,639,412.657860 |
| First-half verified blocks/second | 15,205,726.242485 | 12,640,202.169919 |
| Second-half verified blocks/second | 15,205,576.210656 | 12,638,536.772180 |
| Arithmetic errors | 0 | 0 |
| Process exit code | 0 | 0 |

Every targeted thread completed initial, periodic, and final verification with
correct affinity, FPCR zero, no mismatch, and clean shutdown. Interrupted blocks
(14 Spark, 6 Snapdragon) were excluded from verified totals. Timestamped
post-trim progress quality was sufficient, with no counter regressions, stalled
threads, truncated records, or persistence failures. Stable rates were established
from actual counter deltas, not whole-run totals divided by elapsed time.
Manifest, parsed, extended, compatibility, and normal report rendering retained
the versioned evidence consistently. No warning/error safety events were recorded.

Supplied optimized AArch64 binaries were inspected with LLVM 22.1's AArch64
disassembler. Both have live calls from `worker_main` through
`run_neon_fp32_fma_loop` to `execute_fp32_fma_block`. Both hot loops contain eight
vector `.4s` FMLAs per round, a 256-round bound, eight independent accumulator
recurrences, and retained output stores: 2,048 vector FMLA instructions per
completed stress block, independently of the witnesses. No scalarization or
inner-loop accumulator spilling was found. GCC 15 emits additional register
copies relative to GCC 13; this is not a correctness failure or a claim of
optimal instruction throughput.

| Supplied local binary | Embedded compiler | SHA-256 |
| --- | --- | --- |
| `results/cpu_stress_helper_arm64` | Ubuntu GCC 15.2.0 | `b31ccf9a7f279a07b88efb61d8b41f4b3f21f3bacfae096d0f2906550dd5982d` |
| `results/cpu_stress_helper_arm64 (Copy)` | Ubuntu GCC 13.3.0 | `c2031f3beee651d15043a79cc39acbc56dca0877c08bcf810bebae7a5738c9c4` |

Compiler metadata, copy provenance, and timestamps strongly associate the GCC 15
binary with Snapdragon and GCC 13 with Spark. Exact historical executable
identity was **not cryptographically established**: no execution-time binary
hash links these bytes to the October 19 processes. Semantic correspondence with
the intended source and instruction emission are confirmed; this is not proof
of a byte-identical source rebuild or a retrospective association with earlier
functional executions. The stale August helper was excluded from acceptance.

Platform-dependent limits remain explicit: Spark exposes platform-zone rather
than CPU-specific temperature, and no CPU power; Snapdragon exposes CPU-subsystem
temperature, but no CPU clocks or power in these runs. CPU throttling indicators
were unavailable. Progress-writer elapsed time includes persistence waiting, not
total verification overhead or measured compute-throughput loss. Neither 100%
CPU utilization, FMLA presence, nor stable verified rates proves maximum pipeline
saturation. No universal performance, power, or thermal threshold was established.

### Reproducible ARM instruction capture

On an AArch64 Linux system, from the updated LVS project root, the following
uses the exact normal helper build recipe from
`Modules/lvs_native_helpers.py:native_helper_build_command`. It rebuilds only
the normal helper, not a test harness, and does not execute a workload:

```bash
set -eu
test "$(uname -m)" = aarch64
mkdir -p build
(
  set -x
  date -u
  uname -a
  git rev-parse HEAD
  git status --short
  gcc --version
  gcc -dumpmachine
  sha256sum native/cpu_stress_helper.c
  gcc -O3 -std=c11 -pthread native/cpu_stress_helper.c -o build/cpu_stress_helper_arm64
  sha256sum build/cpu_stress_helper_arm64
  readelf -h build/cpu_stress_helper_arm64
  readelf -n build/cpu_stress_helper_arm64
  readelf -p .comment build/cpu_stress_helper_arm64
  nm -an build/cpu_stress_helper_arm64
  objdump -d build/cpu_stress_helper_arm64
) > build/neon_fp32_fma_instruction_evidence.txt 2>&1
```

This requires the native compiler and ARM-capable binutils (`readelf`, `nm`,
`objdump`). If the normal compiler is `cc` rather than `gcc`, use that same
compiler consistently for the version, target, and build commands. Do not add
global ISA flags or use a stale/different binary to fill an evidence gap.

Inspect the `execute_fp32_fma_block` symbol and any compiler-generated clones
in the full disassembly. Establish the eight vector FP32 fused chains in the
retained loop, its back edge and round bound; finding one `fmla` elsewhere
(such as the witnesses) is not sufficient. Record the actual instruction
sequence, not a source-intrinsic inference. Preserve the binary and evidence
file together. For association with a future normal LVS run, record its SHA-256
immediately before and after that run and ensure no rebuild/replacement occurs.
These commands cannot establish which binary was used in an earlier run that
did not capture an associated hash or binary.
