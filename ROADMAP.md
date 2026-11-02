# Linux Validation Suite Roadmap

This roadmap is the project-status source for completed, deferred, and
undecided work. Deferred or possible work is not committed release scope.

## Status And Current Priority Queue — 2026-10-30

`[x]` marks only the named checkpoint in its stated scope. Proposal/design,
implementation, software validation and physical acceptance are separate gates;
source presence, smoke-test success or ISA selection does not prove physical
acceptance. Existing historical sections retain their original release scope.

### Published baseline and completed acceptance

1. [x] Implement and software-validate current CLI/TUI configuration parity,
   immediate Copy/Save As persistence and temporary workload overrides. Latest
   pre-release checkpoint: 314/314 smoke tests and 81/81 profiles valid. This is not
   hardware acceptance; the UX does not require physical stress to validate it.
2. [x] Physically confirm corrected EGL readback/scheduling and geometry, and
   Core Ultra OpenCL assigned-target attainment with sampled integrity, guards
   and cleanup on the exercised configurations. This is not exhaustive memory
   verification, physical-residency proof or acceptance of every backend.
3. [x] Complete corrected Vulkan allocation-path integration acceptance:
   dedicated/shared device memory, separately protected host staging, alignment
   accounting and cleanup. The changes and negative safety checks are
   implemented, software-validated and physically confirmed on tested NVIDIA,
   AMD and Adreno configurations. NVIDIA large-descriptor bounds, AMD per-buffer
   submission scheduling, terminal publication and final MSI compute-aware
   shutdown acceptance are complete. Keep unresolved I/O/persistence incidents separate
   from workload correctness and do not declare their cause fixed.
4. [x] Complete current ARM64 `highest_verified_vector` physical integration
   confirmation on Spark and Snapdragon. Capability selection, actual SVE/NEON
   execution, all-thread verification and truthful reporting passed. This does
   not accept wider SVE lengths or other hardware configurations.
5. [x] Complete v0.5.3-alpha inventory, version/documentation reconciliation,
   final review, commit, annotated tag and GitHub publication as an **alpha
   prerelease**. Its physical acceptance campaign is closed within the recorded
   boundaries; post-release development is not retroactively part of that release.

### Immediate development order — Spark first

After stabilizing existing LVS functionality, follow this order:

1. [ ] Finish the adopted, worthwhile specialized **ARM64 work on NVIDIA GB10
   Spark**, prioritizing genuinely different arithmetic and execution behavior.
   Use the acceptance gates below to decide integrity coverage versus sustained
   stress value; do not implement every available ARM extension.
2. [ ] Physically validate shared, supported **NEON implementations on Snapdragon
   X1 Plus**. Preserve baseline/non-SVE operation and fail-closed rejection of
   absent SVE or specialized capabilities; Spark success does not substitute for
   this portability evidence. For the current SVE2 milestone, the next ARM64
   validation step is Snapdragon native baseline compatibility and correct
   rejection of unsupported `sve2_smlal`, not an assumed SVE2 execution campaign.
3. [ ] Return to outstanding **x86-64 ISA work**: BF16/FP16 and separately gated
   AMX work. VNNI physical acceptance is now complete within the configurations
   below, and the milestone is committed in
   `8716340630a5e5df070957e13ddd3699cb7dda97`.
   Additional x86 development follows Spark/Snapdragon priorities.
4. [ ] Proceed to the existing **dynamic GPU, CPU and platform stress sequence**
   after the applicable ISA prerequisites are completed or explicitly,
   responsibly deferred. Record each deferral's unavailable capability/hardware,
   evidence gap, risk and reopening condition; do not label it physically accepted.

This is planning, not authorization to start workloads or a new hardware campaign.
Optional or hardware-gated candidates are not automatic prerequisites for every
release or an indefinite requirement to wait for unavailable hardware.

## Published In v0.5.3-alpha

- [x] Close the eight-system October 29 hardware wave and October 30 MSI S2/S4
  shutdown confirmation within their recorded support boundaries.
- [x] Preserve independent CPU/RAM verification, automatic source/executable
  provenance, physical GPU identities, shared-memory guards and legacy readers.
- [x] Correct EGL readback pattern/scheduling, scalable allocation geometry,
  bounded OpenCL allocation/readback/publication scheduling, Vulkan descriptor
  bounds and per-buffer stateful submissions, cleanup and incomplete-run verdicts.
- [x] Provide shared validated CLI/TUI run-local workload and physical-target
  overrides, immediate Save As/Copy persistence and captured-profile replay.
- [x] Archive the five correction profiles byte-for-byte outside ordinary
  discovery, with retained historical operator instructions.
- [x] Approve and commit the development inventory in `00772b2c9a233680827bc765cd368e23677d6d2b`.
- [x] Commit the separate v0.5.3-alpha identity correction in
  `a229ceb09870e9c4723a13091f0e4e0342717fdf`, create its annotated tag and publish
  the GitHub **alpha prerelease**. No published history was rewritten.

See [v0.5.3-alpha scope, limitations and physical-source provenance](docs/release_notes_v0.5.3-alpha.md).

## Prepared In v0.5.2-alpha

Historical release boundary at publication; subsequent development status is
tracked above and in the ISA section, not retroactively added to this release.

- Physically accepted NEON FP32/FMA on Spark and Snapdragon, independent
  arithmetic verification, all-thread integrity, and sustained verified progress.
