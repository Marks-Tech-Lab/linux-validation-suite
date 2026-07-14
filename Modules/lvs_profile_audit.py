#!/usr/bin/env python3
"""Profile audit payload construction."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List

from .lvs_core import APP_NAME, APP_VERSION, now_local_iso


class ProfileAuditPayloadBuilder:
    """Build profile audit payloads without report writing or UI behavior."""

    def __init__(self, profile_loader: Any) -> None:
        self.profile_loader = profile_loader

    def profile_audit_payload(
        self,
        dry_run_builder: Callable[[Path, Any, List[str]], Dict[str, Any]],
    ) -> Dict[str, Any]:
        profiles = self.profile_loader.list_profiles()
        items: List[Dict[str, Any]] = []
        for profile_path in profiles:
            items.append(self.profile_audit_payload_item(profile_path, dry_run_builder))
        runnable_count = sum(1 for item in items if bool(item.get("runnable")))
        blocked_count = sum(1 for item in items if not bool(item.get("runnable")))
        error_count = sum(int(item.get("validation_error_count") or 0) for item in items)
        warning_count = sum(int(item.get("validation_warning_count") or 0) for item in items)
        return {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "kind": "profile_audit",
            "started": now_local_iso(),
            "profiles_dir": str(self.profile_loader.profiles_dir),
            "counts": {
                "profiles": len(items),
                "runnable": runnable_count,
                "blocked": blocked_count,
                "validation_errors": error_count,
                "validation_warnings": warning_count,
            },
            "profiles": items,
            "ended": now_local_iso(),
        }

    def legacy_profile_audit_payload(self, validator: Any) -> Dict[str, Any]:
        profiles = self.profile_loader.list_profiles()
        items: List[Dict[str, Any]] = []
        total_errors = 0
        total_warnings = 0
        for path in profiles:
            item: Dict[str, Any] = {
                "profile_file": path.name,
                "path": str(path),
                "loaded": False,
                "runnable": False,
                "errors": [],
                "warnings": [],
                "stage_count": 0,
            }
            try:
                profile = self.profile_loader.load_profile(path)
                labels = self.profile_loader.load_segment_labels(path, profile)
                label_source = self.profile_loader.inspect_segment_label_source(path, profile)
                validation = validator.validate(profile, labels)
                errors = list(validation.get("errors") or [])
                warnings = list(validation.get("warnings") or []) + list(label_source.get("issues") or [])
                item.update(
                    {
                        "loaded": True,
                        "profile_name": profile.profile_name,
                        "menu_group": profile.menu_group,
                        "stage_count": len(profile.stages),
                        "enabled_stage_count": sum(1 for stage in profile.stages if stage.enabled),
                        "runnable": not errors,
                        "errors": errors,
                        "warnings": warnings,
                    }
                )
            except Exception as exc:
                item["errors"] = [str(exc)]
            total_errors += len(item.get("errors") or [])
            total_warnings += len(item.get("warnings") or [])
            items.append(item)
        return {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "kind": "profile_audit",
            "started": now_local_iso(),
            "profiles_dir": str(Path(getattr(self.profile_loader, "profiles_dir", ""))),
            "counts": {
                "profiles": len(items),
                "runnable": sum(1 for item in items if item.get("runnable")),
                "blocked": sum(1 for item in items if not item.get("runnable")),
                "validation_errors": total_errors,
                "validation_warnings": total_warnings,
            },
            "profiles": items,
            "ended": now_local_iso(),
        }

    def profile_audit_payload_item(
        self,
        profile_path: Path,
        dry_run_builder: Callable[[Path, Any, List[str]], Dict[str, Any]],
    ) -> Dict[str, Any]:
        item: Dict[str, Any] = {
            "profile_file": profile_path.name,
            "profile_path": str(profile_path),
            "profile_name": "",
            "loaded": False,
            "runnable": False,
            "validation_error_count": 0,
            "validation_warning_count": 0,
            "enabled_stage_count": 0,
            "runnable_stage_count": 0,
            "errors": [],
            "warnings": [],
            "label_source": {},
            "stages": [],
        }
        try:
            profile = self.profile_loader.load_profile(profile_path)
            labels = self.profile_loader.load_segment_labels(profile_path, profile)
            item["profile_name"] = profile.profile_name
            item["loaded"] = True
            report = dry_run_builder(profile_path, profile, labels)
            label_source = self.profile_loader.inspect_segment_label_source(profile_path, profile)
            if label_source.get("issues"):
                validation = report.setdefault("validation", {})
                warnings = validation.setdefault("warnings", [])
                warnings.extend(label_source["issues"])
            validation = report.get("validation") if isinstance(report.get("validation"), dict) else {}
            errors = list(validation.get("errors") or [])
            warnings = list(validation.get("warnings") or [])
            item.update(
                {
                    "runnable": bool(report.get("runnable")),
                    "validation_error_count": len(errors),
                    "validation_warning_count": len(warnings),
                    "enabled_stage_count": int(report.get("enabled_stage_count") or 0),
                    "runnable_stage_count": int(report.get("runnable_stage_count") or 0),
                    "errors": errors,
                    "warnings": warnings,
                    "label_source": label_source,
                    "stages": [profile_audit_stage_item(stage) for stage in report.get("plan") or []],
                }
            )
        except Exception as exc:
            item["errors"] = [f"profile audit failed: {exc}"]
            item["validation_error_count"] = 1
        return item


def profile_audit_stage_item(stage: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "stage_id": stage.get("stage_id"),
        "label": stage.get("label"),
        "type": stage.get("type"),
        "enabled": bool(stage.get("enabled")),
        "runnable": bool(stage.get("runnable")),
        "duration_seconds": stage.get("duration_seconds"),
        "workloads": list(stage.get("workloads") or []),
        "backend_usage": dict(stage.get("backend_usage") or {}),
        "gpu_target_mode": stage.get("gpu_target_mode"),
        "gpu_backend_preferences": dict(stage.get("gpu_backend_preferences") or {}),
        "gpu_backend_fallback_order": dict(stage.get("gpu_backend_fallback_order") or {}),
        "gpu_target_count": len(stage.get("gpu_targets") or []),
        "gpu_effective_target_count": len(stage.get("gpu_effective_targets") or []),
        "issues": list(stage.get("issues") or []),
        "warnings": list(stage.get("warnings") or []),
    }
