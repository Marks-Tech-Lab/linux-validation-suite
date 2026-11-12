# Stage 2B-5: supported internal data-drive screening preparation

**Prepared for review only. No physical workload has been authorized or run.**
The raw-device and existing-file active-access NO-GO findings remain unchanged.
This procedure supports one positively identified internal non-system data drive,
mounted or unmounted, under an approved exclusive or experimental shared read-only
configuration. Exclusive remains limited to inactive HDDs; shared supports the
current SATA/SAS HDD/SSD and qualified single-namespace local PCIe NVMe categories.
This procedure grants no physical, thermal, interference or scalability acceptance.

## Existing evidence and the small remaining measurement gap

The standalone runner already publishes `configuration.json`, effective preflight,
source/tool provenance, raw fio/guard output, `worker_results`, bounded
`progress.jsonl`, temperatures, achieved fio activity, process CPU/RSS observations
and the authoritative `storage_thermal_manifest.json`. Profile execution also
records original/effective configurations, stage timelines, independent auxiliary
outcomes and whole-run evidence. Those artifacts remain authoritative; the
external observer cannot replace their success policy or cleanup certificates.

[The acceptance helper](../scripts/storage_thermal_acceptance.py) adds only the
missing outside-workload baseline/cooling record, ambient/operator markers,
whole-device counters, process-tree resource snapshots and host pressure. It
reuses the existing passive target resolver, diskstats reader, temperature reader
and atomic JSON publication. No production module imports this helper. It never
opens a `/dev` endpoint, launches/signals/reaps a workload, changes a threshold,
resolves recovery, or installs software. Python's standard library suffices.

## Approval card required before physical work

The operator must provide and approve:

- Exact host, kernel, commit/source fingerprint, trusted fio/guard identities,
  physical drive model, WWN/serial, capacity and physical port/controller.
- Explicit data-owner permission and backup/disposable status; a passive inventory
  showing a uniquely identified eligible internal non-system data drive. Mounted
  data partitions are permitted in shared mode; system/swap backing, holders and
  active/ambiguous complex stacks remain blocked. Record the chosen access contract.
- Exact associated sysfs sensor, its documented resolution or an explicitly
  labeled assumption, current temperature, ambient temperature, airflow/fan and
  power-management conditions, and drive operating limits from model documentation.
- Numeric warning and stop thresholds below the stricter documented/reported
  limits, with an agreed conservative margin. There is no universal drive temperature limit.
- Approved non-target storage for repository/build/recovery state and all logs;
  reviewed recovery state with no unresolved ARMED obligation; existing permissions.
- Exact selection, 25%/50% settings, durations, operator attendance, cancellation
  procedure and the finite screening boundary below.

