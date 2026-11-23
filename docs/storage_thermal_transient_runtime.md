# On-demand Thermal Assist data runtime

This experimental path reuses normal LVS, its repository-managed `.venv`, the
foreground `RunLaunchCoordinator.prepare_execution()` boundary, and the accepted
protected service/guard/fio engine. It creates no permanent LVS unit, boot
activation, installed executable tree or static worker account. It does not
migrate an existing installation automatically.

## Authorization and source approval

Passive profile inspection reads endpoint and native-systemd/tool metadata only.
An absent endpoint can be a startup candidate, not proof of eligibility. Unsafe
existing endpoints remain blocked. There is no sudo, service activation,
subprocess, temperature probe or bootstrap loading during this inspection.

After final confirmation and effective overrides, unprivileged preparation reuses
the existing native build and qualified fio cache. A clean committed execution
source and clean tracked tree are required. No dependency is downloaded or
installed. The frontend presents the commit, execution fingerprint, complete
artifact-manifest digest, fixed-stager digest, tool hashes and build provenance.
New startup requires explicit foreground approval even with a cached sudo
credential. The existing privilege manager handles authentication; passwords are
never retained. CLI/TUI and primary execution stay unprivileged.

**Trust boundary:** the operator must approve independently reviewed source and
qualified tool artifacts. A clean Git tree, locally generated checksums, version
strings or native policy probes alone are not independent approval. This is an
operator-approved bootstrap, not signed-release attestation or protection from a
compromised operator/sudo session. Do not approve an arbitrary checkout. Systems
requiring an externally provisioned trust anchor/signature policy must decline
startup until that approval requirement has been satisfied.

The fixed reviewed stager runs through isolated root-owned OS Python, with no
shell interpolation or arbitrary command option. It does not load or execute a
Python file at a user-writable repository path. It pins source entries with
`O_PATH`/`O_NOFOLLOW`, rejects nonregular files before opening them for data,
bounds paths/counts/bytes, and copies into a root-owned snapshot beneath
`/run/lvs-thermal-on-demand`. Every approved file digest and the exact v1 execution
source fingerprint are verified **before any snapshot code is imported**. Unknown
executable inventory is rejected. Only protected approved snapshot code then
starts the fixed service. The worker cannot replace the snapshot or tool paths.
Failed pre-start copies can remain root-protected beneath `/run` for diagnostics;
they are not installations or cleanup certificates and disappear on reboot.

The legacy `installed_runtime` wire/evidence field name is retained for contract
compatibility; `runtime_mode` identifies this transient provider. It does not mean
a permanent installation was made.

## Supervision and worker identity

On supported native systemd/unified-cgroup-v2 systems, two transient units are
used: a root supervisor and a process-free active identity reservation. The latter
uses `DynamicUser=yes`, a unique name, `Type=oneshot` and `RemainAfterExit=yes`.
No `/etc/passwd` or `/etc/group` entry is created. NSS dynamic identity support is
required; a missing or inconsistent reservation fails closed. The allocated
private UID/GID, source and tools are recorded by trusted root code. This is not
an assertion that the identity unit's filesystem sandbox covers the separate root
service's children: the workers' restrictions are the existing native guard and
post-exec confidentiality filter.

The root service keeps native-host namespace/peer checks, generation-bound IPC,
strict bounded configuration, descriptor-bound read-only/direct access, admission
v2, revocation, immutable ownership and required monitoring. Every worker drops
into the reserved non-root identity, clears groups/capabilities and establishes
locked post-exec nondumpability before receiving the target. No arbitrary fio
arguments, executable override, target-path fallback or writable workload is
introduced. One physical target remains one worker/budget/temperature association.

**Data drives only.** All existing topology/media/transport checks remain.
Temporary identity is explicitly rejected by system-drive authorization, including
requests carrying system/co-location/swap opt-in. The previous dedicated-identity
system-drive qualification does not automatically qualify this alternative.
No global core-dump/security policy is changed.

## Lifetime, evidence and recovery

A run holds an authenticated liveness connection through setup, primary execution
and terminal publication. It conveys no admission or CLEAN authority. Cancellation,
heatsoak failure, metadata failure, normal return and process exit release it.
Active handler/worker ownership prevents idle shutdown. After 30 idle seconds,
with no owned handlers/groups and no canonical recovery blocker, the service exits.
A mapped client bootstrap can be reused after recreation only when its bytes
exactly match the new trusted bootstrap; source and protocol checks remain.

Transient `ExecStopPost` confirms cgroup quiescence and canonical recovery under
the existing never-unlinked anchor. Only then can it remove its protected snapshot
and queue release of the dynamic identity. The release is nonblocking because
systemd's stop ordering places it after root-service shutdown. Unconfirmed group
membership, persistence or ARMED retains protection, snapshot and identity; no
maintenance operation publishes CLEAN. Abrupt death can therefore leave an
intentional unresolved obligation requiring operator review.

