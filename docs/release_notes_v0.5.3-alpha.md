# Linux Validation Suite v0.5.3-alpha

Prepared for final review on October 30, 2026. LVS remains an alpha-stage
project. Development commit `00772b2c9a233680827bc765cd368e23677d6d2b`
was pushed with the mistaken prepared identity v0.5.2, without a release tag
or GitHub Release. A separate metadata-only correction prepares v0.5.3-alpha;
it does not amend or rewrite that commit. The published `v0.5.2-alpha` tag and
[historical alpha notes](release_notes_v0.5.2-alpha.md) remain unchanged.

## Release scope

This alpha corrective reliability milestone consolidates the post-alpha development
and accepted physical campaigns without adopting future stress workloads.

- ARM64 SVE FP32/FMA has independently verified scalable arithmetic, all-thread
  affinity/VL evidence, actual preserved-binary instruction inspection and
  600-second Spark sustained acceptance at 128-bit VL. Snapdragon non-SVE
  compilation, rejection, scalar and NEON execution passed. The original Spark
  functional run lacked a launch hash; later process executable observations
  strengthen later runs, not that historical launch association.
- Operator-selected ARM64 `highest_verified_vector` prefers common-capable
  SVE FP32/FMA, NEON FP32/FMA, then integer NEON. Spark/Snapdragon integration
  passed. SVE remains experimental; ordinary Auto, Power Auto, baseline and
  high-throughput policies retain their previous behavior. Explicit ISA requests
  remain exact/fail-closed. Selection never establishes physical acceptance.
- Vulkan physical targeting preserves independent PCI/UUID/DRM evidence,
  including non-PCI Adreno, mixed vendors and identical NVIDIA models. Native
  workers revalidate the intended physical device; names and API ordinals are
  not substitutes for identity.
- Vulkan compute bounds use host-validated descriptor capacity instead of the
  demonstrated NVIDIA large-descriptor `OpArrayLength` failure. Padded
  multidimensional dispatch retains logical bounds. Stateful memory submits one
  buffer at a time while preserving full allocation and arithmetic work; this
  resolved the tested Radeon 610M grouped-submission timeout mechanism.
- Shared/unknown GPU memory uses conservative system-memory protection; only
  positively established dedicated memory receives the device-memory exemption.
  Host staging remains protected independently. Final safe targets are not
  enlarged by later minimum-size normalization, and infeasible assignments remain
  explicit. Reserves and 60%/85% allocation assessment bands are unchanged.
- EGL texture patterns, nonzero-index readback and slow-frame verification
  scheduling are corrected. Shared bounded texture geometry reconciles planning
  and actual execution. OpenCL geometry, bounded event/readback batches,
  allocation timing and publication scheduling improve coverage while retaining
  actual GPU work, synchronization, host-buffer ownership and corruption checks.
- Cleanup errors prevent worker success without discarding successful arithmetic
  evidence. Vulkan terminal results persist after cleanup. Parent Vulkan compute
  shutdown allows two validated observed maximum cycles plus five seconds for
  cleanup, with a 15-second fallback and 60-second hard allowance cap. Independent
  monotonic deadlines are not renewed by sequential waits; hangs still fail.
- Unfinalized executions cannot become completed PASS. Actual process failures,
  unknown cleanup and unavailable verification remain distinct from positive
  execution evidence. Legacy results and compatibility exports remain readable;
  historical evidence is not rewritten.
- CLI/TUI Save As and Copy immediately save validated discoverable profiles.
  Shared run-local workload/physical-GPU overrides affect effective execution
  and captured profiles without changing saved profiles or leaking into fresh
  runs. Captured-profile serialization/replay preserves strict authored input
  validation and targeted historical null-field compatibility.
- Source provenance remains automatic and offline, with the unchanged v1 scope.
  Native CPU/RAM executable observations separately associate prelaunch,
  running-process and post-execution bytes. Neither source hashes nor executable
  snapshots attest external dependencies or continuous executable-memory integrity.

