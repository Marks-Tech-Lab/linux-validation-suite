from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from Modules.lvs_profile_cli_editor import ProfileCliEditor
from Modules.lvs_profile_models import ValidationProfile


class ProfileCompatibilityAdapter:
    """Compatibility wrappers for legacy launcher profile helper methods."""

    def __init__(self, launcher: Any) -> None:
        self.launcher = launcher

    def profile_choice_text(self, path: Path) -> str:
        return self.launcher.profile_cli.profile_choice_text(path)

    def normalize_profile_labels(self, profile: ValidationProfile, labels: List[str]) -> List[str]:
        return self.launcher.profile_cli._normalize_profile_labels(profile, labels)

    def add_profile_stage(self, profile: ValidationProfile, labels: List[str]) -> List[str]:
        return ProfileCliEditor(self.launcher).add_profile_stage(profile, labels)

    def remove_profile_stage(self, profile: ValidationProfile, labels: List[str]) -> List[str]:
        return ProfileCliEditor(self.launcher).remove_profile_stage(profile, labels)

    def profile_audit(self) -> None:
        self.launcher.profile_cli.profile_audit()

    def profile_audit_body(self) -> Dict[str, Any]:
        return self.launcher.profile_cli.profile_audit_body()

    def write_profile_audit_report(self, text: str, payload: Dict[str, Any]) -> Path:
        return self.launcher.profile_cli.write_profile_audit_report(text, payload)


class ProfileCompatibilityMixin:
    """Compatibility delegates for legacy launcher profile helper methods."""

    def _profile_compat_cli_adapter(self) -> ProfileCompatibilityAdapter:
        adapter = getattr(self, "profile_compat_cli", None)
        if adapter is None:
            adapter = ProfileCompatibilityAdapter(self)
            self.profile_compat_cli = adapter
        return adapter

    def _profile_choice_text(self, path: Path) -> str:
        return self._profile_compat_cli_adapter().profile_choice_text(path)

    def _profiles_menu(self) -> None:
        self.profile_cli.profiles_menu()

    def _normalize_profile_labels(self, profile: ValidationProfile, labels: List[str]) -> List[str]:
        return self._profile_compat_cli_adapter().normalize_profile_labels(profile, labels)

    def _add_profile_stage(self, profile: ValidationProfile, labels: List[str]) -> List[str]:
        return self._profile_compat_cli_adapter().add_profile_stage(profile, labels)

    def _remove_profile_stage(self, profile: ValidationProfile, labels: List[str]) -> List[str]:
        return self._profile_compat_cli_adapter().remove_profile_stage(profile, labels)

    def _profile_execution_summary_lines(self, report: Dict[str, Any]) -> List[str]:
        return self.profile_reports.profile_execution_summary_lines(report)

    def _print_profile_execution_summary(self, report: Dict[str, Any]) -> None:
        print("")
        print("\n".join(self._profile_execution_summary_lines(report)))
        print("")

    def _profile_audit(self) -> None:
        self._profile_compat_cli_adapter().profile_audit()

    def _profile_audit_body(self) -> Dict[str, Any]:
        return self._profile_compat_cli_adapter().profile_audit_body()

    def _write_profile_audit_report(self, text: str, payload: Dict[str, Any]) -> Path:
        return self._profile_compat_cli_adapter().write_profile_audit_report(text, payload)
