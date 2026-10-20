"""Deterministic source/build provenance and normal artifact-path regressions."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from Modules import lvs_source_provenance as provenance


def _fixture(root):
    for name in provenance.REQUIRED:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# fixture source\n", encoding="utf-8")
    (root / "profiles").mkdir()
    (root / "profiles" / "Fixture.json").write_text('{}\n', encoding="utf-8")


def _git_fixture(root, algorithm="sha1"):
    """Snapshot HEAD blobs independently, without creating a deployment repo."""
    (root / ".git").mkdir(exist_ok=True)
    entries = []
    for path in root.rglob("*"):
        if path.is_file() and provenance._in_scope(path.relative_to(root).as_posix()):
            raw = path.read_bytes()
            oid = hashlib.new(algorithm, b"blob " + str(len(raw)).encode() + b"\0" + raw, usedforsecurity=False).hexdigest()
            entries.append(b"100644 blob " + oid.encode() + b"\t" + path.relative_to(root).as_posix().encode() + b"\0")
    commit = "a" * (40 if algorithm == "sha1" else 64)
    def run(command, **kwargs):
        assert command[:3] == ["git", "-C", str(root)]
        assert kwargs["timeout"] == 5
        assert kwargs["env"]["GIT_OPTIONAL_LOCKS"] == "0"
        assert command[3:5] == ["-c", "protocol.allow=never"]
        assert kwargs["env"]["GIT_NO_LAZY_FETCH"] == kwargs["env"]["GIT_NO_REPLACE_OBJECTS"] == "1"
        args = command[5:]
        if args == ["rev-parse", "--show-toplevel"]:
            value = str(root).encode() + b"\n"
        elif args == ["rev-parse", "--verify", "HEAD"]:
            value = commit.encode() + b"\n"
        elif args == ["ls-tree", "-rz", commit]:
            value = b"".join(entries)
        elif args == ["status", "--porcelain=v1", "--untracked-files=no"]:
            value = b""  # Byte comparison must catch changes despite clean status.
        else:
            raise AssertionError(command)
        return SimpleNamespace(stdout=value)
    return run


def run_source_provenance_checks():
    for algorithm in ("sha1", "sha256"):
        with TemporaryDirectory(prefix="lvs_provenance_fixture_") as tmp:
            root = Path(tmp)
            _fixture(root)
            run_git = _git_fixture(root, algorithm)
            with patch.object(provenance.subprocess, "run", side_effect=run_git):
                clean = provenance.collect_source_provenance(root)
                assert clean["source"]["status"] == "complete"
                assert clean["source"]["digest"] == "5baec3337bb07dfe1a3b3b1bce2c7d00013960c59d7a6871a45cb15cf7c6f265", "v1 scope/protocol must remain byte-identical"
                assert clean["git"]["scoped_commit_match"] is True
                assert clean["git"]["scoped_source_state"] == "clean"
                stamp = provenance.write_build_stamp(root, "development-fixture")
                stamped = provenance.collect_source_provenance(root)
                assert stamped["source"] == clean["source"]
                assert stamped["stamp_status"] == "content_match"
                assert stamped["capture"]["association"] == "capture_claim_content_matches"
                # Same-size byte edit defeats stat-only or optimistic Git-status checks.
                path = root / "native" / "cpu_stress_helper.c"
                path.write_text("# changed source\n", encoding="utf-8")
                changed = provenance.collect_source_provenance(root)
                assert changed["git"]["scoped_commit_match"] is False
                assert changed["git"]["scoped_source_state"] == "modified"
                assert changed["stamp_status"] == "stale"
                assert changed["capture"]["association"] == "unverified_stale_capture_claim"
                path.write_text("# fixture source\n", encoding="utf-8")
                extra = root / "Modules" / "untracked_worker.py"
                extra.write_text("unexpected = True\n", encoding="utf-8")
                untracked = provenance.collect_source_provenance(root)
                assert untracked["source"]["digest"] != clean["source"]["digest"]
                assert untracked["git"]["scoped_source_state"] == "modified"
                extra.unlink()
                # Capture modified source honestly; its content may verify while
                # its Git commit must never be represented as exact source.
                extra.write_text("new_worker = True\n", encoding="utf-8")
                dirty_stamp = provenance.write_build_stamp(root)
                assert dirty_stamp["git"]["scoped_source_state"] == "modified"
                shutil.rmtree(root / ".git")
                dirty_copy = provenance.collect_source_provenance(root)
                assert dirty_copy["stamp_status"] == "content_match"
                assert dirty_copy["git"]["status"] == "absent"
                assert dirty_copy["capture"]["scoped_source_state"] == "modified"
                (root / ".git").mkdir()
                extra.unlink()
                (root / provenance.STAMP_NAME).write_text(json.dumps(stamp), encoding="utf-8")

            # A copy without Git retains a checked content identity and only a
            # capture claim for its commit, not independently verified Git history.
            shutil.rmtree(root / ".git")
            with patch.object(provenance.subprocess, "run", side_effect=AssertionError("must work offline without Git")):
                copied = provenance.collect_source_provenance(root)
            assert copied["source"] == clean["source"]
            assert copied["git"]["status"] == "absent"
            assert copied["capture"]["commit"] == clean["git"]["commit"]
            assert copied["stamp_status"] == "content_match"
            legacy_stamp = deepcopy(stamp)
            legacy_stamp["git"].pop("association", None)
            legacy_stamp.pop("record_sha256")
            legacy_stamp["record_sha256"] = hashlib.sha256(provenance._canonical(legacy_stamp)).hexdigest()
            (root / provenance.STAMP_NAME).write_text(json.dumps(legacy_stamp), encoding="utf-8")
            legacy = provenance.collect_source_provenance(root)
            assert legacy["stamp_status"] == "content_match" and legacy["git"]["status"] == "absent"
            assert legacy["source"] == clean["source"]
            assert "scoped_commit_match" not in copied["git"]
            assert copied["native_binary_identity"] == copied["external_dependencies"] == "not_assessed"
            text = json.dumps(copied)
            assert str(root) not in text and "remote" not in copied["git"]
            # Excluded results, archives, binaries, secrets and labels are not
            # recursively hashed or published as build contents.
            for name in ("results/private.json", "profiles/Archived/private.json", "build/helper",
                         "settings/global_settings.json", ".env", "README.md", "docs/private.md"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("private ignored bytes", encoding="utf-8")
            assert provenance.collect_source_provenance(root)["source"] == clean["source"]
            altered = deepcopy(stamp)
            altered["git"]["commit"] = "b" * 40
            for invalid in ({}, [], altered, {**stamp, "source": None}):
                (root / provenance.STAMP_NAME).write_text(json.dumps(invalid), encoding="utf-8")
                assert provenance.collect_source_provenance(root)["stamp_status"] == "invalid"
            # Reject malformed/incomplete contracts even with a fresh envelope
            # checksum. A checksum alone is not schema or identity verification.
            for field, value in (("git", {}), ("contract_version", True), ("contract_version", 2),
                                 ("runtime_version", ""), ("runtime_version", "contradictory-version")):
                invalid = deepcopy(stamp)
                invalid[field] = value
                invalid.pop("record_sha256")
                invalid["record_sha256"] = hashlib.sha256(provenance._canonical(invalid)).hexdigest()
                (root / provenance.STAMP_NAME).write_text(json.dumps(invalid), encoding="utf-8")
                assert provenance.collect_source_provenance(root)["stamp_status"] == "invalid"
            (root / provenance.STAMP_NAME).write_text('{"truncated":', encoding="utf-8")
            assert provenance.collect_source_provenance(root)["stamp_status"] == "invalid"
            (root / provenance.STAMP_NAME).write_bytes(b"x" * 65537)
            assert provenance.collect_source_provenance(root)["stamp_status"] == "invalid"
            (root / provenance.STAMP_NAME).unlink()
            assert provenance.collect_source_provenance(root)["stamp_status"] == "missing"
            (root / ".git").mkdir()
            for failure in (FileNotFoundError(), subprocess.TimeoutExpired("git", 5)):
                with patch.object(provenance.subprocess, "run", side_effect=failure):
                    result = provenance.collect_source_provenance(root)
                assert result["git"]["status"] == "unavailable" and not result["git"]["commit"]
                assert result["source"]["status"] == "complete"
            # Incomplete content cannot be stamped or declared exact.
            (root / "native" / "cpu_stress_helper.c").unlink()
            assert provenance.collect_source_provenance(root)["source"]["status"] == "incomplete"
            try:
                provenance.write_build_stamp(root)
            except ValueError:
                pass
            else:
                raise AssertionError("incomplete build stamped")

    with TemporaryDirectory(prefix="lvs_provenance_edges_") as tmp:
        root = Path(tmp)
        _fixture(root)
        try:
            (root / "Modules" / "linked.py").symlink_to(root / "linux_validation_suite.py")
        except (OSError, NotImplementedError):
            pass  # Optional filesystem feature; never required for ordinary capture.
        else:
            assert provenance.collect_source_provenance(root)["source"]["status"] == "incomplete"
            (root / "Modules" / "linked.py").unlink()
            (root / provenance.STAMP_NAME).symlink_to(root / "linux_validation_suite.py")
            assert provenance.collect_source_provenance(root)["stamp_status"] == "invalid"
            (root / provenance.STAMP_NAME).unlink()
        with patch.object(provenance, "MAX_SOURCE_BYTES", 1):
            assert provenance.collect_source_provenance(root)["source"]["status"] == "incomplete"
        for label in ("/private/path", "user@example.com", "x" * 81):
            try:
                provenance.write_build_stamp(root, label)
            except ValueError:
                pass
            else:
                raise AssertionError("unsafe operator label accepted")


def run_source_provenance_artifact_checks():
    from Modules.lvs_core import JsonStore
    from Modules.lvs_run_bootstrap import bootstrap_run_artifacts
    from Modules.lvs_run_artifacts import write_final_run_artifacts
    from Modules.lvs_run_metadata import RunMetadata
    from Modules.lvs_profile_models import ValidationProfile
    from Modules.lvs_segment_parser import SegmentParser
    from Modules.lvs_compat_exporter import CompatibilityExporter
    from Modules.lvs_summary_text import SummaryTextBuilder
    from Modules.lvs_profile_report_artifacts import ProfileReportArtifactWriter
    from Modules.lvs_report_data import compile_report_data
    from Modules.lvs_report_html import render_report_html
    with TemporaryDirectory(prefix="lvs_provenance_artifacts_") as tmp:
        root = Path(tmp)
        source = root / "source"
        source.mkdir()
        _fixture(source)
        observed = provenance.collect_source_provenance(source)
        run_dir = root / "execution"
        profile, metadata = ValidationProfile(profile_name="Provenance fixture", stages=[]), RunMetadata()
        hardware = {"Hardware": {"Cpu": {"Name": "Fixture CPU"}, "Gpu": [], "Storage": [], "Memory": {}, "Bios": {}, "Motherboard": {}}}
        with patch("Modules.lvs_run_bootstrap.collect_source_provenance", return_value=observed):
            boot = bootstrap_run_artifacts(app_name="LVS", app_version="0.5.1-alpha", profile_path=Path("Fixture.json"),
                profile=profile, labels=[], metadata=metadata, preflight={"plan": [], "validation": {}, "telemetry_capabilities": {}},
                run_dir=run_dir, started_iso="2026-10-20T00:00:00+00:00", runtime_environment={}, backends={}, backend_details={},
                abort_on_fail_threshold=False, abort_on_worker_error=True, abort_on_system_fault=True,
                abort_run_on_stage_abort=True, privileged_helper_enabled=False, recovery_report={},
                collect_system_info=lambda *_: deepcopy(hardware), print_run_header=lambda *_: None,
                print_stage_skip=lambda *_: None, print_run_start=lambda *_: None)
        assert boot.manifest_payload["source_provenance"] == boot.system_info["SourceProvenance"] == observed
        # Record source changes, without changing workload verdicts or pretending
        # that a start-only snapshot established an unchanged whole execution.
        (source / "Modules" / "later.py").write_text("changed = True\n", encoding="utf-8")
        ending = provenance.collect_source_provenance(source)
        with patch("Modules.lvs_run_artifacts.collect_source_provenance", return_value=ending):
            write_final_run_artifacts(run_dir=run_dir, manifest_payload=boot.manifest_payload, app_name="LVS",
                app_version="0.5.1-alpha", profile=profile, metadata=metadata, started_iso="2026-10-20T00:00:00+00:00",
                ended_iso="2026-10-20T00:01:00+00:00", total_elapsed=60, system_info=boot.system_info,
                telemetry=SimpleNamespace(samples=[], interval_seconds=2, _gpu_sources=[], source_map=lambda: {"fields": {}}),
                stage_windows=[], executed_plan=[], recovery_report={}, skipped_stages=[], run_aborted=False,
                keep_raw_telemetry=False, export_compatibility_json=True, export_extended_json=True,
                segment_parser=SegmentParser(), exporter=CompatibilityExporter(), summary_exporter=SummaryTextBuilder(),
                stage_sensor_events=lambda _: [], stage_faults=lambda _: [], capture_run_end=lambda **_: None)
        manifest = JsonStore.read(run_dir / "run_manifest.json", {})
        extended = JsonStore.read(run_dir / "parsed_results_extended.json", {})
        custom = JsonStore.read(run_dir / "parsed_results_custom.json", {})
        assert manifest["source_changed_during_run"] is True
        assert manifest["source_provenance_end"] == ending
        assert manifest["source_provenance"] == extended["source_provenance"] == custom["SystemInfo"]["SourceProvenance"] == observed
        report = compile_report_data(run_dir)
        assert report["run"]["source_provenance"] == observed
        html = render_report_html(report)
        assert observed["source"]["digest"] in html and "not binary attestation" in html
        # A report created later must not attribute a legacy result to its own
        # renderer's source checkout.
        for name in ("run_manifest.json", "system_info.json", "parsed_results_custom.json", "parsed_results_extended.json"):
            data = JsonStore.read(run_dir / name, {})
            data.pop("source_provenance", None)
            data.pop("SourceProvenance", None)
            if isinstance(data.get("SystemInfo"), dict):
                data["SystemInfo"].pop("SourceProvenance", None)
            JsonStore.write(run_dir / name, data)
        assert compile_report_data(run_dir)["run"]["source_provenance"] == {"status": "not_recorded"}

        counter = 0
        def report_directory(_label):
            nonlocal counter
            counter += 1
            path = root / str(counter)
            path.mkdir()
            return path
        writer = ProfileReportArtifactWriter(SimpleNamespace(), SimpleNamespace(new_report_dir=report_directory))
        with patch("Modules.lvs_profile_report_artifacts.collect_source_provenance", return_value=observed):
            dry = writer.save_dry_run_report(Path("Fixture.json"), {}, SimpleNamespace(profile=profile, labels=[]))
            diag = writer.save_cli_diagnostics_report(Path("Fixture.json"), profile, [], {})
            preflight = writer.save_cli_preflight_report(Path("Fixture.json"), profile, [], {})
        for path, name in ((dry, "dry_run_diagnostics.json"), (diag, "diagnostics.json"), (preflight, "preflight_report.json")):
            assert JsonStore.read(path / name, {})["source_provenance"] == observed
