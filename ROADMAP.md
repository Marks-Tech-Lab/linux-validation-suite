# Linux Validation Suite Roadmap

This roadmap is the project-status source for completed, deferred, and
undecided work. Deferred or possible work is not committed release scope.

## Status And Authoritative Development Waves — 2026-11-04

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

### Authoritative current development queue — seven waves

This is the **single authoritative current priority queue**. ISA and dynamic-stress
sections below retain detailed scope, gates and evidence; their local ordering
operates within these waves, not as competing immediate priorities. Planned work
is not implemented, software-validated or physically accepted merely because it
has been adopted here. This roadmap edit authorizes no implementation or campaign.

1. [x] **Python Environment Lifecycle — complete for implementation/software scope.**
   Implemented, software-validated and committed, including guided Python
   upgrade/repair/rebuild, recoverable backups, a separate maintenance lock and
   the numbered interactive UI. Commit:
   `bde9e07c3d482f74292390c7ecaf77124c33366d`; final validation: 384/384 smoke
   tests and 81/81 profiles valid. **Broader real-host deployment acceptance
   remains pending**, separate from these completed software gates. See the
   [Environment Manager contract and deployment procedure](docs/environment_manager.md).
2. [ ] **Storage Thermal Assist — next priority; full workload and physical acceptance pending.**
   Wave 2A and Stage 2B-1 are committed, including guarded descriptor proofs.
   Stage 2B-2 standalone inactive-HDD execution is implemented in the development
   tree under software/synthetic review; physical acceptance remains pending.
   Profile/concurrent-stage integration and active-storage paths are not enabled.
   See [the backend foundation contract](docs/storage_thermal_backend_contract.md).
   Optional, lightweight, rate-limited, **read-only** drive activity for whole-system
   thermal validation, including high-density 4U/24-bay servers. Reuse existing
   storage inventory, temperature monitoring and fio where suitable. Require
   explicit selection, authoritative device identity, temperature safeguards,
   bounded cancellation and evaluation of interference with CPU/GPU workloads.
   Bound per-drive and aggregate activity/concurrency from actual devices and
   available resources; a 24-bay example is not a fixed hardware assumption.
   This is **not a storage benchmark or data-integrity test** and does not expand
   or replace the accepted Storage Health/Storage Benchmark baselines.
3. [ ] **ARM64 ISA completion — planned remaining implementations.**
   Finish adopted **SVE BF16** and **SVE2 QRDMLA (`sve2_qrdmla`)**, Spark first,
   with separate arithmetic/integrity and sustained-stress gates. Confirm current
   capabilities and the actual tested VL on GB10 Spark, then Snapdragon shared
   helper/baseline compatibility and supported execution or truthful negative-
   capability rejection as appropriate. Preserve all completed ARM64 acceptance;
   Spark's 128-bit evidence does not accept wider VLs or Snapdragon SVE execution.
4. [ ] **x86-64 ISA completion — planned remaining implementations.**
   AVX-512 BF16, AVX-512 FP16 and dedicated AMX INT8/BF16/FP16 work, with each AMX
   subfeature independently capability/compiler/OS-state gated. Preserve committed,
   physically accepted VNNI and general x86 scope. ISA availability alone does not
   establish arithmetic acceptance, sustained effectiveness or Auto promotion.
5. [ ] **GPU Power-Limit Control — planned separate utility.**
   Narrowly scoped control with CLI/TUI integration, based on actual supported
   controls, permissions, ranges and authoritative physical GPU identity. Require
   explicit confirmation, verification of the applied value, restoration of the
   recorded prior setting, and interruption/recovery safeguards. Do not implement
   automatic overclocking or voltage changes. This explicit operator utility is
   separate from dynamic workloads; it does not authorize automatic limit tuning
   during calibration or stress runs. Existing lab guidance remains a reference,
   not evidence that this utility is already implemented or accepted.
6. [ ] **System Dependency Management — planned, separately gated phases.**
   Detect **installed and functional** package managers and establish the correct
   host-management context, including host versus container and immutable/image-
   based systems. Neither distro identity nor a command's presence alone proves
   a usable package manager. First implement **read-only capability/provider
   resolution**; controlled package installation requires separate subsequent
   approval. Preserve Wave 1's advisory-only system-package boundary until then.
7. [ ] **Existing Dynamic-Stress Roadmap — resume the detailed sequence below.**
   GPU **1A → 1B → 1C**, CPU **milestone 2**, coordinated platform **milestone 3**,
   substantial storage/network review **4**, then reporting modernization **5**.
   Keep their existing design, software and physical gates, detailed planning,
   output compatibility and safety boundaries. Wave 2's thermal assist is a bounded
   precursor, not adoption of the later substantial storage/network expansion.

Within waves 3/4, prioritize worthwhile arithmetic/execution differences rather
than implementing every available extension. Spark success does not substitute
for Snapdragon portability or separately supported execution. Existing optional
and hardware-gated candidates do not become mandatory release prerequisites.
Before advancing with an unmet prerequisite, explicitly record any approved
responsible deferral: unavailable capability/hardware, evidence gap, risk and
reopening condition. A deferral is never physical acceptance. Published releases
and completed hardware campaigns remain closed within their documented boundaries.

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
is closed. Remaining ARM64 work follows Spark/Snapdragon ordering within wave 3;
the seven-wave queue above determines when that work resumes.

