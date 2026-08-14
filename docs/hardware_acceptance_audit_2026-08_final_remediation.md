# LVS final-remediation hardware acceptance audit (2026-08-14)

Original remediation-round baseline: `38164844d797b29d05c370192e742f78967d3d5b` (`Fix hardware acceptance gaps and minimize reruns`). Final-confirmation baseline: `75d7d19a47dcf0a6c26008ed7b34c9f7d1f1293e` (`Fix APU full mixed stateful validation`). Raw PASS/WARN/FAIL values were treated as observations. This report and the companion `hardware_acceptance_matrix_2026-08_final_remediation.csv` preserve both rounds as the final forensic record.

## Decision

**HARDWARE ACCEPTANCE CAMPAIGN COMPLETE — NO FURTHER HARDWARE RUNS REQUIRED FOR THIS DEVELOPMENT WAVE.**

The original remediation round accepted 25 of 27 stages and left only two AMD-APU full-mixed stages partial because LVS omitted integrated shared-stateful pressure while still reporting PASS/WARN. The focused confirmation round at baseline `75d7d19a` executed exactly those two 600-second stages. Both now contain the required fused Vulkan compute/stateful APU worker, meaningful shared allocation, complete CPU/RAM/all-dGPU participation, real steady overlap, continuous verification, and zero correctness failures. The 5700G row is `VALIDATED`; the 8600G row is `VALIDATED WITH EXPLAINED WARNING` for a non-emergency memory-pressure warning and T1000 thermal warning.

The previous Core i9-14900 native-RAM concern is closed: the confirmation completed 10,582 native pattern passes, including 2,653 `inverted_mix64` passes, with zero mismatches under concurrent CPU, RAM, Intel iGPU, and RTX 5090 load.

The 46 parsed Core i9-14900 PCIe AER events are preserved and classified separately as:

`KNOWN EXTERNAL PCIe SLOT AER CONDITION — EXCLUDED FROM LVS ACCEPTANCE VERDICT`

They are correctable NVIDIA `0000:01:00.0` Physical Layer / Receiver ID events from 10:25:54 through 10:35:22 during the full stage. They caused LVS's saved FAIL but did not coincide with worker failure, device loss, readback mismatch, RAM mismatch, crash, timeout, or reset. No suppression or workaround was added.

## Exact new campaign inventory

There are six executions and twelve preceding Dry Run captures. Diagnostics directories are preflight evidence, not additional executions. Archived, Uploaded, Reparsed, Support_Exports, and Migration_Bundles content was not counted.

| Execution | Actual system and topology | Actual GPUs | Profile | Runtime / Advanced Debug / LVS |
|---|---|---|---|---|
| `09-55-59` | Qualcomm Oryon, AArch64, 1 package, 8 physical / 8 logical, two 4-core clusters, no SMT | Adreno X1-45 shared platform GPU (`card1`, `platform:3d00000.gpu`) | ARM64 Shared-GPU Stateful Remediation | 1205.24 s / on / PASS |
| `09-57-38` | Core i7-10750H, 1 package, 6 physical / 12 logical, homogeneous Intel SMT | Intel UHD CML `0000:00:02.0`; GTX 1660 Ti `0000:01:00.0` | x86_64 RAM and Full Mixed Confirmation | 1842.39 s / on / PASS |
| `09-59-17` | Ryzen 7 5700G, 1 package, 8 physical / 16 logical, SMT | Radeon Renoir `0000:07:00.0`; RTX 5090 `0000:01:00.0` | x86_64 APU Shared-GPU Remediation | 4250.61 s / on / WARN |
| `10-00-31` | Core Ultra 9 285K, 1 package, 24 physical / 24 logical | Intel ARL `0000:00:02.0`; Radeon AI PRO R9700 `0000:04:00.0` | x86_64 RAM and Full Mixed Confirmation | 1912.69 s / on / WARN |
| `10-02-41` | Ryzen 5 8600G, 1 package, 6 physical / 12 logical, SMT | Radeon 760M `0000:08:00.0`; RX 550 `0000:04:00.0`; T1000 8GB `0000:05:00.0`; RTX PRO 6000 Blackwell Max-Q `0000:01:00.0` | x86_64 APU Multi-dGPU Remediation | 5460.41 s / on / WARN |
| `10-04-38` | Core i9-14900, 1 package, 24 physical / 32 logical | Intel RPL-S `0000:00:02.0`; RTX 5090 `0000:01:00.0` | x86_64 RAM and Full Mixed Confirmation | 1847.13 s / on / FAIL (known external AER only) |

The `09-57-38` i7-10750H execution is the operator's extra run. It was audited normally and is clean additional regression evidence; it does not create another rerun requirement.

## Readiness and Dry Run