## Physical acceptance boundary

The accepted campaigns cover x86-64 and AArch64 configurations, not every device
implementing those architectures. The October 29 wave exercised Ryzen 9800X3D,
9900X and 9950X, Threadripper PRO 7965WX, Intel i7-10750H and Core Ultra 9 285K,
NVIDIA GB10 Spark and Snapdragon Oryon. GPUs included RTX 5090, RTX PRO 6000
Blackwell variants (including identical-model pairs), GTX 1660 Ti, Radeon iGPUs
and RX 6600 XT, Intel integrated graphics and Adreno X1-45.

These executions verified actual native CPU/RAM progress, common-safe ISA and
affinity behavior, GPU identity and sampled integrity, guards and lifecycle
evidence. They include legitimate warnings and correctly blocked unsupported
attempts; they were not retrospectively relabelled as uniform PASS results.
Earlier targeted campaigns separately accepted EGL/OpenCL corrections and
dedicated/shared Vulkan compute/transfer paths.

The final `2026-10-30_10-01-59_Quick Test` on MSI MS-16U7/i7-10750H confirmed
both formerly failing Intel UHD shutdown paths with concurrent GTX 1660 Ti.
Both Intel workers retained approximately 20.990 GiB across 14 buffers and three
rounds, completed 45/46 cycles and 29 successful samples each, sampled every
buffer, completed initial/final verification and exited zero with confirmed
cleanup and zero claims. Actual shutdown took 4.945/6.854 seconds from the parent
request, within independently selected 9.898/10.155-second allowances. Opt-in
diagnostic publication added approximately 0.371/0.498 seconds. The overall WARN
was the legitimate 96 C platform-temperature warning, not a lifecycle failure.

Local evidence is retained under `results/` (including archived earlier runs)
and is deliberately not shipped in the public repository. No additional physical
campaign is required for metadata-only preparation without contradictory evidence.

## Accepted source and prepared-release provenance

Accepted final physical-source scope: `lvs_execution_source_v1`, SHA-256,
368 files, complete:

```text
d14b5bb1450385929fdb08d6dcc6f3253356293b06055b503a05c44e7620be21
```

It is recorded by the October 30 execution, its `10-01-19` readiness capture and
matching endpoints. The earlier October 29 cross-hardware wave recorded
`e2313ef57a9c619bbbe4fc51055f81368997fd119abb4b7439224584eaeacc56`;
the intermediate MSI phase diagnostic recorded
`792447df751383d6c17ac8be132b8d07dcde4c625a896981b52e2c92d40182ba`.
These are distinct observations of successive development states, not invented
clean-commit identities. Their observed HEAD was `ba7a529ef4bd89f91d9014c6225ac696618b055e`;
modified scoped bytes prevented exact association with that commit.

Before the approved correction-profile archival, changing only `APP_VERSION`
from `0.5.2-alpha` to `0.5.2` yielded this prepared scoped fingerprint:

```text
ff48a7e08a9d6d5053dd13fa33ad250dfdf73814967d660280c4d9f3ea154b46
```

After moving the five byte-preserved correction profiles to
`profiles/Archived/2026 Hardware Validation/08 GPU Corrections October 22/`,
the earlier v0.5.2 preparation fingerprint was complete across 363 scoped files:

```text
7c42ed499e77a034d30771e224883c0145777e669cc0625265bc001d3b91b9a4
```

Correcting only `APP_VERSION` from `0.5.2` to `0.5.3-alpha` gives the current
complete prepared fingerprint across the same 363 scoped files:

```text
6683c863794c7f389265aa51541784cc880fd67a0baa9b865fb06d657c539140
```

