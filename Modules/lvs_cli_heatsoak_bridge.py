from __future__ import annotations

from typing import Callable, Optional

from .lvs_advanced_debug import AdvancedDebugLogger
from .lvs_heatsoak import HeatsoakManager
from .lvs_profile_models import StageConfig


class HeatsoakBridgeMixin:
    """CLI heatsoak stage construction and runtime delegation."""

    def _build_heatsoak_stage(self, duration_seconds: int) -> StageConfig:
        return HeatsoakManager(self.orchestrator).build_heatsoak_stage(duration_seconds)

    def _run_heatsoak_if_requested(
        self,
        minutes: Optional[float] = None,
        *,
        advanced_debug: Optional[AdvancedDebugLogger] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> bool:
        return HeatsoakManager(self.orchestrator).run_heatsoak_if_requested(
            self._pending_heatsoak_minutes if minutes is None else float(minutes or 0.0),
            advanced_debug=advanced_debug,
            cancel_check=cancel_check,
        )
