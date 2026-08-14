# Power Auto and Instruction-Intent Hardware Acceptance Audit — 2026-08

## Decision

**HARDWARE ACCEPTANCE COMPLETE — NO FURTHER HARDWARE RUNS REQUIRED**

The root of `results/` contains **five**, not four, complete independent executions of `CPU Power Auto and Instruction Intent Confirmation`. All five were audited. Four x86_64 systems exercised measured package-power selection through three distinct telemetry paths/topologies; the Qualcomm Oryon AArch64 system exercised the intended no-power fallback. Every sustained stage saturated its complete target CPU set, produced positive verification/progress evidence, and resolved its instruction intent correctly. There were no workload verification failures, native-helper crashes, unexpected skips, or LVS-attributable stability findings.

Two limitations do not invalidate acceptance:

1. The 1-second warm-up plus 3-second measurement produced only 4–6 usable samples per candidate. Selection was arithmetically correct on every measured system, but the i7-10750H and Ryzen 7 5700G winner margins were only about 2 W. Their winners remained valid, verified, fully saturating workloads; the 5700G sustained power corroborated the probe strongly, while the thermally limited 10750H sustained state cannot prove that its cold-probe ranking is universally repeatable. A future confidence/repeat policy would improve ranking robustness but is not required to accept the implemented selector.
2. The 285K captured a successful USB UAS host reset during the Power stage. It was preserved in Advanced Debug kernel evidence and had no CPU-worker effect, but it was not promoted into the LVS summary. This is an external USB-storage transient and a reporting-granularity limitation, not a CPU acceptance failure.

## Scope and provenance

Requested baseline HEAD was `be63008ef908f1269e6043176fa231849dced1c5` (`Close 2026-08 hardware acceptance campaign`) with the Power Auto/instruction-intent implementation staged but uncommitted.

The result manifests identify LVS `0.2.0-alpha` but do **not** embed a Git commit plus dirty-tree fingerprint. Exact byte-for-byte source provenance therefore cannot be cryptographically established. Nevertheless, all five saved profile snapshots are semantically equal to the current staged confirmation profile after normal profile loading/default expansion, and the results contain the new four-stage layout and new additive evidence (`instruction_intent`, resolved kernel, tier-collapse, Power candidate results, and `selection_mechanism`). Timestamps and materialization shape strongly establish that these runs exercised the staged implementation; attribution to an exact dirty-tree state remains the explicit provenance limitation.

## Execution inventory

| Run directory | Start (saved local offset) | System | Architecture/topology | OS/kernel | CPU telemetry | Reported result |
|---|---|---|---|---|---|---|
| `2026-08-14_16-06-25_CPU Power Auto and Instruction Intent Confirmation` | 2026-08-14 16:06:25 -04:00 | Intel Core i7-10750H, MSI GP65 Leopard 10SDK | x86_64; 6C/12T; homogeneous Intel; SMT pairs `(0,6)`…`(5,11)`; no P/E split | Bazzite; 7.1.5-ogc5.1.fc44.x86_64 | package watts: sudo Intel RAPL `package-0/energy_uj`; temperature: Package id 0; clocks: cpufreq | PASS, 4/4 stages |
| `2026-08-14_16-07-32_CPU Power Auto and Instruction Intent Confirmation` | 2026-08-14 16:07:32 -04:00 | Intel Core Ultra 9 285K, Gigabyte B860M EAGLE PLUS WIFI6E | x86_64; 24C/24T; 8 P + 16 E; no SMT | Bazzite; 7.1.5-ogc5.1.fc44.x86_64 | package watts: sudo Intel RAPL `package-0/energy_uj`; temperature: Package id 0; clocks: cpufreq | PASS, 4/4 stages |
| `2026-08-14_16-08-34_CPU Power Auto and Instruction Intent Confirmation` | 2026-08-14 16:08:34 -04:00 | AMD Ryzen 5 8600G | x86_64; 6C/12T; SMT sibling pairs; non-Intel topology correctly unaffected by P/E policy | Bazzite; 7.1.5-ogc5.1.fc44.x86_64 | package watts: Linux RAPL `package-0/energy_uj`; temperature: Tctl; clocks: cpufreq | PASS, 4/4 stages |
| `2026-08-14_16-08-49_CPU Power Auto and Instruction Intent Confirmation` | 2026-08-14 16:08:49 -04:00 | Qualcomm Oryon, HP OmniBook X | AArch64; 8C/8T; clusters 0–3 and 4–7; no SMT/P/E classification | Ubuntu 26.04 LTS; 7.0.0-29-generic | package watts: unavailable (`not found`, not permission failure); temperature: max of 20 CPU thermal zones; clocks: unavailable | PASS, 4/4 stages |
| `2026-08-14_16-09-51_CPU Power Auto and Instruction Intent Confirmation` | 2026-08-14 16:09:51 -04:00 | AMD Ryzen 7 5700G | x86_64; 8C/16T; SMT sibling pairs; non-Intel topology correctly unaffected by P/E policy | Bazzite; 7.1.5-ogc5.1.fc44.x86_64 | package watts: energy hwmon `Esocket0`; temperature: Tctl; clocks: cpufreq | PASS, 4/4 stages |