Each execution has two immediately preceding diagnostics captures. Every capture set `require_all_stages_runnable=true`, reported profile runnable, and resolved all enabled stages: ARM 2/2, i7 3/3, 5700G 7/7, 285K 3/3, 8600G 9/9, and 14900 3/3. Device identities and selector classes matched execution:

- ARM: `integrated_all` resolved Adreno `card1` as shared.
- i7: Intel UHD shared plus GTX 1660 Ti dedicated.
- 5700G: Renoir shared plus RTX 5090 dedicated.
- 285K: Intel ARL shared plus R9700 dedicated.
- 8600G: Radeon 760M shared; RX 550, T1000, and RTX PRO 6000 all dedicated. `discrete_all` included all three dGPUs.
- 14900: Intel RPL-S shared plus RTX 5090 dedicated.

Dry Run accurately predicted commands, backends, selectors, and launch allocation semantics, subject to normal launch-time MemAvailable changes. It also reproduced the remaining defect: full mixed planning considered the AMD APU stage runnable while silently omitting the integrated VRAM/stateful worker because the carved-out 512 MiB report triggered a legacy concurrent-worker skip. Thus preflight predicted execution, but both preflight and execution violated the stage's all-GPU stateful contract. There were no required runtime SKIPs.

## Stage-by-stage acceptance

The authoritative matrix contains all 27 stages plus one separate external-AER finding. Status counts are:

- 19 `VALIDATED`
- 6 `VALIDATED WITH EXPLAINED WARNING`
- 2 `PARTIALLY EXECUTED, NOT VALIDATED`
- 1 `EXTERNAL KNOWN HARDWARE ISSUE / EXCLUDED`
- 0 `FAILED`, SKIP, insufficient-evidence, or not-executed rows

### ARM / Adreno

1. Python RAM: requested 12,937,501,081 bytes; safely resolved/assigned/retained 8,334,839,808 because launch MemAvailable minus the 1 GiB reserve could not support 80% of MemTotal. All 32 chunks succeeded; 1,036 continuous passes verified the full retained set, zero failures/MemoryError, median used memory 12.96 GiB, minimum MemAvailable 1.933 GB, no guard warning/emergency. PASS accepted.
2. Adreno stateful: requested 9,703,125,811 bytes plus fixed commitment; resolved target 9,495,633,920; allocated 9,495,638,016 (100% assigned, 97.86% of requested intent). The compatible 12,128,907,264-byte heap was selected and split into 71 buffers, proving removal of the 32-buffer ceiling. It ran 593.281 s, 1,600 frames, 534 readback verifications, zero mismatches/errors; clock median 1107 MHz, max 50.3 C, minimum MemAvailable 1.902 GB. PASS accepted. The prior 47.216% shortfall is closed.

### Extra i7-10750H

1. stress-ng RAM: exact command included one VM worker, 26,713,469,747 bytes, `--vm-keep --verify --metrics-brief`; 113,743,286 bogo ops, 1 passed/0 failed/0 skipped, trustworthy metrics, exit 0, 605.55 s, median used memory 28.72 GiB. PASS accepted.
2. Python RAM: 26,713,469,747 assigned/retained, 100/100 chunks, 390 passes, zero failures/MemoryError, median 28.73 GiB. PASS accepted.
3. Full mixed: 12/12 native AVX2/FMA workers pinned successfully; aggregate median/p10/min 100/100/100%, lowest logical median 100%; 2,272,004 canary/verify passes. Native RAM retained 16,130,985,984 bytes and completed 2,328 passes (586 mix64, 582 inverted, 581 walking, 579 address), zero errors. GTX stateful allocated 4,509,719,552 bytes with 1,951 verifies; Intel shared stateful allocated 12,069,482,496 with 173 verifies. All overlapped for at least 589.759 s. PASS accepted.

Topology is clean additional evidence: raw pinned CPUID reports non-hybrid, six SMT pairs `0,6` through `5,11`, 6 physical / 12 logical, no bogus E-core split.

### Ryzen 7 5700G / Renoir / RTX 5090

