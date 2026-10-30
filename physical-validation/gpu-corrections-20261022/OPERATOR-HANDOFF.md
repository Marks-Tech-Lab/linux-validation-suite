# Historical targeted GPU correction confirmation — October 22, 2026

This retained handoff describes the October 22 correction campaign, originally
prepared against post-v0.5.2-alpha development source. Its physical acceptance
campaign is complete; it is not a request for new testing or a statement that
ARM64 deployment remains paused. Current acceptance boundaries are documented
in [the v0.5.3-alpha release notes](../../docs/release_notes_v0.5.3-alpha.md).

The five original profile JSON files are archived byte-for-byte in
[08 GPU Corrections October 22](<../../profiles/Archived/2026 Hardware Validation/08 GPU Corrections October 22/>).
They are intentionally absent from normal active-profile discovery.

## Direct project-copy workflow

The operator copies the current LVS working project directly onto each target
system using the established transfer procedure. Preserve existing target
results and settings; do not overwrite historical evidence. There is no separate
packaged-build deployment or metadata-preparation step.

For deliberate historical reproduction only, restore the selected archived JSON
unchanged into the project's root `profiles/` directory, alongside
`PL Validation.json`. The existing loader can validate/load the archive by exact
path, while the normal TUI discovers root JSON non-recursively. No loader change
or separate deployment package is needed. Launch the normal TUI from the copied
project's root after restoring the desired historical profile:

```bash
.venv/bin/python linux_validation_suite_tui.py
```

Select the relevant `GPU Correction ...` profile from the normal profile list,
under **advanced/lab profile** or the unfiltered list. These names are distinct
from `PL Validation`; the five exact names appear below. Their absence before
deliberate restoration is expected. If a restored profile is still missing,
stop and verify that the intended copied project is open and its configured
profile directory is root `profiles/`. Do not launch an older installation or
leave the working directory in another LVS copy. Restart an already-open TUI
after updating the project. Do not substitute PL Validation for a missing test.

Use normal target-local environment setup, first-run prompts and GPU drivers.
No Git checkout, provenance stamp, separate helper compilation, or special
deployment utility is required. CPU/RAM are disabled in these profiles, so a
native CPU/RAM helper need not be built for these GPU tests. If another normal
readiness operation needs one, LVS builds it from the included sources on the
target. Do not treat a helper or virtual environment copied from a different
system as proof of target compatibility; preserve normal local readiness/build
handling.
Python is minimum 3.10; the project's tested interpreter is 3.14. `libEGL`,
`libGLESv2`, working hardware drivers, and (for Core Ultra) a usable Intel GPU
OpenCL ICD must be available. Do not accept CPU OpenCL or software EGL renderers.

Through normal Settings, retain GPU Safe Mode, existing memory reserves and
thermal limits; enable abort
on worker error, system fault and threshold failure. Enable Advanced Debug in
the run setup. Retain the approved settings for execution; do not
recall a historical setup that changes backend, allocation, stages or targets.
Keep uploads disabled unless deliberately configured by the operator.

## Normal execution and automatic pre-launch checks

Select the relevant `GPU Correction ...` profile by NAME, enable **Advanced
Debug** in run setup (`D` toggles advanced debug logging), then execute normally.
TUI: select the profile -> run setup -> enable Advanced Debug -> review and run.
Do not skip a blocking preflight.

A separate manual Dry Run is NOT required. Normal TUI run preparation
already performs profile validation, capability/readiness checks and automatic
preflight before workload launch. Retain their evidence together with Advanced
Debug output. The following are acceptance checks for that normal preparation
and resulting evidence, not a request to run a second diagnostic workflow.

These profiles use historical physical PCI selectors, NOT enumeration indices:
RTX 5090 `0000:01:00.0`, AMD iGPU `0000:0d:00.0`, Intel iGPU `0000:00:02.0`.
Verify the current machine inventory before launch. A changed or absent BDF is
a STOP, not permission to use `all`, an index, or a similarly named device.
If the current layout differs, adjust the target using normal profile editing,
review the automatically refreshed preflight, and retain the changed captured
profile and source fingerprint.

Require all enabled stages runnable, exactly the requested GPU(s)/backends,
CPU/RAM/storage disabled, and no Auto backend substitution. Check provider
identity against inventory: EGL device DRM/render-node association must map to
the requested PCI device. Vendor/model similarity or surfaceless fallback alone
is not sufficient proof for this confirmation. For NVIDIA also reconcile its
UUID/PCI inventory. For Core Ultra require the GPU OpenCL device's physical
identity to agree with the selected Intel iGPU; stop on uncertainty/conflict.

Inspect `gpu_memory_kind`, classification source/confidence and
`allocation_safety`. Shared/unknown allocations MUST have
`device_memory_requires_system_guard=true`, regardless of `device_class`.
Require a valid stage memory plan, reserve and runtime guard policy. The actual
guard file is initialized at execution, not by preflight; inspect its normal
worker-results artifact during/after the run. A missing required guard is a
STOP. Device-class/memory-kind differences are not automatically errors (the
safety contract intentionally supports them); unresolved contradictory memory
evidence or an unjustified dedicated exemption is a STOP.

Record original request, final assigned/planned target, backend minimum,
nominal geometry/feasibility and materialized command target. No command or
runtime target may exceed its safe assignment. Below-minimum assignments must
block execution, never become a 64 MiB floor. Unknown discovery can only be
provisional: runtime EGL must successfully query `GL_MAX_TEXTURE_SIZE`.
An incomplete nominal plan is NOT target attainment.

