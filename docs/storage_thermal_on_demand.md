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

Enabling Thermal Assist preserves the selected access contract. The default
`exclusive` provider supports only inactive physical SATA/SAS HDDs; it excludes
mounted targets, SSDs and NVMe. `shared_readonly_opt_in` is the experimental path
for supported internal data HDDs, SSDs and qualified local PCIe NVMe, mounted or
unmounted. Filesystem names alone do not select a provider. Set aggregate IOPS
and byte/s budgets **before** selecting shared mode, retain required monitoring,
and choose the intended stable physical IDs. No mode selection grants system,
complex-stack or external access. Existing eligibility proofs still apply.

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
