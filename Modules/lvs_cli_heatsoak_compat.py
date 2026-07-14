from __future__ import annotations

from typing import Callable, Optional

from Modules.lvs_advanced_debug import AdvancedDebugLogger
from Modules.lvs_profile_models import StageConfig


class HeatsoakCompatibilityMixin:
    """Compatibility delegates for legacy launcher heatsoak helper methods."""

    def _heatsoak_display_text(self) -> str:
        return self._run_setup_cli_adapter()._heatsoak_display_text()

    def _enter_heatsoak_minutes(self, current: float = 0.0) -> float:
        return self._run_setup_cli_adapter()._enter_heatsoak_minutes(current)

    def _build_heatsoak_stage(self, duration_seconds: int) -> StageConfig:
        return self._run_setup_cli_adapter()._build_heatsoak_stage(duration_seconds)

    def _run_heatsoak_if_requested(
        self,
        minutes: Optional[float] = None,
        *,
        advanced_debug: Optional[AdvancedDebugLogger] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> bool:
        return self._run_setup_cli_adapter()._run_heatsoak_if_requested(
            minutes,
            advanced_debug=advanced_debug,
            cancel_check=cancel_check,
        )
