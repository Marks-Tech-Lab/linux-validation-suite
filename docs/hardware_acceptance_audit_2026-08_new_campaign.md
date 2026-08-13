# LVS new-campaign hardware acceptance audit (2026-08-13)

Baseline under test: `9f3c291ee5d375a395dd12c868daccf26054cfba` (`Complete hardware acceptance audit and rerun coverage`). This audit treats saved PASS/WARN/FAIL/SKIP values as observations, not acceptance decisions. The authoritative 86-row stage matrix is `hardware_acceptance_matrix_2026-08_new_campaign.csv`.

## Dataset and execution inventory

Six independent Advanced Debug executions and twelve immediately preceding Dry Run/preflight captures were found. There is no separately labelled Readiness artifact; the two `dry_run_diagnostics` captures per system are the saved preflight evidence. Reparsed/support/archive copies are not counted as executions.

| Execution | Actual hardware | Topology | Profile result | Duration |
|---|---|---:|---:|---:|
| `2026-08-13_14-04-49_x86_64 Integrated and Discrete GPU Acceptance Rerun` | i7-10750H; Intel UHD CML; GTX 1660 Ti | 6 physical / 12 logical, non-hybrid Intel | FAIL | 9056.6 s |
| `2026-08-13_14-07-11_x86_64 Integrated and Discrete GPU Acceptance Rerun` | Ryzen 7 5700G; AMD Renoir iGPU; RTX 5090 | 8 / 16 | FAIL | 6652.1 s |
| `2026-08-13_14-10-33_x86_64 Integrated and Discrete GPU Acceptance Rerun` | Core Ultra 9 285K; Intel ARL iGPU; Radeon AI PRO R9700 | 24 / 24 | FAIL | 9068.8 s |
| `2026-08-13_14-12-23_x86_64 Integrated and Discrete GPU Acceptance Rerun` | Core i9-14900; Intel RPL-S iGPU; RTX 5090 | 24 / 32 | FAIL | 9057.2 s |
| `2026-08-13_14-14-53_x86_64 Integrated and Discrete GPU Acceptance Rerun` | Ryzen 5 8600G; Radeon 760M; RX 550; T1000 8GB; RTX PRO 6000 Blackwell Max-Q | 6 / 12 | ABORTED | 6591.0 s |
| `2026-08-13_14-15-12_ARM64 Integrated Shared-GPU Acceptance Rerun` | Qualcomm Oryon; Adreno X1-45 | 8 / 8 | FAIL | 6611.8 s |

The 5700G AMD iGPU was present in this campaign and is audited normally. No historical absence diagnosis was attempted. The 8600G/RTX PRO configuration is included because it actually appears in the saved evidence, not because of the superseded plan.

## Preflight accuracy

The i7, 285K, 14900, and ARM captures reported all required stages runnable and correctly predicted physical identities, Vulkan backends, and launch memory semantics. Runtime Vulkan indices sometimes changed, but stable PCI/card identity matched; this is not wrong-device execution.

The 5700G and 8600G captures reported only 11/15 stages runnable because `integrated_all` matched nothing, although Vulkan and execution inventory exposed real AMD integrated GPUs. They also left the profile-level `runnable` value true because at least one stage could run. This was an LVS selector/classification defect plus misleading acceptance-preflight completeness. On the 8600G, `discrete_all` also omitted the Vulkan-discrete RX 550 while selecting both NVIDIA devices. Dry Run memory plans otherwise matched execution subject to normal MemAvailable drift.

## Stages audited

Every execution includes verified stress-ng CPU, verified Python CPU, stress-ng RAM, Python RAM, integrated compute/transfer/stateful, discrete compute/transfer/stateful, RAM+iGPU, RAM+dGPU, all-GPU compute, RAM+all-GPU memory, and full CPU+RAM+all-GPU mixed load. ARM includes the analogous 11 stages: the four evidence stages, standalone integrated compute/transfer/stateful, CPU+compute, RAM+shared stateful, CPU+RAM+shared stateful, and full compute/shared-stateful mixed load. All 86 rows—including skipped and partially executed rows—are in the CSV matrix.

