# Conventional encrypted data drives and offline physical-test deployment

This is experimental shared-read-only **software qualification**, not physical
acceptance or automatic eligibility promotion. The exclusive inactive-HDD opener,
fixed fio workload, native guard, non-root worker, admission and recovery protocols
are unchanged. Earlier access-method NO-GO findings retain their original contracts.

## Qualified topology

One independently identified internal SATA/SAS HDD/SSD or local single-namespace
PCIe NVMe may have several conventional LUKS1/LUKS2 mappings directly over its
whole device or partitions. Each must have exactly one active `crypt` target,
one direct backing device, no downstream holders, no suspended/inactive table,
and a stable kernel generation and geometry. Mounted single-device Btrfs, ext4
and other conventionally mapped filesystems are not excluded by filesystem name.
One physical inventory row/rate/sensor/worker serves all encrypted partitions.
Reads occur below encryption, without decrypting or selecting user files.

Kernel qualification uses fixed `DM_TABLE_STATUS` **INFO / NOFLUSH** queries on
`/dev/mapper/control`, never `DM_STATUS_TABLE_FLAG`, `dmsetup table`, cryptographic
parameters, key retrieval or key export. Only UUID, major/minor, event and size
are retained. UUID text alone does not authorize a holder. Every normal readiness
revalidation repeats this proof and compares it with the registered generation.
Changes stop further authorized submissions; this does not freeze concurrent
administration or undo already-issued kernel I/O. Privileged hostile topology
changes remain outside the workload sandbox's threat model.

Stacks with dm-integrity, LVM/thin/cache/linear holders, RAID, multipath, unknown
or multiple dependencies, unsupported controller mappings and multi-device
filesystems remain blocked. Plain dm-crypt without a LUKS identity is unqualified.
External and system targets remain blocked. No weaker fallback is provided.

## System and namespace authority

Namespace verification failure is a blocker, with `classification_status` set
to `incomplete`; an unestablished negative system/active classification is null,
not false. Known positive system ancestry is still reported. Native privileged
inspection must see the same mount namespace as PID 1; container markers or
unresolved mounts still block execution.

The protected-path policy has two parts. Mounts containing root and `/var`
remain system backing. Mounts containing **or separately mounted beneath**
`/boot`, `/usr`, `/etc`, `/bin`, `/sbin`, `/lib`, `/lib64`, `/sysroot`,
`/var/lib`, `/var/log`, `/var/cache`, `/var/spool` and `/var/tmp` also protect
all their physical backing devices. These are component-aware relationships:
`/usr-data` does not match `/usr`, nor `/var/library` match `/var/lib`.

Ordinary data mounts beneath `/var/home`, `/home`, `/mnt` and `/media` remain
candidates, subject to the existing topology and monitoring checks. Any other
protected mount on the same physical drive still excludes the whole drive.
Bind/subvolume mount roots do not override the destination's OS role. Resolved
OS aliases participate in the same physical mount proof; root is an exact-only
anchor, not a blanket protected subtree. Overlay backing layers require visible
physical ancestry or the narrowly verified OSTree detached-image proof described
below. Missing required ancestry or unresolved aliases fail closed with incomplete
classification. Swap ancestry remains system ancestry.

## Preparation: no elevated execution or device access

The original repository stays in place. Prepare as the ordinary operator on the
system filesystem, outside the proposed data target. The helper copies only the
execution source scope, verifies its complete fingerprint, builds the accepted
guard/bootstrap through existing native compiler helpers and capability-tests
fio using a disposable **regular file**. No packages are installed, no workload
starts, and unresolved source recovery protection refuses preparation.

The installed `/usr/bin/fio` observed during this task is **3.40**, not the
qualified 3.42 behavior family. Do not substitute it silently. Obtain the normal
upstream fio 3.42 release through the operator's approved source/dependency
workflow, review its identity, then configure/build it **unprivileged on the
non-target filesystem**, using the existing installed build dependencies:

