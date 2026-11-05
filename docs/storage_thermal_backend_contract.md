# Storage Thermal Assist: Stage 2B-1

Historical Stage 2B-1 scope: versioned contracts and a constrained fio launch
foundation, software-validated with synthetic devices. It did not implement a
standalone runner, profile/UI integration, physical thermal acceptance or active
storage. The subsequently authorized [Stage 2B-2 standalone runner](storage_thermal_assist.md)
is separate from the foundation observations below. Preserve the
[Wave 2A evidence and revised plan](storage_thermal_wave2a_feasibility.md).

## Contracts and provisional policy

[lvs_storage_thermal.py](../Modules/lvs_storage_thermal.py) defines these v1
snake_case contracts, rejecting unknown configuration/policy versions:

| Contract | Scope |
| --- | --- |
| `lvs.storage_thermal.config` | Selection, percentage/advanced rates, finite duration, read size, monitoring, ordinary scheduling |
| `lvs.storage_thermal.readiness` | Source/hardware context, backend observations, per-device identity/state/reasons, commands |
| `lvs.storage_thermal.result` | Counters, identity/provenance, stop reason, exit, cleanup/publication and monitoring coverage |
| `lvs.storage_thermal.guard` | Native stderr launch observation: PID, UID/GID, groups, capabilities and installed kernel policy |

States: discovered, selected, blocked, ready, running, completed, failed,
cancelled, incomplete, skipped. System devices cannot have executable states.
Authoritative physical eligibility still needs a resolver; a supplied state is
not proof. Foundation readiness always says **BLOCKED**, empty commands and
`launch_implemented=false`. Candidate eligibility is separate and never a
workload PASS. Existing original/effective artifacts will be reused at integration.

Result success requires completed duration, exit 0, identity/provenance and guard
confirmation, read-byte/operation reconciliation, zero errors/write/discard/flush
counts, zero outstanding descriptors, and confirmed cleanup/terminal publication.
Kill, timeout, safety stop, missing evidence and malformed counters reject success.
Future parent integration must own exit, provenance, cleanup and persistence
confirmation, rather than trust child assertions. Successful activity does not
establish heating or thermal safety; those fields default to `unmeasured`.

`thermal_pilot_v1` defines **provisional**, deliberately limited ceilings:

| Class | IOPS ceiling | Bandwidth ceiling | 50% at 64 KiB | System 25% at 64 KiB |
| --- | ---: | ---: | ---: | ---: |
| HDD | 30 | 2 MiB/s | 15 IOPS | 7 IOPS (7.5 requested) |
| SATA/SAS SSD | 128 | 8 MiB/s | 64 IOPS | 32 IOPS |
| NVMe | 256 | 16 MiB/s | 128 IOPS | 64 IOPS |

Scale the lower of IOPS and bandwidth/read-size limits, round down to whole IOPS
and retain requested/effective values. Nonzero sub-IOPS requests reject instead
of rounding upward or introducing bursts. Zero percent means no assist I/O.
Advanced rates are a distinct mode bounded by both class ceilings. Per-device
percentage overrides win over 50% ordinary / 25% system defaults. Unknown classes
block; no capacity/model proxy or per-drive throughput benchmark is used.
These are pilot bounds, not rated-performance percentages, calibrated heating,
or physical safety acceptance. Hardware pilots may revise the versioned policy.

Contract bounds: power-of-two read sizes 4 KiB–1 MiB, QD1, ordinary scheduling,
explicit duration 1–86400 seconds (default 120). Not every combination is
physically accepted. Monitored operation has no invented universal temperature
threshold. Bounded unmonitored operation requires an explicit approval reference.

Selection intent defaults to All Eligible Internal Drives, with all-internal,
SATA/SAS, NVMe, HDD, SSD and individual groups. Automatic groups exclude USB,
virtual, loop and logical devices. Individual selection never bypasses identity,
topology or safety. System devices remain visible at 25% and blocked. This stage
defines configuration, not inventory selection or a UI.

## Narrow native launch guard

[storage_thermal_guard.c](../native/storage_thermal_guard.c) is justified by the
Wave 2A BLKFLSBUF witness. It is not an I/O engine, general sandbox, setuid utility,
package installer or automatic privilege escalation mechanism. Its fixed protocol
accepts a preopened trusted fio ELF descriptor, non-root UID/GID, expected block
major/minor and size, read size, IOPS and seconds. **No device pathname, arbitrary
fio option or job file is accepted.**

