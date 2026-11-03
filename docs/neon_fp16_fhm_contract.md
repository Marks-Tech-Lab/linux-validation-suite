# Explicit NEON FP16 and FHM verified workloads

Uncommitted post-I8MM development adds two experimental, explicit-only tokens:
`neon_fp16` and `neon_fhm`. Neither is part of published v0.5.3-alpha. Ordinary
Auto, generic vector intents and measured Power Auto remain unchanged. Physical
Gate A and Gate B are **PASS independently for both kernels on both tested targets**,
as recorded below. Acceptance is limited to these hardware, compiler, FPCR and
numerical-domain configurations.
Software compilation, instruction emission and labelled emulation are not physical
acceptance or proof of stress effectiveness.

## Instructions and bounded work

`native/cpu_half_kernel.h`, included by the existing native CPU worker, defines:

| Token | Genuine instructions | Independent accumulators | Verified lanes |
|---|---|---|---|
| `neon_fp16` | vector `FMLA Vd.8H, Vn.8H, Vm.8H` | eight 128-bit FP16 chains | 64 binary16 results |
| `neon_fhm` | four `FMLAL` and four `FMLAL2`, `Vd.4S, Vn.4H, Vm.4H` | four low/high pairs, eight FP32 chains | 32 binary32 results |

FHM's `FMLAL2` selects source halfwords 4–7 even though its assembly operands are
spelled `.4H`; `FMLAL` selects halfwords 0–3. Each pair shares one complete
128-bit input vector and has separate accumulators. FP16 pairs share coefficients
but have independent accumulators, each using all eight halfwords. This is real
fused arithmetic, not conversion-only execution, ordinary FP32 multiplication,
DotProd, I8MM, SVE, or a mixed-precision label applied to another workload.
FMLSL variants are not required or implemented in this first milestone.

Each stress block performs **256 dependent accumulation rounds** on all eight
chains, followed by an independently checked **one-round witness** on the same
kernel. This means 16,384 stress lane-FMAs plus 64 witness lane-FMAs for FP16;
8,192 plus 32 for FHM. Derived counts are not measured retired instructions,
CPU saturation, maximum power or superiority over another workload.

The isolated target functions use explicit volatile assembly with early-clobber
read/write accumulator constraints, separate scalar temporaries, condition-code
and memory clobbers. The compiler can allocate/copy registers without collapsing
chains or replacing fused work. Optional function target attributes and local
assembler feature directives permit the intended instructions; no global compiler
`-march` is used. Output widening for FP16 is integer bit-pattern widening, not
FP32 arithmetic. All output lanes and guard words are checked.

## Independent numerical contract

`half_fma_reference` decodes finite IEEE binary16 inputs and the binary16/32
accumulator into signed integer significands and binary exponents. It forms the
exact product and exact sum in checked 128-bit integer arithmetic, then performs
one round-to-nearest, ties-to-even rounding to the destination precision. There
is no native FP16/FHM operation, host floating-point rounding, or tolerance in
the reference. Every successful hardware result must match its exact bits.

Four deterministic seed-varying cases exercise positive/negative values, normal
and subnormal half inputs, both FHM half mappings, rounding and cancellation.
Repeated additions remain finite and bounded; expectations are prepared before
stress, independently for every result lane and every recurrence round. The
one-round witness includes `(1+2^-10)^2 - (1+2^-9) = 2^-20`: FP16 multiplication
rounded before addition would incorrectly produce zero. FHM witnesses also
reject prematurely rounded binary16 products. A block receives verified credit
only after both the 256-round stress and the one-round witness pass completely.

The finite reference domain is explicit: exponent alignment must fit its checked
125-bit operands; NaN/Infinity, alignment outside that domain, or an overflowing
result is rejected rather than approximated. Every generated case must pass
reference preparation. This is not an exhaustive IEEE instruction-conformance
suite: arbitrary FP32 exponent gaps, NaN payloads, infinity arithmetic, every
rounding mode and FP exception behavior are outside this workload contract.
Software rational-arithmetic tests additionally cover finite extremes, signed
zero, ties, subnormal results and zero-product FP32 subnormal accumulators.

Each thread records FPCR and requires RN-even, no FZ/FZ16, no AHP, no enabled
exception traps, and no alternative AH/FIZ input behavior. The worker checks FPCR
again before and after blocks, fails closed on incompatible/changed control
state, and never silently changes it. DN does not affect this finite-input
contract; ordinary sticky FPSR exception flags, including inexact, are allowed.
A missing sensor or a clear arithmetic mismatch cannot be replaced by a tolerance.

