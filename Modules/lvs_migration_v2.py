#!/usr/bin/env python3
"""Migration contract v2 validation and A1 create-only restore planning."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

from .lvs_migration_models import (
    LogicalDestination,
    MIGRATION_BUNDLE_KIND,
    MIGRATION_CONTRACT_ID,
    MIGRATION_CONTRACT_VERSION_V2,
    MigrationPlan,
    MigrationPlanAction,
    MigrationSafeError,
)
from .lvs_migration_paths import MigrationPathOwnership
from .lvs_migration_safe_fs import PinnedRoot, validate_relative_path


MANIFEST_NAME = "migration_manifest.json"
REQUIRED_MANIFEST_FIELDS = frozenset(
    {
        "contract_id",
        "contract_version",
        "kind",
        "suite_version",
        "generated_at",
        "private_bundle",
        "safe_to_share_publicly",
        "source",
        "content",
        "omitted_classes",
    }
)

SUPPORTED_CONTENT_SCHEMAS: dict[str, dict[str, set[int]]] = {
    "settings": {"linux_validation_suite.migration.settings_payload": {1}},
    "setup_history": {"linux_validation_suite.migration.run_setup_history_payload": {1}},
    "custom_profile": {"linux_validation_suite.validation_profile": {1}},
    "modified_stock_profile": {"linux_validation_suite.validation_profile": {1}},
    "profile_menu_metadata": {"linux_validation_suite.migration.profile_menu_metadata": {1}},
    "recovery_profile": {"linux_validation_suite.migration.recovery_profile": {1}},
}

ENTRY_REQUIRED_FIELDS = frozenset(
    {
        "entry_id",
        "content_class",
        "logical_name",
        "bundle_path",
        "source_role",
        "schema_id",
        "schema_version",
        "sha256",
        "size_bytes",
        "private",
        "privacy_class",
        "portability",
        "merge_policy_hint",
        "required",
    }
)


@dataclass(frozen=True)
class ValidatedV2Bundle:
    bundle_path: Path
    manifest: dict[str, Any]
    entries: tuple[dict[str, Any], ...]
    warnings: tuple[MigrationSafeError, ...]


@dataclass(frozen=True)
class V2ContentPayload:
    entry_id: str
    content_class: str
    logical_name: str
    bundle_path: str
    source_role: str
    schema_id: str
    schema_version: int
    payload: bytes
    privacy_class: str = "PRIVATE_CONTENT"
    portability: str = "semantic_portable"
    merge_policy_hint: str = "create_only"
    required: bool = False
    metadata: dict[str, Any] | None = None


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("migration bundle write failed")
        view = view[written:]


def write_v2_bundle(
    bundle_path: Path,
    *,
    suite_version: str,
    generated_at: str,
    source: dict[str, Any],
    contents: tuple[V2ContentPayload, ...],
    omitted_classes: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    """Write an exclusive private directory bundle from already selected A2 inputs."""
    if bundle_path.exists() or bundle_path.is_symlink():
        raise FileExistsError("migration bundle destination already exists")
    bundle_path.mkdir(parents=True, mode=0o700)
    os.chmod(bundle_path, 0o700)
    root = PinnedRoot(bundle_path)
    inventory: list[dict[str, Any]] = []
    try:
        for content in sorted(contents, key=lambda item: (item.content_class, item.logical_name, item.entry_id)):
            parts = validate_relative_path(content.bundle_path)
            if not parts or parts[0] != "payload":
                raise ValueError("migration content must be stored below payload/")
            fd = root.open_exclusive(content.bundle_path)
            try:
                _write_all(fd, content.payload)
                os.fsync(fd)
            finally:
                os.close(fd)
            entry = {
                "entry_id": content.entry_id,
                "content_class": content.content_class,
                "logical_name": content.logical_name,
                "bundle_path": content.bundle_path,
                "source_role": content.source_role,
                "schema_id": content.schema_id,
                "schema_version": content.schema_version,
                "sha256": hashlib.sha256(content.payload).hexdigest(),
                "size_bytes": len(content.payload),
                "private": True,
                "privacy_class": content.privacy_class,
                "portability": content.portability,
                "merge_policy_hint": content.merge_policy_hint,
                "required": content.required,
            }
            if content.metadata:
                for key, value in content.metadata.items():
                    if key not in entry:
                        entry[key] = value
            inventory.append(entry)
        manifest = {
            "contract_id": MIGRATION_CONTRACT_ID,
            "contract_version": MIGRATION_CONTRACT_VERSION_V2,
            "kind": MIGRATION_BUNDLE_KIND,
            "suite_version": suite_version,
            "generated_at": generated_at,
            "private_bundle": True,
            "safe_to_share_publicly": False,
            "source": source,
            "content": inventory,
            "omitted_classes": list(omitted_classes),
        }
        encoded = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        fd = root.open_exclusive(MANIFEST_NAME)
        try:
            _write_all(fd, encoded)
            os.fsync(fd)
        finally:
            os.close(fd)
        return manifest
    finally:
        root.close()


def _error(code: str, phase: str, message: str, **kwargs: Any) -> MigrationSafeError:
    return MigrationSafeError(code, phase, message, **kwargs)


def _read_json_fd(fd: int) -> Any:
    with os.fdopen(os.dup(fd), "r", encoding="utf-8") as stream:
        return json.load(stream)


def _hash_fd(fd: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def validate_v2_bundle(bundle_path: Path) -> tuple[ValidatedV2Bundle | None, tuple[MigrationSafeError, ...]]:
    errors: list[MigrationSafeError] = []
    warnings: list[MigrationSafeError] = []
    try:
        bundle = PinnedRoot(bundle_path)
    except OSError:
        return None, (_error("BUNDLE_UNSAFE", "validate", "Bundle directory is missing or unsafe."),)
    with bundle:
        try:
            manifest_fd = bundle.open_read(MANIFEST_NAME)
            try:
                manifest = _read_json_fd(manifest_fd)
            finally:
                os.close(manifest_fd)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None, (_error("MANIFEST_UNREADABLE", "validate", "Migration manifest is missing or unreadable."),)
        if not isinstance(manifest, dict):
            return None, (_error("MANIFEST_INVALID", "validate", "Migration manifest must be a JSON object."),)

        missing = REQUIRED_MANIFEST_FIELDS - manifest.keys()
        if missing:
            errors.append(_error("MANIFEST_FIELDS_MISSING", "validate", "Migration manifest is missing required fields."))
        if manifest.get("contract_id") != MIGRATION_CONTRACT_ID:
            errors.append(_error("CONTRACT_ID_INVALID", "validate", "Migration manifest contract identity is invalid."))
        if manifest.get("contract_version") != MIGRATION_CONTRACT_VERSION_V2:
            errors.append(_error("CONTRACT_VERSION_UNSUPPORTED", "validate", "Migration manifest version is unsupported."))
        if manifest.get("kind") != MIGRATION_BUNDLE_KIND:
            errors.append(_error("MANIFEST_KIND_INVALID", "validate", "Migration manifest kind is invalid."))
        if manifest.get("private_bundle") is not True or manifest.get("safe_to_share_publicly") is not False:
            errors.append(_error("PRIVACY_MARKER_INVALID", "validate", "Migration bundle privacy markers are invalid."))
        source_metadata = manifest.get("source")
        if not isinstance(source_metadata, dict) or not isinstance(manifest.get("omitted_classes"), list):
            errors.append(_error("MANIFEST_METADATA_INVALID", "validate", "Migration manifest source or omission inventory is invalid."))
        elif source_metadata.get("path_mode") != "logical_roots" or not isinstance(source_metadata.get("logical_roots"), dict):
            errors.append(_error("SOURCE_PATH_MODE_INVALID", "validate", "Migration source paths must use logical-root provenance."))
        if not str(manifest.get("suite_version") or "") or not str(manifest.get("generated_at") or ""):
            errors.append(_error("MANIFEST_METADATA_INVALID", "validate", "Migration manifest version or creation metadata is invalid."))
        if any(not isinstance(item, dict) for item in manifest.get("omitted_classes", [])):
            errors.append(_error("OMITTED_INVENTORY_INVALID", "validate", "Migration omission inventory is invalid."))

        raw_entries = manifest.get("content")
        if not isinstance(raw_entries, list):
            errors.append(_error("CONTENT_INVENTORY_INVALID", "validate", "Migration content inventory is invalid."))
            raw_entries = []
        entry_ids: set[str] = set()
        bundle_paths: set[str] = set()
        entries: list[dict[str, Any]] = []
        for raw in raw_entries:
            if not isinstance(raw, dict) or ENTRY_REQUIRED_FIELDS - raw.keys():
                errors.append(_error("CONTENT_ENTRY_INVALID", "validate", "Migration content inventory has an invalid entry."))
                continue
            entry_id = str(raw.get("entry_id") or "")
            payload_path = str(raw.get("bundle_path") or "")
            content_class = str(raw.get("content_class") or "")
            logical_name = str(raw.get("logical_name") or "")
            if not entry_id or entry_id in entry_ids:
                errors.append(_error("DUPLICATE_ENTRY_ID", "validate", "Migration content entry IDs must be unique."))
            entry_ids.add(entry_id)
            if not payload_path or payload_path in bundle_paths:
                errors.append(_error("DUPLICATE_BUNDLE_PATH", "validate", "Migration payload paths must be unique."))
            bundle_paths.add(payload_path)
            try:
                payload_parts = validate_relative_path(payload_path)
                if not payload_parts or payload_parts[0] != "payload":
                    raise ValueError("payload path is outside the payload inventory")
            except ValueError:
                errors.append(_error("PAYLOAD_PATH_INVALID", "validate", "Migration payload path is unsafe.", content_class=content_class, logical_item=logical_name))
                continue
            supported = SUPPORTED_CONTENT_SCHEMAS.get(content_class)
            if supported is None:
                issue = _error(
                    "CONTENT_CLASS_UNSUPPORTED",
                    "validate",
                    "Migration content class is unsupported by this LVS version.",
                    content_class=content_class,
                    logical_item=logical_name,
                    manual_action_required=bool(raw.get("required")),
                )
                if raw.get("required") is True:
                    errors.append(issue)
                else:
                    warnings.append(issue)
            else:
                schema_id = str(raw.get("schema_id") or "")
                try:
                    schema_version = int(raw.get("schema_version"))
                except (TypeError, ValueError):
                    schema_version = -1
                if schema_id not in supported or schema_version not in supported.get(schema_id, set()):
                    errors.append(_error("SCHEMA_VERSION_UNSUPPORTED", "validate", "Migration content schema is unsupported.", content_class=content_class, logical_item=logical_name))
            if raw.get("private") is not True or str(raw.get("privacy_class")) not in {"PRIVATE_CONTENT", "PRIVATE_METADATA"}:
                errors.append(_error("CONTENT_PRIVACY_INVALID", "validate", "Migration content privacy classification is invalid.", content_class=content_class, logical_item=logical_name))
            try:
                expected_size = int(raw.get("size_bytes"))
            except (TypeError, ValueError):
                expected_size = -1
            expected_hash = str(raw.get("sha256") or "")
            if len(expected_hash) != 64 or any(character not in "0123456789abcdef" for character in expected_hash):
                errors.append(_error("PAYLOAD_HASH_INVALID", "validate", "Migration payload hash is invalid.", content_class=content_class, logical_item=logical_name))
            if raw.get("required") not in {True, False}:
                errors.append(_error("CONTENT_REQUIRED_FLAG_INVALID", "validate", "Migration content required marker is invalid.", content_class=content_class, logical_item=logical_name))
            try:
                fd = bundle.open_read(payload_path)
                try:
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode):
                        raise OSError("payload is not regular")
                    actual_hash, actual_size = _hash_fd(fd)
                finally:
                    os.close(fd)
                if actual_size != expected_size:
                    errors.append(_error("PAYLOAD_SIZE_MISMATCH", "validate", "Migration payload size does not match its manifest.", content_class=content_class, logical_item=logical_name))
                if actual_hash != expected_hash:
                    errors.append(_error("PAYLOAD_HASH_MISMATCH", "validate", "Migration payload hash does not match its manifest.", content_class=content_class, logical_item=logical_name))
            except OSError:
                errors.append(_error("PAYLOAD_MISSING_OR_UNSAFE", "validate", "Migration payload is missing or unsafe.", content_class=content_class, logical_item=logical_name))
            entries.append(dict(raw))

        try:
            actual_files: set[str] = set()
            for directory, directory_names, file_names, directory_fd in os.fwalk(
                ".", dir_fd=bundle.fd, follow_symlinks=False
            ):
                relative_dir = Path() if directory == "." else Path(directory)
                for name in directory_names:
                    info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        errors.append(_error("BUNDLE_SYMLINK", "validate", "Migration bundle contains a symlink."))
                for name in file_names:
                    info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                        errors.append(_error("BUNDLE_ENTRY_UNSAFE", "validate", "Migration bundle contains an unsafe entry."))
                    actual_files.add((relative_dir / name).as_posix())
            unlisted = actual_files - {MANIFEST_NAME, *bundle_paths}
            if unlisted:
                errors.append(_error("UNLISTED_PAYLOAD", "validate", "Migration bundle contains an unlisted payload."))
        except (OSError, ValueError):
            errors.append(_error("BUNDLE_INVENTORY_UNREADABLE", "validate", "Migration bundle inventory could not be verified."))

    if errors:
        return None, tuple(errors)
    return ValidatedV2Bundle(bundle_path.absolute(), manifest, tuple(entries), tuple(warnings)), ()


def logical_destination(entry: dict[str, Any], ownership: MigrationPathOwnership) -> LogicalDestination | None:
    del ownership
    content_class = str(entry.get("content_class") or "")
    if content_class == "settings":
        return LogicalDestination("settings", "global_settings.json")
    if content_class == "setup_history":
        return LogicalDestination("settings", "run_setup_history.json")
    if content_class in {"custom_profile", "modified_stock_profile"}:
        validate_relative_path(str(entry.get("logical_name") or ""))
        if len(validate_relative_path(str(entry.get("logical_name") or ""))) != 1:
            raise ValueError("profile logical name must be one filename")
        return LogicalDestination("profiles", str(entry["logical_name"]))
    return None


def destination_preconditions(actions: list[MigrationPlanAction], ownership: MigrationPathOwnership) -> dict[str, str]:
    state: dict[str, str] = {}
    roots: dict[str, PinnedRoot] = {}
    try:
        for action in actions:
            if action.destination is None:
                continue
            role = action.destination.root_role
            if role not in roots:
                root_path = ownership.root_for_role(role)
                if not root_path.is_dir() or root_path.is_symlink():
                    state[action.action_id] = "missing"
                    continue
                roots[role] = PinnedRoot(root_path)
            state[action.action_id] = roots[role].identity(action.destination.relative_path).token()
    finally:
        for root in roots.values():
            root.close()
    return state


def preview_token(manifest: dict[str, Any], preconditions: dict[str, str]) -> str:
    payload = {
        "manifest": manifest,
        "destination_preconditions": dict(sorted(preconditions.items())),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_a1_plan(bundle: ValidatedV2Bundle, ownership: MigrationPathOwnership) -> MigrationPlan:
    actions: list[MigrationPlanAction] = []
    for entry in sorted(bundle.entries, key=lambda item: (str(item.get("content_class")), str(item.get("logical_name")), str(item.get("entry_id")))):
        content_class = str(entry.get("content_class") or "")
        logical_item = str(entry.get("logical_name") or "")
        if content_class not in SUPPORTED_CONTENT_SCHEMAS:
            actions.append(MigrationPlanAction(str(entry["entry_id"]), content_class, logical_item, None, "excluded", "OPTIONAL_CONTENT_CLASS_UNSUPPORTED", safe_summary="Optional content is not supported by this LVS version."))
            continue
        if content_class in {"profile_menu_metadata", "custom_profile", "modified_stock_profile"}:
            actions.append(MigrationPlanAction(str(entry["entry_id"]), content_class, logical_item, None, "excluded", "A2_SEMANTICS_NOT_IMPLEMENTED", safe_summary="Content is recognized but awaits the A2 semantic migration handler."))
            continue
        if content_class == "recovery_profile":
            actions.append(MigrationPlanAction(str(entry["entry_id"]), content_class, logical_item, None, "quarantine", "RECOVERY_ONLY_CONTENT", safe_summary="Recovery-only content will not be installed into active state."))
            continue
        destination = logical_destination(entry, ownership)
        if destination is None:
            actions.append(MigrationPlanAction(str(entry["entry_id"]), content_class, logical_item, None, "excluded", "A2_SEMANTICS_NOT_IMPLEMENTED"))
            continue
        root_path = ownership.root_for_role(destination.root_role)
        if root_path.is_symlink():
            raise OSError("migration destination root is unsafe")
        if root_path.is_dir():
            with PinnedRoot(root_path) as root:
                identity = root.identity(destination.relative_path)
        else:
            from .lvs_migration_safe_fs import FileIdentity

            identity = FileIdentity(False)
        if identity.exists:
            disposition = "conflict"
            reason = "A2_SEMANTIC_MERGE_REQUIRED"
            operations: tuple[dict[str, Any], ...] = ()
        else:
            disposition = "create"
            reason = "DESTINATION_MISSING"
            operations = ({"operation": "create_file", "entry_id": str(entry["entry_id"])},)
        actions.append(
            MigrationPlanAction(
                str(entry["entry_id"]),
                content_class,
                logical_item,
                destination,
                disposition,
                reason,
                requires_user_choice=disposition == "conflict",
                allowed_resolutions=("keep_destination",) if disposition == "conflict" else (),
                safe_summary="Destination is absent." if disposition == "create" else "Existing content requires the future semantic handler.",
                transaction_operations=operations,
            )
        )
    preconditions = destination_preconditions(actions, ownership)
    token = preview_token(bundle.manifest, preconditions)
    apply_ready = all(not action.requires_user_choice for action in actions)
    return MigrationPlan(True, 2, token, tuple(actions), warnings=bundle.warnings, requires_restart=True, apply_ready=apply_ready)
