# Explicit SVE2 signed widening integer multiply-accumulate

The post-VNNI workload token is **`sve2_smlal`**, committed in
`9edd4e786b7277523fcc3b18ad67c7f95c2a7750` and available through
normal CLI/TUI CPU Instruction Set selection and run-local Stage Overrides.
It is experimental and explicit-only. Ordinary Auto, baseline_vector,
high_throughput_vector, highest_verified_vector and Power Auto do not select it.
Runtime version and released tags/notes remain unchanged. Software validation
and physical acceptance are separate. Both physical gates now PASS on NVIDIA
GB10 Spark across 20/20 allowed CPUs at inherited 128-bit VL. Other SVE2
implementations and wider VLs are not physically accepted by these results;
Snapdragon X1 Plus baseline portability and unsupported-SVE2 rejection are now
accepted as recorded below; this does not claim SVE2 execution on Snapdragon.

## Arithmetic and actual instructions

Four independent pairs of 32-bit vector accumulators execute 256 recurrence
rounds per block. Each pair loads two signed 16-bit source vectors. `SMLALB`
uses source elements `2*i`, and `SMLALT` uses elements `2*i+1`, for destination
word lane `i`. Bottom/top means even/odd interleaved halfwords, not contiguous
lower/upper halves of the vector. Each loop iteration contains four real
`SMLALB` and four real `SMLALT` instructions, with compiler barriers retaining
the dependent recurrence. Normal non-streaming SVE2 is used; no SME is claimed.

A separate scalar reference computes `initial + int64(a) * int64(b) * 256` and
casts to uint32. The largest bounded product/recurrence plus any uint32 initial
value fits int64; conversion defines modulo-2^32 accumulation without signed C
overflow. Four seed-varying cases cover -32768, 32767, -1, 0, 1 and mixed signed
operands, positive/negative products, accumulator wraparound and distinct
bottom/top mappings. All active output lanes of all eight chains are checked
after every completed block. Guard words surround the output allocation.

Initial, recurring and final verification, zero error counters, exact worker
identity and all targeted threads are required. Partial interrupted blocks
receive no verified credit. After normal cancellation, one final bounded block
is verified if initialization succeeded and no error makes that inappropriate.
Execution checks cancellation every 32 recurrence rounds. Arithmetic failure,
invalid VL, affinity loss or instruction unavailability fails without ISA retry.
Software emulation and deliberately corrupted bottom/top results are explicitly
labelled tests, not physical instruction-execution evidence.

## Capability, VL, build and scalability

Linux AArch64 FP/ASIMD/SVE HWCAP and HWCAP2_SVE2 are required, as is optional
SVE2 compiler support. Linux's process-visible common capability set applies
across the selected CPUs; planning intersects the native supported kernels,
and each worker rechecks capability after applying its actual affinity.
CPU model names never authorize the ISA. SVE alone cannot authorize SVE2.

The target-specific region uses `arm_sve.h` intrinsics `svmlalb_s32` and
`svmlalt_s32`. Normal target-local GCC builds first try independently recorded
SVE/SVE2 regions, then existing SVE-only compilation if needed, then baseline
NEON/scalar. No global `-march`, fixed vector length or mandatory SVE2 compiler
flag is imposed on baseline functions. Header changes invalidate helper
readiness. Cross-compilation proves emission/buildability, not physical acceptance.

Every thread queries its inherited `PR_SVE_GET_VL`; LVS never sets VL. Valid
geometry is 16..256 bytes in 16-byte steps, with `VL/4` active int32 lanes and
`VL/2` source halfword lanes. The real execution function checks `svcntw()`
against the recorded thread geometry before loads. Mixed valid thread VLs are
represented individually, never collapsed into one assumed width. Software
fixtures cover 128-bit, non-power-of-two and maximum architectural lengths;
these do not establish physical acceptance of any width.

Work/storage are bounded independently of system RAM, GPU capacity or CPU model.
Per-thread case storage is fixed at the architectural maximum (four cases,
24 KiB total); outputs scale with actual VL up to 2 KiB plus guards. There are
no growing histories or queues. Existing process-allowed CPU targeting,
thermal safeguards, workload-level/load controls, provenance and shutdown
contracts remain authoritative. This cross-hardware design retains baseline
execution on non-SVE2 Snapdragon, unchanged x86/VNNI paths and older compilers
through optional-build fallback; unavailable explicit requests fail closed.

## Evidence and output compatibility

