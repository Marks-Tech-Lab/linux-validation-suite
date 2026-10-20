"""Automatic copied-project provenance, ordinary review and local Git checks."""

from copy import deepcopy
import hashlib
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from Modules import lvs_source_provenance as provenance
from Modules import lvs_source_review as review
from Modules.lvs_core import JsonStore
from smoke_tests.source_provenance_checks import _fixture


def _normal_run(source, result, expected_source_status="complete"):
    """Use the real execution/diagnostic artifact paths, no stamp or CLI setup."""
    from Modules.lvs_run_bootstrap import bootstrap_run_artifacts
    from Modules.lvs_run_artifacts import write_final_run_artifacts
    from Modules.lvs_run_metadata import RunMetadata
    from Modules.lvs_profile_models import ValidationProfile
    from Modules.lvs_segment_parser import SegmentParser
    from Modules.lvs_compat_exporter import CompatibilityExporter
    from Modules.lvs_summary_text import SummaryTextBuilder
    from Modules.lvs_profile_report_artifacts import ProfileReportArtifactWriter
    profile, metadata = ValidationProfile(profile_name="Automatic source fixture", stages=[]), RunMetadata()
    hardware = {"Hardware": {"Cpu": {"Name": "fixture CPU"}, "Gpu": [], "Storage": [], "Memory": {}, "Bios": {}, "Motherboard": {}}}
    with patch.object(provenance, "ROOT", source), patch.object(provenance, "write_build_stamp", side_effect=AssertionError("No setup command allowed")):
        boot = bootstrap_run_artifacts(app_name="LVS", app_version="0.5.1-alpha", profile_path=Path("Fixture.json"),
            profile=profile, labels=[], metadata=metadata, preflight={"plan": [], "validation": {}, "telemetry_capabilities": {}},
            run_dir=result, started_iso="2026-10-20T00:00:00+00:00", runtime_environment={}, backends={}, backend_details={},
            abort_on_fail_threshold=False, abort_on_worker_error=True, abort_on_system_fault=True,
            abort_run_on_stage_abort=True, privileged_helper_enabled=False, recovery_report={},
            collect_system_info=lambda *_: deepcopy(hardware), print_run_header=lambda *_: None,
            print_stage_skip=lambda *_: None, print_run_start=lambda *_: None)
        write_final_run_artifacts(run_dir=result, manifest_payload=boot.manifest_payload, app_name="LVS",
            app_version="0.5.1-alpha", profile=profile, metadata=metadata, started_iso="2026-10-20T00:00:00+00:00",
            ended_iso="2026-10-20T00:01:00+00:00", total_elapsed=60, system_info=boot.system_info,
            telemetry=SimpleNamespace(samples=[], interval_seconds=2, _gpu_sources=[], source_map=lambda: {"fields": {}}),
            stage_windows=[], executed_plan=[], recovery_report={}, skipped_stages=[], run_aborted=False,
            keep_raw_telemetry=False, export_compatibility_json=True, export_extended_json=True,
            segment_parser=SegmentParser(), exporter=CompatibilityExporter(), summary_exporter=SummaryTextBuilder(),
            stage_sensor_events=lambda _: [], stage_faults=lambda _: [], capture_run_end=lambda **_: None)
        def directory(label):
            path = result / label
            path.mkdir()
            return path
        writer = ProfileReportArtifactWriter(SimpleNamespace(), SimpleNamespace(new_report_dir=directory))
        diagnostics = [
            (writer.save_dry_run_report(Path("Fixture.json"), {}, SimpleNamespace(profile=profile, labels=[])), "dry_run_diagnostics.json"),
            (writer.save_cli_diagnostics_report(Path("Fixture.json"), profile, [], {}), "diagnostics.json"),
            (writer.save_cli_preflight_report(Path("Fixture.json"), profile, [], {}), "preflight_report.json"),
        ]
    observed = JsonStore.read(result / "run_manifest.json", {})["source_provenance"]
    assert observed["collection_mode"] == "automatic" and observed["git"]["status"] == "absent"
    assert observed["source"]["status"] == expected_source_status and observed["stamp_status"] == "missing"
    for path, name in diagnostics:
        saved = JsonStore.read(path / name, {})["source_provenance"]
        assert saved["source"] == observed["source"] and saved["git"]["status"] == "absent"
        summary = {"dry_run_diagnostics.json": "dry_run_summary.txt", "diagnostics.json": "diagnostics_summary.txt", "preflight_report.json": "preflight_summary.txt"}[name]
        assert "Source fingerprint:" in (path / summary).read_text()
        if expected_source_status == "complete":
            assert observed["source"]["digest"] in (path / summary).read_text()
    assert not (source / provenance.STAMP_NAME).exists()
    return observed


