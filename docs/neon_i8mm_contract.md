# Explicit NEON I8MM signed, unsigned and mixed matrix arithmetic

The uncommitted post-DotProd development token is **`neon_i8mm`**. It is
experimental and explicit-only through the existing CLI/TUI CPU Instruction Set
and run-local Stage Overrides. Ordinary Auto, generic vector intents and measured
Power Auto do not select it. Published releases and accepted workload policies
are unchanged. Both physical acceptance gates PASS on NVIDIA GB10 Spark and
Qualcomm Snapdragon X1 Plus in the tested configurations below. The milestone
remains uncommitted and is not part of the published v0.5.3-alpha release.

## Real instruction and matrix contract

`execute_neon_i8mm_block` in `native/cpu_i8mm_kernel.h`, included by the native
CPU helper, executes eight independent 128-bit accumulator chains for 256
recurrence rounds: **three SMMLA, three UMMLA and two USMMLA** instructions per
round. The mixed unsigned-left/signed-right chains add operand-order/sign
coverage within the same bounded eight-chain workload. Compiler barriers retain
the dependent recurrence. This is FEAT_I8MM Advanced SIMD, not SVE I8MM or AMX.

Each source vector contains 16 bytes. The left matrix is 2×8, packed by rows;
the right matrix is 8×2, packed by columns. The four accumulator lanes represent
C00, C01, C10, C11. For row `r`, column `c` and depth `k`:

```text
lane = 2*r + c
C[lane] += sum(A[8*r + k] * B[8*c + k], k=0..7)
```

Signed/signed chains are 0–2, unsigned/unsigned chains 3–5, and unsigned/signed
chains 6–7. Each chain has distinct operands and all four results are verified.
This is not four independent four-byte DotProd groups: both rows use both
columns, and every lane consumes eight products per recurrence round.

A separate int64 scalar reference computes the full row/column sum, multiplies
by 256, adds the uint32 initial accumulator and converts to uint32. This defines
modulo-2^32 accumulation without signed C overflow. Even the largest unsigned
case (`8*255*255*256 + UINT32_MAX`) fits int64. Explicit byte decoding defines
signed values without relying on out-of-range signed C conversions. Four
seed-varying cases include -128, 127, -1, 0, 1, 255, mixed signs and accumulator
wraparound. All 32 output words and surrounding guard words are checked after
every completed block; incomplete blocks receive no verification credit.

Each block represents 65,536 byte products: 24,576 signed, 24,576 unsigned and
16,384 mixed. Counts are derived arithmetic work, not measured retired
instructions, saturation or a power claim. Four 512-byte cases plus 136-byte
guarded output use approximately 2.2 KiB of fixed data per thread.

