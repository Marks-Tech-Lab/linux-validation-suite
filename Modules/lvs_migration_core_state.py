#!/usr/bin/env python3
"""Semantic settings, profile, and setup-history migration for contract v2."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from tempfile import TemporaryDirectory
from typing import Any

from .lvs_core import APP_VERSION
from .lvs_migration_models import LogicalDestination, MigrationPlan, MigrationPlanAction, MigrationSafeError
from .lvs_migration_credentials import (
    DESTINATION_CREDENTIAL_RELATIVE,
    CredentialPayloadInvalid,
    UPLOAD_CREDENTIAL_CONTENT_CLASS,
    UPLOAD_CREDENTIAL_SCHEMA_ID,
    destination_credential_path,
    inspect_upload_credentials,
    safe_read_destination_credential,
    validate_service_account_payload,
)
from .lvs_migration_paths import MigrationPathOwnership
from .lvs_migration_safe_fs import FileIdentity, PinnedRoot, validate_relative_path
from .lvs_migration_v2 import V2ContentPayload, ValidatedV2Bundle, destination_preconditions, preview_token
from .lvs_profile_loader import ProfileLoader
from .lvs_run_setup_history_service import run_setup_history_signature
from .lvs_settings import GlobalSettings


PORTABLE = "PORTABLE"
DESTINATION_LOCAL = "DESTINATION_LOCAL"
SECRET_OR_RELINK = "SECRET_OR_RELINK"
SESSION_ONLY = "SESSION_ONLY"

DESTINATION_LOCAL_FIELDS = frozenset({"environment_mode", "results_dir", "profiles_dir", "settings_dir"})
SECRET_OR_RELINK_FIELDS = frozenset(
    {"runtime_environment", "google_drive_credentials_path"}
)
SESSION_ONLY_FIELDS = frozenset({"privileged_helper_enabled", "privileged_helper_prompt_for_sudo"})
PORTABLE_FIELDS = frozenset(
    {
        "sample_interval_seconds", "trim_start_seconds", "trim_end_seconds",
        "export_compatibility_json", "export_extended_json", "keep_raw_telemetry",
        "prompt_for_wall_wattage", "abort_on_fail_threshold", "abort_on_worker_error",
        "abort_on_system_fault", "abort_run_on_stage_abort", "target_gpu_busy_min_percent",
        "target_gpu_busy_sustain_seconds", "target_gpu_memory_busy_min_percent",
        "target_gpu_memory_busy_sustain_seconds", "strict_threshold_recommendation_warnings",
        "gpu_safe_mode", "gpu_retune_warmup_seconds", "gpu_retune_cooldown_seconds",
        "gpu_max_retunes_per_worker", "gpu_internal_ramp_step_seconds",
        "gpu_safe_start_load_fraction", "gpu_safe_max_tuning_step", "gpu_safe_max_load_scale",
        "gpu_safe_max_vram_percent", "gpu_external_max_processes", "suite_department",
        "case_options", "psu_rating_options", "cpu_cooler_options",
        "google_drive_move_to_uploaded_on_success", "google_drive_prompt_after_run",
        "google_drive_shared_drive_id",
        "profile_menu_groups",
    }
)
SETTINGS_FIELD_POLICY = {
    **{name: PORTABLE for name in PORTABLE_FIELDS},
    **{name: DESTINATION_LOCAL for name in DESTINATION_LOCAL_FIELDS},
    **{name: SECRET_OR_RELINK for name in SECRET_OR_RELINK_FIELDS},
    **{name: SESSION_ONLY for name in SESSION_ONLY_FIELDS},
}
_KNOWN_SETTINGS_FIELDS = frozenset(item.name for item in fields(GlobalSettings))
if frozenset(SETTINGS_FIELD_POLICY) != _KNOWN_SETTINGS_FIELDS:
    missing = sorted(_KNOWN_SETTINGS_FIELDS - SETTINGS_FIELD_POLICY.keys())
    extra = sorted(SETTINGS_FIELD_POLICY.keys() - _KNOWN_SETTINGS_FIELDS)
    raise RuntimeError(f"GlobalSettings migration policy is incomplete (missing={missing}, extra={extra})")


@dataclass(frozen=True)
class CoreExport:
    contents: tuple[V2ContentPayload, ...]
    omitted_classes: tuple[dict[str, Any], ...]
    summary: dict[str, Any]
    warnings: tuple[MigrationSafeError, ...] = ()


@dataclass(frozen=True)
class CorePlan:
    plan: MigrationPlan
    materialized_payloads: dict[str, bytes] = field(repr=False)
    summary: dict[str, Any]


class MigrationSourceChanged(OSError):
    """An export input changed while its stable snapshot was being read."""


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _read_stable_regular(path: Path) -> bytes | None:
    if not path.parent.is_dir() or path.parent.is_symlink():
        return None
    try:
        with PinnedRoot(path.parent) as root:
            fd = root.open_read(path.name)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode):
                    return None
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                after = os.fstat(fd)
            finally:
                os.close(fd)
    except FileNotFoundError:
        return None
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    ):
        raise MigrationSourceChanged("migration export source changed while being read")
    return b"".join(chunks)


def _read_json_regular(path: Path) -> tuple[Any | None, dict[str, Any]]:
    raw = _read_stable_regular(path)
    if raw is None:
        return None, {}
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None, {}
    return value, {"path": path.name}


def settings_payload(raw: dict[str, Any], *, source_defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    defaults = dict(asdict(GlobalSettings()) if source_defaults is None else source_defaults)
    values = {key: raw[key] for key in sorted(PORTABLE_FIELDS) if key in raw}
    present = sorted(values)
    relink = {
        key: bool(raw.get(key))
        for key in sorted(SECRET_OR_RELINK_FIELDS)
        if key in raw
    }
    return {
        "schema_id": "linux_validation_suite.migration.settings_payload",
        "schema_version": 1,
        "source_suite_version": APP_VERSION,
        "present_fields": present,
        "portable_values": values,
        "source_defaults": {key: defaults[key] for key in sorted(PORTABLE_FIELDS) if key in defaults},
        "relink_required": relink,
        "unknown_source_keys": sorted(set(raw) - _KNOWN_SETTINGS_FIELDS),
    }


def _normalize_menu_groups(value: Any) -> list[dict[str, str]]:
    return ProfileLoader.normalize_menu_groups(value if isinstance(value, list) else None)


def semantically_pristine_settings(raw: dict[str, Any], *, settings_file: Path) -> bool:
    defaults = asdict(GlobalSettings())
    for key in PORTABLE_FIELDS:
        actual = raw.get(key, defaults[key])
        expected = defaults[key]
        if key == "profile_menu_groups":
            actual, expected = _normalize_menu_groups(actual), _normalize_menu_groups(expected)
        if actual != expected:
            return False
    return True


def _safe_value(value: Any, *, key: str = "") -> str:
    if key == "google_drive_shared_drive_id":
        return "Configured" if bool(str(value or "").strip()) else "Not configured"
    if isinstance(value, (dict, list)):
        return f"<{type(value).__name__}:{len(value)}>"
    text = str(value)
    return text if len(text) <= 80 else text[:77] + "..."


def _menu_group_merge(source: Any, destination: Any) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    src = {item["key"]: item["label"] for item in _normalize_menu_groups(source)}
    dst = {item["key"]: item["label"] for item in _normalize_menu_groups(destination)}
    actions: list[dict[str, Any]] = []
    merged = dict(dst)
    for key in sorted(src):
        if key not in dst:
            merged[key] = src[key]
            actions.append({"key": key, "disposition": "import_source"})
        elif src[key] == dst[key]:
            actions.append({"key": key, "disposition": "unchanged"})
        else:
            actions.append({"key": key, "disposition": "conflict", "source": src[key], "destination": dst[key]})
    return ([{"key": key, "label": merged[key]} for key in sorted(merged)], actions)


def merge_settings(
    source: dict[str, Any], destination_raw: dict[str, Any], *, settings_file: Path,
    resolutions: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[MigrationPlanAction], dict[str, int], set[str]]:
    resolutions = resolutions or {}
    destination_defaults = asdict(GlobalSettings())
    source_values = source.get("portable_values") if isinstance(source.get("portable_values"), dict) else {}
    source_defaults = source.get("source_defaults") if isinstance(source.get("source_defaults"), dict) else {}
    present = set(source.get("present_fields") or source_values.keys())
    output = dict(destination_raw)
    for key, value in destination_defaults.items():
        output.setdefault(key, value)
    actions: list[MigrationPlanAction] = []
    counts: dict[str, int] = {}
    conflicts: set[str] = set()
    for key in sorted(PORTABLE_FIELDS):
        action_id = f"settings:{key}"
        if key not in present or key not in source_values:
            disposition, reason = "preserve_destination", "SOURCE_FIELD_ABSENT"
        elif key == "profile_menu_groups":
            merged, group_actions = _menu_group_merge(source_values[key], output.get(key))
            group_conflicts = [item for item in group_actions if item["disposition"] == "conflict"]
            for item in group_conflicts:
                group_id = f"menu_group:{item['key']}"
                selected = resolutions.get(group_id)
                if selected not in {"keep_destination", "replace_destination"}:
                    selected = None
                if selected == "replace_destination":
                    for group in merged:
                        if group["key"] == item["key"]:
                            group["label"] = item["source"]
                elif selected != "keep_destination":
                    conflicts.add(group_id)
                actions.append(MigrationPlanAction(
                    group_id, "profile_menu_metadata", item["key"], None, "conflict",
                    "MENU_GROUP_LABEL_CONFLICT", requires_user_choice=selected is None,
                    allowed_resolutions=("keep_destination", "replace_destination"),
                    selected_resolution=selected,
                    safe_summary="Source and destination menu-group labels differ.",
                ))
            output[key] = merged
            disposition = "conflict" if group_conflicts else ("merge" if merged != _normalize_menu_groups(destination_raw.get(key)) else "skip_identical")
            reason = "MENU_GROUP_SEMANTIC_MERGE"
        else:
            src = source_values[key]
            dst = output.get(key, destination_defaults[key])
            dst_default = destination_defaults[key]
            destination_customized = dst != dst_default
            if src == dst:
                disposition, reason = "skip_identical", "VALUES_IDENTICAL"
            elif key not in source_defaults:
                if not destination_customized:
                    output[key] = src
                    disposition, reason = "merge", "IMPORT_SOURCE_WITH_UNKNOWN_ERA_DEFAULT"
                else:
                    selected = resolutions.get(action_id)
                    if selected not in {"keep_destination", "replace_destination"}:
                        selected = None
                    if selected == "replace_destination":
                        output[key] = src
                    elif selected != "keep_destination":
                        conflicts.add(action_id)
                    disposition, reason = "conflict", "SOURCE_DEFAULT_UNKNOWN_DESTINATION_CUSTOMIZED"
                    actions.append(MigrationPlanAction(
                        action_id, "settings_field", key, None, disposition, reason,
                        requires_user_choice=selected is None,
                        allowed_resolutions=("keep_destination", "replace_destination"),
                        selected_resolution=selected,
                        safe_summary=f"The source-era default for {key} is unknown and the destination is customized.",
                    ))
                    counts[disposition] = counts.get(disposition, 0) + 1
                    continue
            else:
                src_default = source_defaults[key]
                source_customized = src != src_default
                if source_customized and not destination_customized:
                    output[key] = src
                    disposition, reason = "merge", "IMPORT_SOURCE_CUSTOMIZATION"
                elif not source_customized and destination_customized:
                    disposition, reason = "preserve_destination", "DESTINATION_CUSTOMIZED"
                elif not source_customized and not destination_customized:
                    disposition, reason = "preserve_destination", "VERSION_DEFAULTS_PRESERVED"
                else:
                    selected = resolutions.get(action_id)
                    if selected not in {"keep_destination", "replace_destination"}:
                        selected = None
                    if selected == "replace_destination":
                        output[key] = src
                    elif selected != "keep_destination":
                        conflicts.add(action_id)
                    disposition, reason = "conflict", "BOTH_CUSTOMIZED_DIFFERENT"
                    actions.append(MigrationPlanAction(
                        action_id, "settings_field", key, None, disposition, reason,
                        requires_user_choice=selected is None,
                        allowed_resolutions=("keep_destination", "replace_destination"),
                        selected_resolution=selected,
                        safe_summary=f"Both installations customized {key}; source={_safe_value(src, key=key)}, destination={_safe_value(dst, key=key)}.",
                    ))
                    counts[disposition] = counts.get(disposition, 0) + 1
                    continue
        actions.append(MigrationPlanAction(action_id, "settings_field", key, None, disposition, reason,
            safe_summary=f"Settings field {key}: {reason.lower().replace('_', ' ')}."))
        counts[disposition] = counts.get(disposition, 0) + 1

    for key in sorted(DESTINATION_LOCAL_FIELDS):
        actions.append(MigrationPlanAction(f"settings-local:{key}", "settings_field", key, None,
            "preserve_destination", "DESTINATION_LOCAL", safe_summary=f"{key} remains destination-local."))
        counts["preserve_destination"] = counts.get("preserve_destination", 0) + 1
    relink = source.get("relink_required") if isinstance(source.get("relink_required"), dict) else {}
    for key in sorted(SECRET_OR_RELINK_FIELDS):
        if relink.get(key):
            actions.append(MigrationPlanAction(f"settings-relink:{key}", "settings_field", key, None,
                "relink_required", "SECRET_EXCLUDED", safe_summary=f"{key} requires destination relinking."))
            counts["relink_required"] = counts.get("relink_required", 0) + 1
    for key in sorted(SESSION_ONLY_FIELDS):
        actions.append(MigrationPlanAction(f"settings-session:{key}", "settings_field", key, None,
            "excluded", "SESSION_ONLY", safe_summary=f"{key} is session-only."))
    return output, actions, counts, conflicts


def _canonical_profile_payload(path: Path, menu_groups: Any, *, expected_raw: bytes | None = None) -> dict[str, Any]:
    initial_raw = expected_raw if expected_raw is not None else _read_stable_regular(path)
    if initial_raw is None:
        raise OSError("profile is missing or unsafe")
    raw = json.loads(initial_raw.decode("utf-8"))
    sidecar_path: Path | None = None
    sidecar_raw: bytes | None = None
    sidecar_name = raw.get("segment_label_source") if isinstance(raw, dict) else None
    if sidecar_name:
        parts = validate_relative_path(str(sidecar_name))
        if len(parts) != 1:
            raise ValueError("legacy profile label source must be a local filename")
        sidecar_path = path.parent / parts[0]
        sidecar_raw = _read_stable_regular(sidecar_path)
        if sidecar_raw is None:
            raise ValueError("legacy profile label metadata is unavailable")
    loader = ProfileLoader(path.parent, menu_groups)
    profile = loader.load_profile(path)
    legacy = loader.inspect_segment_label_source(path, profile)
    if profile.segment_label_source and legacy.get("issues"):
        raise ValueError("legacy profile label metadata is incomplete")
    payload: dict[str, Any] = {
        "profile_name": profile.profile_name,
        "profile_type": profile.profile_type,
        "menu_group": loader._normalize_menu_group(profile.menu_group),
        "require_all_stages_runnable": bool(profile.require_all_stages_runnable),
        "defaults": asdict(profile.defaults),
        "stages": [asdict(stage) for stage in profile.stages],
    }
    description = loader._normalize_menu_description(profile.menu_description)
    if description:
        payload["menu_description"] = description
    if _read_stable_regular(path) != initial_raw:
        raise MigrationSourceChanged("profile changed while being exported")
    if sidecar_path is not None and _read_stable_regular(sidecar_path) != sidecar_raw:
        raise MigrationSourceChanged("profile label metadata changed while being exported")
    return payload


def semantic_profile_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _git_baseline(root: Path, profile: Path) -> bytes | None:
    try:
        relative = profile.resolve().relative_to(root.resolve()).as_posix()
        check = subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", "--", relative],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if check.returncode:
            return None
        shown = subprocess.run(["git", "-C", str(root), "show", f"HEAD:{relative}"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
        return shown.stdout if shown.returncode == 0 else None
    except (OSError, ValueError):
        return None


def _baseline_semantic_hash(raw: bytes) -> str | None:
    try:
        with TemporaryDirectory(dir="/tmp") as temporary:
            path = Path(temporary) / "profile.json"
            path.write_bytes(raw)
            return semantic_profile_hash(_canonical_profile_payload(path, None))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def collect_core_export(
    ownership: MigrationPathOwnership,
    source_settings: GlobalSettings,
    *,
    include_upload_credentials: bool = False,
) -> CoreExport:
    contents: list[V2ContentPayload] = []
    settings_raw, _ = _read_json_regular(ownership.settings_file)
    settings_raw = settings_raw if isinstance(settings_raw, dict) else asdict(source_settings)
    source_menu_groups = settings_raw.get("profile_menu_groups", source_settings.profile_menu_groups)
    semantic_settings = settings_payload(settings_raw)
    credential_inspection = inspect_upload_credentials(ownership, settings_raw)
    credentials_included = bool(
        include_upload_credentials and credential_inspection.available and credential_inspection.payload is not None
    )
    semantic_settings["relink_required"]["google_drive_credentials_path"] = bool(
        credential_inspection.configured and not credentials_included
    )
    contents.append(V2ContentPayload(
        "settings", "settings", "global_settings", "payload/settings/semantic_settings.json", "settings",
        "linux_validation_suite.migration.settings_payload", 1, _json_bytes(semantic_settings),
        merge_policy_hint="semantic_merge", required=True,
    ))
    if credentials_included and credential_inspection.payload is not None:
        contents.append(V2ContentPayload(
            "upload-credentials", UPLOAD_CREDENTIAL_CONTENT_CLASS, "google_drive_upload",
            "payload/secrets/google_drive_credentials.json", "upload_authentication",
            UPLOAD_CREDENTIAL_SCHEMA_ID, 1, credential_inspection.payload,
            privacy_class="SECRET_CONTENT", portability="portable_secret",
            merge_policy_hint="credential_conflict",
            metadata={"credential_type": credential_inspection.credential_type},
        ))

    history_raw, _ = _read_json_regular(ownership.settings_root / "run_setup_history.json")
    valid_history, malformed = validate_history_records(history_raw if isinstance(history_raw, list) else [])
    if valid_history:
        history_payload = {"schema_id": "linux_validation_suite.migration.run_setup_history_payload",
            "schema_version": 1, "records": valid_history, "malformed_record_count": malformed}
        contents.append(V2ContentPayload(
            "setup-history", "setup_history", "run_setup_history", "payload/settings/run_setup_history.json",
            "settings", "linux_validation_suite.migration.run_setup_history_payload", 1,
            _json_bytes(history_payload), merge_policy_hint="semantic_merge",
        ))

    profile_counts = {"custom_included": 0, "modified_stock_included": 0, "stock_unchanged_omitted": 0,
        "recovery_only": 0, "unsafe_or_unreadable": 0}
    profile_root = ownership.profiles_root
    if profile_root.is_dir() and not profile_root.is_symlink():
        for path in sorted(profile_root.iterdir(), key=lambda item: item.name.lower()):
            try:
                info = path.lstat()
            except OSError:
                profile_counts["unsafe_or_unreadable"] += 1
                continue
            if path.suffix.lower() != ".json" or stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                if path.suffix.lower() == ".json":
                    profile_counts["unsafe_or_unreadable"] += 1
                continue
            raw = _read_stable_regular(path)
            if raw is None:
                profile_counts["unsafe_or_unreadable"] += 1
                continue
            try:
                canonical = _canonical_profile_payload(
                    path, source_menu_groups, expected_raw=raw,
                )
                encoded = _json_bytes(canonical)
                semantic_hash = semantic_profile_hash(canonical)
            except MigrationSourceChanged:
                raise
            except (OSError, ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError):
                contents.append(V2ContentPayload(
                    f"recovery-profile:{hashlib.sha256(path.name.encode()).hexdigest()[:16]}", "recovery_profile",
                    path.name, f"payload/recovery_profiles/{hashlib.sha256(path.name.encode()).hexdigest()[:16]}.json",
                    "profiles", "linux_validation_suite.migration.recovery_profile", 1, raw,
                    portability="recovery_only", merge_policy_hint="quarantine", metadata={"source_filename": path.name},
                ))
                profile_counts["recovery_only"] += 1
                continue
            baseline = _git_baseline(ownership.application_root, path)
            if baseline is not None:
                baseline_hash = _baseline_semantic_hash(baseline)
                if baseline_hash == semantic_hash:
                    profile_counts["stock_unchanged_omitted"] += 1
                    continue
                provenance, content_class = "tracked_modified", "modified_stock_profile"
                profile_counts["modified_stock_included"] += 1
            else:
                try:
                    path.resolve().relative_to(ownership.application_root)
                    git_present = (ownership.application_root / ".git").exists()
                    provenance = "repository_custom" if git_present else "unknown_provenance"
                except ValueError:
                    provenance = "external_custom"
                content_class = "custom_profile"
                profile_counts["custom_included"] += 1
                baseline_hash = None
            entry_id = f"profile:{semantic_hash}"
            metadata = {"source_filename": path.name, "semantic_sha256": semantic_hash,
                "provenance": provenance, "menu_group": canonical.get("menu_group", "custom")}
            if baseline_hash:
                metadata["baseline_semantic_sha256"] = baseline_hash
            contents.append(V2ContentPayload(
                entry_id, content_class, path.name, f"payload/profiles/{semantic_hash}.json", "profiles",
                "linux_validation_suite.validation_profile", 1, encoded,
                merge_policy_hint="profile_semantic_merge", metadata=metadata,
            ))

    omitted_items = [
        {"content_class": "result_tree", "reason": "not_implemented"},
        {"content_class": "hardware_validation_state", "reason": "derived_state_excluded"},
        {"content_class": "sensor_probe_logs", "reason": "not_implemented"},
        {"content_class": "archived_profiles", "reason": "not_core_v2"},
    ]
    if not credentials_included:
        omitted_items.append({"content_class": "upload_credentials", "reason": "secret_excluded"})
    omitted = tuple(omitted_items)
    shared_drive_configured = bool(str(settings_raw.get("google_drive_shared_drive_id") or "").strip())
    upload_configured = credential_inspection.configured or shared_drive_configured
    upload_complete = not upload_configured or (shared_drive_configured and credentials_included)
    credential_status = (
        "included" if credentials_included else
        "not_configured" if not credential_inspection.configured else
        "unavailable" if not credential_inspection.available else "excluded"
    )
    warnings = (credential_inspection.error,) if credential_inspection.error is not None else ()
    return CoreExport(tuple(contents), omitted, {
        "settings": {"portable_fields": len(semantic_settings["portable_values"]),
            "relink_requirements": sum(bool(value) for value in semantic_settings["relink_required"].values())},
        "profiles": profile_counts,
        "history": {"valid_records": len(valid_history), "malformed_records": malformed},
        "upload": {
            "configured": upload_configured,
            "credentials_available": credential_inspection.available,
            "shared_drive_target": "included" if shared_drive_configured else "not_configured",
            "credentials": credential_status,
            "destination_credential_path": "generated_on_restore" if credentials_included else "not_generated",
            "complete_for_current_configuration": upload_complete,
            "incomplete_reason": "" if upload_complete else (
                credential_inspection.error.error_code if credential_inspection.error else "CREDENTIALS_EXCLUDED"
            ),
        },
        "excluded": [item["content_class"] for item in omitted],
    }, warnings)


def _entry_json(bundle: ValidatedV2Bundle, entry: dict[str, Any]) -> Any:
    return json.loads(_entry_bytes(bundle, entry).decode("utf-8"))


def _entry_bytes(bundle: ValidatedV2Bundle, entry: dict[str, Any]) -> bytes:
    with PinnedRoot(bundle.bundle_path) as root:
        fd = root.open_read(str(entry["bundle_path"]))
        try:
            before = os.fstat(fd)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(fd)
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
            ):
                raise OSError("migration payload changed during semantic materialization")
            payload = b"".join(chunks)
            if len(payload) != int(entry["size_bytes"]) or hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                raise OSError("migration payload failed semantic materialization integrity check")
            return payload
        finally:
            os.close(fd)


def _identity(ownership: MigrationPathOwnership, destination: LogicalDestination) -> FileIdentity:
    root_path = ownership.root_for_role(destination.root_role)
    if not root_path.is_dir() or root_path.is_symlink():
        return FileIdentity(False)
    with PinnedRoot(root_path) as root:
        return root.identity(destination.relative_path)


def _deterministic_import_name(source_name: str, semantic_hash: str, destination_hashes: dict[str, str]) -> str:
    stem, suffix = Path(source_name).stem, Path(source_name).suffix or ".json"
    width = 8
    while True:
        candidate = f"{stem} (Imported {semantic_hash[:width]}){suffix}"
        existing = destination_hashes.get(candidate)
        if existing in {None, semantic_hash}:
            return candidate
        width += 4
        if width > len(semantic_hash):
            raise ValueError("deterministic imported profile name is exhausted")


def _destination_profiles(ownership: MigrationPathOwnership, menu_groups: Any) -> tuple[dict[str, str], dict[str, str]]:
    by_name: dict[str, str] = {}
    by_hash: dict[str, str] = {}
    root = ownership.profiles_root
    if not root.exists():
        return by_name, by_hash
    if root.is_symlink() or not root.is_dir():
        raise OSError("configured profile root is unsafe")
    for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if path.suffix.lower() != ".json" or path.is_symlink() or not path.is_file():
            continue
        try:
            digest = semantic_profile_hash(_canonical_profile_payload(path, menu_groups))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
        by_name[path.name] = digest
        by_hash.setdefault(digest, path.name)
    return by_name, by_hash


def validate_history_records(value: Any) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(value, list):
        return [], 1 if value is not None else 0
    valid: list[dict[str, Any]] = []
    malformed = 0
    for raw in value:
        if not isinstance(raw, dict) or not isinstance(raw.get("metadata", {}), dict):
            malformed += 1; continue
        if "profile_file" in raw and not isinstance(raw.get("profile_file"), str):
            malformed += 1; continue
        if "profile_name" in raw and not isinstance(raw.get("profile_name"), str):
            malformed += 1; continue
        try:
            heatsoak = float(raw.get("heatsoak_minutes", 0.0) or 0.0)
        except (TypeError, ValueError):
            malformed += 1; continue
        if heatsoak < 0:
            malformed += 1; continue
        saved = raw.get("saved")
        if saved not in {None, ""}:
            try: datetime.fromisoformat(str(saved).replace("Z", "+00:00"))
            except ValueError:
                # An invalid timestamp remains a valid record with deterministic fallback ordering.
                pass
        item = dict(raw); item["heatsoak_minutes"] = heatsoak
        valid.append(item)
    return valid, malformed


def _saved_value(item: dict[str, Any]) -> float | None:
    try: return datetime.fromisoformat(str(item.get("saved") or "").replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError): return None


def merge_history(source: Any, destination: Any, mappings: dict[str, str], unresolved: set[str]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    source_valid, source_bad = validate_history_records(source)
    destination_valid, destination_bad = validate_history_records(destination)
    remapped: list[dict[str, Any]] = []
    unresolved_count = 0
    for item in source_valid:
        filename = str(item.get("profile_file") or "")
        if filename in unresolved:
            unresolved_count += 1; continue
        if filename in mappings:
            item = dict(item); item["profile_file"] = mappings[filename]
        remapped.append(item)
    candidates = [(item, 0, index) for index, item in enumerate(destination_valid)] + [
        (item, 1, index) for index, item in enumerate(remapped)
    ]
    chosen: dict[str, tuple[dict[str, Any], int, int]] = {}
    duplicates = 0
    for item, origin, order in candidates:
        signature = run_setup_history_signature(item)
        prior = chosen.get(signature)
        if prior is None:
            chosen[signature] = (item, origin, order); continue
        duplicates += 1
        current_time, prior_time = _saved_value(item), _saved_value(prior[0])
        if current_time is not None and (prior_time is None or current_time > prior_time):
            chosen[signature] = (item, origin, order)
    ordered = sorted(chosen.values(), key=lambda row: (
        -(_saved_value(row[0]) if _saved_value(row[0]) is not None else float("-inf")), row[1], row[2], run_setup_history_signature(row[0])
    ))
    merged = [row[0] for row in ordered]
    dropped = max(0, len(merged) - 8)
    return merged[:8], {"merged": len(merged[:8]), "duplicate": duplicates,
        "unresolved_profile_reference": unresolved_count, "malformed": source_bad + destination_bad,
        "dropped_by_retention_limit": dropped}


def build_core_plan(
    bundle: ValidatedV2Bundle, ownership: MigrationPathOwnership, *, resolutions: dict[str, str] | None = None,
    destination_settings: GlobalSettings | None = None,
) -> CorePlan:
    resolutions = resolutions or {}
    actions: list[MigrationPlanAction] = []
    materialized: dict[str, bytes] = {}
    summary: dict[str, Any] = {"settings": {}, "profiles": {}, "history": {}, "upload": {}}
    conflicts: set[str] = set()
    profile_mapping: dict[str, str] = {}
    unresolved_profiles: set[str] = set()
    entries = sorted(bundle.entries, key=lambda item: (str(item.get("content_class")), str(item.get("logical_name"))))

    settings_entries = [entry for entry in entries if entry.get("content_class") == "settings"]
    destination_raw, _ = _read_json_regular(ownership.settings_file)
    destination_raw = destination_raw if isinstance(destination_raw, dict) else {}
    file_settings = GlobalSettings(**{**asdict(GlobalSettings()), **{
        k: v for k, v in destination_raw.items() if k in _KNOWN_SETTINGS_FIELDS
    }})
    destination_settings = destination_settings or file_settings
    settings_output_action: MigrationPlanAction | None = None
    if settings_entries:
        source = _entry_json(bundle, settings_entries[0])
        if isinstance(source, dict) and "portable_values" not in source:
            source_version = str(bundle.manifest.get("suite_version") or "")
            source = settings_payload(
                source, source_defaults=None if source_version == APP_VERSION else {},
            )
        output, field_actions, counts, setting_conflicts = merge_settings(
            source if isinstance(source, dict) else {}, destination_raw,
            settings_file=ownership.settings_file, resolutions=resolutions,
        )
        local_values = asdict(destination_settings) if destination_settings is not None else {}
        for key in DESTINATION_LOCAL_FIELDS:
            if key in local_values:
                output[key] = local_values[key]
        actions.extend(field_actions); conflicts.update(setting_conflicts); summary["settings"] = counts
        file_id = "settings-output"
        destination = LogicalDestination("settings_file", ownership.settings_file.name)
        before = _identity(ownership, destination)
        operation = "replace_file" if before.exists else "create_file"
        settings_output_action = MigrationPlanAction(file_id, "settings", "global_settings", destination, "merge",
            "SEMANTIC_SETTINGS_MERGE", destructive=before.exists,
            safe_summary="Materialize the resolved semantic settings merge.",
            transaction_operations=({"operation": operation},) if not setting_conflicts else ())

    credential_entries = [
        entry for entry in entries if entry.get("content_class") == UPLOAD_CREDENTIAL_CONTENT_CLASS
    ]
    credential_conflicts: set[str] = set()
    if credential_entries:
        resolved_credentials_ready = False
        credential_entry = credential_entries[0]
        source_credentials = _entry_bytes(bundle, credential_entry)
        if not validate_service_account_payload(source_credentials):
            raise CredentialPayloadInvalid("unsupported upload credential payload")
        source_digest = hashlib.sha256(source_credentials).hexdigest()
        canonical_path = destination_credential_path(ownership)
        configured_text = str(destination_raw.get("google_drive_credentials_path") or "").strip()
        configured_path = Path(configured_text).expanduser() if configured_text else canonical_path
        if not configured_path.is_absolute():
            configured_path = ownership.application_root / configured_path
        active_payload = safe_read_destination_credential(configured_path)
        canonical_payload = (
            active_payload if configured_path == canonical_path
            else safe_read_destination_credential(canonical_path)
        )
        comparison_payload = active_payload if active_payload is not None else canonical_payload
        comparison_path = configured_path if active_payload is not None else canonical_path
        action_id = str(credential_entry["entry_id"])
        selected = resolutions.get(action_id)
        allowed = ("keep_destination", "replace_destination")
        if comparison_payload is not None and hashlib.sha256(comparison_payload).hexdigest() == source_digest:
            output["google_drive_credentials_path"] = str(comparison_path)
            actions.append(MigrationPlanAction(
                action_id, UPLOAD_CREDENTIAL_CONTENT_CLASS, "google_drive_upload",
                LogicalDestination("settings", DESTINATION_CREDENTIAL_RELATIVE)
                if comparison_path == canonical_path else None,
                "skip_identical", "UPLOAD_CREDENTIALS_IDENTICAL",
                safe_summary="Destination upload credentials are already identical; the existing credential is reused.",
            ))
            summary["upload"]["credentials"] = "reused"
            resolved_credentials_ready = True
        elif comparison_payload is not None and selected != "replace_destination":
            if selected == "keep_destination":
                output["google_drive_credentials_path"] = str(comparison_path)
                actions.append(MigrationPlanAction(
                    action_id, UPLOAD_CREDENTIAL_CONTENT_CLASS, "google_drive_upload", None,
                    "preserve_destination", "USER_KEPT_DESTINATION_CREDENTIALS",
                    destructive=False, allowed_resolutions=allowed, selected_resolution=selected,
                    safe_summary="Destination upload credentials are preserved; secret values are not displayed.",
                ))
                summary["upload"]["credentials"] = "destination_preserved"
                resolved_credentials_ready = validate_service_account_payload(comparison_payload)
            else:
                conflicts.add(action_id); credential_conflicts.add(action_id)
                actions.append(MigrationPlanAction(
                    action_id, UPLOAD_CREDENTIAL_CONTENT_CLASS, "google_drive_upload",
                    LogicalDestination("settings", DESTINATION_CREDENTIAL_RELATIVE),
                    "conflict", "DESTINATION_CREDENTIAL_CONFLICT",
                    destructive=True, requires_user_choice=True, allowed_resolutions=allowed,
                    safe_summary="Source and destination upload credentials are configured and differ; secret values are not displayed.",
                ))
                summary["upload"]["credentials"] = "conflict"
        else:
            replace = canonical_payload is not None
            if replace and selected != "replace_destination":
                # A differing canonical LVS-owned secret is never overwritten implicitly,
                # even when another external credential is the active reference.
                if selected == "keep_destination" and active_payload is not None:
                    output["google_drive_credentials_path"] = str(configured_path)
                    actions.append(MigrationPlanAction(
                        action_id, UPLOAD_CREDENTIAL_CONTENT_CLASS, "google_drive_upload", None,
                        "preserve_destination", "USER_KEPT_DESTINATION_CREDENTIALS",
                        allowed_resolutions=allowed, selected_resolution=selected,
                        safe_summary="Destination upload credentials are preserved; secret values are not displayed.",
                    ))
                    summary["upload"]["credentials"] = "destination_preserved"
                    resolved_credentials_ready = validate_service_account_payload(active_payload)
                else:
                    conflicts.add(action_id); credential_conflicts.add(action_id)
                    actions.append(MigrationPlanAction(
                        action_id, UPLOAD_CREDENTIAL_CONTENT_CLASS, "google_drive_upload",
                        LogicalDestination("settings", DESTINATION_CREDENTIAL_RELATIVE),
                        "conflict", "DESTINATION_CREDENTIAL_CONFLICT", destructive=True,
                        requires_user_choice=True, allowed_resolutions=allowed,
                        safe_summary="The LVS-owned destination credential differs from the source credential.",
                    ))
                    summary["upload"]["credentials"] = "conflict"
            else:
                directory_destination = LogicalDestination("settings", "secrets")
                if not ownership.settings_root.exists() or not (ownership.settings_root / "secrets").exists():
                    actions.append(MigrationPlanAction(
                        "upload-credentials-directory", UPLOAD_CREDENTIAL_CONTENT_CLASS,
                        "upload_credentials_directory", directory_destination, "create",
                        "PRIVATE_SECRET_DIRECTORY_REQUIRED",
                        safe_summary="Create the private destination credential directory.",
                        transaction_operations=({"operation": "create_directory"},),
                    ))
                operation = "replace_file" if canonical_payload is not None else "create_file"
                actions.append(MigrationPlanAction(
                    action_id, UPLOAD_CREDENTIAL_CONTENT_CLASS, "google_drive_upload",
                    LogicalDestination("settings", DESTINATION_CREDENTIAL_RELATIVE), "create",
                    "INSTALL_DESTINATION_OWNED_UPLOAD_CREDENTIALS", destructive=operation == "replace_file",
                    allowed_resolutions=allowed if comparison_payload is not None else (),
                    selected_resolution="replace_destination" if comparison_payload is not None else None,
                    safe_summary="Install source upload credentials in the destination-owned private location.",
                    transaction_operations=({"operation": operation},),
                ))
                materialized[action_id] = source_credentials
                output["google_drive_credentials_path"] = str(canonical_path)
                summary["upload"]["credentials"] = "source_installed"
                resolved_credentials_ready = True
        shared_drive_configured = bool(str(output.get("google_drive_shared_drive_id") or "").strip())
        upload_ready = not credential_conflicts and resolved_credentials_ready and shared_drive_configured
        summary["upload"].update({
            "shared_drive_target": "configured" if shared_drive_configured else "not_configured",
            "destination_credential": DESTINATION_CREDENTIAL_RELATIVE,
            "ready_after_restart": upload_ready,
            "incomplete_reason": "" if upload_ready else (
                "credential_conflict" if credential_conflicts else
                "credentials_not_usable" if not resolved_credentials_ready else
                "shared_drive_target_not_configured"
            ),
        })
    else:
        destination_credential_text = str(destination_raw.get("google_drive_credentials_path") or "").strip()
        destination_existing_credential_path = Path(destination_credential_text).expanduser() if destination_credential_text else None
        if destination_existing_credential_path is not None and not destination_existing_credential_path.is_absolute():
            destination_existing_credential_path = ownership.application_root / destination_existing_credential_path
        destination_credential_payload = (
            safe_read_destination_credential(destination_existing_credential_path)
            if destination_existing_credential_path is not None else None
        )
        destination_credential_configured = bool(
            destination_credential_payload is not None
            and validate_service_account_payload(destination_credential_payload)
        )
        destination_drive_configured = bool(str(destination_raw.get("google_drive_shared_drive_id") or "").strip())
        summary["upload"] = {
            "credentials": "not_present_in_bundle",
            "shared_drive_target": "destination_preserved" if destination_drive_configured else "not_configured",
            "ready_after_restart": destination_credential_configured and destination_drive_configured,
            "incomplete_reason": "credentials_not_present_in_bundle",
        }

    if settings_output_action is not None:
        if conflicts:
            settings_output_action = MigrationPlanAction(
                settings_output_action.action_id, settings_output_action.content_class,
                settings_output_action.logical_item, settings_output_action.destination,
                settings_output_action.disposition, settings_output_action.reason_code,
                destructive=settings_output_action.destructive,
                safe_summary=settings_output_action.safe_summary,
                dependencies=tuple(sorted(conflicts)), transaction_operations=(),
            )
        actions.append(settings_output_action)
        materialized[settings_output_action.action_id] = _json_bytes(output)

    menu_groups = destination_settings.profile_menu_groups
    if settings_entries and "output" in locals():
        menu_groups = output.get("profile_menu_groups", menu_groups)
    destination_by_name, destination_by_hash = _destination_profiles(ownership, menu_groups)
    profile_counts: dict[str, int] = {}
    for entry in entries:
        content_class = str(entry.get("content_class") or "")
        if content_class == "hardware_validation_state":
            actions.append(MigrationPlanAction(str(entry["entry_id"]), content_class,
                str(entry.get("logical_name") or "hardware_validation_state"), None,
                "quarantine", "DERIVED_HARDWARE_STATE_NOT_RESTORED",
                safe_summary="Derived hardware validation state is recovery-only and will not be installed."))
            continue
        if content_class == "recovery_profile":
            actions.append(MigrationPlanAction(str(entry["entry_id"]), content_class, str(entry.get("logical_name")), None,
                "quarantine", "RECOVERY_ONLY_CONTENT", safe_summary="Invalid readable profile remains recovery-only in the bundle."))
            profile_counts["recovery_only"] = profile_counts.get("recovery_only", 0) + 1
            continue
        if content_class not in {"custom_profile", "modified_stock_profile"}:
            continue
        payload = _entry_json(bundle, entry)
        if not isinstance(payload, dict):
            continue
        semantic_hash = semantic_profile_hash(payload)
        if semantic_hash != str(entry.get("semantic_sha256") or ""):
            raise ValueError("profile semantic identity does not match manifest")
        source_name = str(entry.get("source_filename") or entry.get("logical_name") or "")
        validate_relative_path(source_name)
        if len(Path(source_name).parts) != 1 or Path(source_name).suffix.lower() != ".json":
            raise ValueError("profile logical filename is invalid")
        existing_name = destination_by_hash.get(semantic_hash)
        if existing_name:
            actions.append(MigrationPlanAction(str(entry["entry_id"]), content_class, source_name,
                LogicalDestination("profiles", existing_name), "skip_identical", "SEMANTIC_PROFILE_EXISTS",
                safe_summary=f"An identical profile already exists as {existing_name}."))
            profile_mapping[source_name] = existing_name
            profile_counts["skip_identical"] = profile_counts.get("skip_identical", 0) + 1
            continue
        occupied = source_name in destination_by_name
        action_id = str(entry["entry_id"])
        allowed = ("keep_destination", "import_source_as_renamed", "replace_destination")
        selected = resolutions.get(action_id)
        selected = selected if selected in allowed else None
        if occupied and content_class == "modified_stock_profile":
            if selected not in allowed:
                conflicts.add(action_id); unresolved_profiles.add(source_name)
                actions.append(MigrationPlanAction(action_id, content_class, source_name,
                    LogicalDestination("profiles", source_name), "conflict", "MODIFIED_STOCK_COLLISION",
                    destructive=False, requires_user_choice=True, allowed_resolutions=allowed,
                    safe_summary="Modified stock profile conflicts with destination content."))
                profile_counts["conflict"] = profile_counts.get("conflict", 0) + 1
                continue
            if selected == "keep_destination":
                unresolved_profiles.add(source_name)
                actions.append(MigrationPlanAction(action_id, content_class, source_name,
                    LogicalDestination("profiles", source_name), "preserve_destination", "USER_KEPT_DESTINATION",
                    allowed_resolutions=allowed, selected_resolution=selected,
                    safe_summary="Destination profile is preserved; source history will not be remapped to it."))
                profile_counts["preserve_destination"] = profile_counts.get("preserve_destination", 0) + 1
                continue
        if occupied and content_class == "custom_profile" and selected == "keep_destination":
            unresolved_profiles.add(source_name)
            actions.append(MigrationPlanAction(action_id, content_class, source_name,
                LogicalDestination("profiles", source_name), "preserve_destination", "USER_KEPT_DESTINATION",
                allowed_resolutions=allowed, selected_resolution=selected,
                safe_summary="Destination profile is preserved; source history will not be remapped to it."))
            profile_counts["preserve_destination"] = profile_counts.get("preserve_destination", 0) + 1
            continue
        if occupied and selected in {None, "import_source_as_renamed"}:
            target_name = _deterministic_import_name(source_name, semantic_hash, destination_by_name)
            disposition, operation = "import_renamed", "create_file"
        else:
            target_name = source_name
            operation = "replace_file" if occupied and selected == "replace_destination" else "create_file"
            disposition = "create"
        destructive = operation == "replace_file"
        selected_for_action = "import_source_as_renamed" if disposition == "import_renamed" else selected if occupied else None
        group_dependency = f"menu_group:{payload.get('menu_group', 'custom')}"
        actions.append(MigrationPlanAction(action_id, content_class, source_name,
            LogicalDestination("profiles", target_name), disposition,
            "DETERMINISTIC_RENAME" if disposition == "import_renamed" else "PROFILE_DESTINATION_AVAILABLE",
            destructive=destructive,
            allowed_resolutions=allowed if occupied else (),
            selected_resolution=selected_for_action,
            safe_summary=f"Profile will be installed as {target_name}.",
            dependencies=(group_dependency,) if group_dependency in conflicts else (),
            transaction_operations=({"operation": operation},)))
        materialized[action_id] = _json_bytes(payload)
        profile_mapping[source_name] = target_name
        destination_by_name[target_name] = semantic_hash; destination_by_hash[semantic_hash] = target_name
        profile_counts[disposition] = profile_counts.get(disposition, 0) + 1
    summary["profiles"] = profile_counts

    history_entries = [entry for entry in entries if entry.get("content_class") == "setup_history"]
    if history_entries:
        source_history_payload = _entry_json(bundle, history_entries[0])
        source_records = (
            source_history_payload.get("records", []) if isinstance(source_history_payload, dict)
            else source_history_payload if isinstance(source_history_payload, list) else []
        )
        for record in source_records:
            if not isinstance(record, dict):
                continue
            referenced = str(record.get("profile_file") or "")
            if referenced and referenced not in profile_mapping and referenced not in destination_by_name:
                unresolved_profiles.add(referenced)
        destination_history, _ = _read_json_regular(ownership.settings_root / "run_setup_history.json")
        merged, history_counts = merge_history(source_records, destination_history or [], profile_mapping, unresolved_profiles)
        summary["history"] = history_counts
        if merged != (destination_history or []):
            action_id = "history-output"; destination = LogicalDestination("settings", "run_setup_history.json")
            before = _identity(ownership, destination)
            actions.append(MigrationPlanAction(action_id, "setup_history", "run_setup_history", destination,
                "merge", "SEMANTIC_HISTORY_MERGE", destructive=before.exists,
                safe_summary="Validated setup history will be merged and capped at eight records.",
                dependencies=tuple(sorted(conflicts)),
                transaction_operations=({"operation": "replace_file" if before.exists else "create_file"},) if not conflicts else ()))
            materialized[action_id] = _json_bytes(merged)
        else:
            actions.append(MigrationPlanAction("history-output", "setup_history", "run_setup_history", None,
                "skip_identical", "HISTORY_IDENTICAL", safe_summary="Destination history already has the merged content."))

    known = {"settings", "setup_history", "custom_profile", "modified_stock_profile", "recovery_profile",
        UPLOAD_CREDENTIAL_CONTENT_CLASS,
        "hardware_validation_state"}
    for entry in entries:
        if str(entry.get("content_class")) not in known:
            actions.append(MigrationPlanAction(str(entry["entry_id"]), str(entry.get("content_class")),
                str(entry.get("logical_name")), None, "excluded", "OPTIONAL_CONTENT_CLASS_UNSUPPORTED",
                safe_summary="Optional content is not part of core state migration."))
    action_map = {action.action_id: action for action in actions}
    resolution_errors: list[MigrationSafeError] = []
    for action_id, resolution in sorted(resolutions.items()):
        action = action_map.get(action_id)
        if action is None:
            resolution_errors.append(MigrationSafeError(
                "RESOLUTION_ACTION_UNKNOWN", "plan",
                "The selected migration action does not exist in this plan.",
                logical_item=action_id, retryable=True,
            ))
        elif resolution not in action.allowed_resolutions:
            resolution_errors.append(MigrationSafeError(
                "RESOLUTION_NOT_ALLOWED", "plan",
                "The selected resolution is not allowed for this migration action.",
                content_class=action.content_class, logical_item=action.logical_item, retryable=True,
            ))
    preconditions = destination_preconditions(actions, ownership)
    token_input = {**bundle.manifest, "selected_resolutions": sorted(resolutions.items())}
    token = preview_token(token_input, preconditions)
    apply_ready = not conflicts and not resolution_errors and all(not action.requires_user_choice for action in actions)
    plan = MigrationPlan(not resolution_errors, 2, token, tuple(actions), errors=tuple(resolution_errors),
        warnings=bundle.warnings,
        requires_restart=True, apply_ready=apply_ready)
    summary["unresolved_conflicts"] = len(conflicts)
    summary["apply_ready"] = apply_ready
    summary["pristine_destination"] = semantically_pristine_settings(destination_raw, settings_file=ownership.settings_file)
    return CorePlan(plan, materialized, summary)