`verification_contract=sve2_smlal_v1` and
`verification_method=wide_integer_smlal_reference_modulo_2_32` identify the
independent integer contract. The operation family is
`s16_widening_multiply_accumulate_bottom_top`, not FP32 FMA or VNNI.
Production records identify `execution_implementation=aarch64_sve2_intrinsics`,
`actual_isa=sve2`, Linux HWCAP capability source and inherited per-thread VL.
Every thread retains HWCAP/HWCAP2, affinity/observed CPU, geometry,
verified/interrupted counts and initial/periodic/final phases. Unknown,
contradictory, failed or incomplete evidence cannot establish software success.

`sve2_smlal_progress_v1` reuses timestamped bounded publication and analysis.
Final counts must match worker results; sufficient post-trim all-thread progress
and a clean observed process exit are required for sustained interpretation.
Derived signed products per block are `8 * active_int32_lanes * 256`; these
are arithmetic work counts, not measured machine instructions, FLOPS or proof of
saturation. Reports retain each thread's VL and distinguish selected versus
executed kernels, software verification and prior physical acceptance. Legacy
exports preserve complete recognized records, including failures. Native helper
prelaunch/process/post identities and automatic source identity remain separate.

## Software validation checkpoint

Six focused SVE2 checks and the existing SVE FP32/FMA integration checks pass.
The complete suite passes **326/326**; **81/81** active/archived profiles validate
with the same five advisories. Python compilation, integration imports and
output/compatibility contracts pass. The actual full native worker was
cross-compiled with Zig/Clang for AArch64: its target function emits four
`SMLALB` and four `SMLALT` instructions per recurrence; the AArch64 baseline
translation unit also compiles with those optional instructions absent.
GCC-built host fixtures execute only labelled integer emulation/reference work,
not an SVE2 hardware workload. Optional cross tools are test/developer tools,
not new runtime dependencies. The completed Spark campaign below independently
establishes target-local GCC compilation and genuine SVE2 execution.

## Completed Spark physical acceptance — November 2, 2026

**Gate A — arithmetic/integrity: PASS.** **Gate B — sustained verified stress:
PASS.** Acceptance is scoped to the NVIDIA GB10 Spark platform tested as an
HP ZGX Nano G1n AI Station, hostname `zgx-6780`, with ten Cortex-A725 and ten
Cortex-X925 CPUs. All 20 allowed CPUs (0–19) executed with successfully applied
affinity, matching observed CPU IDs and inherited 16-byte (128-bit) SVE VL.
Linux HWCAP/HWCAP2 evidence and optional compiled support authorize SVE2;
neither the CPU model nor the historical profile name establishes eligibility.

| Execution folder under `results/` | Actual duration | Independently verified blocks | Verdict |
|---|---:|---:|---|
| `2026-11-02_11-46-04_ARM64 SVE FP32 FMA Functional Confirmation` | 120.219 s | 7,575,089,813 | PASS |
| `2026-11-02_12-07-52_ARM64 SVE FP32 FMA Sustained Effectiveness` | 601.111 s | 37,882,653,161 | PASS |

Both workers identify `aarch64_sve2_intrinsics`, `actual_isa=sve2`, the independent
signed widening reference contract and correct even/odd bottom/top mappings.
Every thread completed initial, periodic and final verification with zero
mismatches/errors. Final progress counts match each terminal thread record.
Both workers exited 0 without shutdown timeout or SIGKILL, parent executions
finalized, and manifests, reports and compatibility exports agree. No safety
intervention was recorded. The CPU-only stages had no budgeted RAM/GPU consumer;
the inactive allocation-growth guard is not missing shared-memory protection.

The sustained run has **481.111 usable seconds**, approximately **63.024 million
verified blocks/s**, zero recorded progress stalls, 301 timestamped snapshots
and 223 post-trim telemetry samples. Minimum per-thread progress coverage was
99.50%; second-half per-thread rates were 99.58–100.49% of first-half rates.
This establishes sustained independently verified computational stress in this
configuration, not maximum power, saturation, a separate execution pipeline or
superiority over SVE FP32/FMA.

The complete **365-file** source fingerprint matches both run endpoints and the
reviewed scoped development source:

```text
2cee8d6061d334dedb180fc1ed4b984a54b9265f4846518ab4baa1684b53b9ca
```

The executed AArch64 helper was built with **GCC 13.3.0**
(`Ubuntu 13.3.0-6ubuntu2~24.04.1`). Prelaunch, running-process and post-execution
identities in both runs match its SHA-256:

```text
92c3f3362d82daf1dceb4d1e5c8b15c2d12f40f9f5439eebe45002a615aa3137
```

The matching 74,280-byte executable is retained locally at
`results/cpu_stress_helper_arm64`, outside the committed source inventory.
Read-only LLVM AArch64 disassembly of `execute_sve2_smlal_block` (address
`0x3934`, 364 bytes) confirms **four SMLALB and four SMLALT** instructions in
the 256-round recurrence, sharing four source pairs with eight distinct
accumulators. The actual binary also checks VL and stores all eight vectors.
This closes the former instruction-evidence gap; cross-compilation alone did
not close it.

