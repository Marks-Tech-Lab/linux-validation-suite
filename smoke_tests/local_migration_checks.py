#!/usr/bin/env python3
"""Focused migration v2 A1 contract, safety, transaction, and adapter checks."""

from __future__ import annotations

import contextlib
from dataclasses import asdict, fields
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
from Modules.lvs_migration_core_state import (
    DESTINATION_LOCAL, PORTABLE, SECRET_OR_RELINK, SESSION_ONLY,
    SETTINGS_FIELD_POLICY, _canonical_profile_payload, _deterministic_import_name,
    build_core_plan, merge_history, merge_settings,
    MigrationSourceChanged, semantic_profile_hash, settings_payload,
)
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
from Modules.lvs_settings import GlobalSettings


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
        preview = manager.preview_restore(bundle_path)
        assert preview.valid, preview.plan
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
    assert "environment_mode" in projected.destination_local_fields
    assert projected.policy_pending_fields == ()
    assert projected.destination_local_fields == ("environment_mode", "results_dir")
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
        exported = manager.create_v1_private_bundle(acknowledge_private_data=True)
        adapted = manager.adapt_v1_bundle(exported.bundle_dir)
        assert adapted.settings_values == {"sample_interval_seconds": 1}
        assert adapted.destination_local_fields == ("results_dir",)
        assert adapted.recovery_only and adapted.recovery_only[0]["disposition"] == "quarantine"


