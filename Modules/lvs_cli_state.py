from __future__ import annotations

import re
from typing import Any, List


class CliStateAdapter:
    """Shared CLI state helpers for environment mode and picker normalization."""

    def __init__(self, launcher: Any) -> None:
        self.launcher = launcher

    @property
    def settings(self) -> Any:
        return self.launcher.settings_manager.settings

    def normalize_text_list(self, values: Any, defaults: List[str]) -> List[str]:
        source = values if isinstance(values, list) and values else defaults
        normalized: List[str] = []
        seen: set[str] = set()
        for value in source:
            text = re.sub(r"\s+", " ", str(value or "").strip())
            key = text.lower()
            if not text or key in seen:
                continue
            normalized.append(text)
            seen.add(key)
        return normalized or list(defaults)

    def environment_mode(self) -> str:
        raw = str(getattr(self.settings, "environment_mode", "production") or "").strip().lower()
        if raw in {"end_user", "end-user", "user", "public", "consumer"}:
            return "end_user"
        return "production"

    def environment_mode_label(self) -> str:
        if self.environment_mode() == "end_user":
            return "End User"
        return "Production"

    def feature_enabled(self, feature: str) -> bool:
        mode = self.environment_mode()
        if mode == "production":
            return True
        production_only = {
            "department",
            "google_upload",
            "run_setup_history",
            "run_setup_inventory_fields",
            "settings_inventory_lists",
        }
        return feature not in production_only


class StateCompatibilityMixin:
    """Compatibility delegates for legacy launcher state helper methods."""

    def _state_cli_adapter(self) -> CliStateAdapter:
        adapter = getattr(self, "state_cli", None)
        if adapter is None:
            adapter = CliStateAdapter(self)
            self.state_cli = adapter
        return adapter

    def _normalize_text_list(self, values: Any, defaults: List[str]) -> List[str]:
        return self._state_cli_adapter().normalize_text_list(values, defaults)

    def _environment_mode(self) -> str:
        return self._state_cli_adapter().environment_mode()

    def _environment_mode_label(self) -> str:
        return self._state_cli_adapter().environment_mode_label()

    def _feature_enabled(self, feature: str) -> bool:
        return self._state_cli_adapter().feature_enabled(feature)
