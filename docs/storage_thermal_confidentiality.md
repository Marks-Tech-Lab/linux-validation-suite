# Trusted post-exec Thermal Assist confidentiality

This extends the experimental shared/system provider within its existing scope.
It does not authorize a target or change global core policy, profiles, activity
ceilings, primary verdicts or canonical recovery. Previous system qualification
under `fs.suid_dumpable=0` remains historical evidence. The new worker protection
is designed and tested with policy **2** and a piped core handler.

## Authority and ordering

The approved native guard retains its descriptor/geometry, privilege, ioctl and
mutation restrictions and native admission v2. Its optional confidential mode
loads the reviewed sibling `storage_thermal_confidential.so` through a pinned
read-only descriptor. The guard creates its own clean environment and fixed
`LD_PRELOAD=/proc/self/fd/N`; the client cannot supply a library, executable,
environment, command or target pathname. The trusted runtime manifest, native
source/build provenance and resolved readiness bind the library hash. Installation
checks the actual final fio exec using a private regular-file fixture.

Before exec, the guard places the validated target capability in a private
`SCM_RIGHTS` socket queue, replaces stdin with `/dev/null`, closes target aliases
and retains only the executable/library/handoff handles and approved outputs.
**No sector data has been read.** A missing/ignored/broken preload leaves no
ordinary target descriptor in the executed program. The approved fio's fixed
`filename=-` cannot fall back to a device pathname.

After final exec, the constructor:

1. Sets `PR_SET_DUMPABLE=0`; checks non-root credentials and the expected parent,
   and rearms parent-death SIGKILL after exec/credential transitions.
2. Installs a native-ABI seccomp filter with **TSYNC** before releasing the target.
   It blocks later exec, credential changes, user/other namespace creation,
   dumpability reset and parent-death reset. It denies worker ptrace/process-memory
   operations. Unsupported clone3 returns ENOSYS for the standard pthread clone
   fallback; normal threads/forks inherit the restriction and dumpability.
3. Checks dumpability and harmless denied reset/exec/credential probes. Any failed
   setup, verification or synchronization exits before dequeue. TSYNC failure is
   not replaced by a single-thread filter or weaker fallback.
4. Receives exactly one read-only/direct descriptor, verifies its device and size,
   restores stdin, closes handoff/library handles and emits a bounded numeric
   `lvs.storage_thermal.postexec` witness. It logs no payload bytes or keys.

