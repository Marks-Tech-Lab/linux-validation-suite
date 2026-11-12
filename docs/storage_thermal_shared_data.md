# Experimental shared read-only Thermal Assist for internal data drives

The operator's revised objective prioritizes ordinary internal non-system data
HDDs and SSDs, mounted or unmounted, before physical screening, system drives,
complex stacks and explicitly selected external devices. Default automatic
production eligibility is **not** promoted by this implementation. The existing
exclusive inactive-HDD path remains the default and retains its mutation stops.
No seven-profile/41-stage JSON or primary workload/verdict setting is changed.

## Explicit contract and status

`access_mode="shared_readonly_opt_in"` is a separately named experimental access
contract. It is implemented in the existing resolver/supervisor; there is no new
I/O engine, guard mode, filesystem worker, writable file or arbitrary fio command.
Both standalone and profile-stage configuration use the same validated fields.
Shared mode requires explicit aggregate IOPS and byte/s budgets and reliable
monitoring. There is no unmonitored shared fallback in this first milestone.

The previous [raw-access NO-GO](storage_thermal_active_access_research.md) and
[existing-file NO-GO](storage_thermal_file_access_research.md) remain historical
results under their original contracts. The raw observations demonstrate kernel
writeback, waiting and initialization activity; they do not demonstrate direct
workload data mutation or corruption. The following relaxation is explicit:

| Activity | Shared contract |
| --- | --- |
| fio write/trim/discard, initialization/formatting, flush/cache-control requests | Prohibited; fixed read-only job, descriptor flags and native restrictions remain authoritative |
| Kernel persistence of already dirty whole-device data | May be induced, accelerated or waited upon; not represented as a new application data write |
| Normal filesystem/application writes | Allowed concurrent OS activity; device-wide counters are observations, not attribution to fio |
| Executable/library/provenance and open/close initialization I/O | Included in the footprint; outside fio workload pacing, not hidden warmup or guaranteed zero |
| Performance interference | Must be measured; read success does not establish acceptable interference |
| Submitted I/O that completes late or cannot promptly be interrupted | Possible; finite submission/runtime intent does not guarantee kernel return; bounded supervision and unresolved-cleanup recovery remain required |

**Limits are per-drive and aggregate LVS fio-request budgets, not hard caps on
all device I/O, other applications, kernel writeback or initialization.** Startup
is staggered by one second in shared mode. Resource/FD safety reserves remain
independent from device-class rate ceilings. No CPU reservation is added.
Shared completion is always WARN / COMPLETED_WITH_WARNINGS, even when all intended
reads complete. Heating, hardware safety and physical acceptance remain unproven.

## Implemented selection and remaining restrictions

| Target | Exclusive default | Explicit shared opt-in |
| --- | --- | --- |
| Independently identified inactive internal SATA/SAS HDD | Existing supported path | Software path available |
| Mounted internal SATA/SAS HDD data drive | Blocked | Software path available |
| Internal SATA/SAS SSD data drive, mounted/unmounted | Blocked | Software path available |
| Local PCIe NVMe SSD, one namespace/controller, data-only | Blocked | Software path available |
| Single-device conventional filesystem, including single-device Btrfs | Mounted excluded | Filesystem name alone does not exclude; physical mapping must resolve |
| Root/boot/system/swap drive | Blocked | Blocked: system-specific compatibility remains separate |
| RAID/ZFS/LVM/multipath, multi-device filesystem | Blocked | Blocked or unresolved: separate ownership/mapping/controller qualification required |
| NVMe fabrics, multiple namespaces, virtual/controller RAID volume | Blocked | Blocked: local independent physical-drive budgeting not established |
| External/USB | Excluded | Still blocked; future explicit external opt-in is a roadmap requirement |
| Missing identity, permissions, sensor/threshold, direct-I/O capability or backend | Blocked | Blocked with exact reasons; no weaker access fallback |

