#!/usr/bin/env python3
"""Configured logical-path ownership for private local migration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
from pathlib import Path
from typing import Any

from .lvs_settings import GlobalSettings


def _resolve_owned_path(root: Path, value: object, fallback: Path) -> Path:
    raw = Path(str(value or fallback))
    return raw.resolve() if raw.is_absolute() else (root / raw).resolve()


@dataclass(frozen=True)
class MigrationPathOwnership:
    application_root: Path
    settings_file: Path
    settings_root: Path
    profiles_root: Path
    results_root: Path
    bundle_root: Path
    relative_path_resolution: str = "application_root"

    @classmethod
    def from_settings(
        cls,
        *,
        application_root: Path,
        settings_file: Path,
        settings: Any,
    ) -> "MigrationPathOwnership":
        root = application_root.resolve()
        settings_path = settings_file.resolve() if settings_file.is_absolute() else (root / settings_file).resolve()
        settings_root = _resolve_owned_path(root, getattr(settings, "settings_dir", None), settings_path.parent)
        profiles_root = _resolve_owned_path(root, getattr(settings, "profiles_dir", None), Path("profiles"))
        results_root = _resolve_owned_path(root, getattr(settings, "results_dir", None), Path("results"))
        return cls(
            application_root=root,
            settings_file=settings_path,
            settings_root=settings_root,
            profiles_root=profiles_root,
            results_root=results_root,
            bundle_root=results_root / "Migration_Bundles",
        )

    @classmethod
    def load_nonmutating(cls, *, application_root: Path, settings_file: Path | None = None) -> tuple["MigrationPathOwnership", GlobalSettings]:
        root = application_root.resolve()
        selected = settings_file or (root / "settings/global_settings.json")
        selected = selected.resolve() if selected.is_absolute() else (root / selected).resolve()
        defaults = asdict(GlobalSettings())
        payload: dict[str, Any] = {}
        try:
            candidate = json.loads(selected.read_text(encoding="utf-8"))
            if isinstance(candidate, dict):
                allowed = {item.name for item in fields(GlobalSettings)}
                payload = {key: value for key, value in candidate.items() if key in allowed}
        except (OSError, UnicodeError, json.JSONDecodeError):
            payload = {}
        settings = GlobalSettings(**{**defaults, **payload})
        if not selected.exists():
            settings.settings_dir = str(selected.parent)
        return cls.from_settings(application_root=root, settings_file=selected, settings=settings), settings

    def root_for_role(self, role: str) -> Path:
        roots = {
            "settings": self.settings_root,
            "settings_file": self.settings_file.parent,
            "profiles": self.profiles_root,
            "results": self.results_root,
            "application": self.application_root,
        }
        if role not in roots:
            raise ValueError("unknown migration logical root")
        return roots[role]