def _valid_profile(name: str, *, menu_group: str = "custom", duration: int = 60) -> dict:
    return {
        "profile_name": name,
        "profile_type": "validation_schedule",
        "menu_group": menu_group,
        "defaults": {"telemetry_interval_seconds": 2, "trim_start_seconds": 30, "trim_end_seconds": 30},
        "stages": [{
            "id": "stage_1", "name": "CPU", "display_label": "CPU", "duration_seconds": duration,
            "enabled": True, "modules": {"cpu": {"enabled": True}},
            "normalization": {"trim_start_seconds": 30, "trim_end_seconds": 30},
        }],
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _settings_for(root: Path, *, department: str = "Production", groups: list[dict] | None = None) -> GlobalSettings:
    settings = GlobalSettings()
    settings.settings_dir = str(root / "settings")
    settings.profiles_dir = str(root / "profiles")
    settings.results_dir = str(root / "results")
    settings.suite_department = department
    if groups is not None:
        settings.profile_menu_groups = groups
    return settings


def test_a2_settings_policy_and_merge_matrix() -> None:
    assert set(SETTINGS_FIELD_POLICY) == {item.name for item in fields(GlobalSettings)}
    assert SETTINGS_FIELD_POLICY["environment_mode"] == DESTINATION_LOCAL
    assert all(SETTINGS_FIELD_POLICY[key] == DESTINATION_LOCAL for key in ("results_dir", "profiles_dir", "settings_dir"))
    assert all(SETTINGS_FIELD_POLICY[key] == SECRET_OR_RELINK for key in (
        "runtime_environment", "google_drive_credentials_path"))
    assert SETTINGS_FIELD_POLICY["google_drive_shared_drive_id"] == PORTABLE
    assert all(SETTINGS_FIELD_POLICY[key] == SESSION_ONLY for key in (
        "privileged_helper_enabled", "privileged_helper_prompt_for_sudo"))
    assert SETTINGS_FIELD_POLICY["sample_interval_seconds"] == PORTABLE

    defaults = asdict(GlobalSettings())
    source = settings_payload({**defaults, "sample_interval_seconds": 1.0, "suite_department": "Source"})
    destination = {**defaults, "suite_department": "Destination", "future_bool": True, "future_number": 7,
        "future_string": "kept", "future_list": [1, "two"], "future_extension": {"kept": True}}
    output, actions, counts, conflicts = merge_settings(source, destination, settings_file=Path("settings/global_settings.json"))
    assert output["sample_interval_seconds"] == 1.0
    assert output["suite_department"] == "Destination"
    assert output["future_extension"] == {"kept": True}
    assert {key: output[key] for key in ("future_bool", "future_number", "future_string", "future_list")} == {
        "future_bool": True, "future_number": 7, "future_string": "kept", "future_list": [1, "two"]}
    assert "settings:suite_department" in conflicts and counts["conflict"] >= 1
    resolved, _, _, conflicts = merge_settings(source, destination,
        settings_file=Path("settings/global_settings.json"),
        resolutions={"settings:suite_department": "replace_destination"})
    assert resolved["suite_department"] == "Source" and not conflicts

    old_defaults = dict(defaults); old_defaults["sample_interval_seconds"] = 1.0
    old_source = settings_payload({**defaults, "sample_interval_seconds": 1.0}, source_defaults=old_defaults)
    new_destination = {**defaults, "sample_interval_seconds": defaults["sample_interval_seconds"]}
    cross, _, _, conflicts = merge_settings(old_source, new_destination, settings_file=Path("x"))
    assert cross["sample_interval_seconds"] == defaults["sample_interval_seconds"] and not conflicts
    customized_old = settings_payload({**defaults, "sample_interval_seconds": 2.0},
        source_defaults={**defaults, "sample_interval_seconds": 1.0})
    customized_new, _, _, conflicts = merge_settings(customized_old, new_destination, settings_file=Path("x"))
    assert customized_new["sample_interval_seconds"] == 2.0 and not conflicts
    destination_custom = {**defaults, "sample_interval_seconds": 3.0}
    _, _, _, conflicts = merge_settings(customized_old, destination_custom, settings_file=Path("x"))
    assert "settings:sample_interval_seconds" in conflicts
    unknown_era = settings_payload({**defaults, "sample_interval_seconds": 1.0}, source_defaults={})
    imported_unknown, _, _, conflicts = merge_settings(unknown_era, new_destination, settings_file=Path("x"))
    assert imported_unknown["sample_interval_seconds"] == 1.0 and not conflicts
    _, _, _, conflicts = merge_settings(unknown_era, destination_custom, settings_file=Path("x"))
    assert "settings:sample_interval_seconds" in conflicts
    absent = settings_payload(defaults); absent["present_fields"].remove("trim_end_seconds"); absent["portable_values"].pop("trim_end_seconds")
    preserved, _, _, _ = merge_settings(absent, {**defaults, "trim_end_seconds": 47}, settings_file=Path("x"))
    assert preserved["trim_end_seconds"] == 47
    menu_source = settings_payload({**defaults, "profile_menu_groups": [
        {"key": "custom", "label": "Source Custom"}]})
    _, menu_actions, _, menu_conflicts = merge_settings(menu_source, defaults, settings_file=Path("x"))
    assert "menu_group:custom" in menu_conflicts
    assert any(action.content_class == "profile_menu_metadata" and action.requires_user_choice for action in menu_actions)
    assert _deterministic_import_name("P.json", "abcdef0123456789", {"P (Imported abcdef01).json": "different"}) == "P (Imported abcdef012345).json"


def test_a2_fresh_install_and_external_roots() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        base = Path(temporary); source = base / "source"; destination = base / "destination"
        source_state = base / "source-state"; destination_state = base / "destination-state"
        source_settings = _settings_for(source, department="Migrated", groups=[
            *asdict(GlobalSettings())["profile_menu_groups"], {"key": "lab", "label": "Lab Profiles"},
        ])
        source_settings.settings_dir = str(source_state / "settings")
        source_settings.profiles_dir = str(source_state / "profiles")
        source_settings.results_dir = str(source_state / "results")
        source_settings.runtime_environment = {"PRIVATE_TOKEN": "must-not-migrate"}
        source_settings.environment_mode = "development"
        source_settings.google_drive_credentials_path = "/private/source/credentials.json"
        source_settings.google_drive_shared_drive_id = "private-drive-id"
        _write_json(source_state / "settings/global_settings.json", asdict(source_settings))
        _write_json(source_state / "profiles/My Lab Test.json", _valid_profile("My Lab Test", menu_group="lab"))
        _write_json(source_state / "settings/run_setup_history.json", [{
            "saved": "2026-09-15T10:00:00-04:00", "profile_name": "My Lab Test",
            "profile_file": "My Lab Test.json", "metadata": {"case_sku": "Fixture"}, "heatsoak_minutes": 0,
        }, "malformed"])
        bundle = LocalMigrationManager(source, settings=source_settings,
            settings_path=source_state / "settings/global_settings.json").create_private_bundle(
                acknowledge_private_data=True, output_parent=base / "bundles")
        manifest_text = bundle.manifest_path.read_text(encoding="utf-8")
        bundle_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore")
            for path in bundle.bundle_dir.rglob("*") if path.is_file())
        assert '"contract_version": 2' in manifest_text
        assert "must-not-migrate" not in bundle_text
        assert "private-drive-id" in bundle_text
        assert "/private/source" not in bundle_text and str(source) not in manifest_text
        assert any(item["content_class"] == "custom_profile" for item in bundle.manifest["content"])
        profile_entry = next(item for item in bundle.manifest["content"] if item["content_class"] == "custom_profile")
        assert profile_entry["provenance"] == "external_custom"
        settings_entry = next(item for item in bundle.manifest["content"] if item["content_class"] == "settings")
        semantic_settings = json.loads((bundle.bundle_dir / settings_entry["bundle_path"]).read_text())
        assert not ({"environment_mode", "results_dir", "profiles_dir", "settings_dir", "runtime_environment",
            "google_drive_credentials_path", "privileged_helper_enabled",
            "privileged_helper_prompt_for_sudo"} & set(semantic_settings["portable_values"]))

        destination_settings = _settings_for(destination)
        destination_settings.settings_dir = str(destination_state / "settings")
        destination_settings.profiles_dir = str(destination_state / "profiles")
        destination_settings.results_dir = str(destination_state / "results")
        destination_settings.environment_mode = "end_user"
        destination_raw = asdict(destination_settings); destination_raw["future_extension"] = "preserved"
        destination_raw.update({"future_bool": False, "future_number": 11, "future_string": "local",
            "future_list": ["a"], "future_nested": {"local": [1, 2]}})
        _write_json(destination_state / "settings/global_settings.json", destination_raw)
        (destination_state / "profiles").mkdir(parents=True); (destination_state / "results").mkdir()
        manager = LocalMigrationManager(destination, settings=destination_settings,
            settings_path=destination_state / "settings/global_settings.json")
        preview = manager.preview_restore(bundle.bundle_dir)
        assert preview.valid and preview.plan["apply_ready"], preview.plan
        assert preview.plan["summary"]["pristine_destination"]
        result = manager.apply_restore(bundle.bundle_dir, yes=True)
        assert result.valid and result.applied and result.plan["requires_restart"], result.plan
        restored_settings = json.loads((destination_state / "settings/global_settings.json").read_text())
        assert restored_settings["suite_department"] == "Migrated"
        assert restored_settings["environment_mode"] == "end_user"
        assert restored_settings["profiles_dir"] == str(destination_state / "profiles")
        assert restored_settings["future_extension"] == "preserved"
        assert {key: restored_settings[key] for key in (
            "future_bool", "future_number", "future_string", "future_list", "future_nested")
        } == {"future_bool": False, "future_number": 11, "future_string": "local",
            "future_list": ["a"], "future_nested": {"local": [1, 2]}}
        assert restored_settings["runtime_environment"] == {}
        assert any(group["key"] == "lab" and group["label"] == "Lab Profiles"
            for group in restored_settings["profile_menu_groups"])
        assert (destination_state / "profiles/My Lab Test.json").is_file()
        history = json.loads((destination_state / "settings/run_setup_history.json").read_text())
        assert history[0]["profile_file"] == "My Lab Test.json"
        assert not list(destination_state.rglob(".lvs_migration_transactions/*"))