- Vulkan stall diagnostics (historical interruption cause still unresolved),
  physically accepted fail-closed GPU targeting, and inventory UUID/memory fixes.
- Automatic offline source provenance, normal reports/QA source comparisons,
  and bounded local Git correlation, without manual stamps or deployment changes.
- SVE FP32/FMA implementation is committed but experimental and physically
  unverified. Release policy permits explicit functional testing only; no
  implicit Auto, instruction-intent, or Power Auto promotion.

See [v0.5.2-alpha release scope](docs/release_notes_v0.5.2-alpha.md).

## Completed Through v0.2.0-alpha

- Established output-contract classification and the forward-only casing and
  unit policy for new LVS-owned fields.
- Preserved compatibility aliases, raw/vendor boundaries, and the intentionally
  legacy `parsed_results_custom.json` contract.
- Completed the Storage Health baseline with normalized SMART/NVMe evidence and
  explicit raw-provider boundaries.
- Completed the Storage Benchmark baseline with standalone and profile-stage
  workflows, sequential all-internal mode, system-drive safeguards, CoW/Btrfs
  warnings, and normalized/raw artifact separation.

## Completed In v0.3.0-alpha

- Completed Phase 1 contract clarifications covering legacy unit meanings,
  compatibility aliases, enum domains, storage-provider semantics, and
  deprecation tracking without changing payloads.
- Completed Phase 2A contract identities for `run_manifest.json`,
  `dependency_check.json`, and `telemetry_source_map.json`.
- Completed Phase 2B additive telemetry unit aliases. Existing binary-GiB
  `_gb` telemetry fields remain unchanged, while unit-correct `_gib` aliases
  are available to new consumers.
- Completed post-release operator and documentation cleanup for storage
  dependencies and safeguards, GUI status, CPU cooler/PPT/TDP metadata, and
  Phase 1 historical status.
- Added the optional `all_internal_non_root_low_occupancy` Storage Benchmark
  target mode with a configurable filesystem-occupancy threshold, unconditional
  root/system-drive exclusion, and execution-time occupancy and free-space
  rechecks. Existing `all_internal` and `selected_target` modes and the
  ready-made Storage Benchmark profiles remain unchanged.
- Added first-class AArch64 execution alongside x86_64, including native scalar
  and NEON CPU helpers, stress-ng and Python CPU paths, native/stress-ng/Python
  RAM paths, helper readiness, targeting, affinity, topology, telemetry, and
  evidence behavior.
- Added platform GPU discovery and validated Qualcomm Adreno Vulkan compute,
  transfer/readback, and stateful-memory operation on AArch64.
- Unified RAM and shared-GPU memory planning with reserve-once accounting,
  launch-time worker assignments, dedicated-VRAM isolation, and a runtime
  allocation guard.
- Hardened CPU targeting around online and process-allowed CPU intersections,
  including sparse and nonzero CPU sets, SMT topology, Intel P/E hybrid-core
  CPUID classification, and common-safe ISA selection across every targeted
  CPU.
- Added explicit `baseline_vector`, `high_throughput_vector`, and
  `highest_verified_vector` instruction intents with architecture-aware
  resolution, AArch64 NEON tier-collapse disclosure, and fail-closed exact ISA
  behavior.
- Added Power Auto as a distinct cross-backend policy comparing viable native,
  stress-ng matrixprod, and Python PBKDF2 candidates. It uses measured package
  power when a trustworthy measured winner exists, the validated thermal
  fallback on AArch64 otherwise, and the compatibility/capability fallback on
  x86_64 otherwise.
- Converted the PL Validation family, QA System Test Short v2, and Quick Test to
  architecture-aware instruction intent; Power Test now explicitly requests
  Power Auto.
- Corrected Python RAM zero-pattern verification, stress-ng final metrics and
  verification retention, native RAM evidence, AMD APU and small-dGPU routing,
  shared Vulkan heap selection, stateful buffer allocation, multi-GPU planning,
  stable physical telemetry association, and selected-result TUI upload
  targeting.
- Archived completed hardware campaign profiles outside normal discovery while
  retaining them for historical reproduction.
- Completed cross-architecture hardware acceptance for the current development
  wave, including Qualcomm Oryon/NEON, Qualcomm Adreno Vulkan, Intel hybrid P/E
  common-safe ISA behavior, measured Intel/AMD Power Auto, and the AArch64
  no-package-power fallback. No current acceptance failure remained at
  closeout.

## Deferred Compatibility And Output Work

The remaining output-standardization work is divided into two coordinated,
deferred milestones. Neither milestone changes the existing
`parsed_results_custom.json` compatibility contract.

### Phase 3 — Canonical-First Result Reader Compatibility

- Add identity-aware result resolution and a normalized internal result view
  for validation, comparison, QA, report, inventory, and importer-facing
  adapters.
- Readers prefer recognized canonical names when available and fall back to
  legacy names without operator-facing deprecation warnings.
- Preserve all legacy fields and aliases. Phase 3 changes readers and adapters
  only; it does not emit `parsed_results.json`.
- Prove legacy-only, canonical-only, and dual-artifact equivalence with frozen
  fixtures before changing artifact selection behavior.

### Phase 4 — Canonical Parsed Result v1 Dual-Output Migration

- Emit an identified canonical `parsed_results.json` using fixed snake-case
  LVS-owned keys and explicit units while continuing to emit the unchanged
  `parsed_results_custom.json` legacy compatibility artifact.
