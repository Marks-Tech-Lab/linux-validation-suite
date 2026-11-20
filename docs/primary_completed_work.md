# Primary completed-work measurements

These supplementary measurements preserve workload selection, affinity,
verification, allocation, stage timing and primary PASS/FAIL rules. Existing
verification cycles remain available as diagnostic proxies. They are not
retrospectively converted into throughput. Missing, failed or insufficient
measurement evidence never creates a primary PASS or FAIL.

## Native execution counters

SSE2 (`sse2` and `sse2_int`) counts the actual executed inner-loop iterations,
including the completed portion of a signal-interrupted batch. Full batches are
200,000 FP32 iterations or 260,000 integer iterations; zero executed iterations
contribute zero. The existing finite/checksum/canary verification runs unchanged.
This is genuine completed computational work, not a new numerical oracle for
every arithmetic result. SSE2 FP32 has four four-lane multiplies, three adds and
one subtraction per iteration: **32 algorithmic FP32 operations**. Clamp,
checkpoint, canary and housekeeping instructions are excluded. Compilers may
unroll or express subtraction as addition of a negative constant. This is not
retired-instruction counting, a utilization-derived estimate or peak FLOPS.
Integer SSE2 reports iterations, without inventing an arithmetic-operation rate.
Other ISA families retain their existing verified-progress contracts; no SSE2
geometry is assigned to them. Python/external workers remain unmeasured here.

RAM counts actual 64-byte regions processed by the existing loop, per thread:

- `processed_bytes`: bytes written plus bytes actually compared with the expected
  pattern. Initialization writes count as processing, without claiming readback.
- `verified_bytes`: bytes in successfully matched eight-byte comparisons.
- `completed_units`: regions written, including completed work in a partial pass.

Untouched per-thread tails and unprocessed allocation are excluded. Failed comparisons
are not verified bytes. Existing integrity errors and minimum verification remain
authoritative. No additional workload memory reads/writes are introduced. These
are **logical workload bytes**, not measured physical DRAM bandwidth: caches,
write allocation, controller traffic and pattern computation remain distinct.

## Raw observations and interval analysis

Native `RESULT.work.jsonl` sidecars and terminal `work_progress` use the versioned
`lvs_primary_work_v1` contract. Each contains process identity, per-thread counters
and Linux CLOCK_MONOTONIC timestamps; raw rows include correlated wall-clock
pairs. Worker-private cumulative counters publish at bounded checkpoints with a
250 ms minimum publication interval. RAM counts and checks publication after each actual pass traversal
(or partial final pass), outside the unchanged region hot loop; CPU checks at its existing verification batch boundary.
Production builds link the shared publisher as a separate compilation unit to
keep accounting state and compiler inlining effects out of the workload loops.
Direct single-source development builds include that same implementation. No I/O
or mutex is added to the arithmetic inner loop. One supplementary writer
thread per measured helper snapshots in O(thread count) storage every two seconds,
using a monotonic condition timer. Counter publication uses a short mutex;
filesystem writes occur outside it. Snapshot write duration is retained.
Very large/slow per-thread passes can leave stale publications and insufficient
in-window rate evidence; allocation is never used to fabricate progress between
those boundaries. Publication failure makes measurement unavailable and preserves
verdict policy.

Final artifact construction uses the same time base as raw stage telemetry.
`worker_results[].primary_work_analysis` is retained in the run manifest and
`primary_completed_work` in report JSON. Both publication endpoints must lie
inside the actual stage interval after start/end trims. No warmup interpolation,
nominal-duration denominator or extrapolation over missed snapshots is used.
Per-thread covered seconds and deltas are retained; aggregate rates sum each
thread's observed-interval mean rate, without double counting. Threads may cover
slightly different subintervals; these are not an asserted simultaneous
instantaneous bandwidth. An observation window too short to cover every thread
is unavailable. Canceled work can provide valid observed intervals when native
verification, clean exit and final publication are confirmed; it does not become
a completed stage. Missing terminal/sidecar, lost records, resets, foreign PID,
thread disagreement, verification errors, persistence errors and contradictory
terminal counters suppress rates. No metric certifies storage cleanup.

For future matched Thermal Assist comparisons, retain the same resolved primary
commands, affinity, thread count and RAM allocation, comparable starting
conditions, identical trims and enough observed duration. Compare per-thread
coverage and genuine work rates alongside existing resource/telemetry evidence.
The existing observer accepts:

```sh
.venv/bin/python -m scripts.storage_thermal_acceptance analyze \
  --directory /absolute/observer-capture \
  --run-manifest /absolute/run/run_manifest.json
```

This attaches recorded primary measurements; it does not reconstruct them from
historical verification proxies. Historical Samsung physical campaigns remain
accepted within their original scope and are not retroactively throughput tests.

## Qualification scope and scalability

Deterministic fixtures exercise one and 256 heterogeneous counter streams, exact
known native loop work, partial regions, trimmed windows, malformed/missing and
contradictory observations. Real concurrent helper tests use the existing
production launch, stop and evidence functions. The sealed QEMU campaign in
`scripts/primary_work_probe.py` runs genuine SSE2/RAM helpers through production
stage execution, cancellation and native result evaluation, with actual procfs
telemetry callbacks. Three alternating reference pairs compare against accepted
pre-instrumentation helpers. Legacy pass rates in those pairs are overhead
proxies only; current completed-work rates remain separately recorded.

Instrumentation does not select allocations or threads from hardware models or
unrelated capacities. Storage is linear in actual worker count, with one writer
per helper process, not per worker. Existing safe resource plans, CPU targeting,
older ISA paths and memory guards remain unchanged. Native builds track the new
shared header for both helpers. No universal cross-hardware overhead percentage,
physical DRAM rate, or definitive physical interference acceptance is claimed.
A timing difference smaller than reference variability is unresolved rather than
proof of zero overhead. Broader physical/calibration/scalability work remains open.

## Recorded final software results

The final-source sealed VM used Linux 7.2.9-200.fc44.x86_64 and QEMU 10.2.2,
with the actual supported native build commands and the accepted `2ee5db0`
reference sources. A ten-second completed CPU/RAM stage and seven-second
cancellation case retained genuine procfs telemetry, native verification and
observed interval rates. Raw binaries, source fingerprints, compiler identity,
sidecars, stage windows and three alternating four-second reference pairs are
retained by the reproducible harness. No physical storage workload was run.

Initial in-loop accounting and compilation variants produced material pass-rate
changes and were rejected. Final external publication differed from the original
CPU proxy by -0.62% and RAM proxy by +0.08% in this VM sample, within observed
reference variability. These are bounded overhead observations, not proof of
universal zero overhead or physical throughput-interference acceptance. The
verification-cycle proxy is used only for comparing old/new implementation
overhead; actual current work measurements have the separate semantics above.

Final regression validation passed 503/503 smoke tests, including four focused
completed-work groups and the retained 112-case Thermal Assist evidence matrix.
All 81 profiles validated with five unchanged advisories; 439 Python files
compiled and 65 integration imports passed. The final CPU/RAM helpers and shared
publisher compiled for AArch64; native x86-64 safety, documentation, import-cycle
and whitespace checks passed. Seven Thermal Assist profiles/41 stages and all
protected artifacts remain unchanged.