Elapsed run times were 1185.34 s, 1181.21 s, 1198.87 s, 1141.50 s, and 1183.83 s respectively. Advanced Debug was enabled in every run.

This inventory discrepancy is material: the supplied evidence contains one AArch64 and **four** x86_64 executions. The extra 5700G execution is complete and is treated as additional independent acceptance evidence.

## Readiness, Dry Run, and preflight

Each execution has two immediately preceding diagnostics directories containing `dry_run_diagnostics.json`, `dry_run_summary.txt`, and `profile_used.json`:

- 10750H: `16-06-18` and `16-06-23`
- 285K: `16-07-28` and `16-07-31`
- 8600G: `16-08-25` and `16-08-33`
- Oryon: `16-08-46` and `16-08-49 Diagnostics`
- 5700G: `16-09-48` and `16-09-50`

All report runnable, 4/4 stages materializable, and zero errors. The run manifests also preserve `preflight_validation`. Preflight architecture, target CPU set, Power pending/fallback capability, and intent resolution agree with runtime materialization. No required worker disappeared between Dry Run and execution.

## Independent per-stage matrix

Telemetry statistics use each stage's monotonic start/end, trim 15 seconds from both ends, and exclude probe/startup/teardown transitions. `min` is the minimum meaningful aggregate utilization in that trimmed interval.

