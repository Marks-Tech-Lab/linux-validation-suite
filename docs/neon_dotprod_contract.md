# Explicit NEON signed and unsigned byte dot-product stress

The post-release development token is **`neon_dotprod`**. It is experimental,
explicit-only and available in the existing CLI/TUI CPU Instruction Set controls
and run-local Stage Overrides. It is excluded from ordinary Auto, all generic
vector intents and measured Power Auto. No published release identity is changed.

## Arithmetic and emitted instructions

Each block runs eight independent 128-bit accumulators for 256 dependent rounds:
four signed `SDOT` chains and four unsigned `UDOT` chains. Each vector contains
four 32-bit accumulator lanes. Each instruction adds four corresponding byte
products to each lane, without saturation. Compiler barriers preserve the
recurrence; optional per-function targets isolate the actual DotProd instructions
from baseline code. The production entry is `execute_neon_dotprod_block` in
`native/cpu_dotprod_kernel.h`, included by the existing native CPU helper.

Four seed-varying cases include signed -128, 127, -1, 0 and 1, unsigned 0, 255,
1, 128 and 127, mixed signs, distinct lane data and accumulator wraparound.
A separate scalar reference sums four products in int64, multiplies by 256,
adds the initial uint32 accumulator and converts to uint32. The bounded expression
fits int64; the final conversion defines modulo-2^32 behavior without signed
C overflow. Every output lane of both instruction families is checked against
that reference after every completed block. Output guard words detect writes
outside the expected 32 words. Partial blocks receive no verified credit.

Each block accounts for 32,768 byte products (16,384 signed and 16,384 unsigned).
These are derived arithmetic counts, not measured retired instructions. Four
512-byte reference cases plus guarded output require approximately 2.2 KiB of
fixed per-thread data, independent of installed RAM or SVE vector length.

## Capability, portability and lifecycle

Linux AArch64 HWCAP FP, ASIMD and ASIMDDP (bit 20) plus successful optional
DotProd compilation are required. Native capability probes are pinned to each
selected allowed CPU. Every executing thread is pinned, rechecks capability
after binding, records HWCAP, and checks observed CPU identity before and after
work. Linux HWCAP is the process-visible common capability set; CPU model names
or compiler support alone never authorize execution. No SVE support is required.
NEON is fixed at 128 bits and does not inherit or modify an SVE vector length.

The helper build attempts the isolated DotProd region independently at each
existing optional SVE/SVE2 or baseline build tier. An unsupported DotProd
compiler falls back to that same tier without DotProd; an unavailable SVE
compiler can still retain DotProd. No global `-march` is added. Header changes
invalidate helper readiness. Readiness records `dotprod_build` and collected
native provenance exposes `dotprod_build_status`; runtime capability output
separately records `dotprod_compiled`, `dotprod_available` and HWCAP.

Explicit unsupported requests fail before execution with no generic fallback.
Normal cancellation checks occur every 32 arithmetic rounds. A completed initial
block is followed by recurring verified blocks and one bounded final verified
block on normal termination. Failed arithmetic or capability/affinity checks
stop the workload and cannot be overwritten by a successful final snapshot.
Existing thread joins, parent lifecycle, thermal safeguards, source identity and
prelaunch/process/post-execution native executable provenance remain authoritative.

## Evidence and compatibility contract

- `verification_contract=neon_dotprod_v1`, `verification_version=1`.
- `verification_method=wide_integer_dot_reference_modulo_2_32`.
- `operation_family=s8_s8_and_u8_u8_dot_product_accumulate`.
- `execution_implementation=aarch64_neon_dotprod_intrinsics`, `actual_isa=asimddp`.
- Eight accumulator chains, four active int32 lanes, four products per lane,
  256 dot rounds per block; all-thread HWCAP, affinity and verification phases.
- `neon_dotprod_progress_v1` sidecar: monotonic/realtime timestamps, per-thread
  verified blocks, interrupted blocks in the terminal worker record, phase and
  affinity evidence, bounded publication and explicit persistence errors.