The filter makes the attribute persistent for the worker and its descendants:
new threads/forks inherit it, and exec/credential routes that could reset it are
blocked. RLIMIT_CORE=0 remains defense in depth, not the proof. Linux may ignore
that limit for a piped handler; the per-process nondumpable attribute is essential.
See [Linux dumpability](https://man7.org/linux/man-pages/man2/PR_SET_DUMPABLE.2const.html)
and [core handling](https://man7.org/linux/man-pages/man5/core.5.html).

The boundary assumes the approved fio, guard/hook, root-owned OS loader/libraries
and privileged supervisor are trusted. It is not protection against a compromised
root/kernel or a privileged debugger already controlling the trusted process.
Actual privileged workers are created by the trusted root service/bootstrap and
drop into the dedicated non-login identity; an ordinary operator cannot attach to
that root bootstrap before the drop or acquire the later nondumpable worker.
The initial loader may fault before the hook, but has no raw target bytes or
ordinary target descriptor. Other applications' memory/core policy is unchanged.

## Execution, evidence and recovery

Qualified installed workers, including data/exclusive regressions, use the new
mode whenever its policy is present. A failed qualified policy blocks readiness;
there is no silent legacy fallback. The original standalone data guard without
this optional component retains its established read-only contract and cannot
authorize system access. System requests always require the dedicated identity,
unreadable trusted fio, approved hook and actual final-exec capability proof.

Readiness retains stable tool identities and policy results, not transient probe
PIDs. Each actual worker emits its own PID/UID/GID, zero dumpability, TSYNC/locked
state, deferred-target and device/geometry witness. Terminal reading and primary
publication enforce it against authoritative readiness; a boolean assertion cannot
replace missing or contradictory native facts. The library is included in final
tool-provenance reconciliation and installed service health.

Native admission commits before the final exec as before. An admitted worker that
fails its hook remains independently owned, even if it read no sectors. A failure
is not falsely NOT_RUN or successful execution. Confirmed reaping/group cleanup
can legitimately permit CLEAN after a failed worker; lost authority, uncertain
cleanup or failed durable publication retains ARMED. No child witness grants CLEAN.
Cancellation, temperature enforcement and stage deadlines remain supervised
through the accepted ownership/revocation paths. Already-issued kernel I/O has
its existing shared-access limitations.

## Qualification and limitations

Only private writable QEMU images are used: conventional ext4 root and selected
LUKS2/Btrfs root, busy-root activity, real disk-backed swap, cancellation, synthetic
automatic temperature stop, handler death and durable EIO/ENOSPC cases. Separate
real-systemd installation tests include root-owned immutable-OS directory aliases.
No physical Samsung campaign is repeated. Actual installed service, opener,
guard, final fio exec, block reads, identities, ownership and recovery are genuine;
primary stress/temperature inputs in system-storage cases are synthetic. Genuine
CPU/RAM completed-work reporting has separate production-path regression/VM proof.

Privacy controls use an **untraced** same-UID parent: an ordinary child proves
ptrace and process-memory visibility, and a real crash invokes the piped handler
even with core limit zero. Protected children with a real private buffer deny
ptrace, process_vm_readv and procfs memory/FD access; real SIGABRT must not invoke
the handler. Thread/fork state, initialization denial and filter-synchronization
denial are recorded. Outer root strace would invalidate that debugger positive
control, so privacy campaigns do not claim a complete syscall trace. The accepted
native read-only policy proofs remain mandatory.

Raw fixtures/addresses are not retained as payload evidence. Exported controls
contain only opaque IDs, sizes, state, counts and outcomes. Fio read/write/error
counters and required witnesses remain separate from claims of physical thermal,
scalability, power-loss or definitive interference acceptance.

## Routine preparation and workstation promotion

Use the original repository `.venv` via `./setup.sh` option 9. The qualified fio
3.42 cache is reused; fio is not patched or rebuilt. Native guard/bootstrap/hook
are built and hash-bound by the existing preparation workflow. Nothing elevates,
installs packages or changes a worker account during preparation.

On immutable hosts the fixed `/opt` and `/usr/local` locations can be root-owned
OS aliases. The installer verifies every alias, ancestor and endpoint before
using a canonical root-owned location. Writable/user-owned aliases, unsafe targets
and loops fail. Executed paths remain canonical and link-free. No arbitrary
installation-prefix override is introduced. Bazzite metadata resolves these to
`/var/opt` and `/var/usrlocal`; no host links or ownership are changed.

Administrator authorization is still required to copy the independently reviewed
installer into the verified canonical libexec directory, check its approved hash
**before root execution**, then invoke the fixed `--approve --bundle ...
--manifest-sha256 ...` operation. The generated approval JSON contains the actual
canonical installer path and promotion command. It is approval material, not a
self-issued certificate. Promotion preserves prior deployments, stable service
identity, canonical journal and anchor. Inaccessible canonical contents do not
establish CLEAN; privileged inspection/locking must confirm readiness.

After separately approved promotion, verify source/tool/component health and
canonical recovery. System access remains explicitly run-local, bound to the
resolved physical identities/session and any co-located control-plane/swap
approval. First obtain native-host topology, actual sensor observations and
model-appropriate limits under separate authorization. A proposed first screen
is at most 60 seconds, 8 IOPS / 0.5 MiB/s, 64 KiB random reads, QD1, with required
monitoring and separately approved warning/stop limits. This document does not
authorize it. No global core-policy change, system workload or multi-drive run
is performed by preparation or installation.

## Completed software qualification (2026-11-20)

The final 398-file execution source is
`ea5ee812f5af93d2e4d402ca0f368f5a6a43d6f8f0c3418642cbd389ed6873a0`.
The frozen-tree smoke run passed 505/505 checks, including the existing 112-case
evidence matrix and new post-exec native controls. Separate validation compiled
441 Python files, imported 67 integration modules, validated 81 profiles (five
unchanged advisories), and checked documentation, import cycles and whitespace.
Native x86-64 execution passed; guard, bootstrap and confidentiality-hook
AArch64 compilation passed. No AArch64 execution is claimed.

Retained accepted VM reports are `/tmp/lvs-confidential/ext4-reviewed.json`,
`encrypted-reviewed.json` and `installation-reviewed.json`. They bind the same
source fingerprint. Conventional ext4 root and encrypted Btrfs root campaigns
passed actual guarded fio execution, busy-root operation, disk-backed swap,
cancellation, synthetic temperature enforcement, injected worker crash,
topology change, and persistence-failure cases. Both preserved fixture integrity,
confirmed normal CLEAN and independently observed ARMED after final uncertainty.
Actual systemd installation/update tests passed fresh/repeat installation,
upgrade from the prior accepted deployment, rollback, failed/interrupted
promotion, restart and unresolved-recovery protection, including root-owned OS
directory aliases. Guest kernel was `7.2.9-200.fc44.x86_64`, systemd
`259.9-1.fc44`, and fio `3.42`.

Separate genuine CPU/RAM production execution completed a configured ten-second
stage in 10.095 seconds with 45 telemetry samples; cancellation was observed at
7.104 seconds with 34 samples. Completed-work counters and integrity verification
remained available. System-storage campaigns use synthetic primary/temperature
inputs as described above; these are separate scopes of evidence.

All 130 protected-artifact hashes and standard profiles remain unchanged. No
host privileged installation, security-policy change or physical storage
workload was performed. Physical system-drive acceptance, broader hardware,
intensity calibration and scalability remain pending.