Source provenance is automatic. Runtime version stays 0.5.2-alpha; the actual
fingerprint identifies this corrected source, not that release tag. With no
`.git`, Git association must be unknown. Retain the actual runtime-observed
source fingerprint and initial/final source-change evidence in the results;
do not infer a clean release association from the version string. Profiles are
included in source scope, so deliberate local profile edits change that digest
and must remain visible. No manual provenance command is required.

## Minimal ordered sequence

Select the appropriate named correction profile, enable Advanced Debug and
execute through normal setup/preflight. Do not accidentally choose PL Validation
instead of a targeted test. Run tests sequentially, never in parallel from
separate LVS instances.

1. Ryzen 9950X: `GPU Correction EGL NVIDIA Short` (90 s, 1% VRAM, EGL VRAM only),
   then `GPU Correction EGL AMD Short` (90 s, 1%, EGL VRAM only). These are modest
   percentages, not fixed byte promises; review current assignments first.
2. MSI GP65: `GPU Correction EGL Intel Baseline` (90 s, 1%) first. Only after a
   clean baseline run use `GPU Correction EGL Intel Bounded Geometry` (180 s,
   40%). The latter is deliberately below the historical 80% request, not a
   forced 24.60 GiB assignment. Current MemAvailable and reserves remain
   authoritative. If safe resources cannot fit it, stop rather than increase
   pressure. If budget capping means geometry never exceeds the old
   512 x 16 MiB envelope, mark that scaling boundary untested; do not force it.
3. Core Ultra 7: `GPU Correction EGL OpenCL Intel Timing` (180 s). One explicit
   EGL extreme/steady 3D worker plus one OpenCL VRAM worker at 80%, targeting the
   SAME Intel GPU. No RAM/CPU workload. The higher VRAM request preserves the
   allocation-progress question, but the actual safe assignment may be lower.
   An above-ceiling plan or a short run can legitimately miss full allocation;
   preserve that result. This is a timing diagnosis, not an expected full
   coverage PASS. Do not change allocation cadence, synchronization, intensity
   or buffer count to obtain a better label.

All profiles use two-second telemetry, five-second boundary trims, functional
analysis and no fabricated GPU utilization, clock, temperature or power target.

When the relevant targeted checks are satisfactory, return to the normal
profile selector in THIS SAME build, select **PL Validation**, enable Advanced
Debug for that run, and proceed during the same hardware session. Keep the
targeted results and PL Validation results separate. Do not proceed past an
unresolved safety, identity, verification or lifecycle failure, or treat a
partial/inconclusive targeted result as a full coverage pass.

## Evidence and stopping rules

EGL: require `vram_verification_passes` specifically, not render/marker passes;
zero `vram_mismatch_count`, `gl_error_count` and worker errors; exact runtime
device evidence; clean exit/reaping. Require multiple allocated textures and
enough frames to reach the recurring every-180-frame texture checks, which
sample index zero, middle and last. With a slow driver, 90/180 seconds does NOT
guarantee this: absent texture evidence means INCONCLUSIVE, not PASS. Check the
existing checksum/index evidence where retained; do not invent unsaved samples.
Observe assigned versus nominal allocated bytes, texture side/count and runtime
maximum, backoff, guard denial, cancellation and cleanup. Nominal allocations
do not prove physical residency or exhaustive byte verification.

OpenCL: retain `allocation_feasibility`, `planned_allocation_feasibility`,
`allocation_timing_evidence` and `allocation_progress_evidence`. Compare create,
initial touch enqueue/finish, recurring fill enqueue/finish, blocking readback,
persistence, sleep/yield, maxima, slow events/overwrites and unaccounted time.
Check attempted = completed + interrupted + active; errors/cancellation must
not be counted completed. Retain terminal `LVS_OPENCL_ALLOCATION_TIMING` stderr,
which includes the final persistence observation. Record assigned/active/actual
bytes, chunk size, 1024-buffer or other actual count limit, guard intervention,
API errors and readback. Time spent is not itself proof of driver causation.

Stop immediately through normal Cancel/Ctrl-C on genuine readback mismatch,
unexpected memory pressure, thermal termination, missing/contradictory critical
evidence, wrong target, enlarged assignment, abnormal shutdown, unsafe cleanup
or unexplained allocation failure. Do not kill -9 as normal cancellation. Let
LVS reap workers and preserve logs. Do not proceed to the next larger test.
If testing cancellation responsiveness is needed, use ONE operator-cancelled
repeat after a successful bounded run; label it INTERRUPTED, not a full PASS.
Normal timed completion already exercises termination, cleanup and reaping.

Keep allocation coverage distinct from correctness: a clean readback with a
partial target is partial coverage, never full requested validation. A resource
infeasibility or shortfall is not a diagnosis of defective hardware. Do not
expand testing or change thresholds without review.

## Return artifacts

Return the COMPLETE normal execution result directories from `results/`,
including their Advanced Debug captures and any preflight/diagnostics artifacts
automatically produced. No separately generated `_Diagnostics` folder or manual
Dry Run is required. Include `system_info.json`, captured profile, manifest, all
parsed/extended/compatibility outputs, text/HTML/QA files actually generated,
telemetry/source maps, worker JSON and stdout/stderr, runtime-memory guard state
and Advanced Debug captures. Keep absent telemetry unavailable rather than zero.
Preserve results in the copied working project until returned to the development
checkout; never merge over older run folders. Do not send credentials, secrets
or the whole target settings directory.

For each machine report build digest and hardware, intended/actual backend and
identity, requested/assigned/feasible/achieved bytes, specific readback counters,
guard and lifecycle behavior, errors, and PASS/FAIL/INCONCLUSIVE with paths.
After satisfactory targeted checks, normal PL Validation in the same session
is the approved next step; no additional campaign is required by this handoff.