Remaining adopted specialized x86 work is assigned to wave 4, after wave 3:

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
  fail closed. Explicit `sve2_smlal` is committed in
  `9edd4e786b7277523fcc3b18ad67c7f95c2a7750`;
  it is excluded from every generic intent and physically accepted only within
  the Spark configuration recorded below.

SVE and SVE2 must not be encoded as automatically hotter than scalar or NEON.
The published v0.5.2-alpha policy excluded SVE from generic intents. This
change published in v0.5.3-alpha affects only the deliberate highest-vector
intent. Ordinary Auto stays NEON/scalar and Power Auto excludes SVE. A wider
inherited VL is software-validated, never thereby declared physically accepted.

### AArch64 specialized stress flavors — wave 3, Spark first

The adopted ARM64 scope is deliberately finite:

- [x] Implement experimental explicit-only NEON FP16/FHM (`neon_fp16` /
  `neon_fhm`) in committed milestone `fbefdea9617beb2185348a7c6ab8f14051f1fb78`, with independent ASIMDHP /
  ASIMDFHM runtime and optional compilation gates, genuine fused instructions,
  exact independent reference verification and all-thread progress/lifecycle.
- [x] NEON FP16 Gate A arithmetic/integrity acceptance on Spark (20 CPUs) and
  Snapdragon X1 Plus (8 CPUs), with independent ASIMDHP eligibility.
- [x] NEON FP16 Gate B sustained verified-stress acceptance on both tested platforms.
- [x] NEON FHM Gate A on both targets, with independent ASIMDFHM eligibility.
- [x] NEON FHM Gate B on both targets, independently of FP16 acceptance.
- [x] Implement explicit NEON DotProd (`asimddp`, token `neon_dotprod`) in
  committed milestone `853a27db6ba96f1809ae3ac0c56035ae53228629`: genuine signed `SDOT` and unsigned `UDOT`,
  independent modulo-2^32 reference, per-thread affinity/capability and verified
  progress. Software validation and physical acceptance remain separate.
- [x] NEON DotProd Gate A physical arithmetic/integrity acceptance on Spark
  (20 CPUs) and Snapdragon X1 Plus (8 CPUs), with current all-target eligibility.
- [x] NEON DotProd Gate B sustained verified-stress evaluation on those targets;
  do not assume greater power or stress effectiveness from the instruction family.
- [x] Implement experimental explicit-only NEON I8MM (`neon_i8mm`) in the
  committed milestone `787c9ae255f81ad2aab4326b2721e740510767d3`: genuine
  SMMLA/UMMLA/USMMLA, independent 2×8 by
  8×2 matrix verification and per-thread capability/affinity/progress evidence.
- [x] NEON I8MM Gate A physical arithmetic/integrity acceptance on Spark
  (20 CPUs) and Snapdragon X1 Plus (8 CPUs), with pinned all-target eligibility.
- [x] NEON I8MM Gate B sustained verified-stress evaluation on both tested platforms.
- [x] Implement experimental explicit-only NEON BF16 (`neon_bf16`) in the
  committed milestone `83665bc59213c8392b3d69480262b1b70b339a80`: BFDOT/BFMMLA and alternating
  BFMLALB/BFMLALT, exact standard-EBF0 and fused widening references,
  independent HWCAP2_BF16 gating and all-thread FPCR/affinity/progress evidence.
- [x] NEON BF16 Gate A arithmetic/integrity acceptance independently on GB10 Spark
  (20 allowed CPUs) and Snapdragon X1 Plus (eight allowed CPUs), FPCR=0 / EBF=0.
- [x] NEON BF16 Gate B sustained verified-stress acceptance on both tested targets,
  with continuous reconciled progress, zero mismatches/stalls and complete lifecycle.
- [x] Implement the distinct SVE2 signed widening integer workload below
  (`sve2_smlal`, committed in `9edd4e786b7277523fcc3b18ad67c7f95c2a7750`);
  both physical gates PASS on Spark at 128-bit VL.
- [ ] Implement the final adopted SVE2 workload, experimental explicit-only
  `sve2_qrdmla`: scalable signed 16-bit and 32-bit saturating fixed-point
  SQRDMLAH/SQRDMLSH, independent exact references and meaningful non-invariant
  sustained recurrence. Implementation and software validation remain pending.
- [ ] SVE2 QRDMLA Gate A arithmetic/integrity acceptance on GB10 Spark at its
  actually tested VL, with every active lane verified.
- [ ] SVE2 QRDMLA Gate B sustained verified-stress evaluation on Spark, including
  evidence that recurrence does not collapse to permanently saturated constants.
- [ ] Updated-helper Snapdragon non-SVE compatibility and explicit unsupported
  `sve2_qrdmla` rejection, with no worker launch or ISA fallback.
