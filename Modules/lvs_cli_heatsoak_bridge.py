from __future__ import annotations

from typing import Callable, Optional

from .lvs_advanced_debug import AdvancedDebugLogger
from .lvs_heatsoak import HeatsoakManager
from .lvs_profile_models import ModuleCpu, ModuleGpu3D, StageConfig, StageModules, StageNormalization


class HeatsoakBridgeMixin:
    """CLI heatsoak stage construction and runtime delegation."""

    def _build_heatsoak_stage(self, duration_seconds: int) -> StageConfig:
        return StageConfig(
            id="heatsoak",
            name="Combined",
            duration_seconds=max(1, int(duration_seconds)),
            enabled=True,
            modules=StageModules(
                cpu=ModuleCpu(
                    enabled=True,
                    mode="extreme",
                    load="steady",
                    instruction_set="avx",
                    threads="all",
                    priority="high",
                ),
                gpu_3d=ModuleGpu3D(
                    enabled=True,
                    mode="steady",
                    intensity="extreme",
                    gpus="all",
                    backend_preference="auto",
                    compute_variant="stress_hash",
                ),
            ),
            normalization=StageNormalization(0, 0),
        )

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