def run_automatic_source_workflow_checks():
    from Modules.lvs_result_comparison import ResultComparisonFacade
    from Modules.lvs_result_overview_reports import ResultOverviewReportBuilder
    from Modules.lvs_result_report_text import result_comparison_text
    from Modules.lvs_report_data import compile_report_data
    from Modules.lvs_report_html import render_report_html
    from Modules.lvs_summary_text import SummaryTextBuilder
    from Modules.linux_validation_suite_service import SuiteAppService
    from Modules.lvs_result_validation import ResultValidationFacade
    from Modules.lvs_pre_import_sanity import PreImportSanityFacade
    from Modules.lvs_result_artifacts import ResultArtifactFacade
    from Modules.lvs_tui_result_presentation import qa_result_review_presentation
    with TemporaryDirectory(prefix="lvs_automatic_source_") as tmp:
        root = Path(tmp)
        origin = root / "source_fixture"
        origin.mkdir()
        _fixture(origin)
        # Representative ordinary sources, including additions not tracked in Git.
        for name in [*provenance.REQUIRED, "Modules/lvs_source_provenance.py", "native/vulkan_compute_worker.py"]:
            target = origin / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(provenance.ROOT / name, target)
        (origin / "Modules" / "untracked.py").write_text("extra_source = 1\n")
        (origin / ".git").mkdir()
        deployed = root / "copied_fixture"
        shutil.copytree(origin, deployed, ignore=shutil.ignore_patterns(".git", provenance.STAMP_NAME))
        assert not (deployed / ".git").exists() and not (deployed / provenance.STAMP_NAME).exists()
        with patch.object(review, "ROOT", deployed), patch.object(provenance, "read_local_git", side_effect=AssertionError("Git not required")), patch.object(review, "read_local_git", side_effect=AssertionError("Git not required")):
            first, second, different = root / "first", root / "second", root / "different"
            observed = _normal_run(deployed, first)
            _normal_run(deployed, second)
            payload = ResultComparisonFacade().compare_result_folders(first, second)
            assert payload["source_comparison"]["status"] == "matching"
            assert "Source comparison: matching" in result_comparison_text(payload)
            assert "stamp" not in (first / "run_summary.txt").read_text().lower()
            (deployed / "Modules" / "untracked.py").write_text("extra_source = 2\n")
            _normal_run(deployed, different)
            payload = ResultComparisonFacade().compare_result_folders(first, different)
            assert payload["source_comparison"]["status"] == "different"
            assert "Source comparison: different" in result_comparison_text(payload)
            digest = observed["source"]["digest"]
            overview = ResultOverviewReportBuilder(SummaryTextBuilder(), lambda path: JsonStore.read(path, {}))
            assert digest in overview.result_overview_text(first)
            report = compile_report_data(first)
            assert report["run"]["source_identity"]["git_association"] == "unknown"
            assert digest in render_report_html(report)
            assert "Git: unknown association" in render_report_html(report)
            assert digest in (first / "run_summary.txt").read_text()

            # Exercise the same QA service and pure presentation used by CLI/TUI.
            service = SuiteAppService.__new__(SuiteAppService)
            service.summary_exporter = SummaryTextBuilder()
            service.result_validation = ResultValidationFacade(root)
            service.result_comparison = ResultComparisonFacade()
            service.pre_import_sanity = PreImportSanityFacade(root, service.result_validation, service.summary_exporter)
            service.result_artifacts = ResultArtifactFacade(root)
            qa = service.qa_result_review_payload(first, comparison_dir=second, refresh_summary=False)
            assert qa["source_identity"]["fingerprint"] == digest
            assert digest in qa_result_review_presentation(qa, "fixture help")
            assert qa["comparison"]["source_comparison"]["status"] == "matching"

            (deployed / "native" / "memory_stress_helper.c").unlink()
            incomplete_dir = root / "incomplete"
            _normal_run(deployed, incomplete_dir, expected_source_status="incomplete")
            assert ResultComparisonFacade().compare_result_folders(first, incomplete_dir)["source_comparison"]["status"] == "insufficient_evidence"
            with patch.object(provenance, "_source_snapshot", side_effect=PermissionError("fixture")):
                unavailable_dir = root / "unavailable"
                _normal_run(deployed, unavailable_dir, expected_source_status="unavailable")
            assert review.load_result_source_identity(unavailable_dir)["status"] == "unavailable"

        # Incomplete and unavailable evidence cannot become a matching source.
        incomplete = deepcopy(observed)
        incomplete["source"]["status"] = "incomplete"
        assert review.compare_source_identities(review.source_identity(observed), review.source_identity(incomplete))["status"] == "insufficient_evidence"
        assert review.compare_source_identities({}, {})["status"] == "unavailable"
        assert review.compare_source_identities({"status": "available"}, {"status": "available"})["status"] != "matching"
        assert review.source_identity({})["status"] == "not_recorded"
        assert review.source_identity({"contract_id": "wrong"})["status"] == "invalid_evidence"
        invalid = deepcopy(observed)
        invalid["collection_confidence"] = "insufficient"
        assert review.source_identity(invalid)["status"] == "invalid_evidence"
        invalid = deepcopy(observed)
        invalid["git"] = dict(status="available", commit="a" * 40, scoped_commit_match=True,
                              scoped_source_state="clean", association="unknown")
        assert review.source_identity(invalid)["git_association"] == "unknown"
        for bad in (True, None, -1, "0"):
            invalid = deepcopy(observed)
            invalid["source"]["error_count"] = bad
            assert review.source_identity(invalid)["status"] == "invalid_evidence"
        conflict = review.review_source_records([observed, {**observed, "source": {**observed["source"], "digest": "b" * 64}}], correlate=False)
        assert conflict["status"] == "conflicting_evidence" and not conflict["fingerprint"]
        end = {**observed, "source": {**observed["source"], "digest": "b" * 64}}
        assert review.source_identity(observed, end=end, changed=True)["change_status"] == "changed"
        assert review.source_identity(observed, end=end, changed=False)["change_status"] == "conflicting_evidence"