- [x] Implement experimental explicit-only SVE I8MM (`sve_i8mm`) in committed
  milestone `90b547d15e3bedc5087730c9959b6219a0d47c4d`: scalable Z-register
  SMMLA/UMMLA/USMMLA, all active
  128-bit segments, 256 rounds plus a one-round witness, independent modulo-2^32
  matrix reference, per-thread VL/capability/affinity/progress and lifecycle.
- [x] SVE I8MM Gate A arithmetic/integrity acceptance on GB10 Spark at 128-bit VL.
- [x] SVE I8MM Gate B sustained verified-stress evaluation on Spark.
- [x] Updated helper Snapdragon portability: independently inspected scalar/NEON
  executions and operator-confirmed screenshot of explicit unsupported-SVE-I8MM
  rejection on CPUs 0–7, with no commands, worker or fallback.
- [ ] SVE BF16.

SVE2/DotProd/NEON I8MM/FP16/FHM/BF16 and SVE I8MM are committed and accepted
within their recorded boundaries. SVE BF16 and SVE2 QRDMLA remain planned
implementations in wave 3.
Both physical gates PASS on Spark and Snapdragon for DotProd, I8MM, FP16/FHM and
BF16; existing SVE2 and baseline acceptance remain unchanged.
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

**NEON DotProd implementation (committed, physically accepted):**
The [DotProd contract](docs/neon_dotprod_contract.md) defines eight independent
128-bit accumulator chains (four signed and four unsigned), 256 recurrence
rounds, independent verification of all result lanes, isolated optional
compilation, HWCAP `asimddp` gating, all-target affinity and versioned progress.
Software validation passes **332/332 smoke tests**, all **81/81 profiles** with
five unchanged advisories, compilation and integration imports. Both physical
gates PASS independently on Spark and Snapdragon within the tested configurations.
It remains experimental and explicit-only: no generic Auto/vector-intent or
Power Auto promotion. Small fixed per-thread memory and bounded cancellation
are independent of installed capacity and SVE VL.

On November 2, Spark's 20-CPU functional execution completed 120.371 seconds and
10,932,750,690 verified blocks; sustained execution completed 600.911 seconds and
54,587,906,380 blocks. Snapdragon X1 Plus's eight-CPU functional execution completed
121.276 seconds and 2,856,577,340 blocks; sustained execution completed 600.570
seconds and 14,323,962,061 blocks. All-thread pinned eligibility, initial/periodic/
final independent signed/unsigned verification, zero mismatches, successful
worker exits and finalized parent PASS results establish integrity acceptance.
Actual executed ELF helpers confirm four `SDOT` and four `UDOT` instructions each.

The complete 366-file physical source fingerprint is
`320977e5bf46a8e69a27da4874f98dc7a7fb450a28234aa2feb9a4b8377985ec`.
Spark GCC 13.3.0 helper SHA-256 is
`5c64b739603111995e481dc24533f86c826753a8d2378e9a8fc19b23ca8f3bf0`;
Snapdragon GCC 15.2.0 helper SHA-256 is
`2500602ff7d287cd07b5e3cefa1b7e01806d41199c656539f35567195054aab5`.
Each matches its own prelaunch/process/post-execution observations. The contract
records all four execution folders, matching original-template diagnostics and
retained executable paths. Snapdragon evidence is independently inspected;
the earlier missing-folder conclusion is superseded.

Sustained verified throughput was approximately 90.843 million blocks/s on Spark
and 23.856 million on Snapdragon, with zero recorded stalls and sufficient
progress/telemetry coverage. This establishes sustained computational stress,
not maximum power, superior effectiveness or universal hardware support. Spark
CPU-specific temperature/power were unavailable; platform thermal zones peaked
at 85.7/86.7 C in functional/sustained runs. Reported cpufreq values are not
independently measured effective clocks. Snapdragon CPU-subsystem temperatures
peaked at 84.4/89.9 C; clocks and package power were unavailable. Kernel visibility
on both remains limited by denied `dmesg` and empty filtered journal captures.

No further DotProd physical repetition is required. Unfinished adopted ARM64
work belongs to wave 3, Spark first, then supported Snapdragon compatibility and
acceptance; the seven-wave queue determines its overall priority. SVE/SVE2,
VNNI and generic selection behavior remain unchanged.

**SVE I8MM implementation (committed, physically accepted on Spark):**
The [SVE I8MM contract](docs/sve_i8mm_contract.md) defines `sve_i8mm`, with three
signed SMMLA, three unsigned UMMLA and two unsigned-by-signed USMMLA scalable
Z-register accumulator chains. Every active 128-bit segment uses independent
2×8 by 8×2 matrix verification, four int32 result lanes and modulo-2^32 accumulation.
Each credited block must pass all lanes, guards, 256 rounds and a separate one-round
witness. Runtime eligibility requires FP/ASIMD/SVE plus HWCAP2_SVEI8MM (bit 9),
not an inferred NEON I8MM or SVE2 flag. Per-thread inherited VL (16–256 bytes,
16-byte multiples) is validated against actual CNTW before loads/stores and checked
throughout credited work. Different valid per-thread VLs remain independently
accounted for; changed or malformed VL fails closed. Compilation is independently
optional; baseline non-SVE startup and existing Auto/vector/Power Auto are preserved.

