from __future__ import annotations

from pathlib import Path
from typing import List

from Modules.lvs_cli_run_setup import RunSetupCliAdapter
from Modules.lvs_profile_models import ValidationProfile
from Modules.lvs_run_metadata import RunMetadata


class RunSetupCompatibilityMixin:
    """Compatibility delegates for legacy launcher run-setup helper methods."""

    def _run_setup_cli_adapter(self) -> RunSetupCliAdapter:
        adapter = getattr(self, "run_setup_cli", None)
        if adapter is None:
            adapter = RunSetupCliAdapter(self)
            self.run_setup_cli = adapter
        return adapter

    def _run_overrides_menu(self, profile: ValidationProfile) -> None:
        self._run_setup_cli_adapter()._run_overrides_menu(profile)

    def _maybe_edit_labels(self, labels: List[str]) -> List[str]:
        return self._run_setup_cli_adapter()._maybe_edit_labels(labels)

    def _run_setup_review(
        self,
        profile_path: Path,
        profile: ValidationProfile,
        labels: List[str],
    ) -> RunMetadata | None:
        return self._run_setup_cli_adapter()._run_setup_review(profile_path, profile, labels)
