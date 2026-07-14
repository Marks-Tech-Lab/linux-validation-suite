from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .lvs_compat_export_helpers import gpu_worker_backend_name
from .lvs_compat_exporter import CompatibilityExporter
from .lvs_dry_run import build_dry_run_report
from .lvs_faults import LinuxFaultCollector
from .lvs_gpu_safety_marker import GpuSafetyMarkerStore
from .lvs_gpu_worker_plan import GpuWorkerSpec
from .lvs_intel_gpu_sidecar import start_intel_gpu_top_sidecar, stop_intel_gpu_top_sidecar
from .lvs_orchestrator_retune_callbacks import (
    effective_gpu_retune_cooldown_seconds as orchestrator_effective_gpu_retune_cooldown_seconds,
    effective_gpu_retune_warmup_seconds as orchestrator_effective_gpu_retune_warmup_seconds,
    gpu_is_thermally_safe_to_retune as orchestrator_gpu_is_thermally_safe_to_retune,
    latest_sample_metric_value as orchestrator_latest_sample_metric_value,
    maybe_retune_gpu_processes as orchestrator_maybe_retune_gpu_processes,
    minimum_gpu_retune_remaining_seconds as orchestrator_minimum_gpu_retune_remaining_seconds,
    recent_metric_values_for_telemetry as orchestrator_recent_metric_values_for_telemetry,
    worker_retune_count as orchestrator_worker_retune_count,
)
from .lvs_orchestrator_stage_callbacks import (
    faults_for_stage as orchestrator_faults_for_stage,
    stage_gpu_backend_effectiveness_events as orchestrator_stage_gpu_backend_effectiveness_events,
    stage_process_failure_events as orchestrator_stage_process_failure_events,
    stage_sensor_events as orchestrator_stage_sensor_events,
    stage_target_gpu_progress_summary as orchestrator_stage_target_gpu_progress_summary,
    stage_target_gpu_utilization_events as orchestrator_stage_target_gpu_utilization_events,
    stage_vram_target_attainment_events as orchestrator_stage_vram_target_attainment_events,
    stage_worker_result_events as orchestrator_stage_worker_result_events,
)
from .lvs_orchestrator_support import (
    build_gpu_recovery_report as orchestrator_build_gpu_recovery_report,
    make_validation_run_dir,
)
from .lvs_profile_models import StageConfig, ValidationProfile
from .lvs_profile_validation import ProfileValidator
from .lvs_run_metadata import RunMetadata
from .lvs_run_models import StageWindow
from .lvs_run_orchestration import execute_validation_run
from .lvs_segment_parser import SegmentParser
from .lvs_settings import GlobalSettings
from .lvs_stage_lifecycle import stage_targets_intel_gpu
from .lvs_stage_process_control import StageProcess
from .lvs_stage_worker_evidence import fallback_worker_payload_for_entry, read_worker_result
from .lvs_strict_threshold_policy import (
    profile_strict_threshold_recommendation_warnings,
    stage_strict_threshold_recommendation_warnings,
    strict_threshold_warning_scope,
)
from .lvs_summary_text import SummaryTextBuilder
from .lvs_system_info import SystemInfoCollector
from .lvs_telemetry_collector import TelemetryCollector
from .lvs_worker_evidence import read_log_tail