The pre-physical software baseline passes **358/358 smoke tests**, **81/81 profiles** with five
unchanged advisories, 379 Python compilation checks and 19 integration imports.
The six new SVE I8MM groups include independent matrix references, genuine
AArch64 object instruction/data-flow analysis, all 16 supported software VLs,
capability/resource/cancellation failures and reporting/frontend parity.
Baseline, SVE-I8MM-only and combined-feature AArch64 compilation pass.
The complete 370-file execution-source fingerprint is
`8d3c99476db9b4da561a6daeecd96880b9f2d1bb441757f3f7fb272b886fdb90`;
documentation and regression files are outside that scope.
Both Spark physical gates PASS at 128-bit VL: 20/20 CPUs, 121.310-second
functional execution / 4,684,435,829 verified blocks and 601.922-second sustained
execution / 23,273,347,282 blocks. The 481.950-second usable window sustains
38.665 million verified blocks/s, stable halves and zero recorded stalls. The
executed GCC 13.3.0 helper SHA-256 is
`78e04ae9f9c33187dec60e5952477c072021155270a5f637083875b4753ecb55`,
matching all executable observations. Genuine 3/3/2 signed/unsigned/mixed scalable
matrix chains, every active lane, the one-round witness, capability/affinity/VL,
independent arithmetic and normal lifecycle pass with zero errors. Wider VLs remain
software-only. Spark's sustained platform thermal peak is 73.7°C; CPU-specific
power/temperature, independent effective clocks and kernel-log visibility remain
limited. This is sustained verified work, not proven maximum-power superiority.

Snapdragon current-helper compilation and native scalar/NEON compatibility PASS
on CPUs 0–7 (121.310/121.238 seconds, respectively; zero errors, successful exits
and finalized results). The recorded baseline helper identity is
`a78699f4a74ba48ae94722ba85ddb250d0121dd2eec97bd37e40e153540fb026`.
Explicit `sve_i8mm` rejection is accepted from the operator-confirmed screenshot:
effective token, CPUs 0–7, blocked readiness, zero runnable stages/commands and no
worker/fallback. It is not an independently inspected machine-readable diagnostic;
original `sve` template captures remain original. Snapdragon has no SVE I8MM
arithmetic/stress acceptance. No physical repetition is required.

All four physical runs recorded unchanged endpoints for the 370-file fingerprint
above. Subsequent effective-readiness persistence changes alter full-source identity
without changing native arithmetic, capability policy or execution eligibility.
They automatically preserve CLI/TUI run-local readiness, including blocked attempts,
as separate READY/BLOCKED preflight-only artifacts with original/effective profiles,
overrides, targets/capabilities, commands, source/host/backend evidence and reasons.
Original Dry Run diagnostics remain distinct; Advanced Debug is not required.
The modified diagnostic snapshot passes **362/362 smoke tests**, **18/18 focused
checks**, **81/81 profiles** with five unchanged advisories, 380 Python compilation
checks and 29 integration imports. Its complete 370-file source fingerprint is
`524d9414cfac636b2ccdc45a89dcdc613f8729a65ff33daeb53ca1a9b597a470`.
Native workloads and capability/selection/safety/lifecycle policies are unchanged.
This snapshot is software-validated separately, not claimed as physically executed.
SVE I8MM, effective-readiness persistence and the final SVE2 scope amendment are
committed in `90b547d15e3bedc5087730c9959b6219a0d47c4d`. Within wave 3,
SVE BF16 precedes the remaining SVE2 QRDMLA work, Spark first; this is not the
immediate project priority ahead of wave 2. Accepted prior ISA and explicit-only
boundaries remain unchanged.

**NEON BF16 implementation (committed, physically accepted):**
The [BF16 contract](docs/neon_bf16_contract.md) defines an experimental explicit-only
`neon_bf16` kernel with two BFDOT, two BFMMLA, two BFMLALB and two BFMLALT independent
128-bit accumulator chains. Each credited block verifies all 32 FP32 result lanes
through 256 rounds and a separate one-round witness. Standard dot/matrix arithmetic
uses explicit unfused round-to-odd and denormal-flush references; widening uses
independent fused RN-even integer references. Checked 640-bit dyadics preserve large
exponent gaps without floating-point tolerances. HWCAP2_BF16, FP/ASIMD and pinned
eligibility are mandatory; EBF16 capability is recorded independently, EBF=1 is
rejected, and FPCR is validated without mutation. No SVE capability is inferred.

Software validation passes **352/352 smoke tests**, including six BF16 groups and
existing specialized ISA/selector/output-contract regressions; **81/81 profiles**
remain valid (five unchanged advisories). All **378 Python files** compile and
integration imports pass. AArch64 baseline, BF16-only and combined optional-feature
assembly/object compilation pass, including actual BF16 object disassembly and
bounded emitted data/control-flow tracing. The complete **369-file** source
fingerprint is
`6700ba394f55de32c7ef84a61d5eaf6df05247e1707ecf736b7e07c3ecacd79a`.
All four physical executions recorded that complete 369-file identity at unchanged
initial/final endpoints. The current scoped production implementation still matches;
acceptance documentation is outside the execution-source fingerprint scope.

