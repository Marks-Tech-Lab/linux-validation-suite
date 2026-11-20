# Historical workstation readiness review after routine-install qualification

Metadata-only review on 2026-11-20 preserved every prepared/installed version,
canonical recovery and host policy. No sudo, sensor access or workload occurred.

The prepared `2ee5db0429882f541634cb66802d3d5b512cf22f` runtime remains intact:
394-file source `bb047cacbd254121720eb3d05ea46880353cc394d4b6e5b08e0a29a31df56feb`,
400 manifest entries verified; manifest SHA-256
`0005ad22de4bd2746633f1c0d2d9cb9a05ff1e6bae946d0e231f68ede142241c` and checksum-list
SHA-256 `f2ad31f509bbd4b9ab15cb20a2ee67af6ad794fd2c5593ea205dc269e27fca7c`.
It is reviewable installation material, not authority to install or run.

The active service still uses `/opt/lvs-thermal/integrated-ea60eaa9` and its
392-file source `1e35d99bf3b6b1789e6b4bc6571f4be4357afc8e7269413657e777b8bee8dc53`.
Its older API rejects the new metadata health operation. It is not compatible
with the prepared/current source: no silent worker fallback is permitted.
Canonical journal contents require administrator access; unprivileged inspection
received permission denied and cannot freshly certify CLEAN. Previously accepted
CLEAN evidence is preserved, not claimed to be a new observation.

## Exact confidentiality prerequisite

The accepted system-access contract requires a dedicated non-login worker,
unreadable trusted fio, no operator memory/debugger access to raw-sector buffers,
no core retention, restricted native execution, and confirmed durable recovery.
The actual host has `fs.suid_dumpable=2` and a piped systemd-coredump handler.
The installed older manifest has no dedicated system-worker identity. System
admission must remain blocked. Routine installation can provision the dedicated
identity, but does not change the host core policy or authorize system access.

`RLIMIT_CORE=0` alone does not protect a piped core handler. Setting dumpability
before an exec is insufficient because credential/exec transitions can reset it.
An unreadable executable with policy 2 is not a proof of no dump. Disabling final
core storage alone also does not prove memory was never processed or temporarily
written. See the Linux manuals for [dumpability](https://man7.org/linux/man-pages/man2/PR_SET_DUMPABLE.2const.html)
and [core handling](https://man7.org/linux/man-pages/man5/core.5.html), and
[systemd core processing](https://www.freedesktop.org/software/systemd/man/259/coredump.conf.html).

## Least-disruptive options and next approval

Prefer separately qualifying a trusted **post-exec worker initialization hook**
that sets and verifies `PR_SET_DUMPABLE=0` before any target read or buffer access,
retains dedicated UID separation and prevents subsequent re-enabling. This needs
an independently approved fio/build identity or equivalent trusted in-process
mechanism, exact native syscall-policy review and a positive VM crash/ptrace
proof under policy 2 with the actual piped handler. An ordinary wrapper that sets
prctl and then execs fio is insufficient. No such code or guard exception is
implemented by this milestone, and the existing system authorization check is
unchanged. Pre-exec failures must also contain no raw data; post-read faults,
threads, cancellation and diagnostic paths must all preserve the property.

An explicitly authorized administrator-wide `fs.suid_dumpable=0` change is the
existing compliant alternative; it affects other privileged applications' crash
handling and must not be silently made. Host-wide coredump suppression, container
wrappers, directory permissions or `MADV_DONTDUMP` on one buffer are not accepted
substitutes without proving the entire memory/register lifecycle and debugger
boundary. Root/kernel compromise is outside the existing worker threat model.

Before new physical testing, use the routine setup workflow to prepare source
matching the intended checkout, independently approve the installer and bundle,
then authorize administrator promotion. Preserve prior deployments and inspect
canonical recovery through the trusted path without clearing ARMED. Validate
component/source compatibility and current target readiness. System-drive testing
additionally requires the confidentiality prerequisite above and explicit
run-local target/session authorization. No physical trial or security-policy
change is authorized by this document. The genuine primary-throughput work is
independent of this remaining system-worker qualification.

The findings above describe the accepted 709c730-era state. The subsequent
[post-exec confidentiality implementation](storage_thermal_confidentiality.md)
qualifies dedicated worker protection under policy 2 without changing host policy.
It does not install itself or make the older prepared/installed runtime match the
new source. Fresh preparation, independent approval and privileged recovery
verification remain mandatory before any new physical authorization.
