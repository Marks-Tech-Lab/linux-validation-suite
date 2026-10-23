# Linux Validation Suite: Dynamic Stress and Diagnostics Roadmap

**Revised planning draft | 2026-10-23 | Not yet applied to the LVS repository | Incorporates lab experience with OCCT Adaptive Switch**

## Priority and boundaries

This is a staged proposal for later development, not permission to change the current workers or tests. Prioritize finishing current TUI/CLI usability/parity, corrected GPU-path acceptance on Vulkan, ARM64 vector-selection acceptance, and already-adopted major x86_64/AArch64 ISA work. Only then start the proposed transient-stress features. Put those features **ahead of substantial *new* storage-stress and network-test expansion**; LVS already has a Storage Health and Storage Benchmark baseline. Retain planned release readiness and correctness work. Extensive HTML output refinement belongs later, after the new workloads and their evidence contracts stabilize.

Roadmap governance: distinguish **adopted future priority** from **implementation commitment**. For each major feature, track `planned/design -> implementation -> software-validated -> physically accepted`, with separate evidence or acceptance notes. Maintain a short current-priority queue and deferred queue; do not mark capabilities complete merely because source exists or smoke tests pass. Make the roadmap actionable and checkable without rewriting historical entries or imposing new format on every old milestone.

## Milestone 1 - GPU high-power and dynamic/transient hammer (highest priority after current work)

**Practical motivation:** OCCT's modern 3D Adaptive Switch has underperformed in the user's professional testing: it often does not reach wall-power levels that characterize the troublesome cases and has not reliably reproduced intermittent gaming shutdowns. OCCT's variable-load approach may be useful for voltage/frequency sensitivity, but LVS **must not use it as the performance bar**. Build an independently verifiable high-power workload *first*, then transition into and out of it. No stress test can promise detection of every OC/UV, GPU, or PSU fault.

### 1A. Calibrated high-power GPU workload (foundation)

- Offer complementary GPU workloads using supported, authoritatively bound backends: graphics/render, compute/shader, and memory/bandwidth where verification and hardware capability permit. The strongest load may differ by vendor/architecture; do not presume Vulkan, OpenCL, or EGL universally wins.
- Perform a **bounded, safe device-local workload calibration** to compare these candidates for achieved load. Use available GPU board power, effective clocks, utilization/busy, thermal/power-cap reasons, and optionally operator-provided external wall wattage. Explicitly label unobserved measurements.
- Retain a **fixed, repeatable highest-power candidate** plus its device/backend/configuration and observed envelope. Avoid a perpetual hunt for extra watts or automatic BIOS/driver power-limit modification. A power cap or thermal throttle must be reported, not silently treated as achieved target power.
- Separate `requested workload intensity`, `verified computational progress`, `observed telemetry`, and `sustained high-load achievement`. A GPU at 100% utilization is not automatically at maximum board watts. GPU nominal TGP/TBP is not a universal achieved-watt threshold.
- Provide a sustained high-power baseline mode by itself, since a system that cannot maintain the high-power workload need not proceed to transient trials to demonstrate that particular fault.
- Keep safety preflight, guards, trusted GPU identity, bounded times and temperatures, and verification on every applicable backend; ensure the test can safely stop or fail closed on missing critical evidence.

### 1B. High-amplitude power transitions (primary transient mode)

- Alternate **measured/calibrated high-demand work** with idle/light work. Support low-to-high, high-to-low, and low-medium-high transition series, with asymmetric dwell lengths and predictable cycle timing.
- Prefer keeping resources allocated and the backend initialized across transitions; change actual dispatch/work mix to avoid benchmarking setup or allocation overhead. Provide an explicit separate allocation-churn test only if later justified.
- Distinguish requested transitions from **achieved** GPU power or utilization changes. Record phase IDs, transition commands, completed work, actual dispatch time, observed settling, and missed cycles. Do not report a transient as achieved when the driver throttles, the workload stalls, or telemetry cannot verify it.
- Explore achievable software-controlled transitions in milliseconds-to-seconds ranges using measured pilots. Do **not** describe ordinary user-space phase switching as laboratory-grade 100-microsecond ATX power-excursion testing.
- Consider controlled short dwell, burst clusters, randomized patterns with saved seeds, repeated cold-to-hot startup, and sustained-to-idle-to-hot recovery, with bounded total stress and meaningful timeout rules.

### 1C. GPU OC/UV and workload-diversity stability