References: [Arm ACLE matrix intrinsic mappings](https://arm-software.github.io/acle/neon_intrinsics/advsimd.html#matrix-multiply)
and the [QEMU architectural implementation](https://qemu.googlesource.com/qemu/+/refs/heads/stable-9.2/target/arm/tcg/vec_helper.c)
confirm the instruction forms and packed row/column semantics. LVS uses its own
bounded reference and test implementation.

## Capability, compilation and safety

Linux AArch64 FP/ASIMD HWCAP plus **HWCAP2_I8MM (bit 13)** and successful optional
I8MM compilation are required. DotProd, SVE, SVE2, CPU model names or compiler
support alone do not authorize I8MM. All selected allowed CPUs must pass the
native pinned capability probe. Each worker rechecks current common HWCAP/HWCAP2
after binding, records both values and verifies observed CPU affinity before
and after arithmetic. NEON is fixed-width 128-bit; no SVE VL is modified.

The ISA function uses isolated GCC `+i8mm` / Clang `i8mm` target attributes,
with no global `-march`. At each existing SVE/SVE2/baseline build tier, compilation
tries DotProd+I8MM, DotProd alone, I8MM alone, then neither. This preserves either
independent optional region when the other is unavailable. At most four attempts
per tier and twelve overall are allowed; successful builds are cached normally.
Missing optional compiler support retains baseline paths. Header changes
invalidate helper readiness. The existing SVE FP32 header uses GNU target pragmas;
Clang can fall back from that optional region while retaining I8MM/DotProd.

Runtime capability output distinguishes `i8mm_compiled` and `i8mm_available`.
Readiness records `i8mm_build`; captured executable readiness additionally carries
`i8mm_build_status`. Explicit unavailable requests fail closed without substitution.
Cancellation is checked every 32 rounds; normal termination completes one final
bounded verified block after initialization. Capability loss, affinity failure
or corruption stops verified progress and cannot be overwritten by final success.
Thread joins, parent completion, thermal safeguards and source/executable
provenance use the established infrastructure. No allocation reserve, GPU guard,
workload concurrency or accepted ISA selection policy is changed.

Scalability review: fixed small per-thread memory is independent of installed RAM
and SVE width. The allowed CPU set and common capability evidence determine
concurrency, including sparse heterogeneous sets; no model-specific assumptions
or new minimum-memory floor are used. Software fixtures cover one CPU, sparse
sets, 256 targets, a missing-capability target and compilers lacking either/both
optional regions. Physical hardware support and stress effectiveness remain
separate gates rather than inferred from these fixtures.

## Verification, progress and reporting

- `verification_contract=neon_i8mm_v1`, version 1.
- `verification_method=wide_integer_matrix_reference_modulo_2_32`.
- `operation_family=s8_s8_u8_u8_u8_s8_matrix_multiply_accumulate_2x8_8x2`.
- `execution_implementation=aarch64_neon_i8mm_intrinsics`, `actual_isa=i8mm`.
- Eight chains, four int32 lanes, eight products per lane, 256 matrix rounds;
  signed/unsigned/mixed chain counts 3/3/2.
- `matrix_layout=a_row_major_b_column_major_c_row_major`.
- All-thread HWCAP/HWCAP2, target/observed CPU, affinity and
  initial/periodic/final verification are required.
- `neon_i8mm_progress_v1` preserves the existing bounded timestamped per-thread
  progress, error/final snapshots and persistence-error evidence.

Strict integer integrity assessment reconciles all-thread verified counts,
positive phase evidence, matrix geometry and capability. Missing, contradictory,
failed or incomplete evidence prevents successful worker classification. Reports
separate selection, execution, software verification and physical acceptance;
legacy exports retain complete recognized records, including failures. Derived
byte-products/s are not measured instruction rates or a saturation verdict.
Software emulation is explicitly labelled `test_integer_emulation` and
`test_override`, never physical execution proof.

## Software validation and source identity

Focused deterministic checks cover all row/column basis combinations, signed,
unsigned and mixed extrema, modulo accumulation and each result lane, actual
SMMLA/UMMLA/USMMLA emission from the full native translation unit, baseline
compilation, capability rejection, optional compiler fallback, corruption in
each arithmetic family, initial/periodic/final verification, affinity loss,
partial thread creation, interrupted blocks, progress, CLI/TUI parity,
reporting and compatibility. Existing DotProd/SVE/SVE2/VNNI regressions remain
part of the complete software suite. Cross-emission and emulation do not close
physical acceptance.

**Combined software checkpoint:** six focused I8MM checks and the two CPU
instruction-ordering checks pass, along with existing DotProd/SVE/SVE2/VNNI
regressions. The complete suite passes **340/340 smoke tests**;
all **81/81 profiles** (25 active, 56 archived) validate with five unchanged
advisories. Compilation of 376 Python files and changed-module/CLI/TUI imports
passes. Host GCC baseline/emulation builds and AArch64 ELF64 object compilation
(baseline and I8MM+DotProd+SVE2) pass. Cross-emission confirms three signed,
three unsigned and two mixed-sign logical chains in the real function.
The emission check traces bounded control flow,
input/accumulator identities, 256 updates per chain and all output stores. It
accepts ordinary and compiler-peeled loops and rejects missing/repeated chains,
wrong iteration counts, swapped operands, wrong vector shapes and incomplete or
incorrect stores. Independent matrix-reference and corruption tests remain
authoritative for arithmetic and lane mapping.
Existing GNU-pragmas-only SVE FP32 optional compilation is not claimed supported
by Clang; the established fallback retains the available kernels.

All four physical executions recorded this complete **367-file**
`lvs_execution_source_v1` fingerprint, unchanged between initial and final capture:

```text
d553defe2f14cafc62750d5684f05e068b9a52289edb03821274b739efe9e5e7
```

The subsequent CPU instruction-selector sorting correction produced the current
complete **367-file** development fingerprint:

```text
f0496662c2ea4e69a399672c602bb4657a40a96a818f94aaf4375a0e52ef4572
```

The scoped differences are presentation/selection changes in five Python
modules. Native I8MM source, capability handling, arithmetic verification and
lifecycle are unchanged between these snapshots. The current full UI-corrected
snapshot itself was not physically executed. Markdown and software fixtures,
including the emission-test portability correction, are outside this scope and
do not change the current fingerprint. Native helpers are associated below by
recorded executable identity, not filenames or compiler version alone.

CPU instruction choices now use shared dynamic case-insensitive alphabetical
ordering, with Auto first, in CLI/TUI profile editing and run-local Stage
Overrides. Regression checks cover future catalog additions, numbered selection,
current-value highlighting, cancellation and persistence. Saved ISA tokens,
capability checks, generic Auto/vector intents and measured Power Auto policies
remain unchanged; `neon_i8mm` remains experimental and explicit-only.

Prior November 2 DotProd captures show HWCAP2_I8MM on both intended platforms:
Spark `0x801af3ff`, Snapdragon `0x3b6181`. This is actual earlier capability
evidence, not inference from model names, and does not replace current-build
compilation and pinned prelaunch checks or physical I8MM execution.

## Physical acceptance gates

**Gate A — PASS on both tested platforms.** Acceptance requires genuine I8MM
execution in the actual retained helper, current-build pinned eligibility for every selected CPU,
independent signed/unsigned/mixed arithmetic with complete initial/periodic/final
verification, zero mismatches, correct affinity, matching source and
prelaunch/process/post-execution helper identities, normal exit and complete
parent finalization. First evaluate GB10 Spark, then Snapdragon X1 Plus using
its own capability evidence. Earlier DotProd/SVE2 acceptance does not accept I8MM.

**Gate B — PASS on both tested platforms.** Acceptance requires sustained
independently verified activity, sufficient post-trim progress and telemetry coverage, no unexplained
stalls, complete lifecycle evidence and recorded operating conditions where
available. No maximum-wattage, temperature, frequency or superiority claim is
implied by ISA support, width or successful arithmetic. Missing telemetry remains
missing; physical acceptance is limited to the tested configurations.

### Completed physical acceptance — November 3, 2026

| Platform | Functional native execution | Sustained native execution | Gate A | Gate B |
|---|---|---|---|---|
| NVIDIA GB10 Spark, 20/20 allowed CPUs | 120.401 s; 11,070,382,739 verified blocks | 601.198 s; 55,275,587,404 verified blocks | PASS | PASS |
| Qualcomm Snapdragon X1 Plus, 8/8 allowed CPUs | 120.899 s; 2,161,049,164 verified blocks | 601.495 s; 10,750,441,029 verified blocks | PASS | PASS |

All four independently inspected executions used native `neon_i8mm`, with pinned
all-target HWCAP2_I8MM eligibility, successful affinity, independent signed,
unsigned and mixed-sign matrix verification, complete initial/periodic/final
checks and zero mismatches. Progress counters reconciled across per-thread
sidecars and terminal results. Native workers exited successfully, parents
finalized PASS, and reports/compatibility exports agreed. No lifecycle or safety
intervention was reported. CPU-only execution did not exercise GPU allocation
claims or memory-guard denial branches.

Evidence under `results/` (each execution includes worker JSON, progress,
effective profile, telemetry, manifest and reports):

| Platform/test | Execution folder | Matching diagnostic folder |
|---|---|---|
| Snapdragon functional | `2026-11-03_08-56-33_ARM64 SVE FP32 FMA Functional Confirmation` | `2026-11-03_08-56-21_ARM64 SVE FP32 FMA Functional Confirmation_Diagnostics` |
| Spark functional | `2026-11-03_08-57-41_ARM64 SVE FP32 FMA Functional Confirmation` | `2026-11-03_08-57-35_ARM64 SVE FP32 FMA Functional Confirmation_Diagnostics` |
| Snapdragon sustained | `2026-11-03_08-58-50_ARM64 SVE FP32 FMA Sustained Effectiveness` | `2026-11-03_08-58-45_ARM64 SVE FP32 FMA Sustained Effectiveness_Diagnostics` |
| Spark sustained | `2026-11-03_08-59-54_ARM64 SVE FP32 FMA Sustained Effectiveness` | `2026-11-03_08-59-48_ARM64 SVE FP32 FMA Sustained Effectiveness_Diagnostics` |

The original template diagnostics inspect SVE FP32/FMA; Snapdragon's template
SVE rejection is expected. Actual run-local effective configuration, overridden
readiness, launch commands and worker evidence establish I8MM execution.

**Matching physical executables:** both are AArch64 ELF helpers compiled locally,
with identical prelaunch, running-process and post-execution identities within
each platform's two runs:

- Spark: GCC 13.3.0; retained locally as `results/cpu_stress_helper_arm64`;
  SHA-256 `2d8c344bf685d2b88aa80a64c9179b56c2aa958ae4fd898230303644b4adbe22`.
- Snapdragon: GCC 15.2.0; retained locally as `results/cpu_stress_helper_arm64 (1)`;
  SHA-256 `da4c0cd8712d63db3323aaa94826467c9b0dc51d85582e282d346c37ab046b4d`.

Disassembly of the actual executed functions confirms eight independent logical
chains: three SMMLA, three UMMLA and two USMMLA, with 128-bit sources, four 32-bit
result lanes and all result stores. GCC 13 emits three static SMMLA sites.
Snapdragon GCC 15 peels the first signed triplet, producing six static SMMLA
sites: one initial triplet plus 255 loop repetitions, preserving exactly three
signed chains and 256 effective updates per chain. Unsigned and mixed chains
also execute 256 updates. This is verified semantic equivalence, not an exception
to arithmetic or coverage requirements. Static mnemonic counts alone are not a
valid compiler-portable test of the recurrence.

**Sustained evaluation:** Spark provides 481.282 s of usable analysis, approximately
91.945 million verified blocks/s; Snapdragon provides 481.501 s and approximately
17.877 million verified blocks/s. Both record zero progress stalls. Per-thread
progress coverage is 99.44–99.52% on Spark and 99.53–99.60% on Snapdragon;
second-half/first-half work-rate ratios are 99.75–100.22% and 99.58–100.26%,
respectively. Spark's heterogeneous cores have differing per-thread throughput;
this is not missing target coverage.

**Operating conditions and limitations:** Spark reports cpufreq values of
2,808/3,900 MHz (aggregate 3,354 MHz), not independently measured effective clocks.
CPU-specific temperature and package power are unavailable; other platform
thermal readings peak at 85.7/87.3 C in functional/sustained tests. Snapdragon
CPU-subsystem thermal maxima are 80.1/86.0 C; CPU clocks and package power are
unavailable. On both, `dmesg` capture is permission-denied and filtered journal
captures are empty, so complete kernel-event visibility is not established.
Missing sensors/logs remain missing evidence, not measured zero or proof of no
kernel incidents. These gates accept independently verified sustained arithmetic
on the tested configurations only; they do not establish maximum power,
superiority over DotProd/SVE, or universal I8MM hardware acceptance.

No additional physical repetition or production kernel change is required by
this evidence. Local result folders and helper binaries remain outside the
committed development inventory.

### Reproduction procedure — Spark, then Snapdragon (acceptance complete)

Copy the actual current working project to Spark and launch LVS normally.

1. Select **ARM64 SVE FP32 FMA Functional Confirmation**. Under **Run Setup →
   Stage Overrides → Configure Stage Workloads (this run only)** select the CPU
   stage and change **CPU Instruction Set** to **`neon_i8mm`**.
2. Enable **Advanced Debug** and Run. Change nothing else: keep native backend,
   empty instruction intent, Power Auto off, all allowed CPUs, extreme/steady,
   120 seconds, two-second telemetry and 30/30 trims; other modules stay disabled.
   Automatic prelaunch validation remains authoritative. No separate manual
   Dry Run, new saved profile or deployment package is needed.
3. After Gate A succeeds, select **ARM64 SVE FP32 FMA Sustained Effectiveness**.
   Change only the instruction set to `neon_i8mm` and enable Advanced Debug.
   Retain the authored 600 seconds, 60/60 trims and 480-second usable window.
4. Preserve complete execution/diagnostic folders and **each target's actual
   executed `build/cpu_stress_helper_arm64`**. Match its SHA-256 to prelaunch,
   running-process and post-execution records before disassembling
   `execute_neon_i8mm_block` (including compiler-renamed variants). Require
   three SMMLA, three UMMLA and two USMMLA logical chains with eight independent
   accumulators, exactly 256 effective updates and all result stores. Equivalent
   compiler loop peeling may change static instruction-site counts.
5. Stop on conflicting/unavailable capability, affinity failure, corruption,
   safety intervention, unexplained exit or incomplete terminal evidence. Never
   substitute DotProd or another kernel and call it an I8MM pass.

After Spark acceptance, repeat the same two existing profiles and only the
same ISA/Advanced Debug changes on Snapdragon X1 Plus. Establish current-build
I8MM eligibility for its actual allowed CPUs; do not assume it from DotProd
support or the processor name. Keep the two helpers separately named and associate
by recorded hash. Return effective profiles, overridden readiness, per-thread
capabilities/affinity, JSON, progress, logs, telemetry, compiler/build and executable
identities, manifests and final reports. Diagnostics may capture the original
SVE template; actual effective configuration and worker evidence establish I8MM.
