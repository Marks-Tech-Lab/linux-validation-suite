# Linux Validation Suite v0.5.2-alpha

Prepared corrective alpha; not a claim that a tag or GitHub Release already exists.
The maintainer publishes the GitHub prerelease manually after final code/tag review.

## Exact scope since v0.5.1-alpha

Previous release commit: `0ff535c02772e09e6980aab00d2cf9664cc56f3d`.
Audited development checkpoint: `a801ec5bd50a66979a4221d28f85fc8a8f7ea331`.
Exactly six intervening development commits, oldest first:

1. `29502fa7858d06cfc12d139b11a2f3a2119afa4d` — verified ARM64 NEON
   FP32/FMA: explicit vector arithmetic, independent binary32 reference,
   all-thread affinity and verification, timestamped verified progress,
   trimmed-throughput analysis, and compatibility/report evidence. Temporary
   accepted NEON profiles were archived.
2. `ddeee091c35926fb57c2d2dd17fde19f58760849` — implemented experimental
   scalable SVE FP32/FMA, optional targeted compilation, HWCAP/VL initialization,
   verification/progress contracts, and an active functional test profile.
   Strict integer error counters and contradictory-error rejection protect both
   versioned FP32 contracts. Added bounded Vulkan slow-operation diagnostics
   and export retention, not a fix for the historical GPU interruption.
3. `1634d5e33b20f4e4062b773e95becff2e67e5500` — fail-closed Vulkan physical
   device targeting: authoritative UUID/PCI evidence, target identity propagation,
   and independent compute/transfer runtime selection. Model similarity or a
   single visible candidate cannot establish physical identity.
4. `9218838a441852f017a0740fe64faa3384e57a35` — static GPU inventory UUID
   association and evidence-backed device/memory classification for identical
   models, with other-vendor, integrated, and platform-device compatibility.
5. `25d8426a1ef02ec260540b4cb04049cfff8588bd` — scoped deployed-source hashing,
   actual-content Git comparison, initial/final provenance, offline artifacts,
   and legacy compatibility. The original manual-stamp recommendation is
   superseded by the following checkpoint.
6. `a801ec5bd50a66979a4221d28f85fc8a8f7ea331` — automatic provenance workflow
   and source comparisons in ordinary reports, Results Overview, and QA;
   bounded local committed-content correlation; no manual provenance setup.

This release preparation additionally excludes experimental SVE from every
implicit generic vector and Power Auto path, while retaining explicit functional
selection and authoritative capability discovery. Native arithmetic is unchanged.

## Physical acceptance and limitations

- NEON FP32/FMA passed functional and 600-second sustained validation on Spark
  GB10 (20/20 threads, 15.205646 million verified blocks/s) and Snapdragon Oryon
  (8/8 threads, 12.639413 million verified blocks/s), with zero arithmetic
  mismatches, correct affinity, clean shutdown, and sufficient progress evidence.
  Supplied GCC 13/GCC 15 ARM binaries contain repeated vector FP32 FMLA and
  eight accumulator recurrences. Exact historical executed-binary hashes were
  not cryptographically established; source identity is not binary attestation.
- Fail-closed Vulkan targeting was physically accepted on the three-GPU
  Gigabyte system, including the two identical RTX PRO 6000 Max-Q cards and
  Workstation card. Correct execution and verification do not imply exhaustive
  requested VRAM coverage; observed allocation shortfalls remain separate.
- The historical synchronized GPU interruption remains unattributed. Diagnostics
  improve evidence, not a claim of a resolved root cause.
- SVE FP32/FMA is implemented but experimental and physically unverified.
  ARM compilation/disassembly and all-thread execution acceptance remain pending.
  Explicit `sve`/`sve_fp32_fma` requests require actual capabilities and never
  substitute NEON/scalar. SVE2 and SME are not implemented.
- No universal numerical GPU saturation or maximum CPU FP32 pipeline saturation
  was established. Very old/tiny-memory GPU physical coverage remains incomplete.
  Telemetry depends on platform/provider capability; unavailable is not zero.
  The legacy `card1` identity-label inconsistency remains a nonblocking follow-up.
- x86_64 and AArch64 support remains capability-specific, not an all-hardware
  guarantee. Existing thermal safety, memory reserves/guards, and output contracts
  remain authoritative. Alpha status remains appropriate.

## Manual GitHub prerelease draft

Title: **Linux Validation Suite v0.5.2-alpha — verified ARM compute and GPU identity reliability**

This corrective alpha adds physically validated ARM64 NEON FP32/FMA with
independent per-thread verification and sustained verified-work measurements.
It hardens Vulkan physical GPU selection with fail-closed UUID/PCI matching,
corrects identical-GPU inventory/memory association, and adds bounded GPU stall
diagnostics. Source fingerprints and comparisons now work automatically in
normal execution, diagnostics, reports, and QA—no stamps, Git, network access,
or new deployment steps required.

SVE FP32/FMA is included as explicit-only experimental development capability;
physical SVE acceptance is pending. SVE2/SME are not implemented. The historical
GPU interruption is not claimed fixed, VRAM coverage is not exhaustive, and no
universal saturation or complete hardware-coverage claim is made.

Existing scalar, integer NEON, x86 SIMD, safety, portable fallbacks, and historical
result compatibility are retained. This remains an alpha prerelease.
