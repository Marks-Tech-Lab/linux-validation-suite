# Explicit legacy service retirement

This is an administrator-approved migration of a recognized routine installation
into the on-demand **data-drive-only** runtime. It is never invoked by setup,
preview, ordinary startup or attempted workload execution. It does not authorize
any workload. The old account, executable tree, results and recovery evidence are
retained. No workstation migration or physical test is implied by VM acceptance.

## Inspection and trust

The standard-library administrator tool is
`Modules/lvs_storage_thermal_migration.py`. Independently review its committed
bytes, then copy that exact reviewed file into a root-owned, non-writable temporary
path. Use trusted OS Python with `-I -B` and an empty environment. **Never sudo the
repository module.** A self-generated checksum is consistency evidence, not source
approval. The normal repository `.venv` remains the LVS frontend environment.

These are separately authorized administrator operations, not commands LVS runs
automatically. After approving the source and protected copy, use:

```sh
# Replace the UID and approval below with the actual reviewed inspection values.
# The reviewed tool has already been installed at this protected path.
sudo /usr/bin/env -i PATH=/usr/bin:/bin HOME=/root LC_ALL=C \
  /usr/bin/python3 -I -B /run/lvs-thermal-migration-admin/retire.py --inspect 1000

# Separate explicit approval for precisely that deployment/generation:
sudo /usr/bin/env -i PATH=/usr/bin:/bin HOME=/root LC_ALL=C \
  /usr/bin/python3 -I -B /run/lvs-thermal-migration-admin/retire.py \
  --retire 1000 --approve-sha256 APPROVED_INSPECTION_SHA256
```

Inspection does not create directories/locks, contact the workload socket, query
sensors, open devices, stop processes or alter recovery. It reads the registered
unit and manager state, root-owned manifest/checksums/source identity, complete
executable inventory, prior installer approval and dedicated worker metadata.
It checks the worker's locked non-login/private identity without retaining its
password field. Root-controlled OS directory aliases such as `/opt -> /var/opt`
are resolved; writable ancestors, symlinks inside executable trees, extra files,
changed bytes, alternate units, overrides and activation triggers are rejected.
Only the routine installer's exact known unit and `active` version-1 record are
supported. Manual, older unregistered or ambiguous installations require separate
review; this tool does not guess a conversion.

The inspection approval includes the operator, deployment/source/tool identity,
record and unit hashes, socket inode, service PID/creation ticks, enablement and
canonical anchor/journal identity. A changed deployment, service generation or
journal before the first transition requires new review. Legitimate later CLEAN
work does not invalidate an already completed retirement; the anchor must remain
the same. It is not a blanket approval for a UID.

## Locks and prerequisites

Every inspection/change uses this global order:

1. Existing canonical `install.lock` (also understood by older installers).
2. Existing `/run/lvs-thermal-on-demand/startup.lock`.
3. Existing, never-unlinked canonical recovery `.scope` anchor.

If the startup lock does not yet exist, holding `install.lock` prevents the new
bootstrap from creating it. Inspection/migration do not create it. New temporary
startup now takes the same installer lock before its startup lock and scope.

Missing, inaccessible, malformed, replaced, locked or ARMED recovery blocks
migration and rollback. A successful command requires the existing anchor and a
validated CLEAN journal with confirmed cleanup. The tool never creates, resolves,
replaces, clears or repairs either. Other privileged runtimes, active legacy
handlers, descendants, escaped worker-UID processes and independent launchers
block the transition. An idle verified legacy main process may be stopped only
after these checks. Kernel/process/root visibility uncertainty blocks it.

## Durable states and interruption

Root-only audit material is retained at
`/var/lib/lvs-thermal/retirements/UID-APPROVAL_PREFIX/`:

| State | Meaning |
| --- | --- |
| `PREPARED` | Original record, unit and exact approval are durably archived; live changes may be pending. |
| `MASKED` | Live record is a non-executable `retiring` marker; enablement removed and original unit replaced with a persistent `/dev/null` mask; manager reloaded. |
| `STOPPED` | Service stopped and complete cgroup/worker quiescence proven. |
| `SOCKET_RECONCILED` | Only the approved socket inode, proven refused and stale after stop, was removed; absence is also acceptable. |
| `RETIRED` | Root-protected live marker and completed audit transaction permit transient startup; legacy unit remains masked. |
| `ROLLING_BACK` | Explicit recovery-gated restoration is underway. |
| `ROLLED_BACK` | Original unit/record restored, service **stopped and disabled**. |