Do not unmount or reformat an otherwise supported data drive, disable swap, change
topology or permissions, bypass the selected contract, or clear recovery files to
obtain eligibility. Shared is an explicit choice, not a fallback from failed
exclusive acquisition. Required
monitoring is mandatory for thermal acceptance. Temperature reads may wake a drive
or affect its standby timer: [drivetemp documentation](https://docs.kernel.org/hwmon/drivetemp.html).
Approval of this preparation does not authorize even the monitored-idle campaign.

## Commands after separate target-specific authorization

Run from the repository root, using the existing qualified Python environment.
Use an approved results filesystem outside the target. Paths and drive IDs below
are placeholders to replace after reviewing the approval card.

```sh
python3 lvs_storage_thermal_assist.py --check \
  --access-mode shared_readonly_opt_in --aggregate-iops-limit 128 \
  --aggregate-bps-limit 8388608 > /approved/control/inventory.json
python3 -m scripts.storage_thermal_acceptance capture \
  --inventory /approved/control/inventory.json --device-id 'wwn:APPROVED_ID' \
  --directory /approved/control/passive --seconds 300
```

For exclusive inactive-HDD screening, omit the three shared/budget flags.
The inventory records the chosen contract and the observer uses that same
contract for fresh eligibility checks; a shared inventory is not rechecked under
exclusive rules. The first command is passive inventory; the second reads proc/sysfs identity and
counters but **does not read sensor values** unless `--temperatures` is supplied.
Each capture requires a new directory. Initial and five-second passive identity,
monitor-source and eligibility revalidation must match the inventory. The helper
checks that its destination is outside the target. No block-device probe or
workload is started by either capture mode. Passive does not imply the rest of
the operating system stops accessing devices.

For the monitored sequence, start a new observer in a separate terminal:

```sh
python3 -m scripts.storage_thermal_acceptance capture \
  --inventory /approved/control/inventory.json --device-id 'wwn:APPROVED_ID' \
  --directory /approved/control/screen --seconds 10800 --interval 1 \
  --temperatures --sensor-resolution-c 1
```

Use resolution 1 only if verified or explicitly recorded as the working assumption.
This three-hour ceiling is an observation allowance, not approval for three hours
of workload. Stop the observer with Ctrl-C after the cooling observations finish.
Its clean final publication does not prove the requested duration was observed.

From another terminal record phase/ambient and event markers:

```sh
python3 -m scripts.storage_thermal_acceptance mark \
  --directory /approved/control/screen --event monitored_idle_started \
  --phase idle --ambient-c 22.0
python3 -m scripts.storage_thermal_acceptance mark \
  --directory /approved/control/screen --event supervisor_registered \
  --pid APPROVED_SUPERVISOR_PID --role auxiliary
```

Replace ambient with an actual contemporaneous observation; 22.0 is an example.
Record it at least every five minutes and at each phase boundary. Observations
older than five minutes are excluded from ambient-corrected temperature analysis.
Register the actual auxiliary supervisor before workload startup, then known
helpers separately if necessary. Registration captures process start ticks;
public numeric PID reuse does not transfer observation identity. For later
matched trials, register primary roots with `--role primary`. Explicit auxiliary
subtrees take precedence over inherited primary attribution. These labels are
operator measurement declarations, not process ownership authorization.

Start the existing interactive runner, with all guardrails unchanged:

```sh
python3 lvs_storage_thermal_assist.py \
  --fio /absolute/qualified/fio --guard /absolute/accepted/storage_thermal_guard \
  --output-root /approved/control/lvs-results
```

For cold interpreter-startup accounting, optionally run the command above through
`sh -c 'printf "Register auxiliary launcher PID %s, then Enter: " "$$"; read -r answer; exec python3 lvs_storage_thermal_assist.py --fio /absolute/qualified/fio --guard /absolute/accepted/storage_thermal_guard --output-root /approved/control/lvs-results'`.
Register the printed PID and wait until a sample contains it before pressing
Enter. Exec retains that creation identity. Without this handshake, startup
before registration remains outside sampled process CPU. This is an operator
launch procedure, not a new provider or unattended execution path.

In standalone Advanced options choose **6: Access contract and aggregate budgets**.
Select shared read-only for a supported mounted data drive/SSD/NVMe; enter 128
aggregate fio IOPS and 8388608 B/s for an initial one-drive budget. These cover
one 50% NVMe case; they do not cap OS, startup or kernel I/O. Keep exclusive for
an approved inactive HDD when appropriate. No JSON file editing is needed.

Select **individual drives**, verify the stable ID, set ordinary intensity/duration,
required monitoring and the approved warning/stop temperatures. Preserve system
intent at 25%; system drives remain blocked. Preview and explicitly confirm each
run. No unattended launch flag is introduced. A runner-produced configuration can
be reviewed/reused with `--config FILE`; `--plan` checks readiness and may read/wake
sensors, but does not execute a workload.

## Single-drive screening, then stop

1. Passive inventory and physical identity/topology/permission verification.
   Verify output/build/recovery locations are outside the selected target.
2. Five minutes passive counters, then 15 minutes monitored idle. The added
   monitoring cost is part of the record, not a claim of sensor-free idle.
3. 25%, 60-second launch test; examine actual reads, duration, guard evidence,
   terminal publication, cleanup and recovery before another workload.
4. 25%, configured five-minute cancellation test. Mark `cancellation_requested`,
   press `0` + Enter after about 30 seconds, and retain the real stop/cleanup times.
5. 25%, five-minute low-intensity pilot. Record `--phase low`.
6. 50%, 30-minute heating test, only if preceding evidence is satisfactory.
   Record `--phase heat` immediately before explicit start and actual startup
   boundaries from the runner. Requested HDD rates at 64 KiB are 7 IOPS / 448 KiB/s
   at 25%, and 15 IOPS / 960 KiB/s at 50%. SATA/SAS SSD resolves to 32/64 IOPS
   (2/4 MiB/s), and NVMe to 64/128 IOPS (4/8 MiB/s), at 25%/50% respectively.
   These are provisional media-specific activity policies, not utilization claims.
7. Record `--phase cooling` after stopping. Observe at least 20 minutes, and
   recovery toward the matched starting temperature, with a 60-minute cooling
   observation ceiling. Do not force cooling or alter airflow to improve results.
8. Inspect all retained evidence and stop for review. No repeatability, 100%,
   multi-drive or primary CPU/GPU/RAM comparisons are automatically authorized.

Use markers for confirmation/startup, cancellation, terminal result availability
and operator-observed cleanup. Marker times are operator observations, not the
actual admission or reap times. Preserve the runner's native timings alongside
markers; a marker named `cleanup_observed` cannot authorize CLEAN.

Immediate termination conditions include temperature limits, lost required
monitoring, identity/topology changes, prohibited worker mutations, unexpected
exclusive-target writes/discards/flushes,
I/O errors/resets, unsafe resource pressure or uncertain cleanup. Stop through
runner controls, not this observer. Unconfirmed cleanup retains ARMED protection;
do not delete its anchor/journal or infer cleanup from SIGKILL/reboot. Preserve
all evidence and obtain a separately reviewed recovery disposition before retrying.
Shared device-wide writes/discards/flushes are retained as background observations;
they are not by themselves proof of a Thermal Assist mutation or an automatic
safety failure. fio write/trim/flush/error evidence still fails. Keep ordinary
filesystem activity comparable and recorded in shared baselines and workload phases.

## Capture and analysis

```sh
python3 -m scripts.storage_thermal_acceptance analyze \
  --directory /approved/control/screen > /approved/control/screen-analysis.json
```

Retain `session.json`, raw `samples.jsonl`, immutable event files, the analysis,
passive inventory, LVS output directories, approval card and ambient observations.
The analysis reports gaps, resets, unavailable data and ambient-corrected heat
minus idle means. Its heat endpoint uses the last five observed minutes of the
heat phase, not a fixed number of samples. Short/incomplete phases remain
inadequate for acceptance even when a descriptive delta can be calculated.

Cross-check requested versus effective configuration against actual fio runtime,
read counters and achieved rates in LVS artifacts. The observer's disk counters
are whole-device observations, not exclusively attributable fio activity. They
include startup and background operations. Missing/reset intervals are excluded,
not converted into zero activity. Read await and average queue are derived Linux
block statistics, not controller service-time or guaranteed media access:
[Linux I/O statistics](https://docs.kernel.org/admin-guide/iostats.html).

Inspect authoritative worker results and the final completion manifest for guard,
identity, provenance, duration, terminal publication and cleanup. Inspect recovery
without modifying it. An observer report never validates those contracts, clears
an obligation or establishes safety. Original/effective profile evidence is
already supplied by LVS; no profile changes are needed for this screening.

## Overhead, bounds and limitations

- One observer, one shared diskstats read per sample; no subprocess per drive or
  polling shell commands. Counters and host CPU/memory/VM/PSI data come from proc.
  PSI absence is recorded as unavailable. CPU/thread/FD/RSS snapshots cover
  registered roots and observed leader-child descendants. Start ticks are checked
  before/after process sampling. Exited/reused PID numbers are quarantined from
  automatic rediscovery; explicit re-registration is a new operator observation.
- Short-lived helpers between samples, descendants born through nonleader threads,
  process reparenting and permissions can cause gaps. Register missing roots using
  existing LVS ownership evidence. Sampled process CPU is a **lower bound**, not
  complete total auxiliary CPU; waited-child CPU ticks are retained separately
  and never blindly added to already counted child CPU. Use authoritative fio and
  supervisor accounting to explain gaps. Do not certify a 5% budget from a lower
  bound alone. RSS sums double-count shared pages; they are not unique physical RAM.
- The helper records its own process CPU, peak RSS, sample latency/lateness,
  FD/thread counts and bytes written. Startup CPU includes imports and initial
  inventory. Outputs are flushed and fsynced every ten samples and at exit;
  control-filesystem costs belong to measurement overhead. They can interfere
  with a primary workload and must remain identical across later comparisons.
- Bounds: 1..60-second cadence, six-hour capture maximum, 28 selected drives,
  128 simultaneously tracked processes, 256 event files, 128 MiB raw log, 1 MiB
  sample and 8192 process-history entries. Limit breaches stop observation and
  preserve an incomplete record; they never stop a workload. No silent overflow
  is accepted. Estimate volume from a short capture before any future many-drive
  campaign; 28 drives at one-second cadence need not fit for six hours. Use
  separately approved shorter captures or a coarser cadence, not a hidden drop.
  Repeated captures can cover longer future campaigns after approval.
- Sysfs sensor access itself may stall. This external helper has no real-time
  completion guarantee and is not part of the primary timing path. Large gaps,
  slow reads and incomplete publication are measurement failures. Watch its
  terminal; stop physical work if required acceptance evidence is being lost.
- At each selected sensor the helper adds one extra poll per interval, alongside
  the runner's existing monitoring. The monitored-idle baseline measures observer
  polling, while workload phases include the additional runner polling. Record
  that difference. Do not claim completely isolated monitoring overhead or add a
  second collector silently. Device firmware caches and internal maintenance,
  temperature quantization, ambient drift and delayed thermal responses remain.
- Analysis is offline and should run after capture, not compete with the pilot.
  It streams raw records and keeps bounded histories/summaries. Missing fields,
  stale ambient, wall-clock steps, counter resets and incomplete samples remain
  explicit. Raw records preserve evidence for independent review.

## Provisional review decisions

Report four separate conclusions: genuine read execution, practical heating,
resource/interference acceptability, and operational safety/cleanup.

A 3°C ambient-corrected rise is the initial usefulness target, subject to sensor
resolution and idle variability. Require adequate idle/heat coverage and a rise
larger than their uncertainty; failure to heat is not a fabricated drive integrity
failure. Report stabilization/cooling observations separately. The proposed 5%
aggregate host CPU and 2% sustained primary-throughput-loss budgets are investigation
budgets only. This screening does not run primary comparisons or change hardware
verdict rules. No observed-resource or thermal result is automatically PASS.

The preparation tests use synthetic proc files, counters, sensors, fake clocks
and recorded observations only. No real block endpoint or temperature sensor is
read by those tests. The 387-file execution source remains unchanged; the existing
software baseline and both active-access NO-GO findings retain their original scope.


## Integrated run-local setup

Launch `python3 linux_validation_suite.py` or the existing TUI. Choose the profile,
then **O / Stage Overrides → Configure Stage Workloads**. Enable Thermal Assist,
set aggregate IOPS 128 and bytes/s 8388608 first, then choose
`shared_readonly_opt_in`. Enter a stable ID as plain text (or comma-separated IDs)
then choose individual selection. Set required monitoring and the model-specific
warning/stop thresholds. Keep ordinary/system intensity at 50%/25% and the existing
stage duration. Changes are run-local; do not Save to change the seven profiles.
Shared experimental status and aggregate requested rates appear in generated
summaries/readiness, independently of actual completed activity. Multiple selected
drives require a reviewed aggregate budget; insufficient budget blocks storage
without fabricating a primary hardware failure.

Conventional LUKS data drives use the separately reviewed [non-target deployment and encrypted-topology procedure](storage_thermal_encrypted_deployment.md). Native privileged readiness and target-specific approval are still required before any physical workload.