## Separate capability and compilation requirements

Linux AArch64 HWCAP is authoritative, after binding each selected allowed CPU:

- `neon_fp16`: FP + ASIMD (bits 0/1) and **ASIMDHP (bit 10)**, plus successful
  optional FP16 compilation. It uses no scalar half arithmetic requiring FPHP.
- `neon_fhm`: FP + ASIMD and **ASIMDFHM (bit 23)**, plus successful optional FHM
  compilation. It does not infer this capability from ASIMDHP, DotProd, SVE,
  I8MM, a compiler flag or a processor name. Its emitted code requires FHM;
  there is no ordinary vector FP16 arithmetic substituted for FMLAL/FMLAL2.

Both remain separately compiled/available in the native capability JSON. GCC
uses isolated `+fp16` / `+fp16fml` targets; Clang uses `fullfp16` / `fp16fml`.
The bounded helper build tries all four optional NEON regions together first.
If needed, it establishes the existing SVE-tier baseline and adds DotProd, I8MM,
FP16 and FHM incrementally, preserving earlier supported regions when a later
one fails. A final rebuild restores the selected combination after a failed
attempt. Maximum: seven builds per existing SVE2/SVE/baseline tier, 21 total;
normal fully supported compilation takes one build. Header changes invalidate
readiness. Missing optional compilation retains scalar/NEON and existing
supported optional kernels, including on non-SVE Snapdragon systems.

Pinned all-target eligibility and per-thread affinity use the existing CPU
selection infrastructure. Cancellation is checked every 32 rounds. Interrupted
blocks receive no verified credit; after initialization a normal stop completes
one final bounded stress/witness block. Capability/environment failures, affinity
loss, corruption, progress publication errors or unsuccessful lifecycle cannot
be overwritten by a successful arithmetic snapshot.

Scalability review: four fixed 1-KiB cases plus a guarded 264-byte result buffer
per thread are independent of installed RAM, SVE width and CPU model. Concurrency
comes from the allowed CPU set and common capability, including sparse and
heterogeneous sets. Software fixtures cover one CPU, two workers, sparse sets,
256 targets, missing capabilities, and all 16 optional-NEON compiler combinations.
No GPU guard, memory reserve, allocation target or concurrency policy changes.

