from __future__ import annotations

from typing import List

from .lvs_cli_profile_compat import ProfileCompatibilityAdapter
from .lvs_profile_models import ValidationProfile


class RunSetupBridgeMixin:
    """Shared run setup bridge helpers for profile editing compatibility."""

    def _profile_compat_adapter(self) -> ProfileCompatibilityAdapter:
        adapter = getattr(self, "profile_compat_cli", None)
        if adapter is None:
            adapter = ProfileCompatibilityAdapter(self)
            self.profile_compat_cli = adapter
        return adapter

    def _normalize_profile_labels(self, profile: ValidationProfile, labels: List[str]) -> List[str]:
        return self._profile_compat_adapter().normalize_profile_labels(profile, labels)

    def _add_profile_stage(self, profile: ValidationProfile, labels: List[str]) -> List[str]:
        return self._profile_compat_adapter().add_profile_stage(profile, labels)

    def _remove_profile_stage(self, profile: ValidationProfile, labels: List[str]) -> List[str]:
        return self._profile_compat_adapter().remove_profile_stage(profile, labels)