def test_a2_profile_identity_rename_conflict_and_reimport() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        base = Path(temporary); source = base / "source"; destination = base / "destination"
        source_settings = _settings_for(source)
        _write_json(source / "settings/global_settings.json", asdict(source_settings))
        source_profile = _valid_profile("Collision", duration=60)
        _write_json(source / "profiles/Collision.json", source_profile)
        bundle = LocalMigrationManager(source, settings=source_settings,
            settings_path=source / "settings/global_settings.json").create_private_bundle(
                acknowledge_private_data=True, output_parent=base / "bundles")
        destination_settings = _settings_for(destination)
        _write_json(destination / "settings/global_settings.json", asdict(destination_settings))
        _write_json(destination / "profiles/Collision.json", _valid_profile("Collision", duration=120))
        (destination / "results").mkdir()
        manager = LocalMigrationManager(destination, settings=destination_settings,
            settings_path=destination / "settings/global_settings.json")
        preview = manager.preview_restore(bundle.bundle_dir)
        renamed = next(action for action in preview.plan["actions"] if action["disposition"] == "import_renamed")
        assert "(Imported " in renamed["destination"]["relative_path"]
        first = manager.apply_restore(bundle.bundle_dir, yes=True); assert first.applied
        imported = destination / "profiles" / renamed["destination"]["relative_path"]
        assert imported.is_file()
        second_preview = manager.preview_restore(bundle.bundle_dir)
        assert any(action["disposition"] == "skip_identical" and action["logical_item"] == "Collision.json"
            for action in second_preview.plan["actions"])
        assert len(list((destination / "profiles").glob("Collision (Imported *).json"))) == 1
        formatting_variant = json.loads(imported.read_text())
        assert semantic_profile_hash(formatting_variant) == semantic_profile_hash(json.loads(json.dumps(formatting_variant)))
        canonical = _canonical_profile_payload(imported, destination_settings.profile_menu_groups)
        mutations = (
            ("profile_name", lambda item: item.update(profile_name="Different")),
            ("profile_type", lambda item: item.update(profile_type="different_type")),
            ("menu_group", lambda item: item.update(menu_group="standard")),
            ("run policy", lambda item: item.update(require_all_stages_runnable=True)),
            ("defaults", lambda item: item["defaults"].update(trim_start_seconds=99)),
            ("stage identity", lambda item: item["stages"][0].update(id="different")),
            ("stage duration", lambda item: item["stages"][0].update(duration_seconds=999)),
            ("stage enablement", lambda item: item["stages"][0].update(enabled=False)),
            ("module behavior", lambda item: item["stages"][0]["modules"]["cpu"].update(enabled=False)),
            ("normalization", lambda item: item["stages"][0]["normalization"].update(trim_end_seconds=99)),
        )
        canonical_hash = semantic_profile_hash(canonical)
        for label, mutate in mutations:
            changed = json.loads(json.dumps(canonical)); mutate(changed)
            assert semantic_profile_hash(changed) != canonical_hash, label

    with TemporaryDirectory(dir="/tmp") as temporary:
        base = Path(temporary); source = base / "source"; destination = base / "destination"
        source_settings = _settings_for(source); destination_settings = _settings_for(destination)
        _write_json(source / "settings/global_settings.json", asdict(source_settings))
        _write_json(source / "profiles/Stock.json", _valid_profile("Stock", duration=60))
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "add", "profiles/Stock.json"], check=True)
        subprocess.run(["git", "-C", str(source), "-c", "user.name=LVS", "-c", "user.email=lvs@example.invalid",
            "commit", "-qm", "stock"], check=True)
        unchanged_bundle = LocalMigrationManager(source, settings=source_settings,
            settings_path=source / "settings/global_settings.json").create_private_bundle(
                acknowledge_private_data=True, output_parent=base / "unchanged-bundles")
        assert not any(item["content_class"] in {"custom_profile", "modified_stock_profile"}
            for item in unchanged_bundle.manifest["content"])
        assert unchanged_bundle.manifest["export_summary"]["profiles"]["stock_unchanged_omitted"] == 1
        _write_json(source / "profiles/Stock.json", _valid_profile("Stock", duration=90))
        bundle = LocalMigrationManager(source, settings=source_settings,
            settings_path=source / "settings/global_settings.json").create_private_bundle(
                acknowledge_private_data=True, output_parent=base / "bundles")
        assert any(item["content_class"] == "modified_stock_profile" for item in bundle.manifest["content"])
        _write_json(destination / "settings/global_settings.json", asdict(destination_settings))
        _write_json(destination / "profiles/Stock.json", _valid_profile("Stock", duration=60)); (destination / "results").mkdir()
        manager = LocalMigrationManager(destination, settings=destination_settings,
            settings_path=destination / "settings/global_settings.json")
        preview = manager.preview_restore(bundle.bundle_dir)
        conflict = next(action for action in preview.plan["actions"] if action["reason_code"] == "MODIFIED_STOCK_COLLISION")
        assert not preview.plan["apply_ready"] and conflict["requires_user_choice"]
        assert conflict["action_id"] in preview.summary_text and "--resolve" in preview.summary_text
        resolved = manager.preview_restore(bundle.bundle_dir, resolutions={conflict["action_id"]: "import_source_as_renamed"})
        assert resolved.plan["apply_ready"]
        cli_output = io.StringIO()
        with contextlib.redirect_stdout(cli_output):
            cli_code = local_migration_main([
                "--root", str(destination), "--settings-file", str(destination / "settings/global_settings.json"),
                "restore", str(bundle.bundle_dir), "--resolve",
                f"{conflict['action_id']}=import_source_as_renamed",
            ])
        assert cli_code == 0 and "Apply ready: yes" in cli_output.getvalue()
        applied = manager.apply_restore(bundle.bundle_dir, yes=True,
            resolutions={conflict["action_id"]: "import_source_as_renamed"})
        assert applied.applied and len(list((destination / "profiles").glob("Stock (Imported *).json"))) == 1
        imported_path = next((destination / "profiles").glob("Stock (Imported *).json"))
        imported_path.unlink()
        replace_preview = manager.preview_restore(bundle.bundle_dir,
            resolutions={conflict["action_id"]: "replace_destination"})
        replace_action = next(action for action in replace_preview.plan["actions"] if action["logical_item"] == "Stock.json"
            and action["content_class"] == "modified_stock_profile")
        assert replace_action["destructive"] and replace_action["transaction_operations"][0]["operation"] == "replace_file"
        ownership = MigrationPathOwnership.from_settings(application_root=destination,
            settings_file=destination / "settings/global_settings.json", settings=destination_settings)
        validated_bundle, errors = validate_v2_bundle(bundle.bundle_dir)
        assert validated_bundle is not None and not errors
        replace_core = build_core_plan(validated_bundle, ownership,
            resolutions={conflict["action_id"]: "replace_destination"}, destination_settings=destination_settings)
        original_stock = (destination / "profiles/Stock.json").read_bytes()
        profile_sequence = next(index for index, action in enumerate(replace_core.plan.actions, start=1)
            if action.action_id == conflict["action_id"])
        def fail_after_replace(phase: str, sequence: int) -> None:
            if phase == "applied" and sequence == profile_sequence:
                raise OSError("fixture after profile replacement")
        rolled_back = MigrationTransaction(ownership=ownership, bundle=validated_bundle, plan=replace_core.plan,
            materialized_payloads=replace_core.materialized_payloads,
            plan_builder=lambda: build_core_plan(validated_bundle, ownership,
                resolutions={conflict["action_id"]: "replace_destination"},
                destination_settings=destination_settings).plan,
            failure_hook=fail_after_replace).execute()
        assert not rolled_back.applied and rolled_back.rollback_complete
        assert (destination / "profiles/Stock.json").read_bytes() == original_stock
        replaced = manager.apply_restore(bundle.bundle_dir, yes=True,
            resolutions={conflict["action_id"]: "replace_destination"})
        assert replaced.applied
        assert json.loads((destination / "profiles/Stock.json").read_text())["stages"][0]["duration_seconds"] == 90

        unknown = manager.preview_restore(bundle.bundle_dir, resolutions={"missing-action": "keep_destination"})
        assert not unknown.valid and any(error["error_code"] == "RESOLUTION_ACTION_UNKNOWN"
            for error in unknown.plan["errors"])
        invalid = manager.preview_restore(bundle.bundle_dir,
            resolutions={conflict["action_id"]: "not-a-resolution"})
        assert not invalid.valid and any(error["error_code"] == "RESOLUTION_NOT_ALLOWED"
            for error in invalid.plan["errors"])
        with contextlib.redirect_stderr(io.StringIO()) as duplicate_error:
            duplicate_code = local_migration_main([
                "--root", str(destination), "--settings-file", str(destination / "settings/global_settings.json"),
                "restore", str(bundle.bundle_dir), "--resolve", f"{conflict['action_id']}=keep_destination",
                "--resolve", f"{conflict['action_id']}=replace_destination",
            ])
        assert duplicate_code == 2 and "specified more than once" in duplicate_error.getvalue()


