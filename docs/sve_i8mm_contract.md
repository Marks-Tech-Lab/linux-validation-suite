# Explicit SVE I8MM verified workload

`sve_i8mm` is experimental, explicit-only uncommitted development after the accepted
NEON BF16 milestone (`83665bc59213c8392b3d69480262b1b70b339a80`). It is not part of
published v0.5.3-alpha. Auto, generic vector intents, `highest_verified_vector` and
measured Power Auto retain their existing policies.

**Gate A and Gate B PASS on GB10 Spark at 128-bit VL. Snapdragon native
compilation, scalar/NEON compatibility and explicit unsupported-SVE-I8MM rejection
are accepted.** The explicit rejection is operator-confirmed screenshot evidence;
it is not a machine-readable saved diagnostic inspected in this workspace.
Compiler success, disassembly, labelled emulation and feature flags are software or
capability evidence; they do not establish physical acceptance or stress effectiveness.

## Instructions, segment mapping and recurrence

[`native/cpu_sve_i8mm_kernel.h`](../native/cpu_sve_i8mm_kernel.h) defines eight
independent scalable accumulator chains:

| Chains | Actual native instructions | Interpretation |
|---|---|---|
| 0–2 | `SMMLA Zd.S, Zn.B, Zm.B` | signed × signed bytes |
| 3–5 | `UMMLA Zd.S, Zn.B, Zm.B` | unsigned × unsigned bytes |
| 6–7 | `USMMLA Zd.S, Zn.B, Zm.B` | unsigned left × signed right bytes |

These are SVE Z-register instructions. They are not Advanced SIMD V/Q-register
I8MM, DotProd, SVE2 SMLAL, floating-point arithmetic or emulation.
Each independent 128-bit segment computes A[2][8] × B[8][2] + C[2][2]. A is packed
by rows, B by columns, and the four int32 output lanes are C00, C01, C10, C11.
A scalable register has VL/16 such matrix segments, with **four outputs per segment**.
Each chain has distinct operands and its own accumulator initialization.

A credited block executes **256 recurrence rounds on all eight chains**, then a
separately checked **one-round witness** using the same native function and inputs.
All active result lanes and guards must pass before one block is credited. At VL
bytes, each block verifies 8×(VL/4) int32 lanes, with 8×(VL/4)×8×256 stress byte
products plus 8×(VL/4)×8 witness products. These derived counts are not measured
instruction retirement, maximum-power evidence or direct cross-kernel throughput.