- Preserve useful OCCT-style structure and documented dynamic-label,
  raw-provider, vendor, and backend boundaries rather than mechanically
  converting every key.
- Update QA, validation, comparison, reports, and importers through the Phase 3
  compatibility layer as one coordinated migration.
- Apps Script, SQL, and other external importer changes require representative
  fixtures, identity-aware artifact selection, compatibility planning, and a
  tested rollback path.

Storage Benchmark v1 aggregate reshaping is outside Phase 3 and Phase 4. Any
such change requires a separately approved, versioned benchmark-contract
milestone and does not authorize new storage testing, comparison, or reporting.

## Adopted CPU ISA Stress Roadmap

LVS is a **hardware stress and stability validation suite**, not an exhaustive
CPU instruction-set compatibility tester. Adopt workloads that exercise
meaningfully different arithmetic, execution resources or operating conditions,
provide independently verified fault detection, or add useful sustained stress.
Newer, wider, supported or architecturally different instructions do not by
themselves prove higher power, independent execution hardware, greater stability
coverage or a need for a separate sustained workload. Architectural coverage and
physically demonstrated incremental stress effectiveness must be reported separately.

A useful workload need not produce the highest wattage: different arithmetic,
execution behavior and fault-detection opportunities can justify multiple modes.
Conversely, different instruction semantics alone do not establish useful
incremental stress coverage. Apply the purpose and evidence gates below rather
than implementing an extension checklist.

### Complementary CPU operating conditions

Preserve two deliberate, complementary sustained-stress objectives rather than
optimizing every CPU mode for the same operating region:

- **High-frequency sustained stress:** relatively lightweight, continuously
  independently verified work intended to exercise stability at potentially
  higher sustained clocks. Existing x86-64 scalar and SSE2/128-bit SIMD are
  important baseline candidates; ARM64 scalar and fixed-width NEON provide
  corresponding baseline capabilities.
- **High-compute-demand sustained stress:** intensive independently verified
  arithmetic targeting demanding computational resources. Existing x86 AVX,
  AVX2 and AVX-512 families, ARM NEON FMA/SVE, and adopted specialized integer
  dot-product and matrix kernels contribute where supported and accepted.

These are workload objectives, not guaranteed ISA properties or a ranking of
instruction sets. Actual sustained clocks, power, thermal limitations and stress
effectiveness require physical measurements. Do not assume AVX always reduces
frequency, that SVE is inherently more demanding than NEON, or that the two use
independent execution hardware. Spark's observed SVE acceptance is at **128-bit
VL**, not evidence of a wider-vector operating region.

Existing SSE2 coverage is sufficient for the x86 baseline SIMD objective: it
already provides verified fixed-width 128-bit SIMD work alongside scalar work.
Dedicated SSE3/SSSE3/SSE4 stress families are not required to preserve that
operating-region objective; extra instruction semantics alone do not establish
incremental stability coverage. ARM likewise needs no artificial SSE-equivalent
ISA hierarchy: scalar and NEON baselines plus justified specialized workloads
serve the objectives under ARM's actual capabilities.

Keep operating-region goals separate from existing selection policies.
`baseline_vector` requests the architecture's baseline vector tier;
`high_throughput_vector` requests its established throughput-oriented tier;
`highest_verified_vector` requests the highest eligible tier under its existing
verification policy. None promises a measured clock, power level or stress
optimum. Power Auto remains a separate measurement-driven policy with its
existing telemetry requirements and fallbacks. This requirement changes no
selection order, eligibility, promotion policy or accepted functionality, and
does not replace the established VNNI functional/sustained acceptance procedure.

### Two separate acceptance decisions

**A — ISA arithmetic/integrity acceptance**

For each adopted implementation:

- [ ] Prove genuine target-specific instruction emission and actual execution;
  isolate instruction-specific compilation so unsupported hosts retain baseline
  kernels. Runtime capability, OS state and pinned-core/common-target eligibility
  remain authoritative on heterogeneous systems.
- [ ] Independently calculate reference results for the instruction's signedness,
  accumulation, overflow, rounding, saturation or matrix semantics as applicable.
  Demonstrate corruption detection, bounded verification and truthful progress,
  affinity, termination and cleanup evidence; unsupported or failed requests
  must fail closed without silent ISA substitution.
- [ ] Physically confirm the intended implementation and verification on suitable
  capability-proven hardware, within the specific recorded configuration.

An ISA can be accepted for arithmetic/integrity coverage without becoming a
primary sustained stress workload. Compiler flags, disassembly, simulation and
feature detection are software/capability evidence, not physical acceptance by
themselves. These unchecked items are a reusable gate template for pending work,
not a reopening of completed acceptance below.

**B — Sustained stability-stress acceptance**

- [ ] Establish a repeatable sustained workload with meaningful verified activity,
  arithmetic integrity, progress coverage, bounded cancellation/cleanup and the
  existing safeguards, reserves and thermal protections.
- [ ] Choose duration, repetitions and evidence according to the workload's
  purpose and observed behavior. Physically evaluate its stress characteristics,
  telemetry availability and incremental value against relevant existing modes.
  Distinguish measured effects from architectural hypotheses or missing telemetry.
- [ ] Decide whether the mode merits standalone sustained use, complementary
  coverage or integrity-only availability. No universal wattage, saturation or
  superiority threshold is implied.

