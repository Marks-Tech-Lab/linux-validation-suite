"""Terminal execution evidence shared by result consumers; no live-host inference.

Recorded 'running' means last observed running, not proof that a copied run is
still alive. Only a caller supervising that execution may assert active=True.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
import json

from .lvs_worker_integrity import worker_cleanup_satisfied, worker_integrity_error_count

PASS = {"pass", "passed", "finished", "success", "successful", "stable"}
FAIL = {"fail", "failed", "failure", "error", "crashed", "unstable"}
ABORT = {"aborted", "manually_aborted", "interrupted"}
TERMINAL = PASS | FAIL | ABORT | {"warning", "warn"}


def _state(value):
    return str(value or "").strip().lower()


def _ended(value):
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return True
    except (ValueError, TypeError):
        return False


def execution_completion(manifest: dict, parsed: dict | None = None,
                         workers=(), *, active: bool = False) -> dict:
    """Failure is monotonic; missing completion never becomes affirmative PASS."""
    parsed = parsed or {}
    raw = _state(manifest.get("verdict") or parsed.get("Result") or parsed.get("result")
                 or (parsed.get("ReportSummary") or {}).get("Result"))
    windows = manifest.get("stage_windows") or []
    evidence = list(workers) + [w for stage in windows for w in stage.get("worker_results", []) if isinstance(w, dict)]
    def errors(events):
        return any(_state(e.get("severity") or "error") in {"error", "critical", "fatal"}
                   for e in events if isinstance(e, dict))

    failed = raw in FAIL or errors(manifest.get("error_events") or [])
    pending_worker = False
    for worker in evidence:
        status = _state(worker.get("status") or worker.get("Status"))
        code = worker.get("observed_exit_code")
        failed |= bool(worker.get("forced_kill") or worker.get("shutdown_timed_out"))
        counters = {k: worker[k] for k in ("error_count", "gl_error_count", "draw_mismatch_count",
            "compute_mismatch_count", "transfer_mismatch_count", "vram_mismatch_count") if k in worker}
        failed |= status in FAIL or bool(worker_integrity_error_count(
            [worker if status in PASS | {"ok"} else counters]))
        failed |= code is not None and code != 0 and not (code == -15 and worker.get("expected_termination"))
        failed |= not worker_cleanup_satisfied(worker)
        pending_worker |= status in {"running", "starting", "initializing"}
    failed |= any(_state(w.get("verdict")) in FAIL or errors(w.get("error_events") or []) for w in windows)
    ended = manifest.get("ended") if manifest else parsed.get("Ended") or parsed.get("ended")
    if manifest:
        stages_complete = bool(windows) and all(
            _state(w.get("verdict")) in TERMINAL and _ended(w.get("ended_iso") or w.get("ended_at"))
            for w in windows)
        planned = [p for p in manifest.get("plan", []) if p.get("enabled", True) and p.get("runnable", True)]
        finished_ids = {w.get("stage_id") for w in windows}
        stages_complete &= all(p.get("stage_id") in finished_ids for p in planned)
    else:
        # Legacy compatibility records retain their own terminal evidence;
        # never replace it with the reviewing checkout's observations.
        outcomes = (parsed.get("ReportSummary") or {}).get("StageOutcomes") or parsed.get("Segments") or []
        stages_complete = bool(outcomes) and all(
            _state(w.get("Verdict") or w.get("Result")) in TERMINAL for w in outcomes)
    complete = bool(_ended(ended) and stages_complete and not pending_worker and raw in TERMINAL)
    if failed:
        return {"status": "fail", "complete": complete, "reason": "Recorded worker or run failure; completion cannot override it."}
    aborted = raw if raw in ABORT else next((_state(w.get("verdict")) for w in windows if _state(w.get("verdict")) in ABORT), "")
    if aborted:
        return {"status": aborted, "complete": complete, "reason": "Execution was aborted or interrupted."}
    if complete:
        return {"status": "completed", "complete": True, "reason": "Run endpoint and terminal stage evidence recorded."}
    return {"status": "running" if active else "incomplete", "complete": False,
            "reason": "No complete run endpoint and finalized stage evidence; recorded running state is not proof of a live process."}


def completion_from_directory(root: Path, parsed: dict | None = None) -> dict:
    def read(path):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}
    manifest = read(root / "run_manifest.json")
    parsed = parsed if parsed is not None else read(root / "parsed_results_custom.json")
    workers = []
    # Interrupted runs have no normalized stage results. Preserve explicit raw
    # errors, but never fabricate a worker exit or cleanup from a snapshot.
    if manifest and not manifest.get("stage_windows"):
        workers = [read(p) for p in sorted((root / "worker_results").glob("*.json"))
                   if "guard" not in p.name and "progress" not in p.name]
    return execution_completion(manifest, parsed, workers)


def with_completion(result: dict, completion: dict) -> dict:
    """Ephemeral/export mirror; never edit historical files."""
    output = deepcopy(result)
    output["ExecutionCompletion"] = completion
    existing = _state(output.get("Result") or output.get("result") or (output.get("ReportSummary") or {}).get("Result"))
    if (completion["complete"] and completion["status"] == "completed"
            or completion["status"] == "fail" and existing in FAIL
            or completion["status"] in ABORT and existing in ABORT):
        return output
    state = completion["status"].upper()
    output["Result"] = state
    for key in ("verdict", "Verdict"):
        if key in output:
            output[key] = state
    if "result" in output:
        output["result"] = state
    report = output.setdefault("ReportSummary", {})
    report.update(Result=state, OutcomeClass=completion["status"], OutcomeSummary=completion["reason"])
    report["DepartmentUseSummary"] = {**(report.get("DepartmentUseSummary") or {}), "Status": "not_ready", "Blocking": True,
        "Decision": "Execution is not an accepted completed validation.", "Confidence": "incomplete_or_failed_execution"}
    output["report_summary"] = report
    for key in ("Stability",):
        if isinstance(output.get(key), dict):
            output[key]["Verdict"] = state
    if "StabilityInterpretation" in output:
        output["StabilityInterpretation"] = {"Outcome": state, "Summary": completion["reason"]}
    metadata = output.get("Metadata")
    if isinstance(metadata, dict):
        metadata["ReportSummary"] = report
        if isinstance(metadata.get("Stability"), dict):
            metadata["Stability"]["Verdict"] = state
            metadata["Stability"]["InterpretationSummary"] = output.get("StabilityInterpretation")
        if "ExecutionDetail" in metadata:
            metadata["ExecutionDetail"] = completion["reason"]
        if "Result" in metadata:
            metadata["Result"] = state
    return output