def _local_objects(root, algorithm="sha1"):
    """Independent Git-object byte fixtures; no history scan or network exists."""
    raw = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*")
           if path.is_file() and provenance._in_scope(path.relative_to(root).as_posix())}
    blobs = {}
    tree = []
    for name, data in sorted(raw.items()):
        oid = hashlib.new(algorithm, b"blob " + str(len(data)).encode() + b"\0" + data, usedforsecurity=False).hexdigest()
        blobs[oid] = data
        tree.append(f"100644 blob {oid} {len(data)}\t{name}".encode() + b"\0")
    length = 40 if algorithm == "sha1" else 64
    head, second = "a" * length, "b" * length
    calls = []
    def git(path, *args, input_bytes=None):
        calls.append(args)
        if args == ("rev-parse", "--show-toplevel"):
            return str(root).encode()
        if args == ("rev-parse", "--verify", "HEAD"):
            return head.encode()
        if args[:2] == ("cat-file", "-t") and args[2] in (head, second):
            return b"commit\n"
        if args[:2] == ("ls-tree", "-rlz") and args[2] in (head, second):
            return b"".join(tree)
        if args == ("cat-file", "--batch"):
            return b"".join(oid.encode() + b" blob " + str(len(blobs[oid])).encode() + b"\n" + blobs[oid] + b"\n"
                            for oid in input_bytes.decode().splitlines())
        raise AssertionError("Unexpected historical/network operation: " + repr(args))
    return git, calls, head, second


def _run_source_git_correlation_checks(algorithm):
    with TemporaryDirectory(prefix="lvs_source_git_objects_") as tmp:
        root = Path(tmp)
        _fixture(root)
        record = provenance.collect_source_provenance(root)
        (root / ".git").mkdir()
        git, calls, head, second = _local_objects(root, algorithm)
        identity = review.source_identity(record)
        (root / "native" / "cpu_stress_helper.c").write_text("different reviewing checkout\n")
        review._commit_source.cache_clear()
        with patch.object(review, "read_local_git", side_effect=git):
            assert review.correlate_local_source(dict(identity, scope="other_scope"), root=root)["local_git_correlation"]["status"] == "not_checked"
            assert review.correlate_local_source(dict(identity, fingerprint=""), root=root)["local_git_correlation"]["status"] == "not_checked"
            checked = review.correlate_local_source(identity, root=root)
            assert checked["local_git_correlation"]["status"] == "verified_match"
            assert checked["git_association"] == "unknown"  # Runtime Git absence is not rewritten.
            assert checked["local_git_correlation"]["matching_commits"] == [head]
            with_record = dict(identity, recorded_head=second)
            both = review.correlate_local_source(with_record, root=root)
            assert both["local_git_correlation"]["matching_commits"] == [head, second]
            assert both["local_git_correlation"]["unique_commit_identity"] is False
            assert all(row[0] in ("rev-parse", "cat-file", "ls-tree") for row in calls)
            wrong = dict(identity, fingerprint="0" * 64)
            assert review.correlate_local_source(wrong, root=root)["local_git_correlation"]["status"] == "no_match_in_checked_candidates"
            forged = dict(wrong, git_association="recorded_content_match", recorded_head=head)
            assert review.correlate_local_source(forged, root=root)["git_association"] == "conflicting_recorded_git_evidence"

        for failure in (FileNotFoundError(), ValueError("missing objects")):
            with patch.object(review, "read_local_git", side_effect=failure):
                assert review.correlate_local_source(identity, root=root)["local_git_correlation"]["status"] == "unavailable"
        review._commit_source.cache_clear()
        with patch.object(review, "read_local_git", side_effect=git), patch.object(review, "MAX_CORRELATION_BYTES", 1):
            assert review.correlate_local_source(identity, root=root)["local_git_correlation"]["status"] == "unavailable"
            assert review.source_identity(record)["status"] == "available"  # Correlation limits do not invalidate a fingerprint.
        review._commit_source.cache_clear()
        def truncated(path, *args, **kwargs):
            data = git(path, *args, **kwargs)
            return data[:-1] if args == ("cat-file", "--batch") else data
        with patch.object(review, "read_local_git", side_effect=truncated):
            assert review.correlate_local_source(identity, root=root)["local_git_correlation"]["status"] == "unavailable"
        review._commit_source.cache_clear()


def run_source_git_correlation_checks():
    for algorithm in ("sha1", "sha256"):
        _run_source_git_correlation_checks(algorithm)
