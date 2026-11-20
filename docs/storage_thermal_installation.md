# Routine trusted Thermal Assist installation and updates

Use the original checkout and its Wave 1 managed `.venv`. `./setup.sh` option
**9 — Trusted Thermal Assist installation/update** provides metadata-only
readiness and unprivileged preparation. Option 7 and normal LVS dependency
reports also show service compatibility, permission and recovery diagnostics.
No operation automatically invokes sudo, downloads packages, starts a workload
or changes profiles. The separate LLM environment is not an LVS dependency.

## Normal workflow

1. Use `./setup.sh` to verify/repair this repository's environment and check
   dependencies. Stop LVS runs before maintenance. Preparation shares Wave 1's
   maintenance lock and uses the existing native helper build commands.
2. Obtain an ordinary qualified fio **3.42** executable through an independently
   approved distro/source-build workflow. A version string or a locally computed
   hash alone is not release verification. Nothing is automatically installed.
   Import the reviewed executable and its approved SHA-256 once. The durable
   repository-local `build/thermal-runtime/fio` cache is reused on later updates;
   temporary research tools and a separate execution workspace are not required.
   A mismatching cached tool is rejected, never silently replaced or downgraded.
3. Choose setup option 9, then preparation. Supply the approved execution-source
   fingerprint; for the first import also supply fio's path and approved hash.
   Preparation produces the complete versioned source/tools snapshot, native
   build evidence, checksum list and administrator handoff. No manual bundle
   assembly is needed. Source changes require a new approval. Git state is
   recorded honestly; a dirty/unversioned preparation is not claimed to be an
   approved committed release.
4. An administrator independently reviews the source identity, tool approval,
   compiler/build evidence and generated identities, then authorizes promotion.
   The installer is a small standalone standard-library program. Bootstrap it
   once into trusted libexec, and verify its independently approved SHA-256
   **before executing it as root**. Do not sudo the repository, `.venv`, an
   arbitrary interpreter or a user-writable script. Later updates reuse the
   approved root-owned installer; changed installer bytes require fresh review.
5. The installer stages and verifies the complete root-owned deployment, runs
   regular-file native-policy/component checks, provisions the private worker,
   promotes the fixed service unit, checks authenticated component health and
   only then permits workload admission. It enables the metadata/session service
   for normal restart/boot. Starting this service does not authorize any workload.
6. Restart an already running LVS frontend after promotion. Use normal CLI/TUI,
   Advanced Debug and run-local O / Stage Overrides. Source/bootstrap mismatch
   is auxiliary unavailability, never a primary hardware failure or an arbitrary
   repository-executable fallback.

Noninteractive unprivileged equivalents:

```sh
./setup.sh --thermal-check
./setup.sh --thermal-prepare --approved-source APPROVED_EXECUTION_SHA256 \
  --fio /absolute/path/to/approved/fio --approved-fio-sha256 APPROVED_FIO_SHA256
# Subsequent preparations reuse the qualified local tool:
./setup.sh --thermal-prepare --approved-source APPROVED_EXECUTION_SHA256
```

Preparation prints the actual bundle, manifest/checksum-list digests, installer
identity and promotion command, also retained in
`build/thermal-runtime/approval.json`. This is approval **material**, not a
self-issued trust certificate. The tool version, exact bytes and approved source
must have independent provenance. A capable but unqualified fio version remains
unsupported for this provider, with an actionable dependency failure.

## Administrator boundary

Initial bootstrap requires inspecting `/usr/local` and `/usr/local/libexec`
ancestors: real root-owned directories, no group/other write permissions and no
symbolic links. If libexec is absent, create it only beneath a verified safe
parent. Never repair unsafe ownership blindly. Copy the approved installer to a
new root-owned temporary name with mode 0755, compare that installed copy against
the independently approved SHA-256, then rename it into place. A mutable source
copy is never executed as root before checking the copied bytes.

After bootstrap, the generated handoff uses the following fixed interface (use
the actual quoted bundle path and approved manifest digest):

