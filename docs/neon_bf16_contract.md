# Explicit NEON BF16 verified workload

`neon_bf16` is uncommitted post-FP16/FHM development, experimental and explicit-only.
It is not part of published v0.5.3-alpha. Auto, generic vector intents and measured
Power Auto are unchanged. Software validation does not establish physical acceptance.
**Gate A arithmetic/integrity and Gate B sustained verified stress are PASS
independently on NVIDIA GB10 Spark and Qualcomm Snapdragon X1 Plus**, within the
tested hardware, compilers, FPCR=0 and finite numerical domain recorded below.

## Instructions and work

The isolated `execute_neon_bf16_block` in
[`native/cpu_bf16_kernel.h`](../native/cpu_bf16_kernel.h) executes eight independent
128-bit FP32 accumulator chains, each with four result lanes:

| Chains | Advanced SIMD instruction | Operand mapping |
|---|---|---|
| 0–1 | `BFDOT Vd.4S, Vn.8H, Vm.8H` | two adjacent BF16 products per FP32 lane |
| 2–3 | `BFMMLA Vd.4S, Vn.8H, Vm.8H` | A 2×4 row-major, B 4×2 packed by columns, C 2×2 row-major |
| 4, 6 | `BFMLALB Vd.4S, Vn.8H, Vm.8H` | even halfwords 0, 2, 4, 6 |
| 5, 7 | `BFMLALT Vd.4S, Vn.8H, Vm.8H` | odd halfwords 1, 3, 5, 7 |

The three forms exercise adjacent dot products, matrix reduction and alternating
widening fused accumulation, rather than conversion-only or ordinary FP32 work.
A block performs 256 recurrence rounds, then a separately checked one-round
witness using the same kernel. All 32 lanes and both output guards must pass
before that block receives credit. This represents 16,384 stress BF16 products
and 64 witness products; these are derived counts, not measured instruction
retirement or directly comparable stress effectiveness across ISA families.

The assembly uses early-clobber read/write accumulators, independent input vectors,
condition-code/memory clobbers, bounded cancellation checks every 32 rounds, and
complete result stores. Compiler register allocation and equivalent control-flow
transformations are allowed; tests trace effective chain updates and stores.
Conversion, indexed, subtract and other BF16 variants are not separate workloads:
the selected three arithmetic forms already provide the adopted distinct behavior.
Enhanced BF16 arithmetic is outside this first finite contract.

## Architectural arithmetic and independent reference