Independent status totals: 53 `VALIDATED`, 5 `VALIDATED WITH EXPLAINED WARNING`, 11 `FAILED`, 3 `UNPROVEN DUE TO INSUFFICIENT EVIDENCE`, 8 `UNEXPECTED SKIP / LVS DEFECT`, and 6 `PARTIALLY EXECUTED, NOT VALIDATED`.

## CPU acceptance

All twelve dedicated CPU evidence stages are validated. Every intended logical CPU had a worker, every Python worker applied affinity, all workers made substantial progress, verification failures were zero, and steady-state utilization was consistent with saturation.

| System | stress-ng workers; bogo ops | Python workers; progress range; verified passes | Aggregate median / p10 / minimum | Lowest logical-CPU median |
|---|---|---|---|---|
| i7-10750H | 12/12; 5,542,477 | 12/12; 3,904–3,944; 47,131 | 100 / 100 / 99.89% | 100% |
| Ryzen 7 5700G | 16/16; 6,748,761 | 16/16; 6,702–6,837; 108,573 | 100 / 100 / 100% | 100% |
| Core Ultra 9 285K | 24/24; 47,118,700 | 24/24; 15,746–17,716; 392,231 | 100 / 100 / 100% | 100% |
| Core i9-14900 | 32/32; 19,441,951 | 32/32; 4,399–5,160; 153,121 | 100 / 98.15 / 95.65% | 100% |
| Ryzen 5 8600G | 12/12; 5,543,434 | 12/12; 8,324–8,488; 101,102 | 100 / 100 / 100% | 100% |
| Qualcomm Oryon | 8/8; 439,878 | 8/8; 19,595–19,718; 157,268 | 100 / 100 / 100% | 100% |

stress-ng commands contained `--verify --metrics-brief`; dispatched/passed counts equalled requested counts and failed/skipped counts were zero. Python workers independently recomputed PBKDF2, used `compare_digest`, produced positive per-worker progress, and recorded zero mismatches. No target CPU was materially underloaded and no evidence shows workload displacement outside the intended allowed set.

Intel topology is hardware validated. The 285K reported the architectural hybrid flag on every pinned logical CPU: raw `0x40` on CPUs 0–7 and `0x20` on CPUs 8–23, aggregating to 8 P + 16 E physical cores, 24 logical CPUs, no SMT, and no homogeneous fallback. The 14900 reported raw `0x40` on logical CPUs 0–15 grouped into eight P-core SMT sibling pairs and raw `0x20` on CPUs 16–31 grouped into sixteen single-thread E cores: 8 P + 16 E physical, 32 logical. The 10750H reported `intel_cpuid_non_hybrid`, six physical sibling pairs and twelve logical CPUs, with no bogus E split. AMD remained unclassified by Intel logic and AArch64 retained generic package/cluster/core topology.

## RAM acceptance

Installed physical-memory reports were approximately 31 GiB (i7), 30 GiB (5700G), 93 GiB (285K), 62 GiB (14900), 30 GiB (8600G), and 15 GiB (ARM). All targets were resolved from launch MemAvailable minus reserve rather than naïvely from installed capacity.

stress-ng RAM is conclusively validated on the i7 and ARM: one VM worker, `--verify --metrics-brief`, 1 passed/0 failed, positive bogo totals (112,827,979 and 76,322,050), sustained roughly 602–605 seconds, and median used memory of 28.66 and 13.04 GiB. The 5700G, 285K, and 14900 created real pressure (median used 28.81, 82.81, and 56.18 GiB) but their logs stop at `stopping 1 stressors`; no final result/VM metrics were ingested. Their saved PASS labels are not accepted. The 8600G reached MemAvailable=0 for three samples; the runtime guard warned and then emergency-aborted at 530.8 seconds. That workload is failed, while the guard behavior is independently validated.