- Include a **stepped and seeded variable-intensity sweep**, with intermediate power/voltage-frequency operating regions and repeated return to high demand.
- Alternate diverse GPU execution patterns, e.g. compute-heavy versus bandwidth-heavy, rather than only varying a nominal percent slider on one kernel.
- Never silently change driver voltage offsets, power limits, or board firmware. Test **operator-selected stock/OC/UV configurations** and record permitted existing tuning metadata when available.
- Support A/B testing across stock vs undervolt/overclock, GPU power limits, and PSU/cable/port changes. A clean run establishes stability only for that particular pattern and duration, not global stability.

### Stress adequacy and acceptance gates (critical)

- Separate (a) **functional integrity verdict** (verified calculations/readbacks/errors), (b) **stress adequacy/coverage** (was the intended high-power or amplitude envelope actually achieved?), and (c) **incident outcome** (GPU reset, worker hang, host reset/shutdown, abnormal exit). Avoid a single unconditional PASS when the workload merely ran at low wattage.
- Calibrate physically against representative GPUs and **compare to demanding known-good baseline loads and relevant gaming loads**, including external wall-meter observations when available. The accepted workload must demonstrate genuine power loading, not merely a UI setting of 'extreme'. No arbitrary universal minimum wattage or frequency applies to every GPU.
- Existing software telemetry may be slow, filtered, or GPU-only. *Wall AC watts* includes CPU/platform and PSU conversion losses; it is not GPU board power. External power meters also have time-resolution limits. Do not infer sub-millisecond peaks from a consumer outlet meter; calibrated high-speed electrical instrumentation is required for actual electrical peak measurements or ATX compliance.
- If the host loses power, persistent evidence may stop abruptly. Preserve bounded **last-confirmed phase** breadcrumbs, start/end run-state and an `interrupted / unknown cause` outcome on next launch where feasible. Avoid high-frequency synchronous file writes, especially given observed storage-I/O interruptions; report timestamp uncertainty and lost samples.
- Report driver resets, GPU timeouts, failed compute/readback verification, event/cleanup failures, thermal/power limiting and missing power/occupancy sensors accurately. Do not automatically diagnose PSU failure from a sudden shutdown.
- Safety and reliability: honor existing memory/UMA allocation guards, independent GPU identity, thermal shutoff where supported, bounded run duration/duty, cancellation, cleanup and resource release; don't exceed vendor power limits or auto-alter OC/UV settings. On missing reliable sensors, remain conservative and disclose evidence limits.
- Physically accept the individual backend/device paths actually exercised (AMD/NVIDIA/Intel, dGPU/iGPU where feasible). No blanket GPU/PSU certification from one lab device.

### Operator-facing presets (design targets)

1. **GPU Maximum Power**: calibrated sustained high demand and verified integrity.
2. **GPU Power Transitions**: verified high-power-to-light/idle hammer, with explicit stress-adequacy reporting.
3. **GPU OC/UV Stability**: graduated and mixed load/clock-region sweep, optionally incorporating high-power pulses.

Keep advanced phase timing, seeds, backend selection and other tuning in a secondary control surface. These are future UI goals, not existing LVS commands.

## Milestone 2 - CPU dynamic core-count / burst / hotspot hammer

**Motivation:** Sustained all-core stress may be capped by package power and not reproduce intense high-boost, low-thread behavior, hotspot temperatures, or core-transition instability. Example motivating case: a 65W-restricted Core i9-14900K system appears fine under multicore load but heats or throttles markedly on lightly threaded desktop activity.

### Candidate workload modes

- **Topologically aware worker counts:** 1, 2, 4, 8, ... physical cores up to all physical cores, then all allowed hardware threads, with valid clipping for small systems.
- **Core class and placement:** P-only / E-only / mixed on hybrid CPUs; SMT one-sibling-per-core vs both; rotating favored/fast cores; on AMD, optional CCD-local and cross-CCD placement when topology is authoritative; AArch64 performance/efficiency cluster awareness where available.
- **Hot-core rotation:** stress one chosen physical core (and optionally its SMT sibling), then move to another, while retaining full affinity evidence.
- **Burst/duty modes:** bounded light-to-heavy and idle-to-heavy transitions as well as short sustained windows and changing active core count.
- **Verified computation:** reuse existing proven ISA/native arithmetic checks; errors must be detected despite transitions, cancellation and core pinning.
- **Real-world boost analogue:** workloads that are not only maximal AVX/ISA power, because typical desktop work often reaches high boost under a small number of active threads and lower total package watts.
- **CPU power calibration distinct from boost/hotspot calibration:** a maximum-package-power kernel, a high-frequency/lightly threaded verified kernel, and burst transitions may all be different. Preserve each; do not choose just the highest package-watt workload and assume it covers high-core-temperature behavior.

