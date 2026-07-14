#!/usr/bin/env python3
"""Shared profile validation and guarded persistence workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List

from .lvs_profile_editor import ProfileEditor
from .lvs_profile_loader import ProfileLoader
from .lvs_profile_models import ValidationProfile


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

    def save(
        self,
        profile_path: Path,
        preparation: ProfileSavePreparation,
        *,
        allow_errors: bool = False,
    ) -> Path:
        if preparation.errors and not allow_errors:
            raise ValueError(
                "Profile has validation error(s): "
                + "; ".join(preparation.errors[:5])
            )
        self.profile_loader.save_profile(
            profile_path,
            preparation.profile,
            preparation.labels,
        )
        return profile_path
