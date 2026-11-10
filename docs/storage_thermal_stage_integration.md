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
and uses the durable execution-intent journal described below for later processes.
A missing or unreadable terminal record is not proof of descendant cleanup.

Neither the journal nor its scope anchor is automatically removed. Manual recovery
must establish that the recorded supervisor/native processes, descendants and
exclusive claims are gone, then publish a confirmed CLEAN record while holding
the original scope lock. Deleting a marker alone is not recovery; missing state
beside the permanent anchor remains blocked. Failure to establish durable intent
prevents admission, so later publication failures cannot erase an existing
ownership obligation. External deletion/rollback and malicious administrative
processes remain outside this constrained protocol's security assumptions.

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

## Adversarial-audit corrections: monitoring, recovery and terminal evidence

The primary timed loop consumes bounded, nonblocking status messages over the
existing supervisor pipe. It performs no auxiliary evidence-file reads, appends,
recovery-journal inspection or path resolution. Status production is limited to
one update per second, with safety-stop updates bounded by the supervisor's
100 ms loop; at most one pending packet is retained, with a 30 KiB
summary budget and explicit omitted-device count. The primary consumes at most
64 KiB per poll and limits its printed suffix to 512 characters. Absent or stale
status never establishes activity. Full per-drive observations remain in the
supervisor's evidence files. The supervisor also owns `stage_monitoring.jsonl`,
with at most 1,024 interval observations plus a safety-transition observation
per activity window; no primary-thread append is needed. File publication failures stop the auxiliary runner;
they do not delay primary telemetry or enter primary failure reasons.

Terminal-file reading, recovery-latch publication, adapter publication and
whole-run auxiliary file publication run in separately supervised, descriptor-free
Python helpers after the primary metric endpoint. Each has a two-second deadline
and a bounded post-KILL observation window. An unkillable helper remains tracked;
further evidence-helper launches are refused until it is reaped. This cannot
provide an instantaneous-stop guarantee for uninterruptible kernel I/O. Such a
helper receives no device descriptor and cannot perform thermal I/O. Missing or
failed terminal/publication evidence remains an independent auxiliary ERROR.

The [recovery journal](../Modules/lvs_storage_thermal_recovery.py) uses a permanent
`storage_thermal_recovery_required.json.scope` flock anchor and a versioned JSON
journal beside it. All production LVS stage supervisors and the standalone entrypoint use the
same scope. The standalone menu uses the same journal around its unchanged
authoritative runner; it cannot bypass unresolved stage ownership.
The independently owned flock is held throughout startup, target acquisition,
execution and cleanup. Before initializer permission or any native launch, the
supervisor publishes and verifies an ARMED execution intent containing its PID,
unique token, evidence directory and primary lease identity. Journal file contents,
replacement directory entry, anchor and newly created directory entries are
fsynced before admission. Failure to establish that protection refuses auxiliary
execution; CPU/GPU/RAM validation continues.

SIGKILL releases the flock but leaves ARMED ownership unresolved. A missing or
corrupt journal beside the anchor, an orphan journal, inaccessible state, an active
owner, legacy recovery marker or unresolved intent blocks future storage work.
Only confirmed native cleanup, no retained runner claims, and successful terminal
publication permit CLEAN publication. CLEAN is an explicit cleanup certificate,
not deletion: neither anchor nor journal is automatically removed. A later clean
run may acquire the same scope and arm a new token. A failure before replacing
ARMED leaves the obligation intact. If a directory fsync fails after CLEAN has
become visible, cleanup was already confirmed; the operation still reports its
publication failure. No unsafe ownership is cleared merely to hide an error.

These guarantees require local Linux flock/fsync/atomic-rename semantics, a
filesystem honoring durability requests, and trusted ownership of the journal
path. First deployment has neither file and must initialize both before I/O.
External deletion of both files, storage rollback, malicious administrators and
filesystems that dishonestly acknowledge durability are outside this protocol.
The journal does not grant any device capability and cannot enable active-drive
execution. Intent is armed only after checking that its destination is not a
selected target. Manual recovery must independently establish that all old
workers and exclusive descriptors are gone; stale PIDs alone never clear ARMED.

