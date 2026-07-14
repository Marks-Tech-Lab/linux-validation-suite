# QA Review Wrapper Usage

`linux_validation_suite_qa.py` is the supported thin command wrapper for external QA tooling that needs the versioned QA review payload without importing internal suite modules.

## Single Result

```bash
.venv/bin/python linux_validation_suite_qa.py review "results/<result-folder>"
```

With a comparison/baseline result:

```bash
.venv/bin/python linux_validation_suite_qa.py review "results/current" --comparison "results/baseline"
```

## Batch

```bash
.venv/bin/python linux_validation_suite_qa.py batch "results/current" "results/baseline"
```

If no result folders are passed to `batch`, the wrapper asks `SuiteAppService` for the configured completed-result candidates.

## Notes For QA Tooling

- Output is JSON on stdout.
- Non-zero exit means wrapper execution failed; stderr contains the command error.
- The payload contract is identified by `contract_id` and `contract_version`.
- The wrapper does not implement import policy decisions or validation rules.
- The wrapper does not judge unknown hardware against external CPU/GPU/platform specifications. It summarizes suite-generated evidence and existing validation outcomes only.
- `--refresh-summary` is opt-in so automation can request read-only review payloads by default.
- `--settings PATH` can point the wrapper at a specific suite settings file.
- Missing or invalid result paths should still return a versioned payload shape when the backend can construct one; tooling should inspect payload readiness/status fields instead of assuming every JSON payload is importable.
- Operators should use the TUI/CLI review screens for manual work. This wrapper is the supported external automation boundary.

See `QA_REVIEW_PAYLOAD_CONTRACT.md` for required payload fields.