| System | Stage | Actual workload / resolution | Actual duration | Target / affinity | Aggregate CPU % median / p10 / min | Verification/progress | Independent verdict |
|---|---|---|---:|---|---|---|---|
| i7-10750H | Power Auto | stress-ng matrixprod, measured `power_probe` winner | 601.35 s | 0–11; `--taskset`; all logical CPUs observed busy | 100 / 100 / 99.88 | 5,435,799 bogo; 12 dispatched/passed; 0 failed; `--verify`; exit 0 | VALIDATED WITH EXPLAINED WARNING — valid high-power workload; small probe margin and sustained thermal limiting |
| i7-10750H | Baseline Vector | native SSE/SSE2 (`sse2`) | 180.69 s | 12/12 native affinity successful | 100 / 100 / 100 | 1,525,235 canary/verification passes; 0 errors | VALIDATED |
| i7-10750H | High-Throughput Vector | native AVX2/FMA (`avx2_fma`) | 180.99 s | 12/12 successful | 100 / 100 / 100 | 1,786,638 passes; 0 errors | VALIDATED |
| i7-10750H | Highest Verified Vector | native `avx2_fma` (AVX-512 absent from common set) | 180.39 s | 12/12 successful | 100 / 100 / 100 | 1,782,581 passes; 0 errors | VALIDATED |
| Core Ultra 9 285K | Power Auto | Python PBKDF2, measured `power_probe` winner | ~600.14 s | 0–23; 24/24 worker affinity successful | 100 / 100 / 100 | 128,726 duplicate-PBKDF2/`compare_digest` passes; 0 errors | VALIDATED WITH EXPLAINED WARNING — unrelated successful USB UAS reset preserved in kernel log |
| Core Ultra 9 285K | Baseline Vector | native SSE/SSE2 (`sse2`) | 180.27 s | 24/24 successful | 100 / 100 / 100 | 5,800,263 passes; 0 errors | VALIDATED |
| Core Ultra 9 285K | High-Throughput Vector | native AVX2/FMA (`avx2_fma`) | 180.21 s | 24/24 successful | 100 / 100 / 100 | 6,698,436 passes; 0 errors | VALIDATED |
| Core Ultra 9 285K | Highest Verified Vector | native `avx2_fma`, correct common P/E-safe maximum | 180.16 s | 24/24 successful | 100 / 100 / 100 | 6,665,389 passes; 0 errors | VALIDATED |
| Ryzen 5 8600G | Power Auto | Python PBKDF2, measured `power_probe` winner | ~600.14 s | 0–11; 12/12 worker affinity successful | 100 / 100 / 100 | 32,993 duplicate-PBKDF2/`compare_digest` passes; 0 errors | VALIDATED |
| Ryzen 5 8600G | Baseline Vector | native SSE/SSE2 (`sse2`) | 180.22 s | 12/12 successful | 100 / 100 / 100 | 2,495,495 passes; 0 errors | VALIDATED |
| Ryzen 5 8600G | High-Throughput Vector | native AVX2/FMA (`avx2_fma`) | 180.38 s | 12/12 successful | 100 / 100 / 100 | 2,946,474 passes; 0 errors | VALIDATED |
| Ryzen 5 8600G | Highest Verified Vector | native AVX-512/FMA (`avx512_fma`) | 180.61 s | 12/12 successful | 100 / 100 / 100 | 1,719,869 passes; 0 errors | VALIDATED |
| Qualcomm Oryon | Power Auto | stress-ng matrixprod, `thermal_validated_fallback` | 600.10 s | 0–7; `--taskset`; all logical CPUs observed busy | 100 / 100 / 99.63 | 438,835 bogo; 8 dispatched/passed; 0 failed; `--verify`; exit 0 | VALIDATED |
| Qualcomm Oryon | Baseline Vector | ARM64 native NEON (`neon`) | 180.23 s | 8/8 successful and observed on requested CPUs | 100 / 100 / 100 | 963,550 passes; 0 errors | VALIDATED |
| Qualcomm Oryon | High-Throughput Vector | ARM64 native NEON (`neon`), explicit tier collapse | 180.20 s | 8/8 successful | 100 / 100 / 100 | 963,988 passes; 0 errors | VALIDATED |
| Qualcomm Oryon | Highest Verified Vector | ARM64 native NEON (`neon`) | 180.22 s | 8/8 successful | 100 / 100 / 100 | 963,603 passes; 0 errors | VALIDATED |
| Ryzen 7 5700G | Power Auto | stress-ng matrixprod, measured `power_probe` winner | 600.63 s | 0–15; `--taskset`; all logical CPUs observed busy | 100 / 100 / 99.85 | 6,722,981 bogo; 16 dispatched/passed; 0 failed; `--verify`; exit 0 | VALIDATED WITH EXPLAINED WARNING — small probe margin, sustained result corroborates winner |
| Ryzen 7 5700G | Baseline Vector | native SSE/SSE2 (`sse2`) | 180.02 s | 16/16 successful | 100 / 100 / 100 | 3,339,931 passes; 0 errors | VALIDATED |
| Ryzen 7 5700G | High-Throughput Vector | native AVX2/FMA (`avx2_fma`) | 180.36 s | 16/16 successful | 100 / 100 / 100 | 3,614,539 passes; 0 errors | VALIDATED |
| Ryzen 7 5700G | Highest Verified Vector | native `avx2_fma` | 180.19 s | 16/16 successful | 100 / 100 / 100 | 3,611,025 passes; 0 errors | VALIDATED |

All per-logical-CPU medians were 100%. The lowest targeted logical-CPU median was therefore 100% in every stage. The target sets equal the online and process-allowed sets, so no outside-target workload or target oversubscription exists. For stress-ng, affinity is durably recorded as requested through `--taskset` but not independently observed per worker; the per-logical telemetry provides independent corroboration that every requested CPU was saturated.

## Power Auto candidate audit

All measured candidates recorded clean startup, expected worker count, affinity state, positive progress, and zero verification failures. Consequently all were valid competitors. The selected candidate is the independently computed maximum of the valid mean-watt values in every x86 run.

### i7-10750H — sudo Intel RAPL

| Rank | Candidate | Mean W | Max W | Samples | Valid |
|---:|---|---:|---:|---:|---|
| 1 | stress-ng matrixprod | 81.05 | 84.64 | 4 | yes |
| 2 | Python PBKDF2 | 79.04 | 80.51 | 4 | yes |
| 3 | native avx2 | 68.18 | — | 4–6 | yes |
| 4 | native sse2_int | 62.48 | — | 4–6 | yes |
| 5 | native avx | 61.47 | — | 4–6 | yes |
| 6 | native avx2_fma | 60.79 | — | 4–6 | yes |
| 7 | native avx_fma | 59.30 | — | 4–6 | yes |
| 8 | native sse2 | 55.23 | — | 4–6 | yes |
| 9 | native scalar | 51.68 | — | 4–6 | yes |

