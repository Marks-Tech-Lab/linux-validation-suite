# Linux Validation Suite Roadmap

This roadmap is the project-status source for completed, deferred, and
undecided work. Deferred or possible work is not committed release scope.

## Status And Current Priority Queue — 2026-10-23

`[x]` marks only the named checkpoint in its stated scope. Proposal/design,
implementation, software validation and physical acceptance are separate gates;
source presence, smoke-test success or ISA selection does not prove physical
acceptance. Existing historical sections retain their original release scope.

1. [x] Implement and software-validate current CLI/TUI configuration parity,
   immediate Copy/Save As persistence and temporary workload overrides. Latest
   local checkpoint: 303/303 smoke tests and 81/81 profiles valid. This is not
   hardware acceptance; the UX does not require physical stress to validate it.
2. [x] Physically confirm corrected EGL readback/scheduling and geometry, and
   Core Ultra OpenCL assigned-target attainment with sampled integrity, guards
   and cleanup on the exercised configurations. This is not exhaustive memory
   verification, physical-residency proof or acceptance of every backend.
3. [ ] Complete corrected Vulkan allocation-path integration acceptance:
   dedicated/shared device memory, separately protected host staging, alignment
   accounting and cleanup. The changes and negative safety checks are
   implemented/software-validated; earlier Vulkan identity acceptance does not
   accept these newer paths. Keep unresolved I/O/persistence incidents separate
   from workload correctness and do not declare their cause fixed.
4. [ ] Complete current ARM64 `highest_verified_vector` physical integration
   confirmation on Spark and Snapdragon. The policy is implemented and
   software-validated; earlier SVE/NEON arithmetic acceptance remains scoped to
   its actual campaigns, not the newly exposed selection workflow.
5. [ ] Finish the already-adopted major x86_64/AArch64 ISA milestones below,
   with independent verification and scoped hardware acceptance. Record any
   hardware-unavailability deferrals explicitly rather than marking them done.
6. [ ] Retain corrective release-readiness, safety, provenance and compatibility
   review before publication. No future feature here assigns a release version.

Only after these current prerequisites are closed or explicitly re-scoped may
the dynamic-stress sequence below begin. This records future planning priority,
not authorization to implement workers or change current test/verdict policy.

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

Generic ISA capability selection and Power Auto thermal selection remain
separate policies. An implemented or higher-throughput ISA is not assumed to be
the hottest workload. Power Auto continues to measure valid candidates when
trustworthy package-watt telemetry exists; unmeasured thermal ordering requires
physical evidence.

### Current x86_64 kernels

The implemented general and Power Auto native kernels are `scalar`, `sse2`,
`sse2_int`, `avx`, `avx_fma`, `avx2`, `avx2_fma`, `avx512_fma`, and
`avx512_int`.

The adopted specialized x86_64 stress roadmap is AVX-VNNI/256-bit VNNI,
AVX-512 VNNI, AVX-512 BF16, and AVX-512 FP16 as high-throughput stress flavors
and Power Auto candidates. Intel AMX INT8/BF16/FP16 is a separate matrix/tile
stress family. These are not additional ordinary top-level SIMD tiers unless
architecture semantics require one. AVX10.x remains future work until physical
hardware is available.

Outstanding adopted flavors (design/implementation, software validation and
physical acceptance remain to be completed for each):

- [ ] AVX-VNNI / 256-bit VNNI.
- [ ] AVX-512 VNNI.
- [ ] AVX-512 BF16.
- [ ] AVX-512 FP16.
- [ ] Separate Intel AMX INT8/BF16/FP16 matrix/tile family.

SSE3/SSSE3/SSE4.x, AES/SHA/GFNI, BMI/ADX, IFMA/VBMI, and similar extensions are
not adopted merely because they exist; they are not current general
thermal-stress priorities.

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
- [ ] Physically confirm the current highest-vector selection integration;
  this is separate from the accepted arithmetic campaigns.
- [ ] Physically validate wider SVE vector lengths and other implementations;
  software scalable/mixed-VL fixtures do not close this gate.
- [ ] Design, implement, independently verify and physically accept distinct
  SVE2-specific work; SVE FP32/FMA is not SVE2.

Current ARM instruction intents resolve as follows:

- `baseline_vector` selects NEON.
- `high_throughput_vector` prefers NEON FP32/FMA, then integer NEON.
- `highest_verified_vector` prefers common SVE FP32/FMA, then NEON FP32/FMA,
  then integer NEON. Actual per-thread VL and software verification are
  established at execution; prior physical acceptance is separate evidence.
- Explicit `neon`, `sve` and exact FP32/FMA requests retain their identities or
  fail closed. SVE2 remains future work, not a selectable implemented kernel.

SVE and SVE2 must not be encoded as automatically hotter than scalar or NEON.
The published v0.5.2-alpha policy excluded SVE from generic intents. This
post-release development change affects only the deliberate highest-vector
intent. Ordinary Auto stays NEON/scalar and Power Auto excludes SVE. A wider
inherited VL is software-validated, never thereby declared physically accepted.

### AArch64 specialized stress flavors

The adopted specialized AArch64 roadmap is NEON FP16/FHM (`asimdhp` and
`asimdfhm`), NEON DotProd (`asimddp`), NEON I8MM, NEON BF16, SVE I8MM, and SVE
BF16. AES/SHA/SM3/SM4/CRC and SVE crypto extensions, SVE bitperm, and FCMA/RDM
or miscellaneous DSP extensions are outside current scope unless later evidence
establishes unique validation value. SME and SME2 remain deferred until
physical hardware exposing them is available.

Outstanding adopted specialized families, each requiring its own design,
implementation, independent software verification and physical acceptance:

- [ ] NEON FP16/FHM (`asimdhp` / `asimdfhm`).
- [ ] NEON DotProd (`asimddp`).
- [ ] NEON I8MM.
- [ ] NEON BF16.
- [ ] SVE I8MM.
- [ ] SVE BF16.

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
Agree which current ISA gates must close and explicitly approve any unavailable-
hardware deferrals before starting 1A; do not let this proposal silently waive
SVE wider-VL, specialized ISA or existing release-readiness obligations.
Existing deferred Phase 3/4 output migration remains separately gated; early
evidence groundwork does not authorize changing the legacy compatibility format.

## Deferred Hardware Modules

- Additional storage testing beyond the current Storage Health and Storage
  Benchmark baseline is deferred pending milestone 4 planning above.
- Before the first real AArch64 GPU OpenCL validation, add common AArch64
  multiarch loader paths through one shared resolver. Do not fork the OpenCL
  workers or claim ARM GPU OpenCL acceptance before hardware validation.
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
