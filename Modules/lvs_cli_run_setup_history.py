from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List

from .lvs_cli_compat import BackRequested
from .lvs_profile_models import ValidationProfile
from .lvs_run_metadata import RunMetadata


class RunSetupHistoryMixin:
    """CLI run setup history recall and preflight report delegates."""

    def _run_setup_history_path(self) -> Path:
        return self.run_setup_manager.run_setup_history_path()

    def _load_run_setup_history(self) -> List[Dict[str, Any]]:
        return self.run_setup_manager.raw_run_setup_history()

    def _save_run_setup_history(
        self,
        profile_path: Path,
        profile: ValidationProfile,
        metadata: RunMetadata,
        *,
        heatsoak_minutes: float = 0.0,
    ) -> None:
        if not self._feature_enabled("run_setup_history"):
            return
        self.run_setup_manager.save_run_setup_history(
            profile_path,
            profile,
            metadata,
            heatsoak_minutes=heatsoak_minutes,
        )

    def _run_setup_history_signature(self, item: Dict[str, Any]) -> str:
        return self.run_setup_manager.run_setup_history_signature(item)

    def _maybe_recall_run_setup_history(self, metadata: RunMetadata) -> RunMetadata:
        history = self._load_run_setup_history()
        if not history:
            return metadata
        try:
            raw = self._input("Recall previous run setup? [y/N]: ").strip().lower()
        except BackRequested:
            return metadata
        if raw not in {"y", "yes"}:
            return metadata
        print("\nRecent Run Setups")
        for index, item in enumerate(history[:8], start=1):
            item_metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            profile = item.get("profile_name") or item.get("profile_file") or "profile"
            case = item_metadata.get("case_sku") or "Case not set"
            description = item_metadata.get("description") or "Description not set"
            psu = item_metadata.get("psu_wattage") or "PSU not set"
            heatsoak = float(item.get("heatsoak_minutes") or 0.0)
            heatsoak_text = f" | heatsoak {heatsoak:g} min" if heatsoak > 0 else ""
            saved = item.get("saved") or ""
            print(f"{index}. {case} | {description} | {profile} | {psu}{heatsoak_text} | {saved}")
        choice = self._input("Choose setup to recall [Enter cancels]: ").strip()
        if not choice:
            return metadata
        try:
            selected = history[int(choice) - 1]
            selected_metadata = selected.get("metadata") if isinstance(selected.get("metadata"), dict) else {}
        except Exception:
            print("Invalid history selection.")
            return metadata
        recalled = self._metadata_from_history(selected_metadata, fallback=metadata)
        recalled.dept = self.settings_manager.settings.suite_department
        recalled.wall_wattage = ""
        self._last_recalled_heatsoak_minutes = max(0.0, float(selected.get("heatsoak_minutes") or 0.0))
        self._update_pending_heatsoak_minutes(self._last_recalled_heatsoak_minutes)
        print("Run setup recalled. Wall wattage will still be collected after this run.")
        return recalled

    def _recalled_heatsoak_minutes(self) -> float | None:
        return getattr(self, "_last_recalled_heatsoak_minutes", None)

    def _metadata_from_history(self, payload: Dict[str, Any], fallback: RunMetadata) -> RunMetadata:
        base = asdict(fallback)
        for key in base:
            if key in payload:
                if key == "advanced_debug_logging":
                    base[key] = bool(payload.get(key))
                else:
                    base[key] = str(payload.get(key) or "")
        base["advanced_debug_logging"] = False
        return RunMetadata(**base)

    def _write_preflight_report(
        self,
        profile_path: Path,
        profile: ValidationProfile,
        labels: List[str],
        preflight: Dict[str, Any],
    ) -> Path:
        return self.profile_reports.save_cli_preflight_report(
            profile_path,
            profile,
            labels,
            preflight,
            runtime_environment=self.orchestrator.workload_runner.runtime_environment(),
            backends=self.orchestrator.workload_runner.detect_backends(),
            backend_details=self.orchestrator.workload_runner.backend_details(),
            summary_text=self._preflight_summary_text(preflight),
        )
