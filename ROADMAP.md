# Linux Validation Suite Roadmap

This roadmap is the project-status source for completed, deferred, and
undecided work. Deferred or possible work is not committed release scope.

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

## Completed After v0.2.0-alpha On Main

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

## Deferred Hardware Modules

- Additional storage testing beyond the current Storage Health and Storage
  Benchmark baseline is deferred pending actual planning.
- ARM64/Linux support is a long-term goal after the core project is more
  complete and mature. It is not fully validated now and is not promised for a
  specific release.
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
