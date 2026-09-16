#!/usr/bin/env python3
"""Frontend-neutral discovery and safe operator presentation for migration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import stat
from typing import Any, Callable

from .lvs_migration_safe_fs import PinnedRoot
from .lvs_migration_v2 import MANIFEST_NAME, validate_v2_bundle


@dataclass(frozen=True)
class MigrationBundleCandidate:
    path: Path
    generated_at: str
    suite_version: str
    contract_version: int | None
    content_classes: tuple[str, ...]
    content_summary: str
    size_bytes: int
    valid: bool
    warning_count: int
    private_bundle: bool
    safe_status: str

    @property
    def row_label(self) -> str:
        created = format_generated_at(self.generated_at) or self.path.name
        version = f"v{self.contract_version}" if self.contract_version is not None else "unknown version"
        state = "valid" if self.valid else "INVALID"
        warnings = f" | {self.warning_count} warning(s)" if self.warning_count else ""
        return (
            f"{_bounded_text(created, 28)} | {_bounded_text(version, 16)} | "
            f"LVS {_bounded_text(self.suite_version or 'unknown', 24)} | "
            f"{_bounded_text(self.content_summary, 64)} | {state}{warnings}"
        )


def _bounded_text(value: Any, limit: int) -> str:
    compact = " ".join(str(value).split())
    return compact if len(compact) <= limit else compact[: max(1, limit - 1)] + "…"


def _read_manifest(directory: Path) -> dict[str, Any] | None:
    try:
        with PinnedRoot(directory) as root:
            fd = root.open_read(MANIFEST_NAME)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size > 4 * 1024 * 1024:
                    return None
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
            finally:
                os.close(fd)
        payload = json.loads(b"".join(chunks).decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _content_summary(version: int | None, manifest: dict[str, Any]) -> tuple[tuple[str, ...], str, int]:
    if version == 2:
        entries = manifest.get("content") if isinstance(manifest.get("content"), list) else []
        classes = tuple(sorted({str(item.get("content_class")) for item in entries if isinstance(item, dict)}))
        profiles = sum(str(item.get("content_class")) in {
            "custom_profile", "modified_stock_profile", "recovery_profile"
        } for item in entries if isinstance(item, dict))
        labels: list[str] = []
        if "settings" in classes:
            labels.append("settings")
        if "setup_history" in classes:
            labels.append("history")
        if profiles:
            labels.append(f"{profiles} profile{'s' if profiles != 1 else ''}")
        other = [value for value in classes if value not in {
            "settings", "setup_history", "custom_profile", "modified_stock_profile", "recovery_profile"
        }]
        labels.extend(other)
        size = sum(int(item.get("size_bytes") or 0) for item in entries if isinstance(item, dict))
        return classes, ", ".join(labels) or "empty", size
    files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
    logical = tuple(sorted({str(item.get("logical_name")) for item in files if isinstance(item, dict)}))
    labels = [
        "settings" if value == "global_settings" else
        "history" if value == "run_setup_history" else
        "hardware state (recovery-only)" if value == "hardware_result_validation_state" else value
        for value in logical
    ]
    size = sum(int(item.get("size_bytes") or 0) for item in files if isinstance(item, dict))
    return logical, ", ".join(labels) or "empty", size


def _timestamp_value(value: str) -> float | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def format_generated_at(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return ""
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OverflowError):
        return ""


def discover_migration_bundles(
    bundle_root: Path,
    *,
    validate_v1: Callable[[Path], dict[str, Any]],
) -> tuple[MigrationBundleCandidate, ...]:
    """Inspect direct child directories only; never follows candidate symlinks."""
    try:
        children = sorted(bundle_root.iterdir(), key=lambda item: item.name.casefold())
    except OSError:
        return ()
    candidates: list[MigrationBundleCandidate] = []
    for path in children:
        try:
            info = path.lstat()
        except OSError:
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            continue
        manifest = _read_manifest(path)
        if manifest is None:
            if not path.name.startswith("Private_Migration_Bundle"):
                continue
            candidates.append(MigrationBundleCandidate(
                path, "", "", None, (), "manifest unavailable", 0, False, 0, True,
                "Missing or malformed migration manifest.",
            ))
            continue
        try:
            version = int(manifest.get("contract_version"))
        except (TypeError, ValueError):
            version = None
        classes, summary, size = _content_summary(version, manifest)
        warnings = 0
        valid = False
        safe_status = "Unsupported migration contract version."
        if version == 2:
            validated, errors = validate_v2_bundle(path)
            valid = validated is not None
            warnings = len(validated.warnings) if validated is not None else 0
            safe_status = "Valid migration bundle." if valid else (
                errors[0].safe_message if errors else "Migration bundle validation failed."
            )
        elif version == 1:
            result = validate_v1(path)
            errors = result.get("errors") if isinstance(result, dict) else ["invalid"]
            valid = not errors
            warnings = len(result.get("warnings", [])) if isinstance(result, dict) else 0
            safe_status = (
                "Valid migration bundle v1; profiles and results are not included."
                if valid else "Migration bundle v1 validation failed."
            )
        candidates.append(MigrationBundleCandidate(
            path=path,
            generated_at=str(manifest.get("generated_at") or ""),
            suite_version=str(manifest.get("suite_version") or ""),
            contract_version=version,
            content_classes=classes,
            content_summary=summary,
            size_bytes=size,
            valid=valid,
            warning_count=warnings,
            private_bundle=bool(manifest.get("private_bundle", True)),
            safe_status=safe_status,
        ))
    def sort_key(item: MigrationBundleCandidate) -> tuple[int, float, str]:
        timestamp = _timestamp_value(item.generated_at)
        category = 0 if item.valid and timestamp is not None else 1 if item.valid else 2
        return category, -(timestamp or 0.0) if category == 0 else 0.0, item.path.name.casefold()

    candidates.sort(key=sort_key)
    return tuple(candidates)


def format_size(size_bytes: int) -> str:
    value = float(max(0, int(size_bytes)))
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024.0 or unit == "GiB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} GiB"


def bundle_candidate_detail(candidate: MigrationBundleCandidate) -> str:
    privacy = "PRIVATE — NOT PUBLIC-SAFE" if candidate.private_bundle else "privacy marker invalid"
    lines = [
        "Migration Bundle",
        "================",
        "",
        f"Created: {format_generated_at(candidate.generated_at) or 'Unknown'}",
        f"Source LVS: {_bounded_text(candidate.suite_version or 'Unknown', 80)}",
        f"Contract: v{candidate.contract_version}" if candidate.contract_version is not None else "Contract: Unknown",
        f"Contents: {_bounded_text(candidate.content_summary, 160)}",
        f"Declared payload size: {format_size(candidate.size_bytes)}",
        f"Warnings: {candidate.warning_count}",
        f"Status: {candidate.safe_status}",
        f"Privacy: {privacy}",
    ]
    if candidate.contract_version == 1:
        lines.extend(("", "v1 limitations: profiles/results are absent; hardware state is recovery-only."))
    return "\n".join(lines)


def unresolved_actions(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in plan.get("actions", [])
        if isinstance(item, dict) and item.get("requires_user_choice")]


def resolution_label(action: dict[str, Any], resolution: str) -> str:
    if resolution == "keep_destination":
        return "Keep destination"
    if resolution == "import_source_as_renamed":
        return "Import source as renamed copy"
    if resolution == "replace_destination":
        if action.get("content_class") in {"settings_field", "profile_menu_metadata"}:
            return "Use source (replace destination value)"
        return "Replace destination"
    return resolution.replace("_", " ").title()


def destructive_action_count(plan: dict[str, Any]) -> int:
    """Project the backend-owned destructive marker without reinterpretation."""
    return sum(bool(item.get("destructive")) for item in plan.get("actions", []) if isinstance(item, dict))


def _counts_line(values: Any) -> str:
    if not isinstance(values, dict) or not values:
        return "none"
    return ", ".join(f"{str(key).replace('_', ' ')}={value}" for key, value in sorted(values.items()))


def migration_plan_text(plan: dict[str, Any], *, include_details: bool = False) -> str:
    """Render only structured plan fields; never parses backend summary text."""
    summary = plan.get("summary") if isinstance(plan.get("summary"), dict) else {}
    conflicts = unresolved_actions(plan)
    lines = [
        "Migration Preview",
        "=================",
        "",
        f"Status: {'READY TO APPLY' if plan.get('valid') and plan.get('apply_ready') else 'BLOCKED' if plan.get('valid') else 'INVALID'}",
        f"Settings: {_counts_line(summary.get('settings'))}",
        f"Profiles: {_counts_line(summary.get('profiles'))}",
        f"History: {_counts_line(summary.get('history'))}",
        f"Manual / relink: {sum(item.get('disposition') == 'relink_required' for item in plan.get('actions', []) if isinstance(item, dict))}",
        f"Recovery items: {sum(item.get('disposition') == 'quarantine' for item in plan.get('actions', []) if isinstance(item, dict))}",
        f"Conflicts: {len(conflicts)}",
        f"Destructive actions: {destructive_action_count(plan)}",
        f"Restart required: {'yes' if plan.get('requires_restart') else 'no'}",
    ]
    errors = [item for item in plan.get("errors", []) if isinstance(item, dict)]
    if errors:
        lines.extend(("", "Errors:"))
        for error in errors:
            code = str(error.get("error_code") or "MIGRATION_ERROR")
            phase = f" [{error.get('phase')}]" if error.get("phase") else ""
            lines.append(f"- {code}{phase}: {error.get('safe_message') or 'Migration operation failed safely.'}")
            if error.get("logical_item"):
                lines.append(f"  item: {error['logical_item']}")
            if include_details and isinstance(error.get("diagnostics"), dict):
                safe_detail = ", ".join(
                    f"{key}={value}" for key, value in sorted(error["diagnostics"].items())
                    if key in {"errno", "operation", "logical_path", "transaction_id"}
                )
                if safe_detail:
                    lines.append(f"  technical details: {safe_detail}")
    warnings = [item for item in plan.get("warnings", []) if isinstance(item, dict)]
    if warnings:
        lines.extend(("", "Warnings:"))
        for warning in warnings:
            code = str(warning.get("error_code") or "MIGRATION_WARNING")
            phase = f" [{warning.get('phase')}]" if warning.get("phase") else ""
            lines.append(f"- {code}{phase}: {warning.get('safe_message') or 'Migration warning.'}")
            if warning.get("logical_item"):
                lines.append(f"  item: {warning['logical_item']}")
    if conflicts:
        lines.extend(("", "Conflicts:"))
        for action in conflicts:
            lines.append(f"- {action.get('action_id')}: {action.get('logical_item')} ({action.get('content_class')})")
            lines.append(f"  {action.get('safe_summary') or action.get('reason_code')}")
            lines.append("  choices: " + ", ".join(
                resolution_label(action, resolution)
                for resolution in action.get("allowed_resolutions") or []
            ))
            dependencies = action.get("dependencies") or []
            if dependencies:
                lines.append(f"  dependencies: {', '.join(str(item) for item in dependencies)}")
    if include_details:
        grouped: dict[str, list[dict[str, Any]]] = {"Settings": [], "Profiles": [], "History": [], "Manual / Recovery": []}
        for action in plan.get("actions", []):
            if not isinstance(action, dict):
                continue
            content = str(action.get("content_class") or "")
            target = "Settings" if content in {"settings", "settings_field", "profile_menu_metadata"} else (
                "Profiles" if "profile" in content else "History" if content == "setup_history" else "Manual / Recovery"
            )
            grouped[target].append(action)
        for heading, actions in grouped.items():
            if not actions:
                continue
            lines.extend(("", f"{heading} details:"))
            for action in actions:
                destination = action.get("destination") if isinstance(action.get("destination"), dict) else {}
                suffix = f" -> {destination.get('relative_path')}" if destination else ""
                lines.append(f"- {action.get('disposition')}: {action.get('logical_item')}{suffix}")
    return "\n".join(lines) + "\n"


def export_preview_text(summary: dict[str, Any], *, approximate_size: int) -> str:
    profiles = summary.get("profiles") if isinstance(summary.get("profiles"), dict) else {}
    history = summary.get("history") if isinstance(summary.get("history"), dict) else {}
    return "\n".join((
        "Migrate LVS State — Export Preview",
        "==================================",
        "",
        "PRIVATE — NOT PUBLIC-SAFE",
        f"Portable settings fields: {summary.get('settings', {}).get('portable_fields', 0)}",
        f"Setup history records: {history.get('valid_records', 0)}",
        f"Custom profiles: {profiles.get('custom_included', 0)}",
        f"Modified stock profiles: {profiles.get('modified_stock_included', 0)}",
        f"Unchanged stock profiles omitted: {profiles.get('stock_unchanged_omitted', 0)}",
        f"Recovery-only profiles: {profiles.get('recovery_only', 0)}",
        f"Approximate payload size: {format_size(approximate_size)}",
        "Excluded: results, archived profiles, sensor logs, credentials/secrets, hardware derived state.",
        "",
    ))


def successful_apply_text(plan: dict[str, Any]) -> str:
    summary = plan.get("summary") if isinstance(plan.get("summary"), dict) else {}
    return "\n".join((
        "Migration Applied Successfully",
        "==============================",
        "",
        f"Settings: {_counts_line(summary.get('settings'))}",
        f"Profiles: {_counts_line(summary.get('profiles'))}",
        f"History: {_counts_line(summary.get('history'))}",
        f"Recovery items: {sum(item.get('disposition') == 'quarantine' for item in plan.get('actions', []) if isinstance(item, dict))}",
        f"Relink requirements: {sum(item.get('disposition') == 'relink_required' for item in plan.get('actions', []) if isinstance(item, dict))}",
        "",
        "RESTART REQUIRED",
        "Restart LVS before configuring or starting another validation.",
        "",
    ))
