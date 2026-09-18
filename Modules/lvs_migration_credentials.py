#!/usr/bin/env python3
"""Focused service-account credential handling for private migration bundles."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

from .lvs_migration_models import MigrationSafeError
from .lvs_migration_paths import MigrationPathOwnership
from .lvs_migration_safe_fs import PinnedRoot
from .lvs_settings import DEFAULT_GOOGLE_CREDENTIALS_PATH


UPLOAD_CREDENTIAL_CONTENT_CLASS = "upload_credentials"
UPLOAD_CREDENTIAL_SCHEMA_ID = "linux_validation_suite.migration.google_service_account"
UPLOAD_CREDENTIAL_SCHEMA_VERSION = 1
UPLOAD_CREDENTIAL_MAX_BYTES = 1024 * 1024
DESTINATION_CREDENTIAL_RELATIVE = "secrets/google-credentials.json"


class CredentialPayloadInvalid(ValueError):
    """A secret payload is intact but not a supported credential document."""


@dataclass(frozen=True)
class UploadCredentialInspection:
    configured: bool
    available: bool
    credential_type: str
    payload: bytes | None = field(repr=False)
    sha256: str
    error: MigrationSafeError | None


def destination_credential_path(ownership: MigrationPathOwnership) -> Path:
    return ownership.settings_root / DESTINATION_CREDENTIAL_RELATIVE


def resolve_source_credential_path(
    ownership: MigrationPathOwnership,
    configured_value: object,
) -> Path:
    raw = Path(str(configured_value or DEFAULT_GOOGLE_CREDENTIALS_PATH)).expanduser()
    candidate = raw if raw.is_absolute() else ownership.application_root / raw
    # Symlinked credential paths are supported by the uploader. Resolve the
    # final target deliberately, then pin that target without following again.
    return candidate.resolve(strict=True)


def _stable_bounded_read(path: Path) -> bytes:
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise OSError("credential parent is unsafe")
    with PinnedRoot(path.parent) as root:
        fd = root.open_read(path.name)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise OSError("credential source is not a regular file")
            if before.st_size > UPLOAD_CREDENTIAL_MAX_BYTES:
                raise OverflowError("credential source exceeds size limit")
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = os.read(fd, min(1024 * 1024, UPLOAD_CREDENTIAL_MAX_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > UPLOAD_CREDENTIAL_MAX_BYTES:
                    raise OverflowError("credential source exceeds size limit")
            after = os.fstat(fd)
        finally:
            os.close(fd)
    identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
    if identity(before) != identity(after):
        raise RuntimeError("credential source changed during export")
    return b"".join(chunks)


def validate_service_account_payload(payload: bytes) -> bool:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(value, dict) or value.get("type") != "service_account":
        return False
    private_key = value.get("private_key")
    return all(
        isinstance(value.get(key), str) and bool(value.get(key).strip())
        for key in ("project_id", "private_key_id", "client_email", "client_id", "token_uri")
    ) and isinstance(private_key, str) and "BEGIN PRIVATE KEY" in private_key and "END PRIVATE KEY" in private_key


def inspect_upload_credentials(
    ownership: MigrationPathOwnership,
    settings_raw: dict[str, Any],
) -> UploadCredentialInspection:
    configured_value = settings_raw.get("google_drive_credentials_path")
    drive_configured = bool(str(settings_raw.get("google_drive_shared_drive_id") or "").strip())
    try:
        path = resolve_source_credential_path(ownership, configured_value)
    except FileNotFoundError:
        configured_text = str(configured_value or "").strip()
        configured = drive_configured or bool(
            configured_text and configured_text != str(DEFAULT_GOOGLE_CREDENTIALS_PATH)
        )
        if not configured:
            return UploadCredentialInspection(False, False, "service_account", None, "", None)
        return UploadCredentialInspection(configured, False, "service_account", None, "",
            MigrationSafeError("CREDENTIAL_SOURCE_MISSING", "export",
                "Configured upload credentials are missing.", content_class=UPLOAD_CREDENTIAL_CONTENT_CLASS,
                logical_item="google_drive_upload", retryable=True, manual_action_required=True))
    except OSError:
        return UploadCredentialInspection(True, False, "service_account", None, "",
            MigrationSafeError("CREDENTIAL_SOURCE_UNREADABLE", "export",
                "Configured upload credentials are unreadable or unsafe.",
                content_class=UPLOAD_CREDENTIAL_CONTENT_CLASS, logical_item="google_drive_upload",
                retryable=True, manual_action_required=True))
    try:
        payload = _stable_bounded_read(path)
    except OverflowError:
        return UploadCredentialInspection(True, False, "service_account", None, "",
            MigrationSafeError("CREDENTIAL_TOO_LARGE", "export",
                "Configured upload credentials exceed the migration size limit.",
                content_class=UPLOAD_CREDENTIAL_CONTENT_CLASS, logical_item="google_drive_upload",
                manual_action_required=True))
    except RuntimeError:
        return UploadCredentialInspection(True, False, "service_account", None, "",
            MigrationSafeError("CREDENTIAL_CHANGED_DURING_EXPORT", "export",
                "Configured upload credentials changed during export; retry the migration.",
                content_class=UPLOAD_CREDENTIAL_CONTENT_CLASS, logical_item="google_drive_upload", retryable=True))
    except OSError:
        return UploadCredentialInspection(True, False, "service_account", None, "",
            MigrationSafeError("CREDENTIAL_SOURCE_UNREADABLE", "export",
                "Configured upload credentials are unreadable or unsafe.",
                content_class=UPLOAD_CREDENTIAL_CONTENT_CLASS, logical_item="google_drive_upload",
                retryable=True, manual_action_required=True))
    if not validate_service_account_payload(payload):
        return UploadCredentialInspection(True, False, "service_account", None, "",
            MigrationSafeError("CREDENTIAL_INVALID", "export",
                "Configured upload credentials are not a valid supported service-account document.",
                content_class=UPLOAD_CREDENTIAL_CONTENT_CLASS, logical_item="google_drive_upload",
                manual_action_required=True))
    return UploadCredentialInspection(
        True, True, "service_account", payload, hashlib.sha256(payload).hexdigest(), None,
    )


def safe_read_destination_credential(path: Path) -> bytes | None:
    if not path.parent.exists():
        return None
    try:
        return _stable_bounded_read(path)
    except FileNotFoundError:
        return None