Successful stage and whole-run outcomes now use the standalone strict device
success contract. Every executed identity must uniquely match a requested,
selected, eligible readiness identity and a successful terminal record. Reads,
duration, identity, provenance, guard, cleanup and terminal publication must all
be supported. Contradictory PASS/WARN records retain their raw evidence and gain
explicit `evidence_errors` plus auxiliary ERROR. Legitimate blocked coverage can
produce COMPLETED_WITH_WARNINGS when the eligible subset succeeds; zero-rate
skips and disabled/unavailable work do not invent executed devices. Primary
hardware-validation verdicts remain independent. Established analysis-intent and
telemetry-quality requirements continue to determine whether primary performance
claims have sufficient evidence; no blanket sample threshold is introduced.

New regressions exercise blocked three-second reads/publication/persistence
against two-second primary stages with real telemetry callbacks, cancellation,
malformed/stale snapshots, ENOSPC, independent process contention/restart,
SIGKILL after native policy-test admission, missing/corrupt state and contradictory
terminal success. These are software/synthetic checks, not physical thermal,
interference, active-storage or 28-drive scalability acceptance.

### Six-finding follow-up: process creation, channel and authority boundaries

The optional [owned launch bootstrap](../native/storage_thermal_launch.c), wrapped
by [the Python owner](../Modules/lvs_storage_thermal_launch.py), is prepared and
provenance-recorded during readiness, outside primary timing. It supports Linux
x86-64 and AArch64. Unsupported or unavailable preparation has no synchronous
Popen fallback. The native parent returns an owned PID without waiting for the
child's exec/error pipe, filesystem setup, interpreter loader or startup. The
child closes unapproved descriptors, establishes an isolated process group and
waits on an ownership gate before continuing. Python registers the PID before
releasing that gate. A parent-death signal, native monotonic deadline and bounded
TERM/KILL/reap supervision cover partial startup. Exceptions retain any created
PID. The bootstrap receives no target device descriptor; the existing native v2
admission and guarded fio path remain the sole device-access authority.

This removes the demonstrated pre-exec delay from primary execution and includes
helper creation in the evidence-operation deadline. It does not promise hard
real-time kernel process creation, instantaneous termination of uninterruptible
I/O, or progress on a wedged host. Failed/unreapable helpers remain tracked and
prohibit subsequent helper launches. No background Python thread is abandoned.
Preparation requires the existing compiler machinery; the launch bootstrap does
not grant privileges or change the standalone storage I/O engine.

Both pipe descriptors now have kernel O_NONBLOCK set. Partial writes, EAGAIN,
EINTR and EPIPE have explicit handling. Live status keeps one pending packet of
at most 30 KiB and records dropped updates, partial writes and peer closure.
Critical ownership, completion and cleanup records use the separately supervised
file-publication path. Primary polling reads at most 64 KiB, processes at most
32 packets and retains at most 64 KiB of incomplete input. Initial configuration
is bounded at 8 MiB. READY is single-shot: a duplicate is a protocol fault, closes
admission and stops that auxiliary peer; it cannot append repeated RUN responses.

Recovery ownership is held by a private flock-bearing open file description and
a duplicated lifetime reference. The public transport descriptor and the probe
are independently opened descriptions, not lock owners. Identity is checked
against the original anchor inode, but is not treated as proof of lock ownership.
Before ARMED, admission checks and CLEAN, independent nonblocking probes must
conflict and both private references must prove compatible ownership. Public
same-inode close/reuse therefore cannot release the real lock. Replacement of a
private working description or explicit lock loss rejects authority without
reacquisition. Ambiguous references are retained, not closed as though cleanup
were proven. Inherited Python scope objects reject use in another process.
CLEAN additionally requires an explicit confirmed-cleanup certificate; it never
means that arithmetic or activity evidence passed. These are trusted-process
capabilities, not protection against arbitrary code closing/unlocking all private
references or an administrator replacing the recovery directory.