| Tested platform | Functional native seconds / verified blocks | Sustained native seconds / verified blocks | Gate A | Gate B |
|---|---|---|---|---|
| GB10 Spark, 20/20 allowed CPUs | 120.189 / 6,533,938,633 | 600.989 / 32,669,799,505 | PASS | PASS |
| Snapdragon X1 Plus, 8/8 allowed CPUs | 121.219 / 1,412,988,998 | 600.717 / 7,117,306,219 | PASS | PASS |

Both retained physical helpers confirm two independent chains each of BFDOT,
BFMMLA, BFMLALB and BFMLALT, correct 256-round recurrence, mandatory one-round
witness and all 32 FP32 result stores. All selected CPUs passed capability and
pinned affinity checks. Every worker recorded FPCR=0, enhanced BF16 unavailable,
bit-exact independent arithmetic with the documented distinct rounding/accumulation
semantics, and complete initial/periodic/final verification. No arithmetic mismatch,
progress stall or lifecycle failure occurred. All native processes exited 0 with
normal cleanup and completed parent PASS results; progress and terminal counters
reconcile. No physical corruption injection is claimed.

Executed helpers match their platform's prelaunch/process/post-execution identities:

- Spark, GCC 13.3.0: `a3d70617fe4dd76fa1acb5a4b525f68687dee6bc1d154020ab2d9ab8cf7dd486`.
- Snapdragon, GCC 15.2.0: `4488337d574d524e8eea0e15086644353771ac38c8c321b0b5120c8cc6c95ac6`.

Spark's sustained usable window is 481.024 s at 54.360 million verified blocks/s;
Snapdragon's is 480.729 s at 11.848 million. Per-thread progress coverage is
99.506–99.572% / 99.587–99.639%, with zero stalls and stable first/second-half rates
(+0.008% / +0.013%). Sustained peaks are 73.8 C in Spark platform thermal zones
and 70.2 C in Snapdragon CPU-subsystem monitoring. CPU package power is unavailable;
Spark lacks CPU-specific temperature and independent effective clocks, and Snapdragon
clocks are unavailable. Denied dmesg and empty filtered journals limit kernel visibility.

The original SVE-template diagnostics are distinct from the independently inspected
run-local BF16 overrides, readiness and actual native execution on each platform.
Exact execution/diagnostic paths and retained helper locations are in the contract;
local physical evidence remains outside the development commit. Acceptance covers
the tested EBF=0 hardware/compiler/finite-domain configurations, not universal
compatibility, maximum-power effectiveness or superiority over other kernels.
No further physical test or production correction is required. BF16 remains
experimental and explicit-only; Auto, vector intents and Power Auto are unchanged.
The NEON BF16 milestone was committed in
`83665bc59213c8392b3d69480262b1b70b339a80`. SVE I8MM Spark acceptance and Snapdragon portability are now complete;
SVE BF16 remains later adopted work. Accepted prior ISA boundaries are unchanged.

**NEON FP16/FHM implementation (committed, physically accepted):**
The [FP16/FHM contract](docs/neon_fp16_fhm_contract.md) defines two independent,
experimental explicit-only kernels. `neon_fp16` executes eight vector FP16 FMLA
chains (64 result lanes); `neon_fhm` executes four FMLAL/FMLAL2 low/high pairs
with FP32 accumulation (32 lanes). Both perform 256 recurrence rounds and a
one-round fused witness, with exact integer-significand RN-even references,
signed/normal/subnormal cases, bounded finite results and one-bit corruption
checks. FPCR rounding/flush/trap/alternative-mode conditions are recorded and
validated rather than silently changed. ASIMDHP and ASIMDFHM are independently
gated on every selected allowed CPU; no SVE or processor-model inference is used.

Software validation passes **346/346 smoke tests**, **81/81 profiles** with five
unchanged advisories, native baseline/feature-enabled AArch64 compilation,
Python compilation/imports and output-contract checks. The complete 368-file
source fingerprint is
`d7fdd746fd5befb1ffe2b5e2a99331dbac82a2dbaaa9088d19acb0067e49fb4c`.
All eight physical executions recorded that fingerprint with unchanged
initial/final endpoints. That accepted implementation was committed in
`fbefdea9617beb2185348a7c6ab8f14051f1fb78`. Subsequent BF16 integration adds a
separate optional kernel; it does not change the accepted FP16/FHM arithmetic.
Acceptance documentation remains outside the scoped source identity.

| Tested platform / workload | Functional duration / verified blocks | Sustained duration / verified blocks | Gate A | Gate B |
|---|---|---|---|---|
| GB10 Spark FP16, 20 CPUs | 120.362 s / 8,133,277,285 | 600.844 s / 40,624,592,362 | PASS | PASS |
| GB10 Spark FHM, 20 CPUs | 120.301 s / 9,543,546,155 | 600.343 s / 47,491,560,659 | PASS | PASS |
| Snapdragon X1 Plus FP16, 8 CPUs | 121.286 s / 2,293,577,085 | 600.565 s / 11,376,472,625 | PASS | PASS |
| Snapdragon X1 Plus FHM, 8 CPUs | 121.115 s / 2,706,391,538 | 600.412 s / 13,409,180,224 | PASS | PASS |

