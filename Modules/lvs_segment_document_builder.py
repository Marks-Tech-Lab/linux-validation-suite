from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class SegmentDocumentInput:
    index: int
    window: Any
    duration: str
    analysis_window: str
    core_clocks: List[Dict[str, Any]]
    p_core_clock_stats: Dict[str, Optional[float]]
    e_core_clock_stats: Dict[str, Optional[float]]
    cpu_clock_stats: Dict[str, Optional[float]]
    cpu_temp_stats: Dict[str, Optional[float]]
    cpu_power_stats: Dict[str, Optional[float]]
    cpu_section: Dict[str, Any]
    memory_temp_modules: List[Dict[str, Any]]
    ram_temp_stats: Dict[str, Optional[float]]
    storage_temp_drives: List[Dict[str, Any]]
    storage_temp_stats: Dict[str, Optional[float]]
    gpu_temp_groups: Dict[str, Any]
    gpu_metrics: List[Dict[str, Any]]
    gpu_observation_summary: Dict[str, Any]
    gpu_power_stats: Dict[str, Optional[float]]
    gpu_clock_stats: Dict[str, Optional[float]]
    gpu_memory_clock_stats: Dict[str, Optional[float]]
    gpu_usage_stats: Dict[str, Optional[float]]
    gpu_memory_usage_stats: Dict[str, Optional[float]]
    gpu_vram_used_stats: Dict[str, Optional[float]]
    gpu_targeting: List[Dict[str, Any]]
    worker_state_summary: Dict[str, Any]
    stability_interpretation: Dict[str, Any]
    empty_stats: Dict[str, Optional[float]]


