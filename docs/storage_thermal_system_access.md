# Experimental system-drive shared access

This milestone extends the existing descriptor-bound provider. Physical system-drive
acceptance is pending. Existing data/exclusive behavior and provisional activity
ceilings are preserved. No saved profile authorizes a system drive.

## Authorization and support boundary

Use the normal repository-managed `.venv`, CLI/TUI and production run service.
The privileged installed runtime remains root-owned and independently approved;
the interface and primary workloads remain unprivileged.

A run-local O / Stage Overrides setting named **Run-local system authorization**
accepts a complete JSON object:

```json
{"device_ids": ["the-exact-system-physical-ID"], "colocated": true, "swap": false}
```

First configure individual selection, shared read-only opt-in, aggregate budgets
and required monitoring. The system IDs must be a subset of the individually
selected IDs. The setting is an ephemeral attribute, omitted from profile JSON.
It is carried in the effective stage configuration, resolved readiness and current
session/lease; topology generation and worker identity are checked on revalidation
and terminal acceptance. Classification remains `system_drive=true`.

The 25% system intensity remains provisional intent. It is not calibrated drive
utilization or permission to execute. Advanced rates remain bounded by existing
class policy and explicit aggregate budgets.

Conventional direct internal SATA/SAS or qualified single-namespace PCIe NVMe
physical mappings reuse the existing opener. Single-device conventional mounted
filesystems and one-to-one LUKS/dm-crypt ancestry reuse existing proofs. Namespace,
identity, geometry, encrypted dependencies, protected system mounts and composefs
ancestry remain authoritative. Ambiguous RAID, ZFS, LVM, integrity/cache/thin,
multipath and multi-device filesystem stacks remain blocked. Unknown ancestry
never becomes a confirmed non-system or runnable state.

Disk-backed swap needs the additional `swap:true` live authorization. Regular swap
files resolve through their containing filesystem's physical ancestry. Zram is
memory-only only when its authoritative `backing_dev` is `none`; unknown backing
blocks discovery. Swap usage is volatile and is excluded from topology identity;
changing swap configuration still invalidates authorization.

## Confidentiality and trusted execution

System operation requires a separately approved dedicated **lvs-thermal-worker**
account with a non-login shell and a UID different from the operator. No UID is
hardcoded in production. Preparation accepts `--worker-uid` and `--worker-gid`;
it does not create accounts, elevate, install or change device permissions.
Provisioning belongs to the reviewed installation workflow.

The qualified fio file is root-owned, mode 0711 after promotion, and supplied on
its verified descriptor. The trusted post-exec hook establishes and verifies
nondumpability, synchronizes its persistent restrictions across threads and only
then receives the deferred target descriptor. System requests fail without this
proof; host `fs.suid_dumpable=0` is no longer required for the qualified new mode.
The dedicated worker retains no supplementary groups or capabilities. The zero
core limit is defense in depth, not protection against a piped core handler.
See [the post-exec contract and VM controls](storage_thermal_confidentiality.md).
The earlier policy-zero qualification remains historical evidence.
An operator/root administrator's ability to compromise the OS is outside this
boundary. Diagnostic output contains identities/counts, not raw sector payloads
or encryption keys. Raw reads below dm-crypt do not perform decryption.

The native guard's fixed read-only/direct descriptor job, ioctl restrictions,
privilege drop, deadline/admission protocol and no-write rules remain unchanged.
System authorization cannot supply an executable, UID, recovery or privileged
output pathname over IPC. Current source/runtime generation must match.

## Qualified control-plane co-location

A selected system disk may contain the installed runtime, dependencies, canonical
recovery and evidence. This is explicit in the system contract; an independent
physical disk is not a production requirement. Data-only/default/exclusive
requests retain their previous output-location rules.

Keep the same `/var/lib/lvs-thermal` scope and anchor across deployments. Durable
ARMED publication and read-back still precede admission. CLEAN requires confirmed
owned-process cleanup, successful revocation and durable cleanup publication.
Persistence uncertainty remains blocked across fresh processes. RAM-only state,
new deployment directories or deleting markers cannot substitute for recovery.

Control output has a per-request cumulative JSON/progress byte budget derived
from selected count, separate bounded worker-log extents, per-file size limits
and a free-space reserve checked before admission. These are logical output
limits, not filesystem write amplification or bounds on all device I/O. ENOSPC,
EIO or publication errors remain visible. A reported free-space reserve is not a
guarantee that a filesystem cannot subsequently run out of space.

Direct workload writes/trim/discard/flush/cache-control remain prohibited.
Ordinary OS, filesystem, swap and LVS control-plane writes are separate activity.
Existing shared-contract kernel persistence, startup I/O and delayed completion
observations remain applicable. Their original research NO-GO records are retained
under their original contracts.

Auxiliary initialization, supervision and finalization remain outside primary
execution. Actual OS-wide storage failure may impede the whole machine, including
instruction fetch, paging, logging and recovery. Report incomplete or compromised
execution truthfully; do not promise hardware-failure insulation or manufacture
CPU/RAM hardware failures from an auxiliary outcome.

## Qualification and next installation milestone

