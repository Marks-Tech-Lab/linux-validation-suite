"""Unfinalized execution must never become completed PASS in any consumer."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from Modules.lvs_run_completion_evidence import execution_completion, completion_from_directory, with_completion
from Modules.lvs_report_data import compile_report_data
from Modules.lvs_result_report_adapters import list_result_entries, result_summary_text
from Modules.lvs_result_overview_reports import ResultOverviewReportBuilder
from Modules.lvs_summary_text import SummaryTextBuilder
from Modules.lvs_result_validation_checks import validate_run_manifest
from smoke_tests.standalone_report_checks import _build_fixture

ROOT = Path(__file__).resolve().parents[1]


def run_completion_evidence_checks():
    initial = {"started": "2026-10-26T14:09:23-04:00", "verdict": "pass",
        "plan": [{"stage_id": "amd", "enabled": True, "runnable": True}], "error_events": []}
    completed_worker = {"kind": "gpu", "status": "ok", "error_count": 0,
        "verification_passes": 28, "initial_verification_completed": True,
        "final_verification_completed": True, "cleanup_complete": True,
        "outstanding_system_memory_claim_bytes": 0, "allocation_claim_cleanup_error": ""}
    shapes = [completed_worker,
        {"kind": "gpu", "status": "running", "error_count": 0, "verification_passes": 22,
         "initial_verification_completed": True, "final_verification_completed": False},
        {k: v for k, v in completed_worker.items() if k not in
         {"cleanup_complete", "outstanding_system_memory_claim_bytes", "allocation_claim_cleanup_error"}}]
    # No cleanup record is manufactured by the reader for the third shape.
    with TemporaryDirectory(dir=ROOT) as tmp:
        root = Path(tmp)
        for index, worker in enumerate(shapes):
            folder = root / str(index); folder.mkdir(); (folder / "worker_results").mkdir()
            manifest = folder / "run_manifest.json"; manifest.write_text(json.dumps(initial))
            raw = folder / "worker_results/amd.json"; raw.write_text(json.dumps(worker))
            before = raw.read_bytes(), manifest.read_bytes()
            report = compile_report_data(folder)
            assert report["run"]["report_outcome"] == "INCOMPLETE"
            assert report["run"]["execution_completion"]["complete"] is False
            assert not report["stages"]
            # A stale summary or compatibility mirror cannot resurrect PASS.
            (folder / "run_summary.txt").write_text("Result: Finished\n")
            (folder / "parsed_results_custom.json").write_text(json.dumps({"Result": "Finished"}))
            assert "Result: INCOMPLETE" in result_summary_text(folder, SummaryTextBuilder())
            overview = ResultOverviewReportBuilder(SummaryTextBuilder(), lambda path: json.loads(path.read_text()))
            assert "INCOMPLETE" in overview.result_overview_text(folder)
            assert (raw.read_bytes(), manifest.read_bytes()) == before
        assert {entry.verdict for entry in list_result_entries(root)} == {"incomplete"}
        # An explicit shutdown failure overrides stale positive raw status.
        failed = root / "0/worker_results/amd.json"
        failed.write_text(json.dumps({**completed_worker, "forced_kill": True,
                                     "shutdown_timed_out": True, "observed_exit_code": -9}))
        assert compile_report_data(root / "0")["run"]["report_outcome"] == "FAIL"
        assert completion_from_directory(root / "0")["status"] == "fail"
        assert "Result: FAIL" in result_summary_text(root / "0", SummaryTextBuilder())
        for payload in ({**completed_worker, "status": "error", "error_count": 1},
                        {**completed_worker, "allocation_claim_cleanup_error": "release failed"},
                        {**completed_worker, "cleanup_complete": False}):
            assert execution_completion(initial, workers=[payload])["status"] == "fail"
        # A normally finalized PASS and historical compatibility remain accepted.
        good = root / "good"; good.mkdir(); _build_fixture(good, native="pass")
        assert compile_report_data(good)["run"]["report_outcome"] == "PASS"
        manifest = json.loads((good / "run_manifest.json").read_text())
        assert execution_completion(manifest)["complete"]
        # A terminal-looking manifest cannot conceal orchestrator SIGKILL.
        stale = deepcopy(manifest)
        stale["stage_windows"][0]["worker_results"] = [{**completed_worker,
            "forced_kill": True, "shutdown_timed_out": True, "observed_exit_code": -9}]
        (good / "run_manifest.json").write_text(json.dumps(stale))
        assert compile_report_data(good)["run"]["report_outcome"] == "FAIL"
        entries = {entry.name: entry.verdict for entry in list_result_entries(root)}
        assert entries["good"].lower() in {"fail", "failed"}
        assert any(issue["category"] == "worker_failure" for issue in validate_run_manifest(good, {})["issues"])
        (good / "run_manifest.json").write_text(json.dumps(manifest))
        for change in ({"ended": ""}, {"ended": "invalid"}, {"stage_windows": []},
                       {"plan": [{"stage_id": "not_completed", "runnable": True}]}):
            assert execution_completion({**manifest, **change})["status"] == "incomplete"
        bad_window = deepcopy(manifest); bad_window["stage_windows"][0]["ended_iso"] = ""
        assert execution_completion(bad_window)["status"] == "incomplete"
        assert execution_completion({**manifest, "verdict": "fail"})["status"] == "fail"
        assert execution_completion({**initial, "verdict": "manually_aborted"})["status"] == "manually_aborted"
        assert execution_completion({**initial, "verdict": "interrupted"})["status"] == "interrupted"
        assert execution_completion({**initial, "verdict": "running"}, active=True)["status"] == "running"
        assert execution_completion({**initial, "verdict": "running"})["status"] == "incomplete"
        # Missing kernel capture never means no fault: completion only attests
        # recorded lifecycle, and does not create a clean kernel observation.
        assert not (good / "advanced_debug").exists()
        legacy = {"Result": "Finished", "Ended": manifest["ended"],
                  "ReportSummary": {"StageOutcomes": [{"Verdict": "pass"}]}}
        assert execution_completion({}, legacy)["complete"]
        assert execution_completion({}, {"Result": "Finished"})["status"] == "incomplete"
        mirrored = with_completion(legacy, execution_completion(initial))
        assert mirrored["Result"] == mirrored["ReportSummary"]["Result"] == "INCOMPLETE"
        assert mirrored["ReportSummary"]["DepartmentUseSummary"]["Blocking"]
        assert legacy["Result"] == "Finished"
    # Bootstrap must not start a real capture as a provisional PASS.
    source = (ROOT / "Modules/lvs_run_bootstrap.py").read_text()
    assert '"verdict": "running"' in source and '"execution_state": "running"' in source