The shared strict integer dot-product assessment requires positive reconciled
all-thread counts and complete initial/periodic/final evidence. Missing,
contradictory, corrupt or interrupted records cannot establish worker success.
Reports separate selected kernel, actual execution, successful software
verification and physical acceptance. Compatibility exports preserve complete
recognized records, including failures, rather than assigning an invented legacy
SIMD tier. Labelled `test_integer_emulation` / `test_override` fixtures are
software tests and never physical instruction evidence.

## Validation and acceptance gates

Software validation checks the independent reference, signed/unsigned corruption,
initial/periodic/final failure, guarded output, cancellation, affinity loss,
capability loss, partial thread creation, progress, reports, compatibility,
CLI/TUI parity and optional compilation fallbacks. Full AArch64 production-source
cross-emission checks four `SDOT` and four `UDOT` instructions in the real block;
baseline compilation contains neither. This does not prove physical execution.

**Software checkpoint:** all six focused DotProd checks and the complete
**332/332 smoke suite** pass. All **81/81 profiles** (25 active, 56 archived)
validate with the five unchanged advisories. Python compilation and changed-module
plus CLI/TUI integration imports pass. Existing SVE/SVE2 and VNNI regressions
remain passing. Host compilation uses GCC 16.2.1; full AArch64 production-source
cross-emission also succeeds using the optional Zig/Clang toolchain. These are
software results, not target-local compilation or physical acceptance.

The complete 366-file `lvs_execution_source_v1` fingerprint for this uncommitted
implementation is:

```text
320977e5bf46a8e69a27da4874f98dc7a7fb450a28234aa2feb9a4b8377985ec
```

This differs from the committed SVE2 source because native DotProd code and its
Python integration were added. The DotProd executions below independently accept
this source within their tested configurations; earlier workload acceptance alone
did not accept DotProd. Markdown and software test fixtures are outside that source scope.

**Scalability review:** work uses the selected allowed CPU set and common pinned
capability evidence, not model names or RAM capacity. Fixed small per-thread
state, eight register chains and bounded cancellation apply equally to small
and large CPU sets. Deterministic tests cover one CPU, sparse heterogeneous
sets, 256 targets and a target missing DotProd. Baseline builds, missing optional
compiler support and unsupported architectures retain their existing behavior.
No GPU allocation, memory reserve, affinity policy or concurrency was changed.

**Gate A — PASS on Spark and Snapdragon:** genuine physical DotProd execution
and arithmetic/integrity acceptance are established by the evidence below.
Require current-build all-target eligibility, actual executed helper
instruction evidence, independent initial/periodic/final verification on every
thread, zero mismatches, correct affinity, matching source/helper identities,
normal native exit and complete parent finalization. Spark and Snapdragon were
independently reviewed using their actual capability and executable evidence.
Older non-DotProd ARM64 must retain baseline operation and reject an
explicit unsupported request.

**Gate B — PASS on Spark and Snapdragon:** sustained verified-stress evaluation
is established within the tested configurations. Require sustained
verified progress, sufficient usable-window coverage, no unexplained stalls,
normal lifecycle and available operating-condition telemetry. Assess useful
sustained computation separately from maximum power, ISA width or claimed
superiority over NEON/SVE FP32/FMA. Missing power, temperature or kernel telemetry
must remain missing. Physical acceptance applies only to tested configurations.

## Completed physical acceptance — November 2, 2026

Both gates PASS independently on NVIDIA GB10 Spark (HP ZGX Nano G1n AI Station,
20/20 allowed CPUs 0–19) and Qualcomm Snapdragon X1 Plus (HP OmniBook X 14-fe1xxx,
8/8 allowed CPUs 0–7). These are independently inspected physical executions,
not compiler fixtures or operator-only attestations. The earlier missing-folder
conclusion for Snapdragon is superseded by the complete execution review.