A separate 600-second campaign is **not automatically mandatory for every
precision variant or closely related flavor** merely because it is listed here.
Existing completed 600-second campaigns retain their actual acceptance; future
campaigns require purpose-specific duration and coverage decisions. A previous
per-flavor test recipe is a candidate procedure, not a universal acceptance gate.

Generic ISA selection and thermal/power selection remain separate. Power Auto
continues its established measurement-driven selection where trustworthy telemetry
exists and its documented fallbacks otherwise. Newly implemented specialized
kernels are not automatically eligible for ordinary Auto, generic vector intents
or Power Auto. Any later promotion needs an explicit policy/effectiveness review;
capability alone does not authorize it.

### Current x86_64 kernels and adopted specialized scope

The released general and Power Auto native kernels remain `scalar`, `sse2`,
`sse2_int`, `avx`, `avx_fma`, `avx2`, `avx2_fma`, `avx512_fma`, and
`avx512_int`, with their existing common-capability requirements and scoped
physical acceptance. This plan neither expands nor retracts that accepted scope.

The adopted specialized x86-64 scope remains AVX-VNNI/256-bit VNNI, AVX-512
VNNI, AVX-512 BF16, AVX-512 FP16 and the dedicated Intel AMX INT8/BF16/FP16
tile/matrix family. They are not new ordinary top-level SIMD tiers. Future
Power Auto consideration is conditional on the separate policy and evidence
review above, not an implemented or promised promotion.

**Committed post-release VNNI milestone:** both variants were implemented,
software-validated (**320/320 smoke tests**) and physically accepted in commit
`8716340630a5e5df070957e13ddd3699cb7dda97`. They use genuine `VPDPBUSD`,
independent integer verification and verified progress. They are **not part of
published v0.5.3-alpha**. Both physical acceptance decisions are complete within the
tested configurations below. Ordinary Auto,
generic vector intents and Power Auto continue to exclude these specialized modes.

- [x] Implement AVX-VNNI / 256-bit VNNI with bounded independent verification
  (committed VNNI milestone).
- [x] Implement AVX-512 VNNI with bounded independent verification
  (committed VNNI milestone).
- [x] Software-validate VNNI arithmetic, instruction emission, selection and lifecycle.
- [x] Physically accept AVX-VNNI / 256-bit VNNI arithmetic/integrity on Core Ultra
  9 285K (24 allowed CPUs) and Ryzen 9950X (32 allowed logical CPUs).
- [x] Physically accept AVX-512 VNNI arithmetic/integrity on Ryzen 9950X
  (32 allowed logical CPUs).
- [x] Accept sustained verified stress under gate B in those configurations:
  three 120-second functional and three 600-second sustained executions passed
  on October 30 and November 2, 2026, with at least 480 usable seconds per
  sustained run, zero mismatches, all-thread affinity and independent
  initial/periodic/final verification, successful exits and parent finalization.

Matching native-helper inspection confirms genuine VEX/YMM and EVEX/ZMM
`VPDPBUSD`. All six runs share the complete 364-file scoped source fingerprint
`4f5a3ee3290ade6e109532b091d9d39955c386f9386051db41bfc4944136b6fc`
and prelaunch/process/post-execution helper SHA-256
`d5a52421f973143400b8e4980afebbad96add9d11b851a40b4a68ee1cc30e087`.
Associated diagnostic captures rejected the original SVE templates on x86;
successful run-local VNNI preflight and actual execution evidence are retained
separately. Kernel visibility is limited by denied `dmesg` access and empty
filtered journal captures. Recorded CPU clocks are CPU0 cpufreq observations,
not all-core effective-frequency measurements.

See [the VNNI contract, six-run acceptance record and retained procedure](docs/vnni_dot_product_contract.md).
Arithmetic/integrity and measured sustained-stress acceptance remain separate;
these results establish useful sustained verified activity within the tested
configurations, not maximum power, universal stress superiority or automatic
ISA promotion. The established VNNI durations remain intact without imposing a
600-second campaign on every future instruction flavor. This physical campaign
is closed; next implementation work is specialized ARM64 on Spark, followed by
Snapdragon compatibility and physical acceptance as ordered above.

Remaining adopted specialized work, deferred behind Spark/Snapdragon priorities:

- [ ] AVX-512 BF16.
- [ ] AVX-512 FP16.
- [ ] Dedicated Intel AMX INT8 tile/matrix workload.
- [ ] Dedicated Intel AMX BF16 tile/matrix workload.
- [ ] Dedicated Intel AMX FP16 tile/matrix workload.

AMX subfeatures require independent runtime capability, compiler, OS tile-state
and execution checks. AMX INT8 or BF16 availability does **not** establish AMX
FP16 support. Each arithmetic implementation needs gate A; gate B depends on its
intended stability-stress role, not its presence in this list.

### AArch64 general SIMD work

Accepted AArch64 kernels are `scalar`, integer `neon`, and independently
verified `neon_fp32_fma`. Spark and Snapdragon functional and sustained NEON
acceptance is complete. `sve_fp32_fma` is implemented with scalable arithmetic,
per-thread VL initialization, independent verification, and progress reporting,
and Spark functional compilation, execution, preserved-binary disassembly and
600-second sustained acceptance have passed at 128-bit VL. Current-build
Snapdragon non-SVE compilation, rejection and scalar/NEON execution have passed.
The original functional run lacked a launch hash; the sustained run records a
matching process executable hash. Wider-VL physical acceptance remains pending.
SVE remains experimental but is deliberately eligible through the operator's
ARM64 `highest_verified_vector` intent, separately from ordinary Auto/Power Auto.

