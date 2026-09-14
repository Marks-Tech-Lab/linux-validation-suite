#!/usr/bin/env python3
"""Focused migration v2 A1 contract, safety, transaction, and adapter checks."""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Modules.lvs_core import APP_VERSION
from Modules.lvs_local_migration import LocalMigrationManager
from Modules.lvs_local_migration import main as local_migration_main
from Modules.lvs_migration_lock import MigrationLockUnavailable, state_lock
from Modules.lvs_migration_models import LogicalDestination, MigrationPlan, MigrationPlanAction
from Modules.lvs_migration_paths import MigrationPathOwnership
from Modules.lvs_migration_safe_fs import PinnedRoot
from Modules.lvs_migration_transaction import MigrationTransaction
from Modules.lvs_migration_v1_adapter import adapt_v1_payloads
from Modules.lvs_migration_v2 import (
    V2ContentPayload,
    build_a1_plan,
    destination_preconditions,
    preview_token,
    validate_v2_bundle,
    write_v2_bundle,
)
from Modules.lvs_run_launch import RunLaunchCoordinator


def _roots(root: Path) -> MigrationPathOwnership:
    for name in ("settings", "profiles", "results"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return MigrationPathOwnership.load_nonmutating(application_root=root)[0]


def _content(entry_id: str, name: str, payload: bytes, *, content_class: str = "settings", bundle_path: str | None = None, required: bool = False) -> V2ContentPayload:
    schemas = {
        "settings": "linux_validation_suite.migration.settings_payload",
        "setup_history": "linux_validation_suite.migration.run_setup_history_payload",
        "recovery_profile": "linux_validation_suite.migration.recovery_profile",
    }
    return V2ContentPayload(
        entry_id,
        content_class,
        name,
        bundle_path or f"payload/{entry_id}.json",
        "fixture",
        schemas.get(content_class, "example.unknown"),
        1,
        payload,
        required=required,
    )


def _bundle(root: Path, contents: tuple[V2ContentPayload, ...]) -> Path:
    path = root / "bundle"
    write_v2_bundle(
        path,
        suite_version=APP_VERSION,
        generated_at="2026-09-14T00:00:00-04:00",
        source={"platform": "linux", "architecture": "x86_64", "path_mode": "logical_roots", "logical_roots": {}},
        contents=contents,
        omitted_classes=({"content_class": "results", "reason": "NOT_SUPPORTED_BY_CORE_V2"},),
    )
    return path


def _error_codes(bundle: Path) -> set[str]:
    _, errors = validate_v2_bundle(bundle)
    return {item.error_code for item in errors}


def _manual_plan(bundle, ownership, destinations: list[tuple[str, str, str]], *, operation: str = "create_file") -> MigrationPlan:
    actions = []
    for entry_id, role, relative in destinations:
        actions.append(
            MigrationPlanAction(
                entry_id,
                "settings",
                entry_id,
                LogicalDestination(role, relative),
                "create",
                "FIXTURE_OPERATION",
                transaction_operations=({"operation": operation, "entry_id": entry_id},),
            )
        )
    return MigrationPlan(True, 2, "fixture", tuple(actions), apply_ready=True)


def _transaction_fixture(root: Path):
    ownership = _roots(root / "destination")
    contents = tuple(_content(f"entry-{index}", f"item-{index}", f'{{"value": {index}}}\n'.encode()) for index in range(1, 4))
    bundle_path = _bundle(root / "source", contents)
    bundle, errors = validate_v2_bundle(bundle_path)
    assert bundle is not None and not errors
    plan = _manual_plan(bundle, ownership, [(f"entry-{index}", "settings", f"item-{index}.json") for index in range(1, 4)])
    return ownership, bundle, plan


def test_manifest_and_inventory() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary)
        bundle = _bundle(root, (_content("settings/global", "global_settings", b"{}\n"),))
        validated, errors = validate_v2_bundle(bundle)
        assert validated is not None and not errors
        assert validated.manifest["contract_version"] == 2
        assert validated.manifest["private_bundle"] is True
        assert validated.manifest["safe_to_share_publicly"] is False

        manifest_path = bundle / "migration_manifest.json"
        original = json.loads(manifest_path.read_text())
        cases = []
        duplicate_id = json.loads(json.dumps(original)); duplicate_id["content"].append(dict(duplicate_id["content"][0])); cases.append((duplicate_id, "DUPLICATE_ENTRY_ID"))
        duplicate_path = json.loads(json.dumps(original)); extra = dict(duplicate_path["content"][0]); extra["entry_id"] = "other"; duplicate_path["content"].append(extra); cases.append((duplicate_path, "DUPLICATE_BUNDLE_PATH"))
        traversal = json.loads(json.dumps(original)); traversal["content"][0]["bundle_path"] = "../escape"; cases.append((traversal, "PAYLOAD_PATH_INVALID"))
        absolute = json.loads(json.dumps(original)); absolute["content"][0]["bundle_path"] = "/tmp/escape"; cases.append((absolute, "PAYLOAD_PATH_INVALID"))
        bad_schema = json.loads(json.dumps(original)); bad_schema["content"][0]["schema_version"] = 99; cases.append((bad_schema, "SCHEMA_VERSION_UNSUPPORTED"))
        for index, (manifest, code) in enumerate(cases):
            case = root / f"case-{index}"
            case.mkdir()
            payload = case / "payload/settings"
            payload.mkdir(parents=True)
            (payload / "global.json").write_bytes(b"{}\n")
            # Preserve the original payload path where needed.
            original_payload = bundle / original["content"][0]["bundle_path"]
            destination = case / original["content"][0]["bundle_path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(original_payload.read_bytes())
            (case / "migration_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            assert code in _error_codes(case), (code, _error_codes(case))


def test_unknown_classes_and_bundle_entries() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary)
        optional = _bundle(root / "optional", (_content("optional", "future", b"x", content_class="future_class"),))
        validated, errors = validate_v2_bundle(optional)
        assert validated is not None and not errors
        assert {item.error_code for item in validated.warnings} == {"CONTENT_CLASS_UNSUPPORTED"}
        required = _bundle(root / "required", (_content("required", "future", b"x", content_class="future_class", required=True),))
        assert "CONTENT_CLASS_UNSUPPORTED" in _error_codes(required)
        (optional / "extra.bin").write_bytes(b"private")
        assert "UNLISTED_PAYLOAD" in _error_codes(optional)


def test_hash_size_privacy_and_malformed_manifest() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary)
        for name, mutate, expected in (
            ("hash", lambda manifest: manifest["content"][0].update({"sha256": "0" * 64}), "PAYLOAD_HASH_MISMATCH"),
            ("size", lambda manifest: manifest["content"][0].update({"size_bytes": 999}), "PAYLOAD_SIZE_MISMATCH"),
            ("privacy", lambda manifest: manifest.update({"safe_to_share_publicly": True}), "PRIVACY_MARKER_INVALID"),
        ):
            bundle = _bundle(root / name, (_content("settings/global", "global", b"{}\n"),))
            manifest_path = bundle / "migration_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            mutate(manifest)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            assert expected in _error_codes(bundle)
        malformed = _bundle(root / "malformed", (_content("settings/global", "global", b"{}\n"),))
        (malformed / "migration_manifest.json").write_text("{private", encoding="utf-8")
        assert "MANIFEST_UNREADABLE" in _error_codes(malformed)