```sh
# In the independently obtained and reviewed fio-3.42 source directory:
./configure
make
# From the LVS repository; replace the ordinary upstream build path:
python3 -B -m scripts.storage_thermal_prepare \
  --destination /var/tmp/lvs-thermal-prepared \
  --fio /var/tmp/fio-3.42/fio
```

The destination must be new. The helper reports the execution fingerprint and
manifest/checksum hashes. Inspect `manifest.json`, `SHA256SUMS`, `launch.py`, the
source/test review and native build evidence before approving promotion. Do not
promote untrusted downloaded executables simply because they report a version.
This reuses normal upstream fio building and LVS compiler/capability checks;
it does not install a parallel dependency manager or reuse temporary research tools.

## Separate operator-authorized promotion (not executed by this task)

For the current host, `/opt` (normally canonical `/var/opt` on an atomic host)
and `/var/lib` must first be confirmed on the system NVMe, not the Samsung data
NVMe. Use a new root-owned deployment directory and one canonical state scope
across deployment versions. Do not run the original/deployed copies concurrently.
Review any existing recovery scope; never migrate past or delete unresolved ARMED.
The original repository, venv and development files remain untouched.

Before any privileged copying or recursive ownership operation, inspect the
existing destination ancestors with trusted OS tools:

```sh
sudo /usr/bin/namei -l /opt /var/lib
if [ -e /opt/lvs-thermal ]; then sudo /usr/bin/namei -l /opt/lvs-thermal; fi
if [ -e /var/lib/lvs-thermal ]; then sudo /usr/bin/namei -l /var/lib/lvs-thermal; fi
```

STOP unless all existing ancestors, including resolved aliases, are root-owned
and not group/other-writable. Do not repair an unsafe existing prefix by recursively
chowning it. Keep this review separate from the following copy step; no user may
be able to replace a destination ancestor during promotion. Missing child directories
are created by `install` only beneath these already verified ancestors.

The following are ordinary OS installation/verification commands. They do not
execute the supplied Python/native code before promotion and verification:

```sh
set -eu
BUNDLE=/var/tmp/lvs-thermal-prepared
DEPLOY=/opt/lvs-thermal/encrypted-data-review
if [ -e "$DEPLOY" ] || [ -L "$DEPLOY" ]; then
  echo "STOP: deployment already exists" >&2; exit 1
fi
sudo /usr/bin/install -d -o root -g root -m 0755 "$DEPLOY"
sudo /usr/bin/cp -R --preserve=timestamps --no-preserve=ownership "$BUNDLE/." "$DEPLOY/"
if [ -n "$(sudo /usr/bin/find "$DEPLOY" -type l -print)" ]; then
  echo "STOP: symlink in deployment" >&2; exit 1
fi
sudo /usr/bin/chown -R --no-dereference root:root "$DEPLOY"
sudo /usr/bin/chmod -R go-w "$DEPLOY"
sudo /usr/bin/install -d -o root -g root -m 0755 /var/lib/lvs-thermal
# APPROVED_SUMS_HASH is the independently reviewed preparation output, not
# a new hash copied from the promoted directory without comparison.
printf '%s  %s\n' "$APPROVED_SUMS_HASH" "$DEPLOY/SHA256SUMS" | sudo /usr/bin/sha256sum -c -
(cd "$DEPLOY" && sudo /usr/bin/sha256sum -c SHA256SUMS)
# Before executing launch.py: inspect this OS-tool output. STOP unless every
# directory/alias in the actual path is root-owned and not group/other-writable.
sudo /usr/bin/namei -l "$DEPLOY/launch.py"
```

The source fingerprint must match the independently accepted commit/report,
and fio/guard/bootstrap hashes must be approved from trusted source/build
evidence. A self-generated manifest or freshly computed checksum alone is not
a trust anchor. `APPROVED_SUMS_HASH` binds **all** promoted bytes, including the
launcher and observer outside the execution-source scope; obtain it only after
that independent review. If those identities cannot be established, stop. No
NOPASSWD rule or general privileged service is installed.