Associated diagnostic folders are
`2026-11-02_11-45-57_ARM64 SVE FP32 FMA Functional Confirmation_Diagnostics`
and `2026-11-02_12-07-45_ARM64 SVE FP32 FMA Sustained Effectiveness_Diagnostics`.
They inspect the original SVE FP32/FMA templates. Actual effective profiles,
overridden preflight, launch commands, worker records and Advanced Debug stage
selection instead establish explicit SVE2 execution. Preserve both records;
the template capture is not SVE2 acceptance evidence by itself.

CPU-specific temperature and package-power telemetry were unavailable, not zero.
Seven platform thermal zones remained monitored, with a sustained maximum of
74.8 C; these are not CPU junction-temperature measurements. Per-core cpufreq
readings were 2,808 MHz on A725 and 3,900 MHz on X925; the aggregate 3,354 MHz
is their mean, although the source map displays a representative CPU0 path.
These readings are not independently measured effective execution clocks.
Kernel visibility remains limited: `dmesg` was permission-denied and filtered
journal collection returned successfully but empty. This does not establish
the absence of all kernel/hardware events.

No further Spark repeat is required to close this campaign. The workload remains
experimental and explicit-only. Wider VLs and other SVE2 hardware remain separate
acceptance boundaries. Snapdragon portability has separate evidence below;
Spark execution alone does not establish non-SVE compatibility.

## Completed Snapdragon X1 Plus portability acceptance

**PASS:** target-local native compilation, scalar functional execution, NEON
FP32/FMA functional execution, and explicit unsupported-SVE2 rejection. This
closes portability acceptance for the committed SVE2 milestone. It does not
accept any future specialized NEON workload or claim Snapdragon SVE2 execution.

The target is the HP OmniBook X Laptop 14-fe1xxx with eight Qualcomm Oryon CPUs
and Adreno X1-45, running Ubuntu 26.04.1 and kernel `7.0.0-38-generic`. All allowed
CPUs 0–7 were targeted. Recorded HWCAP `0xffbfffff` and HWCAP2 `0x3b6181` expose
FP/ASIMD but not SVE/SVE2. Optional SVE/SVE2 compiler support does not authorize
execution on these CPUs.

The November 2 evidence under local `results/` includes:

| Requirement | Evidence | Outcome |
|---|---|---|
| Native compilation | Captures `2026-11-02_13-30-57_ARM64 SVE FP32 FMA Functional Confirmation_Diagnostics` and `2026-11-02_13-31-58_ARM64 SVE FP32 FMA Sustained Effectiveness_Diagnostics` (historical captures may reside in `results/Archived/`) | Target-local GCC build succeeded, including optional SVE/SVE2 compilation; baseline fallback was not needed. |
| Scalar execution | `2026-11-02_13-38-19_ARM64 SVE FP32 FMA Functional Confirmation` | 121.278 seconds of native scalar execution across eight pinned CPUs; 152,096 verification/canary passes, zero errors, exit 0 and finalized PASS. |
| NEON FP32/FMA execution | `2026-11-02_13-44-03_ARM64 SVE FP32 FMA Functional Confirmation` | 121.249 seconds across eight pinned CPUs; 1,527,028,320 independently verified blocks, initial/periodic/final verification, zero errors, exit 0 and finalized PASS. |
| Explicit SVE2 rejection | Operator-confirmed final screenshot: effective `instruction_set=sve2_smlal`, unsupported across CPUs 0–7, preflight blocked, zero runnable stages and no runnable commands | Expected unsupported-capability rejection; no SVE2 worker or silent fallback. |

The rejection row records the operator's supplied screenshot confirmation. No
screenshot file was discoverable in the local project during this documentation
update, so its pixels and file identity were not independently inspected. The
available `2026-11-02_13-48-46_ARM64 SVE FP32 FMA Functional Confirmation_Diagnostics`
capture records the original `sve_fp32_fma` template, not the effective SVE2
request; it must not be substituted for the explicit-rejection evidence.
Likewise the functional runs' matching diagnostics at `13-38-07` and `13-43-53`
inspect the original template. Effective profiles, launch commands and worker
records establish actual scalar and NEON execution.

Both functional runs match the complete 365-file source fingerprint:

```text
2cee8d6061d334dedb180fc1ed4b984a54b9265f4846518ab4baa1684b53b9ca
```

Their prelaunch, running-process and post-execution executable identities agree:

```text
741cdad1a98efa457e959c73470459eaf3778bbb724d5481b1b658c2a4ad9ff2
```