The adopted general SIMD work is:

- [x] Spark SVE functional build/instruction/execution acceptance completed, with
   documented retrospective executable-association limits.
- [x] Spark sustained effectiveness and current Snapdragon negative-capability
   portability completed. Wider-vector-length physical validation remains
   outstanding; see [the SVE contract](docs/sve_fp32_fma_contract.md).
- [x] Implement and software-validate ARM64 `highest_verified_vector`, ranking
   common-capable implementations with
   established software-verification contracts: SVE FP32/FMA, NEON FP32/FMA,
   then integer NEON. This is not a physical-coverage or performance ranking.
   Baseline/high-throughput intents, ordinary Auto and Power Auto are unchanged.
- [x] Physically confirm highest-vector selection integration on Spark (SVE,
  128-bit VL) and Snapdragon (NEON FP32/FMA); the October 29 current-build
  confirmation is separate from the earlier arithmetic campaigns.
- [ ] Physically validate wider SVE vector lengths and other implementations;
  software scalable/mixed-VL fixtures do not close this gate.
- [x] Physically accept and evaluate explicit SVE2 integer work on Spark:
  gates A/B both PASS at inherited 128-bit VL across all 20 allowed CPUs.
  This has separate evidence from existing SVE FP32/FMA acceptance.

Current ARM instruction intents resolve as follows:

- `baseline_vector` selects NEON.
- `high_throughput_vector` prefers NEON FP32/FMA, then integer NEON.
- `highest_verified_vector` prefers common SVE FP32/FMA, then NEON FP32/FMA,
  then integer NEON. Actual per-thread VL and software verification are
  established at execution; prior physical acceptance is separate evidence.
- Explicit `neon`, `sve` and exact FP32/FMA requests retain their identities or
  fail closed. Explicit `sve2_smlal` is implemented in uncommitted development;
  it is excluded from every generic intent and physically accepted only within
  the Spark configuration recorded below.

SVE and SVE2 must not be encoded as automatically hotter than scalar or NEON.
The published v0.5.2-alpha policy excluded SVE from generic intents. This
change published in v0.5.3-alpha affects only the deliberate highest-vector
intent. Ordinary Auto stays NEON/scalar and Power Auto excludes SVE. A wider
inherited VL is software-validated, never thereby declared physically accepted.

### AArch64 specialized stress flavors — Spark-first work

The adopted ARM64 scope is deliberately finite:

- [ ] NEON FP16/FHM (`asimdhp` / `asimdfhm`), with each required subfeature gated.
- [ ] NEON DotProd (`asimddp`).
- [ ] NEON I8MM.
- [ ] NEON BF16.
- [x] Implement the distinct SVE2 signed widening integer workload below
  (uncommitted `sve2_smlal`); both physical gates PASS on Spark at 128-bit VL.
- [ ] SVE I8MM.
- [ ] SVE BF16.

Except for the implemented and Spark-accepted SVE2 kernel, these remain adopted
future implementations without specialized ARM64 physical acceptance.
Prioritize on Spark by demonstrated capability and worthwhile
arithmetic/execution differences, then confirm the shared supported NEON paths
on Snapdragon X1 Plus. Require separate runtime eligibility for each family;
Snapdragon portability includes correct rejection of unavailable capabilities.
Do not infer Snapdragon support from Spark execution or a shared architecture name.

NEON and SVE variants cover distinct instruction behavior but may share execution
hardware. Neither independent pipelines nor additive thermal/power demand may be
assumed. Evidence must establish their incremental stress effectiveness before
claiming a distinct sustained-stress benefit. Integrity acceptance can still be
useful when that incremental benefit is absent or not yet established.

**Implemented SVE2 integer workload (uncommitted, Spark physically accepted):**
`sve2_smlal` performs independently verified signed widening integer
multiply-accumulate in normal non-streaming SVE2, using real `SMLALB` / `SMLALT`
even/odd halfword mappings, signed 16-bit inputs and 32-bit accumulators. This is SVE2 instruction coverage, not SME coverage.
These exercise widening integer arithmetic and alternating source-element
mapping that SVE FP32/FMA does not cover; separate physical execution resources
or improved fault coverage are hypotheses, not established facts. Require:

- [x] Isolated optional SVE2 compilation and genuine opcode emission checked
  by cross-compiling the actual native worker; runtime HWCAP/HWCAP2 eligibility
  and unsupported-request rejection are software-tested. This does not prove
  target-side execution or physical acceptance.
- [x] Independent wide-integer reference results, signed extrema, exact defined
  accumulator wraparound, both bottom/top source mappings and deterministic
  corruption detection across all active vector lanes.
- [x] Software-validate inherited per-thread VL and affinity, bounded work/progress and
  guarded memory/tail handling; do not assume the arithmetic instructions
  themselves supply predication or memory safety.
- [x] Gate A physical arithmetic/integrity PASS on NVIDIA GB10 Spark across
  20/20 allowed CPUs, with inherited 128-bit VL, independent initial/periodic/
  final arithmetic verification, zero mismatches, correct affinity and successful
  worker exits and parent finalization.
