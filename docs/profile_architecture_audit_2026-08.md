# LVS Profile and Runner Architecture Audit — 2026-08

Baseline inspected: `be63008ef908f1269e6043176fa231849dced1c5` (`Close 2026-08 hardware acceptance campaign`).

This audit separates profile intent from implementation architecture. The design was subsequently approved and implemented additively: the seven mixed operator profiles now use the three reviewed CPU instruction intents, while explicit ISA profiles and historical results retain their exact meanings. No ARM/x86 profile duplication, generic runner rename, or generalized workload abstraction was introduced.

## Approved implementation addendum

The implemented `cpu.instruction_intent` vocabulary is deliberately limited to:

- `baseline_vector`: x86 SSE/SSE2 family or AArch64 NEON;
- `high_throughput_vector`: x86 AVX2 family or AArch64 NEON, with explicit ARM tier-collapse evidence;
- `highest_verified_vector`: highest common verified non-scalar x86 vector kernel or AArch64 NEON.

Every intent requires the native helper, resolves against the complete target-CPU capability intersection, and fails closed rather than substituting scalar, stress-ng, or Python. An explicit `instruction_set` and `instruction_intent` are mutually exclusive. Quick Test stage 3 is now the approved generic `highest_verified_vector` check, not AVX512 certification.

The PL Validation family, QA System Test Short v2, and Quick Test retain their existing profile names. Their Power-labelled stages now explicitly use Power Auto; legacy SSE stages use `baseline_vector`; sustained AVX2 stages use `high_throughput_vector`; and Quick Test's former AVX512 stage uses `highest_verified_vector`. Legacy RAM ISA strings were returned to `auto` because the RAM execution layer does not consume them.

## Conclusions

- The workload stack is mostly shaped correctly: generic orchestration calls an architecture/capability policy, which selects architecture-specific native implementations only where an ISA actually requires one.
- The active GPU and storage profiles are CPU-architecture-neutral. Their limitations are API/device capability limitations, not x86 versus ARM profile limitations.
- `PL Validation` (all durations), `QA System Test Short v2`, and `Quick Test` were mixed legacy profiles. Their generic names now match architecture-aware intent resolution.
- A small, explicit workload-intent resolver is practical for those three profile families because scalar/baseline SIMD/high-throughput/highest-verified concepts already have verified x86_64 and AArch64 implementations. A large schema abstraction is not justified.
- The active Power profile is dynamically portable after the focused `power_auto` work: measured package-power selection is used only with credible CPU/package power telemetry; otherwise the architecture-specific validated fallback is explicit.
- Generic modules such as `lvs_workload_runner`, `lvs_workload_cpu_memory`, Python CPU/RAM workers, stress-ng integration, GPU orchestration, and storage orchestration should not be renamed to x86 variants.
- Accurate native-order aliases (`X86_NATIVE_POWER_PROBE_KERNEL_ORDER`, `ARM64_NATIVE_POWER_PROBE_KERNEL_ORDER`, `CPU_NATIVE_POWER_PROBE_KERNEL_ORDER`, and `cpu_native_power_probe_kernel_order`) are now available. Historical `MAX_POWER` names remain compatibility aliases.
- OpenCL discovery normally uses `ctypes.util.find_library("OpenCL")`, so it can work on AArch64, but its hard-coded fallback list lacks common AArch64 multiarch paths. This is a small future resolver improvement, not a reason to fork the OpenCL workers.

## Disposition codes

- **A** — Keep one generic profile unchanged.
- **B** — Keep one generic profile; make a small architecture-aware resolver improvement.
- **C** — Split into x86_64 and ARM64 variants.
- **D** — Rename as x86_64-specific because meaningful ARM parity does not exist.
- **E** — Create a distinct ARM64 counterpart because equivalent intent needs genuinely different stages.
- **F** — Archive; it is campaign/engineering material rather than a normal operator profile.

## Active profile audit

