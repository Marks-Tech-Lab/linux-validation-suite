#!/usr/bin/env python3
"""Frontend-neutral migration v2 contracts, plans, and safe errors."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


MIGRATION_CONTRACT_ID = "linux_validation_suite.private_migration_bundle"
MIGRATION_CONTRACT_VERSION_V2 = 2
MIGRATION_BUNDLE_KIND = "private_local_migration_bundle"

PLAN_DISPOSITIONS = frozenset(
    {
        "create",
        "import_renamed",
        "merge",
        "skip_identical",
        "preserve_destination",
        "conflict",
        "relink_required",
        "excluded",
        "invalid",
        "quarantine",
    }
)
PLAN_RESOLUTIONS = frozenset(
    {"keep_destination", "import_source_as_renamed", "replace_destination"}
)


@dataclass(frozen=True)
class MigrationSafeError:
    error_code: str
    phase: str
    safe_message: str
    content_class: str = ""
    logical_item: str = ""
    retryable: bool = False
    manual_action_required: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LogicalDestination:
    root_role: str
    relative_path: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class MigrationPlanAction:
    action_id: str
    content_class: str
    logical_item: str
    destination: LogicalDestination | None
    disposition: str
    reason_code: str
    destructive: bool = False
    requires_user_choice: bool = False
    allowed_resolutions: tuple[str, ...] = ()
    selected_resolution: str | None = None
    safe_summary: str = ""
    dependencies: tuple[str, ...] = ()
    transaction_operations: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.disposition not in PLAN_DISPOSITIONS:
            raise ValueError("unsupported migration plan disposition")
        if any(value not in PLAN_RESOLUTIONS for value in self.allowed_resolutions):
            raise ValueError("unsupported migration plan resolution")
        if self.selected_resolution is not None and self.selected_resolution not in self.allowed_resolutions:
            raise ValueError("selected migration resolution is not allowed")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.destination is not None:
            payload["destination"] = self.destination.to_dict()
        return payload


@dataclass(frozen=True)
class MigrationPlan:
    valid: bool
    bundle_contract_version: int
    preview_token: str
    actions: tuple[MigrationPlanAction, ...]
    errors: tuple[MigrationSafeError, ...] = ()
    warnings: tuple[MigrationSafeError, ...] = ()
    requires_restart: bool = True
    apply_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "migration_restore_plan",
            "valid": self.valid,
            "bundle_contract_version": self.bundle_contract_version,
            "preview_token": self.preview_token,
            "actions": [action.to_dict() for action in self.actions],
            "errors": [error.to_dict() for error in self.errors],
            "warnings": [warning.to_dict() for warning in self.warnings],
            "requires_restart": self.requires_restart,
            "apply_ready": self.apply_ready,
        }


@dataclass(frozen=True)
class MigrationApplyResult:
    valid: bool
    applied: bool
    plan: MigrationPlan
    transaction_id: str = ""
    rollback_complete: bool | None = None
    recovery_required: bool = False
    recovery_instructions: tuple[str, ...] = ()