```sh
sudo /usr/bin/env -i PATH=/usr/bin:/bin HOME=/root LC_ALL=C \
  /usr/bin/python3 -I -B /usr/local/libexec/lvs-thermal-install.py \
  --approve --bundle '/absolute/prepared/path' --manifest-sha256 APPROVED_MANIFEST_SHA256
```

There is no arbitrary privileged executable/configuration override. The installer
checks its own ownership/ancestors and actual isolated system interpreter. Source
components are opened with pinned directory descriptors and `O_NOFOLLOW`, copied
with bounded sizes, checked against approval and durably staged. Unexpected
entries, links, changed bytes, insufficient dependencies and unsafe existing
installations fail before promotion. No privileged compiler runs.

Supported routine supervision is native-host **systemd 235 or newer** (the
`RuntimeDirectoryPreserve` capability is required), with a trusted system Python
meeting the shared Wave 1 minimum. The privileged service never borrows a
user-writable venv interpreter. The fixed unit remains
`lvs-thermal-UID.service`; source versions live under `/opt/lvs-thermal`, and the
operator remains the same authenticated non-root UID/GID. Other init systems can
continue the previously reviewed manual session workflow; routine promotion for
those managers is not claimed qualified. Read-only/image-based Linux is supported
only where `/opt`, `/etc/systemd/system` and canonical `/var` state have their
normal administrator-writable, root-owned backing. No image/package changes are
made to manufacture these prerequisites.

The dedicated `lvs-thermal-worker` account is created using the distro's existing
`useradd`: system UID, private group, locked password, non-login shell, no home,
no supplementary groups, no disk-group membership or device permission changes.
An unsafe pre-existing account is refused. Only its UID/GID are inserted by the
trusted installer into the installed manifest; approved source/tool bytes remain
unchanged. Guard/fio execution remains descriptor-bound and restricted. The
normal frontend and primary workloads never become root. System-drive execution
still needs separate explicit session-bound authorization; installation grants
none and does not alter saved profiles or rate ceilings.

## Update, interruption and recovery

Prior deployments are retained. Validation occurs before stopping the previous
service. The installer captures and verifies the previous trusted deployment and
normalizes its supported service command; it does not replay arbitrary old shell
commands/environment assignments. Each promotion has a root-owned durable
installation transaction. A failed promotion restores the previous unit/service
when recovery authority permits. An interrupted transaction blocks new workload
admission, even if its new service process exists; metadata health remains
available for diagnosis. Explicit administrator rollback is:

```sh
sudo /usr/bin/env -i PATH=/usr/bin:/bin HOME=/root LC_ALL=C \
  /usr/bin/python3 -I -B /usr/local/libexec/lvs-thermal-install.py \
  --approve --rollback OPERATOR_UID
```

This uses the same canonical gate; it is not an ARMED recovery-reset command.
Installation and rollback never clear, rewrite or replace the workload journal
or its never-unlinked anchor. Active ownership, ARMED, corruption, missing journal
beside an anchor or uncertain shutdown blocks promotion/rollback. The previous
installation remains on disk for inspection. Resolve actual ownership using the
existing recovery procedure, not by deleting markers or choosing another scope.

The qualified systemd fixture uses unified cgroup v2. A nonempty cgroup on an
unrecognized hierarchy cannot establish quiescence; promotion stops rather than
guessing where processes went. An authoritative empty manager group remains
distinct from unknown membership. Other hierarchy configurations need targeted
qualification when this gate is required.

An idle crashed service can leave a stale socket. Reconciliation requires the
known service to be stopped, its cgroup empty, canonical recovery acceptable,
root-owned endpoint identity and kernel `ECONNREFUSED`. A live or uncertain
listener is refused. The unit declares a root-owned 0755 runtime directory and
preserves it across stops; sockets remain 0660. This incorporates the established
`UMask=0077` traversal correction without changing device or journal permissions. No guessed PID is signalled and no unknown endpoint is
blindly removed. Installers serialize with a separate stable installation lock;
operators must not concurrently issue manual service changes or external updates.

