# Storage Thermal Assist in timed validation stages — Stage 2B-3

This development milestone integrates the [standalone runner](storage_thermal_assist.md)
with the shared profile-stage execution path. It is software/synthetic validation,
not physical heating, interference or active-storage acceptance. The existing
completion-based Storage Benchmark remains separate.

## Configuration and operator workflow

`modules.storage_thermal` is a duration-based optional module. Its duration is
always the containing stage's duration; a saved profile cannot supply a second
duration or reusable execution approval. The shared CLI/TUI **Configure workload
settings** interface and Run Setup **O / Stage Overrides** expose:

- Enabled/OFF, all internal, SATA/SAS, NVMe, HDD, SSD or individual stable IDs.
- Ordinary 50% and system-drive 25% intent; individual intensity overrides.
- Read size, and an atomic advanced-rate JSON edit containing `rate_mode`, `iops`
  and `bandwidth_bytes_per_second` (use JSON `null` for an unused rate).
- Required monitoring or explicitly requested bounded unmonitored operation,
  temperature warning/stop thresholds and ordinary Linux scheduling.

Lists and per-drive mappings use JSON. Configuration is transactionally validated
by the same `ThermalConfig` policy as the standalone runner. Enter/back cancels
editing; invalid input does not partly change a stage. Save, Save As and Copy use
the existing profile workflows. A run-local OFF comparison changes no saved file.
Original/effective profiles and field-level overrides remain separately captured
in [effective readiness evidence](../OUTPUT_CONTRACT_INDEX.md). Runtime results
also preserve `profile_original.json`, `profile_used.json`, manifest/extended
`profile_configurations`, and compatibility `ProfileConfigurations`. Consent
remains separate from authored profile data.

The existing `thermal_pilot_v1` ceilings remain provisional: HDD 30 IOPS/2 MiB/s,
SATA/SAS SSD 128 IOPS/8 MiB/s, NVMe 256 IOPS/16 MiB/s. Percentages are bounded
activity policy, not rated performance or measured heating. Only proven inactive,
independently addressable ATA/SAS HDD paths can execute. System/mounted drives,
RAID/ZFS/LVM, unsupported SSD/NVMe and uncertain topology remain blocked. Automatic
filters exclude USB, virtual and logical devices; individual selection bypasses
only that filter. No permission change or automatic guard/fio installation occurs.

## Independent, non-gating readiness

Storage Thermal Assist never determines CPU/GPU/RAM validation PASS/FAIL.
Readiness records discovered, selected, eligible, excluded and blocked devices,
resolved rates, backend evidence and exact reasons in its own plan. CLI/TUI and
saved diagnostics show that coverage separately from primary readiness counts.

No eligible drive, unavailable backend, missing permission, unsupported topology,
missing required monitoring or another pre-execution blocker produces auxiliary
**NOT_RUN**, while valid primary workloads continue automatically. A validated
eligible subset runs automatically with excluded drives and reduced coverage
reported. No reduced-coverage confirmation is required, and no storage warning or
error is injected into primary evaluation. Malformed auxiliary settings remain
non-executable and independently diagnosed; profile editing/saving still rejects
invalid authored values. An unreadable whole profile is not implicitly repaired.

Only safety-sensitive unmonitored execution requires a run-local decision. CLI
and TUI offer numbered choices: explicitly approve the listed bounded activity,
continue primary validation without unmonitored activity (Enter/default), or
cancel the run. A declined/missing/expired approval means auxiliary NOT_RUN, never
implicit permission. Consent covers the exact schedule, device identities,
durations, intensities, backend and monitoring scope. It is consumed at launch,
expires within the bounded session and is never stored in a saved profile.
Changed unmonitored scope cannot inherit a short or previous approval. No measured
thermal margin or heating claim accompanies unmonitored activity.

All seven standard profiles retain required monitoring by default. Active boot/
system drives remain visible with 25% intent but blocked. This is a temporary
backend-proof boundary: a separately validated active boot-drive read-only path
is the first priority of Stage 2B-4, followed by other active-storage proofs. No
Stage 2B-3 setting bypasses exclusive ownership, identity or the native guard.

## Execution, monitoring and outcome policy