Python RAM allocated every assigned byte on all six systems but failed everywhere after 16 completed integrity passes. Assigned/retained bytes were 26,713,469,747 (i7), 2,261,966,848 (5700G), 80,055,209,984 (285K), 32,967,602,176 (14900), 13,181,108,224 (8600G), and 8,358,469,632 (ARM). The verifier's rewrite sequence legitimately reached byte value zero; `current_pattern or 1` then changed expected zero to one and generated millions of false mismatches. The low 5700G/14900/8600G assignments were launch-plan caps caused by transiently unreleased stress-ng VM memory, not Python allocator failure. The i7, 285K, and ARM already prove full allocation and sixteen real retained-set passes; the zero transition is deterministic and covered synthetically after correction. Because the verifier implementation changed, representative AArch64 and x86 hardware reruns remain in the minimal plan; the i7 need not duplicate the x86 proof.

Native RAM workers in accepted combined stages allocated their resolved targets, completed multiple pattern passes, and reported zero errors. The 14900 full mixed stage is the exception: two genuine `inverted_mix64` mismatches (threads 15 and 16) occurred among 10,740 successful passes. LVS correctly failed that stage; the cause is not supported as an LVS defect by current evidence.

## Vulkan acceptance by physical GPU

The repository-root bootstrap fix is proven: every executed Vulkan worker imported, selected a hardware device, created its device/pipeline, submitted work, read back data, and emitted durable evidence. No llvmpipe/lavapipe/software renderer was selected.

| GPU | Compute | Transfer | Stateful memory | Trustworthy response evidence |
|---|---|---|---|---|
| Adreno X1-45 | VALIDATED: 3,930 verifies / 11,789 frames | VALIDATED: 38,109 verifies / 114,326 frames | FAILED standalone: 4.295/9.096 GB (47.216%); combined targets up to 4.243 GB validated; full 4.295/4.489 GB (95.679%) | 1107 MHz median devfreq; 44.7–82.1 C depending stage; no invented utilization/power |
| Intel UHD CML | VALIDATED: 1,074 verifies | VALIDATED: 14,180 verifies | VALIDATED: 20.035 GB, ratio 1.0 | sustained 1150 MHz; no trustworthy busy counter due perf permission |
| Intel ARL | VALIDATED | VALIDATED | VALIDATED: 60.404 GB, ratio 1.0 | worker verification/clock evidence; no software substitution |
| Intel RPL-S | VALIDATED | VALIDATED | VALIDATED: 40.212 GB, ratio 1.0 | worker verification/clock evidence |
| Radeon AI PRO R9700 | VALIDATED: 731 verifies, busy median/p10 98/97% | VALIDATED: 9,806, 90/90% | VALIDATED: 30.788 GB, 1,843 verifies, busy 93%, memory busy 85% | resident VRAM about 29.19 GiB |
| GTX 1660 Ti | VALIDATED: 2,828, busy 92% | VALIDATED: 13,228, busy 91% | VALIDATED: 5.798 GB, 3,584 verifies | resident 5.41 GiB; stateful busy/memory busy 83/87% |
| RTX 5090 (5700G/14900) | VALIDATED: busy 87/83 and 91/82 median/p10 | VALIDATED: 96/95 and 95/94% | VALIDATED: 30.772 GB, 4,240/4,138 verifies | resident about 28.75 GiB; stateful busy about 73% |
| RTX PRO 6000 Blackwell | VALIDATED for selected paths: compute 99%, transfer 95%, stateful 92.378 GB / 1,483 verifies | same | same | resident 86.14 GiB; busy/memory busy 98/98% |
| NVIDIA T1000 8GB | VALIDATED for selected paths: compute 96%, transfer 98%, stateful 7.731 GB / 1,652 verifies | same | same | resident 7.21 GiB; busy/memory busy 96/96% |
| Radeon RX 550 | Compute VALIDATED in all-GPU combined stage (100%, 648 verifies) | NOT EXECUTED | 70%-class combined stateful VALIDATED at 751.6 MB; standalone 90% NOT EXECUTED | correct physical identity in `all` stages |
| Radeon Renoir iGPU | Compute VALIDATED in all-GPU stages (93/77%, 4,837/3,149 verifies) | UNEXPECTED SKIP | FAILED stateful: 483 MB of 6.978 GB (6.925%) | target existed; selector and capacity defects |
| Radeon 760M | Compute VALIDATED in all-GPU stages (91/80%, 6,127/4,403 verifies) | UNEXPECTED SKIP | FAILED stateful: 483 MB of 6.496 GB (7.439%) | target existed; selector and capacity defects |