def test_bundle_payload_and_destination_symlinks() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary)
        real = _bundle(root / "real", (_content("settings/global", "global", b"{}\n"),))
        link = root / "bundle-link"; link.symlink_to(real, target_is_directory=True)
        assert "BUNDLE_UNSAFE" in _error_codes(link)
        payload = real / "payload/settings/global.json"
        saved = payload.read_bytes(); payload.unlink(); target = root / "payload-target"; target.write_bytes(saved); payload.symlink_to(target)
        assert "PAYLOAD_MISSING_OR_UNSAFE" in _error_codes(real) or "BUNDLE_ENTRY_UNSAFE" in _error_codes(real)

        destination = root / "destination"; ownership = _roots(destination)
        outside = root / "outside"; outside.mkdir()
        (destination / "settings/parent").symlink_to(outside, target_is_directory=True)
        with _assert_raises(OSError):
            with PinnedRoot(destination / "settings") as pinned:
                pinned.open_exclusive("parent/escape.json")


class _assert_raises:
    def __init__(self, kind): self.kind = kind
    def __enter__(self): return self
    def __exit__(self, exc_type, _exc, _tb):
        assert exc_type is not None and issubclass(exc_type, self.kind)
        return True


def test_configured_roots_and_nonmutating_loader() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary)
        external = root / "external"
        settings_file = root / "config/global.json"
        settings_file.parent.mkdir(parents=True)
        settings_file.write_text(json.dumps({"settings_dir": str(external / "settings"), "profiles_dir": str(external / "profiles"), "results_dir": str(external / "results")}), encoding="utf-8")
        ownership, _ = MigrationPathOwnership.load_nonmutating(application_root=root, settings_file=settings_file)
        assert ownership.settings_root == (external / "settings").resolve()
        assert ownership.profiles_root == (external / "profiles").resolve()
        assert ownership.results_root == (external / "results").resolve()
        relative_settings = root / "relative.json"
        relative_settings.write_text(
            json.dumps({"settings_dir": "custom/settings", "profiles_dir": "custom/profiles", "results_dir": "custom/results"}),
            encoding="utf-8",
        )
        relative_ownership, _ = MigrationPathOwnership.load_nonmutating(
            application_root=root,
            settings_file=relative_settings,
        )
        assert relative_ownership.settings_root == (root / "custom/settings").resolve()
        assert relative_ownership.profiles_root == (root / "custom/profiles").resolve()
        assert relative_ownership.results_root == (root / "custom/results").resolve()
        missing = root / "never-created/global_settings.json"
        before_tree = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
        MigrationPathOwnership.load_nonmutating(application_root=root, settings_file=missing)
        assert not missing.exists() and not missing.parent.exists()
        LocalMigrationManager(root, settings_path=missing)
        assert not missing.exists() and not missing.parent.exists()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = local_migration_main(
                ["--root", str(root), "--settings-file", str(missing), "restore", str(root / "missing-bundle")]
            )
        assert code == 1 and not missing.exists() and not missing.parent.exists()
        after_tree = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
        assert after_tree == before_tree

        bundle_path = _bundle(root / "source", (_content("settings/global", "global_settings", b"{}\n"),))
        manager = LocalMigrationManager(root, settings_path=settings_file)
        assert manager.preview_restore(bundle_path).valid
        result = manager.apply_restore(bundle_path, yes=True)
        assert result.applied
        assert (external / "settings/global_settings.json").is_file()