Conventional directly backed LUKS mappings are covered by the [encrypted-data qualification and deployment workflow](storage_thermal_encrypted_deployment.md).

System classification resolves essential OS mount ancestry and swap, not broad data-directory prefixes or just the
root mount. Known container/namespace visibility problems and unresolvable active
storage remain blockers. The existing SAS end-device proof is retained. NVMe must
have a real local PCIe controller ancestor and a single namespace; an nvme-shaped
name is insufficient. Multiple namespaces would otherwise independently consume
one physical device's budget. No capacity or model-name performance proxy is used.

Raw physical descriptors identify the actual disk/namespace. Logical-filesystem
traffic is never presented as proven physical-member activity. The resolver uses
existing mount/Btrfs/sysfs topology; it does not scan personal files or write
workload data. Reading a selected physical device still requires operator
permission to read its contents; contents are not retained in reports.

## Descriptor, ownership and evidence boundaries

The exclusive opener still uses O_RDONLY|O_DIRECT|O_EXCL|O_CLOEXEC|O_NOFOLLOW.
Only the explicitly selected shared path omits O_EXCL. Both validate physical
identity, size, sector alignment and descriptor flags before and after acquisition.
Shared readiness additionally binds the canonical device-node inode, rejecting
node replacement even when its WWN and device numbers appear unchanged.

