#!/usr/bin/env python3
"""Conservative v1 bundle projection into migration v2 planning input."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

from .lvs_settings import GlobalSettings


DESTINATION_LOCAL_SETTINGS = frozenset({"environment_mode", "results_dir", "profiles_dir", "settings_dir"})
SECRET_OR_RELINK_SETTINGS = frozenset(
    {"runtime_environment", "google_drive_credentials_path", "google_drive_shared_drive_id"}
)
SESSION_ONLY_SETTINGS = frozenset({"privileged_helper_enabled", "privileged_helper_prompt_for_sudo"})
POLICY_PENDING_SETTINGS = frozenset()


@dataclass(frozen=True)
class V1PlanningInput:
    settings_values: dict[str, Any]
    destination_local_fields: tuple[str, ...]
    relink_required: tuple[str, ...]
    session_only_fields: tuple[str, ...]
    policy_pending_fields: tuple[str, ...]
    history_records: tuple[dict[str, Any], ...]
    recovery_only: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]
    absent_content_classes: tuple[str, ...] = ("custom_profile", "modified_stock_profile", "result_tree")


def adapt_v1_payloads(payloads: dict[str, Any]) -> V1PlanningInput:
    allowed = {item.name for item in fields(GlobalSettings)}
    raw_settings = payloads.get("global_settings")
    source_settings = raw_settings if isinstance(raw_settings, dict) else {}
    settings_values = {
        key: value
        for key, value in source_settings.items()
        if key in allowed
        and key not in DESTINATION_LOCAL_SETTINGS
        and key not in SECRET_OR_RELINK_SETTINGS
        and key not in SESSION_ONLY_SETTINGS
        and key not in POLICY_PENDING_SETTINGS
    }
    relink = tuple(
        sorted(
            key
            for key in SECRET_OR_RELINK_SETTINGS
            if key in source_settings and bool(source_settings.get(key))
        )
    )
    raw_history = payloads.get("run_setup_history")
    history = tuple(dict(item) for item in raw_history if isinstance(item, dict)) if isinstance(raw_history, list) else ()
    recovery: list[dict[str, Any]] = []
    if isinstance(payloads.get("hardware_result_validation_state"), dict):
        recovery.append(
            {
                "content_class": "hardware_validation_state",
                "disposition": "quarantine",
                "reason_code": "V1_DERIVED_HARDWARE_STATE_NOT_RESTORED",
                "safe_summary": "Legacy hardware validation state is recovery-only and will not be installed.",
            }
        )
    warnings = (
        "Version 1 bundles do not contain profiles or result artifacts.",
        "Version 1 scaffolds are ignored by the version 2 planning engine.",
    )
    return V1PlanningInput(
        settings_values=settings_values,
        destination_local_fields=tuple(sorted(DESTINATION_LOCAL_SETTINGS & source_settings.keys())),
        relink_required=relink,
        session_only_fields=tuple(sorted(SESSION_ONLY_SETTINGS & source_settings.keys())),
        policy_pending_fields=tuple(sorted(POLICY_PENDING_SETTINGS & source_settings.keys())),
        history_records=history,
        recovery_only=tuple(recovery),
        warnings=warnings,
    )
