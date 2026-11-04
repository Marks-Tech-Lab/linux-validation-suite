# Storage Thermal Assist: Wave 2A feasibility and safety evidence

Status: descriptor-bound **research feasibility confirmed for the tested fio
3.42 build**, not production workload or HDD thermal acceptance. fio 3.40 is
unsupported for this exact approach. No Storage Benchmark policy, profiles,
stage orchestration, CLI/TUI controls, or system dependencies are changed.

## Experiment and retained evidence

The research-only [probe](../scripts/storage_thermal_fio_probe.py) builds an
initramfs and runs unprivileged QEMU TCG with one private 32 MiB synthetic raw
image. It has no device-path argument, host disk passthrough, network, KVM
requirement, or system installation step. All guest files/logs are in RAM.
The backing image is writable, so a read-only hypervisor cannot conceal a
broken read-only workload. Each invocation retains its private `/tmp` bundle.
The guest requires a matching boot token, QEMU identity, exact synthetic serial
and size before opening `/dev/vda`; these are fixture guards, not production
device-identity or topology validation.

The completed experiment is retained locally in
`/tmp/lvs-wave2a-7mc1gx8s/`: `host.json`, `console.log`, synthetic image,
`evidence/results.json`, per-case fio JSON/stderr, and complete per-process
strace logs. This is temporary developer evidence, not historical physical
acceptance under `results/`. Earlier failed research attempts are retained too.
Subsequent probe changes add host-side evidence-verdict checks (replayed against
this bundle) and clarify a comment; they do not change the guest experiment.

Versions: Linux 7.2.9-200.fc44.x86_64 guest, fio 3.42 built from the official
`fio-3.42` source tag with `./configure --disable-native; make`, strace 6.13
extracted from a Debian package into `/tmp` (not installed), CPython 3.14.8.
The host supplied QEMU and a kernel with built-in virtio-blk/devtmpfs/initramfs.
The fio 3.42 executable SHA-256 is
`444ba07aeaa89d0f2f9ecdd2577f6846401d8dcbc54d6dedce96120cb95c9378`.
Tool/kernel hashes and exact QEMU arguments are in `host.json`.

| Disposable case | Observed outcome |
| --- | --- |
| 10 IOPS, 64 KiB, QD1, 3 s | Exit 0; 30 complete reads; 29 distinct offsets; 9.997 IOPS |
| 30 IOPS, 64 KiB, QD1, 3 s | Exit 0; 90 complete reads; 82 distinct offsets; 29.990 IOPS |
| Cancellation of 60 s job at 2 s | 17 reads; exit 128; reaped in 2.263 s total; no SIGKILL or remaining process-group member |
| Write/trim requests plus `--readonly` | Both rejected during parsing; exit 1; no target I/O |
| fio 3.40 | Rejects unknown `filetype`; exit 1; no target I/O |
| `filename=-` before `filetype=block`, fio 3.42 | Fails size discovery; exit 1; no target I/O |
| Deliberately enable invalidation, negative witness only | `ioctl(BLKFLSBUF) = 0` despite read-only descriptor; **unsafe setting rejected for proposed workload** |
| Independent misaligned direct read / write-on-read-only witnesses | Kernel EINVAL / EBADF respectively |

Both successful pilots reported 100% depth 1, zero write/trim bytes, and
automatically discovered the full 33,554,432-byte size through BLKGETSIZE64.
Every traced successful read was 65,536 bytes, aligned to 65,536 bytes and
within the descriptor's bounds. Offsets varied nonsequentially; repeats are
permitted. No explicit fio `size` was supplied. The synthetic device advertises
512-byte logical and 4096-byte physical sectors. This does not establish direct
I/O alignment behavior on all real devices.

The whole synthetic image hash before and after all cases was identical:
`eeca4a419d2c537e0eb24ec08925decf2c6fbfb95e64e98c185a9a369bab0a86`.
The guest exits after serial evidence publication; its resulting PID1-exit
kernel panic and `-no-reboot` QEMU exit are deliberate fixture shutdown, not an
HDD or LVS workload failure.

