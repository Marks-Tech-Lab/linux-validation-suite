from __future__ import annotations

"""Settings, dependency, and profile-maintenance facade methods for shared services."""

from typing import Any, Dict, List

from .lvs_service_models import FrontendActionSpec


class SuiteSettingsServiceMixin:
    """Prompt-free settings/dependency methods shared by TUI, GUI, and QA callers."""

    def ensure_example_profile_text(self) -> str:
        path = self.profile_loader.ensure_example_profile()
        self.reload()
        return f"Example profile ensured:\n{path}"

    def settings_summary_text(self) -> str:
        return self.settings_facade.settings_summary_text()

    def toggle_environment_mode_text(self) -> str:
        return self.settings_facade.toggle_environment_mode_text()

    def set_department_text(self, value: str) -> str:
        return self.settings_facade.set_department_text(value)

    def set_numeric_setting_text(self, attr_name: str, value: str) -> str:
        return self.settings_facade.set_numeric_setting_text(attr_name, value)

    def toggle_bool_setting_text(self, attr_name: str) -> str:
        return self.settings_facade.toggle_bool_setting_text(attr_name)

    def set_runtime_environment_overrides_text(self, raw: str) -> str:
        return self.settings_facade.set_runtime_environment_overrides_text(raw)

    def set_gpu_target_thresholds_text(self, values: Dict[str, str]) -> str:
        return self.settings_facade.set_gpu_target_thresholds_text(values)

    def set_gpu_safe_mode_settings_text(self, values: Dict[str, str]) -> str:
        return self.settings_facade.set_gpu_safe_mode_settings_text(values)

    def google_drive_readiness_text(self) -> str:
        return self.post_run_manager.google_drive_readiness_text()

    def settings_action_for_key(self, key: str) -> FrontendActionSpec:
        return self.settings_facade.settings_action_for_key(key)

    def settings_list_action_for_key(self, key: str) -> FrontendActionSpec:
        return self.settings_facade.settings_list_action_for_key(key)

    def settings_input_label(self, field: str) -> str:
        return self.settings_facade.settings_input_label(field)

    def setting_text_list(self, list_key: str) -> List[str]:
        return self.settings_facade.setting_text_list(list_key)

    def setting_text_list_summary(self, list_key: str) -> str:
        return self.settings_facade.setting_text_list_summary(list_key)

    def setting_text_list_title(self, list_key: str) -> str:
        return self.settings_facade.setting_text_list_title(list_key)

    def add_setting_text_list_item(self, list_key: str, value: str) -> str:
        return self.settings_facade.add_setting_text_list_item(list_key, value)

    def rename_setting_text_list_item(self, list_key: str, index: int, value: str) -> str:
        return self.settings_facade.rename_setting_text_list_item(list_key, index, value)

    def delete_setting_text_list_item(self, list_key: str, index: int) -> str:
        return self.settings_facade.delete_setting_text_list_item(list_key, index)

    def restore_setting_text_list_defaults(self, list_key: str) -> str:
        return self.settings_facade.restore_setting_text_list_defaults(list_key)

    def profile_menu_groups_text(self) -> str:
        return self.settings_facade.profile_menu_group_summary_text()

    def profile_menu_groups(self) -> List[Dict[str, str]]:
        return self.settings_facade.profile_menu_groups()

    def add_profile_menu_group_text(self, raw_key: str, label: str) -> str:
        return self.settings_facade.add_profile_menu_group_text(raw_key, label)

    def rename_profile_menu_group_text(self, index: int, label: str) -> str:
        return self.settings_facade.rename_profile_menu_group_text(index, label)

    def delete_profile_menu_group_text(self, index: int) -> str:
        return self.settings_facade.delete_profile_menu_group_text(index)

    def restore_profile_menu_group_defaults_text(self) -> str:
        return self.settings_facade.restore_profile_menu_group_defaults_text()

    def profile_audit_text(self, save: bool = True) -> str:
        return self.profile_reports.profile_audit_text(save=save)

    def profile_audit_payload(self) -> Dict[str, Any]:
        return self.profile_reports.profile_audit_payload(self.orchestrator.dry_run)

    def profile_audit_summary_text(self, payload: Dict[str, Any]) -> str:
        return self.profile_reports.profile_audit_summary_text(payload)

    def dependency_summary_text(self) -> str:
        return self.dependency_reports.dependency_summary_text()

    def dependency_check_payload(self) -> Dict[str, Any]:
        return self.dependency_reports.dependency_check_payload()

    def run_dependency_check(self) -> Any:
        return self.dependency_reports.run_dependency_check(self.settings.results_dir)