1. stress-ng RAM: 26,377,925,427 bytes, 116,472,044 bogo ops, final verified metrics durable, 1/0/0 pass/fail/skip, exit 0, median 28.72 GiB. PASS accepted.
2. Python RAM: 26,377,925,427 assigned/retained, 99 chunks, 357 passes, zero failures. PASS accepted.
3. Renoir transfer: correct RADV Renoir device, device+staging 50,331,648 bytes each, 43,179 readbacks, 129,537 frames, zero errors, 599.973 s; busy median/p10 74/74%. PASS accepted as transfer/routing validation, not shader saturation.
4. Renoir standalone stateful: 9,078,974,054 assigned, 9,078,977,536 achieved, nine buffers on the 11,348,717,568-byte shared heap, 487 verifies, zero mismatches, busy 98/98% median/p10. PASS accepted; prior carved-out-heap shortfall is closed.
5. RAM+iGPU: native RAM 20,336,713,728 bytes, 3,720 clean passes; Renoir shared 6,995,141,632 bytes, 234 verifies; CPU telemetry reaches 100% because native RAM threads actively verify; meaningful overlap at least 581.659 s. PASS accepted.
6. RAM+all GPU memory: native RAM 20,448,256,000; Renoir shared 7,033,716,736; RTX dedicated 23,933,645,824; every assignment reached, 3,694 RAM passes and 1,679 GPU verifies, zero failures. MemAvailable briefly entered warning range (minimum 917 MB) but never emergency; growth stopped safely and cleanup released claims. WARN accepted.
7. Full mixed: CPU/native RAM/Renoir compute/RTX stateful were healthy and concurrent, but Renoir received only a 50,335,744-byte `stress_hash` compute buffer. Its required 70% shared-stateful allocation was omitted. Saved PASS is rejected as `PARTIALLY EXECUTED, NOT VALIDATED`.

### Core Ultra 9 285K / Intel ARL / R9700

1. stress-ng RAM: 80,539,025,408 bytes, 200,744,933 bogo ops, 1/0/0, trustworthy final metrics, exit 0, 605.56 s, median used memory 82.27 GiB. PASS accepted.
2. Python RAM: 80,539,025,408 assigned/retained, 301 chunks, 127 full-set passes and zero failures. Allocation/steady work extended stage finalization to 671.48 s; no timeout or forced kill. PASS accepted.
3. Full mixed: 24/24 AVX2/FMA workers pinned, aggregate and lowest logical median 100%, 11,144,363 canaries. Native RAM 52,481,744,896 bytes, 3,970 clean passes. Intel shared stateful 39,337,710,592 bytes/80 verifies; R9700 dedicated 23,946,124,288/2,140 verifies, R9700 busy median/p10 85/84%, memory busy 77/76%. All overlapped at least 580.82 s. MemAvailable warning minimum 918 MB, no emergency. WARN accepted.

Pinned CPUID reconfirms 8 P (`0x40`) + 16 E (`0x20`), 24 physical/logical CPUs, no SMT and no homogeneous fallback. The captured USB UAS resets on external `usb 2-2` during RAM stages are platform/peripheral events; RAM verification stayed clean and LVS did not misclassify them as memory errors.

### Ryzen 5 8600G / Radeon 760M / RX 550 / T1000 / RTX PRO 6000

1. Python RAM: requested 26,110,319,001; safely resolved and retained 25,313,873,920, 95 chunks, 408 passes, zero failures, minimum MemAvailable 1.378 GB. PASS accepted.
2. 760M transfer: correct RADV Phoenix, device+staging 50,331,648 each, 58,873 verifies, 176,617 frames, 599.113 s, busy 62/61%. PASS accepted as transfer validation.
3. 760M stateful: 8,989,769,728 assigned, 8,989,773,824 achieved, nine buffers on the 11,237,212,160-byte shared heap, 817 verifies, busy 98/97%, zero errors. PASS accepted.
4. All-dGPU transfer: RTX PRO, RX 550, and T1000 all selected with stable slots. Device+staging allocations were 402.7+402.7 MB, 151.0+151.0 MB, and 201.3+201.3 MB; verifies 6,575/841/2,452; zero mismatch/error; busy medians 95/100/98%. PASS accepted. RX 550 routing defect is closed.
5. All-dGPU stateful: achieved 92,377,763,840 (RTX PRO), 805,310,464 (RX 550), and 7,730,941,952 (T1000), all 100% assigned; verifies 1,478/2,481/1,625. RTX PRO and T1000 reached 86/88 C maximum, producing truthful thermal warnings without verification loss. WARN accepted.
6. RAM+iGPU: RAM 18,597,601,280 with 3,791 passes; shared 6,396,070,912 with 704 verifies; 100% CPU telemetry and at least 598.51 s overlap. PASS accepted.
7. RAM+all dGPUs: RX 550 included with RTX PRO and T1000. RAM 25,642,704,896; dGPU allocations 92,377,766,912 / 805,310,464 / 7,730,945,024; all verified. Guard warning minimum 925 MB plus T1000 87 C, no emergency. WARN accepted.
8. RAM+all GPUs: RAM 19,395,194,880; RTX PRO 71,849,374,720; RX 550 751,623,168; 760M shared 6,672,011,264; T1000 6,012,957,696. All reached assigned target and verified, with 3,624 RAM and 5,607 GPU passes. Warning minimum 915 MB plus T1000 85 C, no emergency. WARN accepted.
9. Full mixed: 12/12 native AVX-512 integer workers pinned, aggregate/lowest median 100%, 5,807,045 canaries; native RAM 22,846,529,536 and 3,706 clean passes; all three dGPUs stateful and verified. The 760M received only 50,335,744 bytes of compute memory rather than 70% shared-stateful pressure. Thermal warning was accurate, but the full stage is `PARTIALLY EXECUTED, NOT VALIDATED`.

