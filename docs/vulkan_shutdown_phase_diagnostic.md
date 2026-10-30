# Opt-in Vulkan compute shutdown phases

This diagnostic investigates the Intel UHD CML GT2 S2 shutdown failure in
`results/2026-10-29_15-35-59_Quick Test`. Arithmetic and final sampled verification
completed, but the parent killed the worker after its five-second shutdown
wait. The last JSON was the pre-teardown `completed` snapshot. It does not
identify the subsequent blocked operation or establish resource release.

The same execution's S4 used the same 20.990 GiB target, 14 buffers and three
rounds, and completed cleanup. Neither result establishes a hardware defect.

## One focused capture on the MSI i7-10750H system

Copy the current working LVS project using the normal workflow. From its root:

```sh
LVS_VULKAN_SHUTDOWN_PHASES=1 LVS_VULKAN_SHUTDOWN_SLOT=0000:00:02.0 \
  .venv/bin/python -B linux_validation_suite_tui.py
```

Select **Quick Test**, then use normal Run Setup stage overrides to enable only
**Baseline SIMD (CPU + VRAM)** (S2) and **GPU (3D + VRAM)** (S4). Retain both
90-second durations and their existing workload, Auto backend, all-GPU targeting
and allocation settings. S2 retains its CPU baseline intent and 90% VRAM policy;
S4 retains its concurrent GPU/VRAM workloads. Keep the GTX 1660 Ti concurrent;
only the Intel worker is instrumented. Do not force the historical byte
assignment if current safe resources differ. Enable **Advanced Debug** and run;
no separate manual Dry Run. Disable S1, S3 and Storage Benchmark for this capture.

GPU identity, preflight, allocation guards, verification and failure classification
are unchanged. The compute-aware parent policy below now governs shutdown.
Invalid diagnostic PCI syntax or a missing
result destination blocks the opted-in worker; other PCI targets are unaffected.

Return the complete execution directory, including Advanced Debug, manifest,
effective profile, worker JSON/logs, telemetry and
`worker_results/segment_2_vram_2.json.shutdown-phases.json` (the ordinal may differ).

## Evidence and interpretation

The `linux_validation_suite.vulkan_shutdown_phases` v1 sidecar contains at most
64 recent entered/completed/raised host-phase records, a cumulative count and
overwrite count, stop-request monotonic/wall timestamps, active phase, PID,
requested/observed physical identity, phase-error count/last error, and diagnostic
publication error/time totals. Worker JSON embeds `shutdown_phase_evidence`.
Earlier observations are replaced atomically; the signal handler performs no I/O.

After a stop request, queue submissions, fence waits, timestamp retrieval,
readback and selected persistence operations are observed. Terminal publication,
wait-idle, each resource destruction/free, device/instance destruction and claim
release are observed even if an earlier exception led directly to finalization.
The forced atexit publication retry is observed without repeating teardown.

An entered phase without a corresponding return identifies where the worker
was last observed, not proof of a permanently hung driver call. Correlate it
with the parent's termination request, wait deadline and exit status. Finishing
the current cycle and a required final cycle can consume part of that deadline.
GPU work and verification are not reduced; instrumentation does not change the
parent policy or renew its deadline.
The stop-request timestamps observe Python signal-handler delivery; they are
not measurements of when the parent sent SIGTERM or when the kernel delivered it.

Each observation emits a bounded-size stderr marker before diagnostic file I/O,
then atomically publishes and fsyncs the sidecar. A completed-phase marker with
`diagnostic_publication=starting` means the operation returned, even if the
following sidecar publication stalls. Check stderr and worker JSON together.
Diagnostic failures remain explicit and do not swallow workload exceptions.

Instrumentation adds shutdown-only I/O and can perturb a tight deadline. Its
publication time is recorded separately; enclosing phases can include nested
diagnostic overhead. OS/filesystem blocking cannot itself be given a hard bound
by synchronous checkpoint writes. Existing parent termination remains the bound.
No ordinary hot-loop publication is added before a stop request.

These are diagnostic host observations, not GPU timings, scheduler-job evidence,
physical-release attestation or an alternative worker verdict. Missing final
cleanup evidence, especially after SIGKILL, must remain unconfirmed.

## Bounded parent shutdown policy

Suite-native Vulkan compute workers in GPU and VRAM roles receive two observed
maximum cycles plus five seconds for cleanup/publication. The total is capped
at 60 seconds. Missing or rejected observations use a finite 15-second fallback
(ten seconds for unknown computation, five for cleanup). These are lifecycle
bounds, not throughput or integrity acceptance thresholds. A capped allowance
does not promise that every possible workload can finish within that bound.

The parent accepts only a bounded regular-file snapshot from the launched PID,
matching result destination and physical target, with verified identity evidence,
finite positive internally consistent cycle timings, and a monotonic publication
timestamp within the current process lifetime. The publication must be no older
than the selected two-cycle-plus-cleanup window (minimum five, maximum 60 seconds).
Cycle durations over 60 seconds are rejected as excessive evidence and fall back;
otherwise valid observations exceeding the total budget are explicitly capped.

Each deadline is anchored once to that worker's SIGTERM-request monotonic time.
Waiting for an earlier worker consumes, rather than renews, its remaining budget.
The parent also interrupts its waits on other workers at pending Vulkan deadlines
to enforce expiry. Unrelated backend allowances retain their existing policy.
After expiry SIGKILL remains available; reaping has a separate five-second bound.
A kernel-stuck process may remain unreaped, which is reported as failure rather
than successful cleanup. Exit timestamps are parent observations, not invented
measurements of the exact instant the process exited.

Parent-normalized WorkerResults retain `shutdown_evidence`, including identity,
timing acceptance/rejection, selected compute/cleanup allowances, cap/fallback
reason, request/deadline/wait/exit/kill observations and final worker result.
The raw child JSON is not rewritten to retrofit parent observations. Compatibility
GPU details/worker summaries expose the intact additive `ShutdownEvidence`.
An accepted timing observation or a normal process exit never substitutes for
successful arithmetic, required final verification, cleanup or publication.