| Current profile | Classification | Architecture-sensitive stages / backend | Restriction | Runtime parity | Dynamic selector practical? | Recommendation | Proposed future name / compatibility |
|---|---|---|---|---|---|---|---|
| GPU EGL GLES 12hr | Architecture-neutral as written | EGL/GLES `gpu_3d`, all GPUs | Intentional graphics-API capability | Yes where EGL/GLES is available | Not needed | A | Keep name; capability failure remains explicit |
| GPU EGL GLES Lab | Architecture-neutral as written | EGL/GLES `gpu_3d`, all GPUs | Intentional graphics-API capability | Yes | Not needed | A | Keep |
| GPU OpenCL Variant Lab | Architecture-neutral as written | OpenCL baseline and integer-mix variants | Intentional API capability; loader fallback list is incomplete on ARM | Yes when ICD/loader exists | Small loader fix only | B | Keep profile name and backend IDs |
| GPU Troubleshooting Extended VRAM 80 | Dynamically architecture-portable | Auto mixed GPU/VRAM plus EGL, OpenCL, Vulkan compute stages | Intentional backend comparison | Yes by discovered GPU/API capabilities | Already dynamic | A | Keep |
| GPU Troubleshooting Extended | Dynamically architecture-portable | Auto mixed GPU/VRAM plus EGL, OpenCL, Vulkan compute stages | Intentional backend comparison | Yes | Already dynamic | A | Keep |
| GPU Troubleshooting dGPU Isolation | Dynamically architecture-portable | Auto `discrete_all` GPU/VRAM | Intentional target-class capability | Yes | Already dynamic | A | Keep |
| GPU Troubleshooting | Dynamically architecture-portable | Auto mixed GPU/VRAM plus EGL, OpenCL, Vulkan compute stages | Intentional backend comparison | Yes | Already dynamic | A | Keep |
| GPU VRAM dGPU Isolation 90 | Architecture-neutral as written | OpenCL VRAM on `discrete_all` | Intentional OpenCL/dGPU capability | Yes when OpenCL exists | Small loader fix only | B | Keep; do not create ARM copy |
| GPU VRAM dGPU Isolation | Architecture-neutral as written | OpenCL VRAM on `discrete_all` | Intentional OpenCL/dGPU capability | Yes when OpenCL exists | Small loader fix only | B | Keep; do not create ARM copy |
| GPU Vulkan Memory Lab | Architecture-neutral as written | Vulkan fused stateful-memory compute, all GPUs | Intentional Vulkan capability | Yes; hardware validated on x86_64 and AArch64 | Not needed | A | Keep |
| GPU Vulkan Stress Lab | Architecture-neutral as written | Vulkan verified stress-hash compute, all GPUs | Intentional Vulkan capability | Yes | Not needed | A | Keep |
| GPU Vulkan Transfer Diagnostic | Architecture-neutral as written | Vulkan transfer/readback, all GPUs | Intentional Vulkan capability | Yes | Not needed | A | Keep |
| PL Validation | Dynamically architecture-portable | Power Auto; baseline vector CPU+RAM+VRAM; high-throughput vector CPU+RAM | Approved architecture-neutral intent | Yes | Implemented | B complete | Generic name retained; old explicit result fields remain compatible |
| PL Validation 4hr | Dynamically architecture-portable | Same four-stage intent pattern as PL Validation | Approved intent | Yes | Implemented | B complete | Same migration as family |
| PL Validation 6hr | Dynamically architecture-portable | Same four-stage intent pattern as PL Validation | Approved intent | Yes | Implemented | B complete | Same migration as family |
| PL Validation 12hr | Dynamically architecture-portable | Two repeats of the portable PL pattern | Approved intent | Yes | Implemented | B complete | Generic name retained |
| PL Validation 24hr | Dynamically architecture-portable | Four repeats of the portable PL pattern | Approved intent | Yes | Implemented | B complete | Generic name retained |
| Power Test 5hr | Dynamically architecture-portable | Explicit `power_auto` CPU plus Auto GPU | Intentional cross-backend Power policy | Yes: measured when CPU/package power is credible; validated fallback otherwise | Implemented by focused Power objective | B | Keep name and existing backend/result identifiers; new selection evidence is additive |
| QA System Test Short v2 | Dynamically architecture-portable | Power Auto; baseline and high-throughput vector CPU+RAM | Approved architecture-neutral intent | Yes | Implemented | B complete | Generic name retained |
| Quick Test | Dynamically architecture-portable with a required dGPU capability | Power Auto CPU+dGPU; baseline vector+VRAM; highest verified vector+RAM | Approved generic breadth intent; exact AVX512 remains a separate concern | Yes where its required dGPU exists | Implemented | B complete | Generic name retained; stage 3 is not AVX512 certification |
| Storage Benchmark Quick | Architecture-neutral as written | fio/storage target policy | None beyond OS/tool/storage safety capability | Yes | Not needed | A | Keep |
| Storage Benchmark Sequential | Architecture-neutral as written | fio/storage target policy | None beyond OS/tool/storage safety capability | Yes | Not needed | A | Keep |

