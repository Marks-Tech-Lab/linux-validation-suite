# Exact ea60 transient-session retirement

This compatibility adapter retires the **previously approved**
`/opt/lvs-thermal/integrated-ea60eaa9` generation. It does not authorize its old
worker to run again or extend historical confidentiality guarantees retroactively.
The newer routine-installer retirement path remains separate and unchanged.
No workstation retirement or protected recovery inspection has been performed by
this software qualification.

## Reconstructed contracts and independent byte identity

The authoritative historical source is commit
[`ea60eaa944ff79681150fb2afc641fbc322015af`](https://github.com/Marks-Tech-Lab/linux-validation-suite/commit/ea60eaa944ff79681150fb2afc641fbc322015af),
particularly `scripts/storage_thermal_prepare.py`,
`Modules/lvs_storage_thermal_service.py`, `Modules/lvs_storage_thermal_recovery.py`
and `docs/storage_thermal_integrated_runtime.md`. It is an ancestor of the accepted
repository history. All 392 execution-source files and the external observer
match those committed bytes; the generated launcher matches the committed
LAUNCHER literal. The previously retained independent approval supplies the
qualified fio release/native build identities. This is not approval derived only
from a new self-generated manifest.

| Item | Exact historical value |
| --- | --- |
| Execution source | 392 files, `1e35d99bf3b6b1789e6b4bc6571f4be4357afc8e7269413657e777b8bee8dc53` |
| Manifest SHA-256 | `dffa0d4cf30e1314a9b0d63eb9d4f071004473bc312290d84061e03d0599e7a9` |
| SHA256SUMS SHA-256 | `c3e04bbb37b373b8a7a7db695f5f0ac911dbf2944e567f66199d31f8fab35d1f` |
| Launcher SHA-256 | `ab1640212d259f47969d2813068794172064e98f0af28b659c8d272c4e52a369` |
| fio SHA-256 | `9fb25d8c36e58faf644139806e9c37d6ccd782b536c15f0e592cecc198ef96db` |
| Guard SHA-256 | `4376a903224543399b167ed83e8f845970569631a45ca3daa4bf02fbf3faa78d` |
| Bootstrap SHA-256 | `c7107704953beb802c11e26565c693769d3128bc5f746c6571c0247fd561249c` |

The offline-bundle-v1 manifest has exactly `contract`, `source`, `uid`, `gid`,
`files`, `backend`: 397 declared components plus the manifest and checksum list.
There is **no preparation.json, post-exec hook, installation record or dedicated
worker identity**. These missing later-generation fields are not fabricated.
The entire exact manifest/checksum list and every deployed component are pinned.
Other operators/builds/source variants are not automatically covered merely
because they also say "392 files" or have a similar directory name.

The historical procedure used `systemd-run --collect`, Type=exec, KillMode=mixed,
TimeoutStopSec=45, UMask=0077 and a fixed `env -i ... /usr/bin/python3 -I -B
/opt/lvs-thermal/integrated-ea60eaa9/launch.py --serve-integrated` command.
The unit is a manager-generated fragment under `/run/systemd/transient`, not a
boot-enabled `/etc` unit. Its exact known contents, namespace, manager properties,
no overrides/triggers, kernel listener ownership and PID creation identity are
required. Root-controlled `/opt -> /var/opt` aliases are resolved; the logical
historical command path is still checked. An unexpected permanent unit or live
installation record blocks this adapter.

## Actual historical ownership

`RuntimePolicy.runner()` used the explicit **operator UID/GID from the manifest**.
It did not provision a private system account. The adapter reports the dedicated
worker identity as absent; it never scans that ordinary UID as if every desktop
process were a storage worker.

Instead it requires the root-owned service cgroup to contain only the verified
idle main process (nothing after stop), complete process visibility, and no
independent launcher or pinned guard/fio executable/bootstrap mapping elsewhere.
Mapping identities are streamed and compared numerically, not retained or logged
as user path/content evidence. The workstation demonstrated that Btrfs `stat()`
reported device 65 while `/proc/maps` reported device 38 for the same bootstrap
inode. Those numbers are observations, never hardcoded authority. The tool derives
the kernel mapping token by creating a temporary **MAP_PRIVATE/PROT_READ** mapping
of each verified regular code-file descriptor. It proves the observed range,
permissions, offset and length, then closes it. No code is executed and no target
sectors or user-file contents are read. This is an ownership observation, not a
new filesystem-aware thermal workload. It does not require debugger/map_files
access or host security-policy changes. Potential mapping-identity collisions
conservatively block retirement rather than inventing a confirmed worker identity. An old LVS frontend still mapping that bootstrap
must exit before retirement. Inaccessible observations fail closed. The accepted
historical native restrictions did not permit workers to escape the service
cgroup; the independently locked recovery scope additionally prevents new target
admission during transition. The absence of a dedicated UID is not accepted as a
generic bypass for other generations.

## Explicit operation and rollback

Use the [existing reviewed administrator-tool procedure](storage_thermal_legacy_retirement.md)
with **`--historical-ea60` on inspection, retirement, resume and rollback**. For
example, only after separate administrator approval and a reviewed root-owned
copy of the current tool:

```sh
sudo /usr/bin/env -i PATH=/usr/bin:/bin HOME=/root LC_ALL=C \
  /usr/bin/python3 -I -B /run/lvs-thermal-migration-admin/retire.py \
  --historical-ea60 --inspect 1000
# Review that exact inspection before separately approving the transition.
sudo /usr/bin/env -i PATH=/usr/bin:/bin HOME=/root LC_ALL=C \
  /usr/bin/python3 -I -B /run/lvs-thermal-migration-admin/retire.py \
  --historical-ea60 --retire 1000 --approve-sha256 APPROVED_INSPECTION_SHA256
```

Read-only inspection creates nothing. The old generation did not have install.lock;
on explicitly approved mutation only, a missing root-protected installer lock is
initialized as serialization metadata. The acquisition order remains installer,
existing transient-startup lock, existing canonical anchor. No deployment, unit,
socket or retirement record changes before authoritative CLEAN and quiescence.
Missing/corrupt/inaccessible/locked/ARMED canonical recovery always blocks; no
journal/anchor is created, repaired or cleared. The new coordination lock is
retained after rollback, never unlinked while another process might use it.

The same durable retirement phases and audit directory are used. The archived
`original-record.json` is an explicit **absence sentinel**, not an invented v1
installation record. The exact transient fragment is archived before changes.
After stopping and proving quiescence, only that unchanged fragment is reconciled
so it cannot outrank the persistent `/etc` mask. Manager mask verification remains
mandatory. Unknown fragment/socket bytes or identity changes stop the operation.
The retained installation marker protects the handoff and blocks later installer
replay. No account or executable tree is removed.

Rollback under CLEAN restores **absence** of the permanent unit and installation
record. It neither installs the transient fragment as a permanent unit nor
recreates/starts the old session. The archived command remains available for a
separate administrator decision. Explicit rollback uses the same approved digest
and historical flag. Active new helpers or ARMED obligations block rollback.
Restoring the old running state is deliberately not automatic.

## Qualification and real workstation boundary

The sealed `encrypted-ea60-migration-systemd` VM campaign copies the exact approved
historical regular-file bundle without executing its tools on the host. It starts
the real historical root service in a disposable native-systemd guest with no
permanent worker account; no historical raw workload is requested. The final
fixture places the legacy executable tree on a **separate Btrfs control volume**
to reproduce the workstation mapping distinction without making the selected
data NVMe a system/runtime backing device. It checks
ordinary-operator versus bootstrap-mapped processes, active client conflicts,
interrupted phases, resumption, rollback and serialization. It then uses the
current protected transient provider for genuine guarded reads/cancellation on
mounted disposable LUKS2/Btrfs NVMe storage, repeated readiness, idle cleanup and
source updates. Final deliberate ARMED protection must survive a fresh process.
Temperatures/primary stress remain synthetic; these tests are not physical or
power-loss acceptance.

On the workstation the exact generation is supported **subject to a fresh
administrator inspection** proving ownership, native process visibility, unit and
socket identity, record absence and canonical CLEAN. Current recovery contents
remain unverified. Do not infer them from historical CLEAN evidence. Close old
clients identified by the administrator rather than killing unknown processes.
Any catalog mismatch or unsupported unit variation remains blocked and requires
separately approved evidence/adapter qualification, not a force option.

Final software evidence: 526/526 smoke checks; 13 focused migration groups;
112/112 evidence-matrix expectations; 81 valid profiles with five unchanged
advisories; 449 Python compilations and 75 imports. Native safeguards are unchanged.
The Btrfs-carried legacy VM observed stat device 36 versus proc device 35 for the
same inode, and the derived mapping proof rejected the real mapped-bootstrap
process. It tested both resumption and direct rollback at all five durable phases,
plus an idle-service SIGKILL leaving the approved stale socket. That exact inode
was reconciled after quiescence. Genuine new-provider windows completed 210 reads
normally and 28 before cancellation, with confirmed cleanup and zero worker
writes/discards/flushes/errors. The shortened auxiliary windows remained STOPPED;
primary stress was synthetic and elapsed timing/telemetry were real. Subsequent
intentional unresolved recovery remained ARMED and blocked rollback/startup in a
fresh process. A genuine newer-generation VM control passed; only the historical
mapping proof changed after that control, with default class/functions unchanged.

If fresh administrator inspection fails, retain the precise reason and private
metadata evidence: unit fragment/properties and creation identity, complete cgroup
membership, manifest/checksum/tool hashes, native namespace/ownership checks,
socket inode/listener ownership, and canonical anchor plus CLEAN/ARMED observation
under its lock. Missing or ambiguous evidence is not permission for manual journal
removal, forced cleanup certification or guessing a worker UID. No force flag is
provided. Any manual retirement of an unrecognized variant requires separate
administrator review and explicit authorization.