GPU telemetry mapping is stable: telemetry indices 0/1/2/3 map by slot/card to RTX PRO/RX 550/760M/T1000. No index drift, duplication, wrong-device clock/temperature, or misattributed utilization was found. Captured Wi-Fi invalid-WMM messages are unrelated platform noise.

### Core i9-14900 / Intel RPL-S / RTX 5090

1. stress-ng RAM: 53,616,207,462 bytes, 172,716,349 bogo ops, 1/0/0 with trustworthy final metrics, exit 0, 606.50 s, median used memory 55.95 GiB. PASS accepted.
2. Python RAM: 53,616,207,462 assigned/retained, 200 chunks, 112 passes, zero failures/MemoryError. PASS accepted.
3. Full mixed workload: 32/32 AVX2/FMA workers pinned, aggregate/lowest median 100%, 4,866,114 canaries. Native RAM allocated 34,043,154,432 bytes and completed 10,582 clean passes: mix64 2,659; inverted_mix64 2,653; walking_bit 2,638; address_xor 2,632. Intel shared stateful achieved 25,506,978,816 with 101 verifies; RTX stateful 23,933,645,824 with 2,643 verifies. All overlapped at least 578.875 s. Minimum MemAvailable 1,066 MB caused a warning, not emergency. The workload is independently accepted and closes the prior two-mismatch concern.

The stage's saved FAIL and run FAIL are solely the 46 known correctable AER events. They remain a separate external hardware finding and are excluded from LVS workload acceptance.

Pinned CPUID reconfirms 8 P physical cores represented by 16 SMT logical CPUs (`0x40`, pairs 0-1 through 14-15) plus 16 single-thread E cores (`0x20`, 16-31): 24 physical / 32 logical.

## Cross-cutting verdicts

### CPU

- Native: `VALIDATED`. New full stages used all intended logical CPUs, 100% median/p10/min aggregate utilization, 100% lowest logical median, successful affinity, positive canary/verification progress, and zero errors.
- stress-ng CPU and Python CPU: not present in these remediation profiles; the prior campaign's accepted evidence remains authoritative (stress-ng `--verify --metrics-brief`; Python PBKDF2 independent recomputation/`compare_digest`). No new regression invalidates it.
- ISA: `VALIDATED`. Actual tuned kernels: i7 AVX2/FMA; 5700G SSE2 integer; 285K AVX2/FMA; 8600G AVX-512 integer; 14900 AVX2/FMA. ARM NEON/native CPU evidence remains previously accepted and was not repeated.
- Affinity, P/E, SMT: `VALIDATED`, including new 285K, 14900, and i7 control evidence. AMD and AArch64 remain unaffected by Intel classification.

### RAM

- Python: `VALIDATED` on all six systems. Every assigned byte was retained, continuous rewrite cycles progressed beyond the former deterministic zero-pattern failure, and failures/MemoryError were zero. Pass totals: ARM 1,036; i7 390; 5700G 357; 285K 127; 8600G 408; 14900 112.
- stress-ng: `VALIDATED` on all four applicable x86 systems. Exact commands used one VM worker, byte target, `--vm-keep --verify --metrics-brief`; every run preserved positive bogo metrics, passed=1, failed/skipped/untrustworthy=0, exit 0.
- Native: `VALIDATED`. All new combined workers allocated their resolved targets and completed all four patterns with zero errors. The 14900 prior mismatch is closed by strong non-repetition under equivalent full pressure.
- Allocation, pressure, integrity, runtime guard: `VALIDATED`. Planner reductions were traceable to launch MemAvailable/reserve or shared-pool rebalance; workers followed assignments. Warning samples stopped growth without emergency or invalid PASS. Claims were released.

### GPU

- Adreno: stateful remediation `VALIDATED`; compute and transfer remain previously validated.
- Intel iGPU: `VALIDATED` from prior and new full mixed evidence.
- AMD APU/iGPU: standalone transfer, standalone stateful, RAM+iGPU, and RAM+all-GPU `VALIDATED`; full CPU+RAM+all-GPU shared-stateful concurrency remains not validated on 5700G and 8600G only.
- AMD dGPU: R9700 and RX 550 `VALIDATED`; RX 550 transfer/stateful/all-selector routing now executes.
- NVIDIA dGPU: GTX 1660 Ti, RTX 5090, T1000, and RTX PRO 6000 paths represented here are `VALIDATED`, with explained thermal warnings on the 8600G system.
- Multi-dGPU: `VALIDATED` for transfer, stateful, RAM+dGPU, and RAM+all-GPU. All actual dGPUs were selected; no `[None]` worker appeared.
- Vulkan compute/readback, transfer/readback, and stateful verification: `VALIDATED` per device where executed. No software renderer, device loss, reset, timeout, readback mismatch, compute mismatch, or worker crash.
- Shared heap/cap/count: `VALIDATED` on Adreno, Renoir, and 760M. Correct large compatible heaps were selected; carved-out 512 MiB did not cap standalone/combined allocation; legal splitting used 71 buffers on Adreno and 7-9 on AMD APUs.
- Dedicated VRAM isolation: `VALIDATED`. Dedicated targets were excluded from the system pool; only shared targets, staging, and fixed host costs were charged.
- Telemetry association: `VALIDATED`. Stable card/slot/platform identity agrees among discovery, worker, telemetry source map, parsed results, and summary.