Before fio execution it:

1. Validates stdin block type, major/minor, exact size, logical alignment,
   O_RDONLY and O_DIRECT; rejects block stdout/stderr.
2. Pins the supplied ELF descriptor for fexecve, rejects scripts and setuid/setgid
   executables, and closes all other inherited descriptors above stderr.
3. When root, clears supplementary groups and drops real/effective/saved UID/GID
   to explicit non-root IDs. Ordinary users retain their existing supplementary
   groups. Effective/permitted/inheritable and ambient capabilities are cleared.
4. Sets no_new_privs and installs a mandatory seccomp policy. Unknown architecture
   and alternate x86 syscall ABI reject. Installation failure is fatal.
5. Allows only BLKGETSIZE64, BLKSSZGET and BLKPBSZGET ioctl requests. Everything
   else, including high-word aliases, returns EPERM across duplicated descriptors
   and descendants. Blocks fsync/fdatasync/sync/syncfs, supported sync-file-range,
   fallocate, alternate AIO/io_uring interfaces, and fadvise except RANDOM.
6. Constructs the fixed direct psync randread command: block type before stdin
   filename, QD1/one job, explicit invalidate=0 and disabled creation/allocation/
   flush options. stdout carries reports; no output or device path is supplied.
   Executes with a clean fixed environment.

The [backend specification builder](../Modules/lvs_storage_thermal_backend.py)
verifies the supplied fio descriptor against capability hash/inode evidence and
rechecks guard identity. Callers must use its clean launcher environment, without
LD_* or FIO_* customization. The guard protocol's maximum rate never authorizes
exceeding a class policy; the future planner enforces the effective plan.

Assumptions: trusted guard, fio, loader/libraries, kernel, supervisor, initial
descriptor provider and evidence files; executables must not be concurrently
rewritten. This is not confinement for arbitrary programs, hostile root, injected
code, arbitrary filesystem writes or descriptor transfer after startup. Target
data-write syscalls fail through the read-only descriptor; ioctl/flush/cache
restrictions add independent enforcement. Trusted fixed psync must preserve
direct flags and reviewed data flow. Firmware background activity is not excluded.

The future opener must independently prove serial/WWN identity, inactive topology,
exclusive claim and post-open identity, and retain ownership until cleanup. This
guard cannot infer those properties from F_GETFL and implements no opener.
Permission, seccomp or identity failures never fall back to a pathname/root fio.

## Runtime capability and portability

Uses existing native compiler-command conventions, libc/Linux headers and no new
Python dependency. Linux little-endian x86-64 and AArch64 compile; actual runtime
proof is **x86-64 only**. Cross-compilation is not AArch64 runtime acceptance.

Runtime inspection hashes executables, checks fio block-filetype/psync support,
then exercises real guard enforcement on a private regular-file descriptor.
This accesses no device and does not replace synthetic block qualification or
physical eligibility. Missing binaries/kernel proof are unavailable; missing
features unsupported; other capable fio families untested. Only proven fio 3.42
behavior is enabled; fio 3.40 is rejected without fallback. Root inspection callers
must return to an explicit regular operator session. No compilation or package
operation occurs during capability inspection.

## Synthetic proof and evidence

[storage_thermal_guard_probe.py](../scripts/storage_thermal_guard_probe.py) reuses
Wave 2A's disposable QEMU builder through optional guest/verifier hooks. Default
Wave 2A behavior is preserved. Automated smoke checks never start QEMU or access
a host block device. The research probe accepts no host-device argument.

Final evidence: `/tmp/lvs-wave2a-8pewsg1j/`, including tool hashes, full per-process
strace, guard observations, fio JSON, rejected descriptors, negative controls,
cleanup observations and writable synthetic image. Linux 7.2.9 x86-64, fio 3.42,
strace 6.13, unprivileged QEMU TCG; no host-device passthrough.