Stop on any discrepancy. Parent directories must also be root-owned and not
writable by another account. Never run `sudo python` against the user-writable
repository/venv, enable disk-group access, chmod block devices or reuse a sudo
password programmatically. Promotion authorizes **the reviewed exact code**, not
arbitrary user code. The launcher rejects extra files (including bytecode),
symlinks, unsafe ownership/modes, changed hashes and arbitrary tool/config/output
arguments. Python uses isolated mode and a cleared environment; worker UID/GID
are the non-root preparing operator. The suite itself is not installed setuid.

## Actual Samsung 9100 PRO: passive privileged readiness first

No eligibility claim is made yet for `wwn:eui.002538a35140ace7`. Its physical
identity must match, all mapped holders must qualify, system ancestry must be
excluded and required sensor evidence must succeed under native-host visibility.
The second physical NVMe remains system-blocked.

After separate authorization for privileged metadata inspection only:

```sh
sudo /usr/bin/env -i PATH=/usr/bin:/bin HOME=/root LC_ALL=C \
  /usr/bin/python3 -I /opt/lvs-thermal/encrypted-data-review/launch.py --check
```

After the checksum/ownership gate and that metadata-only check, inspect the
canonical recovery scope using only the already verified root-owned code:

```sh
sudo /usr/bin/env -i PATH=/usr/bin:/bin HOME=/root LC_ALL=C \
  /usr/bin/python3 -I -B -c 'import sys; sys.path.insert(0,"/opt/lvs-thermal/encrypted-data-review/runtime"); from Modules.lvs_storage_thermal_recovery import blocker; reason=blocker("/var/lib/lvs-thermal/storage_thermal_recovery_required.json"); print(reason or "No recorded recovery blocker; first admission still requires durable ARMED"); sys.exit(bool(reason))'
```

This is inspection, not a CLEAN certificate. Any unresolved, inaccessible or
inconsistent state stops the workflow. `--check` alone reports inventory, not
recovery acceptance. Preparation checks the original source scope; review it
again immediately before promotion, with all old instances stopped, and never
run original/deployed copies concurrently. An unreadable legacy scope requires
separately reviewed recovery inspection, not creation of a fresh replacement.

`--check` reads proc/sysfs, stats endpoints and queries key-free mapper INFO;
it does not open target block descriptors or read temperature values. A separately
approved `--plan` can read sensors and run regular-file native capability tests;
it does not start a physical workload. Select the actual stable ID interactively
before the eventual explicit run confirmation.

The same command **without `--check`** opens the standalone menu only after
separate operator authorization. It fixes qualified fio/guard paths, shared
opt-in, aggregate budgets 128 IOPS / 8388608 B/s, non-root worker identity,
`/var/lib/lvs-thermal/results`, and the canonical persistent recovery marker
`/var/lib/lvs-thermal/storage_thermal_recovery_required.json`. Invalid/missing
budgets or monitoring still block execution. The menu must select individual
`wwn:eui.002538a35140ace7`, ordinary intensity 25%, duration 60 seconds,
required monitoring and approved model-specific warning/stop thresholds.
NVMe's existing policy requests 64 KiB, QD1, 64 IOPS / 4 MiB/s at 25%.
System intent remains 25% but does not authorize system-drive execution.

Before authorizing that first physical run, establish model limits, current and
ambient temperatures, sensor association/resolution, numeric thresholds, owner
approval, native privileged readiness, trusted installed tools, non-target state
placement and a clean canonical recovery scope. Use the existing acceptance
observer and finite screening procedure; shared device-wide writes remain
observations, not automatic proof of workload mutation. No physical run occurred
as part of this implementation. Co-located control-plane support remains future
work for system-drive and single-drive hosts; this initial deployment does not
relax non-target placement requirements.

## Retained software qualification evidence