- [x] Gate B sustained verified-stress PASS in that configuration: the
  November 2 functional run completed 120.219 seconds and 7,575,089,813 verified
  blocks; the sustained run completed 601.111 seconds and 37,882,653,161 blocks.
  Its usable window is 481.111 seconds at approximately 63.024 million verified
  blocks/s, with zero recorded progress stalls. This demonstrates sustained
  computational activity, not maximum-power effectiveness or superiority over
  SVE FP32/FMA.

Target-local GCC 13.3.0 compilation and read-only disassembly of the actual
executed helper confirm four `SMLALB` and four `SMLALT` instructions, with four
bottom/top source pairs and eight distinct accumulators. The complete 365-file
physical source fingerprint is
`2cee8d6061d334dedb180fc1ed4b984a54b9265f4846518ab4baa1684b53b9ca`;
prelaunch/process/post-execution helper identities match
`92c3f3362d82daf1dceb4d1e5c8b15c2d12f40f9f5439eebe45002a615aa3137`.
Matching executable evidence is retained locally at
`results/cpu_stress_helper_arm64`, outside the committed inventory.

CPU-specific temperature/package power were unavailable; seven platform thermal
zones remained monitored. Kernel visibility is limited by denied `dmesg` access
and empty filtered journal captures. Per-core cpufreq observations are not
independently measured effective clocks. These limitations remain visible;
Spark acceptance is confined to the actual tested 128-bit configuration.

**Software checkpoint:** 326/326 complete smoke tests pass; all 81 active and
archived profiles remain valid with five unchanged advisories. Cross-emission,
independent reference and labelled lifecycle fixtures do not constitute physical
SVE2 execution. No new hardware workload was run on the development host.

The [SVE2 contract and Spark operator procedure](docs/sve2_smlal_contract.md)
record both completed physical gates, exact execution/diagnostic folders and
scalability/portability boundaries. Original diagnostic captures inspect the SVE
FP32/FMA templates; successful run-local SVE2 preflight and actual execution
evidence are separate. Software lifecycle/scalable-VL emulation cannot accept
other hardware or widths. No further Spark repeat is required. Next is
Snapdragon native baseline compatibility and unsupported-SVE2 rejection;
existing Auto, vector intents, measured Power Auto and accepted FP32/FMA/VNNI
behavior are preserved.

