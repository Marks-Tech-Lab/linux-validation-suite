#!/usr/bin/env python3
"""Focused Migration v2 Wave B operator-UX checks."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Modules.lvs_diagnostics_cli import DiagnosticsCliAdapter
from Modules.lvs_local_migration import main as local_migration_main
from Modules.lvs_migration_models import MIGRATION_BUNDLE_KIND, MIGRATION_CONTRACT_ID
from Modules.lvs_migration_ux import (
    MigrationBundleCandidate,
    bundle_candidate_detail,
    destructive_action_count,
    discover_migration_bundles,
    migration_plan_text,
    resolution_label,
    successful_apply_text,
)
from Modules.lvs_migration_v2 import V2ContentPayload, write_v2_bundle


def _write_bundle(path: Path, generated_at: str, *, suite_version: str = "0.3.1-alpha") -> None:
    write_v2_bundle(
        path,
        suite_version=suite_version,
        generated_at=generated_at,
        source={"path_mode": "logical_roots", "logical_roots": {}},
        contents=(),
        omitted_classes=(),
    )


def _write_v1_manifest(path: Path, generated_at: str) -> None:
    path.mkdir()
    (path / "migration_manifest.json").write_text(json.dumps({
        "contract_id": MIGRATION_CONTRACT_ID,
        "contract_version": 1,
        "kind": MIGRATION_BUNDLE_KIND,
        "suite_version": "0.3.0",
        "generated_at": generated_at,
        "private_bundle": True,
        "safe_to_share_publicly": False,
        "files": [],
    }), encoding="utf-8")


def _v1_validator(path: Path) -> dict:
    return {"errors": [] if path.name.startswith("v1") else ["fixture invalid"], "warnings": []}


def _tree_snapshot(root: Path) -> tuple[tuple[str, str, int, int], ...]:
    snapshot = []
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        kind = "symlink" if path.is_symlink() else "dir" if path.is_dir() else "file"
        snapshot.append((path.relative_to(root).as_posix(), kind, info.st_size, info.st_mtime_ns))
    return tuple(snapshot)


def test_bundle_discovery_is_bounded_safe_and_sorted() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "configured-bundles"
        root.mkdir()
        _write_bundle(root / "older", "2026-09-14T18:03:00+00:00")
        _write_bundle(root / "newer", "2026-09-16T09:20:00+00:00")
        _write_bundle(root / "timezone-equivalent", "2026-09-16T05:20:00-04:00")
        _write_bundle(root / "equal-b", "2026-09-15T12:00:00+00:00")
        _write_bundle(root / "equal-a", "2026-09-15T12:00:00+00:00")
        _write_bundle(root / "naive-time", "2026-09-18T12:00:00")
        _write_v1_manifest(root / "v1-legacy", "2026-09-13T08:00:00+00:00")
        malformed = root / "Private_Migration_Bundle_malformed"
        malformed.mkdir()
        (malformed / "migration_manifest.json").write_text("{", encoding="utf-8")
        future = root / "Private_Migration_Bundle_future"
        future.mkdir()
        (future / "migration_manifest.json").write_text(json.dumps({
            "contract_version": 3, "generated_at": "2026-09-19T00:00:00+00:00",
            "suite_version": "future", "private_bundle": True,
        }), encoding="utf-8")
        checksum = root / "Private_Migration_Bundle_checksum"
        payload = V2ContentPayload(
            "settings", "settings", "global_settings", "payload/settings.json", "settings",
            "linux_validation_suite.migration.settings_payload", 1, b"{}",
        )
        write_v2_bundle(checksum, suite_version="0.3.1-alpha",
            generated_at="2026-09-12T00:00:00+00:00",
            source={"path_mode": "logical_roots", "logical_roots": {}}, contents=(payload,))
        (checksum / "payload/settings.json").write_bytes(b"tampered")
        missing = root / "Private_Migration_Bundle_missing"
        write_v2_bundle(missing, suite_version="0.3.1-alpha",
            generated_at="2026-09-11T00:00:00+00:00",
            source={"path_mode": "logical_roots", "logical_roots": {}}, contents=(payload,))
        (missing / "payload/settings.json").unlink()
        nested_parent = root / "not-a-bundle"
        nested_parent.mkdir()
        _write_bundle(nested_parent / "nested", "2026-09-17T00:00:00+00:00")
        for index in range(12):
            (root / f"unrelated-{index}").mkdir()
            (root / f"unrelated-file-{index}.txt").write_text("unrelated", encoding="utf-8")
        symlink = root / "linked"
        symlink.symlink_to(root / "newer", target_is_directory=True)

        before = _tree_snapshot(root)
        candidates = discover_migration_bundles(root, validate_v1=_v1_validator)
        assert _tree_snapshot(root) == before
        names = [item.path.name for item in candidates]
        assert names[:5] == ["newer", "timezone-equivalent", "equal-a", "equal-b", "older"]
        assert "v1-legacy" in names and malformed.name in names and future.name in names
        assert names.index("naive-time") > names.index("v1-legacy")
        assert names.index("naive-time") < names.index(future.name)
        assert "nested" not in names and "not-a-bundle" not in names and "linked" not in names
        assert not any(name.startswith("unrelated-") for name in names)
        invalid = next(item for item in candidates if item.path.name == malformed.name)
        unsupported = next(item for item in candidates if item.path.name == future.name)
        checksum_invalid = next(item for item in candidates if item.path.name == checksum.name)
        missing_invalid = next(item for item in candidates if item.path.name == missing.name)
        legacy = next(item for item in candidates if item.path.name == "v1-legacy")
        assert not invalid.valid and invalid.safe_status == "Missing or malformed migration manifest."
        assert not unsupported.valid and unsupported.safe_status == "Unsupported migration contract version."
        assert not checksum_invalid.valid and "does not match" in checksum_invalid.safe_status
        assert not missing_invalid.valid and "missing or unsafe" in missing_invalid.safe_status
        assert legacy.valid and "profiles and results are not included" in legacy.safe_status
        assert "v1 limitations" in bundle_candidate_detail(legacy)
        long_candidate = MigrationBundleCandidate(
            root / "long", "2026-09-16T00:00:00+00:00", "release\n" + "x" * 200,
            2, (), "profiles " + "y" * 300, 0, True, 0, True, "Valid migration bundle.",
        )
        assert "\n" not in long_candidate.row_label and len(long_candidate.row_label) < 170

        empty = Path(tmp) / "empty"
        empty.mkdir()
        assert discover_migration_bundles(empty, validate_v1=_v1_validator) == ()


def _conflict_plan(*, resolved: str | None = None, drift: bool = False) -> dict:
    action = {
        "action_id": "profile:stock",
        "content_class": "modified_stock_profile",
        "logical_item": "Stock.json",
        "disposition": "conflict" if resolved is None else "import_renamed",
        "reason_code": "MODIFIED_STOCK_CONFLICT",
        "destructive": resolved == "replace_destination",
        "requires_user_choice": resolved is None,
        "allowed_resolutions": ["keep_destination", "import_source_as_renamed", "replace_destination"],
        "selected_resolution": resolved,
        "safe_summary": "Source and destination stock profiles differ.",
        "dependencies": ["menu:engineering"],
        "destination": {"root_role": "profiles", "relative_path": "Stock.json"},
    }
    errors = ([{
        "error_code": "DESTINATION_CHANGED_AFTER_PREVIEW", "phase": "plan",
        "safe_message": "Destination state changed after preview.",
        "diagnostics": {"operation": "recheck", "transaction_id": "tx-redacted"},
    }] if drift else [])
    return {
        "valid": not drift,
        "apply_ready": resolved is not None and not drift,
        "requires_restart": True,
        "actions": [action],
        "errors": errors,
        "warnings": [],
        "summary": {
            "settings": {"import_source": 2, "preserve_destination": 3},
            "profiles": {"conflict": 1},
            "history": {"merged": 4, "duplicate": 1},
        },
    }


def test_structured_preview_and_error_projection() -> None:
    text = migration_plan_text(_conflict_plan(), include_details=True)
    assert "Settings:" in text and "Profiles:" in text and "History:" in text
    assert "BLOCKED" in text and "profile:stock" in text and "menu:engineering" in text
    assert "Source and destination stock profiles differ." in text
    assert "summary_text" not in text

    drift = migration_plan_text(_conflict_plan(drift=True), include_details=True)
    assert "DESTINATION_CHANGED_AFTER_PREVIEW [plan]" in drift
    assert "technical details: operation=recheck, transaction_id=tx-redacted" in drift
    assert "raw payload" not in drift

    safe_merge = dict(_conflict_plan(resolved="keep_destination"))
    safe_merge["actions"] = [{
        "action_id": "settings-output", "content_class": "settings",
        "destructive": True, "selected_resolution": None,
    }]
    assert destructive_action_count(safe_merge) == 1
    assert destructive_action_count(_conflict_plan(resolved="replace_destination")) == 1
    assert resolution_label({"content_class": "settings_field"}, "replace_destination") == (
        "Use source (replace destination value)"
    )
    assert "RESTART REQUIRED" in successful_apply_text(_conflict_plan(resolved="keep_destination"))


class _FakeMigrationManager:
    def __init__(self, candidate: MigrationBundleCandidate, *, destination_root: Path | None = None) -> None:
        self.candidate = candidate
        self.destination_root = destination_root
        self.preview_calls: list[dict[str, str]] = []
        self.apply_calls: list[dict[str, str]] = []

    def discover_bundles(self):
        return (self.candidate,)

    def preview_restore(self, _path, *, resolutions=None):
        selected = dict(resolutions or {})
        self.preview_calls.append(selected)
        resolution = selected.get("profile:stock")
        return SimpleNamespace(valid=True, plan=_conflict_plan(resolved=resolution))

    def apply_restore(self, _path, *, yes, resolutions=None):
        assert yes
        selected = dict(resolutions or {})
        self.apply_calls.append(selected)
        if self.destination_root is not None:
            (self.destination_root / "applied.marker").write_text("applied", encoding="utf-8")
        return SimpleNamespace(applied=True, plan=_conflict_plan(resolved=selected["profile:stock"]))


class _FakeCliHost:
    def __init__(self, manager: _FakeMigrationManager, answers: list[str]) -> None:
        self.local_migration_manager = manager
        self.answers = iter(answers)

    def _input(self, _prompt: str) -> str:
        return next(self.answers)


def _candidate(path: Path) -> MigrationBundleCandidate:
    return MigrationBundleCandidate(
        path=path, generated_at="2026-09-16T09:20:00+00:00", suite_version="0.3.1-alpha",
        contract_version=2, content_classes=("settings", "modified_stock_profile"),
        content_summary="settings, 1 profile", size_bytes=2048, valid=True,
        warning_count=0, private_bundle=True, safe_status="Valid migration bundle.",
    )


def test_cli_discovery_conflict_cancel_and_restart_flow() -> None:
    with TemporaryDirectory() as tmp:
        manager = _FakeMigrationManager(_candidate(Path(tmp) / "bundle"))
        # Apply, discovered item, import renamed (choice 2), APPLY, then Back.
        host = _FakeCliHost(manager, ["4", "1", "2", "APPLY", "5"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            DiagnosticsCliAdapter(host).migration_support_menu()
        rendered = output.getvalue()
        assert "Available migration bundles" in rendered
        assert "Conflict: Stock.json" in rendered
        assert "Migration Applied Successfully" in rendered and "RESTART REQUIRED" in rendered
        assert manager.apply_calls == [{"profile:stock": "import_source_as_renamed"}]

        destination = Path(tmp) / "destination"
        destination.mkdir()
        before = _tree_snapshot(destination)
        cancelled = _FakeMigrationManager(_candidate(Path(tmp) / "bundle"), destination_root=destination)
        cancel_host = _FakeCliHost(cancelled, ["4", "1", "4", "5"])
        with contextlib.redirect_stdout(io.StringIO()):
            DiagnosticsCliAdapter(cancel_host).migration_support_menu()
        assert not cancelled.apply_calls
        assert _tree_snapshot(destination) == before


def test_cli_external_path_and_destructive_confirmation() -> None:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "external"
        destination = Path(tmp) / "destination"
        destination.mkdir()
        manager = _FakeMigrationManager(_candidate(Path(tmp) / "discovered"), destination_root=destination)
        host = _FakeCliHost(manager, ["2", str(path)])
        with contextlib.redirect_stdout(io.StringIO()):
            assert DiagnosticsCliAdapter(host)._choose_migration_bundle() == path

        before = _tree_snapshot(destination)
        cancelled = _FakeCliHost(manager, ["4", "1", "3", "cancel", "4", "5"])
        with contextlib.redirect_stdout(io.StringIO()):
            DiagnosticsCliAdapter(cancelled).migration_support_menu()
        assert not manager.apply_calls and _tree_snapshot(destination) == before

        # Apply, discovered item, replace (choice 3), resolution REPLACE,
        # final-plan REPLACE, APPLY, Back.
        host = _FakeCliHost(manager, ["4", "1", "3", "REPLACE", "REPLACE", "APPLY", "5"])
        with contextlib.redirect_stdout(io.StringIO()):
            DiagnosticsCliAdapter(host).migration_support_menu()
        assert manager.apply_calls[-1] == {"profile:stock": "replace_destination"}
        assert (destination / "applied.marker").read_text(encoding="utf-8") == "applied"


def test_direct_bundle_listing_is_nonmutating() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "checkout"
        root.mkdir()
        before = tuple(root.rglob("*"))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            assert local_migration_main(["--root", str(root), "migration-list"]) == 0
        assert "No migration bundles found" in output.getvalue()
        assert tuple(root.rglob("*")) == before


def run_migration_ux_checks() -> None:
    tests = (
        test_bundle_discovery_is_bounded_safe_and_sorted,
        test_structured_preview_and_error_projection,
        test_cli_discovery_conflict_cancel_and_restart_flow,
        test_cli_external_path_and_destructive_confirmation,
        test_direct_bundle_listing_is_nonmutating,
    )
    for test in tests:
        test()


if __name__ == "__main__":
    run_migration_ux_checks()
    print("migration v2 Wave B UX checks: PASS")