### Evidence and safety

- Requested and actual affinity, physical core grouping, threads, ISA, verification counts, interval IDs, execution progress; measured package/core temperature, clock and CPU power only where supported and reliably associated.
- Distinguish stable all-core frequency caps from brief single-core boost behavior, thermal throttling and actual errors. A low frequency in idle/transition/cooldown is not a failure.
- Compare thermal behavior across core counts in phase-qualified windows; honor operator thermal/power guardrails; avoid aggressive automatic tuning or BIOS power-limit changes.
- Validation on representative hybrid Intel, AMD SMT/CCD, and ARM big/little devices where applicable.

## Milestone 3 - Coordinated GPU + CPU platform transient sequences

- Reuse milestones 1 and 2 with independently verified workers and one synchronized phase timeline.
- Compare **coincident ramps** (CPU and GPU high together), **offset ramps** (CPU high while GPU drops and vice versa), alternating bursts, and representative gaming-like contention.
- Maintain shared host-memory reserve and accounting on iGPU/UMA systems, bounded device-power demands, deterministic seed for randomized sequences, and exact assignment versus achievement evidence.
- **Calibrate combined platform load** rather than adding two sliders set to '100%'. Compare sustained CPU+GPU platform demand, synchronous ramps and offset ramps to actual wall measurements when available. A CPU workload that power-limits the GPU or competes for shared memory may *reduce* rather than increase peak PSU demand.
- Include distinct modes for (1) maximum combined sustained power, (2) abrupt combined load steps, and (3) anti-phase CPU/GPU swings. Favor accurate executed-work and stress adequacy evidence over nominal percentages.
- Goal: expose system-level weaknesses and enable controlled A/B troubleshooting of PSU, cables, firmware, driver, thermals, OC/UV and board power delivery; never automatically attribute a failure to one cause.
- Positive functional result means 'survived specified patterns with verified computation and disclosed power-envelope coverage', not guaranteed PSU ATX transient compliance. This is especially relevant to the lab's 13700K/RX 6800 XT gaming shutdown scenario, but does not prejudge the PSU as the defective component.

## Milestone 4 - Substantial storage/network expansion (later)

- Revisit deeper dedicated storage stress above the existing Storage Health and Storage Benchmark baseline and the deferred network/NIC test concept, once the dynamic-power work has usable acceptance.
- Preserve non-destructive data safety, system-drive safeguards, and explicit network-peer prerequisites.

## Milestone 5 - HTML/report diagnostics modernization (later; schema groundwork earlier)

- After stress modes and interval reporting are stable, improve the HTML reports' clarity, comparison and drilldowns, while respecting existing output contracts and backward-compatible historical results. Prioritize actionable lab findings over decorative dashboards or overly dense TUI/CLI screens.
- Provide phase-aligned plots and event tables: CPU/GPU load command, observed progress, sensor values, driver resets, thermal throttling events, drops and capture gaps.
- If trustworthy per-model/per-core-class limits are available, show *observations* such as `Observed core temperature X C; reported critical threshold Y C; difference Z C`, including exact sensor and source, rather than asserting physical damage. For Intel, prefer model-specific readable sensor `temp*_crit`/DTS provenance where valid; for other vendors use proven equivalent or 'unknown'.
- Treat base and boost clocks separately by core class and architecture. Flag sustained deficit below a grounded base reference **only during sufficiently loaded, stable, qualifying phase windows**, after stage trim start/end and phase-transition boundaries, with a configurable duration/margin and source/quality indication. Never treat idle dips, power-saving states, changes in core count, intentional power caps, unavailable clocks or transition/cooldown periods as automatic hardware failure.
- Separate warning ('observed deficit') from diagnosis ('thermal or power cap reported by reliable counters') and arithmetic verification FAIL. If only generic vendor/BIOS model data are available, label source and uncertainty; never invent base/boost/TjMax values.
- Keep original raw/extended/compatibility evidence, complete segment association, timing and data-gap disclosures.

## Design gates / unresolved choices (decide before implementation)