def test_transactions_and_reverse_rollback() -> None:
    for fail_sequence in (0, 1, 2, 3):
        with TemporaryDirectory(dir="/tmp") as temporary:
            root = Path(temporary)
            ownership, bundle, plan = _transaction_fixture(root)
            def failure(phase: str, sequence: int) -> None:
                if (fail_sequence == 0 and phase == "materialized") or (fail_sequence and phase == "applied" and sequence == fail_sequence):
                    raise OSError("synthetic transaction failure")
            result = MigrationTransaction(ownership=ownership, bundle=bundle, plan=plan, failure_hook=failure, revalidate_plan=False).execute()
            assert not result.applied and result.rollback_complete is True
            assert not any((ownership.settings_root / f"item-{index}.json").exists() for index in range(1, 4))
    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary)
        ownership, bundle, plan = _transaction_fixture(root)
        result = MigrationTransaction(ownership=ownership, bundle=bundle, plan=plan, revalidate_plan=False).execute()
        assert result.applied and result.valid
        assert [(ownership.settings_root / f"item-{index}.json").is_file() for index in range(1, 4)] == [True, True, True]
        assert all((ownership.settings_root / f"item-{index}.json").stat().st_mode & 0o077 == 0 for index in range(1, 4))

    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary); ownership = _roots(root / "destination")
        bundle_path = _bundle(root / "source", (_content("settings/global", "global_settings", b"{}\n"),))
        manager = LocalMigrationManager(root / "destination", settings_path=ownership.settings_file)
        preview = manager.preview_restore(bundle_path)
        assert preview.valid and preview.plan["apply_ready"] and preview.plan["requires_restart"]
        applied = manager.apply_restore(bundle_path, yes=True)
        assert applied.valid and applied.applied and applied.plan["requires_restart"]
        assert (ownership.settings_root / "global_settings.json").read_bytes() == b"{}\n"
        assert not (ownership.settings_root / ".lvs_migration_transactions").exists()


