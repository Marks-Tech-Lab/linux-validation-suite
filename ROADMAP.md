# Linux Validation Suite Roadmap

This roadmap is the project-status source for completed, deferred, and
undecided work. Deferred or possible work is not committed release scope.

## Prepared In v0.5.2-alpha

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

SSE3/SSSE3/SSE4.x, AES/SHA/GFNI, BMI/ADX, IFMA/VBMI, and similar extensions are
not adopted merely because they exist; they are not current general
thermal-stress priorities.

### AArch64 general SIMD work

Accepted AArch64 kernels are `scalar`, integer `neon`, and independently
verified `neon_fp32_fma`. Spark and Snapdragon functional and sustained NEON
acceptance is complete. `sve_fp32_fma` is implemented with scalable arithmetic,
per-thread VL initialization, independent verification, and progress reporting,
but actual ARM compilation, disassembly, and physical execution remain pending.

The adopted general SIMD work is:

1. Complete normal Spark SVE functional build/instruction/execution acceptance.
2. Establish SVE sustained effectiveness and negative-capability portability.
3. Consider general automatic SVE selection only after acceptance and review.
4. Design and implement distinct SVE2-specific work; SVE FP32/FMA is not SVE2.

Once SVE/SVE2 are independently accepted, future generic ARM instruction intents may
resolve as follows:

- `baseline_vector` selects NEON.
- `high_throughput_vector` selects the appropriate common SVE/SVE2 tier and
  falls back to NEON when that tier is unavailable.
- `highest_verified_vector` selects the highest accepted general vector tier
  common to the complete target CPU set.
- Explicit `neon`, `sve`, and `sve2` requests select that exact tier or fail
  closed.

SVE and SVE2 must not be encoded as automatically hotter than scalar or NEON.
For v0.5.2-alpha all generic ARM intents stay at accepted NEON tiers; ordinary
Auto stays NEON/scalar and Power Auto excludes SVE. Explicit SVE remains a
fail-closed experimental functional-testing request, not production acceptance.

### AArch64 specialized stress flavors

The adopted specialized AArch64 roadmap is NEON FP16/FHM (`asimdhp` and
`asimdfhm`), NEON DotProd (`asimddp`), NEON I8MM, NEON BF16, SVE I8MM, and SVE
BF16. AES/SHA/SM3/SM4/CRC and SVE crypto extensions, SVE bitperm, and FCMA/RDM
or miscellaneous DSP extensions are outside current scope unless later evidence
establishes unique validation value. SME and SME2 remain deferred until
physical hardware exposing them is available.

### AArch64 evidence and portability boundary

Earlier Spark diagnostic notes report Cortex-X925 plus Cortex-A725 CPUs,
GCC 13.3.0, a 16-byte/128-bit SVE vector length, and `asimd`, `fphp`, `asimdhp`,
`asimddp`, `asimdfhm`, `sve`, `sve2`, `svei8mm`, `svebf16`, `i8mm`, and `bf16`
CPU flags. Physical compiler probes passed for `-march=armv8-a+sve`,
`-march=armv9-a+sve2`, `-march=armv9-a+sve2+i8mm`, and
`-march=armv9-a+sve2+bf16`. This proves compiler capability only; it does not
claim runtime validation of the implemented LVS SVE kernel. Its actual per-thread
VL, deployed optional compiler path, optimized instructions, and execution must
be established in the pending functional acceptance; model names authorize nothing.

The baseline ARM64 helper must continue to build and run on the Snapdragon X1
Plus with scalar and NEON only. Do not compile the complete helper globally with
an SVE/SVE2-only `-march`. Future SVE, SVE2, and specialized implementations
must use isolated feature compilation, targeted functions or objects, compiler
capability probes, and appropriate runtime HWCAP/HWCAP2 checks. Snapdragon
regression validation is mandatory after the Spark ISA work.

## Deferred Hardware Modules

- Additional storage testing beyond the current Storage Health and Storage
  Benchmark baseline is deferred pending actual planning.
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