## Required descriptor and fio constraints

- Parent opens the validated descriptor `O_RDONLY | O_DIRECT | O_EXCL |
  O_CLOEXEC`, validates block type, device identity/geometry and F_GETFL, and
  passes it as stdin. `O_EXCL` is an additional guard, not a complete proof of
  inactivity/topology safety. No arbitrary `/dev/sdX` fallback is allowed.
- fio 3.42 parses `filetype` before the filename callback must allocate the
  file: **put `--filetype=block` before `--filename=-`**. A parser merely
  accepting the option is insufficient readiness evidence.
- The tested psync implementation duplicates stdin and uses `pread64` with
  explicit random offsets. It does not reopen the target pathname. Crucially,
  `--direct=1` cannot add `O_DIRECT` to a descriptor obtained by `dup`; the
  parent's direct open is mandatory.
- Fixed generated command: read-only randread, one synchronous job, QD1,
  `allow_file_create=0`, `create_on_open=0`, `fallocate=none`, `invalidate=0`,
  `create_fsync=0`, `fsync=0`, `fdatasync=0`, `end_fsync=0`, `end_syncfs=0`,
  `fsync_on_close=0`. No user job files, engine substitution, arbitrary appended
  options, preparation writes, trim, initialization or content verification
  writes. The command construction is in the probe for reproducibility only.
- Tracing used `strace -ff -ttt -yy -s 0 --kill-on-exit` across all descendants.
  Normal pilots and cancellation have no target write, discard, flush, writable
  mapping or unreviewed target ioctl. Target operations were size discovery,
  descriptor duplication/metadata, POSIX_FADV_RANDOM, reads and close. Output
  writes went to RAM log/report files, not the block descriptor.
- A read-only open causes target-data `write/pwrite` to fail at the kernel,
  while fio `--readonly` independently rejects write/trim directions. **Neither
  alone prevents privileged mutating ioctls:** the invalidation witness proves
  this. The nonmutating result is conditional on the exact reviewed binary,
  fixed options and descriptor path. It is not a sandbox guarantee against
  malicious/replaced fio, unknown engines or arbitrary root code. Future
  production approval must resolve privilege dropping/syscall restrictions and
  reproducible binary/version readiness, rather than claim all fio versions safe.
- Monotonic deadlines, a separate process group, bounded TERM then KILL/reap,
  and explicit remaining-group checks are exercised. Cancellation is reported
  as interrupted, never completed PASS. The normal cancellation path completed
  without escalation; an uninterruptible kernel task cannot be guaranteed to
  exit promptly by this fixture proof.