One adapter process per stage invokes the existing `ThermalRunner`. There is no
second I/O engine. A stage-only native admission protocol wraps the existing guard;
its standalone protocol, fixed descriptor-bound fio arguments,
O_RDONLY/O_DIRECT/O_EXCL ownership, executable pinning, mutation restrictions,
identity checks and thermal safeguards are preserved.

The primary CPU/GPU/RAM launch path and timed loop remain authoritative. The
adapter starts only a supervised initializer on that path; inventory, backend
checks and filesystem preparation happen in the child. Two anonymous pipes carry
a bounded readiness packet and a per-stage permission token. No thread, daemon,
socket service or second I/O engine is involved.

The initializer must obtain permission from the still-current parent stage. That
permission is **not** native I/O admission. A Python lease check remains an early
exit optimization; it cannot authorize a worker on its own.

The stage-only native protocol has three ordered phases:

1. Before calling Popen, the supervisor records a pending bootstrap in
   `launch_ownership.json`, including its own process group. The bootstrap's exec
   image receives `/dev/null` on stdin and only the pinned executable, a private
   Unix packet socket, and the shared lease descriptor. The drive descriptor is
   excluded from inherited descriptors. Trusted Python's normal close-fds
   pre-exec path is part of this contract; arbitrary pre-exec callbacks are
   forbidden. A delayed bootstrap remains in the known supervisor group.
2. After Popen returns, the PID is registered in memory and published before an
   OWN packet permits the native child to create its process group. Only then
   can a drive descriptor be offered through `SCM_RIGHTS`. An offer is not proof
   of admission; an acknowledgement can be lost and is recorded as unconfirmed.
3. The native guard validates the primary-provided lease identity and takes an
   independent Linux open-file-description (OFD) lock on that original memfd. It rejects closure, verifies the packet, and samples
   `CLOCK_MONOTONIC` under the lock after receiving the quarantined descriptor.
   **The successful deadline sample is the admission linearization point.** The
   state must still be open, the owner alive, and the sample before the original
   stage deadline. Only then can the descriptor become fio's stdin. The guard
   acknowledges the commit timestamp and performs the existing identity,
   geometry, privilege and syscall-restriction checks before fio execution.

Revocation first writes a closure request, then attempts the same lock without
waiting. Writing CLOSED under that lock is authoritative revocation: later native
commits cannot pass. A lock already held by an admission critical section means
closure is pending, not falsely confirmed. That section may already represent an
in-flight admission; its PID was registered before it could receive a target.
The request also rejects new entrants. Parent teardown retries closure and retains
the recovery latch if closure or cleanup cannot be confirmed. No primary timed
path waits on this lock or on launcher readiness.

The stage protocol is **v2**; the existing six-byte monotonic state remains
`LVS1OO` / requested `LVS1OR` / closed `LVS1CR`. The primary alone creates the
memfd and captures its kernel `(st_dev, st_ino)` while retaining a live original
pin. `admission_identity` carries those exact integers through the inherited
control channel; the supervisor must attach with that identity, never derive a
new one from a presented descriptor. The same identity is passed explicitly to
the native guard and recorded in admission, ownership and recovery evidence.
Neither a descriptor number, name, size nor valid-looking state establishes it.
Keeping the original inode pinned prevents its identity being recycled while a
stage or uncertain cleanup remains live.

Each Python operation and each native admission **reopens only the validated
lease memfd** through `/proc/self/fd`, yielding an independent OFD. Reopening is
not a device-path fallback. Inherited or dup'd descriptors are not competing lock
owners; a forked Python object is rejected until independently attached. Locks
use `F_OFD_SETLK` / `F_OFD_GETLK`, whole-file range `[0, EOF)`, with nonblocking
acquisition. Missing kernel support rejects instead of falling back to POSIX
locks. Linux OFD support (3.15+) and the already-required `/proc` are necessary.

Private operation pins and lifetime aliases stay live for the complete critical
section. A duplicate is used **only** to retain that exact OFD, never as an
independent contender. Closing another descriptor for the inode cannot release
its OFD lock. The native function is single-threaded, has no asynchronous close
handler, and does not publish these private references. Terminating signals abort
it and kernel teardown releases its references. A private reference is closed
only after unlock/abort; it is not transferred to fio.