The installer does not change `fs.suid_dumpable`. The new trusted final-exec
hook sets and locks worker nondumpability before receiving a target capability,
including on a policy-2 host. System access still requires the dedicated identity,
unreadable fio and a successful actual final-exec capability check. The original
2ee5db0 qualification correctly reported system access blocked under policy 2;
that historical evidence is preserved. The separately qualified new mechanism
is described in [the confidentiality contract](storage_thermal_confidentiality.md).

Fixed installation locations can resolve through verified root-owned OS aliases;
all executed paths remain canonical, root-owned and free of writable ancestors.
The generated administrator handoff uses the canonical libexec location. On the
reviewed Bazzite host these roots resolve to `/var/opt` and `/var/usrlocal`.
Unsafe aliases are refused, never repaired blindly.

The canonical scope remains `/var/lib/lvs-thermal` across versions, standalone
and integrated operation. Installation state is separate from cleanup authority.
ENOSPC/EIO or interruption cannot turn uncertain workload ownership into CLEAN.
A lost root filesystem or uninterruptible hardware I/O may prevent recovery or
rollback from completing; retaining explicit uncertainty is the safe outcome.

## Qualification and remaining acceptance

Use sealed `encrypted-install` and `encrypted-install-systemd` campaigns in the
existing QEMU harness. They contain writable private images, a separate system/
control volume and mounted encrypted Btrfs data partitions. Temperatures/primary
stress are synthetic; installed service, worker account, descriptor opener, fio,
native admission, elapsed timing and canonical recovery are genuine. The former
has a controlled supervisor adapter for fault injection; the latter boots actual
systemd PID 1 and exercises the real unit-manager commands. Raw evidence must
identify which supervisor produced each observation.

Accepted Samsung physical evidence is preserved and is not repeated for installer
qualification. Physical system-drive/simultaneous-drive testing requires separate
runtime approval and explicit target/session authorization. Broader percentage
calibration, other media, scalability and definitive throughput-interference
acceptance remain open. Genuine primary verified-work instrumentation is the next
separate workstream; memory allocations are not bandwidth measurements.

## Completed software qualification

The final 394-file execution snapshot
`bb047cacbd254121720eb3d05ea46880353cc394d4b6e5b08e0a29a31df56feb`
passed 499/499 complete smoke checks, including the four installation groups.
The focused campaign passed 133 thermal/research/acceptance groups, retaining
the 112-case evidence matrix. All 81 profiles validated with five unchanged
advisories; 436 Python files compiled and 62 integration imports succeeded.
Native x86-64 safety execution, AArch64 guard/bootstrap compilation, documentation,
import-cycle and whitespace checks passed. Standard profiles and native sources
were preserved.

The final-source VM booted systemd 259.9-1.fc44 as PID 1 under QEMU 10.2.2
with Linux 7.2.9-200.fc44.x86_64 and qualified fio 3.42. It exercised fresh and
repeat installation, migration from the accepted transient 7e9d892 deployment,
rollback/reapply, failed and interrupted promotion, restart, idle service death,
and the actual administrator CLI. Pending promotion blocked admission. A live
committed worker blocked updates without stopping its service. Normal stage-end
cleanup, cancellation and synthetic temperature-stop cases used real installed
service/guard/fio execution against disposable encrypted data storage, with real
primary elapsed timing and telemetry callbacks. Primary commands and temperature
inputs were synthetic; no physical performance or thermal acceptance is inferred.
Confirmed cleanup produced CLEAN and intact fixture hashes. A deliberately
unresolved ARMED record then blocked install and rollback unchanged, including
independent-process recovery inspection.

Approval-pin substitution, special files, unsafe paths/accounts, wrong-runtime
health, failed persistence and unknown cgroup hierarchy have deterministic
regressions. The earlier unrelated Environment Manager test `/proc/PID/stat`
exit race was corrected in the test only; production process handling was not
changed. No host privileged installation or accepted physical campaign was run
again during this qualification.