| Platform | Functional native execution | Sustained native execution | Gate A | Gate B |
|---|---|---|---|---|
| GB10 Spark, 20 CPUs | 120.371 s; 10,932,750,690 verified blocks | 600.911 s; 54,587,906,380 verified blocks | PASS | PASS |
| Snapdragon X1 Plus, 8 CPUs | 121.276 s; 2,856,577,340 verified blocks | 600.570 s; 14,323,962,061 verified blocks | PASS | PASS |

All four effective profiles and launch commands selected native `neon_dotprod`,
extreme/steady, all allowed CPUs, empty instruction intent and Power Auto off.
Per-target readiness and executing threads establish HWCAP DotProd eligibility
(Spark `0xefffffff`, Snapdragon `0xffbfffff`), successful pinned affinity and
correct observed CPU identities. Workers record `aarch64_neon_dotprod_intrinsics`
and `actual_isa=asimddp`. Every thread completed independent signed/unsigned
initial, periodic and final verification with zero mismatches. Parent and worker
results, timestamped sidecars, summaries and compatibility exports reconcile.

### Execution and diagnostic references

Complete local execution folders under `results/` are:

- Spark functional: `2026-11-02_15-27-41_ARM64 SVE FP32 FMA Functional Confirmation`.
- Spark sustained: `2026-11-02_15-55-08_ARM64 SVE FP32 FMA Sustained Effectiveness`.
- Snapdragon functional: `2026-11-02_16-07-47_ARM64 SVE FP32 FMA Functional Confirmation`.
- Snapdragon sustained: `2026-11-02_16-11-47_ARM64 SVE FP32 FMA Sustained Effectiveness`.

Matching diagnostic folders have the same profile suffix plus `_Diagnostics`,
with timestamps `15-27-36`, `15-54-58`, `16-07-39` and `16-11-39`, respectively.
They inspect the original SVE FP32/FMA templates, including expected unsupported
SVE preflight on Snapdragon. Actual effective profiles, overridden readiness,
launch commands and worker evidence establish DotProd execution; template names
and blocked template diagnostics do not contradict the successful overrides.

### Actual executable and source identity

Both retained binaries are ELF64 AArch64. Their independently compiled hashes
match prelaunch, running-process and post-execution identities in the associated
runs. Read-only AArch64 disassembly confirms four genuine `SDOT` and four `UDOT`
instructions in each actual helper, with four independent signed and four
independent unsigned accumulators, the 256-round recurrence and full output stores.

| Platform | Compiler metadata | Local retained helper | SHA-256 |
|---|---|---|---|
| Spark | GCC 13.3.0 (`Ubuntu 13.3.0-6ubuntu2~24.04.1`) | `results/cpu_stress_helper_arm64(1)` | `5c64b739603111995e481dc24533f86c826753a8d2378e9a8fc19b23ca8f3bf0` |
| Snapdragon | GCC 15.2.0 (`Ubuntu 15.2.0-16ubuntu1`) | `results/cpu_stress_helper_arm64` | `2500602ff7d287cd07b5e3cefa1b7e01806d41199c656539f35567195054aab5` |

The helper association is by recorded bytes, not filename order. Spark's
`execute_neon_dotprod_block.constprop.0` is at `0x4140` (156 bytes); Snapdragon's
`execute_neon_dotprod_block` is at `0x3a80` (268 bytes). All four runs match the
complete 366-file source fingerprint recorded above, unchanged at collection
endpoints. Captured Git metadata correctly identifies modified development
source based on `68e8847b70f1c1b63781bc4bb8def739e150982f`, not an exact match to
that committed predecessor. Local evidence and helpers stay outside the commit.

### Sustained work, lifecycle and limitations

Spark's sustained usable window was 480.939 seconds, at approximately **90.843
million verified blocks/s**. Its 301 progress snapshots reconcile with final
counts; per-thread progress coverage was 99.55–99.60%, with zero recorded stalls.
Second-half per-thread rates were 99.54–100.36% of first-half rates.

