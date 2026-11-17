# Integrated Thermal Assist installed session runtime

The normal LVS CLI/TUI and primary workloads remain unprivileged. An explicitly
operator-authorized session service runs from the existing verified Thermal
Assist bundle. It reuses the accepted workload, native guard, v2 admission,
owned-process supervision and persistent recovery; it is not a general command
service or another workload engine.

## Authority and lifetime

Use the existing [reviewed deployment procedure](storage_thermal_encrypted_deployment.md):
independent source/tool approval, pinned checksum-list digest, root ownership and
safe ancestors before privileged execution. Never elevate the user-writable
repository/venv or change device permissions. No disk group, setuid Python or
NOPASSWD installation is required.

The installed launcher accepts `--serve-integrated` and verifies the whole bundle
before binding `/run/lvs-thermal/UID.sock`. The client checks root endpoint and
peer ownership, installed source identity and bootstrap. The service checks kernel
peer UID/GID and native mount/user/time namespaces. Complete configurations and
only supported operations cross the boundary. Inspect and terminal requests have
bounded framing/deadlines. Stage handoff transfers the existing control pipes and
primary admission descriptor using SCM_RIGHTS; no device descriptor comes from
the caller. Session generation, window, ancestry, pipe modes and lease identity
are validated. Caller executable, output and recovery strings cannot choose root
operations or publication paths. Concurrency is bounded independently of hardware.

Root session evidence is under `/var/lib/lvs-thermal/integrated/UID/SESSION`;
existing evidence cannot be overwritten. Both standalone and integrated operation
use `/var/lib/lvs-thermal/storage_thermal_recovery_required.json`. Competing
admission is excluded. No CLEAN operation is exposed over IPC. Only the existing
recovery owner can resolve ARMED after native cleanup. Unknown cleanup and service
death retain recovery protection; the proxy's exit is never a cleanup certificate.

The owned proxy starts without a parent-side root handshake. Revocation and
control-channel closure precede primary cleanup. Root initialization and evidence
I/O stay outside primary timing. Root workers retain deadline, parent-death,
temperature, descriptor and ownership checks. Authoritative terminal validation
still reconciles the independent launch registry, current stage and run authority.
Missing authorization or invalid responses produce a non-gating auxiliary
unavailability/error, not a primary hardware failure.

This installed mode initially requires reliable monitoring; unmonitored requests
are explicitly unavailable. Shared access still needs explicit opt-in and both
aggregate fio budgets. Initialization, provenance, OS and incidental kernel I/O
are not claimed to be capped by fio limits. Eligibility and provisional media
ceilings are unchanged. Canonical state and installed runtime must remain outside
the selected physical target for initial qualification.

## Operator session

Prepare/promote a NEW reviewed version with `scripts.storage_thermal_prepare` and
the approved fio build. Preserve all old versions and canonical state. Normal
code directories are readable/traversable after promotion, never user-writable.
On this systemd workstation, authorize the fixed installed service (replace
VERSION with the approved version):

```sh
sudo /usr/bin/systemd-run --unit=lvs-thermal-1000 --collect \
  --property=Type=exec --property=KillMode=mixed \
  --property=TimeoutStopSec=45 --property=UMask=0077 \
  /usr/bin/env -i PATH=/usr/bin:/bin HOME=/root LC_ALL=C \
  /usr/bin/python3 -I -B /opt/lvs-thermal/VERSION/launch.py --serve-integrated
```

This authorizes a session, not a workload. No preflight automatically starts sudo.
A stale endpoint is an error, never blindly removed. After the approved campaign:

```sh
sudo /usr/bin/systemctl stop lvs-thermal-1000.service
```

The service cleans its owned children; uncertainty leaves ARMED. Other hosts may
use their existing supervisor with the same launcher; Python does not depend on
systemd. Never clear recovery to restart a session.

Keep the ordinary execution workspace/build/results on the non-target system
filesystem. A normal-user `git archive` execution copy of the accepted commit is
sufficient and preserves the original repository/environment. Use the existing
qualified environment to start the normal CLI/TUI there, never sudo the whole
interface. Its scoped source must match the installed runtime. O / Stage Overrides
remains run-local; no standard profile or manual label is rewritten.

## First matched comparison — separate physical authorization

Use QA System Test Short v2 stage 2, Baseline SIMD (CPU + RAM), and disable all
other stages. Use 60 seconds, 5-second start/end trim, heatsoak disabled and raw
telemetry retained. The original 30+30 trim would leave no analysis window.
Keep identical resolved CPU backend/instructions/threads and RAM allocation and
reserves. Baseline Thermal Assist is disabled; comparison enables only Samsung
`wwn:eui.002538a35140ace7`, shared opt-in, 25%, 64 KiB/QD1, planned 64 IOPS /
4 MiB/s. Enter aggregate 128 IOPS and 8388608 B/s before shared mode, and the stable
ID before individual selection. Require monitoring, 60 C stop and 55 C warning.
Keep comparable ambient/component starting temperatures and unchanged cooling,
power settings and background activity.

