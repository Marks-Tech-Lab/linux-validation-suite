#!/usr/bin/env python3
"""Shared profile validation and guarded persistence workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, List

from .lvs_profile_editor import ProfileEditor
from .lvs_profile_loader import ProfileLoader
from .lvs_profile_models import ValidationProfile
from .lvs_service_models import ProfileEditState
from .lvs_core import now_local_iso


def unique_profile_path(base: Path, profile_name: str) -> Path:
    stem = re.sub(r"[^A-Za-z0-9_. -]+", "_", str(profile_name or "New Profile")).strip(" ._") or "New Profile"
    candidate = base / f"{stem}.json"
    if not candidate.exists():
        return candidate
    for index in range(2, 1000):
        candidate = base / f"{stem} {index}.json"
        if not candidate.exists():
            return candidate
    return base / f"{stem} {now_local_iso().replace(':', '-')}.json"


def prepare_profile_copy_edit(editor: ProfileEditor, loader: ProfileLoader, source: ValidationProfile,
                              name: str, indices: List[int]) -> ProfileEditState:
    """One naming, collision and copy contract for CLI and GUI frontends."""
    name = re.sub(r"\s+", " ", str(name or "").strip())
    if not name:
        raise ValueError("New profile name is required.")
    if name in {".", ".."} or any(char in name for char in "/\\") or any(ord(char) < 32 for char in name):
        raise ValueError("Use a profile name, not a path or control characters.")
    if any(str(loader.profile_menu_metadata(path)["profile_name"]).casefold() == name.casefold()
           for path in loader.list_profiles()):
        raise ValueError("A profile with that name already exists. Choose a different name; no file was overwritten.")
    profile = editor.copy_profile(source, name, list(indices))
    return ProfileEditState(profile_path=unique_profile_path(loader.profiles_dir, name), profile=profile,
                            labels=editor.normalize_labels(profile, []), dirty=True, is_new=True)


@dataclass
class ProfileSavePreparation:
    profile: ValidationProfile
    labels: List[str]
    errors: List[str]
    warnings: List[str]

    @property
    def save_allowed(self) -> bool:
        return not self.errors


class ProfileSaveController:
    """Normalize, validate, and save profiles without frontend interaction."""

    def __init__(
        self,
        profile_editor: ProfileEditor,
        profile_loader: ProfileLoader,
        validator: Any,
    ) -> None:
        self.profile_editor = profile_editor
        self.profile_loader = profile_loader
        self.validator = validator

    def prepare(self, profile: ValidationProfile, labels: List[str]) -> ProfileSavePreparation:
        normalized_labels = self.profile_editor.normalize_labels(profile, labels)
        validation = self.validator.validate(profile, normalized_labels)
        return ProfileSavePreparation(
            profile=profile,
            labels=normalized_labels,
            errors=[str(item) for item in list(validation.get("errors") or [])],
            warnings=[str(item) for item in list(validation.get("warnings") or [])],
        )

    def copy_and_save(self, source: ValidationProfile, name: str, indices: List[int]) -> ProfileEditState:
        edit = prepare_profile_copy_edit(self.profile_editor, self.profile_loader, source, name, indices)
        self.save(edit.profile_path, self.prepare(edit.profile, edit.labels), exclusive=True)
        edit.dirty, edit.is_new = False, False
        return edit

    def save(
        self,
        profile_path: Path,
        preparation: ProfileSavePreparation,
        *,
        allow_errors: bool = False,
        exclusive: bool = False,
    ) -> Path:
        if preparation.errors and not allow_errors:
            raise ValueError(
                "Profile has validation error(s): "
                + "; ".join(preparation.errors[:5])
            )
        if exclusive:
            self.profile_loader.save_profile(profile_path, preparation.profile, preparation.labels, exclusive=True)
        else:
            self.profile_loader.save_profile(profile_path, preparation.profile, preparation.labels)
        return profile_path