class SegmentDocumentBuilder:
    def __init__(self, gpu_backend_catalog: Dict[str, Dict[str, Any]]) -> None:
        self._gpu_backend_catalog = gpu_backend_catalog

    def build(self, document_input: SegmentDocumentInput) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
        detail_key = f"segment_{document_input.index}"
        detail = self._segment_detail(document_input)
        segment = self._segment(document_input)
        return detail_key, detail, segment

    def _segment_summary(self, document_input: SegmentDocumentInput) -> Dict[str, Any]:
        stability = document_input.stability_interpretation
        threshold_recommendations = stability.get("ThresholdRecommendations", {})
        return {
            "cpu_temp_max": document_input.cpu_temp_stats["Max"],
            "gpu_temp_max": document_input.gpu_temp_groups["Core"]["Max"],
            "gpu_hotspot_temp_max": document_input.gpu_temp_groups["Hotspot"]["Max"],
            "gpu_memory_temp_max": document_input.gpu_temp_groups["Memory"]["Max"],
            "cpu_power_max": document_input.cpu_power_stats["Max"],
            "gpu_power_max": document_input.gpu_power_stats["Max"],
            "gpu_clock_max": document_input.gpu_clock_stats["Max"],
            "gpu_memory_clock_max": document_input.gpu_memory_clock_stats["Max"],
            "gpu_usage_max": document_input.gpu_usage_stats["Max"],
            "gpu_memory_usage_max": document_input.gpu_memory_usage_stats["Max"],
            "gpu_vram_used_max_gb": document_input.gpu_vram_used_stats["Max"],
            "stability_state": stability["State"],
            "stability_result": stability["Result"],
            "outcome_class": stability.get("OutcomeClass"),
            "outcome_summary": stability.get("OutcomeSummary"),
            "backend_confidence": stability["BackendConfidence"],
            "warning_category_counts": stability.get("WarningCategoryCounts", {}),
            "error_category_counts": stability.get("ErrorCategoryCounts", {}),
            "report_only_threshold_would_warn_count": (
                threshold_recommendations.get("WouldWarnCount")
                if isinstance(threshold_recommendations, dict)
                else 0
            ),
        }

    def _segment_detail(self, document_input: SegmentDocumentInput) -> Dict[str, Any]:
        window = document_input.window
        return {
            "name": window.display_name,
            "type": window.stage_type,
            "verdict": window.verdict,
            "stability_interpretation": document_input.stability_interpretation,
            "failure_reasons": window.failure_reasons,
            "error_events": window.error_events,
            "system_faults": window.system_faults,
            "worker_results": window.worker_results,
            "intel_gpu_top_sidecar": window.intel_gpu_top_sidecar,
            "cpu_backend": window.cpu_backend,
            "cpu_mode_requested": window.cpu_mode_requested,
            "cpu_mode_resolved": window.cpu_mode_resolved,
            "cpu_kernel_flavor": window.cpu_kernel_flavor,
            "cpu_tuning_policy": window.cpu_tuning_policy,
            "cpu_tuned_avg_power_w": window.cpu_tuned_avg_power_w,
            "gpu_3d_backend_preference": window.gpu_3d_backend_preference,
            "gpu_3d_backend_resolved": window.gpu_3d_backend_resolved,
            "vram_backend_preference": window.vram_backend_preference,
            "vram_backend_resolved": window.vram_backend_resolved,
            "gpu_target_mode": window.gpu_target_mode,
            "gpu_targets": window.gpu_targets,
            "gpu_targeting": document_input.gpu_targeting,
            "gpu_observation_summary": document_input.gpu_observation_summary,
            "gpu_workers_initial": window.gpu_workers_initial,
            "gpu_workers_final": window.gpu_workers_final,
            "gpu_retune_events": window.gpu_retune_events,
            "gpu_worker_state_summary": document_input.worker_state_summary,
            "duration": document_input.duration,
            "analysis_window": document_input.analysis_window,
            "summary": self._segment_summary(document_input),
            "cpu": document_input.cpu_section,
        }

    def _segment(self, document_input: SegmentDocumentInput) -> Dict[str, Any]:
        window = document_input.window
        backend_profile = self._gpu_backend_catalog.get(window.gpu_3d_backend_resolved, {})
        return {
            "Label": window.display_name,
            "Name": window.display_name,
            "DisplayName": window.display_name,
            "SegmentName": window.display_name,
            "TestType": window.display_name,
            "TestTypeDetails": window.stage_type,
            "TestDescription": window.display_name,
            "Duration": document_input.duration,
            "AnalysisWindow": document_input.analysis_window,
            "Started": window.started_iso,
            "Ended": window.ended_iso,
            "Verdict": window.verdict,
            "StabilityInterpretation": document_input.stability_interpretation,
            "FailureReasons": window.failure_reasons,
            "ErrorEvents": window.error_events,
            "SystemFaults": window.system_faults,
            "WorkerResults": window.worker_results,
            "IntelGpuTopSidecar": window.intel_gpu_top_sidecar,
            "CpuInstructionSet": {
                "Backend": window.cpu_backend or "",
                "Requested": window.cpu_mode_requested or "",
                "Resolved": window.cpu_mode_resolved or "",
                "KernelFlavor": window.cpu_kernel_flavor or "",
                "TuningPolicy": window.cpu_tuning_policy or "",
                "TunedAvgPowerW": window.cpu_tuned_avg_power_w,
            },
            "GpuExecution": {
                "BackendPreference3D": window.gpu_3d_backend_preference,
                "BackendResolved3D": window.gpu_3d_backend_resolved,
                "BackendProfile3D": backend_profile,
                "BackendRecommendedForSaturation3D": bool(backend_profile.get("recommended_for_saturation")),
                "BackendPreferenceVRAM": window.vram_backend_preference,
                "BackendResolvedVRAM": window.vram_backend_resolved,
                "TargetMode": window.gpu_target_mode,
                "Targets": window.gpu_targets,
                "Targeting": document_input.gpu_targeting,
                "ObservationSummary": document_input.gpu_observation_summary,
                "WorkersInitial": window.gpu_workers_initial,
                "WorkersFinal": window.gpu_workers_final,
                "RetuneEvents": window.gpu_retune_events,
                "WorkerStateSummary": document_input.worker_state_summary,
                "IntelGpuTopSidecar": window.intel_gpu_top_sidecar,
            },
            "Clocks": {
                "Cores": document_input.core_clocks,
                "PCoreAverage": (
                    document_input.p_core_clock_stats
                    if document_input.core_clocks
                    else dict(document_input.empty_stats)
                ),
                "ECoreAverage": document_input.e_core_clock_stats,
                "AllCoreAverage": document_input.cpu_clock_stats,
            },
            "Temperatures": {
                "Cpu": document_input.cpu_temp_stats,
                "Vrm": dict(document_input.empty_stats),
                "Gpu": {
                    **document_input.gpu_temp_groups,
                    "Max": document_input.gpu_temp_groups["Core"]["Max"],
                },
                "Ram": document_input.ram_temp_stats,
                "Memory": {
                    "Max": document_input.ram_temp_stats["Max"],
                    "Modules": document_input.memory_temp_modules,
                },
                "Storage": {
                    "Overall": document_input.storage_temp_stats,
                    "Drives": document_input.storage_temp_drives,
                },
            },
            "Power": {
                "Cpu": document_input.cpu_power_stats,
                "Gpu": document_input.gpu_power_stats,
            },
            "Cpu": document_input.cpu_section,
            "Voltage": self._voltage_section(),
            "GpuMetrics": document_input.gpu_metrics,
        }

    def _voltage_section(self) -> Dict[str, Any]:
        empty_voltage = {
            "Voltage12V_Min": None,
            "Voltage12V_Avg": None,
            "Voltage12V_Max": None,
            "Voltage5V_Min": None,
            "Voltage5V_Avg": None,
            "Voltage5V_Max": None,
            "Voltage3_3V_Min": None,
            "Voltage3_3V_Avg": None,
            "Voltage3_3V_Max": None,
        }
        return {
            "Motherboard": dict(empty_voltage),
            "Gpu": dict(empty_voltage),
        }