The journal is checked again; it is never treated as migration scratch state.
Audit staging is persisted before publication. Incomplete staging remains root
protected for diagnosis and is not a transaction. A failed or killed operation
never automatically starts or rolls back anything. Repeat the exact approved
retire command to resume `PREPARED` through `RETIRED`; repeated completed retirement
is idempotent. Unknown altered records, audit bytes or units block resumption.

The live retirement marker deliberately omits the older installer's replayable
`previous_unit`/deployment fields. Older installation refuses its phase, and old
rollback cannot replay the archived service. The full original record remains
in the audit directory, not in the old installer's live control path.

Transient startup/service acceptance checks the completed marker, approval/archive
hashes, unchanged canonical anchor and persistent mask. A stopped old service
alone is insufficient. The new service cannot grant system-drive access.

## Explicit rollback limitations

```sh
sudo /usr/bin/env -i PATH=/usr/bin:/bin HOME=/root LC_ALL=C \
  /usr/bin/python3 -I -B /run/lvs-thermal-migration-admin/retire.py \
  --rollback 1000 --approve-sha256 APPROVED_INSPECTION_SHA256
```

Rollback requires independently verifiable CLEAN, no competing transient helper,
valid unchanged old deployment/audit material, approved unit or own mask, and
confirmed cleanup. It can reconcile only the original stale socket. It never
stops an active transient helper to manufacture quiescence and never restarts
legacy service, reenables boot startup or clears ARMED. Restoring service operation
is a separate administrator decision. A rolled-back approval is not recycled for
another retirement; review the subsequent service generation anew. A host root
administrator can deliberately override these protections; this is not protection
against compromised root or arbitrary manual root execution of retained tools.

Account/tree removal and retirement-audit garbage collection are separate future
cleanup decisions, after acceptance of the transient runtime. No automated cleanup
of historical deployment or recovery material is included.

## Qualification

Focused fixtures cover approval changes, scope/lock identity, every durable phase,
ENOSPC/EIO persistence failures, stale/substituted sockets, missing/corrupt/ARMED
recovery and rejection of old installer replay. The sealed disposable systemd VM
uses the accepted `5144e17` installer/runtime, mounted LUKS2/Btrfs data on one emulated
NVMe, and a separate system/control device. It qualifies administrator-process
loss, resume and safe rollback; actual transient guard/fio data reads, cancellation,
repeated use, source generation update, active-client conflicts and idle cleanup.
Temperatures/primary stress are synthetic; guarded data I/O and monotonic timing
are real. This is software migration evidence, not physical thermal or power-loss
acceptance. Actual host migration requires fresh privileged inspection and separate
approval; inaccessible host recovery must never be assumed CLEAN.

Accepted regression evidence: 522 complete smoke checks, nine focused migration
checks, 112/112 terminal/publication matrix expectations, 81 valid profiles (five
unchanged advisories), 449 Python compilations and 75 imports. The final-source VM
completed 208 guarded reads in its normal window and 27 in its cancelled window,
with zero worker writes/discards/flushes/errors and confirmed cleanup. Its timed
synthetic-primary stages lasted 35.127 s (169 telemetry callbacks) and 11.299 s
(56 callbacks, explicitly aborted). Auxiliary shortened coverage remains STOPPED.
After legitimate CLEAN and idle cleanup, a separate deliberately unresolved
RecoveryScope remained ARMED in a fresh process and blocked both rollback and
startup. This final negative control is not described as a cleanup failure of the
successful preceding jobs. A separate short VM proof exercises actual old
installer **and new bootstrap** lock contention without repeating data workloads.

Reproduction uses the existing sealed VM harness and explicit regular-file tool
inputs; no host block passthrough or automatic tool installation is provided:

```sh
.venv/bin/python -B -m scripts.storage_thermal_shared_probe \
  --campaign encrypted-install-migration-systemd \
  --fio /absolute/path/to/approved-fio-3.42 \
  --old-fio /absolute/path/to/system-fio \
  --strace /absolute/path/to/qualified-strace \
  --kernel /absolute/path/to/qualified-vmlinuz --python /usr/bin/python3
# Add --proof-only for the short concurrency/retirement proof without data jobs.
```

Retain the resulting host manifest, private image hashes, exported results and
raw logs. The accepted campaign used kernel 7.2.9-200.fc44.x86_64, native systemd,
unified cgroup v2 and fio 3.42. It tests administrator-process interruption and
persistent mask enforcement; it is not a storage power-loss qualification.

The separately selected [exact ea60 transient-session adapter](storage_thermal_ea60_retirement.md)
handles the older, independently pinned workstation bundle without inventing a
routine installation record or dedicated worker account. It requires
`--historical-ea60`; default newer-generation recognition remains strict.