Both actual AArch64 helpers confirm genuine eight-chain FMLA .8H FP16
accumulation and four FMLAL/four FMLAL2 FP32 chains, with correct low/high
mapping, 256-round recurrence, result stores and a separate one-round witness.
All selected CPUs pass the appropriate independent feature and pinned-affinity
checks, with FPCR=0, bit-exact independent reference verification, complete
initial/periodic/final phases and zero mismatches. Progress reconciles with
terminal counters; workers exit 0, parents finalize PASS, and normal cleanup
completes without safety interventions, timeouts or abnormal termination.

Target-local compilers and matching prelaunch/process/post-execution SHA-256:

- Spark, GCC 13.3.0: `78f125b808033b1807f70aee9a656bb6084d59b2f3440a8780bbc9e82c68b1f3`.
- Snapdragon, GCC 15.2.0: `23d59bf34049529b2490e8bb1e350f300f38d8bdf0609fdecf97dfb171a093de`.

Sustained verified rates are 67.613/79.116 million blocks/s for Spark FP16/FHM
and 18.947/22.338 million for Snapdragon FP16/FHM. First/second-half rates are
stable, per-thread progress coverage is approximately 99.56–99.76%, and all four
sustained runs record zero stalls. Rates are not directly equivalent arithmetic
counts: FP16 and FHM verify different lane counts and accumulation precision.

Spark platform-zone thermal peaks are 83.6/85.1 C for FP16/FHM, with CPU-specific
temperature and package power unavailable. Reported cpufreq is 2,808/3,900 MHz
(aggregate 3,354 MHz), not independently measured effective clocks. Snapdragon
CPU-subsystem peaks are 82.8/85.6 C; clocks and package power are unavailable.
Denied `dmesg` and empty filtered journals limit kernel visibility on both.
Acceptance covers the tested hardware, compilers, FPCR=0 and finite numerical
domain; it does not establish maximum power or superiority of one instruction
family. No deliberate physical corruption injection is claimed.

No further FP16/FHM physical repetition is required. Remaining adopted ARM64
work belongs to wave 3, Spark first, then supported Snapdragon compatibility and
acceptance. Reproduction procedures and exact execution/diagnostic paths remain
in the contract.

Both are high-compute-demand workload candidates, not assumed maximum-power or
higher-demand replacements for scalar, baseline NEON, SVE or other accepted
kernels. Generic Auto, vector intents and measured Power Auto are unchanged.
The shared CPU instruction presentation remains dynamically alphabetized with
Auto first, including the new tokens. No further ISA family is started here.

**NEON I8MM implementation (committed, physically accepted):**
The [I8MM contract](docs/neon_i8mm_contract.md) defines three signed SMMLA,
three unsigned UMMLA and two unsigned/signed USMMLA chains, each with four int32
accumulators and 256 recurrence rounds. Independent wide-integer references
verify both rows and columns of the packed 2×8 by 8×2 operation, including signed
extremes and modulo-2^32 accumulation. Optional compilation and runtime
HWCAP2_I8MM gating are independent of DotProd/SVE support. All-thread pinned
eligibility, affinity, initial/periodic/final verification, progress reconciliation
and worker/parent lifecycle completed with zero mismatches on both platforms.

| Tested platform | Functional execution | Sustained execution | Gate A | Gate B |
|---|---|---|---|---|
| GB10 Spark, 20 CPUs | 120.401 s; 11,070,382,739 blocks | 601.198 s; 55,275,587,404 blocks | PASS | PASS |
| Snapdragon X1 Plus, 8 CPUs | 120.899 s; 2,161,049,164 blocks | 601.495 s; 10,750,441,029 blocks | PASS | PASS |

Spark sustained throughput is approximately 91.945 million verified blocks/s;
Snapdragon is 17.877 million/s, both with zero recorded progress stalls.
Matching physical helpers use GCC 13.3.0 and GCC 15.2.0, respectively:

- Spark SHA-256: `2d8c344bf685d2b88aa80a64c9179b56c2aa958ae4fd898230303644b4adbe22`.
- Snapdragon SHA-256: `da4c0cd8712d63db3323aaa94826467c9b0dc51d85582e282d346c37ab046b4d`.

Actual helper disassembly confirms all eight logical chains. GCC 15 peels the
first signed triplet, yielding six static SMMLA sites but the same three signed
chains and exactly 256 effective updates. The regression follows emitted
control/data flow and result stores rather than requiring fixed static counts.
All four physical runs recorded the complete 367-file source fingerprint
`d553defe2f14cafc62750d5684f05e068b9a52289edb03821274b739efe9e5e7`.

