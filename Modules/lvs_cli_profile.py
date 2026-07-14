from __future__ import annotations

"""CLI adapter for profile creation/editing prompt workflows."""

from typing import Any

from .lvs_cli_profile_commands import ProfileCliCommandMixin
from .lvs_cli_profile_prompts import ProfileCliPromptMixin
from .lvs_cli_profile_view import ProfileCliViewMixin
from .lvs_profile_cli_editor import ProfileCliEditor


class ProfileCliAdapter(ProfileCliCommandMixin, ProfileCliPromptMixin, ProfileCliViewMixin):
    def __init__(self, launcher: Any) -> None:
        self.launcher = launcher
        self.editor = ProfileCliEditor(self)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.launcher, name)
