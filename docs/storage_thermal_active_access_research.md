# Stage 2B-4A: mounted active-block-device research

**Current decision: NO-GO for the proposed raw provider under the current
read-only and paced-activity contract.** The
[final targeted investigation](#final-targeted-mapping-and-startup-investigation)
demonstrates induced whole-device writeback, a long wait during cancellation,
and startup reads outside fio's rate and concurrency controls. The earlier
INCONCLUSIVE and NO-GO investigations remain historical evidence.

## Reusable experiment and isolation

[The research harness](../scripts/storage_thermal_active_probe.py) extends the
[Wave 2A VM builder](../scripts/storage_thermal_fio_probe.py) through an optional
fixture-builder hook. Its default inactive-device experiment remains unchanged,
including its unchanged-image check. Only the mounted-image hook replaces that
check with before/after hashes as provenance, without claiming equality.

The CLI accepts explicit tool/kernel paths, never a device path, raw target,
QEMU option, fio job or passthrough argument. All host inputs must be regular
files. New image files are created exclusively beneath a new `/tmp/lvs-wave2a-*`
bundle. `mkfs.ext4 -d` populates an image; nothing is mounted on the host. QEMU
uses TCG, no network, no monitor, no user configuration and no host device
passthrough. The backing files are writable; host-side read-only enforcement
cannot conceal a guest mutation. Copied host setuid/setgid bits are removed
before populating the guest filesystem.

The guest verifies a matching random boot nonce, QEMU DMI identity, exact
per-disk serial/size, ATA sysfs ancestry, partition-to-parent mapping, actual root
mount device and separate control filesystem before target opening. Its fixed
experimental endpoint is the synthetic whole parent `/dev/sda`, not `/dev/sda1`.
These fixture checks confer no production SATA/ext4 eligibility.

Topology:

- Q35 machine, one emulated CPU, 1 GiB RAM, explicit ICH9 AHCI controller.
- SATA-like HDD image, MBR partition starting at sector 2048; 512 MiB ext4
  partition mounted read-write as the actual switched guest root.
- Separate SATA-like control image, MBR/ext4 128 MiB partition mounted at
  `/control`; evidence, trace files and recovery journals reside there.
- 512-byte logical/4096-byte physical sectors, synthetic rotation-rate hint 7200.
  This hint is not a performance model or actual rotating-media evidence.
- `/tmp` is tmpfs. The fixed ordinary OS writer modifies an existing guest-only
  fixture file, with fsync, in both busy controls and busy assist cases. It is
  explicitly separate from the Thermal Assist worker.

Tools measured: Linux `7.2.9-200.fc44.x86_64`, fio `3.42`, strace `6.13`, CPython
`3.14.8`, QEMU `10.2.2`, mke2fs/libext2fs `1.47.3`. The unchanged guard reports
`lvs-storage-thermal-guard-v1`; stage admission remains protocol v2. Exact kernel,
fio, guard, harness, launch-bootstrap and source hashes are retained in host.json
and its fixture-layout metadata. No packages or permissions are installed/changed.

## Invocation

Compile the unchanged native guard into a temporary regular-file destination
using LVS's existing native-helper compiler policy, then supply explicit paths:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /usr/bin/python3 \
  scripts/storage_thermal_active_probe.py \
  --fio /path/to/qualified-fio-3.42 \
  --old-fio /path/to/older-fio \
  --strace /path/to/strace \
  --kernel /path/to/guest-vmlinuz \
  --python /usr/bin/python3 \
  --guard /tmp/locally-built-thermal-guard
```

Prerequisites are existing QEMU, compatible built-in AHCI/ext4/devtmpfs/tracing
kernel support, mkfs.ext4, switch_root, ldd and the existing C compiler machinery
for a temporary owned-launch library. Missing prerequisites fail visibly; there
is no installation or weaker fallback. Automated smoke tests do not boot a VM.

## Access and measurements

The research-only opener uses O_RDONLY, O_DIRECT, O_CLOEXEC and O_NOFOLLOW,
without O_EXCL. It checks fstat block type/rdev, BLKGETSIZE64, BLKSSZGET, descriptor
flags and guest topology before/after acquisition. The production inactive-HDD
opener keeps O_EXCL and all active-device blockers unchanged.

The unchanged guard supplies fixed descriptor-bound psync/random-read arguments,
64 KiB, QD1, one thread, 7 IOPS, finite duration and explicit invalidate=0. It drops
privileges, clears capabilities, enforces no_new_privs/seccomp and denies mutating
ioctls/synchronization/cache-discard requests, including descriptor aliases.
No data buffers are exported. Seven IOPS is the existing floor-rounded 25% HDD
pilot policy at 64 KiB, not 25% rated utilization or guaranteed heating.

Four three-second assist runs are paired in AB/BA order with four no-assist
controls: idle/control, assist/idle, busy/control and assist/busy. Ordinary writer
operations and timestamps are retained to expose imperfect timing matches.
Cancellation is a separate case. strace captures the complete worker lifecycle,
including descriptor duplication and close. PID1 reaps adopted trace descendants;
uncertain cleanup stops the experiment and retains its ARMED obligation.

Kernel tracing records available selected read/writeback/release/invalidation
functions and block bio/request issue/completion events across tasks. Trace
buffer statistics expose drops/overruns. The harness retains raw traces rather
than treating issuing-task names or nearby timestamps as proof of causality.

The observed mounted pilot produced 21 aligned 64 KiB reads per three-second
assist run, approximately 7 IOPS, with zero target mutations or unknown target
calls in the syscall audit. Busy controls and treatments produced ordinary
filesystem writes and journal/flush traffic. Those are not mislabeled as worker
writes. Cancellation returned nonzero after partial reads, without claiming full
coverage. Function tracing observed the corresponding raw read entries and close
paths; absence of selected calls is scoped to the available instrumented symbols.
It is not proof that every compiled/inlined/deferred cache or writeback path was
observed. Root/control image hashes changed as expected; equality is not a gate.

## Safety/lifecycle cases and outstanding controls

The VM also tests normal native v2 commitment, post-commit cancellation, expired
Python admission, a separate genuine native wait/deadline rejection, wrong major
identity, partition/parent confusion, readwrite/buffered descriptors, native alias
mutation denials, source digest substitution, stale/missing backend evidence and
older fio rejection. Unsupported direct I/O and topology/serial mismatch are
injected refusals: they prove fail-closed behavior, not a different real kernel
or a hot-plug experiment. Misaligned pread returns EINVAL; writes on the read-only
descriptor return EBADF.

Production SharedAdmission, StageLaunches, OwnedProcess and RecoveryScope are
reused. ARMED is durably verified on the control disk before admission. Injected
ENOSPC/EIO before ARMED prevents target opening. Injected CLEAN publication failure
retains ARMED after genuine cleanup. SIGKILL of an admitted supervisor leaves
ARMED visible to a fresh process, while the guarded worker is reaped. A substituted
private pidfd cannot signal the unrelated disposable child or certify cleanup;
restoring genuine authority permits confirmed cleanup and CLEAN.

**Not demonstrated and still blocking provider qualification:**

- Causal exclusion/accounting of indirect, delayed kernel writeback/cache effects.
- General mount/topology transitions, replacement or hot-unplug during I/O.
  A controlled supervisor root-view change was tested: new acquisition rejected,
  the original pre-pinned revoker closed admission, and owned cleanup completed.
  This is not automatic provider monitoring or physical-topology qualification.
- Kernel/device combinations actually lacking direct-I/O support; only injected
  refusal is covered here.
- Non-exclusive access across other kernels/controllers/filesystems and physical
  SATA HDD behavior, including stalls or uninterruptible I/O.

No fallback method is selected. A failed/missing tracing facility or incomplete
lifecycle evidence cannot become provider GO. The v1 research verifier deliberately
has no automatic GO route: resolving kernel causality requires independently
reviewed additional evidence, not changing a status string.

## Report placement and future compatibility

The separate persistent control disk isolates ordinary OS writes, workload reads,
LVS journal/results writes and possible kernel-induced work. Control evidence
synchronization targets only that filesystem; the harness does not call global
sync. Durable ARMED/CLEAN cannot be replaced with volatile tmpfs state.

This does not establish a permanent two-drive production requirement. Single-drive
systems need a separate review of co-located control-plane filesystem writes and
failure behavior. Such writes must be disclosed and separated from workload
mutation claims; they must not clear unresolved ownership or be counted as
measured assist activity. No co-located production recovery is implemented.

The descriptor/guard/admission observations motivate later SATA SSD, NVMe, Btrfs
and conventional mounted-data proofs. They do not qualify those classes. Recheck
identity/mapping, direct-I/O and alignment behavior, kernel open/read/close/cache
paths, controllers, temperature association and operational interference. Btrfs,
encryption, LVM, RAID, ZFS and multipath additionally need their own mapping and
provider evidence; logical reads never imply every member was exercised.

Gate 2B-4B remains blocked. If further raw-access proof succeeds, the first provider
should be a narrowly identifiable direct internal device with a plain partitioned
root, not a general allow-active switch. If raw access cannot satisfy its kernel
contract, seek separate approval for an existing-file/filesystem-aware study.
Existing-file reads also need atime, direct-I/O, concurrent-write, sparse/compressed
extent and physical-activity proofs; no writable test-file substitute is authorized.

## Retained run and observed comparison

The final executable harness run is retained at `/tmp/lvs-wave2a-62cr0fot/`:
`host.json`, `console.log`, both writable raw images and `evidence/results.json`,
per-phase syscall/kernel traces and native ownership/recovery records. Earlier
bundles are retained, including the failed guest-path/setuid-import attempts and
intermediate access measurements. They are not historical physical acceptance.
The guest's PID1 exit after complete serial publication deliberately produces a
kernel panic/no-reboot termination, as in Wave 2A; an incomplete publication is
always a harness failure.

| Final phase | fio reads / 3 seconds | fio IOPS | Ordinary writer operations |
| --- | --- | --- | --- |
| Idle control A/B | None | None | 0 / 0 |
| Idle assist A/B | 21 / 21 | 6.995336 / 6.997667 | 0 / 0 |
| Busy control A/B | None | None | 29 / 30 |
| Busy assist A/B | 21 / 21 | 6.995336 / 6.997667 | 30 / 30 |
| Cancel | 6 partial reads | 6.984866 over actual partial runtime | 0 |

Each full assist run added 21 synchronous parent-device READ requests of 64 KiB
in the recorded block stream. Syscall audits reported zero target mutations and
zero unknown target calls. Selected read-function entries matched those reads;
there was one observed block release per assist, no observed sync_blockdev,
blkdev_flush_mapping, filemap_write_and_wait_range or invalidate_bdev call in
those windows. No trace overruns/drops were reported. This does not cover absent
symbols or all possible indirect paths.

The first busy control showed 29 ordinary data writes, 58 metadata write requests
and 58 flush requests; the second showed 30, 60 and 60, plus additional write
traffic. Busy treatments showed 30, 60 and 60, plus the assist reads. One busy
treatment also contained two additional writes of unresolved attribution. Idle baseline and treatment windows also varied in background
journal/readahead traffic. This is exactly why total-write subtraction and task
names are not sufficient causal proof. Neither all writes nor all flushes are
assigned to Thermal Assist, and unexplained traffic is not silently excused.
Control-device journal/results traffic appears separately under device 8,16.

All 18 implemented lifecycle/backend cases completed their expected checks.
A direct native wait/deadline test returned 125 without receiving a target
file descriptor. Admitted supervisor SIGKILL left ARMED and a fresh-process
blocker. Private pidfd substitution retained ARMED, left the unrelated child
untouched, and reached CLEAN only after genuine authority was restored and the
owned child reaped. Unsupported-direct and wrong-topology refusal cases are
injected controls. The controlled root-view change rejected new acquisition and revoked the
original lease through its pre-pinned authority before cleanup; general changing-
mount/hot-plug proof remains outstanding.

## Initial experiment software validation and scope

The following counts and fingerprint record the initial research tree. Later
investigations and the separate automatic-summary correction have their own
validation evidence. The initial execution-source fingerprint is retained here
as a historical boundary.

The research contracts add three smoke groups. Together with unchanged probe,
native guard, admission/ownership/recovery, primary timing/publication and profile
integration checks, **28 affected groups passed**. The final three research groups
were rerun after the root-visibility witness was added. All **81 profiles** remain
valid, with five unchanged advisories; **409 Python files compile** and **34
integration imports** pass. Native x86-64 restrictions executed in the VM and
regular-file tests; unchanged guard/launch sources also compile as AArch64 objects.
Documentation links, import-cycle inspection and tracked/new-file whitespace
checks pass.

A full smoke rerun is not claimed: the committed 451-test/64-thermal-group baseline
is retained, and this change touches only opt-in research construction, research
checks and documentation. No production execution source, profile, guard or
lifecycle code changes. The existing builder's default behavior is retained and
its affected contracts are exercised. In particular, a completed research VM
with NO-GO is not reported as successful provider acceptance.

The complete `lvs_execution_source_v1` fingerprint remains **387 files**,
`52322da3875035aecd44deeba4e5c1c46121e02f22a40800bef2a924b7402ca5`.
Python research scripts under `scripts`, smoke tests and Markdown are outside that
scope. Their bytes are separately frozen in validation/evidence manifests; an
unchanged production fingerprint does not mean no research code changed.

This guest is a minimal switched-root Linux environment with a controlled writer,
not a full distribution/server boot. Hardware heating, responsiveness, CPU/GPU
interference and 6C/6T/28-drive operation remain Stage 2B-5 measurements.

## Causal follow-up on Fedora 7.2.9

The opt-in [causal mode](../scripts/storage_thermal_causal_probe.py) is selected
with `--causal` on the existing VM command. It accepts only the inspected
Fedora x86-64 `7.2.9-200.fc44.x86_64` kernel image with SHA-256
`5806981b246bfd6e0b9f8dd0ee5e5d2e35561aca66bdf8377f190c8abcc4b2cc` and
guest build ID `faa25318575065a0d5ae9ca29300268a42d91cbb`. Host and guest ran
that release. The host used an Intel Core Ultra 9 285K and QEMU 10.2.2 with
single-thread TCG, q35, one vCPU, 1 GiB RAM and no network or block passthrough.
Guest fio was 3.42, strace 6.13, CPython 3.14.8 and the native guard contract
was version 1. mke2fs 1.47.3 built the ext4 images. Two writable regular-file
images used emulated AHCI with 512-byte logical and 4096-byte physical sectors.
The target parent was `8:0` with a read-write MBR ext4 root partition at sector
2048. The separate control parent was `8:16`, used for the recovery journal,
trace records and results.

### Kernel path and instrumentation

Disassembly of the exact guest ELF, cross-checked with the shipped System.map,
shows `blkdev_read_iter` calling `kiocb_write_and_wait` before direct I/O.
For blocking I/O the latter jumps directly into
`filemap_write_and_wait_range.part.0`. Probing the public wrapper alone missed
this branch in the original experiment. When the mapping has resident pages,
the helper calls `filemap_writeback` and `__filemap_fdatawait_range`.
The former checks the mapping's dirty tag before invoking writepages. The latter
looks for writeback-tagged folios and can wait for their completion. The simple
synchronous direct-I/O path submits a bio and waits for completion. The read
path can also touch atime, subject to normal inode and mount policy.

`bdev_release` can synchronize and truncate the block-device mapping on last
close. Its `disk_flush_events` call handles media events and is distinct from
a block request carrying a cache-flush flag. The pre-mount buffered read/close
control demonstrated the last-close branch and page-cache deletion. Mounted
release recorded two whole-device openers at the inspected point, so that
branch did not run in these arms. The separate invalidation entry points
recorded zero hits. Their negative evidence is limited because they had no
dedicated positive invocation. The cache-deletion tracepoint and last-close
truncate probe did have positive controls.

The probes recorded entry arguments, mapping pointers, page counts, dirty and
writeback tags, returns, bio queueing and block issue/completion. Filesystem,
journal, page-cache and scheduling tracepoints supplied context. Every arm
reported zero buffer overruns and dropped events, and the final probe profile
reported zero missed probes. The trace used the guest monotonic clock with
bracketed markers. The widest marker bracket was 5.33 ms and the greatest
within-arm realtime-to-monotonic offset spread was 2.47 ms. The read
correlation uses PID, byte/sector range and ordered kernel events inside each
direct-I/O call, so it does not depend on sub-millisecond alignment between
strace wall time and the kernel clock.
See the kernel documentation for [ftrace buffer statistics](https://docs.kernel.org/trace/ftrace.html)
and [kprobe profiling](https://docs.kernel.org/trace/kprobetrace.html).

### Paired observations

One boot ran three alternating-order pairs each for idle, busy and dirty
conditions, plus one cancellation pair. Both arms opened and closed the same
parent, pinned the same executables and used the same control-disk journal and
output lifecycle. Each arm had at least two seconds of post-close observation.
Busy arms made 24 scheduled buffered 4 KiB writes each. Dirty arms made eight
before launch. Each arm used its own preallocated regular file. A separate
overlap control used the exact sectors of a known ext4 file extent.

| Condition | Raw assist reads per arm | Target write issues, control / assist | Target flush issues, control / assist |
| --- | ---: | --- | --- |
| Idle | 21 | 3, 2, 49 / 2, 0, 2 | 2, 0, 2 / 2, 0, 2 |
| Busy | 21 | 2, 2, 7 / 2, 2, 3 | 2, 2, 2 / 2, 2, 2 |
| Dirty | 21 | 2, 2, 4 / 4, 3, 3 | 2, 2, 2 / 2, 2, 2 |
| Cancellation | 5 | 0 / 2 | 0 / 0 |

Counts are request **issues**, listed in pair order within each arm type.
The busy and dirty writes scheduled by userspace are a separate measurement
from block requests. Control-device traffic was counted separately. A
35-second tail after the overlap control also contained target writes and
flushes. The dirty and cancellation counts leave some asynchronous traffic
unclassified. The count differences and the task name at issue time do not
establish its origin.

The nine completed assists achieved 6.993–6.998 IOPS at the 7 IOPS setting,
using 64 KiB, QD1, three seconds and `invalidate=0`. Across those runs and
the cancellation arm, all 194 successful target `pread64` offsets matched
bio submission, block issue and completion. The traced processes submitted
no non-read target bios. The syscall trace found no prohibited target
operations. It did show `POSIX_FADV_RANDOM`, a per-open-file readahead hint.
The first assist also issued 12 startup readahead requests in fio's exec
context, accompanied by ext4 file-cache additions, before its first raw
read. Later assists did not repeat that burst. This is startup I/O outside
the 7 IOPS raw-read budget. No worker cache truncation was observed on the
whole-device mapping. The observed worker truncations concerned a different
empty mapping.

Every guarded raw read entered the writeback-and-wait path. The whole-device
mapping had 16 resident pages, no dirty or writeback tags, and all calls
returned zero. No ext4 writepages or folio wait was nested in those calls.
Per-arm median helper time was 28–46 µs, with a 667 µs maximum. Median
target syscall latency was 0.782–1.026 ms and the maximum was 2.134 ms.
Busy-writer median buffered pwrite time was 0.554–0.605 ms in controls and
0.205–0.309 ms with assist. Its median start delay was 0.378–0.606 ms and
0.259–0.282 ms respectively. These small single-boot samples do not establish
an interference bound or a performance benefit. Combined traced child CPU
time was 0.597–0.783 seconds per complete arm and includes tracer overhead.

### Dirty extent, recovery and decision

At byte offset 54,669,312, a raw direct read over the physical sectors of a
dirty ext4 file returned the previous disk bytes. Its own whole-device
mapping stayed clean. A subsequent direct read through the file invoked
writeback on a different dirty mapping, reached ext4 writepages and
`folio_wait_writeback`, and issued a 4 KiB write at those sectors before
reading the new bytes. The positive file writeback call through the end of
its page wait took 409 µs. The following raw read saw those new bytes.
The control demonstrates read-induced persistence of a pre-existing
buffered write. It supplies no evidence of a new application write.

The paired comparison reused the accepted guard and durable recovery scope.
Cancellation recorded five reads, owned group cleanup and a normal mounted
release. The earlier mounted-VM native admission, deadline, supervisor-death
and uncertain-cleanup cases remain separate evidence, as do the rerun
native admission and recovery regressions. No post-close activity by a
traced worker was seen during the two-second windows.

The kernel can take the dirty/writeback branches on the **whole-device**
mapping. Dirtying a regular ext4 file does not produce that condition.
The research also has no causal identifier for all asynchronously issued
requests. The smallest further proof would be a separately reviewed
synthetic test that can demonstrate or exclude dirty/in-flight state on the
same whole-device mapping while the device is shared, with causal trace
correlation through writeback and last release. A provider contract would
then need an enforceable bound or explicit policy for the demonstrated
effects and startup reads, plus topology-transition qualification. If
that bound cannot be enforced, an existing-file or filesystem-aware
method needs its own proof, including its own potential writeback effects.
This leaves the provider decision **INCONCLUSIVE**. Physical thermal
effectiveness and deployment interference remain separate work.

The follow-up passed 29 affected regression groups, 81 profile validations
with five unchanged advisories, 410 Python compilation checks and 35
integration imports. Native x86-64 guard, admission, cancellation and
recovery checks passed. The Stage 2B-3 451-test full-suite result and the
earlier AArch64 object checks remain baseline evidence because the
production and native sources did not change.

## Final targeted mapping and startup investigation

The final opt-in command adds `--targeted` to `--causal`. It reuses the same
kernel build, tools, switched-root fixture, ext4 root and control disk. A
third AHCI disk with a nonce-bound `LVW-` serial contains exactly 64 KiB of
disposable backing data. QEMU limits its writes to 4096 B/s. This disk is
unmounted and separate from the root and control disks. It is a kernel-mapping
proof fixture and supplies no additional mounted-filesystem qualification.
The [mapping probe](../scripts/storage_thermal_mapping_probe.py) is the only
new code allowed to open it writable, after verifying the VM, serial, topology,
size and block descriptor. Its writable descriptor stays in the research
supervisor. The unchanged guard receives an independently opened
`O_RDONLY|O_DIRECT` descriptor and retains its fixed fio arguments.

A kprobe on the exact kernel's `blkdev_llseek` records mapping identity,
resident pages and dirty/writeback tags without issuing a test read. Thus
the required state is observed before guarded execution. Additional
`do_writepages` and readahead probes have demonstrated positive hits.
All trace buffer loss counters and kprobe misses were zero in these cases.
The native guard source and production openers are unchanged.

| Fixture state before launch | Observed mapping state | Guarded behavior |
| --- | --- | --- |
| Clean | 0 resident pages, tags 0 | Seven 64 KiB reads, zero target writes |
| Buffered raw fixture write | 16 pages, dirty tag `0x2` | First read induced one 64 KiB write through `filemap_writeback` and `do_writepages`; write completed before its read |
| Natural background writeback | 16 pages, writeback tag `0x4` | First read waited 10.760964 s for an already-issued write; then issued one read despite the intervening cancellation request |

Only the fixture writer generated the buffered dirty data. The trace and
syscall record distinguish that application write from its later persistence
in the guarded reader's kernel context. The dirty-case first helper call
lasted 950 µs. Later calls saw a clean mapping. The in-flight control used
guest-only dirty-expiration/writeback sysctls of 100 centiseconds and natural
background writeback. No sync, cache dropping or write command was sent to
the guard. Its pre-existing 64 KiB write issued at guest monotonic 25.838648 s,
the writeback snapshot was at 25.929413 s, and the read entered its wait at
26.310568 s. The write completed at 37.071406 s and the read followed at
37.071794 s. SIGTERM was delivered while the read syscall was waiting.
The configured one-second fio run took 11.316 s through owned process cleanup.
This is an in-flight syscall, with no evidence of a new native admission
after revocation. Kernel I/O already in progress can outlive a userspace stop.

Each case reaped its traced process group, closed both fixture descriptors,
observed last-release synchronization/truncation, and resolved its separate
control-disk recovery scope only after cleanup. No requests to the mapping
fixture appeared during the subsequent 2.008–2.012 second observation windows.
This records a finite observation horizon. It supplies no universal bound on
future deferred kernel work or crash recovery on hardware.

### Startup attribution and enforceable budget

The original 12 requests were independently matched against the original
image's ext4 extents using read-only debugfs inspection of its regular image
file. All 4,022,272 bytes mapped to `libtcmalloc_minimal.so.4`, `libmvec.so.1`
and `libstdc++.so.6`. The final cold launch reproduced 12 requests and the same
byte count. They issued within 32.820 ms, from guest 11.055672 to 11.088492 s,
before the first raw read at 11.374389 s. Sector extents and page-cache inode
events identify those libraries. Readahead stack traces show
`page_cache_ra_unbounded -> do_page_cache_ra -> do_sync_mmap_readahead -> filemap_fault`
under userspace page faults during fio initialization. This is filesystem
I/O for loading the worker's libraries, causally attributable to launching
the assist. The root disk is also the synthetic workload target.

The peak was five outstanding startup read requests, despite QD1 for the
subsequent fio workload. The next warm launch had zero pre-workload target
read requests. Cache reclamation, memory pressure, library replacement or
a fresh boot can make the cold condition relevant again. Those recurrence
conditions were not individually exercised. There is no runtime invariant
in the current method that guarantees permanently resident executable pages.

Accounting also includes 5,488,640 root-disk bytes read in the supervisor
while pinning/hashing guard and fio, 2,351,104 bytes while the research-only
strace loads unwind libraries, and 12,288 bytes of root metadata I/O issued
in kworker context. All 37 pre-workload requests total 11,874,304 bytes.
The supervisor and worker-library reads add 9,510,912 bytes of identifiable
production-shaped initialization. The strace component is
instrumentation overhead. Metadata is retained as separately classified
initialization-window traffic. These counts exclude the paced raw reads and
control-device evidence writes.

Neither `rate_iops=7` nor `iodepth=1` constrains these initialization reads.
Preloading libraries, moving tools or warming cache does not eliminate the
initial access cost. Any future budget would need to account for and enforce
all initialization access before descriptor release, including parent-side
provenance reads, and induced kernel work. A cgroup/provider-level budget
would itself need separate proof of coverage and interference. No such
budget was implemented or qualified here.

### Finite decision and next alternative

The proposed method receives **NO-GO** under the existing contract. The
unchanged read-only guard blocks worker mutations but cannot prevent the
demonstrated writeback of pre-existing dirty whole-device data. Non-exclusive
access also cannot guarantee a clean mapping for the entire run. Startup
activity exceeds the nominal read budget and QD1 with no enforced encompassing
limit. Accepting those effects would require a newly reviewed contract and
additional mechanisms. This investigation stops at that boundary.

The next alternative is a separately designed existing-file or
filesystem-aware experiment, with initialization included in its I/O budget.
Buffered reads may avoid this raw-mapping synchronization path but need their
own physical-activity/cache evidence. The earlier direct-file control already
shows why direct file reads also require writeback qualification. No provider,
active-drive eligibility or physical thermal acceptance follows from this work.

## Final combined-task software validation

The final frozen production/research source passed **457/457 smoke tests**.
The separately selected **30 affected groups** cover five research contracts
and the relevant native guard, admission, recovery, ownership, cancellation,
primary timing and publication checks. The new automatic-summary group
exercises 12 representative stage/configuration combinations, an existing
profile without Thermal Assist and all seven standard profiles with 41 stages.
All **81 profiles** validate with five unchanged advisories; **412 Python files**
compile and **38 integration imports** pass. x86-64 guard execution and AArch64
guard/bootstrap compilation pass, along with import-cycle, documentation-link
and diff checks.

The first full-suite attempt overlapped edits to the research harness and failed
a source-inspection assertion. It is retained as an invalid frozen-tree attempt.
The successful full run used frozen source and tests. Production changes are
confined to two automatic-summary presentation modules. Profile JSON, backend
eligibility and lifecycle execution remain unchanged.

The current **387-file** execution-source fingerprint is
`2361ffbbaeb7bb66e24f727d99a6a946c542a2a0922ec31e5de595933d5153b4`.
The research scripts, tests and documentation have separate file hashes in the
final evidence manifest. The guest's provisional `INCONCLUSIVE` field is retained
as emitted by the experiment. The reviewed provider decision above incorporates
the raw traces and startup attribution and is **NO-GO** for the current method.