The canonical `/var/lib/lvs-thermal` journal/anchor and root-owned session evidence
remain persistent across helper versions and frontend instances. Terminal evidence
is not deleted with `/run` code. Fresh-process recovery continues to block unresolved
ARMED. Missing/corrupt/orphan state never becomes CLEAN through startup or cleanup.
Unclassified stale sockets are refused. A stale socket owned by the just-stopped
transient service is removed only after quiescence, CLEAN and kernel refusal of a
connection, with inode revalidation.

Concurrent startups serialize. Existing matching helpers can serve bounded
concurrent clients; canonical admission still excludes competing owned workloads.
A busy, stale, incompatible or missing component is auxiliary unavailability,
not a primary CPU/GPU/RAM failure. All rate ceilings remain provisional and unchanged.

## Legacy conflict and qualification scope

An existing installer record, installed helper or unknown endpoint is a conflict.
Startup never disables/stops that service, replaces its record or removes its
executables. The workstation's legacy deployment remains untouched. A separately
approved retirement/handoff is the next migration step, after authoritative idle,
cgroup and canonical recovery inspection; deleting ARMED is never a migration.

Disposable writable-VM qualification uses a separate system/control volume and
mounted LUKS2/Btrfs data volumes backed by one emulated NVMe. Guarded data reads,
normal/canceled completion, repeated use, same-frontend helper recreation,
transient cleanup and abrupt-death ARMED refusal are genuine. Primary commands and
temperatures are synthetic; telemetry callbacks and elapsed time are real. Static
account databases and permanent unit paths are checked unchanged. Separate negative
proofs reject inconsistent source before importing hostile snapshot code, invalid
tool-version evidence, legacy ownership conflicts and unknown stale endpoints.
These are software proofs, not physical thermal, power-loss or scalability acceptance.

Ordinary data-drive physical screening through this transport still needs separate
approval. System-drive alternative-identity qualification, authorized legacy
migration, broader hardware/drive classes, calibration/percentage scaling and
multi-drive/definitive interference acceptance remain open. No earlier accepted
Samsung campaign needs to be repeated merely to validate this software change.

Systemd's [dynamic identity contract](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#DynamicUser=)
and [service lifetime/ordering](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html#RemainAfterExit=)
are dependencies, not substitutes for the recorded VM checks.

## Recorded software validation

The qualified execution source contains 400 files with fingerprint
`d5ddddc341e21bbe4bc821bf8af00d82814d5fa5442580f923ba4a5c567fd723`.
The final full smoke run passed 513 checks, including the existing evidence matrix,
native read-only/post-exec checks, ownership and revocation regressions. Four new
focused groups cover passive candidates, explicit source approval despite cached
sudo, fixed startup commands, sealed research clients and run-hold cleanup.

On the final source, the VM's configured 35-second normal stage lasted 35.082
seconds, with 208 guarded reads / 13,631,488 bytes in 26 seconds of actual fio
activity at 8 IOPS. Its STOPPED classification truthfully reports the shortened
auxiliary window. The cancellation case completed 27 reads over 3.375 seconds of
fio activity, with confirmed cleanup. Both had zero worker mutations/errors and
verified guard/provenance. After deliberate supervisor death during reads, the
synthetic primary continued for 35.122 seconds with 169 genuine telemetry
callbacks; the auxiliary outcome was ERROR with unconfirmed cleanup. Fresh
inspection of the durable system-volume journal found ARMED and restart refused.
The private identity and protected runtime remained retained.

A separate concurrent-client check completed 210 guarded reads while a second
unprivileged LVS execution-preparation client was blocked by the active canonical
owner. The original helper PID was preserved; final durable state was CLEAN and
idle cleanup succeeded. Static account databases were unchanged throughout.

Serial Base64/gzip exports for these final VM runs were corrupted and were not
accepted as evidence. Valid records were recovered read-only from the stopped
private regular-file ext4 images using `debugfs`, without mounting or host block
device access. Image/extracted-file SHA-256 manifests and independent durable
journal reconciliation accompany those recovered records. The production VM
verifier passed on both recovered result sets. Raw images and the failed serial
exports remain retained; no conclusions rely on the damaged archives.

The subsequent [explicit legacy retirement tool](storage_thermal_legacy_retirement.md)
provides a recovery-gated, reversible handoff for recognized routine installations.
Startup shares `install.lock` serialization and accepts only a completed protected
retirement transaction with the old unit persistently masked. It does not migrate
or stop an installation itself. Legacy metadata, account and tree remain retained.