Identity is checked when attaching, after reopening, and inside the critical
section. Native lock verification uses the separate transport OFD as a GETLK
probe and confirms compatibility on its private owner OFD. Missing, released or
ambiguous ownership rejects. A public handle swapped during admission cannot
redirect state checks to a replacement: state and locking use the original pin.
Unexpected private-handle replacement is also rejected, while its lifetime alias
keeps the original lock/inode pinned until abort. Validation after the clock
sample must succeed before a commit is acknowledged or fio receives stdin.

Revocation writes through an original validated operation pin. If the transport
was unexpectedly closed/reused, the original closure is still requested and the
mismatch is reported; the replacement is neither adopted nor closed as though
owned. A failed identity, failed lock, incomplete closure or uncertain cleanup
remains ERROR with recovery protection. The original pin is retained for manual
verification rather than silently replaced or released.

These are advisory locks between cooperating, source-controlled participants;
they do not restrain malicious writers that deliberately ignore the protocol.
The guarantee excludes arbitrary code injection, ptrace/root interference or
noncooperating same-process code closing all private references. Production
`guard_environment` excludes preload injection. Tests use a private preload shim
only in disposable regular-file policy-test children to force actual kernel
close/reuse/unlock behavior; it is not a runtime dependency or operator option.

A libc binding supports CPython builds without `os.memfd_create`; unavailable
kernel/libc support fails closed. A private AF_UNIX SOCK_SEQPACKET pair carries
ownership and descriptor packets; no listener or third-party package is added.
See [Linux record/OFD lock semantics](https://man7.org/linux/man-pages/man2/fcntl_locking.2.html)
and [Python descriptor passing](https://docs.python.org/3/library/socket.html#socket.socket.sendmsg).

An already-committed launch may begin or continue work briefly after a cancellation
request or deadline tick. Cancellation cannot retroactively undo a valid commit:
its registered process group must be stopped and reaped. This is distinguished
from a late, uncommitted bootstrap, which receives no usable fio target after
closure. The native clock sample establishes authorization, not a hard real-time
promise about later exec or syscall timestamps. Queued descriptors are discarded
when the gate rejects them. The native child also uses parent-death SIGKILL,
re-established after privilege dropping. Host crashes, uninterruptible kernel
calls and malicious administrative processes are outside an instantaneous-stop
guarantee; uncertain cleanup remains an explicit, persistent blocker.

Absolute deadlines use the original primary stage window. The configured native
duration is capped by whole seconds remaining at initializer admission and the
supervisor independently stops activity at stage end. Shortened activity is
recorded separately from requested duration. The Python path declines bootstrap
launches with at most one second remaining; the native deadline remains decisive.

Primary workers, telemetry and progress polling never wait for initializer
readiness. Before initializer permission, helpers share a group: cancellation
uses TERM, a one-second wait, then KILL and a two-second wait when necessary.
After permission, parent reconciliation waits at most six seconds, then kills an
unresponsive supervisor group and waits up to two more seconds. Registered native
leaders carry parent-death SIGKILL; forced owner death still records cleanup as
unconfirmed and requires manual recovery verification, never a fabricated PASS.
Native-launch cleanup broadcasts first, waits at most two seconds, then KILLs
outstanding owned workers with one additional second of observation. These are
bounded cleanup windows, not extensions of the primary metric interval. A stalled
launcher with an unknown PID remains tracked by its pending record and supervisor
group; it cannot receive a target without later registration and native admission.
Missing completion or uncertain descendants remain ERROR with the recovery latch.
Killing only a supervisor is never presented as confirmed native cleanup.

Old guards lacking `--stage-admission-version` v2 block only the auxiliary stage
path with an explicit rebuild reason. Rebuild the guard on the target using the
existing [standalone build instructions](storage_thermal_assist.md). The
standalone runner retains its existing protocol and execution behavior.

Atomic live observations retain monotonic timestamps, device identity, activity
counters, temperature availability and stop reasons. They are correlated in
`storage_thermal/.../stage_monitoring.jsonl`; runner progress and terminal records
remain the underlying evidence. Unavailable sensors are never zeros or proof of
safe temperatures.

A drive-level safety stop or auxiliary execution/monitoring failure stops only
its own storage workers. Primary validation can PASS with auxiliary NOT_RUN,
STOPPED or ERROR. Its verdict, failure-reason list, worker-integrity counters and
GPU/CPU evaluation remain unchanged. A separately evidenced **system-wide** safety
emergency may interrupt the entire run: that is aborted/incomplete, not an
invented CPU/GPU hardware FAIL. Drive temperatures or an auxiliary ERROR alone
are not automatically interpreted as a system-wide emergency. Existing primary
and platform safety policies remain authoritative.

Normal cancellation requests stop the auxiliary supervisor, which performs its
existing bounded group cleanup. A parent PID is supplied at launch: an already-
exited parent blocks startup, and disappearance during activity stops storage.
Unconfirmed cleanup stays ERROR and prohibits subsequent storage launches, while
primary stages may continue. The adapter retains a process-local recovery latch
and writes `build/storage_thermal_recovery_required.json` for later processes.
A missing or unreadable terminal record is not proof of descendant cleanup.

Recovery markers are never automatically removed. An operator must inspect the
recorded supervisor/native PIDs and process groups and retained evidence, establish that processes
and exclusive claims are gone, then explicitly remove the recovery marker and
restart LVS. Do not remove a marker merely to bypass an unknown live process.
If marker publication fails, the in-process latch remains authoritative and the
publication failure is reported; cross-process persistence cannot be promised
on an unwritable filesystem. Separate external or malicious administrative
processes remain outside this narrowly constrained guard's security assumptions.

Workers are **not retained across stages**. Confirmed shutdown and separate
per-stage counters, monitoring and completion take priority over retention
complexity. New I/O admission expires with the primary stage; in-flight I/O and
bounded shutdown may outlast it. The primary metric window ends before auxiliary
reconciliation. Its separate shutdown tail contributes to total run elapsed but
cannot dilute CPU/GPU utilization or integrity analysis. No overlapped or extra
activity is credited to another stage. Parent-session time, stage deadline,
admission state and time to the first native worker are recorded when available.
Physical startup interference and safe retention benefits remain unmeasured.

## Result contract and standard profiles

`storage_thermal_result` in the executed plan and `storage_thermal_summary` in the
stage window preserve requested settings, readiness, consent when applicable,
actual activity and original terminal contracts. Segment documents add
`storage_thermal` / compatibility `StorageThermal` without changing primary
hardware buckets. Operator-facing outcomes are separate from underlying native
PASS/WARN/FAIL/INCOMPLETE evidence:

| Auxiliary outcome | Meaning |
| --- | --- |
| COMPLETED | Intended eligible work finished with confirmed lifecycle/evidence. |
| COMPLETED_WITH_WARNINGS | Completed with partial coverage, unmonitored operation or other nonfatal limits. |
| NOT_RUN | Disabled or blocked before execution; no work credited. |
| STOPPED | Operator cancellation or a local safety termination, with valid cleanup/evidence. |
| ERROR | Execution, monitoring, cleanup or evidence-publication failure. |

Cleanup/publication failures take precedence over a nominal stop or completion.
Raw failure reasons and counters are preserved; adding an auxiliary outcome never
converts incomplete native work into successful verification. Per-drive summaries
retain selection/exclusion reasons, configured and achieved rates, read activity,
temperature coverage, duration, stop reasons and cleanup/publication evidence.

The whole-profile manifest/extended `storage_thermal_summary`, compatibility
`StorageThermalSummary`, and separate `storage_thermal_summary.json/.txt` provide
independent aggregate and per-stage/per-drive outcomes. An auxiliary reporting
failure becomes auxiliary ERROR and stays out of primary failure collections.
The main manifest retains authoritative publication status. Summaries are compact;
full native/source evidence remains in the referenced stage/worker artifacts.

The summary's ERROR/STOPPED outcomes do not change the primary report Result or
run-progress verdict. Successful reads never establish storage integrity, heating
effectiveness or maximum-power superiority.

Exactly seven active profiles request the module in **41 stages**:

| Profile | Stages |
| --- | ---: |
| PL Validation | 4 |
| PL Validation 4hr | 4 |
| PL Validation 6hr | 4 |
| PL Validation 12hr | 8 |
| PL Validation 24hr | 16 |
| QA System Test Short v2 | 4 |
| Power Test 5hr | 1 |

All pre-existing profile fields remain unchanged. Regression comparison strips
only the intentional `storage_thermal` additions and compares each complete
profile with commit `75c7ce439e26720a8aec9a73923248901fe42ea2`. No archived profile
or historical result is edited.

## Scalability and physical acceptance boundary

The same resolver and supervisor resource/descriptor budgets apply on small and
large hosts. There is no core reservation or model-specific targeting. Shared
supervision, QD1, conservative per-device limits and staggered launches preserve
the 6C/6T, 24-HDD + 2-NVMe + 2-SATA-SSD evaluation scenario; unsupported classes
are displayed and blocked. Missing memory, permissions, backend or telemetry is
a readiness limitation, never an unsafe fallback.

Physical inactive-HDD deployment, sensor/safety response, heating, x86/ARM64 host
portability and measured CPU/GPU interference remain pending approved pilots.
No real drive, active storage stack or production server is exercised by this
milestone's tests. Active-storage proof remains Stage 2B-4; physical thermal and
interference acceptance remains Stage 2B-5.

## Development source provenance

Complete scoped development identity: **384 files**, SHA-256
`72815511afc23fb9a0356fefaa323c12279d332a3ad26bf670d6f526e7cea741`.
This supersedes the earlier, gating Stage 2B-3 development snapshot. The new
shared auxiliary-result helper and clarified readiness/lifecycle/reporting policy
change executable Python behavior and the source fingerprint. The seven approved
profile requests remain unchanged. The guard gains only the stage admission
protocol; standalone runner and CPU/GPU workload sources are unchanged. Markdown and smoke tests remain outside the
execution-source scope. No new snapshot is claimed as physically executed.

## Final non-gating validation

- **37/37 focused thermal groups PASS**, including 23 stage/auxiliary groups.
- **424/424 complete smoke checks PASS** on the final frozen implementation.
- **81/81 profiles valid** (25 active, 56 archived); five unchanged advisories.
- **401 Python files compile**, **29 integration imports PASS**.
- Native x86-64 guard policy/negative controls execute on temporary regular-file
  fixtures; AArch64 guard object compilation PASS. No physical drive is tested.
- Primary PASS is verified with each auxiliary outcome, including ERROR and
  STOPPED. The separate evidenced system-wide emergency yields aborted/incomplete,
  not fabricated hardware FAIL. Auxiliary publication failure and exact native
  failure preservation are covered independently of primary completion.
- Unmonitored approval/decline, partial/no coverage, recovery-marker persistence,
  cleanup failure, original/effective configurations, CLI/TUI parity and all
  seven profiles/41 stages pass regression checks.
- Markdown/local links, static import cycles and `git diff --check` PASS.

The earlier gating Stage 2B-3 validation is superseded by these checks. Physical
storage acceptance remains pending. The standalone runner and accepted CPU/GPU
workload implementations remain unchanged; the guard extension is stage-only. Everything stays
unstaged/uncommitted for review.


## Auxiliary isolation corrections

The earlier final audit found two primary-isolation commit blockers: parent-side synchronous
initialization could consume a primary timing window, and auxiliary aggregation
could throw before primary publication. The supervised deadline/permission path
above removes the first dependency. A real-time regression uses a valid two-second
primary stage and a disposable ten-second initializer: normal telemetry continues,
the primary window remains approximately two seconds, and cancellation reaps the
initializer without granting I/O. Early cancellation, late readiness, expired
opens and precise pre-admission rejection records have separate assertions.

Primary finalization and verdict calculation remain outside auxiliary exception
handlers. Auxiliary aggregation, normalization and serialization faults become a
literal JSON-safe ERROR with diagnostic context. The combined text renderer
contains only its auxiliary section; failure uses a minimal ERROR section instead
of losing primary text. Manifest and primary summary publication are atomic.
Root manifest, compatibility and extended summaries preserve the auxiliary error;
per-drive native evidence is not rewritten into successful activity. A genuine
primary exporter, renderer or filesystem failure still propagates.

Fault-injection checks require both primary `run_manifest.json` and
`run_summary.txt` with an independently justified PASS after auxiliary aggregation,
normalization, serialization, publication or rendering errors. All five auxiliary
outcomes are tested separately from primary verdicts. No hardware run or physical
thermal acceptance is implied by these software fixtures.

## Launch-race verification and evidence

The subsequent audit exposed a third blocker: a Python check followed by Popen
could still invoke the launcher after cancellation or expiry. The native protocol
above replaces that boundary rather than adding another Python check.

Deterministic regressions cover cancellation and real monotonic expiry at the
former check-to-launch boundary; cancellation during Popen, immediately after
creation, after ownership and after descriptor offer; eight repeated races;
queued descriptors blocked by a different process's lock; real native deadline
expiry; a registered in-flight commit; ownership-publication and revocation failures; escaped worker-finalization errors; and a
stalled launcher with persistent recovery protection. The two-second primary /
ten-second initializer test and independent publication-failure tests remain.
Fixtures use only private regular files and the native policy-test mode, never
physical drives. The native guard also retains the original standalone negative
controls. Software-only results do not establish physical thermal acceptance.

`stage_launch_ownership` and `launch_ownership.json` retain pending/created/owned/
offering/committed phases, PID, supervisor group, group readiness, descriptor
offer, admission timestamp, exit and cleanup evidence. `initializer_permission_granted`
is separate from native `io_admission_granted` and `io_admission_state`.
An offered descriptor with no confirmed acknowledgement is **unconfirmed**, not
success or proof that no work occurred. These records supplement, not replace,
actual read counters and the authoritative runner's worker evidence.

## Lease-identity correction and kernel regression evidence

The final v1 audit reproduced a different, valid-looking memfd at the old
supervisor descriptor number while the primary's original inode was CLOSED.
Version 2 binds all participants to the primary identity and original pinned
resource. It also removes the POSIX close-any-alias lock-release hazard.

The regression set reproduces that exploit with independent processes and requires
native rejection before a target can be offered. It covers replacement before
locking and during cancellation/revocation, repeated closed/deadline cases, native
transport and private-pin replacement inside the critical section, same-inode
private-OFD substitution, lock failure/release/ambiguity, actual deadline expiry,
process termination, and persistent recovery after identity failure. Real kernel
contention is checked with independent OFDs in the same process and multiple
simultaneous processes. A POSIX alias-close control demonstrates the old release
behavior; OFD controls prove both same-description and same-inode alias closure
retain the intended lock. Inherited lock ownership is never assumed.

The previous launch races, in-flight commit cancellation, stalled-launcher
recovery, two-second primary/ten-second initializer, publication isolation,
non-gating outcomes and seven-profile/41-stage preservation checks remain in the
full suite. All targets remain synthetic/private regular files. No physical
thermal or active-storage acceptance is claimed.

## Complete pending development inventory

Relative to commit `75c7ce439e26720a8aec9a73923248901fe42ea2`: **44 files**,
40 modifications and four additions. Results, helpers, generated artifacts and
`settings/.lvs_state.lock` are excluded.

```text
Modified:
Modules/lvs_cli_preflight_summary.py
Modules/lvs_cli_run.py
Modules/lvs_dry_run.py
Modules/lvs_profile_cli_editor.py
Modules/lvs_profile_loader.py
Modules/lvs_profile_models.py
Modules/lvs_profile_report_text.py
Modules/lvs_profile_save.py
Modules/lvs_profile_validation.py
Modules/lvs_run_artifacts.py
Modules/lvs_run_bootstrap.py
Modules/lvs_run_completion.py
Modules/lvs_run_execution_context.py
Modules/lvs_run_models.py
Modules/lvs_run_orchestration.py
Modules/lvs_segment_document_builder.py
Modules/lvs_stage_completion.py
Modules/lvs_stage_configuration.py
Modules/lvs_stage_execution.py
Modules/lvs_stage_live_loop.py
Modules/lvs_stage_postprocess.py
Modules/lvs_summary_text.py
Modules/lvs_tui_event_adapter.py
Modules/lvs_tui_run_execution_adapter.py
Modules/lvs_tui_run_setup_flow.py
Modules/lvs_tui_stage_configuration.py
Modules/lvs_workload_runner.py
OUTPUT_CONTRACT_INDEX.md
README.md
ROADMAP.md
docs/storage_thermal_backend_contract.md
native/storage_thermal_guard.c
profiles/PL Validation 12hr.json
profiles/PL Validation 24hr.json
profiles/PL Validation 4hr.json
profiles/PL Validation 6hr.json
profiles/PL Validation.json
profiles/Power Test 5hr.json
profiles/QA System Test Short v2.json
smoke_tests/run_smoke_tests.py

Added:
Modules/lvs_storage_thermal_results.py
Modules/lvs_storage_thermal_stage.py
docs/storage_thermal_stage_integration.md
smoke_tests/storage_thermal_stage_checks.py
```
