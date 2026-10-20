# Vulkan worker stall diagnostics

This additive instrumentation investigates the synchronized low-activity interval
in the October 19 PL Validation run. The raw clock, utilization, power and cooling
observations corroborate a real operating-state change. They do not establish
whether its cause was worker code, filesystem contention, host scheduling, the
changed kernel/driver, or another environmental condition. No stall fix or GPU
performance improvement is claimed by this diagnostic patch.

## Measurement and retention

`slow_operation_evidence` in each native compute result uses
`linux_validation_suite.gpu_worker_slow_operations`, contract version 1.
The fixed one-second cutoff is diagnostic only: it never changes a verdict,
workload, verification cadence, thermal threshold or memory guard. Legitimately
slow devices may generate many records without failing a performance requirement.

The worker retains the latest 64 slow/exception observations, a slowest record per
fixed operation name, counters, and explicit overwritten-record counts. Memory is
bounded per worker regardless of run duration. Events do not trigger writes.
Fast operations update only bounded summaries. Existing periodic/error/final
result writes carry the evidence. Parsed worker summaries and compatibility
details retain it as `SlowOperationEvidence`; historical absence stays null.

Records include process/GPU/result-file identity, cycle/submission/verification
counts, monotonic start/end, correlated Unix timestamps, observed wall-clock end,
elapsed host time and process CPU time. A difference between correlated and
observed wall time exposes wall-clock adjustments. Process CPU time can help
distinguish CPU work from waiting, but does not prove the cause of a wait.

Separate scopes cover file open, JSON serialization **and file writes**, flush,
forced fsync, close and replacement; command recording; submission; fence waits;
timestamp retrieval; verification/readback; loop preparation/state updates;
sleep/yield; and final device-idle waiting. Nested scopes overlap: their totals
must not be summed as exclusive time. Fence-wait/host elapsed time is not measured
GPU execution. Existing Vulkan timestamp-query evidence remains separate.

An `unaccounted_loop_gap` is an unscoped host interval between observed operations.
It does not prove scheduling preemption. Exceptions are retained even below the
duration cutoff and remain subject to existing worker failure handling.

A result write cannot include its own completed timing. After cleanup and the
last result-write attempt, one bounded JSON record with event
`gpu_worker_slow_operation_diagnostics` is flushed to the existing worker stderr
log. It includes the most recent persistence durations/failures. Normal JSON
snapshots can lag by one write; retain the terminal log as well. No additional
per-event filesystem persistence is introduced. A native fault/SIGKILL can still
lose observations since the last snapshot; missing final evidence is not success.

## Controlled unit deployment

The diagnostics are integrated into the current LVS working project alongside
the existing unfinished SVE implementation. Capture the ordinary complete LVS
build from this working project through the normal workflow; the temporary
investigation worktree is not a deployment prerequisite. Record the base commit
and patched source hashes to identify the exact combined build. The presence of
SVE source does not establish ARM compilation or physical acceptance. No version,
tag, release or profile change is part of this diagnostics integration.

Use the next already-planned PL Validation on an affected unit. Its final
600-second stage supplies concurrent Vulkan stress_hash and OpenCL VRAM work on
both GPUs, matching the relevant workload combination. Keep normal safety and
telemetry; enable Advanced Debug. Return the normal results, raw telemetry,
native worker JSON and worker stderr logs. Align any low-activity interval with
slow-operation timestamps. Do not suppress idle samples. If records point to an
operation, investigate that operation; if none localizes the pause, retain the
kernel/driver/environment hypothesis rather than inventing a worker fix.
