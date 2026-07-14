from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from .lvs_profile_models import StageConfig, StageModules, ValidationProfile


class ProfileCliCommandMixin:
    """CLI profile command delegates backed by ProfileCliEditor."""

    def profiles_menu(self) -> None:
        self.editor.profiles_menu()

    def profile_choice_text(self, path: Path) -> str:
        return self.editor.profile_choice_text(path)

    def profile_audit(self) -> None:
        self.editor.profile_audit()

    def profile_audit_body(self) -> Dict[str, Any]:
        return self.editor.profile_audit_body()

    def write_profile_audit_report(self, text: str, payload: Dict[str, Any]) -> Path:
        return self.editor.write_profile_audit_report(text, payload)

    def _create_profile(self) -> None:
        self.editor.create_profile()

    def _edit_profile(self) -> None:
        self.editor.edit_profile()

    def _normalize_profile_labels(self, profile: ValidationProfile, labels: List[str]) -> List[str]:
        return self.editor.normalize_profile_labels(profile, labels)

    def _add_profile_stage(self, profile: ValidationProfile, labels: List[str]) -> List[str]:
        return self.editor.add_profile_stage(profile, labels)

    def _remove_profile_stage(self, profile: ValidationProfile, labels: List[str]) -> List[str]:
        return self.editor.remove_profile_stage(profile, labels)

    def _edit_profile_menu_metadata(self, profile: ValidationProfile) -> None:
        self.editor.edit_profile_menu_metadata(profile)

    def _build_stage_modules(self, test_type: str) -> StageModules:
        return self.editor.build_stage_modules(test_type)

    def _edit_stage(
        self,
        profile: ValidationProfile,
        stage_index: int,
        stage: StageConfig,
        labels: List[str],
    ) -> List[str]:
        return self.editor.edit_stage(profile, stage_index, stage, labels)

    def _prompt_stage_edit_value(self, action: str, stage: StageConfig, current_label: str) -> Tuple[bool, Any]:
        return self.editor.prompt_stage_edit_value(action, stage, current_label)