def test_replace_directory_and_rollback_failure() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary); ownership, bundle, _ = _transaction_fixture(root)
        target = ownership.settings_root / "replace.json"; target.write_text("old", encoding="utf-8")
        replace_plan = _manual_plan(bundle, ownership, [("entry-1", "settings", "replace.json")], operation="replace_file")
        result = MigrationTransaction(ownership=ownership, bundle=bundle, plan=replace_plan, revalidate_plan=False).execute()
        assert result.applied and json.loads(target.read_text())["value"] == 1
        directory_plan = _manual_plan(bundle, ownership, [("entry-1", "settings", "new-directory")], operation="create_directory")
        result = MigrationTransaction(ownership=ownership, bundle=bundle, plan=directory_plan, revalidate_plan=False).execute()
        assert result.applied and (ownership.settings_root / "new-directory").is_dir()

    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary); ownership, bundle, _ = _transaction_fixture(root)
        target = ownership.settings_root / "replace.json"; target.write_text("original", encoding="utf-8")
        replace_plan = _manual_plan(bundle, ownership, [("entry-1", "settings", "replace.json")], operation="replace_file")
        def fail_replace(phase: str, sequence: int) -> None:
            if phase == "applied" and sequence == 1:
                raise OSError("replace rollback fixture")
        result = MigrationTransaction(ownership=ownership, bundle=bundle, plan=replace_plan, failure_hook=fail_replace, revalidate_plan=False).execute()
        assert not result.applied and result.rollback_complete is True
        assert target.read_text(encoding="utf-8") == "original"

    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary); ownership, bundle, plan = _transaction_fixture(root)
        def break_rollback(phase: str, sequence: int) -> None:
            if phase == "applied" and sequence == 1:
                (ownership.settings_root / "item-1.json").write_text("external change", encoding="utf-8")
                raise OSError("synthetic failure after external drift")
        result = MigrationTransaction(ownership=ownership, bundle=bundle, plan=plan, failure_hook=break_rollback, revalidate_plan=False).execute()
        assert not result.applied and result.rollback_complete is False and result.recovery_required
        assert result.recovery_instructions
        assert (ownership.settings_root / ".lvs_migration_transactions" / result.transaction_id).is_dir()