Each active stage completion must match the primary's execution context: unique
session ID, run directory, stage ID, timing bounds and original lease identity.
Current readiness and effective configuration are authoritative; embedded old
readiness cannot authorize another device. Device PIDs must reconcile with the
current committed ownership records and their admission timestamps. Stale or
contradictory evidence is retained under `rejected_terminal_evidence`, marked
with `session_errors`, and reported as auxiliary ERROR. Its claimed activity
cannot prove current exercised coverage or current cleanup. Matching, independently
confirmed current ownership cleanup can still resolve recovery after an evidence
error; workload success and resource cleanup remain distinct.

Observed process IDs, exits, reads, guard records and native ownership take
precedence over aggregate `requested=false`, BLOCKED or `execution_started=false`.
Such declarations cannot erase a failed execution as NOT_RUN. This rule applies
through device, stage and whole-run auxiliary reporting, without changing primary
hardware verdicts. The six new regression groups use disposable files, pipes and
independent processes, including the exact descriptor-reuse attack and delayed
creation. No physical-drive, heating, interference or active-storage acceptance
is established by these tests.

### Authoritative terminal acceptance and run registration

`validate_terminal` in the shared result module is the common acceptance policy
for the active session, normalization and whole-run export. It retains the strict
per-device success contract and adds timing, registry and current-run binding.
Validation errors remain auxiliary ERROR with raw observations and detailed
reasons; primary hardware verdicts and artifact publication remain independent.

Each successful device needs measured fio `active_seconds`, its configured
duration, finite ordered worker timestamps, successful terminal flags and activity.
The configured duration cannot exceed current authorization. fio runtime must
complete that effective duration; a boolean `duration_completed` is insufficient.
A 100 ms allowance covers parent observation/rounding, not missing fio runtime.
Reported active work must fit the authorized window, including primary-observed
revocation. Process completion may include the existing five-second exit allowance,
but that allowance does not authorize five more seconds of claimed read activity.
The parent terminal-observation time rejects future completion timestamps.
Shortened authorized work must explicitly report reduced coverage and produces
COMPLETED_WITH_WARNINGS; consistent early cancellation remains STOPPED. The
existing primary metrics, thresholds and normalization are unchanged.

Native ownership is reconciled for every bootstrap: unique PID, commitment phase,
descriptor offer, process group readiness, guard PID, exit code, reaping and cleanup.
A failed extra bootstrap cannot vanish behind successful devices. Device/native
exit disagreement rejects success. The independently published final ownership
file is read alongside terminal evidence by the bounded evidence helper and must
match the terminal registry. Matching failed device/worker records can truthfully
report partial execution: aggregate ERROR with individual successful work retained.
Confirmed cleanup remains separate from successful activity.

The primary creates an in-memory run authority with a fresh UUID before execution,
using a context-local scope. Each actual StageWindow is registered once with its
primary-established session context, readiness and terminal observation. Export
uses those registrations, the current run directory, stage timeline and session
identity; supplied JSON is never a registration authority. Several earlier stages
of the same run remain valid. Repeated windows/sessions, previous runs (even at the
same directory), missing registrations and changed configurations become auxiliary
ERROR. Raw rejected payloads remain available. Scope teardown drops registrations;
restart/offline data cannot self-authorize as a new current run. This adds no
recovery database and does not change the durable ARMED/CLEAN or native v2 lease
protocols. Registration and validation occur outside primary timed polling.

Owned-process signaling now excludes concurrent signaling/reaping without waiting
on a contested lifecycle lock. A reaped owner never signals its old PID/PGID.
Where supported, pidfds identify the original child and pidfd-based wait inspection
detects foreign reaping. Group signals require a still-owned, unreaped child, whose
PID remains reserved. The fallback requires the owner API to be the sole reaper;
external numeric-PID reaping is unsupported. Lost or ambiguous ownership refuses
signaling and retains existing uncertain-cleanup protection. Tests simulate numeric
PID replacement with a disposable child; they do not claim a real kernel PID-reuse
exploit or physical-device acceptance.

