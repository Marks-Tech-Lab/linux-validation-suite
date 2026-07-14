# Manual Test Checklist

Use this checklist for a short end-to-end manual pass before a public alpha or
operator workflow trial. Record the result folder name, profile used, terminal
size if relevant, and any blocker or confusing screen.

## TUI Workflow

1. Launch the TUI:
   - Run `.venv/bin/python linux_validation_suite_tui.py`.
   - Confirm the profile list loads and the first profile summary is readable.

2. Profile review:
   - Highlight `Quick Test.json` and one GPU-focused profile if available.
   - Confirm profile summary, stages, duration, and workload intent are clear.

3. Dry run:
   - Press `D` on the selected profile.
   - Confirm readiness output shows runnable stages, blockers, warnings,
     telemetry/backend notes, and saved report path.

4. Run setup review:
   - Open setup with `T`.
   - Review description, heatsoak, system metadata, stage durations, trim,
     enabled stages, and advanced debug toggle.
   - Confirm blocked or warning readiness is visible before execution.

5. Run launch:
   - From setup, choose Review and run.
   - Confirm the first press shows readiness and the second press starts only
     if not blocked.

6. Live progress and cancel:
   - Confirm the TUI shows current stage, elapsed time, remaining time when
     available, latest event, and compact output tail.
   - Confirm keyboard and mouse cancel request the same safe stop path.

7. Post-run context:
   - Confirm completion, warning, failure, or abort status is understandable.
   - Confirm latest result folder, artifact availability, wall-wattage prompt,
     optional upload status, and next actions are visible.
   - If the run fails before a result folder exists, confirm result-folder
     actions are clearly unavailable.

8. Latest result handoff:
   - Open Results with `S`.
   - Confirm the completed/latest result is selected when present.

## Result Review Workflow

9. Result summary and stage detail:
   - Confirm selected result overview and run summary load.
   - Press `D` in Results and confirm stage/GPU details are readable.

10. QA review:
    - Press `E`.
    - Confirm review/import/compare/escalate status, validation summary,
      worker evidence, action items, telemetry/stability warnings, artifacts,
      and operator next steps are visible.

11. Validation:
    - Press `V`.
    - Confirm selected-result validation text is shown and saved.

12. Pre-import sanity:
    - Press `M`.
    - Confirm selected-result pre-import sanity runs, refresh status is visible,
      and output is saved.

13. Comparison:
    - Press `O` on the result to compare.
    - Select a baseline result and press Enter.
    - Confirm the comparison report renders and next steps are clear.

14. Artifact map/detail:
    - Press `F`.
    - Confirm core result, telemetry/source evidence, reports/review,
      comparison, and debug artifacts are grouped with paths where available.

15. Core settings:
    - Open Settings with `X`.
    - Confirm raw telemetry retention, wall-wattage prompt, optional upload
      readiness, and per-run advanced debug note are visible.
    - Toggle only a safe setting, then toggle it back.

## QA Wrapper Workflow

16. Single-result QA payload:
    - Run `.venv/bin/python linux_validation_suite_qa.py review "RESULT_DIR"`.
    - Confirm JSON includes `contract_id`, `contract_version`,
      identity/status, validation status, import readiness, artifact
      availability, worker evidence, action item summary, and
      telemetry/stability warning summary.

17. Batch QA payload:
    - Run `.venv/bin/python linux_validation_suite_qa.py batch "RESULT_DIR_1" "RESULT_DIR_2"`.
    - Confirm JSON includes batch counts and per-result payloads with the same
      versioned contract shape.

## Pass Criteria

- Operator can complete profile review -> dry run -> setup -> run -> post-run
  -> result review without using external scripts for basic status.
- QA wrapper emits stable JSON for single and batch review.
- Missing optional upload configuration is reported as not configured, not a
  crash.
- No validation, export, parser, or pass/fail behavior changes are needed.
- Any confusing or blocked step is captured with the screen, selected
  profile/result, and expected operator action.
