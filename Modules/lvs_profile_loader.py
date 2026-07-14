#!/usr/bin/env python3
"""Profile loading, saving, sorting, and sidecar-label handling."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .lvs_core import JsonStore
from .lvs_option_defaults import DEFAULT_PROFILE_MENU_GROUPS
from .lvs_profile_models import (
    ModuleCpu,
    ModuleGpu3D,
    ModuleMemory,
    ModuleVram,
    ProfileDefaults,
    StageConfig,
    StageModules,
    StageNormalization,
    ValidationProfile,
)


class ProfileLoader:
    def __init__(self, profiles_dir: Path, menu_groups: Optional[List[Dict[str, Any]]] = None) -> None:
        self.profiles_dir = profiles_dir
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self.menu_groups = self.normalize_menu_groups(menu_groups)

    def list_profiles(self) -> List[Path]:
        return sorted(
            self.profiles_dir.glob("*.json"),
            key=lambda path: self._profile_sort_key(path),
        )

    def profile_menu_metadata(self, path: Path) -> Dict[str, Any]:
        raw = JsonStore.read(path, {})
        if not isinstance(raw, dict):
            raw = {}
        return {
            "profile_name": str(raw.get("profile_name") or path.stem),
            "menu_description": self._normalize_menu_description(raw.get("menu_description") or ""),
            "menu_group": self._normalize_menu_group(raw.get("menu_group") or ""),
        }

    def menu_group_label(self, value: Any) -> str:
        group = self._normalize_menu_group(value)
        for item in self.menu_groups:
            if item.get("key") == group:
                return str(item.get("label") or group.replace("_", " "))
        return f"{group.replace('_', ' ')} (unlisted)"

    def _profile_sort_key(self, path: Path) -> tuple:
        metadata = self.profile_menu_metadata(path)
        profile_name = str(metadata.get("profile_name") or path.stem)
        return (profile_name.lower(), path.name.lower())

    @staticmethod
    def _normalize_menu_description(value: Any) -> str:
        text = str(value or "").strip()
        while text.startswith("(") and text.endswith(")") and len(text) >= 2:
            text = text[1:-1].strip()
        return re.sub(r"\s+", " ", text)

    @staticmethod
    def _normalize_menu_group(value: Any) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"[^a-z0-9_-]+", "_", text).strip("_")
        return text or "custom"

    @classmethod
    def normalize_menu_groups(cls, groups: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
        source = groups if isinstance(groups, list) and groups else DEFAULT_PROFILE_MENU_GROUPS
        normalized: List[Dict[str, str]] = []
        seen: set[str] = set()
        for item in source:
            if not isinstance(item, dict):
                continue
            key = cls._normalize_menu_group(item.get("key") or item.get("name") or item.get("group") or "")
            if not key or key in seen:
                continue
            label = re.sub(r"\s+", " ", str(item.get("label") or key.replace("_", " ").title()).strip())
            normalized.append({"key": key, "label": label or key})
            seen.add(key)
        if not normalized:
            return [dict(item) for item in DEFAULT_PROFILE_MENU_GROUPS]
        if "custom" not in seen:
            normalized.append(cls.normalize_menu_group_entry("custom", "custom profile"))
        return normalized

    @classmethod
    def normalize_menu_group_entry(cls, key: Any, label: Any = "") -> Dict[str, str]:
        normalized_key = cls._normalize_menu_group(key)
        normalized_label = re.sub(r"\s+", " ", str(label or "").strip())
        return {
            "key": normalized_key,
            "label": normalized_label or normalized_key.replace("_", " "),
        }

    def load_profile(self, path: Path) -> ValidationProfile:
        raw = json.loads(path.read_text(encoding="utf-8"))
        defaults = ProfileDefaults(**raw.get("defaults", {}))
        stages: List[StageConfig] = []
        for stage_raw in raw.get("stages", []):
            modules_raw = stage_raw.get("modules", {})
            modules = StageModules(
                cpu=ModuleCpu(**modules_raw.get("cpu", {})),
                memory=ModuleMemory(**modules_raw.get("memory", {})),
                gpu_3d=ModuleGpu3D(**modules_raw.get("gpu_3d", {})),
                vram=ModuleVram(**modules_raw.get("vram", {})),
            )
            stages.append(
                StageConfig(
                    id=stage_raw["id"],
                    name=stage_raw["name"],
                    duration_seconds=stage_raw["duration_seconds"],
                    enabled=stage_raw.get("enabled", True),
                    modules=modules,
                    normalization=StageNormalization(**stage_raw.get("normalization", {})),
                    strict_threshold_recommendation_warnings=stage_raw.get("strict_threshold_recommendation_warnings"),
                )
            )
        return ValidationProfile(
            profile_name=raw["profile_name"],
            profile_type=raw.get("profile_type", "validation_schedule"),
            segment_label_source=raw.get("segment_label_source"),
            menu_description=self._normalize_menu_description(raw.get("menu_description") or ""),
            menu_group=self._normalize_menu_group(raw.get("menu_group") or ""),
            defaults=defaults,
            stages=stages,
        )

    def save_profile(self, path: Path, profile: ValidationProfile, labels: List[str]) -> None:
        payload = {
            "profile_name": profile.profile_name,
            "profile_type": profile.profile_type,
            "segment_label_source": profile.segment_label_source,
            "menu_group": self._normalize_menu_group(profile.menu_group),
            "defaults": asdict(profile.defaults),
            "stages": [asdict(stage) for stage in profile.stages],
        }
        menu_description = self._normalize_menu_description(profile.menu_description)
        if menu_description:
            payload["menu_description"] = menu_description
        JsonStore.write(path, payload)
        if profile.segment_label_source:
            info_path = path.parent / profile.segment_label_source
            info_path.write_text("\n".join(labels) + "\n", encoding="utf-8")

    def ensure_example_profile(self) -> Path:
        path = self.profiles_dir / "PL Validation.json"
        info_path = self.profiles_dir / "PL Validation_info.txt"
        if not path.exists():
            example = {
                "profile_name": "PL Validation",
                "profile_type": "validation_schedule",
                "segment_label_source": "PL Validation_info.txt",
                "menu_group": "standard",
                "defaults": {
                    "telemetry_interval_seconds": 2,
                    "trim_start_seconds": 30,
                    "trim_end_seconds": 30,
                },
                "stages": [
                    {
                        "id": "segment_1",
                        "name": "Combined",
                        "duration_seconds": 600,
                        "enabled": True,
                        "modules": {
                            "cpu": {
                                "enabled": True,
                                "mode": "extreme",
                                "load": "steady",
                                "instruction_set": "auto",
                                "threads": "all",
                                "priority": "high",
                                "dataset": "large",
                            },
                            "gpu_3d": {
                                "enabled": True,
                                "mode": "steady",
                                "intensity": "extreme",
                                "gpus": "all",
                                "priority": "high",
                                "backend_preference": "auto",
                                "compute_variant": "stress_hash",
                            },
                            "memory": {"enabled": False},
                            "vram": {"enabled": False},
                        },
                        "normalization": {"trim_start_seconds": 30, "trim_end_seconds": 30},
                    },
                    {
                        "id": "segment_2",
                        "name": "Combined",
                        "duration_seconds": 300,
                        "enabled": True,
                        "modules": {
                            "cpu": {
                                "enabled": True,
                                "mode": "normal",
                                "load": "steady",
                                "instruction_set": "sse",
                                "threads": "all",
                                "priority": "normal",
                                "dataset": "large",
                            },
                            "memory": {
                                "enabled": True,
                                "allocation_percent": 90,
                                "instruction_set": "sse",
                                "priority": "normal",
                                "threads": "all",
                            },
                            "gpu_3d": {"enabled": False},
                            "vram": {
                                "enabled": True,
                                "allocation_percent": 90,
                                "gpus": "all",
                                "priority": "high",
                                "backend_preference": "auto",
                            },
                        },
                        "normalization": {"trim_start_seconds": 30, "trim_end_seconds": 30},
                    },
                    {
                        "id": "segment_3",
                        "name": "Combined",
                        "duration_seconds": 600,
                        "enabled": True,
                        "modules": {
                            "cpu": {
                                "enabled": True,
                                "mode": "normal",
                                "load": "steady",
                                "instruction_set": "avx2",
                                "threads": "all",
                                "priority": "high",
                                "dataset": "large",
                            },
                            "memory": {
                                "enabled": True,
                                "allocation_percent": 90,
                                "instruction_set": "avx2",
                                "priority": "normal",
                                "threads": "all",
                            },
                            "gpu_3d": {"enabled": False, "backend_preference": "auto"},
                            "vram": {"enabled": False},
                        },
                        "normalization": {"trim_start_seconds": 30, "trim_end_seconds": 30},
                    },
                ],
            }
            JsonStore.write(path, example)
        if not info_path.exists():
            info_path.write_text("Power (CPU + 3D)\nSSE + VRAM\nAVX (CPU + RAM)\n", encoding="utf-8")
        return path

    def load_segment_labels(self, profile_path: Path, profile: ValidationProfile) -> List[str]:
        if not profile.segment_label_source:
            return [stage.name for stage in profile.stages]
        info_path = profile_path.parent / profile.segment_label_source
        if not info_path.exists():
            return [stage.name for stage in profile.stages]
        labels = [line.strip() for line in info_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(labels) != len(profile.stages):
            return [stage.name for stage in profile.stages]
        return labels

    def inspect_segment_label_source(self, profile_path: Path, profile: ValidationProfile) -> Dict[str, Any]:
        if not profile.segment_label_source:
            return {"exists": False, "path": None, "issues": ["segment_label_source is not set"]}
        info_path = profile_path.parent / profile.segment_label_source
        issues: List[str] = []
        if not info_path.exists():
            issues.append(f"label sidecar missing: {info_path.name}")
            return {"exists": False, "path": str(info_path), "issues": issues}

        labels = [line.strip() for line in info_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(labels) != len(profile.stages):
            issues.append(
                f"label count mismatch: {len(labels)} labels for {len(profile.stages)} stages"
            )

        return {"exists": True, "path": str(info_path), "issues": issues}