The presentation-only CPU instruction ordering correction in that accepted
367-file milestone produced fingerprint
`f0496662c2ea4e69a399672c602bb4657a40a96a818f94aaf4375a0e52ef4572`.
CLI/TUI profile editing and Stage Overrides dynamically show Auto first, then
explicit ISA tokens alphabetically (case-insensitive), preserving selection,
highlighting, cancellation and saved tokens. Native kernel, capability,
arithmetic verification and lifecycle are unchanged; the complete UI-corrected
snapshot itself is not claimed physically executed. Markdown and test fixtures
are outside the source fingerprint scope. Combined software validation passes
**340/340 smoke tests**, **81/81 profiles** with five unchanged advisories,
Python compilation/imports and native baseline/AArch64 compilation checks.

Spark reports cpufreq 2,808/3,900 MHz, not independently measured effective
clocks; CPU-specific temperature and package power are unavailable. Other
platform thermal readings peak at 85.7/87.3 C. Snapdragon CPU-subsystem maxima
are 80.1/86.0 C; clocks and package power are unavailable. Denied `dmesg` and
empty filtered journal captures limit kernel visibility on both. Acceptance is
limited to these tested configurations and demonstrated sustained verified
computation, not maximum power or superiority over another ISA workload.

No further I8MM physical repetition is required. This milestone remains
experimental and explicit-only, committed in
`787c9ae255f81ad2aab4326b2721e740510767d3`, outside published v0.5.3-alpha.
No Auto/vector-intent or measured Power Auto promotion is made. Remaining adopted
ARM64 work stays Spark-first within wave 3, followed by supported Snapdragon
compatibility/acceptance; no additional ISA family is adopted here.

**Committed SVE2 integer workload (Spark physically accepted):**
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
other hardware or widths. No further Spark repeat is required.

- [x] Complete Snapdragon X1 Plus portability for the committed SVE2 milestone:
  target-local compilation including optional SVE2 code, native scalar and NEON
  FP32/FMA functional execution across all eight allowed CPUs, and expected
  explicit `sve2_smlal` preflight rejection with no runnable commands.

On November 2, the HP OmniBook X scalar run at `13-38-19` completed 121.278
seconds with 152,096 verification/canary passes; the NEON FP32/FMA run at
`13-44-03` completed 121.249 seconds with 1,527,028,320 independently verified
blocks, all verification phases and zero recorded progress stalls. Both had zero
errors, correct affinity, exit 0 and finalized PASS results. Their scoped source
matches the Spark fingerprint above; prelaunch/process/post-execution helper
SHA-256 is `741cdad1a98efa457e959c73470459eaf3778bbb724d5481b1b658c2a4ad9ff2`.
Scalar retains its legacy canary/checksum contract, not the newer phase/progress
contract. HWCAP/HWCAP2 show SVE/SVE2 unavailable. The operator confirms a final
screenshot of the effective SVE2 request being rejected on CPUs 0–7 with zero
runnable stages/commands. The screenshot itself was not discoverable locally at
this update; this is operator-confirmed evidence, separate from the available
original-template diagnostic JSON. The contract records this evidence distinction,
exact folders, compilation evidence and limited kernel/power visibility.

This closes current-helper Snapdragon portability, not future specialized NEON
acceptance or SVE2 execution on Snapdragon. No additional physical repetition is
required for this milestone. Unfinished specialized ARM64 development is assigned
to wave 3, Spark first, then supported Snapdragon compatibility/acceptance.
Existing Auto, vector intents, measured Power Auto and accepted FP32/FMA/VNNI behavior remain
unchanged.