Reporting-error fallbacks are monotonic: explicit auxiliary ERROR or failed
publication integrity cannot normalize into NOT_RUN merely because worker data
is absent. This applies to whole-run fallback records as well as normal terminals.

`launch_requested_monotonic` records the supervisor's timestamp immediately
before launch; `started_monotonic` remains its later observation of the returned
worker. A delayed ownership publication can separate those observations while
fio is already running. Runtime reconciliation therefore uses the launch interval
and, for stage work, the independently published native commit as the earliest
possible read start. It does not shift primary timestamps or pretend the parent
observation was the actual first I/O. fio runtime, native admission, end observation
and the bounded authorized interval must still agree.

The pidfd branch also binds its handle to the child's kernel identity. It uses
pidfds only when repeated opens for the child have a stable identity distinct
from the parent; otherwise the sole-reaper fallback applies. Signal/reap operations
hold a private duplicate, validate it against the creation identity and use that
same reference for pidfd syscalls. A reused public descriptor cannot redirect the
signal. Regression coverage uses a separate installed pidfd-capable interpreter
when the main test interpreter lacks those APIs, including substitution before
and during the operation. This does not authorize unrelated descriptor closers or
foreign reapers inside the owner's private critical sections.
Run-directory bindings use the same lexical absolute-path normalization as the
primary session, including `..` components; registration does not add filesystem
resolution or symlink walks to primary timed execution.

### Adversarial evidence and cancellation hardening

Cancellation recognition closes the original native admission lease before
operator callbacks or primary-worker shutdown. This fast barrier performs no
worker waits, reaping, journal publication, or auxiliary filesystem work.
Already committed admission remains owned and is reconciled during bounded
auxiliary shutdown. The native v2 OFD synchronization and deadline remain the
admission authority; requesting closure does not retroactively revoke an
already committed launch.

Terminal acceptance reconciles the independently published native ownership
registry with the current primary-owned session registration. Missing terminal
rows cannot establish NOT_RUN when the independent registry proves execution.
Rejected child evidence cannot certify cleanup: cleanup requires consistent,
reaped independent ownership evidence and no observed recovery blocker.
Uncertain cleanup retains the recovery obligation.

Terminal and whole-run acceptance share root contract/type validation,
configuration and duration reconciliation, native protocol checks, raw guard
witness checks, and source endpoint comparison. Explicit ERROR and STOPPED
outcomes cannot become successful completion. Verification booleans cannot
supersede contradictory guard witnesses. These are evidence checks, not claims
that child-produced assertions independently prove kernel enforcement.
Whole-run submission must account for every registered stage; an omitted
registered window is retained as auxiliary ERROR with its historical evidence.

Owned auxiliary processes retain a frozen creation PID/group identity separately
from the public diagnostic PID. Signaling pins and validates the pidfd when
available, and reaping uses `waitid(P_PIDFD)` where supported. Group signaling
uses only the creation group while the original child is verified unreaped.
The older-runtime fallback requires sole-reaper ownership under a nonblocking
lifecycle exclusion; lost reaping or pidfd authority fails closed. No group
signal is issued after confirmed reap. Arbitrary external reaping is outside
this ownership contract and is detected as lost authority, not repaired by
signaling an uncertain numeric PID.

Synthetic regressions replay the original 94 contradiction cases, add omitted
independent ownership and contract-header cases, exercise actual primary
manifest publication, and reproduce cancellation during delayed primary
shutdown. These checks establish software behavior only; physical heating,
power-loss durability and active-storage support remain unaccepted.

### Final-disposition and workload-authority correction

All coordinator signals, including pre-RUN cancellation and timeout escalation,
use the owned-process lifecycle. The diagnostic `pid` and legacy numeric-group
hooks confer no authority. Post-window group-cleanup observation uses the frozen
creation group; a potentially reused group can cause conservative uncertainty,
never an unverified signal. Lost pidfd/reaping authority keeps recovery protection.

