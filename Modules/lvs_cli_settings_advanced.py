from __future__ import annotations

import json


class SettingsAdvancedEditorMixin:
    """CLI editors for advanced settings validated by SettingsFacade."""

    def settings_runtime_environment_overrides(self) -> bool:
        settings = self.settings_manager.settings
        current = json.dumps(settings.runtime_environment, indent=2)
        print("Runtime environment overrides are applied to backend probes and worker launches.")
        print("Enter a JSON object like {\"RUSTICL_ENABLE\":\"radeonsi\"}.")
        print("Leave blank to clear all overrides.")
        raw = self._input(f"Runtime environment overrides [{current}]: ").strip()
        try:
            self.settings_facade.apply_runtime_environment_overrides(raw)
        except Exception as exc:
            print(f"Invalid runtime environment JSON: {exc}")
            return False
        return True

    def settings_gpu_target_thresholds(self) -> bool:
        settings = self.settings_manager.settings
        try:
            self.settings_facade.apply_gpu_target_thresholds(
                {
                    "target_gpu_busy_min_percent": self._input(
                        f"Target GPU busy min percent [{settings.target_gpu_busy_min_percent}] (0 disables): "
                    ).strip(),
                    "target_gpu_busy_sustain_seconds": self._input(
                        f"Target GPU busy sustain seconds [{settings.target_gpu_busy_sustain_seconds}] (0 disables): "
                    ).strip(),
                    "target_gpu_memory_busy_min_percent": self._input(
                        f"Target GPU memory-busy min percent [{settings.target_gpu_memory_busy_min_percent}] "
                        + "(0 disables): "
                    ).strip(),
                    "target_gpu_memory_busy_sustain_seconds": self._input(
                        "Target GPU memory-busy sustain seconds "
                        + f"[{settings.target_gpu_memory_busy_sustain_seconds}] (0 disables): "
                    ).strip(),
                }
            )
        except Exception:
            print("Invalid threshold value.")
            return False
        return True

    def settings_gpu_tuning_safeguards(self) -> bool:
        settings = self.settings_manager.settings
        try:
            self.settings_facade.apply_gpu_safe_mode_settings(
                {
                    "gpu_safe_mode": self._input(
                        f"GPU safe mode [{'Y' if settings.gpu_safe_mode else 'N'}] [Y/N]: "
                    ).strip().lower(),
                    "gpu_retune_warmup_seconds": self._input(
                        f"GPU retune warmup seconds [{settings.gpu_retune_warmup_seconds}]: "
                    ).strip(),
                    "gpu_retune_cooldown_seconds": self._input(
                        f"GPU retune cooldown seconds [{settings.gpu_retune_cooldown_seconds}]: "
                    ).strip(),
                    "gpu_max_retunes_per_worker": self._input(
                        f"GPU max retunes per worker [{settings.gpu_max_retunes_per_worker}]: "
                    ).strip(),
                    "gpu_internal_ramp_step_seconds": self._input(
                        f"GPU internal ramp step seconds [{settings.gpu_internal_ramp_step_seconds}]: "
                    ).strip(),
                    "gpu_safe_start_load_fraction": self._input(
                        f"GPU safe-mode start load fraction [{settings.gpu_safe_start_load_fraction}]: "
                    ).strip(),
                    "gpu_safe_max_tuning_step": self._input(
                        f"GPU safe-mode max tuning step [{settings.gpu_safe_max_tuning_step}]: "
                    ).strip(),
                    "gpu_safe_max_load_scale": self._input(
                        f"GPU safe-mode max load scale [{settings.gpu_safe_max_load_scale}]: "
                    ).strip(),
                    "gpu_safe_max_vram_percent": self._input(
                        f"GPU safe-mode max VRAM percent [{settings.gpu_safe_max_vram_percent}]: "
                    ).strip(),
                    "gpu_external_max_processes": self._input(
                        f"GPU external backend max processes [{settings.gpu_external_max_processes}]: "
                    ).strip(),
                }
            )
        except Exception:
            print("Invalid GPU tuning safeguard value.")
            return False
        return True
