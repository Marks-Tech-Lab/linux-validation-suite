# Thermal Assist on-demand execution boundary

The architectural direction is project-integrated preparation with an authorized,
short-lived trusted helper, preferably transient systemd supervision. A permanent
boot-enabled service, installed executable tree and permanent worker account are
not the intended final deployment model. Previously qualified deployments and
recovery evidence remain historical records; this change does not remove them.

## Inspection versus execution

Profile display, editing and shared preflight never call an interactive privilege
callback. Thermal Assist inspection reads only local trusted-endpoint metadata:
no sudo, RPC, temperature probe, bootstrap load, subprocess or host write. A socket
is only a preparation candidate, not proof of a live/compatible service, eligible
device or execution authority. Its result is `DEFERRED` with
`inspection_only=true`, `execution_ready=false`. An absent endpoint on a supported
native systemd host can be an on-demand startup candidate; an untrusted endpoint
remains unavailable. Timed Thermal Assist-only stages can reach confirmation with
a deferred candidate, but require real readiness before execution; genuinely empty
stages remain rejected.

Both frontends call `RunLaunchCoordinator.prepare_execution()` after final run
confirmation and effective O / Stage Overrides, before starting the execution
thread, heatsoak or primary timers. It uses the existing privilege manager's
noninteractive sudo check, or a frontend-owned explicit authorization callback.
The CLI prompts on its foreground terminal. The TUI suspends Textual before
prompting through the same manager, then restores the interface. Disabled stages
and disabled Thermal Assist require no authorization or runtime preparation.
An absent runtime may offer explicitly approved on-demand startup at this confirmed
foreground point. It never triggers installation or elevation during inspection.
No passwords are retained.

Only this confirmed phase performs the existing authoritative runtime readiness
and verified native-bootstrap loading. Preparation is bound to the effective
Thermal Assist configuration and duration, consumed once when execution starts,
and transferred to the executor's scoped context. Changed configuration, missing
preparation or inspection-only plans cannot authorize a stage session. Server-side
identity, source, configuration, native admission and recovery checks are retained.
Existing run-local storage/system authorizations and bounded unmonitored consent
remain mandatory; sudo readiness is not a substitute for any of them.

Unavailable/declined auxiliary preparation is reported as blocked/NOT_RUN and
cannot introduce primary commands or change primary verdicts. A Thermal Assist-only
stage with no executable activity remains unavailable rather than pretending to
have run. Background service execution checks enhanced-telemetry sudo readiness
noninteractively; it cannot request authentication inside a timed stage or the TUI
worker.

## Access modes and final preparation review

The stage workload screen has one **Storage Thermal Assist…** entry in both
CLI and TUI. In O / Stage Overrides these edits affect only the pending run;
saved-profile editing remains unsaved until the existing Save/Save As action.
No standard profiles, labels or menu descriptions are rewritten.

The normal screen contains:

- **Enabled**: Off, or On — recommended data setup. Explicitly selecting On
  opts into the existing experimental shared data provider, automatic aggregate
  budgets and required monitoring. The current effective provider is displayed.
- **Drives**: internal data groups or **Choose physical drives…**. The picker
  shows device node where known, model, capacity and system/data/unknown status.
  It uses passive metadata, never sudo, RPC or temperature probing. Known system
  targets cannot be selected; unknown classification is not eligibility.
- **Intensity (%)**: the ordinary-drive percentage policy, 0–100. Changing this
  returns from custom rates to percentage mode. This is requested activity, not
  utilization or measured heating. Existing 50% ordinary / 25% system policy
  values and all class ceilings are unchanged.
- **Include system drives**: Off; unavailable through the current on-demand
  identity pending separate confidentiality/identity qualification. Configuration
  cannot manufacture private run-local system authorization.
- **Temperature protection**: Required. Existing legacy unmonitored intent is
  displayed honestly; the guided workflow cannot grant unmonitored approval.
- **Advanced…**: explicit provider, automatic/manual aggregate budgets, custom
  per-drive IOPS and MiB/s, read size in KiB, temperatures in °C, future system
  intensity intent and individual per-drive percentage overrides. Optional rates
  accept `auto`, sensor-derived thresholds `device`, and overrides `default`.
  Choose individual drives before adding overrides; saved overrides can be cleared.
  Set both manual caps before switching to Manual. Custom mode starts at 1 IOPS
  until edited. Every edit is validated transactionally, including threshold order.

