#!/usr/bin/env python3
"""Focused secret-bearing upload credential migration checks (no network access)."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Modules.lvs_local_migration import LocalMigrationManager
from Modules.lvs_migration_core_state import collect_core_export
from Modules.lvs_migration_credentials import (
    DESTINATION_CREDENTIAL_RELATIVE,
    UPLOAD_CREDENTIAL_MAX_BYTES,
    _stable_bounded_read,
    inspect_upload_credentials,
)
from Modules.lvs_migration_paths import MigrationPathOwnership
from Modules.lvs_migration_ux import (
    bundle_candidate_detail, export_preview_text, migration_plan_text, resolution_label,
)
from Modules.lvs_migration_v2 import V2ContentPayload, write_v2_bundle
from Modules.lvs_settings import GlobalSettings
from smoke_tests.local_migration_checks import _settings_for, _valid_profile, _write_json


PRIVATE_MARKER = "fixture-private-key-material-never-render"
DRIVE_MARKER = "fixture-shared-drive-private-id"
CLIENT_EMAIL_MARKER = "fixture@migration-fixture.iam.gserviceaccount.com"


def _credential_bytes(*, client_id: str = "123456789") -> bytes:
    return (json.dumps({
        "type": "service_account",
        "project_id": "migration-fixture",
        "private_key_id": "fixture-key-id",
        "private_key": f"-----BEGIN PRIVATE KEY-----\n{PRIVATE_MARKER}\n-----END PRIVATE KEY-----\n",
        "client_email": "fixture@migration-fixture.iam.gserviceaccount.com",
        "client_id": client_id,
        "token_uri": "https://oauth2.googleapis.com/token",
    }, sort_keys=True) + "\n").encode("utf-8")


def _source(root: Path, state: Path, *, credential: bytes | None = None) -> tuple[GlobalSettings, Path]:
    settings = _settings_for(root, department="Migrated Department")
    settings.settings_dir = str(state / "settings")
    settings.profiles_dir = str(state / "profiles")
    settings.results_dir = str(state / "results")
    settings.environment_mode = "development"
    settings.google_drive_shared_drive_id = DRIVE_MARKER
    credential_path = state / "external-auth/service-account.json"
    settings.google_drive_credentials_path = str(credential_path)
    _write_json(state / "settings/global_settings.json", asdict(settings))
    if credential is not None:
        credential_path.parent.mkdir(parents=True, exist_ok=True)
        credential_path.write_bytes(credential)
        credential_path.chmod(0o600)
    return settings, credential_path


def test_export_secret_inventory_and_failures() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        base = Path(temporary); root = base / "source"; state = base / "source-state"
        settings, credential_path = _source(root, state, credential=_credential_bytes())
        manager = LocalMigrationManager(root, settings=settings, settings_path=state / "settings/global_settings.json")
        preview = manager.preview_private_bundle_export()
        assert preview["summary"]["upload"]["configured"]
        assert preview["summary"]["upload"]["credentials_available"]
        assert preview["summary"]["upload"]["credentials"] == "excluded"
        assert not preview["summary"]["upload"]["complete_for_current_configuration"]

        excluded = manager.create_private_bundle(
            acknowledge_private_data=True, output_parent=base / "excluded",
            include_upload_credentials=False,
        )
        assert excluded.manifest["contains_secrets"] is False
        assert all(item["content_class"] != "upload_credentials" for item in excluded.manifest["content"])
        assert "INCOMPLETE" in excluded.summary_text

        included = manager.create_private_bundle(
            acknowledge_private_data=True, output_parent=base / "included",
            include_upload_credentials=True,
        )
        secret_entry = next(item for item in included.manifest["content"] if item["content_class"] == "upload_credentials")
        assert included.manifest["contains_secrets"] is True
        assert secret_entry["privacy_class"] == "SECRET_CONTENT"
        assert secret_entry["portability"] == "portable_secret"
        assert "private_key" not in json.dumps(included.manifest)
        assert PRIVATE_MARKER not in json.dumps(included.manifest)
        assert DRIVE_MARKER not in json.dumps(included.manifest)
        assert "SECRET AUTHENTICATION MATERIAL" in included.summary_text
        assert stat.S_IMODE((included.bundle_dir / secret_entry["bundle_path"]).stat().st_mode) == 0o600
        exported = collect_core_export(manager.path_ownership, settings, include_upload_credentials=True)
        assert PRIVATE_MARKER not in repr(exported)

        for size in (UPLOAD_CREDENTIAL_MAX_BYTES - 1, UPLOAD_CREDENTIAL_MAX_BYTES):
            boundary = base / f"boundary-{size}"
            boundary.write_bytes(b"x" * size)
            assert len(_stable_bounded_read(boundary)) == size
        over_boundary = base / "boundary-over"
        over_boundary.write_bytes(b"x" * (UPLOAD_CREDENTIAL_MAX_BYTES + 1))
        try:
            _stable_bounded_read(over_boundary)
        except OverflowError:
            pass
        else:
            raise AssertionError("credential size limit + 1 was accepted")

        symlink_path = credential_path.with_name("credential-link.json")
        symlink_path.symlink_to(credential_path)
        symlink_settings = asdict(settings); symlink_settings["google_drive_credentials_path"] = str(symlink_path)
        linked = inspect_upload_credentials(manager.path_ownership, symlink_settings)
        assert linked.available and linked.payload == _credential_bytes()
        with patch("Modules.lvs_migration_credentials._stable_bounded_read", side_effect=PermissionError("denied")):
            unreadable = inspect_upload_credentials(manager.path_ownership, asdict(settings))
        assert unreadable.error is not None and unreadable.error.error_code == "CREDENTIAL_SOURCE_UNREADABLE"

        credential_path.write_text("not-json", encoding="utf-8")
        invalid = manager.preview_private_bundle_export()
        assert invalid["summary"]["upload"]["credentials"] == "unavailable"
        assert invalid["warnings"][0]["error_code"] == "CREDENTIAL_INVALID"
        assert (included.bundle_dir / secret_entry["bundle_path"]).read_bytes() == _credential_bytes()
        credential_path.unlink()
        missing = manager.preview_private_bundle_export()
        assert missing["warnings"][0]["error_code"] == "CREDENTIAL_SOURCE_MISSING"

        credential_path.parent.mkdir(parents=True, exist_ok=True)
        credential_path.write_bytes(b"x" * (UPLOAD_CREDENTIAL_MAX_BYTES + 1))
        too_large = manager.preview_private_bundle_export()
        assert too_large["warnings"][0]["error_code"] == "CREDENTIAL_TOO_LARGE"
        with patch("Modules.lvs_migration_credentials._stable_bounded_read", side_effect=RuntimeError("changed")):
            changed = inspect_upload_credentials(manager.path_ownership, asdict(settings))
        assert changed.error is not None and changed.error.error_code == "CREDENTIAL_CHANGED_DURING_EXPORT"


def test_complete_migration_and_permissions() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        base = Path(temporary); source = base / "source"; source_state = base / "source-state"
        destination = base / "destination"; destination_state = base / "destination-state"
        source_settings, _ = _source(source, source_state, credential=_credential_bytes())
        _write_json(source_state / "profiles/Upload Profile.json", _valid_profile("Upload Profile"))
        _write_json(source_state / "settings/run_setup_history.json", [{
            "saved": "2026-09-18T10:00:00-04:00", "profile_name": "Upload Profile",
            "profile_file": "Upload Profile.json", "metadata": {}, "heatsoak_minutes": 0,
        }])
        bundle = LocalMigrationManager(
            source, settings=source_settings, settings_path=source_state / "settings/global_settings.json",
        ).create_private_bundle(
            acknowledge_private_data=True, output_parent=base / "bundles",
            include_upload_credentials=True,
        )

        destination_settings = _settings_for(destination)
        destination.mkdir(parents=True)
        destination_settings.settings_dir = str(destination_state / "settings")
        destination_settings.profiles_dir = str(destination_state / "profiles")
        destination_settings.results_dir = str(destination_state / "results")
        destination_settings.environment_mode = "production"
        raw = asdict(destination_settings); raw["future_extension"] = {"preserved": True}
        _write_json(destination_state / "settings/global_settings.json", raw)
        destination_state.joinpath("profiles").mkdir(parents=True)
        destination_state.joinpath("results").mkdir(parents=True)
        manager = LocalMigrationManager(
            destination, settings=destination_settings,
            settings_path=destination_state / "settings/global_settings.json",
        )
        discovered = LocalMigrationManager(
            source, settings=source_settings, settings_path=source_state / "settings/global_settings.json",
        )
        discovered.path_ownership = discovered.path_ownership.__class__(
            **{**discovered.path_ownership.__dict__, "bundle_root": base / "bundles"}
        )
        candidates = discovered.discover_bundles()
        assert candidates and candidates[0].contains_secrets
        assert "CONTAINS SECRET AUTHENTICATION MATERIAL" in bundle_candidate_detail(candidates[0])

        preview = manager.preview_restore(bundle.bundle_dir)
        assert preview.valid and preview.plan["apply_ready"], preview.plan
        assert preview.plan["summary"]["upload"]["ready_after_restart"]
        rendered = migration_plan_text(preview.plan, include_details=True)
        assert PRIVATE_MARKER not in rendered and DRIVE_MARKER not in rendered
        result = manager.apply_restore(bundle.bundle_dir, yes=True)
        assert result.applied and result.plan["requires_restart"]
        restored = json.loads((destination_state / "settings/global_settings.json").read_text())
        installed = destination_state / "settings" / DESTINATION_CREDENTIAL_RELATIVE
        assert installed.read_bytes() == _credential_bytes()
        assert restored["google_drive_credentials_path"] == str(installed)
        assert restored["google_drive_shared_drive_id"] == DRIVE_MARKER
        assert restored["environment_mode"] == "production"
        assert restored["future_extension"] == {"preserved": True}
        assert (destination_state / "profiles/Upload Profile.json").is_file()
        history = json.loads((destination_state / "settings/run_setup_history.json").read_text())
        assert history[0]["profile_file"] == "Upload Profile.json"
        assert stat.S_IMODE(installed.stat().st_mode) == 0o600
        assert stat.S_IMODE(installed.parent.stat().st_mode) == 0o700
        assert result.plan["summary"]["upload"]["credentials"] == "source_installed"
        assert result.plan["summary"]["upload"]["ready_after_restart"]


def test_destination_conflict_and_transaction_rollback() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        base = Path(temporary); source = base / "source"; source_state = base / "source-state"
        destination = base / "destination"; destination_state = base / "destination-state"
        source_settings, _ = _source(source, source_state, credential=_credential_bytes())
        bundle = LocalMigrationManager(source, settings=source_settings,
            settings_path=source_state / "settings/global_settings.json").create_private_bundle(
                acknowledge_private_data=True, output_parent=base / "bundles",
                include_upload_credentials=True,
            )
        destination_settings = _settings_for(destination)
        destination.mkdir(parents=True)
        destination_settings.settings_dir = str(destination_state / "settings")
        destination_settings.profiles_dir = str(destination_state / "profiles")
        destination_settings.results_dir = str(destination_state / "results")
        canonical = destination_state / "settings" / DESTINATION_CREDENTIAL_RELATIVE
        canonical.parent.mkdir(parents=True); canonical.parent.chmod(0o700)
        canonical.write_bytes(_credential_bytes(client_id="different")); canonical.chmod(0o600)
        destination_settings.google_drive_credentials_path = str(canonical)
        destination_settings.google_drive_shared_drive_id = ""
        _write_json(destination_state / "settings/global_settings.json", asdict(destination_settings))
        destination_state.joinpath("profiles").mkdir(parents=True)
        destination_state.joinpath("results").mkdir(parents=True)
        manager = LocalMigrationManager(destination, settings=destination_settings,
            settings_path=destination_state / "settings/global_settings.json")
        preview = manager.preview_restore(bundle.bundle_dir)
        conflict = next(item for item in preview.plan["actions"] if item["content_class"] == "upload_credentials")
        assert conflict["requires_user_choice"] and conflict["destructive"]
        assert tuple(conflict["allowed_resolutions"]) == ("keep_destination", "replace_destination")
        assert not preview.plan["apply_ready"]

        keep = manager.preview_restore(bundle.bundle_dir, resolutions={conflict["action_id"]: "keep_destination"})
        assert keep.plan["apply_ready"]
        kept = manager.apply_restore(bundle.bundle_dir, yes=True,
            resolutions={conflict["action_id"]: "keep_destination"})
        assert kept.applied and canonical.read_bytes() == _credential_bytes(client_id="different")

        replace_preview = manager.preview_restore(bundle.bundle_dir,
            resolutions={conflict["action_id"]: "replace_destination"})
        assert replace_preview.plan["apply_ready"]
        original_settings = (destination_state / "settings/global_settings.json").read_bytes()
        original_credential = canonical.read_bytes()
        bundle_valid, errors = __import__("Modules.lvs_migration_v2", fromlist=["validate_v2_bundle"]).validate_v2_bundle(bundle.bundle_dir)
        assert bundle_valid is not None and not errors
        core = __import__("Modules.lvs_migration_core_state", fromlist=["build_core_plan"]).build_core_plan(
            bundle_valid, manager.path_ownership,
            resolutions={conflict["action_id"]: "replace_destination"},
            destination_settings=manager.settings_context,
        )
        from Modules.lvs_migration_transaction import MigrationTransaction
        transaction: MigrationTransaction
        def fail_after_credential(phase: str, sequence: int) -> None:
            if phase != "applied" or sequence < 2:
                return
            workspace = canonical.parent.parent / transaction.workspace_paths["settings"]
            backups = list(workspace.glob("backup-*.bin"))
            assert backups and all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in backups)
            raise OSError("fixture failure")

        transaction = MigrationTransaction(
            ownership=manager.path_ownership, bundle=bundle_valid, plan=core.plan,
            materialized_payloads=core.materialized_payloads, revalidate_plan=False,
            failure_hook=fail_after_credential,
        )
        failed = transaction.execute()
        assert not failed.applied and failed.rollback_complete is True
        assert canonical.read_bytes() == original_credential
        assert (destination_state / "settings/global_settings.json").read_bytes() == original_settings


def test_identical_and_orphan_destination_credentials() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        base = Path(temporary); source = base / "source"; source_state = base / "source-state"
        source_settings, _ = _source(source, source_state, credential=_credential_bytes())
        bundle = LocalMigrationManager(source, settings=source_settings,
            settings_path=source_state / "settings/global_settings.json").create_private_bundle(
                acknowledge_private_data=True, output_parent=base / "bundles",
                include_upload_credentials=True,
            )

        def destination_manager(label: str, payload: bytes, *, configured: bool) -> tuple[LocalMigrationManager, Path, Path]:
            destination = base / label; state = base / f"{label}-state"; destination.mkdir()
            settings = _settings_for(destination)
            settings.settings_dir = str(state / "settings")
            settings.profiles_dir = str(state / "profiles")
            settings.results_dir = str(state / "results")
            canonical = state / "settings" / DESTINATION_CREDENTIAL_RELATIVE
            canonical.parent.mkdir(parents=True); canonical.parent.chmod(0o700)
            canonical.write_bytes(payload); canonical.chmod(0o600)
            settings.google_drive_credentials_path = str(canonical) if configured else ""
            _write_json(state / "settings/global_settings.json", asdict(settings))
            state.joinpath("profiles").mkdir(); state.joinpath("results").mkdir()
            return LocalMigrationManager(destination, settings=settings,
                settings_path=state / "settings/global_settings.json"), canonical, state

        identical_manager, identical_path, identical_state = destination_manager(
            "identical", _credential_bytes(), configured=True,
        )
        identical_preview = identical_manager.preview_restore(bundle.bundle_dir)
        credential_action = next(item for item in identical_preview.plan["actions"]
            if item["content_class"] == "upload_credentials")
        assert credential_action["disposition"] == "skip_identical"
        assert not credential_action["destructive"] and not credential_action["transaction_operations"]
        assert identical_preview.plan["summary"]["upload"]["ready_after_restart"]
        identical_result = identical_manager.apply_restore(bundle.bundle_dir, yes=True)
        assert identical_result.applied and identical_path.read_bytes() == _credential_bytes()
        restored_identical = json.loads((identical_state / "settings/global_settings.json").read_text())
        assert restored_identical["google_drive_credentials_path"] == str(identical_path)

        orphan_manager, orphan_path, orphan_state = destination_manager(
            "orphan", _credential_bytes(client_id="orphan"), configured=False,
        )
        orphan_preview = orphan_manager.preview_restore(bundle.bundle_dir)
        orphan_action = next(item for item in orphan_preview.plan["actions"]
            if item["content_class"] == "upload_credentials")
        assert orphan_action["requires_user_choice"] and not orphan_preview.plan["apply_ready"]
        orphan_resolutions = {orphan_action["action_id"]: "keep_destination"}
        kept_preview = orphan_manager.preview_restore(bundle.bundle_dir, resolutions=orphan_resolutions)
        assert kept_preview.plan["apply_ready"] and kept_preview.plan["summary"]["upload"]["ready_after_restart"]
        kept = orphan_manager.apply_restore(bundle.bundle_dir, yes=True, resolutions=orphan_resolutions)
        assert kept.applied and orphan_path.read_bytes() == _credential_bytes(client_id="orphan")
        orphan_settings = json.loads((orphan_state / "settings/global_settings.json").read_text())
        assert orphan_settings["google_drive_credentials_path"] == str(orphan_path)


def test_public_support_redaction_and_old_bundle_compatibility() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary)
        credential = root / "settings/secrets/google-credentials.json"
        credential.parent.mkdir(parents=True); credential.write_bytes(_credential_bytes())
        settings = asdict(GlobalSettings())
        settings["google_drive_credentials_path"] = str(credential)
        settings["google_drive_shared_drive_id"] = DRIVE_MARKER
        settings["runtime_environment"] = {"SECRET_ENV_FIXTURE": "environment-secret-marker"}
        _write_json(root / "settings/global_settings.json", settings)
        support = LocalMigrationManager(root).export_public_support(root / "support")
        encoded = json.dumps(support.payload)
        support_files = "\n".join(path.read_text(encoding="utf-8", errors="replace")
            for path in support.report_dir.rglob("*") if path.is_file())
        combined = encoded + support_files
        for marker in (
            PRIVATE_MARKER, DRIVE_MARKER, CLIENT_EMAIL_MARKER, "fixture-key-id",
            str(credential), "environment-secret-marker", "https://oauth2.googleapis.com/token",
        ):
            assert marker not in combined
        assert support.payload["google_drive"]["shared_drive_id"] == "redacted"

        manager = LocalMigrationManager(root)
        old_bundle = manager.create_private_bundle(
            acknowledge_private_data=True, output_parent=root / "bundles",
            include_upload_credentials=False,
        )
        assert old_bundle.manifest["contains_secrets"] is False
        manifest_path = old_bundle.manifest_path
        old_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        old_manifest.pop("contains_secrets")
        manifest_path.write_text(json.dumps(old_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        preview = manager.preview_restore(old_bundle.bundle_dir)
        assert preview.valid
        assert preview.plan["summary"]["upload"]["credentials"] == "not_present_in_bundle"

        fresh_root = root / "fresh"; fresh_root.mkdir()
        fresh_state = root / "fresh-state"; fresh_settings = _settings_for(fresh_root)
        fresh_settings.settings_dir = str(fresh_state / "settings")
        fresh_settings.profiles_dir = str(fresh_state / "profiles")
        fresh_settings.results_dir = str(fresh_state / "results")
        _write_json(fresh_state / "settings/global_settings.json", asdict(fresh_settings))
        fresh_state.joinpath("profiles").mkdir(); fresh_state.joinpath("results").mkdir()
        fresh_manager = LocalMigrationManager(fresh_root, settings=fresh_settings,
            settings_path=fresh_state / "settings/global_settings.json")
        fresh_preview = fresh_manager.preview_restore(old_bundle.bundle_dir)
        assert fresh_preview.valid
        assert not fresh_preview.plan["summary"]["upload"]["ready_after_restart"]
        assert fresh_preview.plan["summary"]["upload"]["incomplete_reason"] == "credentials_not_present_in_bundle"


def test_destination_symlink_is_rejected() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        base = Path(temporary); source = base / "source"; source_state = base / "source-state"
        destination = base / "destination"; destination_state = base / "destination-state"
        source_settings, _ = _source(source, source_state, credential=_credential_bytes())
        bundle = LocalMigrationManager(source, settings=source_settings,
            settings_path=source_state / "settings/global_settings.json").create_private_bundle(
                acknowledge_private_data=True, output_parent=base / "bundles",
                include_upload_credentials=True,
            )
        destination.mkdir(); destination_settings = _settings_for(destination)
        destination_settings.settings_dir = str(destination_state / "settings")
        destination_settings.profiles_dir = str(destination_state / "profiles")
        destination_settings.results_dir = str(destination_state / "results")
        canonical = destination_state / "settings" / DESTINATION_CREDENTIAL_RELATIVE
        canonical.parent.mkdir(parents=True); canonical.parent.chmod(0o700)
        outside = base / "outside-secret"; outside.write_bytes(b"outside")
        canonical.symlink_to(outside)
        destination_settings.google_drive_credentials_path = str(canonical)
        _write_json(destination_state / "settings/global_settings.json", asdict(destination_settings))
        destination_state.joinpath("profiles").mkdir(); destination_state.joinpath("results").mkdir()
        manager = LocalMigrationManager(destination, settings=destination_settings,
            settings_path=destination_state / "settings/global_settings.json")
        preview = manager.preview_restore(bundle.bundle_dir)
        assert not preview.valid
        assert outside.read_bytes() == b"outside"


def test_cli_and_frontend_secret_ux() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        base = Path(temporary); root = base / "source"; state = base / "state"
        settings, _ = _source(root, state, credential=_credential_bytes())
        root.mkdir(parents=True)
        command = [
            sys.executable, "-m", "Modules.lvs_local_migration", "--root", str(root),
            "--settings-file", str(state / "settings/global_settings.json"), "migration-export",
            "--acknowledge-private-data", "--output-dir", str(base / "cli-bundles"),
        ]
        unspecified = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        assert unspecified.returncode == 2 and "--include-upload-credentials" in unspecified.stderr
        included = subprocess.run(
            [*command, "--include-upload-credentials"], cwd=ROOT,
            text=True, capture_output=True, check=False,
        )
        assert included.returncode == 0
        assert "SECRET AUTHENTICATION MATERIAL" in included.stdout
        assert PRIVATE_MARKER not in included.stdout and DRIVE_MARKER not in included.stdout

        summary = collect_core_export(
            MigrationPathOwnership.from_settings(
                application_root=root, settings_file=state / "settings/global_settings.json", settings=settings,
            ), settings, include_upload_credentials=True,
        ).summary
        rendered = export_preview_text(summary, approximate_size=100)
        assert "Credentials: included" in rendered and DRIVE_MARKER not in rendered
        action = {"content_class": "upload_credentials"}
        assert resolution_label(action, "keep_destination") == "Keep destination credentials"
        assert resolution_label(action, "replace_destination") == "Use source credentials"


def test_failed_secret_export_is_removed() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        bundle_path = Path(temporary) / "Private_Migration_Bundle_v2_failed"
        content = V2ContentPayload(
            "upload-credentials", "upload_credentials", "google_drive_upload",
            "payload/secrets/google_drive_credentials.json", "upload_authentication",
            "linux_validation_suite.migration.google_service_account", 1,
            _credential_bytes(), privacy_class="SECRET_CONTENT", portability="portable_secret",
        )
        from Modules import lvs_migration_v2
        original_write = lvs_migration_v2._write_all
        calls = 0

        def fail_manifest(fd: int, payload: bytes) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("fixture manifest failure")
            original_write(fd, payload)

        with patch("Modules.lvs_migration_v2._write_all", side_effect=fail_manifest):
            try:
                write_v2_bundle(
                    bundle_path, suite_version="fixture", generated_at="2026-09-18T12:00:00-04:00",
                    source={"path_mode": "logical_roots"}, contents=(content,),
                )
            except OSError:
                pass
            else:
                raise AssertionError("injected secret export failure unexpectedly succeeded")
        assert not bundle_path.exists()


def run_migration_credentials_checks() -> None:
    tests = (
        test_export_secret_inventory_and_failures,
        test_complete_migration_and_permissions,
        test_destination_conflict_and_transaction_rollback,
        test_identical_and_orphan_destination_credentials,
        test_public_support_redaction_and_old_bundle_compatibility,
        test_destination_symlink_is_rejected,
        test_cli_and_frontend_secret_ux,
        test_failed_secret_export_is_removed,
    )
    for test in tests:
        test()
    print("migration v2 upload credential checks: PASS")


if __name__ == "__main__":
    run_migration_credentials_checks()