1. Which hardware/vendor backend(s) can provide safe, verified **high board-power loading**, not merely high utilization, and usable transient switching on Linux? Require empirical calibration with comparable workloads on multiple cards.
2. Define concise operator presets: **GPU Maximum Power**, **GPU Power Transitions**, **GPU OC/UV Stability**, **CPU Core-Count/Boost**, and later **Platform Power Transitions**. Advanced tuning must not overwhelm ordinary setup.
3. Choose safe default durations, dwell ranges, operating temperature/power abort policy, and repeatability strategy from measured pilots, not from speculative universal targets.
4. Define workload verification cadence and cost so transient pattern fidelity and trustworthy integrity checks coexist.
5. Decide how surviving versus interrupted runs, missing sensor evidence, and post-reboot incident breadcrumbs appear in overall verdicts. Fail closed when critical verification is absent.
6. Establish an acceptance matrix with **achieved watts and amplitude versus known baseline workloads**, verified work, A/B calibration under stock vs known OC/UV, different power limits/PSUs, hot-core behaviors, and simulated failure paths without deliberately abusing hardware. An internally clean but weak workload is NOT sufficient validation of the transient-test feature.
7. Keep **PSU electrical compliance certification** out of scope without separately calibrated high-speed equipment. Linux telemetry cannot certify sub-ms excursions.

## References and grounding

- KitGuru, PowerColor RX 6800 XT Red Devil review: reference 300W; Red Devil board 296W Silent / 327W OC average, manual OC approx 375W. https://www.kitguru.net/components/graphic-cards/dominic-moass/powercolor-rx-6800-xt-red-devil-review/all/1/
- Igor's Lab, RX 6800 XT and CPU measured together: approx 409W mean versus 673W brief *combined system* 12V peaks in one OC gaming scenario. https://www.igorslab.de/en/when-the-power-supply-suddenly-shuts-off-load-peaks-from-graphics-card-and-cpu-measured-and-counter-tested-with-power-supplies-basics-practice/6/
- OCCT's explanation of why its Adaptive workload prioritizes variable V/F rather than highest power, and how FurMark differs: https://www.ocbase.com/news/occt-gpu-stress-testing-modern-adaptive-approach
- OCCT developer discussion acknowledging that newer adaptive workloads reduced GPU power draw in some configurations (April 2026): https://www.reddit.com/r/OCCT/comments/1sqrlos/at_some_point_occt_steady_extreme_stopped_being/
- OCCT September 2026 update describing changes to improve maximum GPU power: https://www.ocbase.com/news/occt-v17-1-linux-compatibility-test-improvements
- Intel ATX 3.x PSU excursion requirements are electrical supply design tests under prescribed timing/duty, not watt peaks guaranteed observable by software: https://edc.intel.com/content/www/us/en/design/ipla/software-development-platforms/client/platforms/alder-lake-desktop/atx-version-3-0-multi-rail-desktop-platform-power-supply-design-guide/2.0/2.1/psu-power-excursion/
- Linux Intel coretemp sensor semantics: https://docs.kernel.org/hwmon/coretemp.html
- Linux Intel throttling counters: https://cdn.kernel.org/doc/html/latest/admin-guide/thermal/intel_thermal_throttle.html

## Sequence, repository recording and GitHub handoff

- **Now:** finish CLI/TUI parity, corrected Vulkan and ARM64 physical acceptance, and remaining already-adopted x86_64/AArch64 architecture milestones. Do not interrupt a running Codex task or modify GPU/CPU workers to prototype these future ideas.
- **Once approved:** incorporate a concise, checkable version of this plan into the real root `ROADMAP.md`. Reconcile with the short transient-stress note that may already have been added by the CLI-parity task. Preserve prior historical roadmap content, deferred Phase 3/4 contract work and existing storage baseline. Mark all new workloads *planned*, not implemented or accepted.
- **Git hygiene:** the main LVS working tree contains numerous unstaged/uncommitted functional changes. Review the resulting roadmap diff first, then if authorized stage/commit **only** `ROADMAP.md` and push that small documentation commit, without accidentally committing unrelated unfinished code. Respect project repo permissions and the user's approval for Git actions. If a safe isolated roadmap-only commit is not possible, leave the file uncommitted and give the exact blockers, rather than mingling unrelated software work.
- **Later:** implement and physically validate Milestones 1A, 1B, and 1C in order; then CPU; then coordinated platform; then substantial new storage/network; later HTML diagnostics. Detailed implementation choices remain separately gated by evidence and hardware feasibility.

**Current implementation instruction:** No new stress-workload implementation authorized. This is a reviewed planning draft. Return to current CLI/TUI and physical acceptance afterward.