The design target follows Arm's [SVE2 widening multiply-add example](https://documentation-service.arm.com/static/6659c722876c8d213b7870d3)
and [ACLE instruction mappings](https://arm-software.github.io/acle/main/acle.html).
It is one bounded stability-validation kernel, not a commitment to cover every
SVE2 instruction or to generalize current Spark SVE acceptance.

### Final adopted SVE2 workload — saturating fixed-point arithmetic

**Adopted, not implemented or validated:** add `sve2_qrdmla`, then close planned
SVE2 instruction-family expansion. This complements accepted `sve2_smlal` signed
widening/modulo-32-bit arithmetic with rounded, saturating fixed-point behavior
that provides a specific additional arithmetic fault-detection opportunity.
Different semantics justify evaluating this coverage; they do not establish
independent execution hardware, higher power demand or superior stress effectiveness.

Implementation must use genuine scalable SVE2 **SQRDMLAH and SQRDMLSH** with signed
16-bit and 32-bit accumulator chains, multiple independent accumulators and
meaningful repeated arithmetic. Independent exact wide-integer references must
reproduce architectural doubling, rounding, addition/subtraction and signed
saturation in the correct order. Verify every active lane, including ties,
negative extremes, saturation boundaries and ordinary non-saturating arithmetic.
Use separate saturation witnesses; sustained inputs must avoid permanently
saturated or otherwise invariant accumulators. Evidence must show evolving
arithmetic state, not only repeated instruction execution on constant results.

Preserve vector-length-agnostic operation, current all-target SVE2 eligibility,
per-thread inherited VL validation, pinned affinity, independent verification,
timestamped reconciled progress, executable/source provenance and normal lifecycle.
The workload remains experimental and explicit-only. Auto, generic vector intents,
`highest_verified_vector` and measured Power Auto retain their current policies.

- **Gate A — arithmetic/integrity:** actual native instructions, bit-exact
  independent verification, deterministic corruption-detection regressions, complete
  active-lane coverage, capability/VL/affinity integrity and successful lifecycle.
  Software corruption injection does not imply physical fault injection.
- **Gate B — sustained verified stress:** meaningful sustained computation,
  continuously reconciled verification, stable progress, non-invariant accumulator
  activity and available operating-condition evidence, for a purpose-appropriate
  duration. Compare observed stress characteristics with existing SVE2 integer,
  SVE and NEON work, documenting measurement/comparability limits rather than
  assuming distinct execution resources or greater wattage.

Validate first on NVIDIA GB10 Spark at its supported, recorded physical VL;
Spark's existing 128-bit acceptance does not pre-accept this new kernel. Confirm
updated-helper Snapdragon non-SVE baseline compatibility and truthful explicit
unsupported-capability rejection. Do not run an unsupported sustained SVE2 test
or infer Snapdragon SVE2 arithmetic acceptance from rejection evidence.

**Completion boundary:** once `sve2_qrdmla` passes both gates and its portability
checks, the adopted SVE2 workload scope (`sve2_smlal` and `sve2_qrdmla`) is complete
for the currently tested configurations. This is neither exhaustive SVE2 coverage
nor physical acceptance at untested vector lengths or on other implementations.
No dedicated SVE2 histogram, complex arithmetic, permutation, crypto,
narrowing/packing or additional DSP-family stress workloads are planned. Existing
accepted functionality, the pending SVE BF16 milestone and finite ARM64 scope
otherwise remain unchanged; Spark-first ordering applies within wave 3.

### Exclusions and hardware-gated evaluation candidates

The following remain **outside mandatory standalone ISA stress scope**:

- **x86-64:** SSE3/SSSE3/SSE4.x; AES/SHA/GFNI and related crypto operations;
  BMI/ADX; AVX-512 IFMA; VBMI and miscellaneous permutation extensions.
- **ARM64:** AES/SHA/SM3/SM4/CRC and SVE crypto; SVE bit permutation; separate
  FCMA/RDM and miscellaneous DSP workloads beyond the explicitly adopted,
  bounded SVE2 `sve2_qrdmla` workload above.

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

This detailed sequence is wave 7 of the authoritative queue above, not a competing
immediate priority. Every new workload remains proposed, with design approval and
implementation separately gated. No proposed preset below is an existing
profile, command or menu entry.

| Milestone | Dependency / purpose | Proposal recorded | Design approved | Implemented | Software-validated | Physically accepted |
| --- | --- | --- | --- | --- | --- | --- |
| 1A — Calibrated sustained high-power GPU foundation | After waves 1–6 complete or approved deferrals; establish repeatable verified high demand | [x] | [ ] | [ ] | [ ] | [ ] |
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
Follow the seven-wave priority queue above; Spark → Snapdragon ordering applies
within wave 3, followed by x86 work in wave 4 and utilities in waves 5/6. Agree
which prerequisite gates must close and explicitly approve justified deferrals
before starting wave 7's 1A; do not silently waive specialized ISA or wider-SVE
evidence requirements. Wider
VLs and other implementations remain physically unaccepted until suitable
hardware is available; a recorded deferral is not acceptance. The published
v0.5.3-alpha campaign stays closed, while future releases retain their own
release-readiness obligations.
Existing deferred Phase 3/4 output migration remains separately gated; early
evidence groundwork does not authorize changing the legacy compatibility format.

## Deferred Hardware Modules

- Substantial storage/network expansion beyond the current Storage Health and
  Storage Benchmark baselines remains deferred to wave 7's milestone 4 planning.
  The optional read-only Storage Thermal Assist in wave 2 is a separate, bounded
  thermal-validation aid, not a benchmark, integrity test or adoption of that expansion.
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
- NIC/network testing implementation remains deferred candidate scope: wave 7's
  milestone 4 adopts a review, not implementation. Reconsidering it requires
  deliberate planning for loopback
  connectors, an operator-provided `iperf3` server or external peer, a
  known-good network path, and the time to validate execution and safety
  boundaries.
- `Files/nvidia_persistence.md` remains operator/lab guidance for current NVIDIA
  persistence and power-limit procedures. Wave 5 now plans a separate CLI/TUI
  GPU Power-Limit Control utility; it is not implemented or accepted. Discover
  actual supported NVIDIA/AMD/Intel controls rather than assuming vendor support
  or treating this lab document as an implemented feature design.
- Other hardware-specific validation modules are TBD and are not committed
  release scope.

## Needs User Or Product Decision

- Whether GUI work should progress beyond its current TBD status.

## Do Not Touch / Intentionally Legacy

- `parsed_results_custom.json` behavior and its compatibility aliases.
- Existing compatibility-sensitive field names and established contract IDs.
- Dynamic profile sidecar stage labels.
- Raw vendor/backend property spelling inside documented raw boundaries.
- Retain `Files/nvidia_persistence.md` as operator/lab guidance. Wave 5's planned
  utility requires its own design and gates; this file is not that design.