def test_payload_mutation_and_parent_replacement() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary); ownership, bundle, plan = _transaction_fixture(root)
        payload_path = bundle.bundle_path / bundle.entries[0]["bundle_path"]
        original_read = os.read; mutated = False
        def changing_read(fd: int, size: int) -> bytes:
            nonlocal mutated
            data = original_read(fd, size)
            if data and not mutated:
                mutated = True
                payload_path.write_bytes(payload_path.read_bytes() + b"changed")
            return data
        with patch("Modules.lvs_migration_transaction.os.read", side_effect=changing_read):
            result = MigrationTransaction(ownership=ownership, bundle=bundle, plan=plan, revalidate_plan=False).execute()
        assert not result.applied and not any(ownership.settings_root.glob("item-*.json"))

    # Mutation of the original bundle after all payloads are pinned cannot alter apply.
    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary); ownership, bundle, plan = _transaction_fixture(root)
        source_payload = bundle.bundle_path / bundle.entries[0]["bundle_path"]
        def mutate_after_pin(phase: str, sequence: int) -> None:
            if phase == "materialized" and sequence == 0:
                source_payload.write_bytes(b"changed after pin")
        result = MigrationTransaction(
            ownership=ownership,
            bundle=bundle,
            plan=plan,
            failure_hook=mutate_after_pin,
            revalidate_plan=False,
        ).execute()
        assert result.applied
        assert json.loads((ownership.settings_root / "item-1.json").read_text())["value"] == 1

    # Corruption of a pinned apply input is detected after install and rolled back.
    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary); ownership, bundle, plan = _transaction_fixture(root)
        transaction: MigrationTransaction
        def corrupt_pinned(phase: str, sequence: int) -> None:
            if phase == "materialized" and sequence == 0:
                workspace = ownership.settings_root / transaction.workspace_paths["settings"]
                next(workspace.glob("payload-*.bin")).write_bytes(b"corrupted pinned payload")
        transaction = MigrationTransaction(
            ownership=ownership,
            bundle=bundle,
            plan=plan,
            failure_hook=corrupt_pinned,
            revalidate_plan=False,
        )
        result = transaction.execute()
        assert not result.applied and result.rollback_complete is True
        assert not any(ownership.settings_root.glob("item-*.json"))

    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary); ownership = _roots(root / "destination")
        bundle_path = _bundle(root / "source", (_content("settings/global", "global_settings", b"{}\n"),))
        manager = LocalMigrationManager(root / "destination", settings_path=ownership.settings_file)
        preview = manager.preview_restore(bundle_path); assert preview.valid
        original = ownership.settings_root.with_name("settings-original")
        ownership.settings_root.rename(original)
        outside = root / "outside"; outside.mkdir()
        ownership.settings_root.symlink_to(outside, target_is_directory=True)
        result = manager.apply_restore(bundle_path, yes=True)
        assert not result.applied and not (outside / "global_settings.json").exists()


def test_locking_active_run_and_drift() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        settings_root = Path(temporary); settings_root.mkdir(exist_ok=True)
        with state_lock(settings_root, exclusive=True):
            with _assert_raises(MigrationLockUnavailable):
                with state_lock(settings_root, exclusive=True):
                    pass
        with state_lock(settings_root, exclusive=False):
            with _assert_raises(MigrationLockUnavailable):
                with state_lock(settings_root, exclusive=True):
                    pass

        class Executor:
            def run_profile_direct(self, *_args, **_kwargs):
                with _assert_raises(MigrationLockUnavailable):
                    with state_lock(settings_root, exclusive=True):
                        pass
                return Path("completed")

        launcher = RunLaunchCoordinator(
            Executor(),
            state_lock_context=lambda: state_lock(settings_root, exclusive=False),
        )
        assert launcher.run_direct(Path("profile.json")) == Path("completed")

        class FailingExecutor:
            def run_profile_direct(self, *_args, **_kwargs):
                raise KeyboardInterrupt()

        failing_launcher = RunLaunchCoordinator(
            FailingExecutor(),
            state_lock_context=lambda: state_lock(settings_root, exclusive=False),
        )
        with _assert_raises(KeyboardInterrupt):
            failing_launcher.run_direct(Path("profile.json"))
        # File existence is inert; release on BaseException permits the next apply lock.
        assert (settings_root / ".lvs_state.lock").stat().st_mode & 0o777 == 0o600
        with state_lock(settings_root, exclusive=True):
            pass
        (settings_root / ".lvs_state.lock").write_text("stale pid metadata", encoding="utf-8")
        with state_lock(settings_root, exclusive=True):
            pass

        with state_lock(settings_root, exclusive=True):
            child = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "from pathlib import Path; "
                        "from Modules.lvs_migration_lock import state_lock, MigrationLockUnavailable; "
                        "\ntry:\n with state_lock(Path(r'" + str(settings_root) + "'), exclusive=True): pass\n"
                        "except MigrationLockUnavailable: raise SystemExit(23)\n"
                    ),
                ],
                cwd=ROOT,
                check=False,
            )
        assert child.returncode == 23

    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary); ownership = _roots(root / "destination")
        bundle_path = _bundle(root / "source", (_content("settings/global", "global_settings", b"{}\n"),))
        manager = LocalMigrationManager(root / "destination", settings_path=ownership.settings_file)
        assert manager.preview_restore(bundle_path).valid
        with state_lock(ownership.settings_root, exclusive=False):
            # Preview remains read-only and available while a validation lock is held.
            assert manager.preview_restore(bundle_path).valid
            assert manager.create_private_bundle(
                acknowledge_private_data=True,
                output_parent=ownership.results_root / "Migration_Bundles",
            ).bundle_dir.is_dir()
            blocked = manager.apply_restore(bundle_path, yes=True)
        assert not blocked.applied
        assert any(item.get("error_code") == "ACTIVE_RUN_OR_MIGRATION" for item in blocked.plan["errors"])
        assert manager.apply_restore(bundle_path, yes=True).applied

    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary); ownership = _roots(root / "destination")
        bundle_path = _bundle(root / "source", (_content("settings/global", "global_settings", b"{}\n"),))
        manager = LocalMigrationManager(root / "destination", settings_path=ownership.settings_file)
        preview = manager.preview_restore(bundle_path); assert preview.valid
        (ownership.settings_root / "global_settings.json").write_text("{}", encoding="utf-8")
        result = manager.apply_restore(bundle_path, yes=True)
        assert not result.applied
        assert any(item.get("error_code") == "DESTINATION_CHANGED_AFTER_PREVIEW" for item in result.plan["errors"])

        # Unrelated files are not part of the preview token.
        (ownership.settings_root / "unrelated.txt").write_text("unrelated", encoding="utf-8")
        refreshed = manager.preview_restore(bundle_path)
        token = refreshed.plan["preview_token"]
        (ownership.settings_root / "another-unrelated.txt").write_text("unrelated", encoding="utf-8")
        assert manager.preview_restore(bundle_path).plan["preview_token"] == token