class ValidationOrchestrator:
    """Backend run orchestration wiring shared by CLI, TUI, and service callers."""

    def __init__(
        self,
        settings: GlobalSettings,
        *,
        workload_runner_cls: Any,
        summary_exporter_cls: Any = SummaryTextBuilder,
    ) -> None:
        self.settings = settings
        self.workload_runner = workload_runner_cls(settings.runtime_environment, settings=settings)
        self.system_info_collector = SystemInfoCollector(
            privileged_helper_enabled=settings.privileged_helper_enabled
        )
        self.segment_parser = SegmentParser(
            strict_threshold_recommendation_warnings=settings.strict_threshold_recommendation_warnings
        )
        self.exporter = CompatibilityExporter()
        self.summary_exporter = summary_exporter_cls()
        self.validator = ProfileValidator()
        self.fault_collector = LinuxFaultCollector()
        self.gpu_safety_marker = GpuSafetyMarkerStore(settings.settings_dir)

    def _profile_strict_threshold_recommendation_warnings(self, profile: ValidationProfile) -> bool:
        return profile_strict_threshold_recommendation_warnings(
            profile,
            self.settings.strict_threshold_recommendation_warnings,
        )

    def _stage_strict_threshold_recommendation_warnings(
        self,
        profile: ValidationProfile,
        stage: StageConfig,
    ) -> bool:
        return stage_strict_threshold_recommendation_warnings(
            profile,
            stage,
            self.settings.strict_threshold_recommendation_warnings,
        )

    def _strict_threshold_warning_scope(self, profile: ValidationProfile) -> str:
        return strict_threshold_warning_scope(profile)

    def _gpu_safety_marker_path(self) -> Path:
        return self.gpu_safety_marker.marker_path()

    def _read_gpu_safety_marker(self) -> Optional[Dict[str, Any]]:
        return self.gpu_safety_marker.read()

    def _write_gpu_safety_marker(
        self,
        *,
        profile_name: str,
        stage_name: str,
        gpu_backends: List[str],
        gpu_targets: List[str],
        run_dir: Path,
    ) -> None:
        self.gpu_safety_marker.write(
            profile_name=profile_name,
            stage_name=stage_name,
            gpu_backends=gpu_backends,
            gpu_targets=gpu_targets,
            run_dir=run_dir,
        )

    def _clear_gpu_safety_marker(self) -> None:
        self.gpu_safety_marker.clear()

    def _stage_targets_intel_gpu(self, stage_plan: Dict[str, Any]) -> bool:
        return stage_targets_intel_gpu(
            stage_plan,
            gpu_target_by_id=lambda target_id: self.workload_runner._gpu_target_by_id(target_id),
        )

    def _start_intel_gpu_top_sidecar(
        self,
        *,
        stage_id: str,
        stage_name: str,
        run_dir: Path,
    ) -> Optional[Dict[str, Any]]:
        return start_intel_gpu_top_sidecar(
            stage_id=stage_id,
            stage_name=stage_name,
            run_dir=run_dir,
        )

    def _stop_intel_gpu_top_sidecar(self, sidecar: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        return stop_intel_gpu_top_sidecar(sidecar)

    def _build_gpu_recovery_report(self) -> Dict[str, Any]:
        return orchestrator_build_gpu_recovery_report(
            read_safety_marker=self._read_gpu_safety_marker,
            collect_previous_boot_faults=self.fault_collector.collect_previous_boot,
        )

    def _latest_sample_value(self, telemetry: TelemetryCollector, key: str) -> Optional[float]:
        return orchestrator_latest_sample_metric_value(telemetry, key)

    def _stage_target_gpu_progress_summary(
        self,
        telemetry: TelemetryCollector,
        stage_processes: List[StageProcess],
        stage_elapsed_seconds: float = 0.0,
    ) -> str:
        return orchestrator_stage_target_gpu_progress_summary(
            self,
            telemetry,
            stage_processes,
            stage_elapsed_seconds,
        )

    def _stage_target_gpu_utilization_events(
        self,
        window: StageWindow,
        telemetry: TelemetryCollector,
    ) -> List[Dict[str, Any]]:
        return orchestrator_stage_target_gpu_utilization_events(self, window, telemetry)

    def _stage_gpu_backend_effectiveness_events(
        self,
        window: StageWindow,
        telemetry: TelemetryCollector,
    ) -> List[Dict[str, Any]]:
        return orchestrator_stage_gpu_backend_effectiveness_events(self, window, telemetry)

    def _stage_vram_target_attainment_events(
        self,
        window: StageWindow,
        telemetry: TelemetryCollector,
    ) -> List[Dict[str, Any]]:
        return orchestrator_stage_vram_target_attainment_events(self, window, telemetry)

    def _read_worker_result(
        self,
        entry: StageProcess,
        *,
        allow_partial: bool = False,
    ) -> Optional[Dict[str, Any]]:
        return read_worker_result(entry, allow_partial=allow_partial)

    def _fallback_worker_payload(
        self,
        entry: StageProcess,
        *,
        allow_partial: bool = False,
    ) -> Optional[Dict[str, Any]]:
        return fallback_worker_payload_for_entry(entry, allow_partial=allow_partial)

    def _read_log_tail(self, path: Optional[str], max_chars: int = 4000) -> str:
        return read_log_tail(path, max_chars=max_chars)

    def _poll_stage_process_failures(self, stage_processes: List[StageProcess], display_name: str) -> List[Dict[str, Any]]:
        return orchestrator_stage_process_failure_events(self, stage_processes, display_name)

    def _worker_result_events(self, stage_processes: List[StageProcess], display_name: str) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        return orchestrator_stage_worker_result_events(self, stage_processes, display_name)

    def _gpu_worker_backend_name(self, payload: Dict[str, Any]) -> str:
        return gpu_worker_backend_name(payload, vulkan_gpu_3d_backend="python_vulkan_compute")

    def _stage_sensor_events(self, window: StageWindow, telemetry: TelemetryCollector) -> List[Dict[str, Any]]:
        return orchestrator_stage_sensor_events(self, window, telemetry)

    def _faults_for_stage(self, faults: List[Dict[str, Any]], window: StageWindow) -> List[Dict[str, Any]]:
        return orchestrator_faults_for_stage(faults, window)

    def _recent_metric_values(
        self,
        telemetry: TelemetryCollector,
        key: str,
        window_seconds: float,
    ) -> List[float]:
        return orchestrator_recent_metric_values_for_telemetry(telemetry, key, window_seconds)

    def _gpu_is_thermally_safe_to_retune(
        self,
        telemetry: TelemetryCollector,
        gpu_index: int,
    ) -> bool:
        return orchestrator_gpu_is_thermally_safe_to_retune(telemetry, gpu_index)

    def _worker_retune_count(
        self,
        retune_events: Optional[List[Dict[str, Any]]],
        spec: GpuWorkerSpec,
    ) -> int:
        return orchestrator_worker_retune_count(retune_events, spec)

    def _effective_gpu_retune_warmup_seconds(self, stage_duration_seconds: float) -> float:
        return orchestrator_effective_gpu_retune_warmup_seconds(self, stage_duration_seconds)

    def _effective_gpu_retune_cooldown_seconds(self, stage_duration_seconds: float) -> float:
        return orchestrator_effective_gpu_retune_cooldown_seconds(self, stage_duration_seconds)

    def _minimum_gpu_retune_remaining_seconds(self, stage_duration_seconds: float) -> float:
        return orchestrator_minimum_gpu_retune_remaining_seconds(self, stage_duration_seconds)

    def _maybe_retune_gpu_processes(
        self,
        stage_processes: List[StageProcess],
        telemetry: TelemetryCollector,
        display_name: str,
        retune_events: Optional[List[Dict[str, Any]]] = None,
        stage_elapsed_seconds: float = 0.0,
        stage_duration_seconds: float = 0.0,
    ) -> List[StageProcess]:
        return orchestrator_maybe_retune_gpu_processes(
            self,
            stage_processes,
            telemetry,
            display_name,
            retune_events,
            stage_elapsed_seconds,
            stage_duration_seconds,
        )

    def dry_run(self, profile_path: Path, profile: ValidationProfile, labels: List[str]) -> Dict[str, Any]:
        return build_dry_run_report(self, profile_path, profile, labels)

    def make_run_dir(self, profile_name: str) -> Path:
        return make_validation_run_dir(
            results_dir=self.settings.results_dir,
            profile_name=profile_name,
        )

    def run(
        self,
        profile_path: Path,
        profile: ValidationProfile,
        labels: List[str],
        metadata: RunMetadata,
        run_dir: Optional[Path] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        operator_stop_source: str = "cli",
    ) -> Path:
        return execute_validation_run(
            self,
            profile_path=profile_path,
            profile=profile,
            labels=labels,
            metadata=metadata,
            stage_window_cls=StageWindow,
            run_dir=run_dir,
            cancel_check=cancel_check,
            operator_stop_source=operator_stop_source,
        )
