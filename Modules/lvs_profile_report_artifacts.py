#!/usr/bin/env python3
"""Profile report artifact writing helpers."""

from __future__ import annotations

import re
import os
import json
import tempfile
from uuid import uuid4
from pathlib import Path
from typing import Any, Dict, List

from .lvs_core import APP_NAME, APP_VERSION, JsonStore, now_local_iso
from .lvs_source_provenance import collect_source_provenance
from .lvs_source_review import source_identity, source_identity_text
from .lvs_profile_loader import ProfileLoader


def safe_report_name(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._ -]+", "_", value or "Report").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:80] or "Report"


def profile_used_payload(profile: Any, labels: List[str]) -> Dict[str, Any]:
    return {**ProfileLoader.profile_payload(profile, labels), "segment_labels": list(labels)}


def atomic_preflight_json(path: Path, payload: Any) -> None:
    """Publish complete readiness JSON; never leave a truncated prior decision."""
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=path.parent,delete=False) as handle:
            name = handle.name
            json.dump(payload,handle,indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name,path)
        name = None
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


class ProfileReportArtifactWriter:
    """Write profile report artifacts without CLI prompts or text rendering."""

    def __init__(self, profile_loader: Any, result_reports: Any) -> None:
        self.profile_loader = profile_loader
        self.result_reports = result_reports

    def save_profile_audit_report(self, text: str, payload: Dict[str, Any]) -> Path:
        report_dir = self.result_reports.new_report_dir("Profile_Audit")
        JsonStore.write(report_dir / "profile_audit.json", payload)
        (report_dir / "profile_audit.txt").write_text(text, encoding="utf-8")
        return report_dir

    def save_dry_run_report(
        self,
        profile_path: Path,
        report: Dict[str, Any],
        setup: Any | None = None,
        summary_text: str = "",
    ) -> Path:
        profile = setup.profile if setup is not None else self.profile_loader.load_profile(profile_path)
        labels = setup.labels if setup is not None else self.profile_loader.load_segment_labels(profile_path, profile)
        profile_name = re.sub(
            r"[^A-Za-z0-9_. -]+",
            "_",
            str(getattr(profile, "profile_name", "") or profile_path.stem),
        ).strip()
        report_dir = self.result_reports.new_report_dir(f"{profile_name}_Diagnostics")
        payload = {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "kind": "dry_run_diagnostics",
            "diagnostic_scope": "effective_profile_dry_run" if setup is not None else "original_profile_dry_run",
            "source_provenance": collect_source_provenance(),
            "started": now_local_iso(),
            "profile_name": getattr(profile, "profile_name", profile_path.stem),
            "profile_file": profile_path.name,
            "segment_labels": labels,
            "dry_run": report,
            "ended": now_local_iso(),
        }
        JsonStore.write(report_dir / "dry_run_diagnostics.json", payload)
        self.write_profile_used(report_dir, profile, labels)
        source_text = source_identity_text(source_identity(payload["source_provenance"]))
        (report_dir / "dry_run_summary.txt").write_text((summary_text or str(report)) + "\n\n" + source_text + "\n", encoding="utf-8")
        return report_dir

    def save_cli_diagnostics_report(
        self,
        profile_path: Path,
        profile: Any,
        labels: List[str],
        report: Dict[str, Any],
        *,
        summary_text: str = "",
    ) -> Path:
        profile_name = safe_report_name(str(getattr(profile, "profile_name", "") or profile_path.stem))
        report_dir = self.result_reports.new_report_dir(f"Diagnostics_{profile_name}")
        payload = dict(report)
        payload["kind"] = "dry_run_diagnostics"
        payload["source_provenance"] = collect_source_provenance()
        payload["saved"] = now_local_iso()
        payload["profile_path"] = str(profile_path)
        payload["segment_labels"] = labels
        payload["menu_description"] = getattr(profile, "menu_description", "")
        payload["menu_group"] = getattr(profile, "menu_group", "")
        JsonStore.write(report_dir / "diagnostics.json", payload)
        self.write_profile_used(report_dir, profile, labels)
        source_text = source_identity_text(source_identity(payload["source_provenance"]))
        (report_dir / "diagnostics_summary.txt").write_text((summary_text or str(report)) + "\n\n" + source_text + "\n", encoding="utf-8")
        return report_dir

    def save_cli_preflight_report(
        self,
        profile_path: Path,
        profile: Any,
        labels: List[str],
        preflight: Dict[str, Any],
        *,
        runtime_environment: Dict[str, Any] | None = None,
        backends: Dict[str, Any] | None = None,
        backend_details: Dict[str, Any] | None = None,
        summary_text: str = "",
        effective_context: Dict[str, Any] | None = None,
        report_dir: Path | None = None,
    ) -> Path:
        profile_name = safe_report_name(str(getattr(profile, "profile_name", "") or profile_path.stem))
        suffix = f"{profile_name}_Effective_Preflight_{uuid4().hex[:8]}" if effective_context is not None else f"{profile_name}_Preflight"
        report_dir = report_dir or self.result_reports.new_report_dir(suffix)
        payload = {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "profile_name": getattr(profile, "profile_name", profile_path.stem),
            "profile_file": profile_path.name,
            "menu_description": getattr(profile, "menu_description", ""),
            "menu_group": getattr(profile, "menu_group", ""),
            "segment_labels": labels,
            "started": now_local_iso(),
            "kind": "preflight_only",
            "source_provenance": collect_source_provenance(),
            "runtime_environment": runtime_environment or {},
            "backends": backends or {},
            "backend_details": backend_details or {},
            "preflight": preflight,
            "result": "Ready" if effective_context is not None and preflight.get("runnable") else "Blocked",
        }
        if effective_context is not None:
            payload.update(effective_context)
            payload.update(status="READY" if preflight.get("runnable") else "BLOCKED", ended=now_local_iso(),
                           completion_scope="readiness_only_not_workload_execution")
            atomic_preflight_json(report_dir / "original_profile.json",effective_context["original_profile"])
            atomic_preflight_json(report_dir / "profile_used.json",effective_context["effective_profile"])
            atomic_preflight_json(report_dir / "preflight_report.json",payload)
        else:
            JsonStore.write(report_dir / "preflight_report.json", payload)
            self.write_profile_used(report_dir, profile, labels)
        source_text = source_identity_text(source_identity(payload["source_provenance"]))
        (report_dir / "preflight_summary.txt").write_text((("Effective run-setup readiness only; no workload executed.\nStatus: " + payload["status"] + "\n") if effective_context is not None else "") + (summary_text or str(preflight)) + "\n\n" + source_text + "\n", encoding="utf-8")
        return report_dir

    @staticmethod
    def write_profile_used(report_dir: Path, profile: Any, labels: List[str]) -> None:
        JsonStore.write(report_dir / "profile_used.json", profile_used_payload(profile, labels))