def test_lock_error_and_journal_privacy() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary); ownership = _roots(root / "destination")
        bundle_path = _bundle(root / "source", (_content("settings/global", "global_settings", b'{"token":"never-print"}\n'),))
        manager = LocalMigrationManager(root / "destination", settings_path=ownership.settings_file)
        assert manager.preview_restore(bundle_path).valid
        with patch("Modules.lvs_local_migration.state_lock", side_effect=PermissionError("private/path/token")):
            result = manager.apply_restore(bundle_path, yes=True)
        assert not result.applied
        error = result.plan["errors"][-1]
        assert error["error_code"] == "MIGRATION_LOCK_UNAVAILABLE"
        assert error["phase"] == "lock" and error["manual_action_required"]
        assert "private/path/token" not in json.dumps(error)

    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary); ownership, bundle, plan = _transaction_fixture(root)
        def break_rollback(phase: str, sequence: int) -> None:
            if phase == "applied" and sequence == 1:
                (ownership.settings_root / "item-1.json").write_text("private history contents", encoding="utf-8")
                raise OSError("credential token")
        result = MigrationTransaction(ownership=ownership, bundle=bundle, plan=plan, failure_hook=break_rollback, revalidate_plan=False).execute()
        journal_path = ownership.settings_root / ".lvs_migration_transactions" / result.transaction_id / "journal.json"
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        encoded = json.dumps(journal)
        assert journal["transaction_id"] == result.transaction_id
        assert journal["phase"] == "recovery_required"
        assert journal["operations"][0]["rollback_state"] == "not_started"
        assert "private history contents" not in encoded and "credential token" not in encoded


def test_destination_precondition_matrix() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary); ownership = _roots(root)
        settings_target = ownership.settings_root / "global_settings.json"
        profile_target = ownership.profiles_root / "fixture.json"
        settings_target.write_bytes(b"settings-a")
        profile_target.write_bytes(b"profile-a")
        actions = [
            MigrationPlanAction("settings", "settings", "global", LogicalDestination("settings", settings_target.name), "create", "FIXTURE"),
            MigrationPlanAction("profile", "custom_profile", "fixture", LogicalDestination("profiles", profile_target.name), "create", "FIXTURE"),
        ]
        manifest = {"contract_version": 2, "content": []}
        initial = destination_preconditions(actions, ownership)
        initial_token = preview_token(manifest, initial)
        settings_target.write_bytes(b"settings-b")
        assert preview_token(manifest, destination_preconditions(actions, ownership)) != initial_token
        settings_target.write_bytes(b"settings-a")
        before_remove = preview_token(manifest, destination_preconditions(actions, ownership))
        profile_target.unlink()
        assert preview_token(manifest, destination_preconditions(actions, ownership)) != before_remove
        profile_target.write_bytes(b"profile-a")
        settled = preview_token(manifest, destination_preconditions(actions, ownership))
        (ownership.settings_root / "unrelated").write_bytes(b"ignored")
        assert preview_token(manifest, destination_preconditions(actions, ownership)) == settled