Winner margin: **2.01 W (2.54%)**. Sustained stress-ng: mean/median/max package power 62.06/61.97/67.89 W; mean/median/max temperature 94.45/94/96 °C; median clock 3.8 GHz. The much lower sustained power with 100% utilization and high temperature is consistent with thermal/power limiting after the cold probe. The selection is valid and credible as high pressure, but the short-window rank over Python is not strongly separated.

### Core Ultra 9 285K — sudo Intel RAPL

| Rank | Candidate | Mean W | Max W | Samples | Valid |
|---:|---|---:|---:|---:|---|
| 1 | Python PBKDF2 | 229.01 | 238.10 | 5 | yes |
| 2 | stress-ng matrixprod | 197.59 | 218.54 | 6 | yes |
| 3 | native avx_fma | 133.52 | — | 4–6 | yes |
| 4 | native avx2_fma | 132.24 | — | 4–6 | yes |
| 5 | native avx2 | 129.77 | — | 4–6 | yes |
| 6 | native sse2_int | 127.41 | — | 4–6 | yes |
| 7 | native avx | 112.07 | — | 4–6 | yes |
| 8 | native sse2 | 103.51 | — | 4–6 | yes |
| 9 | native scalar | 103.04 | — | 4–6 | yes |

Winner margin: **31.42 W (15.90%)**. Sustained Python: mean/median/max 213.68/210.72/234.97 W; mean/median/max temperature 76.54/76/81 °C; median clock 4.735 GHz. This is a decisive probe ranking and the sustained result corroborates it.

### Ryzen 5 8600G — Linux package RAPL

| Rank | Candidate | Mean W | Max W | Samples | Valid |
|---:|---|---:|---:|---:|---|
| 1 | Python PBKDF2 | 79.08 | 80.37 | 4 | yes |
| 2 | native avx512_int | 76.10 | 76.85 | 4 | yes |
| 3 | native avx_fma | 71.56 | — | 4–6 | yes |
| 4 | native avx2_fma | 70.91 | — | 4–6 | yes |
| 5 | stress-ng matrixprod | 68.73 | — | 4–6 | yes |
| 6 | native avx2 | 68.03 | — | 4–6 | yes |
| 7 | native sse2_int | 66.95 | — | 4–6 | yes |
| 8 | native avx512_fma | 65.97 | — | 4–6 | yes |
| 9 | native sse2 | 59.95 | — | 4–6 | yes |
| 10 | native avx | 59.44 | — | 4–6 | yes |
| 11 | native scalar | 59.23 | — | 4–6 | yes |

Winner margin: **2.98 W (3.92%)**. Sustained Python: mean/median/max 79.77/79.83/81.91 W; mean/median/max temperature 82.48/82.5/83.12 °C; median clock 4.749 GHz. Sustained measurements strongly corroborate the selected winner.

### Ryzen 7 5700G — energy hwmon Esocket0

| Rank | Candidate | Mean W | Max W | Samples | Valid |
|---:|---|---:|---:|---:|---|
| 1 | stress-ng matrixprod | 87.83 | 87.94 | 5 | yes |
| 2 | Python PBKDF2 | 85.66 | 87.91 | 4 | yes |
| 3 | native sse2_int | 74.40 | — | 4–6 | yes |
| 4 | native avx_fma | 73.88 | — | 4–6 | yes |
| 5 | native avx2_fma | 73.03 | — | 4–6 | yes |
| 6 | native avx2 | 72.60 | — | 4–6 | yes |
| 7 | native sse2 | 61.64 | — | 4–6 | yes |
| 8 | native scalar | 61.36 | — | 4–6 | yes |
| 9 | native avx | 58.83 | — | 4–6 | yes |

Winner margin: **2.17 W (2.53%)**. Sustained stress-ng: mean/median/max 87.83/87.83/88.00 W; mean/median/max temperature 58.72/58.75/59.75 °C; median clock 4.464 GHz. The sustained stage nearly exactly reproduces the probe mean and strongly corroborates the winner despite the small margin.

