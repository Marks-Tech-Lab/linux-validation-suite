# Opt-in AMD Vulkan dispatch timing

The October 26 MSI/9800X3D capture reports matching kernel/module vermagic
`7.2.9-ogc3.1.fc44.x86_64`, module help advertising a 2000 ms default, and
`lockup_timeout` bytes `0a` (empty override string plus newline). This is
consistent with the upstream 7.2.9 default, not a measurement of initialized
scheduler timeout or kernel-job boundaries.

From the complete current LVS project on the MSI system, launch the normal TUI:

```bash
LVS_AMD_VULKAN_DISPATCH_TIMING=1 \
LVS_AMD_VULKAN_DIAGNOSTIC_SLOT=0000:07:00.0 \
.venv/bin/python -B linux_validation_suite_tui.py
```

Select **GPU Vulkan Memory Lab**. In Run Setup → Stage Overrides → Configure
Stage Workloads (this run only), select its stage and set **3D GPU target
selection** to **Radeon 610M | PCI 0000:07:00.0**. The stage label says VRAM,
but its enabled module is gpu_3d, not vram. Review must show
`slots:0000:07:00.0`, 90 seconds, Vulkan compute, stateful_memory, extreme/steady,
80% allocation and no CPU/RAM/VRAM/storage/NVIDIA stress worker. Enable Advanced
Debug and run once. No separate manual Dry Run, profile save or kernel change.
Normal automatic preflight, identity binding, budgeting and guards still apply.

The worker requires readable current-boot kernel journal evidence and a working
follow process, compute timestamps with valid counter width/period and API
functions, and at most 64 buffers. Missing capabilities block the diagnostic;
they do not diagnose hardware failure. The opt-in instrumentation does not itself select submission grouping; the
stateful worker now uses one buffer per submission in both modes. Do not substitute a different target or weaken journal permissions.

## Evidence and limits

The normal result directory contains worker_results, the effective profile,
manifest, telemetry, worker logs and Advanced Debug. Return the complete folder.
The AMD worker's `dispatch_timing_evidence` is a separate diagnostic contract:

- Each record gives cycle, per-buffer dispatch geometry/logical words/descriptor
  bytes/rounds, compute-stage timestamp intervals, whole-submission GPU interval,
  host submission/fence durations, and fence completion. Timestamp intervals may
  include pipeline stalls/overlap and are not isolated shader instruction time
  or AMDGPU job boundaries. Instrumentation can perturb GPU scheduling.
- Two whole-submission queries plus two per dispatch are used; the nine-buffer
  workload has capacity for 20 queries; each one-buffer submission writes and
  retrieves only four, never waiting for unwritten query slots. No allocations, arithmetic, dispatch repetitions or
  verification samples are removed. The latest 64 records are retained, with
  an explicit overwrite count. Each successful timing observation is forced
  into the existing atomic worker publication before proceeding to verification;
  it does not claim that the current cycle's arithmetic has been verified.
- A timeout/reset/fault/wedged message naming the selected AMD PCI device stops
  observation. Monitor loss also stops it. A separate bounded stop sidecar
  `<worker.json>.diagnostic-stop.json` preserves the trigger and kernel event.
- Fence waits poll at 50 ms with the existing ten-second deadline. A 120-second
  worker deadline bounds startup/execution; detected stop conditions allow five
  seconds for cleanup before exit 124. If a Vulkan call remains wedged, the hard
  exit does not fabricate terminal cleanup or release external claims. Existing
  parent cancellation/shutdown protection remains in place.

Keep persistent kernel journal evidence if the parent application or session
fails. An empty worker stderr or a successful sampled readback is not proof of
reset-free execution. Sampled verification is not exhaustive memory coverage.

Short individual intervals whose combined submission crosses the advertised
watchdog interval, with matching kernel events, would support testing sequential
submission partitioning. A long individual dispatch would require finer logical
work tiling instead. A reset during short submissions would require a different
explanation. None of these observations alone establish defective hardware.

## Submission correction following the 16:59 diagnostic

The October 26 16:59 capture retained 32 full observations: the last combined
GPU interval was 2.07354438 seconds while individual dispatch brackets ranged
from 0.12432994 to 0.24446934 seconds. The selected AMD device timeout was
recorded at 17:00:20.561444, during the next submission. Exact scheduler-job
boundaries and the initialized timeout were not directly measured.

Stateful-memory worker v23 submits one buffer at a time and waits before reusing
command/fence/query resources. All allocated buffers, rounds and rotating samples
are retained. A compute-write to compute-read/write dependency protects stateful
reads across submissions. A cycle and its final-verification flag advance only
after every partition completes. Stateless hash/stress-hash batching is unchanged.
Physical acceptance completed on October 27 with two finalized 90-second PASS
executions on the MSI PRO B840-VC WIFI / Ryzen 9800X3D / Radeon 610M configuration.
Both retained approximately 25.527 GiB across nine buffers and five arithmetic
rounds, used the corrected per-buffer submissions, completed verification with
zero mismatches, and confirmed cleanup. No recurrence of the original
compute-ring timeout was observed in the captured evidence. This closes the
timeout acceptance issue for that tested configuration; it does not establish
universal AMD acceptance or exhaustive memory verification. The opt-in diagnostic
remains available for future investigations within the limitations above.
