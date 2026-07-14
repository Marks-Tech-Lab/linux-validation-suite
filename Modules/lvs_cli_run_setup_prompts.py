from __future__ import annotations

from typing import List

from .lvs_profile_models import ValidationProfile


class RunSetupPromptMixin:
    """CLI prompt helpers used by run setup review callbacks."""

    def _run_overrides_menu(self, profile: ValidationProfile) -> None:
        while True:
            print("\nRun overrides")
            print("1. Edit stage durations")
            print("2. Edit trim for all stages")
            print("3. Toggle stage enabled/disabled")
            print("4. Continue")
            choice = self._input("Select: ").strip()
            if choice == "1":
                for idx, stage in enumerate(profile.stages, start=1):
                    raw = self._input(f"Stage {idx} [{stage.name}] duration seconds ({stage.duration_seconds}): ").strip()
                    if raw:
                        try:
                            stage.duration_seconds = int(raw)
                        except Exception:
                            print("Invalid value, keeping current.")
            elif choice == "2":
                try:
                    start_trim = int(
                        self._input(
                            f"Trim start seconds [{profile.defaults.trim_start_seconds}]: "
                        ).strip()
                        or str(profile.defaults.trim_start_seconds)
                    )
                    end_trim = int(
                        self._input(
                            f"Trim end seconds [{profile.defaults.trim_end_seconds}]: "
                        ).strip()
                        or str(profile.defaults.trim_end_seconds)
                    )
                    profile.defaults.trim_start_seconds = start_trim
                    profile.defaults.trim_end_seconds = end_trim
                    for stage in profile.stages:
                        stage.normalization.trim_start_seconds = start_trim
                        stage.normalization.trim_end_seconds = end_trim
                except Exception:
                    print("Invalid trim values.")
            elif choice == "3":
                for idx, stage in enumerate(profile.stages, start=1):
                    current = "on" if stage.enabled else "off"
                    raw = self._input(f"Stage {idx} [{stage.name}] enabled ({current}) [y/n/enter keep]: ").strip().lower()
                    if raw == "y":
                        stage.enabled = True
                    elif raw == "n":
                        stage.enabled = False
            elif choice == "4":
                return

    def _maybe_edit_labels(self, labels: List[str]) -> List[str]:
        edit = self._input("Edit segment labels before run? [y/N]: ").strip().lower()
        if edit != "y":
            return labels
        updated: List[str] = []
        for idx, label in enumerate(labels, start=1):
            raw = self._input(f"Label {idx} [{label}]: ").strip()
            updated.append(raw or label)
        return updated

    def _heatsoak_display_text(self) -> str:
        minutes = float(self._pending_heatsoak_minutes or 0.0)
        if minutes <= 0:
            return "Disabled"
        return f"{minutes:g} min Power Test (3D Auto + AVX, all CPUs/GPUs)"

    def _enter_heatsoak_minutes(self, current: float = 0.0) -> float:
        raw = self._input(f"Heatsoak duration minutes [0 disables, current {float(current or 0.0):g}]: ").strip()
        if not raw:
            return float(current or 0.0)
        if raw.lower() in {"0", "skip", "none", "off", "disable", "disabled"}:
            return 0.0
        try:
            minutes = float(raw)
        except Exception:
            print("Invalid heatsoak duration. Keeping current value.")
            return float(current or 0.0)
        if minutes <= 0:
            return 0.0
        return min(24.0 * 60.0, minutes)