BF16 is not binary16. It has eight exponent and seven stored fraction bits.
Standard `BFDOT` uses separately rounded products, their sum, then accumulation;
`BFMMLA` applies two such adjacent dot-pair accumulations per output lane.
These standard operations use round-to-odd and mandatory input/output denormal
flushing. In contrast, BFMLALB/T perform fused FP32 accumulation under FPCR controls.
Arm's [BF16 overview](https://developer.arm.com/community/arm-community-blogs/b/ai-blog/posts/bfloat16-processing-for-neural-networks-on-armv8_2d00_a)
and [intrinsic mappings](https://arm-software.github.io/acle/neon_intrinsics/advsimd.html)
identify these distinct arithmetic families.

FEAT_EBF16 is separate from basic BF16. With FPCR.EBF=1, dot/matrix pair products
and their pair sum are fused, followed by a separate accumulation, with FPCR
rounding/denormal controls. The implementation intentionally accepts **EBF=0 only**;
it records enhanced capability and rejects EBF=1 without modifying FPCR. The
[QEMU Arm implementation](https://github.com/qemu/qemu/blob/master/target/arm/tcg/vec_helper.c)
provides an independently inspectable cross-check of pair sequencing, alternating
widening indices and enhanced-mode behavior. Emulation is not physical acceptance.

The C reference uses checked signed dyadic arithmetic: ten 64-bit magnitude limbs
in units of 2^-300, exact integer significand products and signed addition/subtraction,
followed by explicit binary32 rounding. This covers every finite BF16 product plus
any finite FP32 addend without truncating large exponent gaps. Standard dot/matrix
rounding truncates and jams the low significand bit on inexact results, flushing
subnormals at each architectural operation. Widening uses one round-to-nearest,
ties-to-even after the exact product-plus-addend, with gradual underflow. No host
floating-point operation or tolerance supplies expected answers.

Four seed-varying finite cases cover signs, matrix/alternating mappings, normal
boundaries, signed zero, BF16 and FP32 subnormals, cancellation and rounding.
Dedicated one-round witnesses distinguish:

- RTO from RN: `1 + 2^-25` produces FP32 bits `0x3f800001` for standard dot,
  whereas RN produces `0x3f800000`.
- Standard dot's flushed `2^-150` products from gradual widening arithmetic.
- Fused widening: `2^-150 + 2^-149` rounds to `0x00000002`; a separately rounded
  product followed by addition incorrectly gives `0x00000001`.

References independently calculate every recurrence round and lane before stress.
Nonfinite operands, finite-domain overflow or an unrepresentable reference state
fail closed. This is a bounded stability workload, not exhaustive IEEE conformance
or NaN-payload testing. Software corruption injection covers each chain, periodic,
final, witness and guard errors; no physical corruption injection is claimed.

## Capability, FPCR, affinity and lifecycle

Every selected CPU must pass pinned native readiness and execution affinity.
Required Linux capabilities are HWCAP FP + ASIMD and **HWCAP2_BF16 (bit 14)**.
SVE BF16 is neither required nor a substitute. **HWCAP2_EBF16 (bit 32)** is recorded
separately; it does not imply EBF=1. See the
[Linux HWCAP definitions](https://github.com/torvalds/linux/blob/master/arch/arm64/include/uapi/asm/hwcap.h).

FPCR must select RN-even, EBF=0, FZ/FZ16=0, AHP=0, AH/FIZ=0 and disabled exception
traps. DN is harmless for this finite domain. FPCR is checked before and after
each credited block and never changed by LVS. Standard dot/matrix still flush
subnormals intrinsically even when FPCR.FZ=0. Supported widening retains gradual
underflow. A changed or incompatible mode blocks verification.

The target-specific function is independently optional (`LVS_CPU_HELPER_ENABLE_BF16`)
with per-function targeting and a local assembler directive, never global `-march`.
Baseline compilation excludes BF16 instructions. Compiler failure retains other
optional kernels through bounded salvage, at most 24 attempts over existing SVE
tiers, rather than dropping previously usable scalar/NEON paths.

Memory is bounded per thread (four 512-byte cases and a 136-byte output buffer,
plus bounded reference temporaries). Threads and CPU targets follow existing
allowed-set/resource policies; there is no hardware-model exception or fixed
thread-count assumption. Regression fixtures cover one/sparse/256 targets,
heterogeneous missing capability and absent optional compilation.

Initial, periodic and final checks, verified/interrupted counters, pinned CPU,
HWCAP/HWCAP2, FPCR, executable identity and progress are preserved by the established
native lifecycle. Interrupted partial arithmetic earns no credit; normal shutdown
requires a fully checked final block. Mismatch, guard, capability, affinity, FPCR,
persistence or lifecycle failure cannot become successful verification.

## Output and software evidence

`neon_bf16_v1` records `integer_dyadic_rto_ftz_and_rne_fused_reference`, comparison
`bit_exact`, operation family `bf16_standard_dot_matrix_and_fused_widening`,
`bf16_mode=standard_ebf0`, eight chains (two of each instruction), 256 stress rounds,
one witness round and four FP32 lanes per chain. Native implementation is
`aarch64_neon_bf16_asm`, actual ISA `asimdbf16`. `test_bf16_emulation` is labelled
software-only and never establishes real instruction execution.

`neon_bf16_progress_v1` uses the existing timestamped per-thread progress contract.
Reports require reconciled terminal counters and all-thread verification. Derived
BF16 product rates are not measured instructions, CPU saturation or package power.
Compatibility exports preserve complete failed/incomplete worker evidence.
Readiness records `bf16_build_status` separately from runtime availability and
source/executable identities.

The focused tests independently use rational arithmetic, exhaustive matrix-placement
bases, signed/boundary/random values, subnormal and rounding witnesses, substantive
emitted data/control-flow interpretation, actual ELF instruction disassembly,
compiler salvage, corruption/cancellation, frontend planning, reporting and progress.
Software validation passes **352/352 smoke tests** and **81/81 profiles** (five
unchanged advisories), all **378 Python files** compile, and **19 integration
imports** pass. Six BF16 groups and existing specialized ISA/selector regressions
pass. AArch64 baseline, BF16-only and combined optional-feature assembly/object
compilation pass, with actual BF16 object instruction disassembly and effective
recurrence/data-flow checks. The complete **369-file** execution-source fingerprint is
`6700ba394f55de32c7ef84a61d5eaf6df05247e1707ecf736b7e07c3ecacd79a`.
All four accepted physical executions recorded this complete fingerprint at both
endpoints, with `source_changed_during_run=false`. It also matches the current
scoped production source. These acceptance-documentation changes are outside
`lvs_execution_source_v1` and do not change that identity. Earlier FP16/FHM
capability captures were not BF16 acceptance; the executions below independently
establish current-build BF16 execution on each platform.

## Completed physical acceptance

Both gates PASS independently for each platform. Durations here are native-process
execution times, not parent-run elapsed times or trimmed analysis windows.

| Tested platform | Allowed / pinned CPUs | Functional seconds / verified blocks | Sustained seconds / verified blocks | Gate A | Gate B |
|---|---|---|---|---|---|
| NVIDIA GB10 Spark, HP ZGX Nano G1n AI Station | 20/20, CPUs 0–19 | 120.189 / 6,533,938,633 | 600.989 / 32,669,799,505 | PASS | PASS |
| Qualcomm Snapdragon X1 Plus, HP OmniBook X | 8/8, CPUs 0–7 | 121.219 / 1,412,988,998 | 600.717 / 7,117,306,219 | PASS | PASS |

Actual executed AArch64 ELF helpers confirm two independent BFDOT chains, two
BFMMLA chains, two BFMLALB chains and two BFMLALT chains. Disassembly and effective
control/data-flow tracing confirm the 256-round recurrence, correct operand and
accumulator mappings, all 32 FP32 result stores, cancellation/final paths and
separate native calls with 256 and one round. This is instruction execution in
the physical workers, not merely compiler fixtures or labelled emulation.

Every selected CPU passed pinned capability and affinity checks. Spark records
HWCAP `0xefffffff`, HWCAP2 `0x801af3ff`; Snapdragon records HWCAP `0xffbfffff`,
HWCAP2 `0x3b6181`. Target-local optional BF16 compilation succeeded on both.
Every physical worker recorded **FPCR=0** and **enhanced BF16 unavailable**.
This confirms the supported standard EBF=0 configuration independently of SVE
capability. No enhanced-mode physical acceptance is claimed.

Both platforms completed bit-exact independent signed/finite BF16 arithmetic,
including standard dot/matrix intermediate RTO/flush behavior and fused widening
FP32 RN-even/gradual-underflow witnesses. Initial, periodic and final checks all
completed, with zero arithmetic mismatches or guard failures. Verified block credit
requires all 32 lanes and both output guards in both the stress and mandatory
one-round checks; raw individual lane values are not continuously exported.
No deliberate physical corruption injection is claimed.

The retained helpers match their respective **prelaunch, running-process and
post-execution SHA-256 identities in both runs**:

| Platform | Compiler | Retained matching executed helper | SHA-256 |
|---|---|---|---|
| Spark | GCC 13.3.0 | `results/cpu_stress_helper_spark_arm64` | `a3d70617fe4dd76fa1acb5a4b525f68687dee6bc1d154020ab2d9ab8cf7dd486` |
| Snapdragon | GCC 15.2.0 | `results/cpu_stress_helper_snapdragon_arm64` | `4488337d574d524e8eea0e15086644353771ac38c8c321b0b5120c8cc6c95ac6` |

Local physical evidence, all under `results/`, deliberately excluded from the
development commit. These are local evidence references, not distributed assets:

| Platform / test | Execution | Matching original-template diagnostic capture |
|---|---|---|
| Spark functional | `2026-11-03_14-21-24_ARM64 SVE FP32 FMA Functional Confirmation` | `2026-11-03_14-21-19_ARM64 SVE FP32 FMA Functional Confirmation_Diagnostics` |
| Spark sustained | `2026-11-03_14-23-38_ARM64 SVE FP32 FMA Sustained Effectiveness` | `2026-11-03_14-23-31_ARM64 SVE FP32 FMA Sustained Effectiveness_Diagnostics` |
| Snapdragon functional | `2026-11-03_14-20-39_ARM64 SVE FP32 FMA Functional Confirmation` | `2026-11-03_14-20-34_ARM64 SVE FP32 FMA Functional Confirmation_Diagnostics` |
| Snapdragon sustained | `2026-11-03_14-22-55_ARM64 SVE FP32 FMA Sustained Effectiveness` | `2026-11-03_14-22-47_ARM64 SVE FP32 FMA Sustained Effectiveness_Diagnostics` |

Profile titles and diagnostic captures retain the original SVE FP32/FMA template.
Snapdragon's original-template diagnostics correctly reject unsupported SVE.
Actual effective profiles, overridden readiness, executed commands, worker records
and Advanced Debug stage evidence consistently identify `neon_bf16`, with no
fallback. The Snapdragon physical evidence was independently inspected.

| Sustained measurement | Spark | Snapdragon |
|---|---|---|
| Usable post-trim analysis window | 481.024 s | 480.729 s |
| Verified blocks/s | 54.360 million | 11.848 million |
| Per-thread verified blocks/s | 2.004–3.423 million | 1.472–1.487 million |
| Per-thread progress coverage | 99.506–99.572% | 99.587–99.639% |
| First-half to second-half rate change | +0.008% | +0.013% |
| Recorded progress stalls | 0 | 0 |
| Sustained thermal peak | 73.8 C, platform thermal zones | 70.2 C, CPU-subsystem maximum |

Progress analysis independently recomputed from timestamped sidecars matches the
persisted analyses and final counters. Sustained records contain 301/302 snapshots
for Spark/Snapdragon, with maximum publication gaps approximately 2.196/2.188 s.
Per-thread rates differ on Spark's heterogeneous CPU; no thread stalled. Both
platforms demonstrate stable, continuous independently verified computation, not
directly comparable arithmetic throughput or maximum power.

All four native processes exited **0** after normal termination requests, complete
final verification and normal native-worker cleanup. Parents finalized completed
PASS results. No shutdown timeout, SIGKILL, arithmetic/lifecycle failure or safety
intervention occurred. Partial blocks interrupted during normal shutdown received
no verified credit. Worker JSON, manifests, progress, summaries and compatibility
exports preserve consistent evidence. CPU-only runtime memory guards were disabled
as designed; their records show no trigger.

CPU package power is unavailable on both platforms. Spark lacks CPU-specific
temperature and independent effective-clock measurements; reported cpufreq values
are 2,808/3,900 MHz, aggregate 3,354 MHz. Snapdragon clocks are unavailable.
`dmesg` access was denied and filtered kernel journals were empty on both systems;
this limits kernel-event visibility and is not proof of no kernel errors.
Acceptance is restricted to these tested EBF=0 hardware/compiler/numerical-domain
configurations. It does not establish universal support, maximum-power effectiveness
or superiority over other kernels. No additional physical test or production
correction is required to close this milestone.

## Reproduction procedure and gate criteria

These procedures remain available for reproduction and new configurations; they
are not outstanding requirements for the two accepted targets.

Deploy the actual working project directory to Spark first. Use the normal TUI;
no saved profile editing, duplicate profile or separate manual Dry Run is needed.

| Existing profile | Only run-setup changes |
|---|---|
| ARM64 SVE FP32 FMA Functional Confirmation | Stage Overrides → Configure Stage Workloads (this run only) → CPU Instruction Set: `neon_bf16`; Advanced Debug: ON |
| ARM64 SVE FP32 FMA Sustained Effectiveness | Same two settings |

Retain template defaults: native CPU, all allowed CPUs (expected 20 on the tested
Spark environment), empty instruction intent, Power Auto off, extreme/steady,
CPU only, 120/600 seconds, existing trims, guards and shutdown policy. Review must
show actual `neon_bf16`; automatic overridden readiness must admit every selected
CPU and the native kernel. Original SVE-template diagnostics do not establish the
effective request. Retain execution and matching diagnostics in full.

**Gate A — integrity:** functional execution, genuine four instruction forms in the
actual helper, all-target eligibility/affinity, recorded supported FPCR, independent
bit-exact initial/periodic/final verification and witness checks, zero mismatches,
verified progress, matching prelaunch/process/post-execution helper hashes,
unchanged source endpoints, successful worker exit and parent finalization.

**Gate B — sustained verified stress:** complete 600-second execution and usable
trimmed window, reconciled per-thread continuous verified progress, throughput and
stall analysis, lifecycle/safety evidence and available thermal/frequency/power/kernel
observations. Record unavailable telemetry explicitly. Neither highest wattage nor
superiority to FP16/FHM/SVE is required or inferred.

After Spark gates pass, repeat the same current-build capability check and two
profiles on Snapdragon (expected eight allowed CPUs in the tested environment).
If BF16 is missing or cannot compile, retain the explicit unsupported preflight
rejection with no BF16 worker or silent fallback; do not claim BF16 physical PASS.
If FPCR is incompatible, retain the failure and investigate without changing
system FP settings to force acceptance.

On each target preserve `build/cpu_stress_helper_arm64` immediately after execution,
with a distinct platform filename outside active build discovery, and record SHA-256.
Match it to the result's prelaunch/running-process/post-execution identities; retain
compiler/build records and disassemble `execute_neon_bf16_block`. Do not substitute
a helper rebuilt later. Return both runs, diagnostics and the matching helper.
Stop on arithmetic, capability, affinity, FPCR, progress, safety or lifecycle failure;
retain partial evidence and do not loop through repeated failing physical runs.
Acceptance is limited to actually tested hardware/compiler/mode/domain configurations.