Shared acquisition obtains nonblocking exclusive `flock` on the **canonical block
node's open file description**. It follows the descriptor through duplication,
exec and native transfer, and is released on final close. Independent cooperating
openers of that inode conflict; closing one duplicated descriptor does not release
all references. Failure to lock rejects acquisition. This is advisory cooperation,
not filesystem ownership, not a security boundary against root/noncooperating
programs, and not global coordination across independently created device aliases.
Use one LVS recovery scope/checkout per host; do not bypass an unresolved journal
by launching another checkout or alias. The lock does not certify cleanup or
replace the existing durable journal. See [Linux flock semantics](https://man7.org/linux/man-pages/man2/flock.2.html).

The native guard, fixed descriptor-bound psync randread, QD1, privilege drop,
capability/seccomp/ioctl restrictions, executable pinning and invalidate=0 remain
unchanged. Its block ABI checks O_RDONLY/O_DIRECT and geometry; it does not need
exclusive ownership to enforce those properties. Trusted fio remains required;
this is not a sandbox for hostile executables. No new native proof is asserted.
Standalone shared workers use the existing immutable OwnedProcess lifecycle;
profile workers retain the native v2 admission/lease and ownership registry.
A group-existence utility moved into that lifecycle module to avoid an import
cycle; its behavior is unchanged and its runner import remains compatible.

ARMED precedes workload claims/admission, failed or uncertain cleanup retains
recovery obligations, and no terminal summary can authorize CLEAN by assertion.
Cancellation, deadline/revocation and publication isolation reuse the accepted
stage implementation. Shared inventory and I/O stay in the auxiliary supervisor,
not the primary timed thread. Storage outcomes remain non-gating.

Device-wide writes, discards and flushes no longer automatically abort **shared**
workers. They are retained as background counters with explicitly nonexclusive
attribution. fio's own nonzero write/trim/flush/error evidence still fails the
workload. The exclusive provider retains its device-wide unexpected-mutation
stop. Counter resets/missing observations, identity changes, lost temperatures,
critical temperatures, memory pressure and I/O errors retain their existing stops.

## Invocation and run-local stage configuration

Only disposable-VM workloads are permitted by the integration fixture. Obtain separate approval
for the specific hardware and limits before using these commands on real drives.
Example configuration for one internal data drive (replace ID and set appropriate
model-specific temperature limits; null relies on a valid reported critical limit):

```json
{
  "access_mode": "shared_readonly_opt_in",
  "aggregate_iops_limit": 128,
  "aggregate_bps_limit": 8388608,
  "selection": "individual",
  "device_ids": ["wwn:REPLACE_WITH_APPROVED_DATA_DRIVE"],
  "intensity_percent": 50,
  "system_intensity_percent": 25,
  "duration_seconds": 60,
  "monitoring": "required",
  "temperature_limit_c": null
}
```

```sh
python3 lvs_storage_thermal_assist.py --config /approved/shared.json --check
python3 lvs_storage_thermal_assist.py --config /approved/shared.json \
  --fio /qualified/fio-3.42 --guard /accepted/storage_thermal_guard --plan
python3 lvs_storage_thermal_assist.py --config /approved/shared.json \
  --fio /qualified/fio-3.42 --guard /accepted/storage_thermal_guard \
  --output-root /approved/non-target/results
```

Routine standalone operation needs no JSON file: Advanced options → 6 selects
access contract and aggregate budgets transactionally, then the numbered drive
picker selects a stable identity. The optional CLI flags `--access-mode`,
`--aggregate-iops-limit` and `--aggregate-bps-limit` also configure passive inventory
or interactive startup.

`--check` is passive inventory; `--plan` can access/wake temperature sensors.
Execution remains interactive with preview and explicit confirmation. Shared
reads are not an unattended flag or authorization to test arbitrary drives.
Results/build/recovery locations must remain outside executing targets. Existing
permissions and an explicit non-root worker identity are required; no automatic
sudo, chmod, disk-group assignment or package installation is introduced.

CLI/TUI Configure Workloads and O / Stage Overrides expose access contract and
aggregate budgets using the same ThermalConfig constraints. Set budgets first,
then choose shared opt-in; invalid edits roll back through the existing editor.
Individual stable IDs accept plain text/comma-separated entries as well as the
existing JSON-list form. Storage OFF comparisons, original/effective evidence and manual labels remain
unchanged. Do not Save if only run-local changes were intended. The seven existing
profiles retain exclusive defaults until a later explicitly reviewed promotion.
No per-filesystem provider or duplicated workload implementation is introduced.

At 64 KiB and ordinary 50%, provisional rates resolve to HDD 15 IOPS, SATA/SAS
SSD 64 IOPS and NVMe 128 IOPS. Their existing class ceilings remain 30/128/256
IOPS and 2/8/16 MiB/s. Exceeding an explicitly supplied aggregate plan budget
blocks execution; no hidden redistribution or unsafe partial budget admission
occurs. Lower achieved throughput is an observation, not automatically a failed
drive. These rates do not establish actual media utilization or heating.

## Software evidence and next usable gate

Synthetic regressions cover explicit configuration/CLI-TUI constraints,
ext4/XFS/single-device-Btrfs data mounts, SATA/SAS SSDs, HDDs, positive PCIe NVMe
mapping and namespace/fabrics rejection. Root, holders, missing temperature,
aggregate/memory limits, descriptor identity/flags and post-open replacement
remain blockers. Regular-file independent-process tests verify shared lock and
duplicated-FD lifetime. Mocked supervision distinguishes permitted background
writes in shared mode from unchanged exclusive stops. Disposable owned children
prove public PID substitution cannot redirect the new standalone shared signaling
path. Synthetic stage-worker execution exercises the same guard/admission adapter,
recovery and terminal result with a shared configuration. These are **software
fixtures, not physical media, mounted-drive or thermal acceptance**.

The simplest next test host has a normal boot drive that remains blocked, one
separately identified internal SATA data HDD/SSD or single-namespace PCIe NVMe,
a resolvable direct data mount, reliable hwmon temperature and trusted fio/guard.
Results and recovery stay on the boot filesystem. No topology changes or unmount
are required to manufacture eligibility. Start with one approved target, short
reads and cancellation, retaining all background activity and cleanup evidence.

Before ordinary automatic enablement: independent review of this revised
contract and software changes, physical shared-read/temperature/cancellation and
interference screening, initialization/writeback accounting, and promotion of
appropriate default policy are required. Qualify materially different kernels,
controllers, namespace layouts and storage stacks; do not repeat a separate
architecture campaign merely for every conventional filesystem/media label.
There is no demonstrated corruption/native-readonly bypass in the earlier
research, but that absence is not universal safety proof. Kernel waits and
firmware/controller behavior remain real operational limitations. No file is
created as an alternate workload and no automatic fallback method exists.


## Production-path integration fixture

[The bounded VM integration harness](../scripts/storage_thermal_shared_probe.py)
uses the existing image builder with independent NVMe system, AHCI control,
SATA HDD data, SATA SSD data and single-namespace PCIe NVMe data devices. Images
are private writable regular files; no host block paths or passthrough options
are accepted. System and data partitions are independently mounted. Production
inventory/eligibility, descriptor acquisition, guard, fio and recovery are used;
only temperature is explicitly synthetic because a VM cannot qualify a physical
sensor. The source/tool hashes, raw strace, worker output and manifests are retained.

The first real-provider attempt exposed missing access-mode/node identity fields
in discovery output: mounted revalidation fell back to exclusive rules and
blocked before a worker started. Discovery now carries those authoritative fields;
the regression checks the actual discovered record, not a hand-built substitute.
This fail-closed defect was not an admission bypass or evidence of target mutation.

The fixture covers unmounted and mounted data, ordinary filesystem writes,
SSD/NVMe execution, real root rejection, cancellation/CLEAN and real process/kernel
I/O beside an independently timed primary telemetry proxy. It is not a new causal
writeback/cache experiment or physical primary-performance acceptance. The normal
stage's primary timing/verdict guarantees remain covered by the full regressions.

### Retained focused review evidence

The corrected full VM campaign is retained at `/tmp/lvs-wave2a-t_zn96hp`, and a
single targeted active-read overlap check at `/tmp/lvs-wave2a-ukco8k3v`. The failed
pre-correction attempt remains at `/tmp/lvs-wave2a-e_h52576`; it is not accepted
mounted-data evidence. Both accepted bundles record the same complete 387-file
execution fingerprint as the reviewed implementation at both source endpoints.

| Real provider case | Successful 64 KiB reads | Result |
| --- | --- | --- |
| Unmounted SATA HDD | 45 | WARN, completed and cleaned |
| Mounted SATA HDD with ordinary filesystem writes | 75 | WARN, completed and cleaned |
| Mounted SATA SSD | 192 | WARN, completed and cleaned |
| Mounted local PCIe NVMe | 384 | WARN, completed and cleaned |
| NVMe operator cancellation | 161 | INCOMPLETE/cancelled, confirmed cleanup |
| Independently supervised NVMe | 1024 | WARN, completed and cleaned |

The ordinary writer performed 108 controlled file-write/fsync operations; the
mounted HDD's last device observation recorded 69 background write I/Os while
fio write/trim/flush counters stayed zero. These counts are not interchangeable
or proof of attribution for every kernel operation. Root backing was rejected
before Thermal Assist opened it. All completed/cancelled owned groups and target
descriptors were cleaned, and fresh recovery inspection confirmed CLEAN.

The first two-second telemetry proxy completed in 2.000235 seconds during slow
auxiliary initialization; the worker began later, so that is not active-I/O
overlap proof. The targeted follow-up collected two real proc snapshots in
2.000285 seconds inside the actual NVMe worker's 29.159–37.783-second execution
window, after device reads were observed. It completed 1024 reads. No primary
hardware performance or physical thermal claim is made by these proxy tests.

Raw strace reconciles successful reads with fio counts, checks alignment/ranges,
read-only direct non-exclusive acquisition, and observes no raw-path reopen or
target mutation by guard/fio threads. Kernel/background activity is outside that
userspace assertion. The observer also captured the genuinely mounted shared
NVMe through production inventory, without reading a physical temperature sensor.
Temperature values in the workload fixture are explicitly synthetic; real sensor
and temperature-stop behavior still require physical screening.
