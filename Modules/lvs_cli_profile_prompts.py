from __future__ import annotations

from typing import Any

from .lvs_cli_profile_gpu_prompts import ProfileCliGpuPromptMixin
from .lvs_cli_profile_stage_prompts import ProfileCliStagePromptMixin


class ProfileCliPromptMixin(ProfileCliStagePromptMixin, ProfileCliGpuPromptMixin):
    """CLI prompt helpers for profile metadata and stage option choices."""

    def _profile_menu_group_label(self, value: Any) -> str:
        return self.profile_loader.menu_group_label(value)

    def _choose_profile_menu_group(self, default: str = "custom") -> str:
        options = [
            (str(item.get("key") or ""), str(item.get("label") or ""))
            for item in self.profile_loader.menu_groups
            if str(item.get("key") or "").strip()
        ]
        default_group = self.profile_loader._normalize_menu_group(default)
        valid = {key for key, _ in options}
        if default_group not in valid:
            options.append((default_group, f"{default_group.replace('_', ' ')} (unlisted/current)"))
            valid.add(default_group)
        print("\nMenu group:")
        for index, (key, label) in enumerate(options, start=1):
            suffix = " [default]" if key == default_group else ""
            print(f"{index}. {label} ({key}){suffix}")
        raw = self._input("Choose menu group [blank keeps default, or type a new key]: ").strip().lower()
        if not raw:
            return default_group
        try:
            return options[int(raw) - 1][0]
        except Exception:
            normalized = self.profile_loader._normalize_menu_group(raw)
            if normalized in valid:
                return normalized
            print(
                f"Using unlisted group '{normalized}'. Add it under Settings > Edit profile menu groups "
                + "if you want it to appear as a normal picker option."
            )
            return normalized

    def _choose_test_type(self) -> str:
        return self.editor.choose_test_type()