### Combined

- CPU+GPU, RAM+iGPU, RAM+dGPU, RAM+all-GPUs, iGPU+dGPU, and multi-dGPU: `VALIDATED` for combinations actually required and executed, with warning limitations recorded in the matrix.
- CPU+RAM+GPU/full mixed: Intel+i7/285K/14900 `VALIDATED`; AMD APU 5700G/8600G `NOT VALIDATED` only for integrated shared-stateful participation. All other participants in those two stages were healthy.

## SKIP, WARN, FAIL, parser, and evaluator audit

No new stage or worker skipped. There were no worker FAILs, nonzero exits, allocation failures, integrity mismatches, device losses, or emergency aborts.

Every WARN was explained:

- runtime-memory warning only: 5700G RAM+all; 285K full.
- thermal only: 8600G all-dGPU stateful and full.
- runtime-memory plus thermal: 8600G RAM+dGPU and RAM+all.
- 14900 runtime-memory warning plus external AER-driven FAIL.

Manifest worker payloads match `stage_windows` and `parsed_results_extended.json` on all stages. Raw worker result counters, allocation bytes, identities, and exit statuses are ingested without discrepancy. Legacy custom output preserves GPU worker evidence and the additive compatibility contract; detailed non-GPU payloads remain authoritative in manifest/extended results. Run summaries match saved evaluator verdicts.

Two evaluator/preflight mismatches remain in the saved evidence: the 5700G full PASS and 8600G full WARN did not detect missing AMD shared-stateful workers. The current code fix prevents that planning omission. The 14900 saved FAIL is accurate under generic kernel-error policy but is independently overridden only by the operator-supplied narrow external-hardware exemption.

## Reconciliation with prior unresolved items

- Python RAM deterministic zero-pattern mismatch: closed on six systems.
- stress-ng VM final evidence loss: closed on four systems.
- Adreno 47.216% stateful allocation: closed at 100% assigned / 97.86% requested, 71 buffers.
- AMD APU selector/classification and required-stage skip: closed; integrated selectors ran on both APUs.
- AMD APU carved-out capacity and shared-heap selection: closed in standalone and RAM-combined stages.
- RX 550 omitted from `discrete_all`: closed in transfer, stateful, RAM+dGPU, RAM+all, and full routing.
- GPU telemetry stable association: closed.
- 14900 native RAM mismatches: closed by clean full confirmation.
- AMD APU shared-stateful participation in full mixed: confirmed still defective in the saved campaign; fixed in code, two minimal confirmations remain.

## Software correction and profile disposition

`Modules/lvs_vram_policy.py` now retains an integrated/APU Vulkan stateful worker during concurrent GPU 3D+VRAM stages. The stateful worker is already the fused compute+verified-memory worker and replaces the same-target 3D worker, so this does not double GPU load. OpenCL safety behavior is unchanged. Regression coverage explicitly protects shared GPUs with small carved-out VRAM reports.

The five original one-off remediation profiles were moved to `profiles/Archived/2026 Hardware Validation/2026-08 Final Remediation Completed/`, outside normal nonrecursive discovery. The generic fail-closed `x86_64 APU Full Mixed Stateful Confirmation` profile was retained in normal discovery only while its two 600-second confirmations remained outstanding. After both confirmations validated, its JSON and sidecar were moved into the same archive. Nothing was deleted, and the fail-closed `integrated_all`/`all` contract remains reproducible from the archived profile.

## Historical minimal hardware request — completed

1. Ryzen 7 5700G: run only `x86_64 APU Full Mixed Stateful Confirmation` once, 600 seconds.
2. Ryzen 5 8600G: run only the same profile once, 600 seconds.

Each result must show CPU and native RAM verification, a fused 70%-intent integrated stateful worker, every installed dGPU stateful worker, correct shared/dedicated planning, overlap, and zero mismatches/errors. Estimated workload time is 20 minutes total across the two systems, plus launch/export overhead. No standalone RAM, transfer, stateful, broad 70/90-minute profile, i7, ARM, 285K, or 14900 rerun is justified.