The design target follows Arm's [SVE2 widening multiply-add example](https://documentation-service.arm.com/static/6659c722876c8d213b7870d3)
and [ACLE instruction mappings](https://arm-software.github.io/acle/main/acle.html).
It is one bounded stability-validation kernel, not a commitment to cover every
SVE2 instruction or to generalize current Spark SVE acceptance.

### Exclusions and hardware-gated evaluation candidates

The following remain **outside mandatory standalone ISA stress scope**:

- **x86-64:** SSE3/SSSE3/SSE4.x; AES/SHA/GFNI and related crypto operations;
  BMI/ADX; AVX-512 IFMA; VBMI and miscellaneous permutation extensions.
- **ARM64:** AES/SHA/SM3/SM4/CRC and SVE crypto; SVE bit permutation; FCMA/RDM
  and miscellaneous DSP extensions.

In particular, AVX-512 IFMA is not promoted merely because its arithmetic differs
from VNNI. Different semantics alone do not prove worthwhile incremental stability
coverage. These exclusions concern standalone mandatory workloads, not incidental
supporting instructions within otherwise justified implementations.

**Noncommitted, low-priority evaluation only:** consider whether compact,
independently verified cryptographic instruction integrity diagnostics across
x86-64 and ARM64 would add useful fault-detection coverage. There is no adopted
crypto implementation milestone, no mandatory individual crypto family, no
sustained crypto stress campaign and no dependency on this evaluation for the
current priority queue. Scope, value, safety and acceptance require a future decision.

**Hardware-gated deferrals:** AVX10 and SME/SME2 remain deferred evaluation
candidates, not immediate development requirements. Suitable physical hardware,
authoritative runtime capability evidence, compiler support and a specific
stress/stability justification are required before adoption or implementation.
Processor model names alone establish neither capability nor availability.
Do not add further ISA families without such a justification.

### AArch64 evidence and portability boundary

Earlier Spark diagnostic notes report Cortex-X925 plus Cortex-A725 CPUs,
GCC 13.3.0, a 16-byte/128-bit SVE vector length, and `asimd`, `fphp`, `asimdhp`,
`asimddp`, `asimdfhm`, `sve`, `sve2`, `svei8mm`, `svebf16`, `i8mm`, and `bf16`
CPU flags. Physical compiler probes passed for `-march=armv8-a+sve`,
`-march=armv9-a+sve2`, `-march=armv9-a+sve2+i8mm`, and
`-march=armv9-a+sve2+bf16`. This proves compiler capability only; it does not
establish runtime acceptance of SVE2 or specialized kernels. Separately, Spark's
October 20 SVE functional execution established all-thread VL 16 bytes, successful
native compilation and verified execution; inspection of the preserved helper
confirmed optimized scalable FP32 FMA instructions. Exact historical launch-hash
association was not recorded for that functional run. The subsequent sustained
run passed with matching prelaunch/process/post-execution hashes. Wider VLs
remain physically unvalidated; model names authorize nothing.

The baseline ARM64 helper must continue to build and run on the Snapdragon X1
Plus with scalar and NEON only. Do not compile the complete helper globally with
an SVE/SVE2-only `-march`. Future SVE, SVE2, and specialized implementations
must use isolated feature compilation, targeted functions or objects, compiler
capability probes, and appropriate runtime HWCAP/HWCAP2 checks. Snapdragon
current-build portability regression passed after the Spark ISA work; future
native ISA changes must continue preserving this non-SVE path.

## Proposed Dynamic Stress And Diagnostics Sequence

Technical reference: [Dynamic Stress and Diagnostics planning draft, revised
2026-10-23](docs/planning/LVS_Dynamic_Power_Stress_Roadmap_Revised_2026-10-23.md).
ROADMAP.md remains authoritative. The reference is retained as a detailed draft;
its "not yet applied" and Git-handoff wording records its drafting context,
not current project status or permission to commit. This section replaces the
earlier brief GPU transient-load/spike-hammer note.

### Milestone Status And Dependencies

The priority sequence is recorded; every new workload remains proposed, with
design approval and implementation separately gated. No proposed preset below
is an existing profile, command or menu entry.

| Milestone | Dependency / purpose | Proposal recorded | Design approved | Implemented | Software-validated | Physically accepted |
| --- | --- | --- | --- | --- | --- | --- |
| 1A — Calibrated sustained high-power GPU foundation | Close current priority queue first; establish repeatable verified high demand | [x] | [ ] | [ ] | [ ] | [ ] |
| 1B — High-amplitude GPU power transitions | Accept 1A's high-demand foundation before transitioning into/out of it | [x] | [ ] | [ ] | [ ] | [ ] |
| 1C — GPU OC/UV and workload-diversity stability | Build on accepted 1A/1B; stepped, seeded and mixed operating-region coverage | [x] | [ ] | [ ] | [ ] | [ ] |
| 2 — CPU core-count / burst / hotspot hammer | After milestone 1; reuse proven native ISA/verification and authoritative topology | [x] | [ ] | [ ] | [ ] | [ ] |
| 3 — Coordinated CPU/GPU platform transients | Accept individual milestone 1/2 paths, then synchronize and calibrate combined load | [x] | [ ] | [ ] | [ ] | [ ] |

Later queue (unscoped proposals, not implementation commitments):

- [ ] **4 — review substantial storage/network expansion** after usable
  dynamic-stress acceptance.
- [ ] **5 — extensive HTML/report diagnostics modernization** after workload/
  interval contracts stabilize.

Milestone 5 concerns retained results, readers and contract acceptance, not new physical
stress tests solely to change presentation. Necessary evidence-schema groundwork
belongs alongside each earlier workload, not only in milestone 5.

### Milestone Scope And Acceptance Gates

- **1A:** Compare complementary graphics/render, compute/shader and
  memory/bandwidth candidates using authoritatively bound supported backends.
  Calibration must be bounded, safe and device-local; retain a fixed,
  repeatable candidate and measured envelope, not a perpetual wattage search.
  Do not assume one API wins across vendors or change driver/firmware limits.
  Provide the sustained high-demand mode independently of transient trials.
  Preserve thermal shutoff where available, bounded duty/duration and
  conservative handling of missing critical sensors.
  Report power/thermal limiting and unobserved measurements rather than
  silently treating them as achieved target power.
- **1B:** Transition calibrated high demand to/from light/idle work, including
  low-medium-high and asymmetric dwell sequences. Prefer initialized, retained
  resources and real dispatch/work-mix changes; allocation churn is a separate
  future decision. Record commanded and achieved phases, dispatch/completion,
  settling, missed cycles and timestamp uncertainty. Measured pilots must set
  feasible dwell ranges; seeded bursts, randomized cycles and cold/hot recovery
  remain bounded design candidates, not promised timing capabilities.
- **1C:** Use stepped/seeded intensity and diverse execution patterns, with
  repeated return to high demand. Record operator-selected stock/OC/UV settings
  and permitted tuning metadata; allow controlled A/B comparisons without
  automatically changing voltage, power limits or firmware. A clean run covers
  only its actual pattern, environment and duration.
- **2:** Vary allowed physical-core counts before all allowed hardware threads;
  clip safely on small systems. Use authoritative hybrid core classes, SMT
  siblings, AMD CCD locality and AArch64 clusters where available, plus hot-core
  rotation and bounded burst/duty modes. Preserve actual affinity and verified
  progress through transitions. Calibrate maximum package power separately
  from lightly threaded high-boost/hotspot behavior; the highest-watt kernel
  need not cover the hottest-core condition or desktop-like boost behavior.
  Preserve both CPU operating objectives defined above: evaluate lightweight
  verified baselines and high-compute-demand modes across core-count, burst,
  frequency and hotspot conditions. Measure achieved clocks and operating
  regions rather than inferring them from ISA labels; retain integrity and
  progress evidence through transitions. These dynamic trials complement,
  rather than replace, sustained acceptance of each intended stress mode.
- **3:** Share one phase timeline across verified workers for coincident ramps,
  offset/anti-phase swings and alternating bursts. Include separate combined
  sustained-power, abrupt-step and anti-phase modes. Calibrate achieved platform
  demand rather than adding nominal percentages; contention or package limits
  can reduce GPU power. Preserve the single host-memory pool/reserve on UMA.
- **4:** Preserve existing Storage Health/Storage Benchmark baselines. New
  dedicated storage stress and NIC/network scope require separate decisions,
  non-destructive/system-drive safeguards and explicit peer prerequisites.
- **5:** Add phase-aligned plots, event tables and comparisons only after the
  evidence contracts stabilize. Preserve raw/extended/compatibility results,
  segment associations and gap disclosures. Show thermal limits and base/boost
  references only with trustworthy sensor/model/core-class provenance. Any
  proposed deficit evaluation needs loaded, stable, phase-qualified windows,
  trims, duration/margin and quality rules; idle, transitions, intentional caps,
  absent sensors or a core-count change must not become automatic hardware FAIL.
  Observation, reliable throttle diagnosis and arithmetic failure stay separate.

Common gates for new stress milestones (all remain outstanding):

- [ ] Preserve the [hardware-scalability contract](ARCHITECTURE_MAP.md#hardware-scalability-contract),
  authoritative physical identity and safety limits across low-resource,
  high-resource, heterogeneous and missing-capability configurations.
- [ ] Approve backend coverage, concise operator presets and measured pilot
  durations/dwell/duty/abort limits. Proposed presets are **GPU Maximum Power**,
  **GPU Power Transitions**, **GPU OC/UV Stability**, **CPU Core-Count/Boost** and
  later **Platform Power Transitions**; keep advanced tuning secondary.
- [ ] Define versioned/additive phase, verification, telemetry and incident
  evidence early. Keep functional integrity, achieved stress adequacy/coverage
  and incident outcomes separate; a weak but error-free workload is not enough
  to accept the high-power/transient feature. Missing evidence is not zero or
  success; absent critical verification must block acceptance.
- [ ] Prove bounded verification cadence, transition scheduling, host storage,
  cancellation, emergency handling, cleanup and reserve/UMA accounting in
  deterministic regressions, including failed and interrupted operations.
- [ ] Physically compare achieved envelopes against demanding known-good and
  relevant gaming loads on representative eligible AMD/NVIDIA/Intel paths,
  dGPU/iGPU where feasible. Include controlled stock/OC/UV and platform A/B
  coverage where justified; accept only the backend/device paths exercised.
- [ ] Retain requested intensity, verified progress, telemetry and achieved
  load as distinct facts. Neither 100% busy nor nominal TGP/TBP proves maximum
  power, and no universal wattage/clock target is authorized. OCCT observations
  motivate independent calibration; OCCT is not the acceptance performance bar.
- [ ] Distinguish GPU board power, wall AC power and platform demand, disclosing
  sensor/meter bandwidth. User-space switching is not laboratory-grade
  100-microsecond excursion testing. PSU electrical/ATX compliance remains out
  of scope without separately calibrated high-speed electrical instrumentation.
- [ ] Design bounded last-confirmed-phase and run-state breadcrumbs, with
  interrupted/unknown-cause handling where feasible after restart. Avoid
  high-frequency synchronous persistence; disclose lost samples and timestamp
  uncertainty. A shutdown/reset alone does not diagnose PSU or hardware failure.

Design decisions still open: empirical backend/candidate choice; calibration
confidence and sensor-poor fallback; verification cost versus phase fidelity;
safe defaults; interrupted-run verdict presentation; and the acceptance matrix.
Follow the Spark → Snapdragon → x86 priority order above. Agree which ISA gates
must close and explicitly approve any justified deferrals before starting 1A;
do not silently waive specialized ISA or wider-SVE evidence requirements. Wider
VLs and other implementations remain physically unaccepted until suitable
hardware is available; a recorded deferral is not acceptance. The published
v0.5.3-alpha campaign stays closed, while future releases retain their own
release-readiness obligations.
Existing deferred Phase 3/4 output migration remains separately gated; early
evidence groundwork does not authorize changing the legacy compatibility format.

## Deferred Hardware Modules

- Additional storage testing beyond the current Storage Health and Storage
  Benchmark baseline is deferred pending milestone 4 planning above.
- Broaden AArch64 OpenCL driver/loader portability through one shared resolver
  where current probing is unavailable. GB10 OpenCL compute/VRAM passed in the
  accepted campaign; Snapdragon OpenCL exposed no usable GPU. Do not generalize
  one platform's execution into universal ARM GPU OpenCL support or fork workers.
- Additional CPU/package-power telemetry providers may be added for unfamiliar
  platforms. Current missing-watts behavior remains a truthful reported
  fallback, not a failed feature.
- Power Auto close-margin confidence/repeat policy is optional future
  refinement, not a current acceptance requirement.
- Additional CPU architectures and platform-specific hardware support require
  separate implementation and validation; x86_64 and AArch64 are the current
  supported architecture contract.
- NIC/network testing remains deferred candidate scope, not an adopted
  roadmap. Reconsidering it requires deliberate planning for loopback
  connectors, an operator-provided `iperf3` server or external peer, a
  known-good network path, and the time to validate execution and safety
  boundaries.
- `Files/nvidia_persistence.md` is retained operator/lab guidance for current
  NVIDIA persistence and power-limit procedures. A future CLI or GUI control
  surface may be considered, but none is implemented or committed to a
  release. If pursued, it should consider AMD and Intel GPU power/control
  options rather than being NVIDIA-only.
- Other hardware-specific validation modules are TBD and are not committed
  release scope.

## Needs User Or Product Decision

- Whether GUI work should progress beyond its current TBD status.

## Do Not Touch / Intentionally Legacy

- `parsed_results_custom.json` behavior and its compatibility aliases.
- Existing compatibility-sensitive field names and established contract IDs.
- Dynamic profile sidecar stage labels.
- Raw vendor/backend property spelling inside documented raw boundaries.
- Retain `Files/nvidia_persistence.md` as operator/lab guidance; it is not a
  committed CLI or GUI feature design.