The AMD APU stateful shortfall was not allocation pressure or guard intervention: `target_vram_total` exposed a small carved-out 512 MB region, which capped the worker to about 483 MB even though Vulkan reported an approximately 11 GB device-local shared heap and the unified plan assigned 6.5–7.0 GB. The worker also selected the first compatible small heap and had a fixed allocation-count ceiling. Dedicated GPU allocations remained outside the system pool and matched resident-VRAM telemetry; integrated commitments participated in the common pool.

## Combined-stage acceptance

ARM CPU+compute, RAM+shared stateful, CPU+RAM+shared stateful, and full CPU+RAM+compute+shared stateful all had concurrent overlap, sustained worker progress, correct CPU saturation where applicable, native RAM verification, GPU verification, and truthful allocation evidence. They are validated despite standalone Adreno stateful failure because their smaller assigned shared targets were actually attained.

All i7 and 285K combined interactions are validated. Guard/thermal warnings in RAM+all-GPU and full stages were explained warnings: no emergency occurred and every participant met allocation and verification requirements. On the 14900, RAM+iGPU, RAM+dGPU, iGPU+dGPU compute, and RAM+all-GPU memory are validated; only full mixed load failed because of the two real native RAM mismatches.

On the 5700G, RAM+dGPU and iGPU+dGPU compute are validated. RAM+all-GPU memory failed on the APU allocation. The saved full-stage PASS is rejected as partial: CPU, native RAM, RTX stateful, Renoir compute, and concurrency executed, but required Renoir shared-stateful pressure was omitted. On the 8600G, all-four-GPU compute is validated with a truthful thermal warning. Standalone discrete and RAM+dGPU stages are partial because RX 550 was omitted. RAM+all-GPU failed on the 760M allocation; full is partial because APU stateful pressure was omitted.

The unified launch planner, system reserve, claims, and release behavior are hardware validated on Intel iGPU and Adreno shared workloads. Mixed shared/dedicated isolation is validated on Intel+AMD/NVIDIA and ARM paths. Runtime guard warning/emergency behavior is validated, especially by the 8600G safe abort. AMD APU execution remains unvalidated until the shared-heap worker correction is rerun.

## Root causes and corrections

1. **Python RAM zero-pattern defect (common LVS, high confidence).** `Modules/lvs_python_memory_worker.py` treated zero as missing. Corrected to distinguish `None` from zero; regression traverses the 17th and later continuous passes.
2. **stress-ng VM final evidence loss (common orchestration/evaluator, high).** `Modules/lvs_stage_process_control.py` allowed only five seconds for large VM cleanup, killed without reaping, and therefore sometimes produced no worker result while the stage stayed PASS. VM workers now receive a bounded 30-second finalization grace, killed processes are reaped, and memory stress-ng executable provenance is captured. Existing strict evidence parsing then fails closed when final counts/metrics are absent.
3. **AMD GPU class selection (common identity/selector, high).** DRM heuristics alone could not distinguish AMD APU and small dGPU. `Modules/lvs_gpu_targets.py` and `lvs_workload_gpu_runtime.py` now merge authoritative matched Vulkan physical-device type before `integrated_all`/`discrete_all` selection.
4. **Integrated Vulkan stateful cap/heap/count (backend-common, high).** `native/vulkan_compute_worker.py`, `native/vulkan_transfer_worker.py`, and `Modules/lvs_vulkan_memory_policy.py` now ignore carved-out VRAM as an integrated total cap, prefer the largest compatible Vulkan heap for shared allocations, and derive a bounded count up to 256 while respecting `maxMemoryAllocationCount`. This also fixes Adreno's 32 × maxStorageBufferRange ceiling.
5. **GPU telemetry/result association (reporting defect, high).** `Modules/lvs_segment_gpu_targeting.py` previously trusted runtime worker index over physical slot/card. It now binds target evidence to telemetry via stable slot/card first. Existing raw slot-mapped telemetry is sufficient; no rerun is needed for this reporting-only defect.
6. **Acceptance preflight completeness (profile behavior, high).** `require_all_stages_runnable` is an explicit profile contract. `lvs_dry_run.py`, profile models/loader, and bootstrap preserve it; remediation profiles are blocked unless every required stage resolves.
7. **14900 native RAM mismatches (hardware/system anomaly, high evidence, unresolved cause).** Two mismatches are real. No code change masks them; one full mixed confirmation is required.