Both requested executions are now complete and independently accepted. No additional hardware evidence is required.

## Final APU full-mixed confirmation addendum

### Scope, baseline, and inventory

The final round contains exactly two root-level executions and four immediately preceding Dry Run captures. Archived, Uploaded, Reparsed, Support_Exports, and Migration_Bundles content is not counted. Both executions used `x86_64 APU Full Mixed Stateful Confirmation`, required every stage to be runnable, enabled Advanced Debug, and contain one required 600-second stage.

| Execution | Actual hardware | Stage / LVS result | Run / stage runtime |
|---|---|---|---|
| `2026-08-14_12-58-08_x86_64 APU Full Mixed Stateful Confirmation` | Ryzen 7 5700G, 8 physical / 16 logical; RTX 5090 `card0` `0000:01:00.0`; integrated RADV Renoir `card1` `0000:07:00.0` | Full CPU RAM and All-GPU Stateful Mixed Confirmation / PASS | 635.64 / 602.441 s |
| `2026-08-14_12-59-50_x86_64 APU Full Mixed Stateful Confirmation` | Ryzen 5 8600G, 6 physical / 12 logical; RTX PRO 6000 `card0` `0000:01:00.0`; RX 550 `card1` `0000:04:00.0`; integrated RADV 760M `card2` `0000:08:00.0`; T1000 8GB `card3` `0000:05:00.0` | Full CPU RAM and All-GPU Stateful Mixed Confirmation / WARN | 648.20 / 602.036 s |

Worker inventory is exact: 5700G has one native CPU worker process containing 16 pinned threads, one native RAM worker containing 16 threads, and two fused Vulkan stateful workers. The 8600G has one native CPU process containing 12 pinned threads, one native RAM process containing 12 threads, and four fused Vulkan stateful workers. All worker exit codes recorded by the manifest are zero. Worker stdout/stderr and all captured filtered kernel/journal logs are empty.

The saved results do not embed a Git SHA, but their profile is the one introduced by, and their execution timestamps follow, baseline `75d7d19a47dcf0a6c26008ed7b34c9f7d1f1293e`. More importantly, their materialized integrated stateful workers directly prove execution of that baseline's policy correction.

### Dry Run and selector accuracy

The `12-58-01` and `12-58-05` diagnostics both reported the 5700G profile runnable 1/1. They resolved `integrated_all` to Renoir and `all` to Renoir plus RTX 5090, classified the 512 MiB DRM report as ambiguous carved-out memory, selected the 11,348,717,568-byte shared Vulkan heap, retained the fused stateful worker, and planned both GPU targets.

The `12-59-40` and `12-59-45` diagnostics both reported the 8600G profile runnable 1/1. They resolved `integrated_all` only to the 760M and `all` to the 760M plus RTX PRO, RX 550, and T1000. The RX 550 was not omitted. They classified the 760M's 512 MiB DRM report as ambiguous, selected the 11,237,212,160-byte shared heap, and planned all four fused stateful workers.

Runtime matches those predictions exactly. There is no `[None]` target, integrated/discrete leakage, required skip, missing worker, or preflight/execution disagreement. The diagnostics' allocation numbers vary slightly from execution because the authoritative launch snapshot uses launch-time MemAvailable; this is expected and explicitly preserved in `system_memory_plan_launch`.

### Ryzen 7 5700G confirmation