def test_a2_profile_provenance_recovery_and_legacy_hydration() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary); settings = _settings_for(root)
        _write_json(root / "settings/global_settings.json", asdict(settings))
        _write_json(root / "profiles/Unknown.json", _valid_profile("Unknown"))
        _write_json(root / "profiles/Broken.json", {"profile_name": "Broken", "stages": "invalid"})
        (root / "profiles/Unsafe.json").symlink_to(root / "profiles/Unknown.json")
        legacy = _valid_profile("Legacy")
        legacy["segment_label_source"] = "Legacy.labels"
        legacy["stages"][0].pop("display_label")
        _write_json(root / "profiles/Legacy.json", legacy)
        (root / "profiles/Legacy.labels").write_text("Hydrated Label\n", encoding="utf-8")
        missing_legacy = _valid_profile("Missing Legacy")
        missing_legacy["segment_label_source"] = "missing.labels"
        missing_legacy["stages"][0].pop("display_label")
        _write_json(root / "profiles/Missing Legacy.json", missing_legacy)
        bundle = LocalMigrationManager(root, settings=settings,
            settings_path=root / "settings/global_settings.json").create_private_bundle(
                acknowledge_private_data=True, output_parent=root / "bundles")
        entries = bundle.manifest["content"]
        unknown = next(item for item in entries if item.get("source_filename") == "Unknown.json")
        assert unknown["provenance"] == "unknown_provenance"
        assert any(item["content_class"] == "recovery_profile" and item["logical_name"] == "Broken.json" for item in entries)
        assert any(item["content_class"] == "recovery_profile" and item["logical_name"] == "Missing Legacy.json" for item in entries)
        legacy_entry = next(item for item in entries if item.get("source_filename") == "Legacy.json")
        hydrated = json.loads((bundle.bundle_dir / legacy_entry["bundle_path"]).read_text())
        assert hydrated["stages"][0]["display_label"] == "Hydrated Label"
        assert bundle.manifest["export_summary"]["profiles"]["unsafe_or_unreadable"] == 1

    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary); settings = _settings_for(root)
        _write_json(root / "settings/global_settings.json", asdict(settings))
        _write_json(root / "profiles/Repo Custom.json", _valid_profile("Repo Custom"))
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        bundle = LocalMigrationManager(root, settings=settings,
            settings_path=root / "settings/global_settings.json").create_private_bundle(
                acknowledge_private_data=True, output_parent=root / "bundles")
        entry = next(item for item in bundle.manifest["content"] if item.get("source_filename") == "Repo Custom.json")
        assert entry["provenance"] == "repository_custom"