### Qualcomm Oryon — no package-power source

The telemetry capability record says CPU package power `not found`, with no permission error; raw stage telemetry contains no `cpu_power_w` values. LVS recorded `selection_mechanism="thermal_validated_fallback"`, `fallback_reason="cpu_package_power_telemetry_unavailable"`, zero probe duration, no fabricated candidate-watt statistics, and the viable order stress-ng matrixprod → Python PBKDF2 → native Auto/NEON → native scalar. All were available and the first preference, stress-ng matrixprod, was selected. It ran with `--verify --metrics-brief --taskset 0,…,7`, completed 438,835 bogo operations, reported 8/8 passed stressors, and had no verification failures.

No x86 machine exercised `architecture_validated_fallback`; all four had usable package-power telemetry. The terminology and behavior are therefore software-validated but not independently exercised by this hardware set. Another run is not warranted solely to manufacture an absent-power x86 environment.

## Probe robustness assessment

The implementation behaved dynamically rather than as a hardcoded selector: stress-ng won on two systems and Python won on two; native kernels participated and one native AVX-512 integer candidate was runner-up on the 8600G. Three distinct package-power provider paths were used successfully.

The selection arithmetic and candidate validity gates are correct in the saved evidence. No real candidate failed, so hardware did not directly challenge the “invalid candidate cannot win” branch; focused synthetic regression remains the authoritative direct proof for that branch.

The 3-second measured interval is adequate for the large 285K margin and is retrospectively corroborated on the 8600G and 5700G. It is not sufficient to claim high statistical confidence for every close ranking, especially the thermally evolving 10750H. Recommended future hardening is a minimum stable-sample/repeat or confidence threshold for close candidates—not a broad hardware rerun and not a blocker to accepting that the selector chose a valid, measured, high-load workload on all four systems.

## Instruction-intent audit

- **AArch64:** common native flavors were `[neon, scalar]`. All three stages launched `build/cpu_stress_helper_arm64` with `--kernel-flavor neon`. Baseline resolved to NEON; high-throughput resolved to NEON with `tier_collapsed=true` and an explicit explanation that the current validated ARM baseline and high-throughput tiers coincide; highest verified resolved to NEON. There was no x86 ISA leakage, scalar substitution, or backend substitution.
- **10750H:** baseline `sse2`; high-throughput and highest verified `avx2_fma`. AVX-512 was absent from the complete target capability intersection.
- **285K hybrid:** baseline `sse2`; high-throughput and highest verified `avx2_fma`. This is the correct common-safe maximum across all targeted P and E logical CPUs; LVS did not use a P-core-only capability.
- **8600G:** baseline `sse2`; high-throughput `avx2_fma`; highest verified `avx512_fma`, consistent with the common capability set across all 12 target threads.
- **5700G:** baseline `sse2`; high-throughput and highest verified `avx2_fma`.

Every intent stage used the native backend, applied affinity to every worker/thread, sustained 100% aggregate and per-logical median utilization, and produced positive native canary/verification counts with zero errors. Worker stdout files are empty and native worker-result records do not repeat the executed process command/exit metadata; the exact helper command is preserved in the materialized launch plan, while worker results independently preserve kernel, per-thread observed CPU, affinity, counters, status, and errors. This is an evidence-granularity limitation, not a contradiction.

The clean real Oryon execution proves the repository's ARM64 native helper path and NEON kernel are healthy on real hardware. Prior compiler/helper bus errors in a Codex sandbox are not relevant to runtime hardware acceptance.

## Evidence consistency and reporting

Cross-checks among saved profiles, diagnostics, manifests, stage events, materialized plans, worker results/logs, raw telemetry, telemetry source maps, extended/custom parsed results, summaries, and Advanced Debug found no target, backend, ISA, mechanism, verification, or verdict contradiction.

- Requested intents agree with resolved ISA/kernel and actual native worker results.
- The selected Power backend agrees with the sustained worker and its progress evidence.
- `selected_isa` is populated for native candidate evidence and absent where a non-native selected backend has no ISA contract.
- No probe candidate evidence leaked into a later sustained stage.
- Legacy `parsed_results_custom.json` remained coherent with additive extended evidence.
- The summary's legacy `Test: Unknown=…` label is cosmetic and does not alter stage/results identity.