Retain `run_manifest.json`, `raw_telemetry.csv`, `telemetry_source_map.json`,
effective setup, primary result/progress files, local thermal adapter result,
referenced root session artifacts and canonical recovery inspection. Root raw
artifacts may require the existing operator export. Reuse the acceptance observer
to separate primary, auxiliary service/native workers and measurement overhead.
Compare verified throughput where available, primary timing, telemetry gaps,
CPU time, RSS and memory pressure over the same trimmed interval. Missing metrics
remain unavailable; utilization is not a throughput substitute.

Initialization consumes storage's available stage window. Report actual requested,
available and executed coverage; never extend/retimestamp primary work. Verify
read-only guard evidence, independent auxiliary outcomes, ownership cleanup and
CLEAN. The first pair is functional integration and preliminary interference
screening, not statistical performance acceptance. The 2% throughput and 5%
aggregate-host-CPU budgets are investigation triggers, not hardware verdict rules.

Accepted standalone cancellation and previous full-duration physical runs remain
historical evidence; they need not be repeated. Intensity calibration and
percentage scaling, sustained operation, physical temperature-stop acceptance,
other drive classes and multi-drive scalability remain prerequisites. Current
pilot ceilings are not permanent constraints on separately reviewed calibration.

## Software qualification and limits

The `encrypted-integrated` campaign in `scripts/storage_thermal_shared_probe.py`
uses the existing sealed writable-image QEMU fixture: separate system/control
volumes, two mounted LUKS2/Btrfs partitions on one emulated data NVMe, and no host
block passthrough. It executes the real installed launcher, authenticated service,
unprivileged stage coordinator/proxy, physical descriptor opener, native guard,
fio, admission and canonical journal. Only primary workers and temperature values
are simulated. Primary elapsed time and periodic telemetry callbacks are real.

The finite campaign checks stage expiry, active cancellation, simulated thermal
stop, a two-second primary stage, standalone/integrated exclusion, invalid
configuration/path/operation requests, missing credentials and substituted tools.
Its last case kills a fixture-owned root handler using a pidfd after real reads;
the primary still completes, auxiliary evidence is ERROR, and a fresh process
must observe ARMED. That deliberately unresolved disposable journal is retained,
not cleared to obtain a passing test. Normal/cancelled/temperature-stopped cases
must first demonstrate confirmed cleanup and legitimate CLEAN.

For this single-core emulated campaign, strace uses kernel-filtered device
access/mutation syscalls to avoid manufacturing finalization timeouts by tracing
every interpreter metadata operation. Full initialization traffic is **not**
measured by that trace. Earlier full-trace timeout evidence remains diagnostic;
production completion deadlines were not increased to accommodate the VM.

Installed bootstrap loading never builds from the ordinary execution copy, even
if its source timestamps are newer. Root handlers revalidate installed code/tools
before each request. Lease revocation racing a live observation stops owned work;
after confirmed worker exit, final identity/temperature observations reconcile
raw fio, guard and exit evidence without granting new admission. Other supervision
exceptions remain errors. None of these tests establishes physical thermal-stop,
performance interference, power-loss, or multi-drive acceptance.

## Thermal Assist-only timed stages

A run-local timed stage may enable only `storage_thermal`. It uses the same
normal LVS preflight, run service, telemetry, Advanced Debug, installed session
service, native admission, cancellation and canonical recovery as a mixed stage.
No CPU/RAM/GPU command or dummy process is required. The stage must have valid
positive duration and authorized runnable Thermal Assist readiness; blocked,
unavailable or unapproved storage-only activity is not a runnable stage. A mixed
stage can still run primary validation when its non-gating auxiliary is blocked.
Genuinely empty stages remain invalid.

Completed storage-only stages report primary verdict `not_applicable`, not PASS.
Their recorded `primary_workloads` is empty; the manifest `primary_validation`
(and compatibility `PrimaryValidation`) explicitly records absent primary work
and `throughput: null`. Compatibility result `Not_Applicable` is a terminal
execution result, not successful hardware validation. Department-use and review
summaries must not promote it to a passing validation. Cancellation and genuine
run failures retain their existing aborted/failure outcomes. Thermal Assist
COMPLETED/WARN, NOT_RUN, STOPPED and ERROR remain separate authoritative outcomes.
In a mixed schedule, a storage-only stage does not replace or improve the primary
verdicts from other stages. Telemetry observed during storage-only work describes
background host conditions, not executed primary throughput.

The November 17 integrated 60-second physical A/B functional screening is accepted
as preliminary functional/interference evidence. Its original artifacts are
preserved; it does not establish calibrated percentages, sustained heating,
physical temperature-stop acceptance or scalability. The approved next campaign
is the ten-minute idle baseline and bounded 16/32/64/128/256 IOPS screening with
up to two confirmation trials and cooling. It remains within the existing pilot
ceilings, with 64 KiB random reads/QD1, required monitoring, 55C agent-requested
stop and 60C automatic stop. It must use the corrected source and a matching
operator-approved installed runtime. No physical screening is authorized by this
document itself; the existing separate campaign authorization is unchanged.