Existing profiles retain the legacy `exclusive` default: inactive physical SATA/SAS
HDDs only, excluding mounted drives, SSDs and NVMe. Simply loading or running an
old profile does not promote it to shared access. The guided On action explicitly
selects `shared_readonly_opt_in`, supporting qualified internal data HDD/SSD/NVMe,
mounted or unmounted. It does not add any eligibility or silently fall back to a
weaker method. Filesystem names do not select a provider. Complex/ambiguous,
external, unsupported and unqualified targets retain their existing blockers.
Automatic mixed-provider selection/global legacy-default promotion is not implemented.

`budget_mode=automatic` is saved profile intent, **not** a new privileged protocol
field or an execution authorization. Before authorized preparation it uses
non-executable probe caps (1 IOPS / 1 B/s). After the existing source/privilege
approval, authoritative readiness identifies qualified monitored physical data
targets. The client sums their exact established `pilot_rate` results with no
capacity/model proxies or new ceilings, then performs the normal authoritative
readiness pass again with explicit numeric aggregate limits. Duplicate or
contradictory rate evidence is rejected; missing monitoring/resources cannot supply
budgets. Unknown/system targets never supply automatic budgets. The existing
privileged provider revalidates all limits, topology, recovery and admission.
No qualified targets means blocked auxiliary execution, never an uncapped fallback.
The resolved limits live only in the one-use effective preparation and its evidence;
saving/reloading a profile requires fresh resolution. A changed effective schedule
cannot reuse the receipt. Final review displays the numeric caps before execution.
These workload caps do not bound all initialization, kernel or application traffic.

The standalone expert menu also uses human drive descriptions, KiB and MiB/s
prompts and displays the current access contract. Its command-line JSON format
remains available for automation; it is not the normal profile-editing workflow.
Its existing explicit manual caps and start confirmation remain required.

After foreground authorization, both CLI and TUI use
`RunLaunchCoordinator.review_execution()` to present the effective contracts and
final preparation results **before heatsoak, the run thread or primary timers**.
The review distinguishes:

- Eligible targets, with planned rates; no execution or achieved activity claim.
- Partial coverage, listing the eligible subset and excluded requested targets.
- Zero eligible drives after authoritative inspection: Thermal Assist NOT_RUN.
- Preparation failed/unavailable, including declined authorization, unavailable
  backend or a global recovery blocker: no claim that
  the hardware itself failed eligibility.

Choose **1 — Continue run** to proceed with primary validation and only the listed
eligible Thermal Assist subset, subject to existing consent, final admission and
revalidation. Unavailable Thermal Assist remains non-gating. This review never
grants new system-drive or unmonitored-coverage authorization.

Choose **2 — Return to setup** (also the empty-input default) for an authoritative
**readiness-only test** through the normal workflow. No primary or physical
Thermal Assist workload starts. Authoritative inspection may observe temperatures
and topology and qualify the backend using disposable regular files. The TUI
reuses its foreground terminal suspension, then returns to the interface; no
external utility or manual observer is needed. Reopen Review and run to obtain
fresh preparation before execution.

Returning, EOF, interruption or review failure discards the one-use receipt and
closes this run's transient liveness hold. Unexpected preparation failures also
release an acquired hold. This is not a cleanup certificate or permission to
write CLEAN: the existing service waits for quiescence and canonical recovery
safety, respects other clients, and performs its existing idle shutdown. No
permanent unit, account or installed executable tree is introduced.

## Implemented transport

The foreground boundary now supports the separately qualified temporary data-drive
runtime described in [the transient runtime contract](storage_thermal_transient_runtime.md).
Its explicit source approval, private dynamic identity reservation and transient
supervision do not install or boot-enable a permanent service. Existing installations
remain untouched and conflicting ownership is refused. System-drive execution through
this alternative identity remains blocked pending separate qualification.

The boundary itself performs no installation or automatic migration. Legacy-service
handoff requires its separate explicit approval, preserving canonical recovery,
previous deployments and evidence. Physical use is separately authorized.