The release-document renames and Markdown edits are outside v1 source scope.
Restoring the version bytes to `0.5.2` reconstructs the preceding `7c42...`
fingerprint exactly. No prepared fingerprint exactly matches a physical run.
Preparation changes
version, documentation and ordinary profile inventory, not executable workload
behavior or profile configuration bytes. Markdown and smoke tests are
outside v1 scope. Runtime version bytes inside `Modules/lvs_core.py` are inside
scope. Root `profiles/*.json` are inside scope; archived profiles are outside it.
The archive removes five root profile paths from the scope; it does not remove
their historical JSON from the repository. Restoring those five records and the
old version bytes reconstructs the accepted physical fingerprint exactly. Any
further scoped inventory change requires a new recorded digest before commit/tag
review. Git commit/tag creation alone is outside
scope, but a clean association requires all scoped source to match the commit.

Normal copying/execution needs no manual stamp, packaging or Git operation.
The optional legacy stamp mechanism is advanced compatibility evidence only.

## Limitations retained

- GPU readbacks are sampled. Sampling every buffer is not exhaustive byte
  verification, proof of physical residency, dependency attestation or maximum
  pipeline saturation.
- SVE physical acceptance is at Spark's observed 128-bit VL. Wider VLs, other
  SVE implementations, SVE2/SME and specialized ARM families remain unaccepted
  or unimplemented as specified in [ROADMAP.md](../ROADMAP.md).
- General x86 SSE/AVX families retain common-capability requirements. Specialized
  VNNI/BF16/FP16, AMX and AVX10 work remains separately gated future work.
- GB10 ARM OpenCL compute/VRAM is accepted within the campaign; Snapdragon's
  captured OpenCL stack exposed no usable GPU. Optional backend availability is
  not guaranteed on every machine.
- Allocation shortfalls, unavailable telemetry, reserve warnings, temperatures,
  root-drive/CoW benchmark caveats and skipped storage targets remain visible.
  A shortfall is not a diagnosis of defective hardware or full target acceptance.
- Historical USB/UAS/persistence incidents and the historical GPU inactivity
  cause are not claimed fixed by these workload corrections. Filtered kernel
  journals do not turn permission-denied `dmesg` into complete kernel coverage.
- GPU power/utilization measurements do not prove architectural efficiency or
  maximum saturation. Public-safe exports and private migration remain distinct.
- Dynamic/transient GPU or coordinated CPU/GPU power stress is proposed work,
  after the adopted major ISA gates and before substantial new storage/network
  stress. Its design, safety and acceptance criteria remain future decisions.

## Software release checks

The pre-preparation baseline passed 314/314 smoke tests and 81/81 active/archived
profiles, with five unchanged advisories. Final prepared-tree validation and the
exact proposed file list are recorded in [the release inventory](release_inventory_v0.5.3-alpha.md).
The approved correction-profile archive leaves 25 active and 56 archived profiles,
81 total, with their exact workload settings preserved.

## Draft manual GitHub prerelease

Tag: **v0.5.3-alpha**. Publish as a GitHub **prerelease** after separate approval.

Title: **Linux Validation Suite v0.5.3-alpha — Reliability and Cross-Hardware Validation**

- Correct GPU readback, scalable allocation, physical targeting and bounded
  lifecycle behavior across the tested NVIDIA, AMD, Intel and Adreno paths.
- Close NVIDIA large-descriptor bounds, Radeon grouped-submission timeouts and
  MSI Intel shutdown acceptance with preserved arithmetic and safety evidence.
- Add automatic CPU/RAM executable provenance and truthful incomplete/failed
  result interpretation alongside automatic source identity.
- Confirm experimental SVE FP32/FMA at Spark 128-bit VL and operator-selected
  highest-vector integration with safe non-SVE Snapdragon selection.
- Make CLI/TUI profile saving, temporary workloads and physical-GPU targeting
  consistent and preserve captured-profile replay.

Hardware-sensitive limitations remain: GPU sampling is not exhaustive VRAM
verification; broader SVE hardware/VLs and specialized/dynamic stress are future
work; legitimate thermal, capacity, telemetry and storage warnings remain visible.
