# Standalone Storage Thermal Assist — Stage 2B-2

Implemented: a duration-based guarded read-only random workload for independently
addressable **inactive physical HDDs** with proven identity/topology. No CPU/GPU
stage concurrency, profile changes, TUI O integration or active-storage execution.
This is not a benchmark, data-integrity test or physical thermal acceptance.

## Invocation and numbered workflow

Basic operation uses the Python standard library (project minimum 3.10), without
Textual or new Python dependencies:

```sh
python3 lvs_storage_thermal_assist.py --help
python3 lvs_storage_thermal_assist.py --check
python3 lvs_storage_thermal_assist.py --build-guard
python3 lvs_storage_thermal_assist.py --fio /absolute/path/to/trusted/fio-3.42
```

`--check` is passive inventory JSON: no block-device open or temperature value
read. `--plan` prints readiness and includes temperature reads which can access/
wake drives. No workload starts. `--config FILE` loads standalone v1 JSON, not an
LVS profile. `--output-root` chooses the result parent. Interactive execution
requires a TTY/SSH terminal; there is no unattended execution flag.

Guard building is explicit and uses the existing native compiler-command policy,
writing only `build/storage_thermal_guard`. A compiler/Linux headers are required;
no packages are installed or CPU/memory helpers rebuilt. Missing fio features are
unsupported; other feature-capable fio versions remain untested. There is no
automatic fio replacement or unsafe pathname fallback.

Use existing read permissions. No ACL/group/device-mode change or sudo invocation
occurs. An administrator manually launching as root must supply `--run-as UID:GID`
for the intended non-root operator, both IDs nonzero. The supervisor opens validated
devices with its existing permissions; the guard drops root before executing fio.
Guard, fio and their libraries must be trusted.

Menu operations: inspect drives; select a group/individual identities; adjust
50% ordinary / 25% system intent; set seconds per started drive; edit advanced
rates/read size, per-drive overrides and monitoring; preview; confirm and start;
review results. Enter cancels the single start confirmation. Choosing a partial
eligible subset is explicit and reported WARN. No runnable devices means BLOCKED
readiness is saved and no worker starts. During activity, `s NUMBER` stops one
drive, `0` stops all, `e` requests emergency stop, and Ctrl-C/SIGTERM/SIGHUP cancels.

The interface reuses Environment Manager screens: acknowledged results before
redraw, numbered confirmations, optional technical detail, and no ANSI escapes
on unsupported/noninteractive terminals. No saved settings/profiles are changed.

## Eligibility and no-write protections

Reuse existing pure inventory, mount/Btrfs topology, Linux sysfs and passive udev
records. Discovery never invokes SMART, blkid, zpool or RAID commands. Unique WWN
or transport-qualified serial is persistent identity; `/dev/sdX` is only a
revalidated ephemeral open path. Missing/duplicate identity blocks execution.

Default All Eligible Internal Drives includes matching system drives for visible
25% blocked reporting. SATA/SAS, NVMe, HDD, SSD and individual filters are supported.
Automatic groups exclude USB, virtual, loop, logical and unqualified RAID devices.
Individual selection overrides only filtering. Only inactive direct ATA or proven
SAS end-device HDD paths execute. HBA/controller identity is not proof of every
physical disk. SSD/NVMe, mounted/system/swap drives, array members and uncertain
topology remain blocked. Unresolved active ZFS/mount topology and known containers
conservatively block even otherwise unused candidates.

After confirmation, revalidate backend, configuration and identities. Acquire all
claims O_RDONLY|O_DIRECT|O_EXCL|O_CLOEXEC|O_NOFOLLOW before reports/worker starts;
verify block type, major/minor, size, sector alignment and identity after opening.
Failure closes previously acquired claims and saves BLOCKED evidence when its
output filesystem is safe. Reports cannot be placed on executing targets; the
ordinary results filesystem can still receive application writes while its own
Thermal Assist path is blocked. That is not thermal-workload coverage. Keep
claims until process/group cleanup is proven; no exclusive-open bypass.

The unchanged [native guard contract](storage_thermal_backend_contract.md) pins
fio's executable descriptor, closes unrelated descriptors, drops privileges and
enforces the reviewed ioctl/flush/cache policy. Fixed psync direct randread, QD1,
invalidate=0, and no creation/allocation/flush options are retained. No target
write, discard, initialization, test-file creation or cache drop. This is not a
sandbox for malicious fio/root, descriptor injection or concurrent administrative
storage reconfiguration. Firmware background behavior is not claimed absent.

## Rates, monitoring and supervision

`thermal_pilot_v1` remains provisional: HDD 30 IOPS/2 MiB/s, SATA/SAS SSD 128/8
MiB/s, NVMe 256/16 MiB/s. Percentage scales the lower IOPS/bandwidth ceiling,
rounding down; zero starts nothing, nonzero sub-IOPS requests reject. Advanced
rates are distinct and remain capped. SSD/NVMe settings do not permit execution.
There is no performance benchmark or claim of measured heating from percentage.

Ordinary Linux scheduling, blocking QD1 and 100 ms worker staggering; no affinity
balancing or reserved core. FD limits and the existing available-memory reserve
bound plans. A provisional 16 MiB + request-size allowance per worker is recorded,
not claimed as measured universal fio RSS. Runtime memory pressure stops work.

Shared diskstats collection runs once per second; identities/topology are checked
every five seconds and before/after execution. Process CPU/RSS are observed where
accessible. Device activity counters are labelled separately from fio's exact
terminal read counters/rates; unrelated traffic/merging prevents automatic
attribution. Unexpected writes/discards/flushes, reset/missing activity, I/O errors,
identity changes, lost monitoring and log limits stop activity as defined.

