# QA Review Payload Contract

This document defines the stable backend payloads returned by:

- `SuiteAppService.qa_result_review_payload(result_dir, comparison_dir=None, refresh_summary=True)`
- `SuiteAppService.qa_batch_review_payload(candidates=None, refresh_summary=False)`

These payloads are intended for QA review, import readiness, comparison readiness, and escalation triage based on evidence already produced by the suite. They are additive contracts: new optional fields may be added, but existing required fields should not be removed or renamed without bumping `contract_version`.

The QA review payload is not an independent hardware standards judge. It does not infer CPU, GPU, platform, cooling, or power-delivery compliance from model names or internet/external specifications. It works offline from current profiles, parsed results, telemetry/source maps, worker evidence, artifacts, comparisons, and existing validation rules.

## Contract Identity

Current contract fields:

- `contract_id`: `linux_validation_suite.qa_review`
- `contract_version`: `1`

Every single-result and batch QA payload must include both fields.

## Single Result Payload

Required top-level fields:

- `app_name`
- `app_version`
- `contract_id`
- `contract_version`
- `kind`: `qa_result_review`
- `started`
- `ended`
- `result_folder`
- `identity`
- `decisions`
- `validation_status`
- `validation`
- `import_readiness`
- `pre_import_sanity`
- `summary_refresh`
- `comparison_readiness`
- `comparison`
- `artifact_availability`
- `worker_failure_evidence`
- `action_item_summary`
- `telemetry_stability_warning_summary`

Stable nested sections:

- `identity`: folder identity, parsed-result availability, profile/result/outcome, operator workflow status, stage count, elapsed time.
- `decisions`: review readiness, import readiness mirror, comparison readiness mirror, escalation decision.
- `validation_status`: compact validation result, error/warning counts, issue category summaries.
- `import_readiness`: pass/warning/fail status, blocking flag, summary-refresh status, reasons.
- `comparison_readiness`: ready/status/reason/comparison folder. `comparison` is `null` unless a valid comparison folder is provided.
- `artifact_availability`: result artifact kind and important artifact flags.
- `worker_failure_evidence`: GPU worker counts, worker failure flag, verification pass count, validation worker issue mirrors.
- `action_item_summary`: total action count, severity counts, category counts, error-action flag.
- `telemetry_stability_warning_summary`: outcome class, warning/error categories, backend confidence counts, worker-verified/no-telemetry count.

Missing or failed result folders must still return a `qa_result_review` payload. They should use blocked/fail statuses and preserve the same top-level shape so QA tooling can render or escalate without special parser failures.

## Batch Payload

Required top-level fields:

- `app_name`
- `app_version`
- `contract_id`
- `contract_version`
- `kind`: `qa_result_review_batch`
- `started`
- `ended`
- `results_dir`
- `counts`
- `items`

`counts` must include:

- `total`
- `validation_by_result`
- `import_by_status`
- `review_by_status`
- `escalation_needed`

`items` contains full single-result QA payloads using this same contract id/version.

## Compatibility Expectations

QA tooling should prefer this payload over parsing report text or dense raw telemetry CSV files.

Existing parser/export schemas, validation thresholds, report wording, CLI behavior, and TUI behavior are separate contracts and are not changed by this QA payload contract.

Future optional reference-spec validation, if added, should be a separate local-data extension layer with explicit source/version metadata. Existing QA payload consumers should not assume such a hardware reference database exists today.