| Case | Observation |
| --- | --- |
| Normal | 90 aligned 64 KiB reads; 30.0 IOPS over 3.000 s; exit 0; total interval 3.627 s |
| Cancellation | 22 reads; exit 128; group reaped in 1.309 s total; no SIGKILL |
| Mutation controls | 17 ioctl denials per policy case, including original/duplicated descriptor; allowed geometry query succeeds |
| Inherited writable block descriptor | fd 77 closed before policy execution; no target write |
| Wrong identity, writable/buffered input, block output | Exit 125 before fio reads |
| fio 3.40 | Parser rejection; no target reads |
| TERM-ignoring sleeper without device descriptors | SIGKILL escalation, reaped in 3.032 s; never completed-work PASS |

Controls cover BLKFLSBUF, discard, zeroing, RO setting, partition reread,
SCSI/NVMe passthrough request numbers, high request bits, cache discard and
asynchronous-I/O setup calls. The filter also denies io_submit and io_uring
enter/register; those are covered by policy inspection rather than separate
live syscall controls. Forbidden harmless BLKROGET demonstrates denial
beyond merely lacking mutation privilege. Normal/cancel traces have no target
mutation or unknown target operation. All groups were reaped and owned descriptors
closed. Entire image hash before/after:
`eeca4a419d2c537e0eb24ec08925decf2c6fbfb95e64e98c185a9a369bab0a86`.
Guard executable SHA-256:
`7045ba6fe461d0e8ce412dcbf3a11427c605298e0a27a1c5242b0fcec29563f5`.
Guest PID1 intentionally exits after publication; its kernel panic is fixture
shutdown, not a drive failure.

fio reported 1.500% user / 0.800% system CPU in the traced single-vCPU VM. This is
not physical-host overhead or incremental guard cost; elapsed time includes
startup/tracing. No 28-drive or CPU/GPU interference acceptance is inferred.
Finite fio runtime and parent deadlines cannot guarantee timely termination of
uninterruptible kernel I/O. Cleanup requires actual reaping/closure.

```sh
gcc -O2 -std=c11 -Wall -Wextra -Werror native/storage_thermal_guard.c -o /tmp/lvs-thermal-guard
python3 scripts/storage_thermal_guard_probe.py \
  --fio /absolute/path/to/fio-3.42 --old-fio /absolute/path/to/fio-3.40 \
  --strace /absolute/path/to/strace --kernel /absolute/path/to/compatible/vmlinuz \
  --python /absolute/path/to/system/python3 --guard /tmp/lvs-thermal-guard
```

## Next approval boundary

Stage 2B-2 must implement authoritative targets, exclusive descriptor ownership,
staggered duration-based supervision, reliable temperature binding and bounded
unmonitored approval, original/effective evidence, per-drive/emergency stop,
parent deadlines and terminal persistence. No CPU core is reserved. The 6C/6T,
24 HDD + 2 NVMe + 2 SATA SSD case has deterministic planning coverage only.

CLI/TUI/O integration, physical pilots, system/mounted drives, ZFS, mdraid,
device-mapper and hardware RAID require separate approvals/proofs. Logical reads
never imply independent member heating. Storage Benchmark commands, preparation
writes, capability policy and execution remain unchanged.

## Stage 2B-3: standard-profile integration requirement

Approved future integration scope, verified read-only at commit
`412cd151a4d42990e52cc43c17380ae13d8e1a5f`:

| Active profile | Stages to request Thermal Assist |
| --- | ---: |
| `profiles/PL Validation.json` | 4 |
| `profiles/PL Validation 4hr.json` | 4 |
| `profiles/PL Validation 6hr.json` | 4 |
| `profiles/PL Validation 12hr.json` | 8 |
| `profiles/PL Validation 24hr.json` | 16 |
| `profiles/QA System Test Short v2.json` | 4 |
| `profiles/Power Test 5hr.json` | 1 |
| **Total** | **41** |

Do not edit these profiles until the standalone runner and concurrent stage
execution are implemented and software-validated. Stage 2B-1's blocked foundation
does not satisfy that prerequisite. Then request Thermal Assist in all 41 stages
alongside their existing workloads, with:

- All Eligible Internal Drives; 50% ordinary and 25% internal boot/system intent.
- USB, virtual, loop and logical devices excluded from automatic groups, without
  bypassing any physical-identity, active-device, backend or monitoring restriction.
- Duration inherited from the existing stage, without truncating it or extending
  another workload. The current foundation's 120-second configuration default is
  not an override of a profile's stage duration.
- Automatic scheduling that resolves to ordinary Linux scheduling, shared
  supervision, rate limits and staggered startup, prioritizing low CPU/GPU
  interference. No automatic core reservation or complex affinity balancing.