The final sealed campaign uses QEMU 10.2.2, Linux 7.2.9-200.fc44.x86_64,
fio 3.42, cryptsetup 2.8.8 and btrfs-progs 7.1; TCG, one vCPU, 1 GiB RAM,
private writable images and no host-device passthrough. A separate ext4 NVMe
system and ext4 control disk accompany a 514 MiB data NVMe with two 256 MiB
LUKS2/Btrfs partitions. A separate whole-device LUKS1/ext4 boot mount tests
encrypted system ancestry. Destructive setup is guarded by QEMU identity,
per-session token and unique emulated-device serials; guest disk enumeration
order is not used as physical authority.

The frozen campaign retained at `/tmp/lvs-wave2a-ak6cz3n2` demonstrated:

- One physical worker for the two mounted encrypted data volumes: 640 reads /
  40 MiB over five seconds at the configured 128 IOPS, with WARN as required.
- 144 ordinary encrypted filesystem write/read/fsync cycles; independent
  integrity files in both volumes unchanged after assist and cancellation.
- Cancellation: 318 completed reads, truthful cancelled result, owned cleanup
  confirmed. Eight-second independent supervisor run: 1024 reads / 64 MiB.
- Actual native guard privilege reduction, descriptor handoff and fio execution;
  traced explicit read counts match fio. No observed target write/trim/flush,
  target pathname reopen by fio, or workload-generated file mutation.
- Root/system and encrypted boot rejection; additional stacked holder causes
  eligibility and revalidation failure, with return to service after its removal.
- Root-owned deployment passive discovery, refusal of arbitrary tool arguments,
  and rejection of changed source before application imports.
- Active-overlap primary proxy: 2.000580 seconds, two genuine proc telemetry
  observations. Existing stage timing, cancellation, native admission, recovery
  fault injection and primary publication tests passed separately.

Temperature alone was synthetic. IOCTL tracing uses raw argument mode and data
buffers are suppressed, so encryption-table parameters and file contents are
not exported; the production qualifier requests no key-bearing tables. The
fixture's temporary key exists only on guest tmpfs, is removed before workload
execution, and is not included in the evidence archive. This does not establish
physical heating, sensor correctness, power-loss durability or large-system
performance. The first setup attempts and sandbox-denied tests are retained as
failed/partial evidence, not counted as qualification successes.

Scalability review: eligibility and kernel geometry are established independently
of model/capacity; existing per-media policies, aggregate fio budgets, memory/FD
reserves, worker admission and duration limits remain authoritative. Adding logical
crypt volumes does not add physical workers or multiply a drive's rate budget.
Existing low-resource, missing-monitor, heterogeneous and 28-device planning
regressions remain applicable. Kernel status-query overhead grows with the number
of mappings and must be measured during physical scaling; software acceptance
makes no 28-drive performance claim. Other device-mapper ioctls/architectures that
cannot establish the required INFO proof remain unqualified, without fallback.

The prepared bundle also includes the existing acceptance observer, covered by
its manifest hash, so physical measurement need not import code from the target
repository. After the separately authorized deployed passive inventory has been
retained on the non-target system filesystem, an ordinary-user observer may run
from the reviewed deployment (use a new, approved non-target capture directory):

```sh
cd /opt/lvs-thermal/encrypted-data-review/runtime
/usr/bin/python3 -B -m scripts.storage_thermal_acceptance capture \
  --inventory /var/home/mark/LVS-Physical-Acceptance/inventory.json \
  --device-id 'wwn:eui.002538a35140ace7' \
  --directory /var/home/mark/LVS-Physical-Acceptance/passive --seconds 300
```

This is proc/sysfs-only, without sensor values by default. `--temperatures`
requires separate monitoring authorization. Missing root-process counters remain
explicitly unavailable; do not infer zero overhead from them. If privileged
resource capture is required, obtain separate approval to run this same reviewed,
root-owned helper under the clean isolated Python workflow, with fixed approved
inventory, identity and non-target destination. Do not run sudo against the
original repository or make target permission changes for the observer.

