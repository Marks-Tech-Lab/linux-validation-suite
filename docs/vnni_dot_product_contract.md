# Explicit VNNI integer dot-product development milestone

This post-v0.5.3-alpha development implements `avx_vnni` and `avx512_vnni`.
Both are experimental, explicit-only CPU instruction-set selections in the shared
CLI/TUI editor and run-local Stage Overrides. No generic vector intent, ordinary
Auto or Power Auto selects them. Runtime version and published notes/tags are
unchanged. Physical arithmetic/integrity and sustained-stress acceptance are
complete for the configurations recorded below, independently of the 320/320
software smoke-test baseline. The implementation remains uncommitted development,
not part of the published v0.5.3-alpha release.

## Arithmetic and instruction implementation

The 256-bit function uses `_mm256_dpbusd_avx_epi32` (VEX `VPDPBUSD`), not an
AVX-512VL implementation relabelled AVX-VNNI. The 512-bit function uses
`_mm512_dpbusd_epi32` (EVEX `VPDPBUSD`). Each block runs eight independent
accumulators through 256 dependent recurrence rounds, with 8 or 16 int32 lanes
per chain. Compiler barriers retain the dependent instructions. Every output
lane is checked after every completed block. This first workload covers
unsigned-byte × signed-byte products and nonsaturating dword accumulation;
saturating VNNI, signed-word dot products and VNNI-INT8/INT16 extensions are not
claimed or implemented by this milestone.

Four deterministic seed-dependent cases include unsigned 0/255, signed -128/127,
negative/positive products and accumulator wraparound. A separately calculated
reference sums four products in int64, multiplies by the known recurrence count
and adds the unsigned initial bits in int64. These bounded calculations cannot
overflow int64. Conversion to uint32 implements modulo-2^32, avoiding C signed
overflow or an accidental saturating interpretation. SIMD and reference do not
share a dot-product intrinsic. Verification checks the authored arithmetic,
not a repeated checksum of possibly incorrect SIMD output.

Initial, recurring and final verification, zero error counters, exact identities,
all targeted threads, successful affinity and matching aggregate/per-thread
counts are mandatory. A partially interrupted block receives no verified credit;
a required final bounded block is verified after cancellation, unless an error
or failed initialization makes that inappropriate. Blocks check cancellation
at 32-round intervals. Errors and lost affinity stop execution, with first-error
lane and expected/actual bits retained. No runtime retry with another ISA occurs.

Progress uses the existing bounded O(threads) snapshot publication and timestamp
analyzer. Result and sidecar contracts use the actual kernel name, not FP32 tags.
Derived byte products per verified block are `8 * lanes * 256 * 4` (65,536 or
131,072). Rates use observed publication timestamps, including first/second-half
and per-thread quality, gaps and stalls. These are not FLOPS, machine instruction
counts or proof of saturation. Sample/emulation fixtures remain labelled software
evidence. Source and independent executable provenance retain their existing rules.

## Capability, portability and scalability boundary

The parent intersects native helper support across every online/process-allowed
target CPU, with each x86 probe pinned. AVX-VNNI requires CPUID 7.1 EAX bit 4,
a valid subleaf, AVX2, OS AVX/OSXSAVE and XCR0 XMM/YMM state. AVX-512 VNNI
requires CPUID 7.0 ECX bit 11, AVX512F, AVX2 and enabled XMM/YMM/opmask/ZMM
state (XCR0 mask 0xe6). The workload rechecks after pinning each actual thread.
Unknown/mixed/unsupported target sets fail closed. Model names do not authorize
execution, and a 512-bit VNNI capability does not imply the distinct VEX feature.

GCC target attributes isolate VNNI instructions from baseline compilation and
probe paths. AVX-VNNI requires GNU GCC 11+ and AVX-512 VNNI GNU GCC 8+ in this
implementation. Other compilers conservatively omit these optional regions;
`--print-isa-capabilities` reports compilation separately from physical support.
There are no global `-march=native`, AVX or VNNI flags. A baseline-only build can
exclude both with `LVS_CPU_HELPER_DISABLE_VNNI`. Header changes invalidate normal
helper readiness. No retained hardware binary is rebuilt for development tests.