Architectural references:
[Linux arm64 HWCAP definitions](https://github.com/torvalds/linux/blob/master/arch/arm64/include/uapi/asm/hwcap.h),
[Linux HWCAP contract](https://www.kernel.org/doc/html/next/arch/arm64/elf_hwcaps.html),
and [Arm ACLE NEON instruction mappings](https://arm-software.github.io/acle/neon_intrinsics/advsimd.html).

## Progress, reporting and software evidence

- Contracts: `neon_fp16_v1` / `neon_fhm_v1`; corresponding `_progress_v1` sidecars.
- Method: `integer_significand_rne_fused_reference`; comparison: `bit_exact`.
- Operations: `fp16_fused_multiply_add` /
  `fp16_product_fp32_fused_accumulate_low_high`.
- Implementations: `aarch64_neon_fp16_asm` / `aarch64_neon_fhm_asm`;
  actual ISA: `asimdhp` / `asimdfhm`.
- Eight chains, 256 stress rounds, one witness round; 8/4 active lanes,
  16-bit inputs and 16/32-bit accumulation. FHM mapping is
  `paired_low_high_halfwords`; FP16 uses `all_eight_halfwords`.
- Every thread records common HWCAP, FPCR, target/observed CPU, affinity,
  initial/periodic/final verification and verified/interrupted block counters.
- Reports distinguish requested/actual execution and software verification.
  Compatibility exports preserve complete recognized records, including failure.
  Captured helper readiness retains independent `fp16_build_status` and
  `fhm_build_status`, separately from runtime eligibility and binary identity.

Labelled `test_half_emulation` exercises lifecycle/verifier paths in software
only. Python Fraction references independently check the C integer reference and
all generated cases. Deliberate one-bit corruption tests cover every accumulator
chain, phase/witness/guard failures, cancellation, environment/capability loss,
affinity, partial thread startup and terminal reconciliation. Emission tests
cross-compile the full native translation unit, trace effective recurrence,
source/accumulator identity, low/high mapping and output stores, and reject
incorrect emissions. They support ordinary/peeled compiler control flow and GNU
numeric labels; fixed static opcode counts are not the acceptance criterion.

**Software checkpoint:** six focused FP16/FHM checks and existing
DotProd/I8MM/SVE/SVE2/VNNI/instruction-ordering regressions; complete suite
**346/346 PASS**, **81/81 profiles valid** (25 active, 56 archived; five unchanged
advisories), Python compilation/imports, host baseline/emulation and AArch64
baseline/feature-enabled object compilation, output contracts and diff checks.

Complete development source fingerprint (`lvs_execution_source_v1`, 368 files):

```text
d7fdd746fd5befb1ffe2b5e2a99331dbac82a2dbaaa9088d19acb0067e49fb4c
```

All eight physical executions recorded this complete source fingerprint, with
unchanged initial/final endpoints. It also matches the current scoped source,
which remains uncommitted beyond the accepted I8MM milestone. The acceptance
updates to this document and ROADMAP are outside the source fingerprint scope;
no arithmetic, execution, capability or lifecycle code changed after physical
testing. Matched target-local executable identities are recorded below.

## Physical acceptance and minimum operator procedure

**Gate A — PASS separately for FP16 and FHM on Spark and Snapdragon.** Require
current native compilation, all-target pinned capability and compatible FPCR,
genuine intended instructions in the actual executed helper, complete independent
lane/witness verification, zero mismatches, correct affinity, matched
prelaunch/process/post-execution binary hashes and unchanged source identity,
normal process exit, confirmed worker lifecycle and finalized parent results.

**Gate B — PASS separately for FP16 and FHM on both tested targets.** Require a
600-second sustained execution, sufficient usable analysis/progress coverage,
continuous reconciled all-thread verified work, no unexplained stalls and normal
lifecycle. Record available clock/temperature/power conditions and safety events.
Unavailable telemetry remains unavailable; maximum wattage, independent execution
pipelines or superiority over NEON/SVE are not requirements or inferred outcomes.

Existing independently inspected I8MM captures advertise both feature bits on
all CPUs: Spark HWCAP `0xefffffff` (20 CPUs), Snapdragon `0xffbfffff` (8 CPUs), in
`results/2026-11-03_08-59-54_ARM64 SVE FP32 FMA Sustained Effectiveness/worker_results/arm64_sve_fp32_fma_sustained_effectiveness_cpu.json`
and
`results/2026-11-03_08-58-50_ARM64 SVE FP32 FMA Sustained Effectiveness/worker_results/arm64_sve_fp32_fma_sustained_effectiveness_cpu.json`.
These earlier observations guided readiness; the independently inspected
FP16/FHM acceptance evidence follows.

### Completed physical acceptance — November 3, 2026

| Platform / workload | Functional native duration / verified blocks | Sustained native duration / verified blocks | Gate A | Gate B |
|---|---|---|---|---|
| GB10 Spark FP16, 20/20 allowed CPUs | 120.362 s / 8,133,277,285 | 600.844 s / 40,624,592,362 | PASS | PASS |
| GB10 Spark FHM, 20/20 allowed CPUs | 120.301 s / 9,543,546,155 | 600.343 s / 47,491,560,659 | PASS | PASS |
| Snapdragon X1 Plus FP16, 8/8 allowed CPUs | 121.286 s / 2,293,577,085 | 600.565 s / 11,376,472,625 | PASS | PASS |
| Snapdragon X1 Plus FHM, 8/8 allowed CPUs | 121.115 s / 2,706,391,538 | 600.412 s / 13,409,180,224 | PASS | PASS |

Each execution is independently inspected physical evidence. The effective
profiles, overridden readiness, launch commands and actual worker records agree
on native `neon_fp16` or `neon_fhm`, native backend, all allowed CPUs,
extreme/steady work and authored 120/600-second duration. The original profile
titles and standalone diagnostic captures refer to the reused SVE FP32/FMA
templates. Snapdragon's original-template SVE rejection is expected and does not
represent the executed FP16/FHM configuration.

All selected CPUs have independently appropriate FP/ASIMD plus ASIMDHP or
ASIMDFHM eligibility, successful pinned affinity, and **FPCR=0**. The eight
FP16 `FMLA .8H` chains and four `FMLAL` plus four `FMLAL2` FP32 chains execute
with the correct operand lanes, 256 stress rounds, one-round witness and complete
result stores. Bit-exact independent reference comparisons passed every
accumulator lane, witness and initial/periodic/final phase, with zero arithmetic
mismatches. Buffer guards are part of the verified path; no physical corruption
was deliberately injected, and software corruption fixtures are not physical
fault-injection evidence.

Raw progress sequences, process identities and per-thread counters reconcile
with final worker JSON, manifests, reports and compatibility exports. Every
stream ends `final_complete`; interrupted partial blocks at normal termination
receive no verified credit. All workers exited 0 and parents finalized PASS.
Normal thread completion, cleanup and terminal publication are confirmed by the
native lifecycle and successful exits; there were no timeouts, SIGKILLs, safety
interventions or abnormal terminations. CPU-only tests do not exercise GPU
memory claims or growth-guard denial branches.

Matching physical helpers are AArch64 ELF64 executables, with identical
prelaunch, running-process and post-execution SHA-256 identities within each
platform's four runs:

- Spark: GCC 13.3.0 (Ubuntu 13.3.0-6ubuntu2~24.04.1), retained locally as
  `results/cpu_stress_helper_spark_arm64`;
  `78f125b808033b1807f70aee9a656bb6084d59b2f3440a8780bbc9e82c68b1f3`.
- Snapdragon: GCC 15.2.0 (Ubuntu 15.2.0-16ubuntu1), retained locally as
  `results/cpu_stress_helper_snapdragon_arm64`;
  `23d59bf34049529b2490e8bb1e350f300f38d8bdf0609fdecf97dfb171a093de`.

Disassembly of each actual helper confirms the native instruction paths,
independent chains, source/result data flow and caller-controlled 256-round
stress/one-round witness sequence. Compiler register allocation and result-store
ordering differ legitimately. No acceptance decision relies on static mnemonic
counts alone or assumes matching hashes between independent target builds.

Execution and corresponding diagnostic folders, all under `results/`:

| Platform / workload | Execution folder | Matching diagnostic folder |
|---|---|---|
| Snapdragon FP16 functional | `2026-11-03_11-04-24_ARM64 SVE FP32 FMA Functional Confirmation` | `2026-11-03_11-04-02_ARM64 SVE FP32 FMA Functional Confirmation_Diagnostics` |
| Spark FP16 functional | `2026-11-03_11-05-23_ARM64 SVE FP32 FMA Functional Confirmation` | `2026-11-03_11-05-17_ARM64 SVE FP32 FMA Functional Confirmation_Diagnostics` |
| Snapdragon FHM functional | `2026-11-03_11-08-39_ARM64 SVE FP32 FMA Functional Confirmation` | `2026-11-03_11-08-29_ARM64 SVE FP32 FMA Functional Confirmation_Diagnostics` |
| Spark FHM functional | `2026-11-03_11-08-56_ARM64 SVE FP32 FMA Functional Confirmation` | `2026-11-03_11-08-46_ARM64 SVE FP32 FMA Functional Confirmation_Diagnostics` |
| Snapdragon FP16 sustained | `2026-11-03_11-11-56_ARM64 SVE FP32 FMA Sustained Effectiveness` | `2026-11-03_11-11-45_ARM64 SVE FP32 FMA Sustained Effectiveness_Diagnostics` |
| Spark FP16 sustained | `2026-11-03_11-12-09_ARM64 SVE FP32 FMA Sustained Effectiveness` | `2026-11-03_11-12-02_ARM64 SVE FP32 FMA Sustained Effectiveness_Diagnostics` |
| Snapdragon FHM sustained | `2026-11-03_11-22-12_ARM64 SVE FP32 FMA Sustained Effectiveness` | `2026-11-03_11-22-02_ARM64 SVE FP32 FMA Sustained Effectiveness_Diagnostics` |
| Spark FHM sustained | `2026-11-03_11-22-28_ARM64 SVE FP32 FMA Sustained Effectiveness` | `2026-11-03_11-22-21_ARM64 SVE FP32 FMA Sustained Effectiveness_Diagnostics` |

### Sustained operating conditions and boundaries

| Platform / workload | Usable sustained window | Verified blocks/s | First-half → second-half verified blocks/s | Recorded thermal peak |
|---|---|---|---|---|
| Spark FP16 | 480.879 s | 67.613 million | 67.608 → 67.618 million | 83.6 C, platform zones |
| Spark FHM | 480.369 s | 79.116 million | 79.125 → 79.107 million | 85.1 C, platform zones |
| Snapdragon FP16 | 480.577 s | 18.947 million | 18.952 → 18.942 million | 82.8 C, CPU-subsystem maximum |
| Snapdragon FHM | 480.424 s | 22.338 million | 22.338 → 22.337 million | 85.6 C, CPU-subsystem maximum |

All four sustained executions have sufficient usable analysis, continuous
all-thread verified progress, approximately 99.56–99.76% per-thread progress
coverage and **zero recorded stalls**. Spark's heterogeneous cores have different
per-thread rates; this is not missing target coverage. The first/second-half
rates sum independently timed per-thread work rates and remain stable.

Spark (HP ZGX Nano G1n, Ubuntu 24.04.5/kernel 7.0.0-1019-nvidia) reports cpufreq
values of 2,808/3,900 MHz, aggregate 3,354 MHz; these are not independent effective
clock measurements. CPU-specific temperature and package power are unavailable;
the Spark peaks above are platform-zone readings, not CPU temperatures.
Snapdragon (HP OmniBook X/Oryon, Ubuntu 26.04.1/kernel 7.0.0-38-generic) has a
CPU-subsystem temperature maximum aggregated from 20 thermal zones; CPU clocks
and package power are unavailable. Both platforms have denied `dmesg` capture
and empty filtered journal captures, limiting kernel-event visibility. Missing
measurements/logs cannot be interpreted as zero or proof of no kernel incidents.

These results accept sustained verified computation within the tested hardware,
compiler, FPCR=0 and finite numerical-domain configurations. Different block
rates are not direct arithmetic-operation equivalence: FP16 verifies 64 lanes
and FHM 32, with different accumulation precision. They do not establish maximum
power, saturation, universal hardware support or superiority of one family.

No implementation defect or additional physical-test requirement remains for
these acceptance gates. Preserve the local evidence and binaries outside the
committed development inventory.

### Reproduction procedure (acceptance complete; no repeat required)

Copy the current working project to **Spark first**, launch the normal TUI and
use the existing profiles. Only change these settings:

| Test | Existing profile | Run-local CPU Instruction Set | Other change |
|---|---|---|---|
| FP16 functional | ARM64 SVE FP32 FMA Functional Confirmation | `neon_fp16` | Advanced Debug ON |
| FP16 sustained | ARM64 SVE FP32 FMA Sustained Effectiveness | `neon_fp16` | Advanced Debug ON |
| FHM functional | ARM64 SVE FP32 FMA Functional Confirmation | `neon_fhm` | Advanced Debug ON |
| FHM sustained | ARM64 SVE FP32 FMA Sustained Effectiveness | `neon_fhm` | Advanced Debug ON |

Select the CPU stage through **Run Setup → Stage Overrides → Configure Stage
Workloads (this run only)**. Retain native backend, empty instruction intent,
Power Auto off, all allowed CPUs, extreme/steady, authored 120/600 seconds,
30/30 or 60/60 trims and two-second telemetry. No separate manual Dry Run or new
saved profile is required. Automatic prelaunch checks remain authoritative.
Evaluate each functional gate before its sustained run.

After Spark acceptance, repeat the same four selections on **Snapdragon X1 Plus**,
subject to independent current-build FP16/FHM readiness. If either feature or
compiler region is unavailable, retain an unsupported result for that family;
do not force execution or substitute a different ISA. Spark's inherited 128-bit
SVE VL does not govern these fixed-width 128-bit NEON kernels; no SVE is required.

Preserve every execution and matching Advanced Debug folder, overridden readiness,
effective profile, per-thread JSON, progress sidecar, telemetry, terminal and
parent reports. Preserve each target's actual `build/cpu_stress_helper_arm64`,
match its SHA-256 with all three executable-provenance captures, and disassemble
`execute_neon_fp16_block` / `execute_neon_fhm_block` including compiler variants.
Verify eight independent FP16 chains or four low/high FHM pairs, actual loop
coverage, correct operand/result data flow and real instruction execution.
Keep the two targets' helpers separately named and associate by hash.

Stop on conflicting/missing identity or capability, incompatible FPCR, affinity
failure, mismatch, safety intervention, unexplained exit or missing terminal
records. Original-template Advanced Debug captures may still inspect SVE; actual
run-local readiness, commands and worker records establish the selected workload.
