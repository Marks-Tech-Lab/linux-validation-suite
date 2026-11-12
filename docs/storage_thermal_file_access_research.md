# Stage 2B-4: bounded existing-file access research

**Decision: NO-GO for the proposed repeatable backing-device activity contract
on ordinary, potentially cached existing files.** On the tested ext4 kernel,
`RWF_DONTCACHE` produced repeated device reads when the approved range started
cold. It did not evict an already cached range or produce additional device
reads from it. Buffered reads likewise reused cached data. Cache eviction is not
authorized, and logical read success is not physical thermal coverage.

This is a separate experiment from the [rejected raw-device method](storage_thermal_active_access_research.md).
Neither negative result changes the accepted inactive-HDD provider. Production
eligibility, its exclusive opener, native block guard, configuration, profiles,
and primary verdict policy are unchanged. No production file provider exists.

## Fixture, versions, and source authority

[The harness](../scripts/storage_thermal_file_probe.py) uses the existing private
QEMU image builder. It accepts regular tool/kernel files, never a target device,
file list, arbitrary fio arguments, QEMU overrides, networking or passthrough.
All writable images are newly created regular files under a retained
`/tmp/lvs-wave2a-*` bundle. No host filesystem is mounted into the guest.

- QEMU 10.2.2, Q35/TCG, one vCPU, 1 GiB RAM.
- Emulated NVMe with a session-specific serial, 512 MiB MBR-partitioned ext4
  root, mounted read-write; partition starts at sector 2048.
- Independent AHCI control disk, 128 MiB ext4 partition, mounted at `/control`.
  Recovery journals, reports and traces go there; `/tmp` is tmpfs.
- Forty explicitly named 64 KiB regular files, prepared offline with
  `mkfs.ext4 -d`; one sparse control. No directory scanning or personal files.
- Linux `7.2.9-200.fc44.x86_64`, CPython 3.14.8, strace 6.13,
  mke2fs/libext2fs 1.47.3, fio 3.42.

The exact kernel SHA-256 is
`5806981b246bfd6e0b9f8dd0ee5e5d2e35561aca66bdf8377f190c8abcc4b2cc`;
ELF build ID `faa25318575065a0d5ae9ca29300268a42d91cbb`.
The fio binary SHA-256 is
`444ba07aeaa89d0f2f9ecdd2577f6846401d8dcbc54d6dedce96120cb95c9378`.
Its adjacent `engines/sync.c` SHA-256 is
`af7609913c35877219f7e5e0ffd0025c6fac42e33ed527abd27025e4a4e2ed63`.
Both source and actual `--enghelp=pvsync2` were inspected. With buffered I/O,
`uncached=1` adds `RWF_DONTCACHE` (`0x80`) to `preadv2`; strace verified this on
each measured read. The old strace flag decoder prints `RWF_???`, so its label
alone is not the capability proof. Unknown flags explicitly returned
`EOPNOTSUPP`; there is no silent fallback.

The [experimental wrapper](../scripts/storage_thermal_file_guard.c) is a separate
x86-64 VM research entrypoint. It reuses the unchanged guard's privilege and
restriction primitives, adds mutation denials, checks the regular descriptor,
native monotonic admission deadline and owned tracer/supervisor chain, then
executes pinned fio with fixed arguments. It does not change or invoke a new
production block-guard mode. Trusted fio remains required; this is not a general
sandbox for arbitrary executables. Native v2 block admission remains separately
covered by its existing regressions, not qualified for regular files by this
wrapper.

## Authorization, privacy, and lifecycle

The VM checks its boot nonce, QEMU identity, NVMe/control serials and sizes,
partition ancestry, actual root filesystem and mount namespace. Corpus names
must occur in the session manifest. An `O_PATH` directory descriptor and
`openat2` BENEATH/NO_SYMLINKS/NO_MAGICLINKS/NO_XDEV constrain acquisition.
`O_RDONLY|O_NOATIME|O_CLOEXEC` is required. The opened inode, filesystem, size,
link state and session are recorded and passed to the native check.