def test_v1_adapter_and_recovery_distinction() -> None:
    projected = adapt_v1_payloads(
        {
            "global_settings": {
                "sample_interval_seconds": 1,
                "environment_mode": "production",
                "results_dir": "/source/results",
                "runtime_environment": {"TOKEN": "secret"},
                "google_drive_shared_drive_id": "private-id",
                "privileged_helper_enabled": True,
            },
            "run_setup_history": [{"profile_name": "Example"}],
            "hardware_result_validation_state": {"entries": [{"path": "results/private"}]},
        }
    )
    assert projected.settings_values == {"sample_interval_seconds": 1}
    assert projected.policy_pending_fields == ("environment_mode",)
    assert projected.destination_local_fields == ("results_dir",)
    assert set(projected.relink_required) == {"google_drive_shared_drive_id", "runtime_environment"}
    assert projected.history_records == ({"profile_name": "Example"},)
    assert projected.recovery_only[0]["disposition"] == "quarantine"
    encoded = json.dumps(projected.recovery_only)
    assert "private-id" not in encoded and "secret" not in encoded and "results/private" not in encoded

    action = MigrationPlanAction("recovery", "recovery_profile", "broken.json", None, "quarantine", "RECOVERY_ONLY_CONTENT")
    assert action.disposition == "quarantine" and not action.transaction_operations

    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary); ownership = _roots(root / "destination")
        recovery_bundle = _bundle(
            root / "source",
            (_content("recovery/broken", "broken.json", b"private recovery", content_class="recovery_profile"),),
        )
        validated, errors = validate_v2_bundle(recovery_bundle)
        assert validated is not None and not errors
        recovery_plan = build_a1_plan(validated, ownership)
        assert recovery_plan.actions[0].disposition == "quarantine"
        assert not recovery_plan.actions[0].transaction_operations
        assert not (ownership.profiles_root / "broken.json").exists()

    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary)
        (root / "settings").mkdir()
        (root / "settings/global_settings.json").write_text(
            json.dumps({"sample_interval_seconds": 1, "results_dir": "/source/results"}),
            encoding="utf-8",
        )
        (root / "hardware_result_validation_state.json").write_text(
            json.dumps({"entries": [{"path": "results/source-only"}]}),
            encoding="utf-8",
        )
        manager = LocalMigrationManager(root)
        exported = manager.create_private_bundle(acknowledge_private_data=True)
        adapted = manager.adapt_v1_bundle(exported.bundle_dir)
        assert adapted.settings_values == {"sample_interval_seconds": 1}
        assert adapted.destination_local_fields == ("results_dir",)
        assert adapted.recovery_only and adapted.recovery_only[0]["disposition"] == "quarantine"


def run_local_migration_checks() -> None:
    tests = (
        test_manifest_and_inventory,
        test_unknown_classes_and_bundle_entries,
        test_hash_size_privacy_and_malformed_manifest,
        test_bundle_payload_and_destination_symlinks,
        test_configured_roots_and_nonmutating_loader,
        test_transactions_and_reverse_rollback,
        test_replace_directory_and_rollback_failure,
        test_payload_mutation_and_parent_replacement,
        test_locking_active_run_and_drift,
        test_lock_error_and_journal_privacy,
        test_destination_precondition_matrix,
        test_v1_adapter_and_recovery_distinction,
    )
    for test in tests:
        test()


if __name__ == "__main__":
    run_local_migration_checks()
    print("local migration v2 A1 checks: PASS")