Primary registration now snapshots a final disposition generation, the validated
auxiliary result and its material finalization evidence. This includes parent
errors, publication integrity, interruption, ownership, cleanup and persistent
recovery observations. Whole-run publication reconciles supplied summaries against
that snapshot. Replaying an earlier same-stage success cannot erase a later parent
ERROR or cleanup obligation. Rejected submissions remain diagnostic evidence;
repeated publication does not recursively wrap the same rejected record.
Missing/duplicated final dispositions fail closed. Valid STOPPED, partial-coverage
and multi-stage results retain their distinct outcomes.

The shared device validator binds the effective read size and complete resolved
`thermal_pilot_v1` rate record to primary-owned readiness. Recorded guard/fio
arguments, when expected by readiness, must agree with those settings and worker
identity. Configured IOPS/bandwidth are limits, not required achieved performance:
slower successful reads remain valid. V1 has no child-authorized adaptive-rate
protocol. A reduced intensity/rate must be authorized in the effective plan before
admission, including existing per-drive and run-local overrides. Shortening the
remaining stage duration preserves its authorized read size and rate.

Readiness captures the complete execution-source identity outside primary timing;
changes before execution invalidate readiness. Successful terminal records require
matching parent/readiness, root-initial and device source identities. The redundant
root endpoint is optional for v1 derived records; when present it must reconcile
with the same authority. Omitting it never excuses a contradictory initial source.
Git metadata, build timestamps and optional source metadata are not required to
exist; supplied scope/algorithm/file-count identities must not conflict. Source-tree
hashes are distinct from fio and guard executable hashes, which remain separately
bound to readiness and their recorded native witnesses.

Synthetic tests reproduce both coordinator wrong-target paths, finalization ERROR
replacement through the real publisher, unauthorized read sizes/rates and source
contradictions. They retain all prior matrix cases and native admission/recovery
checks. They do not establish physical heating, power-loss durability, active-drive
support, actual kernel PID reuse, or 28-drive platform acceptance.

### Production lease round-trip and native-worker ownership

The kernel lease identity has one JSON representation: a two-element list of
nonnegative, unsigned 64-bit integers, in `(st_dev, st_ino)` order. The primary's
immutable tuple and an equivalent JSON list normalize to those exact integers;
booleans, strings, wrong lengths and out-of-range values are rejected. Recovery
read-back verifies this canonical record. In the stage worker, the record is also
bound to the live `SharedAdmission` authority, including its private original-inode
reference; a different well-formed identity cannot substitute for that authority.
The native v2 admission lock and identity protocol are unchanged.

Native workers now use the same `OwnedProcess` lifecycle as their coordinator.
Creation registers the private owned handle before releasing the native launch
bootstrap. A native-stage launch initially remains in the supervisor group so the
existing guard can perform its required `setsid()` after OWN. Before descriptor
offer, its R acknowledgement must reconcile with the live, unreaped creation PID
and isolated group. Before that acknowledgement, cancellation signals only the
owned child, never the supervisor group. Afterwards group actions remain bound to
the unreaped immutable leader. pidfd-backed signal/reap operations are used when
available; the documented sole-reaper fallback retains the original child identity.
No group signal is issued after the leader has been reaped.

The registry keeps an independent private handle for every created native worker,
including failed registration and failed admission. Mutable public PID diagnostics,
caller-replaced handles, cached public status and omitted public rows cannot prove
cleanup. The runner delegates native polling, termination, PID reporting and group
cleanup to that registry. Ambiguous ownership preserves the exclusive target claim
and ARMED obligation. CLEAN requires confirmed owned-worker/descendant cleanup,
confirmed lease revocation, and the existing durable publication/read-back checks.
A lost authority may conservatively require recovery intervention; no guessed PID
is used to clear it. Standalone execution retains its existing process policy.

Production-entrypoint regressions use a genuine lease and synthetic eligible
readiness, forbid all target opens, verify durable ARMED before the admission gate,
and inspect CLEAN or unresolved ARMED from independent fresh processes. Separate
native policy-test fixtures use disposable regular files and exercise OWN/R,
admission, read-only restrictions and public-PID substitution on pidfd/fallback
paths. These establish software behavior, not physical-device acceptance, actual
kernel PID reuse or power-loss durability on every filesystem.