This pins an opened file; it does not prevent a concurrent owner from modifying
it. The synthetic mutation tests deliberately change a file after a genuine
read, then stop the owned worker. They do not prove arbitrary production file
stability or an independently race-free user-file selection policy.

Reports contain opaque file IDs, identities, extents, counters, timings and
statistics, not contents. strace uses `-s 0`. The privileged supervisor acquires
NOATIME descriptors before dropping the worker to UID/GID 65534 with zero
capabilities, seccomp and no-new-privileges. Corpus atime was unchanged in the
measured cases. A separate negative control proves an unprivileged non-owner
gets EPERM for NOATIME while an ordinary read-only open succeeds. No production
permission elevation or user-file access policy is approved.

Existing `OwnedProcess` native creation/registration/reaping is reused. The
auxiliary supervisor enters its private cgroup before exec release. Durable
`RecoveryScope` intent precedes corpus opening and worker execution. Its control
volume state is resolved only after descriptor close and confirmed owned-group
cleanup. Restart inspection follows release of the original exclusive scope;
an earlier harness check incorrectly ran while that lock was still held and
was corrected without changing production recovery.

## Declared budgets and their actual scope

Budgets were established before the comparisons:

| Resource | Research limit |
| --- | --- |
| Logical worker | one job/thread, QD1, 64 KiB, 7 IOPS, two seconds |
| Target cgroup I/O | 2 MiB/s reads, 64 read IOPS |
| CPU | 25,000 / 100,000 microseconds, one quarter of one CPU |
| Memory | 192 MiB high, 256 MiB maximum |
| Processes | 16 |
| Read-byte stop budget | 32 MiB per case, 128 MiB per VM campaign |
| Research provenance deadline | 60 seconds |
| Supervisor timeout | 90 seconds; VM watchdog 300 seconds |

The byte budgets are checked after each finite case, not hard instantaneous
caps. The largest observed aligned guest second contained 2,359,296 whole-target
read bytes, above 2 MiB, including kworker requests. That observation does not
isolate cgroup enforcement from other target activity or establish a hard burst
bound. Applied `io.max` values and charged counters are retained; isolated
rate-enforcement stress was stopped at the feasibility failure. Initial
control-only startup charged 5,750,784 bytes and
113 read I/Os; first fio startup charged additional executable/library activity.
These costs are retained, not hidden as an unreported warmup. Peak cgroup memory
over the four completed batches was 46.52 MiB; CPU throttling counters increased.
Memory/pids exhaustion and isolated slow-I/O stress campaigns were not pursued
after the warm-cache feasibility failure. Configured limits alone are not proof
of their failure-path enforcement.

The accepted production executable-snapshot one-second budget failed when
hashing the 5.54 MB fio binary under this I/O throttle. That failed run retained
ARMED and performed no workload reads. Production was not changed. The separate
research path pins image-preparation digests and checks the open executable
before/after hashing within its already declared 60-second startup allowance;
the first measured hash took about 2.55 seconds. This is research provenance,
not production readiness evidence or approval to loosen its timeout.

Controller boot, tracing setup and initial native-helper preparation are
separately traced outside the auxiliary cgroup. Filesystem background/journal
I/O need not be charged to the triggering reader. Consequently these tests do
not prove a hard aggregate budget for all indirectly attributable kernel work.
Available memory/reserve, CPU capacity and required controllers are checked
independently; resource/missing-capability regression fixtures cover low/high
capacities without turning this fixed VM proof into a production allocation
policy or a scalability acceptance claim.

## Matched comparisons and physical-activity observations

Three repetitions per mode use distinct, identically prepared approved 64 KiB
ranges, with alternating control/buffered/transient order. Cold means mincore
observed zero resident pages before access; no cache dropping was used. Warm
means one explicit, counted 64 KiB pre-read populated all 16 pages. Subsequent
fio reads repeatedly cover that same approved range.