def test_a2_export_source_mutation_detection() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary); settings = _settings_for(root)
        settings_path = root / "settings/global_settings.json"
        profile_path = root / "profiles/Changing.json"
        _write_json(settings_path, asdict(settings)); _write_json(profile_path, _valid_profile("Changing"))
        manager = LocalMigrationManager(root, settings=settings, settings_path=settings_path)
        from Modules import lvs_migration_core_state as core_state
        real_read = core_state._read_stable_regular
        profile_reads = 0
        def changing_read(path: Path) -> bytes | None:
            nonlocal profile_reads
            value = real_read(path)
            if path == profile_path:
                profile_reads += 1
                if profile_reads == 1:
                    _write_json(profile_path, _valid_profile("Changing", duration=120))
            return value
        with patch.object(core_state, "_read_stable_regular", side_effect=changing_read):
            with _assert_raises(MigrationSourceChanged):
                manager.create_private_bundle(acknowledge_private_data=True, output_parent=root / "bundles")


def test_a2_history_merge_and_transaction_rollback() -> None:
    destination = [{"saved": "2026-09-15T12:00:00-04:00", "profile_name": "A", "profile_file": "A.json",
        "metadata": {"case_sku": "one"}, "heatsoak_minutes": 0}]
    source = [dict(destination[0]), {"saved": "invalid", "profile_name": "B", "profile_file": "B.json",
        "metadata": {}, "heatsoak_minutes": 1}]
    merged, counts = merge_history(source, destination, {"B.json": "B (Imported hash).json"}, set())
    assert len(merged) == 2 and counts["duplicate"] == 1
    assert any(item["profile_file"] == "B (Imported hash).json" for item in merged)
    unresolved, counts = merge_history(source, destination, {}, {"B.json"})
    assert counts["unresolved_profile_reference"] == 1 and all(item["profile_file"] != "B.json" for item in unresolved)
    many = [{"saved": f"2026-09-{day:02d}T12:00:00-04:00", "profile_name": str(day),
        "profile_file": f"{day}.json", "metadata": {}, "heatsoak_minutes": 0} for day in range(1, 12)]
    capped, counts = merge_history(many, [], {}, set())
    assert len(capped) == 8 and counts["dropped_by_retention_limit"] == 3

    with TemporaryDirectory(dir="/tmp") as temporary:
        base = Path(temporary); source_root = base / "source"; destination_root = base / "destination"
        source_settings = _settings_for(source_root, department="Source")
        destination_settings = _settings_for(destination_root)
        _write_json(source_root / "settings/global_settings.json", asdict(source_settings))
        _write_json(source_root / "profiles/A.json", _valid_profile("A"))
        _write_json(source_root / "settings/run_setup_history.json", [{
            "saved": "2026-09-15T13:00:00-04:00", "profile_name": "A", "profile_file": "A.json",
            "metadata": {"case_sku": "two"}, "heatsoak_minutes": 0,
        }])
        bundle_result = LocalMigrationManager(source_root, settings=source_settings,
            settings_path=source_root / "settings/global_settings.json").create_private_bundle(
                acknowledge_private_data=True, output_parent=base / "bundles")
        _write_json(destination_root / "settings/global_settings.json", asdict(destination_settings))
        _write_json(destination_root / "settings/run_setup_history.json", destination)
        (destination_root / "profiles").mkdir(); (destination_root / "results").mkdir()
        ownership = MigrationPathOwnership.from_settings(application_root=destination_root,
            settings_file=destination_root / "settings/global_settings.json", settings=destination_settings)
        bundle, errors = validate_v2_bundle(bundle_result.bundle_dir); assert bundle is not None and not errors
        core = build_core_plan(bundle, ownership, destination_settings=destination_settings)
        original_settings = (destination_root / "settings/global_settings.json").read_bytes()
        original_history = (destination_root / "settings/run_setup_history.json").read_bytes()
        for fail_index in (1, 2, 3):
            applied_count = 0
            def fail_after_selected_operation(phase: str, _sequence: int) -> None:
                nonlocal applied_count
                if phase == "applied":
                    applied_count += 1
                    if applied_count == fail_index:
                        raise OSError("fixture")
            core = build_core_plan(bundle, ownership, destination_settings=destination_settings)
            result = MigrationTransaction(ownership=ownership, bundle=bundle, plan=core.plan,
                materialized_payloads=core.materialized_payloads,
                plan_builder=lambda: build_core_plan(bundle, ownership, destination_settings=destination_settings).plan,
                failure_hook=fail_after_selected_operation).execute()
            assert not result.applied and result.rollback_complete, result
            assert (destination_root / "settings/global_settings.json").read_bytes() == original_settings
            assert (destination_root / "settings/run_setup_history.json").read_bytes() == original_history
            assert not (destination_root / "profiles/A.json").exists()


