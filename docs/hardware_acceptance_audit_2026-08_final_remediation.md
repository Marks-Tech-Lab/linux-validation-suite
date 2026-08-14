# LVS final-remediation hardware acceptance audit (2026-08-14)

Baseline audited: `38164844d797b29d05c370192e742f78967d3d5b` (`Fix hardware acceptance gaps and minimize reruns`). Raw PASS/WARN/FAIL values were treated as observations. This report and the companion `hardware_acceptance_matrix_2026-08_final_remediation.csv` are the final forensic record for the root-level campaign present in `results/` on 2026-08-14.

## Decision

The broad hardware campaign is complete, but it cannot yet be closed completely. Twenty-five of 27 new stages are independently accepted. Two AMD-APU full mixed stages are partial because LVS omitted integrated shared-stateful pressure while still reporting PASS/WARN. The defect is fixed in software. Only one 600-second stage on the 5700G and the same 600-second stage on the 8600G are required; no other hardware path should be repeated.

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

The five completed one-off remediation profiles were moved to `profiles/Archived/2026 Hardware Validation/2026-08 Final Remediation Completed/`, outside normal nonrecursive discovery. They were not deleted. A single generic fail-closed `x86_64 APU Full Mixed Stateful Confirmation` profile now contains the only remaining 600-second stage. It requires `integrated_all` for compute and `all` for stateful memory, ensuring an APU without a resolvable integrated target is not considered runnable.

## Minimal additional hardware evidence

1. Ryzen 7 5700G: run only `x86_64 APU Full Mixed Stateful Confirmation` once, 600 seconds.
2. Ryzen 5 8600G: run only the same profile once, 600 seconds.

Each result must show CPU and native RAM verification, a fused 70%-intent integrated stateful worker, every installed dGPU stateful worker, correct shared/dedicated planning, overlap, and zero mismatches/errors. Estimated workload time is 20 minutes total across the two systems, plus launch/export overhead. No standalone RAM, transfer, stateful, broad 70/90-minute profile, i7, ARM, 285K, or 14900 rerun is justified.

After those two rows pass independently, the hardware acceptance campaign can be closed without re-auditing this dataset.

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