### Active classification summary

- Architecture-neutral as written: 10 profiles.
- Dynamically architecture-portable: 12 everyday profiles after the approved migration, plus the temporary CPU confirmation profile.
- Mixed / partially portable: 0 profiles after the approved migration.
- Explicit active x86_64-specific profiles: 0.
- Explicit active ARM64-specific profiles: 0.
- Completed generic intent migrations: PL family, QA, Quick.
- Profiles that should remain split: none among current everyday profiles. Exact-ISA certification profiles, if still desired, should be explicit diagnostics rather than silently embedded in generic schedules.

## Implemented dynamic-profile design

The approved profile-facing CPU intent values resolve through the existing CPU architecture/capability policy:

| Intent | x86_64 resolution | AArch64 resolution | Notes |
|---|---|---|---|
| `baseline_vector` | SSE2-family verified native kernel | NEON verified native kernel | No scalar/backend substitution |
| `high_throughput_vector` | AVX2/FMA family where common | NEON today | ARM tier collapse is explicit; no SVE/SVE2/SME |
| `highest_verified_vector` | highest common verified non-scalar x86 kernel | NEON | Resolves downward across verified vector tiers, never to scalar |

RAM integrity, GPU compute, GPU stateful memory, and storage concepts already resolve through backend/capability policy and do not need architecture-specific profile duplicates. Intent aliases should be additive. Existing `instruction_set` values, parsed output fields, logs, fixtures, and historical comparison contracts must continue to load and retain their exact historical meaning.

## Runner, workload, and module audit