| Initial range state | Mode | Completed logical reads per trial | Worker data BIOs per trial | Resident pages after |
| --- | --- | --- | --- | --- |
| Cold | Startup control | 0 | 0 | 0 |
| Cold | Buffered | 14 | 1 (64 KiB) | 16 |
| Cold | DONTCACHE | 14 | 14 (896 KiB) | 0 |
| Warm | Startup control | 0 | 0 | 16 |
| Warm | Buffered | 14 | 0 | 16 |
| Warm | DONTCACHE | 14 | 0 | 16 |

All three repetitions agree. Warm cases contain one 64 KiB **Python warmup**
BIO; it is not fio activity. All 84 warm workload reads were logical/cache
activity. Cold DONTCACHE's 42 worker data BIOs reconcile with 42 successful
`preadv2` calls, block request issues and completions on the approved extents.
The cold buffered cases generated three worker data BIOs in total. Block-layer
activity on an emulated NVMe device is not guaranteed NAND access, measured
heating, or real NVMe/controller compatibility.

FIEMAP with flags zero records extents without forcing synchronization.
Attribution uses those extents plus the partition offset on the validated
fixture disk. It does not freeze extents or qualify another filesystem. Trace
markers bracket wall/monotonic correlation. Generic file-read/filemap probes,
cache insertion/deletion and block submission/completion provide positive
visibility. Trace overruns, commit overruns and dropped-event counters were
zero in the accepted batches. Whole-device events are retained separately
from file-range/worker-attributed events.

Corpus worker writes were not observed in these comparisons. Kernel ext4
journal writes and flushes do occur on the mounted target, including during
otherwise read-only cases. They are not automatically labeled either direct
worker mutations or wholly unrelated activity. Executable loading, filesystem
metadata and background writeback remain possible contributors. The trace
includes final close and one additional second; it cannot prove absence of
later deferred writes, reclamation or discard. This is not a universal
no-writeback proof.

## Negative controls and finite stopping point

Eleven lifetime cases plus ten recovery cases completed:

- Native write/truncate/fsync/cache-discard attempts rejected; unsupported
  preadv2 flag returned EOPNOTSUPP; NOATIME permission negative demonstrated.
- Expired and delayed-expiry admission, wrong inode, wrong device and missing
  NOATIME rejected with exit 125 and zero successful corpus reads.
- Replacement, rename, unlink, truncation, modification and changed mount
  namespace were injected after one observed read. Workers stopped; actual
  ownership cleanup permitted CLEAN. Changed namespace refused reacquisition.
- Cancellation after a real read stopped the owned group. Private pidfd
  substitution refused signaling and CLEAN(false), and independent inspection
  remained blocked; restoring the saved authority and genuinely reaping the
  worker then allowed CLEAN. The worker could finish during that deliberately
  slow diagnostic, which does not erase the intervening uncertainty.
- Sparse-file control completed 14 reads with zero file-data BIOs, another
  demonstration that byte counts do not prove physical coverage.
- Killing the supervisor after a real read required private-cgroup descendant
  termination/reaping. Independent inspection retained the original ARMED
  obligation even after the cgroup became empty; no synthetic CLEAN was issued.
- ENOSPC/EIO before durable intent prevented corpus admission. The persistent
  anchor/missing journal failed closed in a fresh process. ENOSPC during CLEAN
  publication left ARMED after confirmed worker cleanup and blocked fresh entry.
- Ordinary confirmed cleanup yielded CLEAN and an unblocked fresh independent
  inspector. These process-restart observations are not power-loss durability
  qualification for physical media or other filesystems.

An earlier 38-case VM exceeded its watchdog. Its images/logs are preserved;
29 complete-looking records were extracted only after disabling debugfs
checksum verification on a copied control image. Those records are provisional,
not accepted dirty/concurrent comparison evidence. Smaller completed batches
replaced the necessary cold/warm and lifecycle evidence. The new host verifier
requires the exact campaign inventory, expected rejection/cleanup outcomes and
explicit recovery blockers; each completed case is separately fsynced and
durably recorded before the next one.

