#!/usr/bin/env python3
"""Private migration workspaces, payload pinning, apply, and rollback."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Callable
import uuid

from .lvs_migration_models import MigrationApplyResult, MigrationPlan, MigrationSafeError
from .lvs_migration_paths import MigrationPathOwnership
from .lvs_migration_safe_fs import FileIdentity, PinnedRoot, validate_relative_path
from .lvs_migration_v2 import ValidatedV2Bundle, build_a1_plan, preview_token


@dataclass
class JournalOperation:
    sequence: int
    action_id: str
    logical_target: str
    operation: str
    expected_before: str
    expected_after: str = ""
    backup_location: str = ""
    operation_complete: bool = False
    rollback_state: str = "not_started"


@dataclass
class InstalledOperation:
    root_role: str
    relative_path: str
    operation: str
    after_identity: FileIdentity | None = None
    backup_relative: str = ""


def _safe_error(code: str, phase: str, message: str, *, retryable: bool = False, manual: bool = False) -> MigrationSafeError:
    return MigrationSafeError(code, phase, message, retryable=retryable, manual_action_required=manual)


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("migration workspace write failed")
        view = view[written:]


class MigrationTransaction:
    """Executes an already validated A1 plan from pinned payload copies."""

    def __init__(
        self,
        *,
        ownership: MigrationPathOwnership,
        bundle: ValidatedV2Bundle,
        plan: MigrationPlan,
        failure_hook: Callable[[str, int], None] | None = None,
        revalidate_plan: bool = True,
        plan_builder: Callable[[], MigrationPlan] | None = None,
        materialized_payloads: dict[str, bytes] | None = None,
    ) -> None:
        self.ownership = ownership
        self.bundle = bundle
        self.plan = plan
        self.transaction_id = uuid.uuid4().hex
        self.failure_hook = failure_hook
        self.revalidate_plan = revalidate_plan
        self.plan_builder = plan_builder
        self.materialized_payloads = dict(materialized_payloads or {})
        self.roots: dict[str, PinnedRoot] = {}
        self.workspace_paths: dict[str, str] = {}
        self.journal: list[JournalOperation] = []
        self.installed: list[InstalledOperation] = []
        self.workspace_files: dict[str, set[str]] = {}

    def _root(self, role: str) -> PinnedRoot:
        if role not in self.roots:
            self.roots[role] = PinnedRoot(self.ownership.root_for_role(role), create=True)
        return self.roots[role]

    def _workspace(self, role: str) -> str:
        if role not in self.workspace_paths:
            relative = f".lvs_migration_transactions/{self.transaction_id}"
            root = self._root(role)
            role_path = self.ownership.root_for_role(role).resolve()
            for existing_role, existing_relative in self.workspace_paths.items():
                if self.ownership.root_for_role(existing_role).resolve() == role_path:
                    self.workspace_paths[role] = existing_relative
                    self.workspace_files[role] = self.workspace_files[existing_role]
                    return existing_relative
            root.ensure_private_dir(relative)
            self.workspace_paths[role] = relative
            self.workspace_files[role] = set()
        return self.workspace_paths[role]

    def _write_journal(self, phase: str) -> None:
        if not self.workspace_paths:
            return
        primary_role = sorted(self.workspace_paths)[0]
        root = self._root(primary_role)
        workspace = self.workspace_paths[primary_role]
        temporary = f"{workspace}/journal-{uuid.uuid4().hex}.tmp"
        journal_relative = f"{workspace}/journal.json"
        payload = {
            "transaction_id": self.transaction_id,
            "phase": phase,
            "operations": [asdict(item) for item in self.journal],
        }
        fd = root.open_exclusive(temporary)
        try:
            _write_all(fd, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        root.rename(temporary, journal_relative)
        self.workspace_files[primary_role].discard(temporary)
        self.workspace_files[primary_role].add(journal_relative)

    def _pin_payload(self, entry: dict[str, Any], role: str) -> tuple[str, str, int]:
        bundle_root = PinnedRoot(self.bundle.bundle_path)
        try:
            source_fd = bundle_root.open_read(str(entry["bundle_path"]))
            try:
                before = os.fstat(source_fd)
                if not stat.S_ISREG(before.st_mode):
                    raise OSError("payload is not regular")
                relative = f"{self._workspace(role)}/payload-{hashlib.sha256(str(entry['entry_id']).encode()).hexdigest()}.bin"
                target_fd = self._root(role).open_exclusive(relative)
                self.workspace_files[role].add(relative)
                digest = hashlib.sha256()
                size = 0
                try:
                    while True:
                        chunk = os.read(source_fd, 1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                        size += len(chunk)
                        _write_all(target_fd, chunk)
                    os.fsync(target_fd)
                finally:
                    os.close(target_fd)
                after = os.fstat(source_fd)
                stable = (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                ) == (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                )
                actual_hash = digest.hexdigest()
                if not stable:
                    raise OSError("payload changed while it was pinned")
                if size != int(entry["size_bytes"]) or actual_hash != str(entry["sha256"]):
                    raise OSError("pinned payload does not match manifest")
                return relative, actual_hash, size
            finally:
                os.close(source_fd)
        finally:
            bundle_root.close()

    def _pin_materialized(self, action_id: str, role: str, payload: bytes) -> tuple[str, str, int]:
        relative = f"{self._workspace(role)}/materialized-{hashlib.sha256(action_id.encode()).hexdigest()}.bin"
        target_fd = self._root(role).open_exclusive(relative)
        self.workspace_files[role].add(relative)
        try:
            _write_all(target_fd, payload)
            os.fsync(target_fd)
        finally:
            os.close(target_fd)
        return relative, hashlib.sha256(payload).hexdigest(), len(payload)

    def _cleanup(self) -> bool:
        complete = True
        cleaned: set[tuple[Path, str]] = set()
        for role, relative in list(self.workspace_paths.items()):
            workspace_key = (self.ownership.root_for_role(role).resolve(), relative)
            if workspace_key in cleaned:
                continue
            cleaned.add(workspace_key)
            root = self._root(role)
            for file_relative in sorted(self.workspace_files.get(role, set()), reverse=True):
                try:
                    identity = root.identity(file_relative)
                    if identity.exists:
                        root.remove_verified(file_relative, identity)
                except OSError:
                    complete = False
            try:
                root.remove_empty_dir(relative)
            except OSError:
                complete = False
            try:
                root.remove_empty_dir(".lvs_migration_transactions")
            except OSError:
                pass
        return complete

    def execute(self) -> MigrationApplyResult:
        if not self.plan.valid or not self.plan.apply_ready:
            return MigrationApplyResult(False, False, self.plan)
        entries = {str(item["entry_id"]): item for item in self.bundle.entries}
        pinned: dict[str, tuple[str, str, int]] = {}
        try:
            # Pin roots and payloads before any destination mutation.
            for action in self.plan.actions:
                if not action.transaction_operations or action.destination is None:
                    continue
                operation = str((action.transaction_operations or ({"operation": "create_file"},))[0].get("operation"))
                self._root(action.destination.root_role)
                if operation != "create_directory":
                    if action.action_id in self.materialized_payloads:
                        pinned[action.action_id] = self._pin_materialized(
                            action.action_id,
                            action.destination.root_role,
                            self.materialized_payloads[action.action_id],
                        )
                    else:
                        pinned[action.action_id] = self._pin_payload(entries[action.action_id], action.destination.root_role)
            if self.failure_hook:
                self.failure_hook("materialized", 0)

            current_plan = (
                self.plan_builder()
                if self.revalidate_plan and self.plan_builder is not None
                else build_a1_plan(self.bundle, self.ownership)
                if self.revalidate_plan
                else self.plan
            )
            if self.revalidate_plan and current_plan.preview_token != self.plan.preview_token:
                error_plan = MigrationPlan(
                    False,
                    2,
                    current_plan.preview_token,
                    current_plan.actions,
                    errors=(_safe_error("DESTINATION_CHANGED_AFTER_PREVIEW", "apply_precondition", "Destination state changed after preview. Create a new preview before applying.", retryable=True),),
                    warnings=current_plan.warnings,
                    requires_restart=True,
                    apply_ready=False,
                )
                self._cleanup()
                return MigrationApplyResult(False, False, error_plan, self.transaction_id)

            for sequence, action in enumerate(self.plan.actions, start=1):
                if not action.transaction_operations or action.destination is None:
                    continue
                root = self._root(action.destination.root_role)
                before = root.identity(action.destination.relative_path)
                operation = str((action.transaction_operations or ({"operation": "create_file"},))[0].get("operation"))
                if operation in {"create_file", "create_directory"} and before.exists:
                    raise FileExistsError("destination appeared during apply")
                if operation == "replace_file" and not before.exists:
                    raise FileNotFoundError("replacement destination disappeared during apply")
                journal = JournalOperation(
                    sequence,
                    action.action_id,
                    f"{action.destination.root_role}:{action.destination.relative_path}",
                    operation,
                    before.token(),
                )
                self.journal.append(journal)
                self._write_journal("applying")
                backup_relative = ""
                if operation == "create_directory":
                    root.ensure_private_dir(action.destination.relative_path)
                    installed = InstalledOperation(action.destination.root_role, action.destination.relative_path, operation)
                    after = None
                else:
                    pinned_relative, expected_hash, _ = pinned[action.action_id]
                    if operation == "replace_file":
                        backup_relative = f"{self._workspace(action.destination.root_role)}/backup-{sequence}.bin"
                        root.rename(action.destination.relative_path, backup_relative)
                        self.workspace_files[action.destination.root_role].add(backup_relative)
                        journal.backup_location = backup_relative
                        installed = InstalledOperation(
                            action.destination.root_role,
                            action.destination.relative_path,
                            operation,
                            None,
                            backup_relative,
                        )
                        self.installed.append(installed)
                    root.link_exclusive(pinned_relative, action.destination.relative_path)
                    after = root.identity(action.destination.relative_path)
                    if operation == "replace_file":
                        installed.after_identity = after
                    else:
                        installed = InstalledOperation(
                            action.destination.root_role,
                            action.destination.relative_path,
                            operation,
                            after,
                            backup_relative,
                        )
                        self.installed.append(installed)
                    if after.sha256 != expected_hash:
                        raise OSError("installed destination failed verification")
                    journal.expected_after = after.token()
                journal.operation_complete = True
                if operation == "create_directory":
                    self.installed.append(installed)
                self._write_journal("applying")
                if self.failure_hook:
                    self.failure_hook("applied", sequence)

            self._write_journal("verified")
            cleanup_complete = self._cleanup()
            if not cleanup_complete:
                cleanup_plan = MigrationPlan(
                    False,
                    2,
                    self.plan.preview_token,
                    self.plan.actions,
                    errors=(_safe_error("TRANSACTION_CLEANUP_FAILED", "cleanup", "Migration content was applied, but private transaction cleanup requires review.", manual=True),),
                    warnings=self.plan.warnings,
                    requires_restart=True,
                    apply_ready=False,
                )
                return MigrationApplyResult(
                    False,
                    True,
                    cleanup_plan,
                    self.transaction_id,
                    rollback_complete=None,
                    recovery_required=True,
                    recovery_instructions=("Review the retained private transaction workspace and journal.",),
                )
            return MigrationApplyResult(True, True, self.plan, self.transaction_id, rollback_complete=None, recovery_required=False)
        except BaseException:
            rollback_complete = True
            recovery: list[str] = []
            for installed in reversed(self.installed):
                try:
                    root = self._root(installed.root_role)
                    if installed.operation == "create_directory":
                        root.remove_empty_dir(installed.relative_path)
                    elif installed.after_identity is not None:
                        root.remove_verified(installed.relative_path, installed.after_identity)
                    if installed.operation == "replace_file" and installed.backup_relative:
                        root.rename(installed.backup_relative, installed.relative_path)
                        self.workspace_files[installed.root_role].discard(installed.backup_relative)
                    for item in self.journal:
                        if item.logical_target == f"{installed.root_role}:{installed.relative_path}":
                            item.rollback_state = "restored" if installed.operation == "replace_file" else "removed"
                except OSError:
                    rollback_complete = False
                    recovery.append(
                        f"Review transaction-owned target {installed.root_role}:{installed.relative_path} using the retained journal."
                    )
                    break
            if rollback_complete:
                self._write_journal("rolled_back")
                if not self._cleanup():
                    rollback_complete = False
                    recovery.append("Review the retained private transaction workspace and journal.")
            else:
                self._write_journal("recovery_required")
            error_plan = MigrationPlan(
                False,
                2,
                self.plan.preview_token,
                self.plan.actions,
                errors=(_safe_error("TRANSACTION_APPLY_FAILED", "apply", "Migration apply failed; transaction rollback was attempted.", manual=not rollback_complete),),
                warnings=self.plan.warnings,
                requires_restart=True,
                apply_ready=False,
            )
            return MigrationApplyResult(
                False,
                False,
                error_plan,
                self.transaction_id,
                rollback_complete=rollback_complete,
                recovery_required=not rollback_complete,
                recovery_instructions=tuple(recovery),
            )
        finally:
            for root in self.roots.values():
                root.close()
