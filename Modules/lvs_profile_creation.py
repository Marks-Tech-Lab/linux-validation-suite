#!/usr/bin/env python3
"""Prompt-free profile creation and stage insertion for all frontends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .lvs_profile_editor import ProfileEditor
from .lvs_profile_models import (
    ProfileDefaults,
    StageConfig,
    StageModules,
    StageNormalization,
    ValidationProfile,
)
from .lvs_settings import (
    DEFAULT_SAMPLE_INTERVAL_SECONDS,
    DEFAULT_TRIM_END_SECONDS,
    DEFAULT_TRIM_START_SECONDS,
)


@dataclass(frozen=True)
class ProfileStageDraft:
    label: str
    test_type: str
    duration_seconds: int
    modules: StageModules


@dataclass(frozen=True)
class ProfileCreationRequest:
    profile_name: str
    menu_group: str = "custom"
    telemetry_interval_seconds: float = DEFAULT_SAMPLE_INTERVAL_SECONDS
    trim_start_seconds: int = DEFAULT_TRIM_START_SECONDS
    trim_end_seconds: int = DEFAULT_TRIM_END_SECONDS
    stages: List[ProfileStageDraft] = field(default_factory=list)
    profile_type: str = "validation_schedule"
    segment_label_source: str = ""


@dataclass
class ProfileBuildResult:
    profile: ValidationProfile
    labels: List[str]


@dataclass
class ProfileStageInsertResult:
    stage: StageConfig
    labels: List[str]


class ProfileCreationController:
    """Build save-ready profile state without frontend prompts or filesystem writes."""

    def __init__(self, profile_editor: ProfileEditor) -> None:
        self.profile_editor = profile_editor

    def build_profile(self, request: ProfileCreationRequest) -> ProfileBuildResult:
        defaults = ProfileDefaults(
            telemetry_interval_seconds=request.telemetry_interval_seconds,
            trim_start_seconds=request.trim_start_seconds,
            trim_end_seconds=request.trim_end_seconds,
        )
        stages: List[StageConfig] = []
        labels: List[str] = []
        for index, draft in enumerate(request.stages, start=1):
            stages.append(
                StageConfig(
                    id=f"segment_{index}",
                    name=draft.test_type,
                    duration_seconds=draft.duration_seconds,
                    enabled=True,
                    modules=draft.modules,
                    normalization=StageNormalization(defaults.trim_start_seconds, defaults.trim_end_seconds),
                )
            )
            labels.append(draft.label)
        profile = ValidationProfile(
            profile_name=request.profile_name,
            profile_type=request.profile_type,
            segment_label_source=request.segment_label_source or f"{request.profile_name}_info.txt",
            menu_group=request.menu_group,
            defaults=defaults,
            stages=stages,
        )
        return ProfileBuildResult(profile=profile, labels=labels)

    def insert_stage(
        self,
        profile: ValidationProfile,
        labels: List[str],
        draft: ProfileStageDraft,
        position: int | None = None,
    ) -> ProfileStageInsertResult:
        stage = self.profile_editor.create_stage(
            profile,
            test_type=draft.test_type,
            duration_seconds=max(1, draft.duration_seconds),
            modules=draft.modules,
        )
        _, updated_labels = self.profile_editor.add_stage(
            profile,
            labels,
            stage,
            draft.label,
            position=position,
        )
        return ProfileStageInsertResult(stage=stage, labels=updated_labels)