Source references: [fio 3.42 filesetup](https://github.com/axboe/fio/blob/fio-3.42/filesetup.c),
[psync engine](https://github.com/axboe/fio/blob/fio-3.42/engines/sync.c),
[Linux cache invalidation](https://github.com/axboe/fio/blob/fio-3.42/os/os-linux.h).
Only fio 3.42 was positively exercised; other releases/vendor builds require
the same disposable descriptor/read-only smoke proof. Do not infer a blanket
minimum-version guarantee from two tested versions.

## SMART compatibility correction and no-wake boundary

Storage Health used invalid `--nocheck standby,now`. smartctl 7.5 rejects that
syntax on `/dev/null` before opening any disk. Plain `--nocheck standby` is the
supported request. The correction also reads native nested
`smartctl.messages`, retains older wrapper messages, and removes an unjustified
"without waking it" claim. An argument-error exit bit cannot be mislabeled a
successful standby skip.

SMART exit status is a bit mask. The usual standby skip status 2 also denotes
open/device-access problems: status alone is not evidence of standby. Valid
health JSON with nonzero health/history bits remains usable, with the status
retained; failing SMART health remains failing health. Permission and unsupported
device errors stay distinct from unavailable data. Tests cover these cases.

This does **not** prove no spin-up: type autodetection, bridges, firmware,
inventory enrichment, and some sensor queries can already access a drive before
the power-mode check. No new `-d` policy, power transition, SMART setting,
self-test, or speculative controller support is introduced. Production sleeping
drive policy needs separately proven passive identity/type and monitoring paths;
otherwise skip/block it. See the [smartctl manual](https://raw.githubusercontent.com/smartmontools/smartmontools/master/smartmontools/smartctl.8.in).

## Remaining approval gates and compatibility design

Before implementing the standalone thermal workload:

1. Approve the exact fio/runtime/privilege contract or a separate minimal
   descriptor-only `pread` helper if deployment fio lacks the proven behavior.
   A small reviewed helper is an alternative requiring its own proof, not an
   implemented fallback. An upstream fio descriptor interface/fix is another
   option. Never revert to unchecked device-path launches.
2. Establish authoritative serial/WWN + major/minor identity, physical topology,
   mount/holder/system-device exclusion and pre-open/post-open revalidation.
   Individually addressable **inactive HDDs only** initially. Missing, ambiguous,
   inaccessible, RAID/ZFS/LVM/multipath or active/mounted targets must block.
3. Bind reliable per-drive temperature sources to that identity for monitored
   operation; define stale-sensor, I/O error, thermal stop and emergency/group
   cancellation behavior. Separately design explicit, bounded approval for
   missing-temperature operation as specified in the Wave 2B plan below.
4. Approve pilot measurements of actual per-drive activity, heating/cooling,
   CPU overhead, concurrent CPU/GPU interference, temperature stop/overshoot and
   cleanup. **10/30 IOPS, 64 KiB, QD1 remain experimental candidates**; no final
   thermal limits, polling cadence, duration or interference budget is set here.
   VM rates establish I/O control, not HDD heating or physical host overhead.
5. Scale per-drive and aggregate resource budgets independently from real
   capabilities, including weak hosts and 24+ bay systems. Establish safeguards
   before any explicitly approved physical HDD campaign.

Future active-pool compatibility should preserve an identity graph from logical
volumes/pools through controller/transport paths to physical drives. Providers
must prove membership, controller access, thermal identity, per-drive activity
and application interference. Pool-aware read methods and fail-safe policies
require separate approval and acceptance. Do not make device-letter paths or
absence of current mounts the permanent abstraction. This milestone neither
implements nor accepts active RAID/ZFS/LVM/multipath/system-disk support.

Workload correctness, real drive activity, demonstrated heating, CPU/GPU
interference and thermal safety are separate acceptance gates. Read-only activity
is neither a storage benchmark nor exhaustive data-integrity verification.

## Wave 2B plan: operator-approved requirements

These requirements supersede any proposed **50/25 IOPS defaults**. The intended
values are **50% relative thermal activity for ordinary drives and 25% for
boot/system drives**. This section is planning, not authorization to implement
the full workload or access active devices. The Wave 2A experiment, fixed pilot
rates, evidence and conclusions above remain unchanged.

### Relative intensity and measured activity

Expose 0–100% thermal activity. Zero issues no assist read I/O; monitoring has
its own access policy and must not be described as guaranteed no-wake. One
hundred percent means the upper bound of an approved thermal activity policy,
not manufacturer performance, drive utilization, maximum heating or an
unrestricted benchmark. Defaults are 50% ordinary / 25% boot or system.

Proposed transparent conversion: for a confirmed drive type and reviewed policy
version, scale both a calibrated IOPS ceiling and bandwidth ceiling by the
selected percentage. For a fixed request size, enforce the lower effective rate
from those two limits, with QD1 initially. Record the request size, alignment,
rounding/rate resolution, selected percentage, type-policy limits, effective
rate and observed IOPS/bandwidth. Never silently round a tiny percentage upward
into a materially higher workload; if the backend cannot pace it accurately,
report the supported resolution or block that setting. Advanced controls expose
actual IOPS/bandwidth as a distinct selection mode, still bounded by approved
safety limits; they must not ambiguously compete with percentage mode.

Calibrate conservative HDD/SSD/NVMe policies through separately approved small
pilots, not an expensive capacity or maximum-performance benchmark on every
launch. Unknown drive type or an uncalibrated policy cannot acquire a guessed
production limit from model name or capacity. Observe per-worker completion and,
where available, device counters to report requested versus achieved activity.
Separate assist traffic from unrelated host traffic and controller/cache effects.
Do not automatically raise intensity to chase a temperature or utilization
target. The 10/30 IOPS, 64 KiB experiments are feasibility evidence only, not a
calibration of the percentage scale or finalized presets.

### Selection, visibility and backend eligibility

Default group: **All Eligible Internal Drives**. Offer SATA/SAS, NVMe, HDD, SSD
and individual-device selection. Automatic group filters always exclude USB,
virtual, loop and logical/aggregated devices. Individual selection is the only
way to request those excluded classes, but never overrides physical identity,
topology, backend proof, permissions or other safety checks. It can therefore
produce a visible blocked request rather than permission to run.

Show matching system drives in the selection display with the 25% default and
their specific BLOCKED reason while their active-device backend is unvalidated.
Likewise distinguish discovered, selected, eligible, blocked and runnable drives;
do not silently hide an unsupported member or imply all selected devices ran.
SSD/NVMe discovery and filters do not imply their activity policy or execution
backend has already been accepted. Existing Wave 2A support is a virtual block
descriptor proof, not physical acceptance of any storage class.

| Target/path | Wave 2B disposition and required proof |
| --- | --- |
| Individually addressable inactive internal HDD | First production candidate after identity/topology, permissions, monitoring, rate and thermal safeguards are reviewed and implemented; physical acceptance still required |
| Inactive SATA SSD / NVMe | Display/filter support planned; independent type calibration, alignment/backend and operating-condition acceptance required |
| Boot/system or other mounted/active drive | Display at 25%; BLOCKED until a coordinated active-device read-only path is independently proven |
| USB, virtual, loop, logical/aggregated device | Never auto-selected; individual request remains subject to backend/identity validation and may remain BLOCKED |
| Active ZFS, mdraid, LVM, hardware RAID or multipath | Explicit compatibility goal, separate topology/provider and backend proof; no raw-member bypass of the storage stack |

### Active-stack compatibility research

Investigate both coordinated physical-member read access and read-only
logical-array/pool approaches. For each provider, first establish whether the
normal storage stack permits the operation, whether strict no-write constraints
can be enforced, and whether activity can be attributed to individual members.
Do not equate O_RDONLY on a raw member with safe coordination of an active pool.
Do not use imports, mounts, scrubs, resilvers, cache drops, metadata changes or
other stack-management operations as presumed read-only thermal preparation.

Record logical activity separately from demonstrated direct physical-drive
activity. An array-level read must never be credited as heating or exercising
every member without measured member coverage; cache/parity/layout effects and
unobservable members remain explicit limitations. Some providers may offer only
logical activity or remain unsupported. The identity-graph approach above is the
extension boundary; active compatibility is a design goal, not accepted support.

### Scheduling, overrides and temperature policy

Use ordinary Linux scheduling, blocking I/O, rate limits, staggered startup and
shared supervision by default. A per-drive blocking I/O context must not imply
a dedicated CPU core. Avoid busy polling, aggressive affinity, realtime policy
or complicated scheduling without measurements showing a benefit. Include a
6-core/6-thread host with 24 HDDs, two NVMe drives and two SATA SSDs in the
scalability acceptance plan, measuring aggregate supervisor/worker CPU use,
memory and concurrent CPU/GPU interference independently. No numerical overhead
budget or physical scalability acceptance is established by the VM experiment.

Integrate future drive groups, percentage/advanced-rate mode, per-drive
overrides, duration, monitoring policy and CPU scheduling with the shared CLI/TUI
effective Stage Overrides path, including the TUI **O** interface. Preserve the
original profile, effective settings, resolved device identities, blocked members,
commands and reasons in automatic readiness artifacts, even with zero runnable
commands. Present the effective changes and obtain explicit approval; do not
mutate saved templates merely to apply run-local settings.

Missing temperature telemetry may allow a separately, explicitly approved
bounded run. Approval must state the missing coverage, duration/rate limits and
remaining stop safeguards. Do not claim temperature safety or measured heating
for that drive. Loss of monitoring during a monitored run must stop/pause under
the chosen policy, not silently convert to unmonitored operation. Identity,
topology and no-write failures remain blocking regardless of temperature mode.

### Implementation order and acceptance boundaries

1. Review the bounded inactive-HDD backend and privilege contract; implement only
   after approval, preserving the descriptor-only path with no pathname fallback.
2. Add shared inventory/selection, calibration policy and concise Stage Overrides
   controls, with visible blocked targets, effective-readiness persistence and
   original/effective configuration evidence.
3. Prove monitoring/explicit unmonitored mode, pacing, cancellation, I/O-error
   handling and group emergency stop in deterministic fixtures before hardware.
4. Conduct separately approved physical pilots for activity, useful heating,
   thermal safeguards and exceptionally low CPU/GPU interference, including the
   low-core-count/high-drive-count scenario. Evaluate each gate independently.
5. Extend system-drive, SSD/NVMe and active-stack paths only after their own
   backend safety review/proof and scoped acceptance. Never infer those paths
   from the inactive-HDD proof or from an individual-selection override.

The immediately usable foundation is the completed disposable descriptor proof,
existing inventory/health infrastructure and effective Stage Overrides artifact
framework. No full thermal worker, percentage calibration, active-array access,
system-drive execution or new UI integration is implemented by this plan.

## Reproduction and software checks

With separately supplied trusted tools, on a compatible Linux/x86-64 host:

```sh
python3 scripts/storage_thermal_fio_probe.py \
  --fio /absolute/path/to/fio-3.42 \
  --old-fio /absolute/path/to/fio-3.40 \
  --strace /absolute/path/to/strace \
  --kernel /absolute/path/to/compatible/vmlinuz \
  --python /absolute/path/to/system/python3
```

The probe never installs packages, accepts a drive, or runs a physical thermal
test. It needs Linux O_DIRECT/BLKGETSIZE64, virtio-blk, initramfs support, tracing
inside the guest and sufficient temporary space/RAM. It is a research utility,
not a portable host bootstrapper; different architectures, distributions,
kernels, sector formats and fio builds remain unproven. Failures retain the
bundle and must not be reinterpreted as safe production readiness.

Focused [regressions](../smoke_tests/storage_thermal_feasibility_checks.py) use
only fake SMART responses, pure command/trace fixtures and identity guards;
they never start QEMU or touch a drive. Full software validation is reported
separately from the disposable experiment and future physical acceptance.

Closure software validation: seven affected checks PASS; complete suite
**387/387 PASS**, including three new fixture checks; **81/81 profiles valid**
with five unchanged advisories; **389 Python files compile** and **12 integration
imports PASS**. Evidence-verdict replay accepted the actual bundle and rejected
six injected false-success variants. Markdown/local links and `git diff --check`
pass. No physical thermal testing is performed or accepted.

The complete 376-file `lvs_execution_source_v1` fingerprint is
`8a95d444da227a106ca590f87b5256788c5eb2ea08d91628eef41890b9996052`.
Its change from the baseline is the Storage Health correction. This established
scope excludes Markdown, smoke tests and Python files under `scripts/`; it must
not be presented as an identity of the entire research bundle. The current
research probe SHA-256 is
`0775835952b2b4d6dd3af1ea395cbc7ead54fc01c36a526b02f18541a60c0122`;
the executed copy retained in the final bundle's `root/probe.py` is
`7965b805d40968da6372c01fc0f17db58f1ff93d7fd67f02306c295aded65e83`.
