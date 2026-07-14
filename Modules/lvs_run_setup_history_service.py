#!/usr/bin/env python3
"""Run setup history persistence and conversion helpers."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List

from .lvs_core import JsonStore, now_local_iso
from .lvs_run_metadata import RunMetadata
from .lvs_service_models import RunSetupHistoryEntry, RunSetupState


def run_setup_history_path(settings: Any) -> Path:
    return Path(settings.settings_dir) / "run_setup_history.json"


def raw_run_setup_history(settings: Any) -> List[Dict[str, Any]]:
    payload = JsonStore.read(run_setup_history_path(settings), [])
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def run_setup_history_signature(item: Dict[str, Any]) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    keys = (
        "case_sku",
        "description",
        "psu_wattage",
        "psu_rating",
        "power_limit_data",
        "cpu_cooler",
        "fan_type",
        "fan_details",
    )
    parts = [str(item.get("profile_name") or ""), str(item.get("profile_file") or "")]
    parts.extend(str(metadata.get(key) or "") for key in keys)
    parts.append(str(item.get("heatsoak_minutes") or ""))
    return "\x1f".join(parts)


def metadata_from_history(payload: Dict[str, Any], fallback: RunMetadata) -> RunMetadata:
    base = asdict(fallback)
    for key in base:
        if key in payload:
            if key == "advanced_debug_logging":
                base[key] = bool(payload.get(key))
            else:
                base[key] = str(payload.get(key) or "")
    base["advanced_debug_logging"] = False
    return RunMetadata(**base)


def run_setup_history_entries(settings: Any) -> List[RunSetupHistoryEntry]:
    payload = raw_run_setup_history(settings)
    fallback = RunMetadata(dept=str(settings.suite_department or "Production"))
    entries: List[RunSetupHistoryEntry] = []
    for index, item in enumerate(payload[:8], start=1):
        if not isinstance(item, dict):
            continue
        item_metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        metadata = metadata_from_history(item_metadata, fallback)
        metadata.dept = str(settings.suite_department or "Production")
        metadata.wall_wattage = ""
        heatsoak_minutes = max(0.0, float(item.get("heatsoak_minutes") or 0.0))
        entries.append(
            RunSetupHistoryEntry(
                index=index,
                saved=str(item.get("saved") or ""),
                profile_name=str(item.get("profile_name") or ""),
                profile_file=str(item.get("profile_file") or ""),
                case_sku=metadata.case_sku or "Case not set",
                description=metadata.description or "Description not set",
                psu_wattage=metadata.psu_wattage or "PSU not set",
                metadata=metadata,
                heatsoak_minutes=heatsoak_minutes,
            )
        )
    return entries


def apply_run_setup_history_entry(settings: Any, setup: RunSetupState, entry: RunSetupHistoryEntry) -> None:
    setup.metadata = RunMetadata(**asdict(entry.metadata))
    setup.metadata.dept = str(settings.suite_department or "Production")
    setup.metadata.wall_wattage = ""
    setup.heatsoak_minutes = max(0.0, float(getattr(entry, "heatsoak_minutes", 0.0) or 0.0))


def save_run_setup_history(
    settings: Any,
    profile_path: Path,
    profile: Any,
    metadata: RunMetadata,
    *,
    heatsoak_minutes: float = 0.0,
) -> None:
    if not metadata.case_sku and not metadata.description:
        return
    history = raw_run_setup_history(settings)
    entry = {
        "saved": now_local_iso(),
        "profile_name": str(getattr(profile, "profile_name", "") or ""),
        "profile_file": profile_path.name,
        "metadata": asdict(metadata),
        "heatsoak_minutes": max(0.0, float(heatsoak_minutes or 0.0)),
    }
    signature = run_setup_history_signature(entry)
    filtered = [
        item
        for item in history
        if run_setup_history_signature(item) != signature
    ]
    JsonStore.write(run_setup_history_path(settings), [entry, *filtered][:8])