Snapdragon's sustained usable window was 480.582 seconds, at approximately
**23.856 million verified blocks/s**. Its 302 snapshots reconcile with final
counts; per-thread progress coverage was 99.57–99.62%, with zero recorded stalls.
Second-half rates were 99.51–100.64% of first-half rates. Functional runs also
had sufficient timestamped progress and complete terminal snapshots.

All four workers exited 0 with no shutdown timeout or forced kill, complete final
verification and finalized parent PASS results. Intermediate interrupted-block
records during orderly termination received no verified credit and were followed
by successful final verification. CPU lifecycle completion is established by
thread/process completion; no Vulkan-style device teardown claim is implied.
No safety intervention was recorded. CPU-only allocation growth guards were
disabled as configured; these runs do not exercise memory allocation-denial paths.

Spark cpufreq reported 2,808/3,900 MHz and an aggregate 3,354 MHz, not independently
measured effective clocks. CPU-specific temperature and package power were
unavailable; platform thermal zones peaked at 85.7 C functional and 86.7 C
sustained. Snapdragon CPU-subsystem temperature (maximum of 20 CPU thermal
zones) peaked at 84.4 C functional and 89.9 C sustained; CPU clocks and package
power were unavailable. Missing measurements are not zero. On both platforms,
`dmesg` was permission-denied and filtered journal output was empty; those captures
do not establish the absence of all kernel events.

These results establish useful sustained independently verified computation,
not maximum power, superiority over NEON/SVE FP32/FMA, independent execution
pipelines or universal hardware acceptance. No additional physical repetition
is needed to close this milestone. The workload remains experimental and
explicit-only. Next implementation priority is the remaining specialized ARM64
work on Spark, followed by supported Snapdragon compatibility and acceptance.

## Retained operator procedure

The following preserves reproducibility; it is not a request to repeat the
completed Spark or Snapdragon campaign.

Copy the current working project to **Spark** and launch LVS normally. No new
profile, manual Dry Run or package is needed.

1. Select **ARM64 SVE FP32 FMA Functional Confirmation**.
2. In **Run Setup → Stage Overrides → Configure Stage Workloads (this run only)**,
   select the CPU stage and change **CPU Instruction Set** to `neon_dotprod`.
   Enable **Advanced Debug**, then Run. Change no other setting: the existing
   native backend, empty instruction intent, Power Auto off, all allowed CPUs,
   extreme/steady, 120 seconds, two-second telemetry and 30/30 trims remain.
   Other modules stay disabled. The historical profile label is not ISA evidence.
3. After Gate A succeeds, select **ARM64 SVE FP32 FMA Sustained Effectiveness**.
   Apply the same instruction-set override and enable **Advanced Debug**. Retain
   the authored 600 seconds, 60/60 trims, sustained analysis and 480-second usable
   window. This is Gate B, not an automatic maximum-power claim.
4. Return complete execution/diagnostic folders and the exact executed helper
   for read-only SHA-256 and disassembly confirmation of both `SDOT` and `UDOT`.
   Preserve effective profiles, overridden preflight, per-thread HWCAP/affinity,
   worker JSON, progress sidecars, compiler/build evidence, executable identities,
   telemetry, exit codes and final reports. Template diagnostics may precede
   run-local overrides; use effective launch/worker evidence to identify execution.
5. Stop on unavailable/conflicting capability, affinity failure, arithmetic
   mismatch, safety intervention, unexplained exit or incomplete terminal evidence.
   Never substitute another ISA and call it a DotProd pass.

After Spark acceptance, use the **same existing profiles and only the same ISA
and Advanced Debug changes on Snapdragon X1 Plus**, first functional, then
sustained evaluation. Confirm all eight allowed CPUs from current capability
evidence, rather than assuming support from the processor name. Spark's previous
128-bit SVE observation does not constrain fixed-width NEON or prove DotProd
eligibility on either machine. Both gates are complete only for the tested
configurations recorded above; other implementations require their own evidence.