- Existing monitoring safeguards retained, especially for unattended runs.

Profile/stage editing and shared run-local CLI/TUI Stage Overrides, including
the TUI O workflow, must expose adjustment and disabling. An operator must be able
to run controlled storage-off comparisons without modifying the saved profile.
Persist the original request, effective overrides and actual storage coverage.

If no eligible target or supported backend exists, show requested storage as
blocked/unavailable with specific reasons. Offer an explicit choice to continue
the original CPU/GPU test without Thermal Assist, or cancel. Do not silently skip
storage, fabricate thermal coverage, or classify missing auxiliary support as a
CPU/GPU hardware failure. Persist the operator's continuation decision and scope;
unattended execution must have an explicit preauthorized auxiliary-failure policy,
otherwise remain blocked. Do not hide actual I/O or safety failures as missing
capability or use this choice to weaken emergency-stop behavior.

Short unmonitored approval must be bounded to its approved duration and device/
configuration scope. It must not renew at stage boundaries or automatically
authorize an entire multi-hour profile. A longer unmonitored run needs its own
explicit bounded approval; it still cannot claim monitored thermal safety.

Investigate worker retention across adjacent stages rather than promising it.
Reuse requires unchanged resolved physical identities, compatible effective
configuration, valid backend/ownership evidence, continuing monitoring and
unexpired approval. Revalidate at every boundary; stop/restart if compatibility
cannot be established. Do not simply extend fio runtime or drop duration bounds.
Retention needs bounded supervision plus per-stage counter snapshots, telemetry,
readiness, original/effective settings, start/end timestamps and completed-activity
reconciliation, with no double credit or inter-stage activity hidden from reports.
Reused-worker stage completion must remain distinct from final process exit and
cleanup. Cancellation and safety stops must work during boundary transitions.
Measure startup interference before accepting added retention complexity.

Stage 2B-3 regressions must verify the seven exact active paths and all 41 stages,
load/validation/replay, inherited durations, settings, shared overrides and
storage-off comparisons, requested-versus-executed reporting, missing-backend
continuation decisions and unmonitored expiry across stages. Compare each profile
with its pre-integration configuration to prove unchanged identity, stage order,
durations, CPU/GPU/memory/VRAM settings, normalization and thresholds. Test worker
reuse/restart boundaries and terminal accounting if retention is adopted. Archived
and historically retained profiles must remain unchanged. These are acceptance
requirements, not implementation or test results from Stage 2B-1.

## Final software validation and provenance

- 12/12 affected regressions PASS, including the existing benchmark checks.
- 393/393 complete smoke suite PASS on the final source. An earlier complete run
  also passed; the final run follows a Python 3.10 compatibility correction
  (reuse of bounded native-provenance hashing) and stricter result evidence checks.
- 81/81 profiles valid, five unchanged advisories; 393 Python files compile;
  15 integration imports PASS.
- Native x86-64 build/kernel-policy execution and AArch64 object compilation
  PASS. No AArch64 runtime or physical storage acceptance is claimed.
- Markdown/local links, evidence replay and git diff checks PASS. Protected
  environments, results, profiles and settings remain unchanged.

Complete 379-file `lvs_execution_source_v1` fingerprint:
`cb4fc24ded941c2ead28912a8ed5ed1f3644813505b3faad95c628900c3c880a`.
The three added scoped files are the two Python production modules and native
guard. Research scripts, tests and Markdown are outside this established scope.
The VM proof exercises the recorded native guard and fio binaries; it is not
evidence that the entire LVS source snapshot ran inside that VM or on hardware.
Subsequent Python contract/provenance changes do not alter the proven guard.
The research VM builder requires a modern developer Python (3.12+); ordinary
production modules preserve the project's Python 3.10 API baseline. Actual
validation used Python 3.14; the minimum-version regression excludes use of the
Python-3.11-only hashing API, not a claimed Python 3.10 host deployment.

References: [seccomp](https://man7.org/linux/man-pages/man2/seccomp.2.html),
[no_new_privs](https://man7.org/linux/man-pages/man2/PR_SET_NO_NEW_PRIVS.2const.html),
[fio descriptor implementation](https://github.com/axboe/fio/blob/fio-3.42/filesetup.c).
