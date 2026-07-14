#!/usr/bin/env python3
"""Private local migration bundles and preview-first restore for LVS."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, fields
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any

from .lvs_core import APP_VERSION
from .lvs_local_environment_export import PublicSupportExporter
from .lvs_settings import GlobalSettings


MIGRATION_CONTRACT_ID = "linux_validation_suite.private_migration_bundle"
MIGRATION_CONTRACT_VERSION = 1
DEFAULT_BUNDLE_PARENT = Path("results") / "Migration_Bundles"
DEFAULT_STAGING_PARENT = Path("results") / "Migration_Restore_Staging"
MANIFEST_NAME = "migration_manifest.json"

SETTINGS_BUNDLE_PATH = "payload/settings/global_settings.json"
HISTORY_BUNDLE_PATH = "payload/settings/run_setup_history.json"
HARDWARE_STATE_BUNDLE_PATH = "payload/hardware_result_validation_state.json"
BUNDLE_TARGETS = {
    SETTINGS_BUNDLE_PATH: Path("settings/global_settings.json"),
    HISTORY_BUNDLE_PATH: Path("settings/run_setup_history.json"),
    HARDWARE_STATE_BUNDLE_PATH: Path("hardware_result_validation_state.json"),
}
SCAFFOLD_PATHS = (
    Path("settings/secrets"),
    Path("results"),
    Path("results/Archived"),
    Path("results/Uploaded"),
    Path("sensor_probe_logs"),
)


@dataclass(frozen=True)
class PrivateMigrationBundleResult:
    bundle_dir: Path
    manifest_path: Path
    manifest: dict[str, Any]
    summary_text: str


@dataclass(frozen=True)
class MigrationRestoreResult:
    valid: bool
    applied: bool
    plan: dict[str, Any]
    summary_text: str
    staging_dir: Path | None = None


def _read_json(path: Path) -> tuple[str, Any]:
    if path.is_symlink():
        return "symlink_rejected", None
    if not path.exists():
        return "missing", None
    if not path.is_file():
        return "unreadable", None
    try:
        return "readable", json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "unreadable", None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_private_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _unique_dir(parent: Path, prefix: str) -> Path:
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
    candidate = parent / f"{prefix}_{stamp}"
    suffix = 2
    while candidate.exists():
        candidate = parent / f"{prefix}_{stamp}_{suffix}"
        suffix += 1
    return candidate


def _relative_label(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return "custom_location_redacted"


def _portable_settings(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    allowed = {field.name for field in fields(GlobalSettings)}
    portable = {key: value for key, value in payload.items() if key in allowed}
    portable["runtime_environment"] = {}
    portable["google_drive_credentials_path"] = ""
    portable["google_drive_shared_drive_id"] = ""
    return portable


class LocalMigrationManager:
    """Create private bundles and restore them without overwriting local files."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path(__file__).resolve().parents[1]).resolve()
        self.support_exporter = PublicSupportExporter(self.root)

    def export_public_support(self, output_parent: Path | None = None):
        return self.support_exporter.export(output_parent)

    def create_private_bundle(
        self,
        *,
        acknowledge_private_data: bool,
        output_parent: Path | None = None,
    ) -> PrivateMigrationBundleResult:
        if not acknowledge_private_data:
            raise ValueError("private migration export requires explicit acknowledgement")

        parent = output_parent or (self.root / DEFAULT_BUNDLE_PARENT)
        if not parent.is_absolute():
            parent = self.root / parent
        bundle_dir = _unique_dir(parent, "Private_Migration_Bundle")
        bundle_dir.mkdir(parents=True, exist_ok=False)
        os.chmod(bundle_dir, 0o700)

        files: list[dict[str, Any]] = []
        source_status: dict[str, str] = {}

        settings_status, settings_payload = _read_json(self.root / "settings/global_settings.json")
        source_status["global_settings"] = settings_status
        portable_settings = _portable_settings(settings_payload) if settings_status == "readable" else None
        if portable_settings is not None:
            self._add_bundle_json(bundle_dir, SETTINGS_BUNDLE_PATH, portable_settings, "global_settings", files)

        history_status, history_payload = _read_json(self.root / "settings/run_setup_history.json")
        source_status["run_setup_history"] = history_status
        if history_status == "readable" and isinstance(history_payload, list):
            self._add_bundle_json(bundle_dir, HISTORY_BUNDLE_PATH, history_payload, "run_setup_history", files)
        elif history_status == "readable":
            source_status["run_setup_history"] = "unreadable"

        state_status, state_payload = _read_json(self.root / "hardware_result_validation_state.json")
        source_status["hardware_result_validation_state"] = state_status
        if state_status == "readable" and isinstance(state_payload, dict):
            self._add_bundle_json(
                bundle_dir,
                HARDWARE_STATE_BUNDLE_PATH,
                state_payload,
                "hardware_result_validation_state",
                files,
            )
        elif state_status == "readable":
            source_status["hardware_result_validation_state"] = "unreadable"

        manifest = {
            "contract_id": MIGRATION_CONTRACT_ID,
            "contract_version": MIGRATION_CONTRACT_VERSION,
            "kind": "private_local_migration_bundle",
            "suite_version": APP_VERSION,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "private_bundle": True,
            "safe_to_share_publicly": False,
            "warning": "This bundle may contain private local settings, history, and retained-result mappings.",
            "files": files,
            "source_status": source_status,
            "scaffolds": [path.as_posix() for path in SCAFFOLD_PATHS],
            "excluded": [
                "Google credential files and secrets",
                "Google credential paths and shared-drive IDs",
                "runtime environment overrides",
                "actual result contents",
                "sensor-log contents",
                "vendor and test data",
                ".venv",
                "caches and generated artifacts",
            ],
            "manual_restore_required": [
                "Google Drive credentials and identifiers",
                "runtime environment overrides",
                "retained results if hardware matrix mappings should remain usable",
            ],
        }
        manifest_path = bundle_dir / MANIFEST_NAME
        _write_private_json(manifest_path, manifest)
        for directory in (path for path in bundle_dir.rglob("*") if path.is_dir() and not path.is_symlink()):
            os.chmod(directory, 0o700)
        summary = self.private_bundle_summary(manifest, _relative_label(self.root, bundle_dir))
        return PrivateMigrationBundleResult(bundle_dir, manifest_path, manifest, summary)

    def _add_bundle_json(
        self,
        bundle_dir: Path,
        bundle_path: str,
        payload: Any,
        logical_name: str,
        files: list[dict[str, Any]],
    ) -> None:
        destination = bundle_dir / bundle_path
        _write_private_json(destination, payload)
        files.append(
            {
                "logical_name": logical_name,
                "bundle_path": bundle_path,
                "target_path": BUNDLE_TARGETS[bundle_path].as_posix(),
                "sha256": _sha256(destination),
                "size_bytes": destination.stat().st_size,
                "private": True,
            }
        )

    def private_bundle_summary(self, manifest: dict[str, Any], bundle_label: str) -> str:
        statuses = manifest.get("source_status", {})
        return "\n".join(
            [
                "Private Migration Bundle",
                "========================",
                "",
                "NOT PUBLIC-SAFE. This bundle may contain private local configuration and history.",
                "Google credentials, Google identifiers, results, sensor logs, vendor data, and .venv were excluded.",
                f"Included files: {len(manifest.get('files', []))}",
                f"Global settings source: {statuses.get('global_settings', 'missing')}",
                f"Run setup history source: {statuses.get('run_setup_history', 'missing')}",
                f"Hardware matrix state source: {statuses.get('hardware_result_validation_state', 'missing')}",
                f"Bundle folder: {bundle_label}",
                f"Manifest: {MANIFEST_NAME}",
                "",
            ]
        )

    def preview_restore(self, bundle_dir: Path) -> MigrationRestoreResult:
        bundle = bundle_dir.expanduser().absolute()
        validation = self._validate_bundle(bundle)
        if validation["errors"]:
            plan = {
                "kind": "migration_restore_plan",
                "valid": False,
                "preview_only": True,
                "errors": validation["errors"],
                "warnings": validation["warnings"],
                "actions": [],
            }
            return MigrationRestoreResult(False, False, plan, self.restore_summary(plan))

        manifest = validation["manifest"]
        included = {item["bundle_path"]: item for item in manifest["files"]}
        actions: list[dict[str, str]] = []
        errors: list[str] = []

        for relative in (*SCAFFOLD_PATHS, *BUNDLE_TARGETS.values()):
            if not self._target_path_safe(relative):
                errors.append(f"restore target contains an unsafe symlink: {relative.as_posix()}")

        for relative in SCAFFOLD_PATHS:
            target = self.root / relative
            if target.exists() and not target.is_dir():
                errors.append(f"scaffold target is not a directory: {relative.as_posix()}")
            elif target.is_dir():
                actions.append({"action": "skip_existing", "target": relative.as_posix(), "reason": "directory exists"})
            else:
                actions.append({"action": "create_scaffold", "target": relative.as_posix(), "reason": "directory missing"})

        self._plan_settings_restore(bundle, included, actions)
        self._plan_optional_file_restore(bundle, included, HISTORY_BUNDLE_PATH, actions)
        self._plan_hardware_state_restore(bundle, included, actions)
        actions.extend(
            [
                {
                    "action": "manual_restore_required",
                    "target": "settings/secrets/google-credentials.json",
                    "reason": "Google credentials are never included in v1 bundles",
                },
                {
                    "action": "manual_restore_required",
                    "target": "Google Drive settings",
                    "reason": "Google paths and identifiers are removed from bundled settings",
                },
                {
                    "action": "skip_not_in_bundle",
                    "target": "results and sensor log contents",
                    "reason": "v1 restores folder scaffolding only",
                },
            ]
        )
        plan = {
            "kind": "migration_restore_plan",
            "valid": not errors,
            "preview_only": True,
            "bundle_contract_version": manifest["contract_version"],
            "errors": errors,
            "warnings": validation["warnings"],
            "actions": actions,
        }
        return MigrationRestoreResult(not errors, False, plan, self.restore_summary(plan))

    def _target_path_safe(self, relative: Path) -> bool:
        if relative.is_absolute() or ".." in relative.parts:
            return False
        current = self.root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return False
        return True

    def _plan_settings_restore(
        self,
        bundle: Path,
        included: dict[str, dict[str, Any]],
        actions: list[dict[str, str]],
    ) -> None:
        target = BUNDLE_TARGETS[SETTINGS_BUNDLE_PATH]
        if SETTINGS_BUNDLE_PATH in included:
            action = "stage_for_manual_merge" if (self.root / target).exists() else "restore"
            reason = "destination exists; it will not be overwritten" if action.startswith("stage") else "destination missing"
            actions.append({"action": action, "target": target.as_posix(), "source": SETTINGS_BUNDLE_PATH, "reason": reason})
            return
        example = self.root / "settings/global_settings.example.json"
        if (self.root / target).exists():
            actions.append({"action": "skip_existing", "target": target.as_posix(), "reason": "destination exists"})
        elif example.is_file() and not example.is_symlink():
            actions.append(
                {
                    "action": "create_from_example",
                    "target": target.as_posix(),
                    "source": "settings/global_settings.example.json",
                    "reason": "private settings were not included",
                }
            )
        else:
            actions.append(
                {
                    "action": "manual_restore_required",
                    "target": target.as_posix(),
                    "reason": "no bundled settings or readable committed example",
                }
            )

    def _plan_optional_file_restore(
        self,
        bundle: Path,
        included: dict[str, dict[str, Any]],
        bundle_path: str,
        actions: list[dict[str, str]],
    ) -> None:
        target = BUNDLE_TARGETS[bundle_path]
        if bundle_path not in included:
            actions.append({"action": "skip_not_in_bundle", "target": target.as_posix(), "reason": "optional source missing"})
            return
        action = "stage_for_manual_merge" if (self.root / target).exists() else "restore"
        reason = "destination exists; it will not be overwritten" if action.startswith("stage") else "destination missing"
        actions.append({"action": action, "target": target.as_posix(), "source": bundle_path, "reason": reason})

    def _plan_hardware_state_restore(
        self,
        bundle: Path,
        included: dict[str, dict[str, Any]],
        actions: list[dict[str, str]],
    ) -> None:
        target = BUNDLE_TARGETS[HARDWARE_STATE_BUNDLE_PATH]
        if HARDWARE_STATE_BUNDLE_PATH not in included:
            actions.append(
                {
                    "action": "skip_not_in_bundle",
                    "target": target.as_posix(),
                    "reason": "optional state missing; rebuild after retained results are transferred",
                }
            )
            return
        if (self.root / target).exists():
            action = "stage_for_manual_merge"
            reason = "destination exists; it will not be overwritten"
        elif self._hardware_state_paths_available(bundle / HARDWARE_STATE_BUNDLE_PATH):
            action = "restore"
            reason = "destination missing and referenced result paths are available"
        else:
            action = "stage_for_manual_merge"
            reason = "referenced result paths are unavailable; review or rebuild state"
        actions.append({"action": action, "target": target.as_posix(), "source": HARDWARE_STATE_BUNDLE_PATH, "reason": reason})

    def _hardware_state_paths_available(self, state_path: Path) -> bool:
        status, payload = _read_json(state_path)
        if status != "readable" or not isinstance(payload, dict):
            return False
        entries = payload.get("entries", [])
        if not isinstance(entries, list):
            return False
        for entry in entries:
            if not isinstance(entry, dict) or str(entry.get("status") or "missing") not in {
                "confirmed",
                "available",
                "candidate",
            }:
                continue
            raw_path = str(entry.get("path") or "")
            relative = Path(raw_path)
            if not raw_path or relative.is_absolute() or ".." in relative.parts:
                return False
            candidate = (self.root / relative).resolve()
            try:
                candidate.relative_to(self.root)
            except ValueError:
                return False
            if not candidate.is_dir():
                return False
        return True

    def _validate_bundle(self, bundle: Path) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        if bundle.is_symlink():
            errors.append("bundle directory must not be a symlink")
            return {"errors": errors, "warnings": warnings, "manifest": {}}
        if not bundle.is_dir():
            errors.append("bundle directory is missing")
            return {"errors": errors, "warnings": warnings, "manifest": {}}
        try:
            if any(path.is_symlink() for path in bundle.rglob("*")):
                errors.append("bundle contains a symlink")
        except OSError:
            errors.append("bundle contents are unreadable")

        status, manifest = _read_json(bundle / MANIFEST_NAME)
        if status != "readable" or not isinstance(manifest, dict):
            errors.append("migration manifest is missing or unreadable")
            return {"errors": errors, "warnings": warnings, "manifest": {}}
        if manifest.get("contract_id") != MIGRATION_CONTRACT_ID:
            errors.append("migration manifest contract is invalid")
        if manifest.get("contract_version") != MIGRATION_CONTRACT_VERSION:
            errors.append("migration manifest version is unsupported")
        if manifest.get("kind") != "private_local_migration_bundle":
            errors.append("migration manifest kind is invalid")
        if manifest.get("safe_to_share_publicly") is not False:
            errors.append("migration manifest private safety marker is invalid")

        file_entries = manifest.get("files")
        if not isinstance(file_entries, list):
            errors.append("migration manifest files list is invalid")
            file_entries = []
        listed: set[str] = set()
        for entry in file_entries:
            if not isinstance(entry, dict):
                errors.append("migration manifest contains an invalid file entry")
                continue
            bundle_path = str(entry.get("bundle_path") or "")
            if bundle_path in listed:
                errors.append("migration manifest contains a duplicate payload path")
                continue
            listed.add(bundle_path)
            if bundle_path not in BUNDLE_TARGETS:
                errors.append("migration payload path is not allowed")
                continue
            if str(entry.get("target_path") or "") != BUNDLE_TARGETS[bundle_path].as_posix():
                errors.append("migration target path is invalid")
            source = bundle / bundle_path
            try:
                source.resolve().relative_to(bundle)
            except ValueError:
                errors.append("migration payload escapes bundle")
                continue
            if source.is_symlink() or not source.is_file():
                errors.append("migration payload is missing or unsafe")
                continue
            try:
                if int(entry.get("size_bytes", -1)) != source.stat().st_size:
                    errors.append("migration payload size mismatch")
                if str(entry.get("sha256") or "") != _sha256(source):
                    errors.append("migration payload checksum mismatch")
            except (OSError, TypeError, ValueError):
                errors.append("migration payload cannot be verified")

        try:
            actual_files: set[str] = set()
            for path in bundle.rglob("*"):
                if path.is_symlink():
                    continue
                if path.is_file():
                    actual_files.add(path.relative_to(bundle).as_posix())
                elif not path.is_dir():
                    errors.append("migration bundle contains an unsupported entry")
            expected_files = {MANIFEST_NAME, *listed}
            if actual_files - expected_files:
                errors.append("migration bundle contains an unlisted file")
        except OSError:
            errors.append("migration payload inventory is unreadable")
        return {"errors": errors, "warnings": warnings, "manifest": manifest}

    def apply_restore(self, bundle_dir: Path, *, yes: bool) -> MigrationRestoreResult:
        preview = self.preview_restore(bundle_dir)
        if not preview.valid:
            return preview
        if not yes:
            plan = dict(preview.plan)
            plan["errors"] = [*plan.get("errors", []), "explicit --yes confirmation is required for apply"]
            plan["valid"] = False
            return MigrationRestoreResult(False, False, plan, self.restore_summary(plan))

        bundle = bundle_dir.expanduser().absolute()
        staging_dir: Path | None = None
        applied_actions: list[dict[str, str]] = []
        errors: list[str] = []
        writes_performed = False
        for action in preview.plan["actions"]:
            kind = action["action"]
            relative = Path(action["target"])
            target = self.root / relative
            try:
                if kind == "create_scaffold":
                    if target.exists():
                        if not target.is_dir():
                            raise OSError("target exists and is not a directory")
                    else:
                        target.mkdir(parents=True, exist_ok=False)
                        writes_performed = True
                    applied_actions.append({**action, "result": "created"})
                elif kind in {"restore", "create_from_example"}:
                    source = bundle / action["source"] if kind == "restore" else self.root / action["source"]
                    try:
                        self._copy_exclusive(source, target)
                        writes_performed = True
                        applied_actions.append({**action, "result": "restored"})
                    except FileExistsError:
                        if staging_dir is None:
                            staging_dir = self._create_staging_dir()
                            writes_performed = True
                        staged = staging_dir / relative
                        self._copy_exclusive(source, staged)
                        writes_performed = True
                        applied_actions.append(
                            {
                                **action,
                                "action": "stage_for_manual_merge",
                                "result": "staged_after_conflict",
                                "staged_path": _relative_label(self.root, staged),
                            }
                        )
                elif kind == "stage_for_manual_merge":
                    if staging_dir is None:
                        staging_dir = self._create_staging_dir()
                        writes_performed = True
                    staged = staging_dir / relative
                    self._copy_exclusive(bundle / action["source"], staged)
                    writes_performed = True
                    applied_actions.append(
                        {**action, "result": "staged", "staged_path": _relative_label(self.root, staged)}
                    )
                else:
                    applied_actions.append({**action, "result": "no_write"})
            except OSError:
                errors.append(f"unable to apply migration action for {relative.as_posix()}")

        plan = {
            **preview.plan,
            "valid": not errors,
            "preview_only": False,
            "applied": not errors,
            "writes_performed": writes_performed,
            "errors": errors,
            "actions": applied_actions,
            "staging_folder": _relative_label(self.root, staging_dir) if staging_dir is not None else "none",
        }
        return MigrationRestoreResult(
            not errors,
            not errors,
            plan,
            self.restore_summary(plan),
            staging_dir,
        )

    def _copy_exclusive(self, source: Path, target: Path) -> None:
        if source.is_symlink() or not source.is_file():
            raise OSError("unsafe source")
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as source_stream, target.open("xb") as target_stream:
            shutil.copyfileobj(source_stream, target_stream)
        os.chmod(target, 0o600)

    def _create_staging_dir(self) -> Path:
        parent = self.root / DEFAULT_STAGING_PARENT
        staging = _unique_dir(parent, "Migration_Restore_Conflicts")
        staging.mkdir(parents=True, exist_ok=False)
        os.chmod(staging, 0o700)
        return staging

    def restore_summary(self, plan: dict[str, Any]) -> str:
        actions = plan.get("actions", [])
        action_counts: dict[str, int] = {}
        for action in actions:
            name = str(action.get("action") or "unknown")
            action_counts[name] = action_counts.get(name, 0) + 1
        conflicts = action_counts.get("stage_for_manual_merge", 0)
        manual_actions = action_counts.get("manual_restore_required", 0)
        lines = [
            "Migration Restore " + ("Preview" if plan.get("preview_only", True) else "Apply Result"),
            "=========================",
            "",
            f"Bundle valid: {'yes' if plan.get('valid') else 'no'}",
            f"Writes performed: {'yes' if plan.get('writes_performed') else 'no'}",
            "Action counts: "
            + (", ".join(f"{name}={count}" for name, count in sorted(action_counts.items())) or "none"),
            f"Conflicts requiring staging: {conflicts}",
            f"Manual actions: {manual_actions}",
            f"Staging folder: {plan.get('staging_folder', 'created on apply when conflicts exist')}",
        ]
        for error in plan.get("errors", []):
            lines.append(f"ERROR: {error}")
        for warning in plan.get("warnings", []):
            lines.append(f"WARNING: {warning}")
        lines.append("")
        lines.append("Actions:")
        for action in actions:
            lines.append(
                f"- {action.get('action')}: {action.get('target')} — {action.get('reason', action.get('result', ''))}"
            )
            if action.get("staged_path"):
                lines.append(f"  staged: {action['staged_path']}")
        lines.extend(
            [
                "",
                "Google credentials and identifiers require manual restoration.",
                "Existing destination files are never overwritten.",
                "",
            ]
        )
        return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LVS public support export and private local migration helper.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)

    support = subparsers.add_parser("support-export", help="Write a public-safe, redacted support summary.")
    support.add_argument("--output-dir", type=Path)

    private = subparsers.add_parser("migration-export", help="Write a private migration bundle without secrets.")
    private.add_argument("--acknowledge-private-data", action="store_true")
    private.add_argument("--output-dir", type=Path)

    restore = subparsers.add_parser("restore", help="Preview or apply a validated migration restore.")
    restore.add_argument("bundle", type=Path)
    restore.add_argument("--apply", action="store_true")
    restore.add_argument("--yes", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manager = LocalMigrationManager(args.root)
    try:
        if args.command == "support-export":
            result = manager.export_public_support(args.output_dir)
            print(result.summary_text, end="")
            return 0
        if args.command == "migration-export":
            if not args.acknowledge_private_data:
                print("Private migration export requires --acknowledge-private-data.", file=sys.stderr)
                return 2
            result = manager.create_private_bundle(
                acknowledge_private_data=True,
                output_parent=args.output_dir,
            )
            print(result.summary_text, end="")
            return 0
        if args.yes and not args.apply:
            print("--yes is only valid with --apply.", file=sys.stderr)
            return 2
        if args.apply and not args.yes:
            print("Noninteractive restore apply requires both --apply and --yes.", file=sys.stderr)
            return 2
        result = manager.apply_restore(args.bundle, yes=True) if args.apply else manager.preview_restore(args.bundle)
        print(result.summary_text, end="")
        return 0 if result.valid else 1
    except (OSError, ValueError):
        print("Migration operation failed without exposing private file details.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
