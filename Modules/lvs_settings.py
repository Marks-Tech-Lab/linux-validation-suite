#!/usr/bin/env python3
"""Global suite settings model and persistence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Dict, List

from .lvs_core import JsonStore
from .lvs_option_defaults import (
    DEFAULT_CASE_OPTIONS,
    DEFAULT_CPU_COOLER_OPTIONS,
    DEFAULT_PROFILE_MENU_GROUPS,
    DEFAULT_PSU_RATING_OPTIONS,
)


DEFAULT_RESULTS_DIR = Path("results")
DEFAULT_PROFILES_DIR = Path("profiles")
DEFAULT_SETTINGS_DIR = Path("settings")
DEFAULT_GOOGLE_CREDENTIALS_PATH = DEFAULT_SETTINGS_DIR / "secrets" / "google-credentials.json"
DEFAULT_GOOGLE_SHARED_DRIVE_ID = ""
DEFAULT_TRIM_START_SECONDS = 30
DEFAULT_TRIM_END_SECONDS = 30
DEFAULT_SAMPLE_INTERVAL_SECONDS = 2.0
DEFAULT_STAGE_PROGRESS_INTERVAL_SECONDS = 30.0
GLOBAL_SETTINGS_EXAMPLE_NAME = "global_settings.example.json"


@dataclass
class GlobalSettings:
    environment_mode: str = "production"
    results_dir: str = str(DEFAULT_RESULTS_DIR)
    profiles_dir: str = str(DEFAULT_PROFILES_DIR)
    settings_dir: str = str(DEFAULT_SETTINGS_DIR)
    runtime_environment: Dict[str, str] = field(default_factory=dict)
    sample_interval_seconds: float = DEFAULT_SAMPLE_INTERVAL_SECONDS
    trim_start_seconds: int = DEFAULT_TRIM_START_SECONDS
    trim_end_seconds: int = DEFAULT_TRIM_END_SECONDS
    export_compatibility_json: bool = True
    export_extended_json: bool = True
    keep_raw_telemetry: bool = True
    privileged_helper_enabled: bool = False
    privileged_helper_prompt_for_sudo: bool = True
    prompt_for_wall_wattage: bool = True
    abort_on_fail_threshold: bool = False
    abort_on_worker_error: bool = False
    abort_on_system_fault: bool = False
    abort_run_on_stage_abort: bool = False
    target_gpu_busy_min_percent: float = 0.0
    target_gpu_busy_sustain_seconds: float = 0.0
    target_gpu_memory_busy_min_percent: float = 0.0
    target_gpu_memory_busy_sustain_seconds: float = 0.0
    strict_threshold_recommendation_warnings: bool = False
    gpu_safe_mode: bool = True
    gpu_retune_warmup_seconds: float = 60.0
    gpu_retune_cooldown_seconds: float = 30.0
    gpu_max_retunes_per_worker: int = 1
    gpu_internal_ramp_step_seconds: float = 15.0
    gpu_safe_start_load_fraction: float = 0.35
    gpu_safe_max_tuning_step: int = 2
    gpu_safe_max_load_scale: float = 1.6
    gpu_safe_max_vram_percent: float = 90.0
    gpu_external_max_processes: int = 2
    suite_department: str = "Production"
    case_options: List[str] = field(default_factory=lambda: list(DEFAULT_CASE_OPTIONS))
    psu_rating_options: List[str] = field(default_factory=lambda: list(DEFAULT_PSU_RATING_OPTIONS))
    cpu_cooler_options: List[str] = field(default_factory=lambda: list(DEFAULT_CPU_COOLER_OPTIONS))
    google_drive_credentials_path: str = str(DEFAULT_GOOGLE_CREDENTIALS_PATH)
    google_drive_shared_drive_id: str = DEFAULT_GOOGLE_SHARED_DRIVE_ID
    google_drive_move_to_uploaded_on_success: bool = True
    google_drive_prompt_after_run: bool = True
    profile_menu_groups: List[Dict[str, str]] = field(
        default_factory=lambda: [dict(item) for item in DEFAULT_PROFILE_MENU_GROUPS]
    )


class SettingsManager:
    def __init__(self, settings_path: Path) -> None:
        self.settings_path = settings_path
        fresh_settings = not settings_path.exists()
        data = self._load_initial_payload(fresh_settings)
        self.settings = GlobalSettings(**data)
        if fresh_settings:
            self.settings.settings_dir = str(settings_path.parent)
            self.save()
        self._ensure_local_dirs()
        self.settings.privileged_helper_enabled = False
        self.settings.privileged_helper_prompt_for_sudo = True

    def _load_initial_payload(self, fresh_settings: bool) -> Dict[str, object]:
        default_payload = asdict(GlobalSettings())
        source_path = self.settings_path
        if fresh_settings:
            source_path = self.settings_path.with_name(GLOBAL_SETTINGS_EXAMPLE_NAME)
        payload = JsonStore.read(source_path, default_payload)
        if not isinstance(payload, dict):
            payload = default_payload
        allowed = {field.name for field in fields(GlobalSettings)}
        return {**default_payload, **{key: value for key, value in payload.items() if key in allowed}}

    def _ensure_local_dirs(self) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_dir = Path(str(self.settings.settings_dir or self.settings_path.parent))
        (settings_dir / "secrets").mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        payload = asdict(self.settings)
        # Privileged helper state is intentionally session-only. Persisting it
        # creates a misleading split between "enabled in settings" and "sudo is
        # actually ready" after the next terminal launch.
        payload["privileged_helper_enabled"] = False
        payload["privileged_helper_prompt_for_sudo"] = True
        JsonStore.write(self.settings_path, payload)
