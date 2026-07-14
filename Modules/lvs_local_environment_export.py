#!/usr/bin/env python3
"""Public-safe local environment support summary and recommendations."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, fields
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from urllib.parse import urlparse

from .lvs_settings import GlobalSettings


EXPORT_CONTRACT_ID = "linux_validation_suite.local_environment_export"
EXPORT_CONTRACT_VERSION = 1
DEFAULT_EXPORT_PARENT = Path("results") / "Support_Exports"
DEFAULT_CREDENTIAL_PATH = Path("settings") / "secrets" / "google-credentials.json"
PUBLIC_GIT_HOSTS = {"github.com", "gitlab.com", "codeberg.org"}
PUBLIC_SAFE_SETTING_KEYS = {
    "abort_on_fail_threshold",
    "abort_on_system_fault",
    "abort_on_worker_error",
    "abort_run_on_stage_abort",
    "environment_mode",
    "export_compatibility_json",
    "export_extended_json",
    "google_drive_move_to_uploaded_on_success",
    "google_drive_prompt_after_run",
    "gpu_external_max_processes",
    "gpu_internal_ramp_step_seconds",
    "gpu_max_retunes_per_worker",
    "gpu_retune_cooldown_seconds",
    "gpu_retune_warmup_seconds",
    "gpu_safe_max_load_scale",
    "gpu_safe_max_tuning_step",
    "gpu_safe_max_vram_percent",
    "gpu_safe_mode",
    "gpu_safe_start_load_fraction",
    "keep_raw_telemetry",
    "privileged_helper_enabled",
    "privileged_helper_prompt_for_sudo",
    "prompt_for_wall_wattage",
    "sample_interval_seconds",
    "strict_threshold_recommendation_warnings",
    "target_gpu_busy_min_percent",
    "target_gpu_busy_sustain_seconds",
    "target_gpu_memory_busy_min_percent",
    "target_gpu_memory_busy_sustain_seconds",
    "trim_end_seconds",
    "trim_start_seconds",
}


@dataclass(frozen=True)
class PublicSupportExportResult:
    report_dir: Path
    json_path: Path
    summary_path: Path
    payload: dict[str, Any]
    summary_text: str


def _read_json(path: Path) -> tuple[str, Any]:
    if not path.exists():
        return "missing", None
    if not path.is_file():
        return "unreadable", None
    try:
        return "readable", json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "unreadable", None


def _private_file_status(path: Path) -> str:
    if not path.exists():
        return "missing"
    if not path.is_file():
        return "unreadable"
    try:
        with path.open("rb"):
            pass
    except OSError:
        return "unreadable"
    return "readable"


def _directory_count(path: Path, *, excluded_names: set[str] | None = None) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "directory_count": 0}
    if not path.is_dir():
        return {"status": "unreadable", "directory_count": 0}
    excluded = excluded_names or set()
    try:
        count = sum(1 for item in path.iterdir() if item.is_dir() and item.name not in excluded)
    except OSError:
        return {"status": "unreadable", "directory_count": 0}
    return {"status": "present", "directory_count": count}


def _recursive_file_count(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "file_count": 0}
    if not path.is_dir():
        return {"status": "unreadable", "file_count": 0}
    try:
        count = sum(1 for item in path.rglob("*") if item.is_file())
    except OSError:
        return {"status": "unreadable", "file_count": 0}
    return {"status": "present", "file_count": count}


def _resolve_configured_path(root: Path, raw_path: object, fallback: Path) -> tuple[Path, str, bool]:
    value = str(raw_path or "").strip()
    if not value:
        return root / fallback, "not_configured", False
    configured = Path(value).expanduser()
    kind = "custom_absolute" if configured.is_absolute() else "custom_relative"
    if configured == fallback:
        kind = "default"
    resolved = configured if configured.is_absolute() else root / configured
    return resolved, kind, True


def _settings_summary(status: str, payload: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {"status": status}
    if status != "readable" or not isinstance(payload, dict):
        if status == "readable":
            summary["status"] = "unreadable"
        return summary
    recognized = {field.name for field in fields(GlobalSettings)}
    keys = {str(key) for key in payload}
    environment_mode = str(payload.get("environment_mode") or "").strip().lower()
    summary["public_safe_key_summary"] = {
        "key_count": len(keys),
        "recognized_key_count": len(keys & recognized),
        "unrecognized_key_count": len(keys - recognized),
        "safe_keys_present": sorted(keys & PUBLIC_SAFE_SETTING_KEYS),
        "environment_mode": environment_mode if environment_mode in {"production", "end_user"} else "custom",
        "runtime_environment_key_count": len(payload.get("runtime_environment", {}))
        if isinstance(payload.get("runtime_environment"), dict)
        else 0,
        "case_option_count": len(payload.get("case_options", [])) if isinstance(payload.get("case_options"), list) else 0,
        "psu_rating_option_count": len(payload.get("psu_rating_options", []))
        if isinstance(payload.get("psu_rating_options"), list)
        else 0,
        "cpu_cooler_option_count": len(payload.get("cpu_cooler_options", []))
        if isinstance(payload.get("cpu_cooler_options"), list)
        else 0,
    }
    return summary


def _history_summary(path: Path) -> dict[str, Any]:
    status, payload = _read_json(path)
    if status == "readable" and not isinstance(payload, list):
        status = "unreadable"
    return {
        "status": status,
        "entry_count": len(payload) if status == "readable" else 0,
    }


def _hardware_state_summary(path: Path) -> dict[str, Any]:
    status, payload = _read_json(path)
    if status == "readable" and not isinstance(payload, dict):
        status = "unreadable"
    entries = payload.get("entries", []) if status == "readable" else []
    if not isinstance(entries, list):
        return {"status": "unreadable", "category_count": 0, "status_counts": {}}
    counts = {"confirmed": 0, "candidate": 0, "missing": 0, "stale": 0, "other": 0}
    categories = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        categories += 1
        entry_status = str(entry.get("status") or "missing").lower()
        if entry_status == "available":
            entry_status = "confirmed"
        counts[entry_status if entry_status in counts else "other"] += 1
    return {
        "status": status,
        "category_count": categories,
        "status_counts": counts,
        "local_result_paths_exported": False,
    }


def _venv_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "python_version": "unavailable"}
    if not path.is_dir():
        return {"status": "unreadable", "python_version": "unavailable"}
    version = "unavailable"
    try:
        for line in (path / "pyvenv.cfg").read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip().lower() == "version":
                match = re.fullmatch(r"\s*(\d+\.\d+(?:\.\d+)?)\s*", value)
                if match:
                    version = match.group(1)
                break
    except (OSError, UnicodeError):
        pass
    return {"status": "present", "python_version": version}


def _git_value(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ("git", "-C", str(root), *args),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _redacted_origin_host(origin: str) -> str:
    value = str(origin or "").strip()
    if not value:
        return "not_configured"
    if value.startswith(("/", "./", "../", "file:")):
        return "local_redacted"
    parsed = urlparse(value)
    host = parsed.hostname or ""
    if not host and ":" in value:
        host = value.split(":", 1)[0].rsplit("@", 1)[-1]
    normalized = host.lower()
    return normalized if normalized in PUBLIC_GIT_HOSTS else "other_redacted"


def _repo_summary(root: Path) -> dict[str, Any]:
    inside = _git_value(root, "rev-parse", "--is-inside-work-tree") == "true"
    if not inside:
        return {"status": "not_a_git_worktree"}
    branch = _git_value(root, "branch", "--show-current")
    branch_summary = branch if branch in {"main", "master"} else ("detached" if not branch else "non_default_redacted")
    origin = _git_value(root, "config", "--get", "remote.origin.url")
    changes = bool(_git_value(root, "status", "--porcelain"))
    return {
        "status": "available",
        "branch": branch_summary,
        "working_tree": "changes_present" if changes else "clean",
        "origin_configured": bool(origin),
        "origin_host": _redacted_origin_host(origin),
        "origin_url_exported": False,
    }


def _safe_output_label(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return "custom_output_location_redacted"


def _unique_report_dir(parent: Path, stamp: str) -> Path:
    candidate = parent / f"Public_Support_Export_{stamp}"
    suffix = 2
    while candidate.exists():
        candidate = parent / f"Public_Support_Export_{stamp}_{suffix}"
        suffix += 1
    return candidate


class PublicSupportExporter:
    """Collect and write a share-safe support summary without private data."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path(__file__).resolve().parents[1]).resolve()

    def build_payload(self) -> dict[str, Any]:
        root = self.root
        settings_path = root / "settings" / "global_settings.json"
        settings_status, settings_payload = _read_json(settings_path)
        settings = settings_payload if settings_status == "readable" and isinstance(settings_payload, dict) else {}

        configured_credentials, credential_kind, credential_configured = _resolve_configured_path(
            root,
            settings.get("google_drive_credentials_path"),
            DEFAULT_CREDENTIAL_PATH,
        )
        configured_results, results_kind, _results_configured = _resolve_configured_path(
            root,
            settings.get("results_dir") or "results",
            Path("results"),
        )
        shared_drive_configured = bool(str(settings.get("google_drive_shared_drive_id") or "").strip())

        payload: dict[str, Any] = {
            "contract_id": EXPORT_CONTRACT_ID,
            "contract_version": EXPORT_CONTRACT_VERSION,
            "kind": "public_safe_local_environment_summary",
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "safety": {
                "safe_to_share_by_default": True,
                "secret_contents_exported": False,
                "private_identifiers_exported": False,
                "local_result_paths_exported": False,
                "note": "This is a setup summary, not a backup of secrets or retained results.",
            },
            "settings": {
                "global_settings": _settings_summary(settings_status, settings_payload),
                "global_settings_example": {
                    "status": "present" if (root / "settings" / "global_settings.example.json").is_file() else "missing"
                },
                "run_setup_history": _history_summary(root / "settings" / "run_setup_history.json"),
            },
            "google_drive": {
                "configured": credential_configured or shared_drive_configured,
                "credential_path_configured": credential_configured,
                "credential_path_kind": credential_kind,
                "configured_credential_status": _private_file_status(configured_credentials),
                "default_credential_status": _private_file_status(root / DEFAULT_CREDENTIAL_PATH),
                "legacy_credential_status": _private_file_status(root / "Files" / "google-credentials.json"),
                "shared_drive_id_configured": shared_drive_configured,
                "shared_drive_id": "redacted" if shared_drive_configured else "not_configured",
            },
            "results": {
                "configured_location_kind": results_kind,
                "active": _directory_count(
                    configured_results,
                    excluded_names={
                        "Archived",
                        "Uploaded",
                        "Support_Exports",
                        "Migration_Bundles",
                        "Migration_Restore_Staging",
                    },
                ),
                "archived": _directory_count(configured_results / "Archived"),
                "uploaded": _directory_count(configured_results / "Uploaded"),
            },
            "hardware_result_validation_state": _hardware_state_summary(
                root / "hardware_result_validation_state.json"
            ),
            "sensor_probe_logs": _recursive_file_count(root / "sensor_probe_logs"),
            "virtual_environment": _venv_summary(root / ".venv"),
            "optional_local_tools": {
                "vendor_source_tree": {
                    "status": "present" if (root / "Files" / "OCCT C# Beta 8a").exists() else "missing"
                },
                "vendor_test_data": {
                    "status": "present" if (root / "Files" / "OCCT Test Data").exists() else "missing"
                },
                "external_tool_installation": {
                    "status": "present" if (root / "OCCT 16.1.8").exists() else "missing"
                },
            },
            "repository": _repo_summary(root),
        }
        payload["restore_recommendations"] = self.restore_recommendations(payload)
        return payload

    def restore_recommendations(self, payload: dict[str, Any]) -> list[dict[str, str]]:
        settings_status = payload["settings"]["global_settings"]["status"]
        hardware_status = payload["hardware_result_validation_state"]["status"]
        recommendations: list[dict[str, str]] = []
        if settings_status == "missing":
            recommendations.append(
                {
                    "area": "settings",
                    "action": "recreate_from_example",
                    "detail": "Create global_settings.json from the committed example or restore a reviewed private bundle.",
                }
            )
        elif settings_status == "unreadable":
            recommendations.append(
                {
                    "area": "settings",
                    "action": "manual_review",
                    "detail": "Review the unreadable local settings file before migration.",
                }
            )
        if hardware_status == "readable":
            recommendations.append(
                {
                    "area": "hardware_matrix_state",
                    "action": "rebuild_after_result_transfer",
                    "detail": "Restore only after retained results are transferred, or rebuild mappings on the destination.",
                }
            )
        else:
            recommendations.append(
                {
                    "area": "hardware_matrix_state",
                    "action": "optional_rebuild",
                    "detail": "No local state is required; rebuild it later if retained results are transferred.",
                }
            )
        recommendations.extend(
            [
                {
                    "area": "google_drive",
                    "action": "manual_restore_required",
                    "detail": "Reconfigure Google Drive identifiers and credentials manually on the destination.",
                },
                {
                    "area": "virtual_environment",
                    "action": "recreate",
                    "detail": "Run scripts/setup_venv.sh on the destination; do not transfer .venv.",
                },
                {
                    "area": "local_folders",
                    "action": "recreate_scaffolds",
                    "detail": "Restore can recreate results and sensor-log folder scaffolding without their contents.",
                },
            ]
        )
        return recommendations

    def summary_text(self, payload: dict[str, Any], output_label: str) -> str:
        settings = payload["settings"]
        drive = payload["google_drive"]
        results = payload["results"]
        hardware = payload["hardware_result_validation_state"]
        hardware_counts = hardware["status_counts"]
        logs = payload["sensor_probe_logs"]
        venv = payload["virtual_environment"]
        repository = payload["repository"]
        tools = payload["optional_local_tools"]
        recommendations = payload["restore_recommendations"]
        lines = [
            "Public-safe Support Summary",
            "===========================",
            "",
            "Safe-to-share setup summary only. This is not a secret, credential, settings, or result backup.",
            "",
            f"Global settings: {settings['global_settings']['status']}",
            f"Settings example: {settings['global_settings_example']['status']}",
            f"Run setup history: {settings['run_setup_history']['status']} ({settings['run_setup_history']['entry_count']} entries)",
            "Google Drive: " + ("configured (identifiers redacted)" if drive["configured"] else "not configured"),
            f"Configured Google credential file: {drive['configured_credential_status']} (contents not read or exported)",
            f"Results: active={results['active']['directory_count']}, archived={results['archived']['directory_count']}, uploaded={results['uploaded']['directory_count']}",
            "Hardware matrix state: "
            f"{hardware['status']} ({hardware['category_count']} categories; "
            f"confirmed={hardware_counts.get('confirmed', 0)}, candidate={hardware_counts.get('candidate', 0)}, "
            f"missing={hardware_counts.get('missing', 0)}, stale={hardware_counts.get('stale', 0)}; paths not exported)",
            f"Sensor probe logs: {logs['status']} ({logs['file_count']} files)",
            f"Repo-local virtual environment: {venv['status']} (Python {venv['python_version']})",
            "Optional local tools: "
            + ", ".join(f"{label}={value['status']}" for label, value in tools.items()),
            f"Repository: {repository.get('status', 'unavailable')}; branch={repository.get('branch', 'unavailable')}; origin={repository.get('origin_host', 'unavailable')}",
            "",
            "Intentionally omitted: credential contents, tokens, IDs, private setting values, history entries, retained-result paths, and origin URL.",
            "",
            "Restore recommendations:",
            *(f"- {item['area']}: {item['detail']}" for item in recommendations),
            f"Export folder: {output_label}",
            "Files: public_support_summary.json, public_support_summary.txt",
            "",
        ]
        return "\n".join(lines)

    def export(self, output_parent: Path | None = None) -> PublicSupportExportResult:
        parent = output_parent or (self.root / DEFAULT_EXPORT_PARENT)
        if not parent.is_absolute():
            parent = self.root / parent
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
        report_dir = _unique_report_dir(parent, stamp)
        payload = self.build_payload()
        report_dir.mkdir(parents=True, exist_ok=False)
        output_label = _safe_output_label(self.root, report_dir)
        payload["output"] = {
            "folder": output_label,
            "json": "public_support_summary.json",
            "text": "public_support_summary.txt",
        }
        text = self.summary_text(payload, output_label)
        json_path = report_dir / "public_support_summary.json"
        summary_path = report_dir / "public_support_summary.txt"
        json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        summary_path.write_text(text, encoding="utf-8")
        return PublicSupportExportResult(report_dir, json_path, summary_path, payload, text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write a public-safe LVS local environment support summary.")
    parser.add_argument("command", choices=("support-export",))
    parser.add_argument("--output-dir", type=Path, help="Optional export parent; paths are redacted outside the repo.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        result = PublicSupportExporter(args.root).export(args.output_dir)
    except OSError:
        print("Local environment export failed: unable to write the support bundle.", file=sys.stderr)
        return 1
    print(result.summary_text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