| Layer / name | Classification | Finding | Recommendation |
|---|---|---|---|
| `lvs_workload_runner` | Architecture-neutral orchestration | Coordinates CPU/RAM/GPU plans and processes; no x86 implementation assumption in its role | Do not rename or duplicate |
| `lvs_workload_cpu_memory` | Architecture-aware dispatcher/policy adapter | Uses architecture, common target-set capability, backend selection, and architecture-specific native helper resolution | Keep generic name; this is the correct dispatch boundary |
| `lvs_cpu_execution` | Backend-neutral command/evidence policy with native-kernel catalog | Builds native, stress-ng, and Python commands; legacy `MAX_POWER` symbols can mean candidate order rather than a measured outcome | Future additive aliases such as `NATIVE_POWER_PROBE_KERNEL_ORDER` / `NATIVE_KERNEL_PREFERENCE_ORDER`; retain old symbols and result values for compatibility |
| `lvs_cpu_backend_policy` | Architecture-neutral backend policy | Normal Auto remains native → stress-ng → Python and is separate from Power Auto | Do not rename; preserve behavior |
| `lvs_cpu_architecture` | Architecture/capability policy | Correctly rejects incompatible public ISAs and resolves x86_64 versus ARM64 native artifacts | Keep name; clarify “max power order” terminology additively later |
| `lvs_cpu_power_selection` | Architecture-aware Power policy | Cross-backend measured probe plus truthful architecture-specific fallback | Keep separate from normal Auto; name is accurate |
| `native/cpu_stress_helper.c` | Shared source containing architecture-specific implementations | Compile guards contain x86 SSE/AVX kernels and Linux AArch64 NEON plus scalar; dispatcher and evidence are shared | Do not split source merely for filenames |
| `build/cpu_stress_helper` / `_arm64` | Architecture-specific artifacts with asymmetric legacy naming | Unsuffixed artifact is historically x86; ARM suffix protects against stale binaries | Later add an explicit `_x86_64` alias/manifest metadata while retaining unsuffixed legacy resolution; do not break installs/results |
| `native/memory_stress_helper.c` and native memory runner | CPU-architecture-neutral C memory integrity workload | Pattern/integrity logic is not an x86 ISA test | Keep generic name and one profile intent |
| Python CPU worker | Backend-specific, CPU-architecture-neutral | PBKDF2 plus independent recomputation/`compare_digest`, explicit affinity and evidence | Keep generic; no ARM duplicate |
| Python RAM worker | Backend-specific, CPU-architecture-neutral | Retained-page pattern verification/rewrite | Keep generic; no ARM duplicate |
| stress-ng CPU/RAM paths | External backend, CPU-architecture-neutral policy | ISA semantics are approximate unless native explicit ISA is requested; matrixprod is the current ARM no-power Power fallback | Keep backend IDs and truthful evidence |
| GPU backend resolver/runner | Architecture-neutral orchestration | Selects by stable physical GPU identity and backend/device capability | Do not rename to x86 or ARM |
| OpenCL probe/compute/VRAM workers | Backend-specific, CPU-architecture-neutral | `find_library` is portable; hard-coded fallback paths omit AArch64 multiarch locations | Future narrow shared-library resolver update; do not fork workers or profile library |
| Vulkan runtime/compute/transfer/stateful workers | Backend-specific, CPU-architecture-neutral | Loader fallback includes x86_64 and AArch64; workers bind physical Vulkan identity | Keep names and shared workers |
| EGL/GLES worker | Backend-specific, CPU-architecture-neutral | Depends on graphics/display/device capability, not CPU ISA | Keep shared |
| Storage benchmark/discovery/health paths | Architecture-neutral | fio and storage safety policy have no x86 ISA dependency | Keep shared |
| Profile-facing backend identifiers and result fields | Public/historical compatibility contract | `cpu_native_helper`, `stress_ng`, `python_fallback`, OpenCL/Vulkan/EGL identifiers appear in old results, parsed exports, logs, and fixtures | Any future naming cleanup must use aliases/migration, never destructive replacement |

## Archived campaign profile disposition

Normal discovery is intentionally nonrecursive. Every campaign JSON remains paired with its `_info.txt` sidecar below `profiles/Archived/`, preserving reproducibility without filling the operator picker.

