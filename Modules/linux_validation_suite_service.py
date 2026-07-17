#!/usr/bin/env python3
"""Shared application service for optional UI frontends.

This module is intentionally thin. The CLI in linux_validation_suite.py remains
the canonical implementation; UI layers should call this service instead of
driving CLI prompts as a subprocess.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from .lvs_profile_loader import ProfileLoader
from .lvs_settings import DEFAULT_SETTINGS_DIR, SettingsManager
from .lvs_summary_text import SummaryTextBuilder
from .lvs_settings_facade import SettingsFacade
from .lvs_privileged import PrivilegedTelemetryManager
from .lvs_heatsoak import HeatsoakManager
from .lvs_profile_edit_view import ProfileEditPresenter
from .lvs_runtime_services import build_runtime_services, normalize_runtime_settings
from .lvs_service_profile_readiness import SuiteProfileReadinessServiceMixin
from .lvs_service_profiles import SuiteProfileServiceMixin
from .lvs_service_results import SuiteResultServiceMixin
from .lvs_service_run import SuiteRunServiceMixin
from .lvs_service_settings import SuiteSettingsServiceMixin
from .lvs_service_storage_benchmark import SuiteStorageBenchmarkServiceMixin


class SuiteAppService(
    SuiteStorageBenchmarkServiceMixin,
    SuiteProfileReadinessServiceMixin,
    SuiteProfileServiceMixin,
    SuiteRunServiceMixin,
    SuiteResultServiceMixin,
    SuiteSettingsServiceMixin,
):
    """Backend facade for TUI/GUI frontends.

    Keep this layer free of terminal prompts. It should return structured data
    or text that a frontend can render however it wants.
    """

    def __init__(
        self,
        settings_path: Optional[Path] = None,
        orchestrator_factory: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        self.settings_path = settings_path or (DEFAULT_SETTINGS_DIR / "global_settings.json")
        self.orchestrator_factory = orchestrator_factory or self._default_orchestrator_factory
        self.settings_manager = SettingsManager(self.settings_path)
        self._normalize_settings()
        self._rebuild_runtime_components()

    def _default_orchestrator_factory(self, settings: Any) -> Any:
        from linux_validation_suite import ValidationOrchestrator

        return ValidationOrchestrator(settings)

    @property
    def settings(self) -> Any:
        return self.settings_manager.settings

    def reload(self) -> None:
        self.settings_manager = SettingsManager(self.settings_path)
        self._normalize_settings()
        self._rebuild_runtime_components()

    def _rebuild_runtime_components(self) -> None:
        runtime = build_runtime_services(
            settings=self.settings,
            orchestrator_factory=self.orchestrator_factory,
            ensure_ready=self.ensure_enhanced_telemetry_ready,
            run_heatsoak_if_requested=self.run_heatsoak_if_requested,
            environment_mode_label=self.environment_mode_label,
            profile_loader_type=ProfileLoader,
            summary_exporter=SummaryTextBuilder(),
        )
        runtime.bind_to(self)
        self.privileged_telemetry = PrivilegedTelemetryManager(self.settings)
        self.heatsoak_manager = HeatsoakManager(self.orchestrator)
        self.profile_edit_presenter = ProfileEditPresenter(
            self.profile_editor,
            self.profile_loader.menu_group_label,
        )
        self.settings_facade = SettingsFacade(
            self.settings_manager,
            self.reload,
            self.google_drive_readiness,
            self.environment_mode_label,
            self._normalize_text_list,
        )

    def _normalize_settings(self) -> None:
        settings = self.settings
        settings.privileged_helper_enabled = False
        settings.privileged_helper_prompt_for_sudo = True
        normalize_runtime_settings(
            settings,
            normalize_text_list=self._normalize_text_list,
            profile_loader_type=ProfileLoader,
        )

    def _normalize_text_list(self, values: List[str], defaults: List[str]) -> List[str]:
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

    def environment_mode_label(self) -> str:
        raw = str(getattr(self.settings, "environment_mode", "production") or "").strip().lower()
        if raw in {"end_user", "end-user", "user", "public", "consumer"}:
            return "End User"
        return "Production"

    def enhanced_telemetry_label(self) -> str:
        return self.privileged_telemetry.enhanced_telemetry_label()

    def enable_enhanced_telemetry(self) -> bool:
        return self.privileged_telemetry.enable_enhanced_telemetry()

    def ensure_enhanced_telemetry_ready(self) -> bool:
        return self.privileged_telemetry.ensure_ready()

    def stop_enhanced_telemetry_keepalive(self) -> None:
        self.privileged_telemetry.stop_keepalive()

    def public_support_export_text(self) -> str:
        return self.local_migration_manager.export_public_support().summary_text

    def create_private_migration_bundle(self, *, acknowledge_private_data: bool):
        return self.local_migration_manager.create_private_bundle(
            acknowledge_private_data=acknowledge_private_data,
        )

    def preview_migration_restore(self, bundle_path: Path):
        return self.local_migration_manager.preview_restore(bundle_path)

    def apply_migration_restore(self, bundle_path: Path, *, confirmed: bool):
        if not confirmed:
            raise ValueError("migration restore apply requires explicit confirmation")
        return self.local_migration_manager.apply_restore(bundle_path, yes=True)


def main() -> int:
    service = SuiteAppService()
    print(f"{service.environment_mode_label()} mode")
    print("Profiles:")
    for index, profile in enumerate(service.list_profiles(), start=1):
        print(f"{index}. {profile.name} ({profile.menu_group_label})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
