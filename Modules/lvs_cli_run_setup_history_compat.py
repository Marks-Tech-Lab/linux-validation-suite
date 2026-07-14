from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from Modules.lvs_profile_models import ValidationProfile
from Modules.lvs_run_metadata import RunMetadata


class RunSetupHistoryCompatibilityMixin:
    """Compatibility delegates for legacy launcher run setup history helpers."""

    def _run_setup_history_path(self) -> Path:
        return self._run_setup_cli_adapter()._run_setup_history_path()

    def _load_run_setup_history(self) -> List[Dict[str, Any]]:
        return self._run_setup_cli_adapter()._load_run_setup_history()

    def _save_run_setup_history(
        self,
        profile_path: Path,
        profile: ValidationProfile,
        metadata: RunMetadata,
        *,
        heatsoak_minutes: float = 0.0,
    ) -> None:
        self._run_setup_cli_adapter()._save_run_setup_history(
            profile_path,
            profile,
            metadata,
            heatsoak_minutes=heatsoak_minutes,
        )

    def _run_setup_history_signature(self, item: Dict[str, Any]) -> str:
        return self._run_setup_cli_adapter()._run_setup_history_signature(item)

    def _maybe_recall_run_setup_history(self, metadata: RunMetadata) -> RunMetadata:
        return self._run_setup_cli_adapter()._maybe_recall_run_setup_history(metadata)

    def _metadata_from_history(self, payload: Dict[str, Any], fallback: RunMetadata) -> RunMetadata:
        return self._run_setup_cli_adapter()._metadata_from_history(payload, fallback)

    def _write_preflight_report(
        self,
        profile_path: Path,
        profile: ValidationProfile,
        labels: List[str],
        preflight: Dict[str, Any],
    ) -> Path:
        return self._run_setup_cli_adapter()._write_preflight_report(profile_path, profile, labels, preflight)