Memory use is small and bounded per thread (four cases, at most 128 dword outputs
per block), independent of machine RAM/VRAM. Thread count and affinity use the
existing target policy. Older and non-x86 systems keep their original kernels;
unknown architecture, missing compiler support or unavailable OS state cannot
become VNNI execution. No model-specific cap, new thermal threshold or stress
intensity heuristic is introduced. The existing workload level/load contract is
retained; no claim is made that this instruction is the hottest on any system.

## Completed physical acceptance — October 30 and November 2, 2026

Both VNNI families are physically accepted within these tested configurations:
`avx_vnni` on Intel Core Ultra 9 285K across all 24 allowed CPUs (P- and E-cores),
and `avx_vnni` plus `avx512_vnni` on AMD Ryzen 9 9950X across all 32 allowed
logical CPUs. Each hardware/ISA combination completed one 120-second functional
execution and one 600-second sustained execution, with native backend,
extreme/steady work and Power Auto disabled.

All paths below are under `results/`. Functional and sustained directory suffixes
are respectively `ARM64 SVE FP32 FMA Functional Confirmation` and
`ARM64 SVE FP32 FMA Sustained Effectiveness`; these are structural template names,
not the executed ISA. Each diagnostic uses the same suffix plus `_Diagnostics`.

| Execution timestamp | Hardware / ISA | Template | Associated diagnostic timestamp | Verified arithmetic blocks |
|---|---|---|---|---:|
| 2026-10-30_16-46-40 | Ryzen 9950X / avx512_vnni | Functional | 2026-10-30_16-44-17 | 7,729,753,630 |
| 2026-10-30_17-02-35 | Ryzen 9950X / avx_vnni | Functional | 2026-10-30_17-02-24 | 7,354,801,491 |
| 2026-10-30_17-04-55 | Ryzen 9950X / avx512_vnni | Sustained | 2026-10-30_17-04-45 | 38,971,582,363 |
| 2026-11-02_08-48-16 | Ryzen 9950X / avx_vnni | Sustained | 2026-11-02_08-48-08 | 36,745,800,796 |
| 2026-11-02_08-50-26 | Core Ultra 9 285K / avx_vnni | Functional | 2026-11-02_08-50-20 | 9,024,477,005 |
| 2026-11-02_08-52-49 | Core Ultra 9 285K / avx_vnni | Sustained | 2026-11-02_08-52-40 | 43,852,509,956 |

All six executions passed. Worker JSON, timestamped progress sidecars and parent
records establish `x86_vnni_intrinsics`, matching per-thread pinned CPUID/XCR0
eligibility and affinity, independent initial/periodic/final arithmetic
verification, zero mismatches/errors, successful process exits and completed
parent finalization. Final sidecar counts match every thread's terminal worker
record. Sustained runs retain at least 480 seconds of usable analysis, sufficient
all-thread verified progress and no recorded stalled intervals. No shutdown
timeout, forced kill or safety intervention was recorded.

The complete **364-file** scoped source fingerprint, unchanged at run endpoints
and matching the reviewed development source, is:

```text
4f5a3ee3290ade6e109532b091d9d39955c386f9386051db41bfc4944136b6fc
```

The native helper SHA-256 matches prelaunch, running-process and post-execution
identities in all six runs:

```text
d5a52421f973143400b8e4980afebbad96add9d11b851a40b4a68ee1cc30e087
```

Read-only inspection of that matching retained helper confirms eight VEX/YMM
`VPDPBUSD` instructions in `execute_avx_vnni_block` and eight EVEX/ZMM
`VPDPBUSD` instructions in `execute_avx512_vnni_block`. Its compiler metadata
identifies GCC 16.2.1; readiness records GCC and reuse of an existing helper,
not a separately captured target-local rebuild. Source identity, executable
identity and instruction inspection remain distinct evidence.

The associated `_Diagnostics` captures evaluated the original SVE templates
before the run-local overrides and correctly rejected SVE on x86. They are not
successful VNNI readiness captures. Each actual execution's effective profile,
manifest preflight/plan, launch command and Advanced Debug stage selection instead
record the successful explicit VNNI override and all-target eligibility. Retain
both records without rewriting the original diagnostic rejection.

Kernel-log coverage is limited: `dmesg` was permission-denied, while filtered
journal collection returned successfully with no messages. This is not proof
that no kernel or hardware event occurred. Raw telemetry and its source map
retain clock, temperature and package-power observations omitted from the
extended telemetry summaries. The `cpu_clock_mhz` field is CPU0's cpufreq
`scaling_cur_freq`, not an all-core effective-frequency measurement.