User-facing PASS is independently accurate for all stages. The three `VALIDATED WITH EXPLAINED WARNING` classifications above add forensic context rather than overturning PASS. Detailed selection/intent evidence is mainly in parsed/debug artifacts rather than prose summaries; this is usable but could be made more visible in future reporting.

## Stability and thermal audit

- **10750H:** no MCE, EDAC, AER, OOM, kernel fault, or worker crash. Power stage reached 96 °C and sustained package power fell from cold-probe levels while utilization stayed at 100%; this is documented thermal/power limiting, not failed validation.
- **285K:** two successful `uas_eh_host_reset_handler` sequences for a USB SuperSpeed device at 16:09:43 during Power Auto. No CPU-worker disruption and no CPU/hardware-error signature. No MCE, EDAC, AER, OOM, or thermal failure.
- **8600G:** five Wi-Fi messages reporting invalid AP WMM parameters; unrelated network/AP warnings. No workload, CPU, memory, kernel, or hardware stability failure.
- **Oryon:** no relevant filtered kernel/journal events; no power or clock source was invented.
- **5700G:** no relevant filtered kernel/journal events.

The known 14900 motherboard-slot AER exemption is not applicable: the 14900 system is not in this result set and no PCIe AER finding required classification.

## Cross-system comparison

| System | Power available/source | Branch | Selected | Winner / runner-up | Margin | Sustained util median | Baseline / high / highest | Tier collapse | Verification failures | Independent result |
|---|---|---|---|---|---:|---:|---|---|---:|---|
| i7-10750H | yes / sudo Intel RAPL | power_probe | stress-ng matrixprod | 81.05 / 79.04 W | 2.01 W | 100% | sse2 / avx2_fma / avx2_fma | no | 0 | VALIDATED WITH EXPLAINED WARNING |
| Core Ultra 9 285K | yes / sudo Intel RAPL | power_probe | Python PBKDF2 | 229.01 / 197.59 W | 31.42 W | 100% | sse2 / avx2_fma / avx2_fma | no | 0 | VALIDATED WITH EXPLAINED WARNING |
| Ryzen 5 8600G | yes / Linux package RAPL | power_probe | Python PBKDF2 | 79.08 / 76.10 W | 2.98 W | 100% | sse2 / avx2_fma / avx512_fma | no | 0 | VALIDATED |
| Qualcomm Oryon | no / not found | thermal_validated_fallback | stress-ng matrixprod | not measured | n/a | 100% | neon / neon / neon | yes, high tier | 0 | VALIDATED |
| Ryzen 7 5700G | yes / energy hwmon Esocket0 | power_probe | stress-ng matrixprod | 87.83 / 85.66 W | 2.17 W | 100% | sse2 / avx2_fma / avx2_fma | no | 0 | VALIDATED WITH EXPLAINED WARNING |

## Requirements checklist

| Requirement | Status | Basis / limitation |
|---|---|---|
| Measured cross-backend Power Auto works on real hardware | PROVEN | Four x86 systems; stress-ng and Python both won on different hardware |
| Measured winner independently correct | PROVEN | Recalculated maximum valid mean matches LVS 4/4 |
| Invalid candidates cannot win | PROVEN WITH EXPLAINED LIMITATION | Validity gating is present and software-regressed; every real candidate happened to be valid |
| Package-power source trustworthy | PROVEN | Intel RAPL, Linux AMD package RAPL, and AMD energy-hwmon package sources; credible stable units/ranges |
| Selected winner sustains meaningful CPU load | PROVEN | ~600 s, all target CPUs at 100% median, continued verification |
| No-power fallback works | PROVEN | Real Oryon with genuinely absent package watts |
| ARM fallback truthful | PROVEN | Thermal fallback and reason explicit; no invented watts |
| x86 fallback terminology truthful | PROVEN WITH EXPLAINED LIMITATION | Not hardware-exercised because every x86 system exposed watts; software regression is authoritative |
| `baseline_vector` resolves correctly | PROVEN | NEON on ARM; SSE2-family on all x86 |
| `high_throughput_vector` resolves correctly | PROVEN | NEON on ARM; AVX2/FMA on x86 |
| `highest_verified_vector` resolves correctly | PROVEN | NEON, AVX2/FMA, or AVX-512/FMA according to common target capability |
| ARM tier collapse explicit | PROVEN | Saved requested/resolved evidence and reason |
| x86 highest-common-safe behavior | PROVEN | Hybrid 285K and homogeneous/SMT AMD/Intel paths covered |
| Explicit ISA behavior not broken | PROVEN WITH EXPLAINED LIMITATION | Confirmation profile uses intents; explicit-ISA path was unchanged and remains covered by prior acceptance/software regression |
| Native helper executes resolved ISA | PROVEN | Actual native worker kernel, counters, affinity, and real ARM64 helper path |
| Targeting/affinity/worker count correct | PROVEN | Native per-worker observation; stress-ng taskset plus per-CPU telemetry; Python per-worker affinity |
| CPU utilization remains strong | PROVEN | Every aggregate and per-logical median 100% |
| Verification remains meaningful | PROVEN | Positive native canaries, PBKDF2 comparisons, and stress-ng verified bogo; zero failures |
| Reporting/logging trustworthy | PROVEN WITH EXPLAINED LIMITATION | Core facts consistent; USB reset not promoted and detailed selection mainly lives in debug/parsed evidence |
| No architecture leakage | PROVEN | ARM helper/NEON only on Oryon; common x86 capability policies correct |
| No LVS-attributable hardware instability | PROVEN | No workload errors/faults; external USB/Wi-Fi events explained |
| Converted PL/QA/Quick architecture behavior | PROVEN WITH EXPLAINED LIMITATION | Hardware proves the shared resolver/materializer; converted profile JSON was software-validated rather than rerunning long operator profiles |

