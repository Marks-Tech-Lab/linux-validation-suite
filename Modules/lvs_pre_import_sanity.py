#!/usr/bin/env python3
"""Frontend-neutral pre-import sanity orchestration."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .lvs_core import APP_NAME, APP_VERSION, JsonStore, now_local_iso
from .lvs_result_report_text import result_validation_text
from .lvs_result_validation import ResultValidationFacade


class PreImportSanityFacade:
    """Coordinate result validation and summary refresh before import."""

    def __init__(
        self,
        results_dir: Path | str,
        result_validation: ResultValidationFacade,
        summary_exporter: Any,
    ) -> None:
        self.results_dir = Path(results_dir)
        self.result_validation = result_validation
        self.summary_exporter = summary_exporter

    def refresh_run_summary(self, result_dir: Path) -> Dict[str, Any]:
        parsed_path = result_dir / "parsed_results_custom.json"
        summary_path = result_dir / "run_summary.txt"
        status = {
            "summary_path": str(summary_path),
            "refreshed": False,
            "error": "",
        }
        try:
            parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
            summary_path.write_text(self.summary_exporter.build(parsed), encoding="utf-8")
            status["refreshed"] = True
        except Exception as exc:
            status["error"] = str(exc)
        return status

    def write_result_validation_report(self, result_dir: Path) -> Dict[str, Any]:
        payload = self.result_validation.validate_result_folder(result_dir, self.summary_exporter)
        self.result_validation.write_validation_report(result_dir, result_validation_text(payload), payload)
        return payload

    def write_selected_report(
        self,
        result_dir: Path,
        *,
        validation_text: str,
        validation_payload: Dict[str, Any],
        pre_import_text: str,
        pre_import_payload: Dict[str, Any],
        save_validation: bool = True,
    ) -> Path:
        if save_validation:
            self.result_validation.write_validation_report(result_dir, validation_text, validation_payload)
        JsonStore.write(result_dir / "pre_import_sanity.json", pre_import_payload)
        (result_dir / "pre_import_sanity.txt").write_text(pre_import_text, encoding="utf-8")
        return result_dir

    def write_batch_report(self, text: str, payload: Dict[str, Any], timestamp_name: str = "") -> Path:
        timestamp = timestamp_name or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        report_dir = self.results_dir / f"{timestamp}_Pre_Import_Sanity_Batch"
        report_dir.mkdir(parents=True, exist_ok=True)
        JsonStore.write(report_dir / "pre_import_sanity_batch.json", payload)
        (report_dir / "pre_import_sanity_batch.txt").write_text(text, encoding="utf-8")
        return report_dir

    def prepare_selected(self, result_dir: Path) -> Dict[str, Any]:
        return {
            "result_folder": str(result_dir),
            "validation": self.result_validation.validate_result_folder(result_dir, self.summary_exporter),
            "summary_refresh": self.refresh_run_summary(result_dir),
        }

    def complete_selected(
        self,
        prepared: Dict[str, Any],
        comparison: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "kind": "pre_import_sanity",
            "started": now_local_iso(),
            "result_folder": str(prepared.get("result_folder") or ""),
            "validation": prepared.get("validation") if isinstance(prepared.get("validation"), dict) else {},
            "summary_refresh": (
                prepared.get("summary_refresh")
                if isinstance(prepared.get("summary_refresh"), dict)
                else {}
            ),
            "comparison": comparison,
            "ended": now_local_iso(),
        }

    def run_batch(
        self,
        candidates: Optional[List[Path]] = None,
        *,
        save_individual_validation: bool = True,
    ) -> Dict[str, Any]:
        result_dirs = list(candidates) if candidates is not None else self.result_validation.result_candidates()
        validation_payload = self.result_validation.validate_batch(
            result_dirs,
            validate_one=lambda result_dir: self.result_validation.validate_result_folder(
                result_dir,
                self.summary_exporter,
            ),
            write_one=self.write_result_validation_report,
            save_individual=save_individual_validation,
        )

        items: List[Dict[str, Any]] = []
        refresh_statuses: List[Dict[str, Any]] = []
        validation_items = validation_payload.get("items") if isinstance(validation_payload.get("items"), list) else []
        validation_by_folder = {
            str(item.get("folder") or ""): item
            for item in validation_items
            if isinstance(item, dict)
        }
        refreshed = 0
        failed = 0
        for result_dir in result_dirs:
            status = self.refresh_run_summary(result_dir)
            refresh_statuses.append({"folder": str(result_dir), "folder_name": result_dir.name, **status})
            if status.get("refreshed"):
                refreshed += 1
            else:
                failed += 1
            validation_item = validation_by_folder.get(str(result_dir), {})
            items.append(
                {
                    "folder": str(result_dir),
                    "folder_name": result_dir.name,
                    "result": validation_item.get("result") or "unknown",
                    "summary": validation_item.get("summary") if isinstance(validation_item.get("summary"), dict) else {},
                    "summary_refresh": status,
                }
            )

        counts = dict(validation_payload.get("counts") or {})
        return {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "kind": "pre_import_sanity_batch",
            "started": now_local_iso(),
            "results_dir": str(self.results_dir),
            "excluded_root_dirs": ["Archived", "Uploaded"],
            "result": "fail"
            if int(counts.get("errors") or 0) or failed
            else "warning"
            if int(counts.get("warnings") or 0)
            else "pass",
            "counts": counts,
            "summary_refresh": {
                "total": len(refresh_statuses),
                "refreshed": refreshed,
                "failed": failed,
                "items": refresh_statuses,
            },
            "validation": validation_payload,
            "items": items,
            "ended": now_local_iso(),
        }