Temperatures require exact sysfs device ancestry, never fuzzy name matching.
Available upper/lower critical and warning limits are respected; configured stop
limits cannot override a stricter hardware critical limit. No universal HDD
temperature is invented. Monitored mode requires a reliable reading and stop
threshold; configure one if hardware supplies none. Critical evidence triggers
group emergency stop. No SMART subprocess is spawned in the polling loop.
Even drivetemp can affect standby behavior: [kernel documentation](https://docs.kernel.org/hwmon/drivetemp.html).

Unmonitored operation needs explicit confirmation, bound to exact configuration,
target set and duration with expiry. Changed settings invalidate it. Approval
does not renew across stages or authorize a multi-hour profile. Available critical
evidence still stops work. Missing telemetry cannot establish heating or margins.

Each started process has a monotonic duration+5-second completion allowance.
Cancellation broadcasts TERM, escalates after two seconds, then bounds reaping.
This cannot guarantee an uninterruptible kernel read returns. Unconfirmed cleanup
retains descriptors, reports INCOMPLETE and blocks another run in that manager.
Uncatchable supervisor death cannot guarantee cleanup; finite fio runtime is not
proof of resource release. Do not reset controllers or infer cleanup from SIGKILL.

## Evidence and completion authority

Every execution has a new `*_Storage_Thermal_Assist_*` directory containing v1
configuration/effective readiness, source endpoints, executable/guard evidence,
raw worker logs, terminal worker results, observation summary and bounded progress
JSONL (approximately at most 1024 samples per drive). Actual native fio rates,
temperature coverage/start/peak/end, interruptions, descriptor ownership and
observable supervisor/child CPU consumption remain separate.

**`storage_thermal_manifest.json` is the single aggregate completion authority.**
It begins running/INCOMPLETE and is atomically finalized last, after cleanup,
terminal worker publication and report preparation. Bounded publication retry
does not hide failure. No earlier successful aggregate snapshot exists. Summary
text points to this authority instead of independently claiming final PASS.

PASS means completed monitored read activity under policy, not accepted heating
or integrity. WARN preserves approved unmonitored operation, partial requested
coverage or temperature warnings. Cancellation/missing cleanup/publication is
INCOMPLETE; demonstrated I/O/evidence/safety failure is FAIL; no eligible backend/
target is BLOCKED. No CPU/GPU hardware verdict is generated by this standalone tool.

## Validation boundary

Regressions use temporary topology/device files and mocked workers. The opt-in
[runner proof](../scripts/storage_thermal_runner_probe.py) copies scoped source
into a sealed disposable VM and exercises the real supervisor, descriptor opener,
guard and fio. Its virtual-fixture resolver override exists only in that research
script; production has no bypass flag. No host block device is attached, and
ordinary smoke tests never launch a VM or open a real block device.

Physical ATA/SAS deployment, real sensor/stop response, heating, a 6C/6T host with
24 HDDs, two NVMe drives and two SATA SSDs, CPU/GPU interference and ARM64 deployment
remain unaccepted. Seven standard profiles/41 stages remain unchanged for Stage
2B-3; the approved contract section is preserved. Active system/RAID/ZFS/LVM and
logical-array execution require separate proofs. No physical retest is requested
or performed by this software milestone.

### Completed software and synthetic evidence

- **20/20 affected checks**, **401/401 complete smoke**, **81/81 profiles valid**
  with five unchanged advisories; **398 Python compilation checks** and
  **20 integration imports** PASS. Standard-library startup, UI cancellation,
  lifecycle/persistence, target races and existing benchmark regressions pass.
- Native x86-64 guard build/kernel-policy execution and AArch64 guard object
  compilation PASS. AArch64 standalone runtime is not physically accepted.
- Final real-supervisor VM evidence is retained at
  `/tmp/lvs-wave2a-h7plb0ix/`: normal and publication-retry runs each completed
  45 reads / 2,949,120 bytes at approximately 14.995 IOPS and correctly returned
  WARN for unmonitored operation. Cancellation completed nine reads and returned
  INCOMPLETE. All three confirmed guard identity and cleanup.
- Full traces contain 99 aligned, bounded reads, **zero target mutation calls**
  and **zero unknown target operations**. The writable synthetic image's SHA-256
  remained `eeca4a419d2c537e0eb24ec08925decf2c6fbfb95e64e98c185a9a369bab0a86`.
  The guard is byte-identical to Stage 2B-1:
  `7045ba6fe461d0e8ce412dcbf3a11427c605298e0a27a1c5242b0fcec29563f5`.
- The traced single-vCPU VM normal run observed 5.918 seconds overall, 1.038
  supervisor CPU seconds and 0.283 child CPU seconds. These include tracing,
  source collection and publication; they are **not** physical-host overhead or
  a passed CPU/GPU interference budget.

Complete 382-file scoped development fingerprint:
`5b2e464dffd586ae4536a55b6567fcc04368b6b7c3c9a7d9ae0c9470b70089c3`.
All synthetic runs recorded that same fingerprint at both endpoints. This is
synthetic execution evidence, not new physical acceptance of LVS workloads.
Research scripts, smoke tests and Markdown remain outside the established source
scope. The approved 73-line Stage 2B-3 requirement is preserved unchanged.

Final review reproduced an SSH hangup gap in an isolated mock-only subprocess:
before correction, SIGHUP exited with signal 1 without supervisor cleanup. The
runner now handles HUP with the same bounded group cancellation as INT/TERM. The
regression confirms INCOMPLETE plus confirmed cleanup; the complete suite and
end-to-end synthetic proof were rerun after this correction.
