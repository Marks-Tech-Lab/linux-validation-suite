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
`inspection_only=true`, `execution_ready=false`. Missing or untrusted endpoints
remain unavailable. Timed Thermal Assist-only stages can reach confirmation with
a deferred candidate, but require real readiness before execution; genuinely empty
stages remain rejected.

Both frontends call `RunLaunchCoordinator.prepare_execution()` after final run
confirmation and effective O / Stage Overrides, before starting the execution
thread, heatsoak or primary timers. It uses the existing privilege manager's
noninteractive sudo check, or a frontend-owned explicit authorization callback.
The CLI prompts on its foreground terminal. The TUI suspends Textual before
prompting through the same manager, then restores the interface. Disabled stages
and disabled Thermal Assist require no authorization or runtime preparation.
Missing runtime does not trigger sudo or installation. No passwords are retained.

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

## Scope and next step

The existing authenticated installed runtime remains the only implemented
transport in this boundary change. An installed runtime may fail source matching
following a client change; that remains truthful auxiliary unavailability. This
change does not install, replace, start, stop or reconfigure it. No accounts,
systemd units, protected recovery state, workload limits, native security policy
or standard profiles are changed.

The next task must qualify a protected temporary runtime and on-demand supervised
helper through this preparation point, including trusted code/tool identities,
termination and cleanup ownership, canonical durable recovery and authorization
failure. System-drive access must remain fail-closed until an equivalent alternative
worker identity and confidentiality boundary are independently qualified. No
physical access is authorized by this implementation or its synthetic tests.