Use only sealed, writable private-image QEMU fixtures in
`scripts.storage_thermal_shared_probe.py` (`ext4-system`, `encrypted-system`).
They boot the genuinely selected root disk; runtime, journal and provider output
are on that root. The separate control disk retains traces only. Temperatures,
primary stress and selected persistence delays/errors are explicitly simulated;
block reads, service credentials, opener, native guard and recovery are real.

Required gates include unauthorized rejection, busy root, preserved fixture
integrity, real swap-out, confidentiality controls with a core positive control,
cancellation, thermal stop, delayed publication, low-space rejection, persistence
errors, handler death and independent ARMED inspection. Successful ordinary cases
must establish CLEAN. Negative final cases deliberately retain ARMED and never
clear it for the next test.

Physical OS-drive and simultaneous-drive execution require separate authorization.
The existing Samsung data-drive milestones remain accepted and must not be
repeated. Other media, broader calibration, higher rates, verified-throughput
interference and scale remain open.

Next development: integrate verified source/tool preparation, dedicated account
provisioning, trusted installation/versioned updates and service lifecycle with
existing Wave 1 environment/native/dependency preparation. Preserve root-owned
ancestors, operator approval, source matching, old deployments and canonical
recovery. Do not elevate a user-writable repository or `.venv`, install dependencies
automatically, or introduce another temporary execution workspace.

Primary verified-work instrumentation is a separate workstream. Extend existing
CPU progress contracts and define RAM verified/processed-byte counters; do not
infer memory bandwidth from allocation multiplied by pass counts. It requires
integrity, overhead and hardware-scalability review before definitive interference
acceptance.

### Evidence interpretation and limits

The qualification uses QEMU 10.2.2, Linux 7.2.9-200.fc44.x86_64 and fio 3.42.
The encrypted root is a single LUKS2 mapping with a Btrfs filesystem. The direct
root is ext4. Both fixtures use private writable image files, an emulated NVMe
root, one CPU and 1 GiB RAM. The control volume retains traces; the installed
runtime, recovery journal and workload publications are on the selected root.

Core-handler visibility has a positive control. Operator memory, FD, signal and
debugger denials accompany nondumpable execution. The debugger denial alone is
not a complete proof, because strace already observes the worker. Raw trace
payloads are suppressed. Normal root reads, ordinary filesystem activity, real
swap-out and fixture integrity are distinct observations. Short primary windows
can shorten actual auxiliary coverage and produce STOPPED; they do not prove a
full native-duration completion.

Persistence EIO/ENOSPC and slow publication are deliberate software injections.
They qualify application failure handling, not physical media failure, power-loss
durability or arbitrary kernel D-state latency. The handler-death case retains
uncertainty even if the kernel later terminates a worker. A fresh process must
still observe ARMED. An OS-wide stall may prevent monitoring and persistence;
this limitation is not hidden by a successful synthetic timing test.

For one selected drive the cumulative control budget is 40 MiB, with two worker
logs limited to 8 MiB each and an initial free-space reserve of 112 MiB. Budgets
scale by selected physical count; no CPU/core count, model name or disk capacity
is used as an activity proxy. Missing confidentiality capability, inadequate
free space or unresolved recovery blocks admission rather than choosing a weaker
fallback. Existing low/high-resource, heterogeneous-class and missing-capability
regressions remain required. Percentage calibration and physical scale remain
separate from these output bounds.

The next installation task should extend `Modules/lvs_python_environment.py`,
`Modules/lvs_native_helpers.py`, the existing dependency preparation and
`scripts/storage_thermal_prepare.py` rather than create a parallel environment or
installer. It must provision the dedicated account with operator approval,
verify trusted source/tools and ancestors, preserve versioned deployments and
canonical recovery, and integrate normal CLI/TUI service availability. No host
account, deployment or service is changed by this VM qualification.

### Retained software qualification results

The final regression tree passed 495/495 smoke checks, 111 focused groups,
112/112 existing evidence-matrix expectations plus six system-authorization
reader/publication cases, 81 profile validations (five unchanged advisories),
432 Python compilation checks and 57 integration imports. Native x86-64 policy
execution and AArch64 guard/bootstrap compilation passed; the latter retains an
existing musl-header signedness warning. Import-cycle, links and whitespace
checks passed after correcting a static dependency cycle in the new authority
code. The common installed path-ownership policy remains unchanged.

The ext4 and encrypted-Btrfs selected-root campaigns traced 480 and 362 successful
64 KiB root-device reads respectively, plus data-drive/exclusive-HDD regressions.
No target mutation or unchecked worker target-path reopen was observed. Both
performed 4,096 pages of actual swap-out and ordinary root filesystem work.
They demonstrated CLEAN before deliberate final faults, then independently
observed ARMED after injected CLEAN-publication ENOSPC (ext4) or handler SIGKILL
(encrypted Btrfs). Fixture integrity hashes remained unchanged. These are logical
fixture-integrity checks, not comprehensive media or power-loss acceptance.

VM execution predates the dependency-only relocation of the common path validator;
the corrected full suite and direct authority/runtime regressions cover that
relocation. The final source scope is 393 files, fingerprint
`7871a5a3647abdeba15daec3b9f3255b0e88aaffbfc54f10a74f1092c00cbe90`.
Raw VM images, traces, source manifests, fault results and validation logs are
retained under `/var/tmp/lvs-system-qualification` and
`/tmp/lvs-system-qualification`. They are not generated repository artifacts.