Following the decisive warm-cache result, new dirty/concurrent comparison and
slow-I/O/memory/pids stress batches were stopped rather than extending the
campaign. Their reusable cases remain in the harness, explicitly unqualified.
Dirty-page and concurrent-writer causality, post-unlink reclamation, arbitrary
blocking-read cancellation latency and total indirect-I/O accounting therefore
remain incomplete for this new method. Existing synthetic primary-isolation
regressions still pass; they do not fill these research gaps.

## Reproduction and evidence

From the repository root, supply regular, independently qualified tool paths:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m scripts.storage_thermal_file_probe \
  --campaign access-cold \
  --fio /path/to/fio-3.42/fio --old-fio /path/to/fio-3.42/fio \
  --strace /path/to/strace --kernel /path/to/exact-vmlinuz \
  --python /path/to/python3.14 --guard /path/to/accepted-block-guard
```

Repeat with `access-warm`, `lifetime-a`, and `lifetime-recovery` for the completed
batches. The inherited builder requires `--old-fio` and `--guard`; those binaries
do not authorize a regular-file production mode. Other campaigns are retained
for reproducibility, not a recommendation to resume an indefinite investigation.
The automatic result envelope intentionally remains INCONCLUSIVE and cannot
grant provider eligibility. The final gate decision above comes from reviewing
the cold/warm comparison and its limitations.

Accepted local evidence:

| Batch | Retained bundle | Cases |
| --- | --- | --- |
| Cold | `/tmp/lvs-wave2a-v7tqshtj` | 9 |
| Warm | `/tmp/lvs-wave2a-cdlso66u` | 9 |
| Lifetime | `/tmp/lvs-wave2a-r8uz1fvs` | 11 |
| Recovery | `/tmp/lvs-wave2a-1gda4ldm` | 10 |

Each contains original writable images, host command/manifests, exact copied
guest source, console, traces, syscalls and per-case recovery/evidence records.
`/tmp/lvs-file-research/analysis.json` records the independent syscall/BIO/request
reconciliation; its final manifest records file and evidence hashes. Earlier
failed attempts remain beside it. Temporary paths are local evidence locations,
not published or retained hardware-acceptance artifacts.

Four new smoke groups cover fixture/capability refusal, attribution separation,
incomplete/duplicated evidence rejection and native wrapper argument denial.
Thirty existing affected research/safety groups pass, including native v2
admission, durable recovery, owned-process authority, cancellation, profile/UI
preservation and independent publication. The two-second primary regression
recorded 2.002017 seconds with genuine callbacks at 0.001394 and 1.001571 seconds
despite a ten-second auxiliary initializer. Another delayed-creation regression
recorded 2.002282 seconds with two callbacks. No timestamps or samples were
fabricated. The committed 457-test baseline remains applicable to unchanged
production code; the new groups were run separately rather than claiming a new
full-suite total. All 81 profiles remain valid with five existing advisories.
All 414 Python files compile and 40 integration imports pass. The import graph
has no new cycles; Markdown/relative links and tracked/new-file whitespace
checks pass. Unchanged native guard/bootstrap AArch64 objects compile with Zig;
the guard build suppresses a sign-comparison warning in Zig's musl CMSG macro,
not a change to guard source. The new regular-file wrapper is qualified only
on the tested x86-64 fixture.

## Next boundary

Do not enable a provider or silently switch back to raw access. A different
research contract would need to accept and truthfully report cache-dependent
coverage, or establish a separately approved way to obtain a useful cold corpus
without scanning private data, writing workload files or evicting existing
cache. No such method is approved here. Btrfs compression/CoW/repair, real NVMe,
dm-crypt, RAID and other topologies are untested. Btrfs research is not the next
automatic gate after this ext4 NO-GO. Physical thermal effectiveness, primary
interference on hardware, power-loss durability and many-drive scalability
remain separate acceptance work.