- CPU: native tuned `sse2_int`; CPUs 0-15 intended and actually targeted; 16/16 threads created; affinity attempted/applied 16/16 with observed CPU equal to target and no failure. In the 542.441-second trimmed steady window, aggregate utilization median/p10/min is 100/100/100%. Every logical-CPU median is 100%; none is materially underloaded and no CPU exists outside the target set. The helper completed 8,096,016 verify/canary passes, zero errors. CPU clock median 4516.6 MHz, power 84.735 W, temperature 53.88 C.
- RAM: 70% requested 23,080,684,748 bytes; launch assignment 20,120,839,587; allocated/retained 20,120,842,240 (100.000% assigned, 87.176% requested). Sixteen threads completed 3,308 passes: mix64 831, inverted_mix64 830, walking_bit 825, address_xor 822; zero mismatches. Steady memory-used median/min/max is 29.16/29.07/29.40 GiB.
- Renoir: physical target is RADV RENOIR, `card1`, `0000:07:00.0`, Vulkan integrated device, hardware match score 2760 and unambiguous. The fused `vulkan_compute_stateful_memory_v19` worker created its Vulkan device/queue/pipeline and ran `stateful_memory`; a software renderer was enumerated by system Vulkan diagnostics but was not selected. The 512 MiB carved-out report did not cap the worker. Requested 7,944,102,297 bytes; assigned 6,920,481,373 after the unified-pool rebalance; allocated 6,920,484,864 (100.000% assigned, 87.115% requested; 60.980% of the compatible heap). Seven legal buffers span 478,029,824 to 1,073,741,824 bytes, with no allocation failure/backoff. All seven buffers were retained and covered by readback; 948 frames, 316 verification passes, zero compute mismatch/error, 593.319 s. Steady busy median/p10 96.5/93%, clock median 1987 MHz, temperature median/max 39/40 C, power median 84 W.
- RTX 5090: `card0`, `0000:01:00.0`, dedicated and excluded from the system pool. Requested/assigned 23,933,642,342; allocated 23,933,645,824 (100.000%), eight buffers, 6,514 frames, 2,172 readbacks, zero mismatch/error, 595.913 s. Dedicated residency remained 22.38 GiB. Busy is intentionally bursty during full-buffer verification (median 30%, p10 0%, max 91%), while 2827 MHz median clock and 228.9 W median power plus continuous frame/readback progress prove real work.
- Unified plan/guard: MemTotal 32,972,406,784; launch MemAvailable 28,116,111,360; reserve 1,073,741,824; safe pool 27,042,369,536. Allocation ledger is RAM 20,120,839,587 plus shared-consumer commitment 6,921,529,949, exactly the pool. Dedicated RTX VRAM is outside it. The Renoir runtime claim is 6,920,484,864; minimum MemAvailable 1,400,778,752. No warning, emergency, denied growth, guard trigger, or termination; claims were released during clean worker shutdown.
- Concurrency: every worker lifespan exceeds 593.319 s inside the 602.441-second stage. Therefore every worker necessarily covers the complete stage+30 to stage-end-30 interval: 542.441 seconds of simultaneous CPU, RAM, Renoir stateful, and RTX stateful work. During that overlap CPU is 100%, memory is near its sustained 29.16 GiB median, Renoir is 96.5% median busy with full retained allocation, RTX retains 22.38 GiB and produces verified bursts, and all final verification counters are positive with zero failures.

Independent verdict: **VALIDATED**, high confidence. LVS PASS agrees with the underlying behavior. Its report-only RTX utilization recommendation is an advisory telemetry caveat, not a missing workload or verification failure.

### Ryzen 5 8600G confirmation

- CPU: native tuned `avx512_int`; CPUs 0-11 intended/actual; 12/12 threads, affinity attempted/applied 12/12, observed CPU equals target. The 542.036-second trimmed steady window has aggregate median/p10/min 100/100/100%; every logical median is 100%, with no outside CPU or underloaded target. The helper completed 5,768,651 verify/canary passes, zero errors. Clock median 4670.245 MHz, power 87.22 W, temperature 62.12 C.
- RAM: 70% requested 22,846,529,126; assigned 19,215,032,196; allocated/retained 19,215,032,320 (100.000% assigned, 84.105% requested). Twelve threads completed 2,816 passes: mix64 709, inverted_mix64 707, walking_bit 702, address_xor 698; zero mismatches. Steady used-memory median/min/max is 29.27/29.11/29.43 GiB.
- Radeon 760M: physical RADV PHOENIX `card2`, `0000:08:00.0`, integrated, hardware match score 2760 and unambiguous; no software renderer selected. Requested 7,866,048,511; assigned 6,609,678,460; allocated 6,609,682,432 (100.000% assigned, 84.028% requested; 58.820% of the 11,237,212,160-byte selected shared heap). The 512 MiB carved-out report did not cap allocation. Seven buffers span 167,227,392 to 1,073,741,824 bytes, no failure/backoff; all seven covered, 2,214 frames, 738 verifies, zero mismatch/error, 592.086 s. Busy median/p10 95/93%, clock median 2445.5 MHz, temperature median/max 43/44 C.
- RTX PRO 6000: dedicated `card0` `0000:01:00.0`; requested/assigned 71,849,371,238; allocated 71,849,374,720, 20 buffers, 3,467 frames, 1,156 verifies, zero errors, 587.721 s. Steady busy median 62%, clock 1991 MHz, power 222.375 W, temperature median/max 77/80 C, residency 67.02 GiB.
- RX 550: dedicated `card1` `0000:04:00.0`; requested/assigned 751,619,276; allocated 751,623,168, three buffers, 6,967 frames, 2,323 verifies, zero errors, 597.652 s. Busy median/max 100/100%, clock 1183 MHz, temperature median/max 73/81 C, residency 0.71 GiB. This proves the small dGPU remains included.
- T1000 8GB: dedicated `card3` `0000:05:00.0`; requested/assigned 6,012,954,214; allocated 6,012,957,696, six buffers, 5,580 frames, 1,860 verifies, zero errors, 594.288 s. Busy median/p10 84/81%, memory busy 85/83%, clock 1395 MHz, residency 5.62 GiB. Temperature median/max 84/87 C crossed the 85 C warning hint but caused no mismatch, throttle fault, reset, or early exit.
- Unified plan/guard: MemTotal 32,637,898,752; launch MemAvailable 26,899,501,056; reserve 1,073,741,824; pool 25,825,759,232. Allocation ledger is RAM 19,215,032,196 plus shared-consumer commitment 6,610,727,036, exactly the pool. All three dedicated targets remain outside it. The 760M claimed 6,609,682,432 real growth. Minimum MemAvailable was 1,033,822,208, briefly below the 1 GiB warning threshold but well above the 512 MiB emergency threshold. Growth stopped safely after full assigned allocation; no claim was denied, guard did not trigger, termination was not required, and cleanup released claims.
- Concurrency: the shortest GPU lifespan is 587.721 s within the 602.036-second stage, which guarantees all CPU/RAM/four-GPU workers cover the entire 30-second-trimmed 542.036-second interval. During overlap CPU remains 100%, memory remains at 29.27 GiB median, 760M remains 95% median busy with 6.61 GB retained, and every dGPU retains its assigned allocation and produces verification progress.