| Archive destination | Profiles moved/organized | Classification and reason |
|---|---|---|
| `2026 Hardware Validation/01 Bring-up and Functional/ARM64/` | ARM64 CPU Targeting Functional; CPU Utilization Native Scalar Short; CPU Utilization Python Fallback Short; Native CPU NEON; Native CPU Scalar; Native Memory Validation; Python CPU Fallback AVX2 Diagnostic; Python CPU Fallback Auto; Python CPU Fallback Scalar; stress-ng CPU Auto | ARM64-specific bring-up, fallback, targeting, and short probe material; campaign-only but useful evidence/reproduction designs (F) |
| `2026 Hardware Validation/01 Bring-up and Functional/x86_64/` | x86_64 CPU Targeting Functional | Campaign targeting probe retained for fixtures/reproduction (F) |
| `2026 Hardware Validation/02 Sustained Acceptance/ARM64/` | ARM64 CPU Full Validation; Combined Full Validation; Combined Heatsoak Validation; GPU Full Validation; Memory Full Validation | Sustained ARM acceptance runners, not everyday workflows (F) |
| `2026 Hardware Validation/02 Sustained Acceptance/x86_64/` | x86_64 AMD APU GPU Full Validation; AMD dGPU Full Validation; AMD dGPU OpenCL Optional Validation; CPU AVX512 Optional Validation; CPU Full Validation; Intel iGPU Full Validation; Memory Full Validation; Multi-GPU Combined Full Validation; NVIDIA dGPU Full Validation; NVIDIA dGPU OpenCL Optional Validation; iGPU EGL Optional Validation; iGPU OpenCL Optional Validation | Sustained vendor/backend acceptance runners, retained as historical reproducibility material (F) |
| `2026 Hardware Validation/03 Exact-Hardware Vulkan Reruns/` | ARM64 Snapdragon Vulkan Rerun; x86_64 285K Intel R9700 Vulkan Rerun; x86_64 5700G RTX 5090 Vulkan Rerun; x86_64 8600G RTX PRO 6000 Vulkan Rerun | Exact-hardware reruns grouped instead of scattered at archive root (F) |
| `2026 Hardware Validation/04 Campaign Initial Reruns/` | ARM64 Integrated Shared-GPU Acceptance Rerun; x86_64 Discrete GPU Acceptance Rerun; x86_64 Integrated and Discrete GPU Acceptance Rerun | Initial broad rerun phase retained (F) |
| `2026 Hardware Validation/05 Final Remediation and Confirmation/` | ARM64 Shared-GPU Stateful Remediation; x86_64 APU Full Mixed Stateful Confirmation; x86_64 APU Multi-dGPU Remediation; x86_64 APU Shared-GPU Remediation; x86_64 RAM Evidence Remediation; x86_64 RAM and Full Mixed Confirmation | Final issue-specific remediation and closeout profiles retained (F) |
| `2026 Hardware Validation/06 Power Auto and Instruction Intent Confirmation/` | CPU Power Auto and Instruction Intent Confirmation | Completed generic five-system Power Auto/instruction-intent hardware confirmation, retained with its sidecar for exact campaign reproducibility (F) |
| `Reusable Diagnostics/Vulkan/` | GPU Vulkan Compute Lab | Reusable diagnostic retained, but organized outside the campaign and outside normal discovery |

Deleted profiles: **none**. Exact-hardware one-offs were archived because they still encode unique historical target/coverage decisions; uncertainty was resolved in favor of preservation.

Retained active profiles are exactly those in the active-profile table. They are normal operator or reusable lab/troubleshooting workflows; the approved PL/QA/Quick conversion is now implemented through the additive instruction-intent resolver described above.

## Compatibility constraints preserved by the migration

1. Do not reinterpret historical `instruction_set` values. A saved `sse`, `avx2`, `avx512`, or `neon` must continue to mean that exact request.
2. Add intent fields/aliases rather than rename backend identifiers or parsed-result keys.
3. Preserve legacy `parsed_results_custom.json`, `parsed_results_extended.json`, logs, comparison fixtures, and cold-import contracts.
4. Make incompatible explicit ISA requests fail closed as they do now; dynamic intent is opt-in, not a silent downgrade of exact ISA certification.
5. Keep normal CPU Auto separate from Power Auto. Cross-backend comparison belongs only to explicit Power intent.
6. Validate the converted PL/QA/Quick files with x86_64 and AArch64 fixtures and the planned two-system hardware confirmation.

## OpenCL AArch64 future prerequisite

Before the first real AArch64 GPU OpenCL validation, centralize loader candidate construction, add common `/usr/lib/aarch64-linux-gnu` and `/lib/aarch64-linux-gnu` paths, and use the same resolver for probe, compute, and VRAM workers. The workers themselves remain architecture-neutral and must not be duplicated. The current Snapdragon exposes no usable GPU OpenCL device, so this is future capability work rather than a current acceptance defect.

## Current stopping point

The additive intent migration is complete in software and awaits the planned two-system Power Auto/instruction-intent confirmation. No runner split or mass rename is recommended. The OpenCL loader improvement remains deliberately deferred until ARM OpenCL hardware is available for validation.