In the trimmed sustained windows, average CPU0 clocks / average temperatures /
average package powers were approximately 4,370 MHz / 75.12 C / 186.02 W for
Intel AVX-VNNI, 4,202 MHz / 60.98 C / 155.27 W for AMD AVX-VNNI, and
4,307 MHz / 63.18 C / 157.50 W for AMD AVX-512 VNNI. These observations and
sustained verified work close the intended sustained-stress gate for these
configurations. Arithmetic/integrity acceptance remains a separate decision;
neither decision establishes maximum power, superiority over another workload,
universal hardware acceptance or automatic selection-policy eligibility.

No further repeat is required to close this campaign. Both families remain
experimental, explicit-only specialized workloads; generic vector intents,
ordinary Auto and measured Power Auto eligibility are unchanged.

## Retained physical acceptance procedure

The following is the reproducible procedure used for this milestone, not a
request to repeat the accepted campaign. Its 120-second functional and
600-second sustained criteria remain the established VNNI procedure; they do
not impose an automatic per-variant duration on unrelated future ISA work.

Use the normal complete working-project copy, target-local setup and automatic
native helper build. Do not copy a helper executable from another machine.

For a reproducible CPU-only run without altering saved profiles, use the
existing **ARM64 SVE FP32 FMA Functional Confirmation** profile as a structural
CPU-only template: in Run Setup → Stage Overrides → Configure Stage Workloads,
set **CPU instruction set** to `avx_vnni` or `avx512_vnni`. This is an x86 run-local
workload override, not ARM execution; normal effective review must show the exact
new x86 request, native backend, Power Auto false, no instruction intent, all
allowed CPUs, extreme/steady, 120 seconds, two-second telemetry, and no RAM/GPU/
VRAM/storage. The original saved profile stays unchanged. Keep its authored
functional analysis/trims; capture the actual effective settings to avoid relying
on the original profile name. Enable **Advanced Debug** and execute through normal
automatic preflight; no separate manual Dry Run is required.

Prefer the Core Ultra 9/7 systems for a candidate 256-bit run and Ryzen/Threadripper
systems for a candidate 512-bit run, **only after current-build all-target readiness
confirms the requested flavor**. These names are candidate routing hints, not
capability proof. The local Core Ultra 9 285K read-only probe reports AVX-VNNI
but not AVX-512 VNNI. Older captured acceptance runs did not record the additional
CPUID bits; they do not physically accept either new workload.

For each supported family, begin with the CPU-only 120-second functional run
above. If successful, select the existing **ARM64 SVE FP32 FMA Sustained
Effectiveness** structural profile and apply the same run-local x86 instruction
set override. It already authors 600 seconds, 60-second initial/final trims,
sustained intent and a 480-second minimum; preserve those settings, native
backend, Power Auto false and all allowed CPUs. Set a run-local segment label
identifying the actual VNNI family. The source profile name is historical context,
not executed ISA evidence; the effective configuration and worker must agree.
This requires no new profile, manual JSON edit or saved-profile change. Do not
force an unsupported family on a machine or require a 256-bit VEX test on an
AVX512-only host.

Retain complete execution/Advanced Debug directories, effective profile, source
endpoints, prelaunch/process/post executable identities, helper build/compiler
and pinned capability evidence, worker JSON, progress sidecar and telemetry.
Inspect the actual associated helper's optimized disassembly for the correct
VEX/YMM or EVEX/ZMM instruction in `execute_*_vnni_block`; flags/compiler success
alone are insufficient instruction-execution evidence. Require all threads and
phases, zero mismatches/errors, sustained progress quality, clean worker exit and
normal memory/lifecycle safety. Missing/short evidence is insufficient, never
physical acceptance. Stop on identity/capability/affinity change, arithmetic error,
safety termination, unexpected exit or incomplete final evidence. Do not infer
hardware damage from a failed test. There are no universal VNNI throughput,
power, temperature or efficiency targets.

References: [GCC x86 target attributes](https://gcc.gnu.org/onlinedocs/gcc/x86-Function-Attributes.html)
and [Intel instruction reference](https://www.intel.com/content/dam/develop/external/us/en/documents/319433-024-697869.pdf).