## Required future routine integration

This separate, operator-reviewed deployment is an initial physical-qualification
workflow only. Normal future use must integrate trusted dependency preparation,
the accepted native build lifecycle, privilege handling and CLI/TUI/run-local
profile workflows in LVS itself. Routine profile execution must not require users
to maintain and manually promote a separate deployment. That integration is not
implemented or authorized by this milestone.

## Protected-submount finalization and focused deployment review

The follow-up sealed `encrypted-review` campaign at
`/tmp/lvs-wave2a-avnfo8nn` tests readiness/revalidation rather than repeating the
completed read-workload campaign. Binding either encrypted Btrfs data volume at
`/usr/bin` or `/etc/ssl` marks its physical NVMe as system, blocks readiness and
rejects the prior data registration. Removing the bind restores ordinary data
eligibility. Root and encrypted boot backing remain excluded.

The same guest rejects writable deployment ancestors, writable bundle directories,
writable/unprivileged-owned tools, a substituted tool symlink and extra executable
code. Clean isolated startup ignores poisoned Python/FIO environment variables.
An independently retained approval digest rejects changed checksum metadata;
self-consistent candidate metadata alone is not approval. Confirmed synthetic
cleanup permits CLEAN; unresolved ARMED persists through fresh-process inspection
and prevents a new scope from entering. No physical workload was run in this
follow-up. Existing guarded-read/cleanup evidence remains applicable to the
unchanged backend, guard and native ownership protocol.

The trusted OS promotion/checksum/parent-ownership gate is mandatory **before**
executing the promoted launcher. Checks inside a Python script cannot retroactively
make an untrusted bootstrap script safe. Do not skip the independent approval
or path inspection steps, or treat the launcher as a privileged service for
untrusted callers. Routine integrated privilege support remains future work.

### Atomic-host overlay ancestry

Native-host discovery understands legacy `lowerdir=` lists (including `::`
data-only layers) and modern `lowerdir+=` / `datadir+=` mountinfo options. Layer
separators are parsed before escaped delimiters are decoded. Every visible
metadata, data-only, upper and work backing directory must resolve to a known
mount and physical ancestry. An unknown layer, mount cycle, or conflicting
visible backing mount blocks execution with the mount and layer reason.

On the observed OSTree composefs host, the root's EROFS metadata lower is detached
from the visible mount tree. Its `/run/ostree/.private/cfsroot-lower` name alone
is insufficient evidence. The narrowly supported readonly root requires the
root-owned `/run/ostree-booted` GVariant record, a matching device/inode for the
deployment selected by the kernel `ostree=` argument, and a trusted regular
`.ostree.cfs` image. The deployment is resolved relative to the kernel-declared
object store, not an assumed boot-device name. Both the resolved image and every
data-only object-store layer are mapped independently through visible Btrfs,
partition and dm-crypt ancestry. A relocated image on another physical drive
therefore protects that drive too. Transient roots, absent/mismatched witnesses,
and unsupported representations remain blocked. Decoding uses the host's system
GLib library; a missing decoder blocks this topology without installing anything.

SELinux's kernel virtual filesystem and the standard non-system per-user GVfs
and document-portal export endpoints do not constitute independent physical
mount ancestry. Unknown FUSE filesystems and exports at protected OS paths do not
receive that exemption. Positive system ancestry is retained even if another
mount is unresolved; unknown ancestry still prevents eligibility. Ordinary
`/var/home` data mounts remain distinct from essential OS mounts.

This correction was checked against the workstation's actual mountinfo and
root-owned boot/deployment metadata without sudo, block-device descriptors, or
temperature reads. Ordinary-user namespace visibility is still insufficient for
final native-host eligibility. A newly reviewed, versioned deployment must run
the privileged metadata-only check before claiming the data target eligible.
The previous encrypted disposable-VM workload evidence remains applicable;
this change does not alter the opener, guard, fio, ownership or recovery policy.