Arm [ACLE](https://arm-software.github.io/acle/main/acle.html) maps the corresponding
SVE operations to `svmmla_s32`, `svmmla_u32` and `svusmmla_s32`. LVS uses an isolated
volatile assembly region here: fixed Z-register clobbers retain eight independent
chains without GCC's extended-asm operand limit, and make bounded cancellation,
full-predicate loads/stores and VL consistency explicit. This avoids relying on
compiler unrolling/peeling to preserve the stress recurrence. The compiler still
owns scalar ABI, register saves and surrounding control flow. Tests trace effective
data/control flow rather than relying on static opcode counts.

Full `PTRUE` byte/word predicates and `MUL VL` addressing load all active coefficients,
initial accumulators and output lanes. `CNTW` is compared with the validated lane
count before loads and again before stores. Cancellation is checked every 32 rounds;
an interrupted partial block stores no completed result and earns no credit. The
final verification block and its witness finish completely during normal shutdown.

## Independent arithmetic and bounds

The reference constructs each 2×8 by 8×2 matrix result using signed int64 products
and sums, independently for every chain, segment and lane. Explicit byte decoding
implements signed/unsigned/mixed semantics without implementation-defined int8 casts.
It multiplies the eight-product sum by 256 (or one for the witness), adds the
initial unsigned accumulator in int64, then converts to uint32 for defined modulo
2^32 behavior. Even 8×255×255×256 + UINT32_MAX fits safely in int64.

Four deterministic seed-varying cases include signed extremes -128/127, unsigned
0/255, mixed-sign operands, 0x80000000 and near-UINT32_MAX accumulators, wraparound,
all row/column positions and segment-varying data. Integer arithmetic needs neither
FPCR rounding modes nor floating-point tolerances. Initial, periodic and final
checks compare every active uint32 bit pattern exactly. The software stepwise
emulator is separate from the closed-form reference; an independent Python matrix
oracle checks mapping, boundaries and every generated active lane at all supported
software VLs. Physical corruption injection is not claimed.

Current SVE architectural lengths are handled as **16–256 bytes in multiples of
16**, without a power-of-two or 128-bit assumption. Each thread inherits its VL;
LVS never calls PR_SVE_SET_VL. Valid independently observed VLs can differ between
threads. Each thread's recorded VL/flags must remain unchanged throughout credited
work. Linux PR_SVE_GET_VL failure, unsupported flags, malformed geometry, inconsistent
CNTW, affinity loss or a later VL change fails closed.

Input/reference storage is bounded at architectural maximum capacity: four
10,240-byte cases and a 2,056-byte output buffer (**43,016 heap bytes per thread**),
plus bounded local temporaries and existing thread infrastructure. Active data is
packed using the observed VL. Inactive capacity ensures that an unexpected VL
increase remains inside allocated storage before rejection. Guards cover the
active output end and maximum capacity. Only the recorded active extent is verified
and credited; inactive padding is not claimed as work. Allocation failure terminates
with explicit error evidence, freeing whichever allocations succeeded.

Scalability review: target threads follow the existing allowed-CPU/resource policy;
there is no CPU-model exception or unrelated capacity proxy. Constant per-thread
storage is about 42 KiB and grows linearly with selected threads. Software fixtures
cover one/sparse/256 CPU target sets, heterogeneous missing capability, resource
failure, all 16 valid VLs, mixed per-thread VLs and later-segment corruption. These
fixtures do not grant physical acceptance for wider VLs or 256-thread hardware.

## Independent capability and optional compilation

Linux runtime requirements on **every selected CPU** are:

- HWCAP_FP (bit 0), HWCAP_ASIMD (bit 1), HWCAP_SVE (bit 22).
- **HWCAP2_SVEI8MM (bit 9)**.
- Successful inherited per-thread PR_SVE_GET_VL, supported geometry and pinned affinity.

SVE2 (HWCAP2 bit 1), Advanced SIMD I8MM (bit 13), and SVE I8MM (bit 9) are separate
runtime evidence. Neither SVE2 nor NEON I8MM alone admits this kernel; the kernel
executes only the requested SVE matrix forms. See the official
[Linux HWCAP definitions](https://github.com/torvalds/linux/blob/master/arch/arm64/include/uapi/asm/hwcap.h)
and [SVE userspace ABI](https://www.kernel.org/doc/html/latest/arch/arm64/sve.html).
PR_SVE_VL_INHERIT is accepted and recorded; unknown configuration flags are rejected.
No SVE instruction or VL-dependent load is executed before capability admission.

The independent `LVS_CPU_HELPER_ENABLE_SVE_I8MM` region uses GCC function targeting
`+sve+i8mm` or Clang `sve,i8mm`, plus local assembler extensions. Build commands never
add global `-march` or require SVE hardware to compile the baseline helper. Optional
compilation salvage preserves existing kernels when a compiler/assembler cannot
build this region; the existing three SVE build tiers have a finite maximum of
27 attempts, with ordinary successful builds still using one attempt. Readiness
separately records compiled support and actual hardware availability.

Historical current-project captures show Spark HWCAP `0xefffffff`, HWCAP2
`0x801af3ff` and 16-byte VL, including SVE I8MM capability. Snapdragon captures show
HWCAP `0xffbfffff`, HWCAP2 `0x3b6181`, no SVE and no SVE I8MM. These are prior-build
observations, not new-kernel acceptance. Both targets require current-build checks.

## Reporting, progress and lifecycle

`verification_contract=sve_i8mm_v1` records:

- Method `wide_integer_segmented_matrix_reference_modulo_2_32`.
- Operation family `sve_segmented_s8_s8_u8_u8_u8_s8_matrix_2x8_8x2`.
- Native implementation `aarch64_sve_i8mm_asm`, actual ISA `svei8mm`.
- Eight chains (three signed, three unsigned, two mixed), 256 matrix rounds, one
  witness round, eight products per result lane, 128-bit matrix segments and layout
  `a_row_major_b_column_major_c_row_major`.
- Per-thread VL bytes/bits/flags/errno, active int32 lanes, matrix segments per chain,
  HWCAP/HWCAP2, pinned CPU identity, verification phases, verified/interrupted blocks
  and explicit errors. All per-thread counters must reconcile with the aggregate.

`test_integer_emulation` and `test_override` are labelled software evidence only.
Reports and compatibility exports retain complete failed/incomplete worker evidence.
Missing verification, bad capability/geometry, arithmetic/affinity errors, failed
progress persistence or unsuccessful process lifecycle prevents worker success.
Normal completion requires final verified work, thread joins, freed buffers,
terminal results and successful process exit under existing parent completion rules.

`sve_i8mm_progress_v1` uses monotonic/realtime-correlated per-thread snapshots.
Publication geometry must match final verified thread geometry, including all active
segments. Reports derive stress byte-product rates per thread from that thread's
VL, then aggregate them. Witness products are counted separately. Progress analysis
checks startup/terminal records, timestamps, PID/CPU identities, counter monotonicity,
stalls and trimmed-window coverage. Hardware throughput and maximum power are not
inferred from the instruction family or a derived operation count.

## Software validation and source identity

Focused validation includes matrix-placement bases and boundary/reference arithmetic,
all 16 supported software VLs, native object disassembly, bounded emitted control/data
flow, incorrect-opcode/mapping/stride/store/round mutations, optional compiler salvage,
capability/VL/affinity/corruption/resource/cancellation/lifecycle failures, progress
and CLI/TUI planning/reporting parity. AArch64 baseline, SVE-I8MM-only and combined
optional-feature objects are compiled without executing them on the development host.
The pre-physical software baseline passes **358/358 smoke tests**, including six new SVE I8MM
groups. The focused specialized-ISA and selector run passes **50/50 groups**.
All **81/81 profiles** validate (25 active, 56 archived), with five unchanged
advisories. **379 Python files** compile and **19 integration imports** pass.
AArch64 baseline, SVE-I8MM-only and combined-feature assembly/object compilation
and instruction/data-flow checks pass; these are cross-compilation evidence,
not target-local GCC or physical execution acceptance.

The complete **370-file** `lvs_execution_source_v1` source identity is
`8d3c99476db9b4da561a6daeecd96880b9f2d1bb441757f3f7fb272b886fdb90`.
The scope includes the new native header and production integration. Markdown
and smoke-test files are outside this execution-source scope. This differs from
the accepted NEON BF16 snapshot because executable implementation has changed;
this snapshot was physically accepted in the executions below. Subsequent
readiness-persistence changes have a different full-source identity and were not
physically executed by these runs.

## Completed physical acceptance and portability

| Platform / actual workload | Native duration | Verified work | Decision |
|---|---:|---:|---|
| GB10 Spark functional, 20 CPUs | 121.310 s | 4,684,435,829 blocks | Gate A PASS |
| GB10 Spark sustained, 20 CPUs | 601.922 s | 23,273,347,282 blocks | Gate A/B PASS |
| Snapdragon X1 Plus scalar, 8 CPUs | 121.310 s | 151,548 verification/canary passes | Baseline compatibility PASS |
| Snapdragon X1 Plus NEON FP32/FMA, 8 CPUs | 121.238 s | 1,526,694,116 blocks | Baseline compatibility PASS |

The independently reviewed Spark executions are the November 3, 2026 16:49:59
functional and 16:52:49 sustained folders. Snapdragon scalar and NEON executions
are 16:49:03 and 16:53:37. All four initial/final complete 370-file source identities
match `8d3c99476db9b4da561a6daeecd96880b9f2d1bb441757f3f7fb272b886fdb90`
with no recorded source changes. Effective profiles, launch commands, workers,
progress and finalized reports establish actual ISAs despite SVE template titles.

Spark's retained executed helper (`results/cpu_stress_helper_arm64` at review)
is AArch64 ELF, Ubuntu GCC 13.3.0, SHA-256
`78e04ae9f9c33187dec60e5952477c072021155270a5f637083875b4753ecb55`.
It matches both runs' prelaunch, running-process and post-execution observations.
Disassembly confirms three signed, three unsigned and two mixed Z-register chains,
256 rounds, the separate one-round witness, full predicates and all eight stores.
Every thread on CPUs 0–19 recorded inherited 16-byte VL, four int32 lanes and one
128-bit matrix segment per chain, with correct capability and affinity evidence.
All active lanes passed independent exact reference checks and guards in initial,
periodic and final verification, with zero arithmetic errors. Wider VLs remain
software-validated only. Software corruption tests are not physical fault injection.

The sustained trimmed window is 481.950 seconds with **38.665 million verified
blocks/s**, approximately 38.665/38.664 million blocks/s in its first/second halves.
Per-thread coverage is 99.636–99.719%, with zero recorded stalls; 302 snapshots
reconcile with terminal counters and process identity. Both Spark workers exited
zero, with final verification after uncredited interrupted partial work, no
shutdown timeout/SIGKILL, and finalized parent PASS results. Normal worker resource
release and thread joins precede successful exit. CPU-only runtime memory guards
were disabled and did not claim GPU allocation-guard coverage.

Spark platform thermal peaks were 71.7°C functional and 73.7°C sustained.
CPU-specific temperature and package power were unavailable. Static cpufreq
2808/3900 MHz readings are not independent effective-clock measurements. Denied
`dmesg` access and empty filtered journals restrict kernel visibility. Sustained
verified work is accepted, not maximum-power effectiveness or superiority to NEON.

Snapdragon's updated helper compiled optional SVE I8MM successfully while correctly
reporting no hardware SVE/SVEI8MM capability. Its recorded executable SHA-256
`a78699f4a74ba48ae94722ba85ddb250d0121dd2eec97bd37e40e153540fb026`
agrees across both baselines' prelaunch/process/post-execution records. CPUs 0–7
had correct affinity, zero errors, successful native exits and parent finalization;
NEON initial/periodic/final checks and timestamped progress reconcile. The scalar
run recorded an incidental USB reset without CPU/lifecycle failure; CPU power and
frequency were unavailable. These are independently inspected native executions.

The operator separately confirmed a screenshot showing effective
`instruction_set=sve_i8mm`, CPUs 0–7, blocked readiness, the explicit unsupported
`sve_i8mm` reason, zero runnable stages, no runnable commands, no worker and no
fallback. This closes negative-capability behavior on operator-confirmed evidence.
The inspected standalone captures (including 16:55:43) instead request original
`sve`; they must not be relabelled as machine-readable SVE-I8MM rejection evidence.
No screenshot file is claimed present or independently inspected here.
Snapdragon receives portability acceptance, not SVE I8MM arithmetic/stress acceptance.

## Effective-readiness persistence correction after physical acceptance

The later diagnostic correction automatically saves effective Run Setup readiness
for both CLI and TUI, before any worker/execution folder is created, independently
of Advanced Debug. The original-profile Dry Run remains separately labelled.
`*_Effective_Preflight_*` artifacts contain atomic `preflight_report.json`,
`original_profile.json`, effective `profile_used.json` and a summary. They retain
original/effective selections, field-level run-local overrides, CPU targets and
capability verdicts, commands (including empty lists), warnings/errors, backend
compilation status, source identity and available host identity. Status is
READY/BLOCKED, explicitly readiness-only: no execution PASS is fabricated.
A changed configuration or decision preserves a separate artifact; repeated display
refreshes the same decision. Persistence errors remain visible. This fixes missing
effective evidence, not capability policy or any executed arithmetic kernel.

The physical-source identity above remains authoritative for accepted execution.
The post-acceptance diagnostic tree must be identified separately; documentation
closure does not make that full snapshot physically tested. No physical retest is
required for this persistence-only change.

The diagnostic correction passes **18/18 focused checks**, **362/362 complete
smoke tests**, **81/81 profiles** (five unchanged advisories), **380 Python
compilation checks** and **29 integration imports**. Baseline/SVE-I8MM/combined
AArch64 object and emission checks remain covered by the complete suite. Markdown,
local links and diff checks pass. Its complete 370-file source fingerprint is
`524d9414cfac636b2ccdc45a89dcdc613f8729a65ff33daeb53ca1a9b597a470`.
The changed scoped files implement diagnostic persistence and original/effective
configuration evidence; native workload arithmetic, capability gates, verification,
allocation, affinity, safety, lifecycle and selection policies are unchanged.
This is software validation of the modified snapshot, not a new physical-source
claim. The following procedures are retained
for reproducibility, not requests to repeat completed acceptance.

## Minimum Spark physical acceptance

Deploy the actual working project directory. Use these existing normal TUI profiles:

| Existing profile | Only settings to change in Run Setup |
|---|---|
| ARM64 SVE FP32 FMA Functional Confirmation | Stage Overrides → Configure Stage Workloads (this run only) → CPU Instruction Set: `sve_i8mm`; Advanced Debug: ON |
| ARM64 SVE FP32 FMA Sustained Effectiveness | Same two changes |

Retain profile defaults: native CPU, all allowed CPUs, empty instruction intent,
Power Auto off, extreme/steady, CPU only, 120/600 seconds and existing trims/guards.
Expected Spark CPU count is 20 only if the current allowed set confirms it. Review
must show effective `sve_i8mm`; automatic overridden preflight must admit every
selected CPU. No separate manual Dry Run or saved profile copy is required.

**Gate A — arithmetic/integrity:** actual native SVE SMMLA/UMMLA/USMMLA execution;
independent verification of every active matrix segment/lane and the one-round
witness; complete initial/periodic/final checks with zero mismatches; capability,
VL and affinity integrity; matching source and executable identities; successful
worker exit, cleanup and parent finalization. Preserve the executed helper, not a
later rebuild, for instruction and hash verification.

**Gate B — sustained verified stress:** complete 600-second execution, appropriate
usable post-trim window, continuous reconciled per-thread progress, throughput and
stall analysis, lifecycle/safety evidence and available temperature/frequency/power
and kernel observations. Explicitly retain unavailable-sensor and restricted-log
limitations. Maximum wattage or superiority over NEON I8MM is not an acceptance
requirement. Spark's previously observed 128-bit VL grants no physical wider-VL
acceptance; only actually tested lengths can be accepted.

Return both execution folders, corresponding Advanced Debug/template diagnostics,
effective overridden readiness and `build/cpu_stress_helper_arm64` copied immediately
to a distinct Spark-labelled evidence filename, with SHA-256. Match the file against
prelaunch, process-executable and post-execution observations and retain target-local
compiler/build evidence. Template SVE FP32/FMA labels are not the effective ISA.
Stop on arithmetic, capability, VL, affinity, guard or lifecycle failure and retain
partial evidence; do not repeatedly run a failing workload.

## Minimum Snapdragon portability confirmation after Spark acceptance

Use **ARM64 SVE FP32 FMA Functional Confirmation** for each item below; change only
the indicated run-local instruction set and turn Advanced Debug ON:

| Purpose | CPU Instruction Set override | Duration / expected result |
|---|---|---|
| Updated helper baseline | `scalar` | Existing 120 seconds; verified native PASS on all allowed CPUs |
| Existing NEON FP32/FMA | `neon_fp32_fma` | Existing 120 seconds; verified native PASS on all allowed CPUs |
| Explicit SVE I8MM rejection | `sve_i8mm` | Preflight must reject absent SVE/SVEI8MM; zero worker launches and no fallback |

Retain native target-local compilation/readiness, both functional executions with
full lifecycle/provenance, and effective `sve_i8mm` rejection across the complete
allowed set (expected eight CPUs only if currently observed). If preflight blocks
before an execution directory is created, retain the effective Run Setup and its
rejection evidence; an original-template `sve_fp32_fma` rejection alone is insufficient.
Preserve the updated Snapdragon helper separately for hash association.
Do not run a 600-second unsupported SVE workload. Correct rejection is portability
acceptance, not physical SVE I8MM execution acceptance. If current capabilities differ
from historical captures, stop and review that evidence before changing the procedure.