The target-local helper is 74,384 bytes. Functional readiness reused that built
helper; it did not rebuild it for each run. Captured Git metadata describes a
modified predecessor checkout rather than an exact association with commit
`9edd4e786b7277523fcc3b18ad67c7f95c2a7750`; the observed scoped source bytes
nevertheless match the committed, Spark-accepted implementation.

Scalar retains its established finite/checksum and independent integer-canary
contract: it does not emit the FP32/FMA initial/periodic/final phase fields or a
timestamped verified-block sidecar. Do not invent that evidence. NEON uses the
independent `integer_binary32_fma_reference` contract and timestamped progress:
approximately 12.597 million verified blocks/s with zero recorded stalls.
Both runs completed all-thread affinity checks and normal native/parent
lifecycles without shutdown timeouts or forced termination. Normal thread/process
completion establishes their CPU lifecycle; Vulkan-style allocation cleanup
fields are not applicable.

CPU package power was unavailable. Kernel visibility remained limited by denied
`dmesg` access and empty filtered journal captures; those captures do not prove
absence of kernel events. These short functional runs establish compatibility,
not new sustained-stress or maximum-power acceptance. No additional Snapdragon
execution is required for this milestone. Next implementation priority is the
unfinished specialized ARM64 work on Spark, followed by capability-appropriate
Snapdragon validation of the resulting shared NEON implementations.

## Retained physical evaluation criteria and procedure

The following records the two distinct gate criteria and reproducible procedure;
it is not a request to repeat the accepted Spark campaign.

**Integrity acceptance:** use the complete current working-project copy on Spark,
normal target-local setup/build and automatic prelaunch checks. Require genuine
SVE2 opcode execution, all-thread eligibility/affinity, independent arithmetic
verification and complete successful lifecycle evidence. Previously observed
Spark SVE width was 128 bits: record the actual inherited width without forcing
it, and accept only the physically observed configuration. Other widths remain
unaccepted until tested on suitable hardware.

**Sustained-stress evaluation:** after integrity succeeds, assess repeatable
verified activity and observed clocks, temperature and power where available.
A bounded 600-second trial below provides 480 planned usable seconds. Use its
measurements to judge sustained usefulness; no universal wattage, saturation,
throughput superiority or separate execution-pipeline claim is implied. SVE2
integer coverage is distinct from SVE FP32/FMA, but incremental stress value
requires physical evidence. This purpose-specific trial does not mandate the
same duration for every future instruction flavor.

### Exact Spark operator procedure

1. Copy the current working LVS project to Spark. Use normal target-local setup;
   do not substitute the published release or a helper from another machine.
2. Launch `.venv/bin/python linux_validation_suite_tui.py`.
3. Select **ARM64 SVE FP32 FMA Functional Confirmation**. In **Run Setup →
   Stage Overrides → Configure Stage Workloads (this run only)**, select the
   CPU stage, set **CPU Instruction Set** to `sve2_smlal`, and retain native
   backend, empty instruction intent, Power Auto off, all allowed CPUs,
   extreme/steady, 120 seconds, two-second telemetry and authored 30/30 trims.
   RAM/GPU/VRAM/storage workloads remain disabled. Use a run-local SVE2 label;
   preserve the saved profile. Review effective settings, enable **Advanced
   Debug**, and Run. No separate manual Dry Run is required.
4. Stop if optional compilation/capability, affinity or VL is unavailable or
   contradictory; do not substitute SVE FP32/FMA. Stop on arithmetic error,
   thermal/safety intervention, unexpected exit or incomplete terminal evidence.
5. If functional evidence passes, use **ARM64 SVE FP32 FMA Sustained
   Effectiveness** with the same SVE2 override. Retain 600 seconds, 60/60 trims,
   sustained analysis and 480-second minimum usable window, native/all CPUs and
   Advanced Debug. Do not infer ISA from the historical template name.
6. Return the complete execution directories and any associated diagnostic
   folders: effective profiles, manifests, native build/capability records,
   worker JSON/logs, `.progress.jsonl`, raw telemetry/source map, Advanced Debug,
   reports and source/helper identities. Inspect the associated helper's
   `execute_sve2_smlal_block` disassembly for both instruction forms.

Snapdragon X1 Plus must retain normal baseline native compilation and operation;
if current HWCAP evidence lacks SVE2, explicit selection must be rejected before
execution. That portability confirmation is separate from Spark arithmetic
acceptance and must not be inferred from a CPU model name.

References: [Arm ACLE SVE2 mappings](https://arm-software.github.io/acle/main/acle.html)
and [GCC AArch64 target options](https://gcc.gnu.org/onlinedocs/gcc/AArch64-Options.html).