Current unresolved acceptance count: **0**. No additional hardware run exercises a materially necessary unproven current path. Additional runs would be redundant.

## Disposition and repository closeout

### Current accepted

- AArch64 Power Auto no-watts fallback.
- x86_64 measured cross-backend selection across Intel/AMD, homogeneous/hybrid, SMT/non-SMT, and three package-power provider paths.
- All three instruction intents on ARM64 and multiple x86 ISA ceilings.
- Real ARM64 native-helper/NEON execution, full targeting, saturation, and verification.
- Additive evidence and legacy result compatibility in real results.

### Historical / explained

- Earlier hardware campaigns remain authoritative and are not reopened.
- The 10750H thermal-limited sustained state and 285K USB reset are recorded above without misclassifying them as LVS failures.
- The results cannot prove an exact dirty-tree Git fingerprint because LVS does not embed one.

### Future optional

- Improve close-margin probe confidence/repeat policy.
- Make detailed Power/intent selections more prominent in prose summaries and optionally promote relevant captured kernel transients.
- Add AArch64 OpenCL multiarch loader candidate paths before the first real ARM GPU OpenCL validation; no worker duplication is needed.
- SVE/SVE2/SME and future platform-specific CPU telemetry sources if later implemented.
- Physically confirm the TUI Results-view Google Drive upload on a future host with the complete Google Drive dependency/integration setup.

### Current unresolved

None.

The completed `CPU Power Auto and Instruction Intent Confirmation.json` and its `_info.txt` sidecar are archived under:

`profiles/Archived/2026 Hardware Validation/06 Power Auto and Instruction Intent Confirmation/`

Final profile discovery/validation and the 240-test smoke suite pass after archival. TUI Results-view `G Upload` is **PROVEN BY SOFTWARE REGRESSION, PHYSICAL INTEGRATION UNVERIFIED**: the implementation resolves `selected_result.path`, retains the shared `PostRunManager`/uploader behavior, and refreshes Results inventory after a move, with focused TUI, CLI, post-run, selected-path, and refresh regression coverage. It was not physically exercised end-to-end on this host because the Google Drive dependency/integration setup is incomplete. Its accepted final status is: **SOFTWARE/REGRESSION VALIDATED — PHYSICAL END-TO-END TUI GOOGLE DRIVE UPLOAD UNVERIFIED ON CURRENT HOST DUE TO INCOMPLETE GOOGLE DRIVE DEPENDENCY/INTEGRATION SETUP.** This is neither a failure nor a release blocker, and no physical-success claim is made.

## Evidence roots

For each run, authoritative evidence includes `run_manifest.json`, `profile_used.json`, `run_metadata.json`, `system_info.json`, `raw_telemetry.csv`, `telemetry_source_map.json`, `parsed_results_extended.json`, `parsed_results_custom.json`, `run_summary.txt`, `worker_results/`, `worker_logs/`, `advanced_debug/`, and the immediately preceding diagnostics directories listed above. Raw evidence was inspected read-only and was not reparsed or modified.
