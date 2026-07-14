#!/usr/bin/env python3
"""Frontend-neutral result-artifact discovery and inventory construction."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .lvs_core import APP_NAME, APP_VERSION, JsonStore, now_local_iso
from .lvs_result_artifact_details import ResultArtifactDetailBuilder, plan_detail_payload, safe_json_read
from .lvs_result_artifact_inventory import EXACT_ARTIFACT_NAMES, ResultArtifactInventoryBuilder


class ResultArtifactFacade:
    """Discover and normalize active result artifacts without UI behavior."""

    MARKER_FILES = (
        "parsed_results_custom.json",
        "preflight_report.json",
        "diagnostics.json",
        "dependency_check.json",
        "profile_audit.json",
        "results_inventory.json",
        "result_validation_batch.json",
        "pre_import_sanity_batch.json",
    )

    EXACT_ARTIFACT_NAMES = EXACT_ARTIFACT_NAMES

    def __init__(self, results_dir: Path | str) -> None:
        self.results_dir = Path(results_dir)
        self.detail_builder = ResultArtifactDetailBuilder()
        self.inventory_builder = ResultArtifactInventoryBuilder(self.EXACT_ARTIFACT_NAMES)

    def candidates(self) -> List[Path]:
        excluded_root_dirs = {"archived", "uploaded"}
        candidates: List[Path] = []
        if not self.results_dir.exists():
            return candidates
        for path in self.results_dir.iterdir():
            if not path.is_dir():
                continue
            if path.name.strip().lower() in excluded_root_dirs:
                continue
            if any((path / marker).exists() for marker in self.MARKER_FILES):
                candidates.append(path)
        return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)

    @staticmethod
    def safe_json_read(path: Path) -> Dict[str, Any]:
        return safe_json_read(path)

    def artifact_file_names(self, result_dir: Path) -> List[str]:
        return self.inventory_builder.artifact_file_names(result_dir)

    def run_result_detail_payload(self, result_dir: Path) -> Dict[str, Any]:
        return self.detail_builder.run_result_detail_payload(result_dir)

    def preflight_detail_payload(self, result_dir: Path) -> Dict[str, Any]:
        return self.detail_builder.preflight_detail_payload(result_dir)

    def diagnostics_detail_payload(self, result_dir: Path) -> Dict[str, Any]:
        return self.detail_builder.diagnostics_detail_payload(result_dir)

    def dependency_detail_payload(self, result_dir: Path) -> Dict[str, Any]:
        return self.detail_builder.dependency_detail_payload(result_dir)

    def profile_audit_detail_payload(self, result_dir: Path) -> Dict[str, Any]:
        return self.detail_builder.profile_audit_detail_payload(result_dir)

    def results_inventory_detail_payload(self, result_dir: Path) -> Dict[str, Any]:
        return self.detail_builder.results_inventory_detail_payload(result_dir)

    def result_validation_batch_detail_payload(self, result_dir: Path) -> Dict[str, Any]:
        return self.detail_builder.result_validation_batch_detail_payload(result_dir)

    def pre_import_sanity_batch_detail_payload(self, result_dir: Path) -> Dict[str, Any]:
        return self.detail_builder.pre_import_sanity_batch_detail_payload(result_dir)

    def detail_payload(self, result_dir: Path, kind: str = "") -> Dict[str, Any]:
        artifact_kind = kind or str(self.inventory_item(result_dir).get("kind") or "")
        return self.detail_builder.detail_payload(result_dir, artifact_kind)

    def prepare_detail_report(self, result_dir: Path) -> Dict[str, Any]:
        item = self.inventory_item(result_dir)
        detail_payload = self.detail_payload(result_dir, str(item.get("kind") or ""))
        return {
            "report": {
                "app_name": APP_NAME,
                "app_version": APP_VERSION,
                "kind": "result_artifact_details",
                "started": now_local_iso(),
                "result_folder": str(result_dir),
                "inventory_item": item,
                "details": detail_payload.get("details") or {},
            },
            "detail_payload": detail_payload,
        }

    @staticmethod
    def complete_detail_report(prepared: Dict[str, Any]) -> Dict[str, Any]:
        report = dict(prepared.get("report") or {})
        report["ended"] = now_local_iso()
        return report

    def detail_report_payload(self, result_dir: Path) -> Dict[str, Any]:
        return self.complete_detail_report(self.prepare_detail_report(result_dir))

    @staticmethod
    def plan_detail_payload(report: Dict[str, Any], full_detail_name: str) -> Dict[str, Any]:
        return plan_detail_payload(report, full_detail_name)

    def inventory_payload(self) -> Dict[str, Any]:
        items = [self.inventory_item(path) for path in self.candidates()]
        kind_counts: Dict[str, int] = {}
        result_counts: Dict[str, int] = {}
        for item in items:
            kind = str(item.get("kind") or "unknown")
            result = str(item.get("result") or "unknown")
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
            result_counts[result] = result_counts.get(result, 0) + 1
        return {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "kind": "results_inventory",
            "started": now_local_iso(),
            "results_dir": str(self.results_dir),
            "excluded_root_dirs": ["Archived", "Uploaded"],
            "counts": {
                "total": len(items),
                "by_kind": kind_counts,
                "by_result": result_counts,
            },
            "items": items,
            "ended": now_local_iso(),
        }

    def write_inventory_report(self, text: str, payload: Dict[str, Any], timestamp_name: str = "") -> Path:
        timestamp = timestamp_name or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        report_dir = self.results_dir / f"{timestamp}_Results_Inventory"
        report_dir.mkdir(parents=True, exist_ok=True)
        JsonStore.write(report_dir / "results_inventory.json", payload)
        (report_dir / "results_inventory.txt").write_text(text, encoding="utf-8")
        return report_dir

    @staticmethod
    def write_detail_report(result_dir: Path, text: str, payload: Dict[str, Any]) -> Path:
        JsonStore.write(result_dir / "artifact_details.json", payload)
        (result_dir / "artifact_details.txt").write_text(text, encoding="utf-8")
        return result_dir

    def inventory_item(self, result_dir: Path) -> Dict[str, Any]:
        return self.inventory_builder.inventory_item(result_dir)