def test_a2_v1_adapter_settings_and_history() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        base = Path(temporary); source = base / "source"; destination = base / "destination"
        (source / "settings").mkdir(parents=True)
        _write_json(source / "settings/global_settings.json", {
            "suite_department": "Legacy Source", "environment_mode": "production",
            "results_dir": "/legacy/results", "profiles_dir": "/legacy/profiles",
            "settings_dir": "/legacy/settings", "runtime_environment": {"TOKEN": "secret"},
        })
        _write_json(source / "settings/run_setup_history.json", [{
            "saved": "2026-09-15T08:00:00-04:00", "profile_name": "Legacy",
            "profile_file": "Legacy.json", "metadata": {}, "heatsoak_minutes": 0,
        }])
        _write_json(source / "hardware_result_validation_state.json", {"entries": [{"path": "results/private"}]})
        legacy = LocalMigrationManager(source).create_v1_private_bundle(acknowledge_private_data=True,
            output_parent=base / "legacy-bundles")
        destination_settings = _settings_for(destination); destination_settings.environment_mode = "end_user"
        _write_json(destination / "settings/global_settings.json", asdict(destination_settings))
        (destination / "profiles").mkdir(); (destination / "results").mkdir()
        manager = LocalMigrationManager(destination, settings=destination_settings,
            settings_path=destination / "settings/global_settings.json")
        preview = manager.preview_restore(legacy.bundle_dir)
        assert preview.valid and preview.plan["adapted_to_core_semantics"] and preview.plan["apply_ready"]
        assert any(warning["error_code"] == "V1_HARDWARE_STATE_IGNORED" for warning in preview.plan["warnings"])
        assert any(action["content_class"] == "hardware_validation_state" and action["disposition"] == "quarantine"
            for action in preview.plan["actions"])
        applied = manager.apply_restore(legacy.bundle_dir, yes=True); assert applied.applied
        settings = json.loads((destination / "settings/global_settings.json").read_text())
        assert settings["suite_department"] == "Legacy Source" and settings["environment_mode"] == "end_user"
        assert settings["results_dir"] == str(destination / "results")
        assert settings["runtime_environment"] == {}
        assert preview.plan["summary"]["history"]["unresolved_profile_reference"] == 1
        assert not (destination / "settings/run_setup_history.json").exists()
        assert not (destination / "hardware_result_validation_state.json").exists()


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
        test_a2_settings_policy_and_merge_matrix,
        test_a2_fresh_install_and_external_roots,
        test_a2_profile_identity_rename_conflict_and_reimport,
        test_a2_profile_provenance_recovery_and_legacy_hydration,
        test_a2_export_source_mutation_detection,
        test_a2_history_merge_and_transaction_rollback,
        test_a2_v1_adapter_settings_and_history,
    )
    for test in tests:
        test()


if __name__ == "__main__":
    run_local_migration_checks()
    print("local migration v2 A1+A2 checks: PASS")