Independent verdict: **VALIDATED WITH EXPLAINED WARNING**, high confidence. LVS WARN accurately represents the non-emergency memory warning and T1000 87 C thermal warning. Neither invalidates workload integrity or concurrency.

### Evidence consistency and final reconciliation

For both runs, `run_manifest.json` stage worker payloads exactly equal `parsed_results_extended.json`; legacy custom output contains every stable target; summaries report the same worker counts, allocation ratios, verification counters, warnings, and PASS/WARN outcomes. All GPU workers report hardware verification, unambiguous device matching, 100% assigned allocation, complete buffer coverage, positive frames/readbacks, zero mismatches, and zero observed process exit codes. There is no device loss, reset, timeout, OOM, kernel fault, or worker exception.

Stable telemetry mapping is correct despite Vulkan runtime-index ordering: source-map indices bind by card/slot to RTX/Renoir on 5700G and RTX PRO/RX 550/760M/T1000 on 8600G. Worker target slot/card, system inventory, telemetry source, parsed output, and summary all agree. No duplication, drift, missing source, or cross-device temperature/clock association was found.

The saved `executed_plan.commands` list is the pre-launch planning snapshot and contains byte arguments from an earlier MemAvailable sample. `system_memory_plan_launch`, final materialized worker specs, runtime guard, and worker results are the authoritative launch/execution evidence and agree. This field distinction did not affect execution, parsing, evaluation, or acceptance.

The two new rows supersede, but do not erase, the historical partial rows. The prior missing-APU-stateful defect is conclusively closed on both Renoir and Phoenix. The historical matrix now contains 20 `VALIDATED`, 7 `VALIDATED WITH EXPLAINED WARNING`, 2 superseded `PARTIALLY EXECUTED, NOT VALIDATED`, and 1 external-known-hardware row. Current unresolved count is zero.

The completed `x86_64 APU Full Mixed Stateful Confirmation` profile is archived under `profiles/Archived/2026 Hardware Validation/2026-08 Final Remediation Completed/`, outside normal nonrecursive discovery, with both JSON and sidecar preserved for reproducibility.

## Software validation

All validation below was non-hardware and launched no sustained workload.

- Focused regressions passed for Python RAM continuous verification, stress-ng final metrics and RAM evaluation, AMD APU selectors, small-dGPU classification, compatible shared-heap selection, allocation-count splitting, stable GPU telemetry identity, Vulkan compute/transfer/stateful planning and evidence, runtime-memory guard behavior, combined orchestration, multi-GPU targeting, Intel P/E and SMT fixtures, CPU targeting/ISA, profile parsing/validation, fail-closed required targets, and legacy result compatibility.
- The full smoke suite passed: **237/237**.
- Whole-tree `compileall`, explicit Vulkan worker `py_compile`, recursive Modules compilation, static internal import-cycle analysis, cold-import manifest, and optional-Textual import-boundary checks passed.
- All active and archived profile JSON parsed successfully. `git diff --check` passed.
- Native helper source/build-contract tests passed. The checked-in ARM64 CPU and memory helper binaries are newer than their sources; both are valid AArch64 ELF executables, the CPU helper resolves `auto` to `neon`, and the memory helper answers its non-workload usage probe.
- A fresh explicit native-helper rebuild could not be completed in this Codex execution environment: no sandbox compiler is installed, and the only exposed host GCC 15 executable terminates with `SIGBUS` before compiling either unchanged C source, both in and outside the sandbox. This is an environment/tool execution limitation, not a compiler diagnostic or source failure; it does not create another hardware rerun requirement. The failed attempts wrote only under `/tmp` and did not change repository build artifacts.

## Evidence preservation

No file under `results/` was altered, renamed, deleted, or reparsed in place. No sustained hardware workload was launched by this audit.