No CPU ISA/topology logic, reserve percentage, dedicated-VRAM semantics, telemetry collection, legacy result schema, or global `abort_on_worker_error` policy was changed.

## Profile disposition and minimal reruns

The three initial broad acceptance runners are archived under `profiles/Archived/2026 Hardware Validation/2026-08 New Campaign Initial/`, which is outside nonrecursive normal discovery. They are replaced temporarily by five fail-closed, hardware-class/evidence-gap profiles. All stages are 600 seconds and selectors remain generic (`integrated_all`, `discrete_all`, `all`).

| Actual system | One profile | Stages | Planned time |
|---|---|---|---:|
| i7-10750H | none | all required campaign paths are conclusively accepted | 0 min |
| Oryon/Adreno | `ARM64 Shared-GPU Stateful Remediation` | Python RAM 80%; integrated stateful shared memory 80% | 20 min |
| 285K/Intel/R9700 | `x86_64 RAM Evidence Remediation` | stress-ng RAM 80% with final verified metrics; Python RAM 80% | 20 min |
| i9-14900/Intel/RTX 5090 | `x86_64 RAM and Full Mixed Confirmation` | stress-ng RAM 80%; Python RAM 80%; full CPU+RAM70%+all-GPU compute/stateful70% | 30 min |
| 5700G/Renoir/RTX 5090 | `x86_64 APU Shared-GPU Remediation` | stress-ng RAM80%; Python RAM80%; iGPU transfer; iGPU stateful80%; RAM70%+iGPU70%; RAM70%+all-GPU memory70%; full mixed70% | 70 min |
| 8600G/760M/multi-dGPU | `x86_64 APU Multi-dGPU Remediation` | Python RAM80%; iGPU transfer; iGPU stateful80%; all-dGPU transfer; all-dGPU stateful90%; RAM70%+iGPU70%; RAM80%+all-dGPU90%; RAM70%+all-GPU70%; full mixed70% | 90 min |

Before launch, Readiness and Dry Run must show every stage runnable, the actual installed integrated/discrete devices, hardware Vulkan backends, and the intended unified plan. The explicit profile contract now makes partial readiness non-runnable. No separate shell, taskset, CPUID, or duplicate debug run is required; enable Advanced Debug once and preserve the complete result directory.

## Preserved validation

No rerun is required for dedicated CPU stress-ng/Python verification, CPU targeting/affinity, Intel P/E/SMT classification, Intel non-hybrid control, AMD/AArch64 topology, i7/ARM stress-ng RAM, native RAM except the isolated 14900 full anomaly, Adreno compute/transfer and validated combined paths, all Intel iGPU Vulkan paths, R9700/GTX/RTX/T1000/RTX PRO paths that actually ran, RX 550 compute and 70%-class stateful evidence, AMD APU compute, accepted combined interactions, unified planning on proven shared devices, runtime guard behavior, or telemetry re-association from raw evidence.
