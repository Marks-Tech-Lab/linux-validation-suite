from __future__ import annotations

from typing import Any, Dict, List

from .lvs_segment_document_builder import SegmentDocumentInput


class SegmentMetricContextBuilder:
    def __init__(
        self,
        metric_helper: Any,
        cpu_clocks: Any,
        cpu_metrics: Any,
        gpu_targeting: Any,
        gpu_metrics: Any,
        gpu_worker_summary: Any,
        temperature_metrics: Any,
        stage_stability: Any,
    ) -> None:
        self._metric_helper = metric_helper
        self._cpu_clocks = cpu_clocks
        self._cpu_metrics = cpu_metrics
        self._gpu_targeting = gpu_targeting
        self._gpu_metrics = gpu_metrics
        self._gpu_worker_summary = gpu_worker_summary
        self._temperature_metrics = temperature_metrics
        self._stage_stability = stage_stability

    def build(
        self,
        *,
        index: int,
        window: Any,
        telemetry: Any,
        gpu_inventory: List[Dict[str, Any]],
        gpu_names: Dict[int, str],
        gpu_order: Dict[int, int],
        gpu_device_classes: Dict[int, str],
        cpu_package_metadata: Dict[int, Dict[str, Any]],
        duration: str,
        analysis_window: str,
        strict_threshold_enabled: bool,
    ) -> SegmentDocumentInput:
        samples = self._metric_helper.samples_for_window(telemetry.samples, window)
        core_clocks = self._cpu_clocks.core_clock_entries(samples, telemetry)
        cpu_clock_stats = (
            self._cpu_clocks.aggregate_core_clock_stats(core_clocks)
            if core_clocks
            else self._metric_helper.metric_stats(samples, "cpu_clock_mhz")
        )
        p_core_clock_stats = self._cpu_clocks.aggregate_core_clock_stats_by_type(core_clocks, "P")
        e_core_clock_stats = self._cpu_clocks.aggregate_core_clock_stats_by_type(core_clocks, "E")
        cpu_temp_stats = self._metric_helper.metric_stats(samples, "cpu_temp_c")
        cpu_power_stats = self._metric_helper.metric_stats(samples, "cpu_power_w")
        cpu_section = self._cpu_metrics.metric_section(
            samples,
            core_clocks,
            cpu_package_metadata,
            temp_stats=cpu_temp_stats,
            power_stats=cpu_power_stats,
            all_core_clock_stats=cpu_clock_stats,
        )

        memory_temp_modules = self._temperature_metrics.memory_temp_entries(samples, telemetry)
        ram_temp_stats = self._temperature_metrics.aggregate_memory_temp_stats(memory_temp_modules)
        storage_temp_drives = self._temperature_metrics.storage_temp_entries(samples, telemetry)
        storage_temp_stats = self._temperature_metrics.aggregate_storage_temp_stats(storage_temp_drives)

        gpu_targeting = self._gpu_targeting.targeting_details(
            window,
            gpu_names,
            gpu_order,
            samples,
            gpu_inventory,
        )
        gpu_temp_groups = self._temperature_metrics.gpu_temperature_groups(samples, gpu_names, gpu_order)
        gpu_metrics = self._gpu_metrics.metric_entries(
            samples,
            gpu_names,
            gpu_order,
            gpu_targeting,
            gpu_device_classes,
        )
        gpu_observation_summary = self._gpu_metrics.observation_summary(gpu_targeting, gpu_metrics)
        gpu_power_stats = self._gpu_metrics.aggregate_metric_stats(gpu_metrics, "Power")
        gpu_clock_stats = self._gpu_metrics.aggregate_metric_stats(gpu_metrics, "Clock")
        gpu_memory_clock_stats = self._gpu_metrics.aggregate_metric_stats(gpu_metrics, "MemoryClock")
        gpu_usage_stats = self._gpu_metrics.aggregate_metric_stats(gpu_metrics, "Usage")
        gpu_memory_usage_stats = self._gpu_metrics.aggregate_metric_stats(gpu_metrics, "MemoryUsage")
        gpu_vram_used_stats = self._gpu_metrics.aggregate_metric_stats(gpu_metrics, "VramUsedGB")

        worker_state_summary = self._gpu_worker_summary.summary(window)
        stability_interpretation = self._stage_stability.interpret(
            window,
            gpu_targeting,
            gpu_metrics,
            worker_state_summary,
            strict_threshold_enabled=strict_threshold_enabled,
        )

        return SegmentDocumentInput(
            index=index,
            window=window,
            duration=duration,
            analysis_window=analysis_window,
            core_clocks=core_clocks,
            p_core_clock_stats=p_core_clock_stats,
            e_core_clock_stats=e_core_clock_stats,
            cpu_clock_stats=cpu_clock_stats,
            cpu_temp_stats=cpu_temp_stats,
            cpu_power_stats=cpu_power_stats,
            cpu_section=cpu_section,
            memory_temp_modules=memory_temp_modules,
            ram_temp_stats=ram_temp_stats,
            storage_temp_drives=storage_temp_drives,
            storage_temp_stats=storage_temp_stats,
            gpu_temp_groups=gpu_temp_groups,
            gpu_metrics=gpu_metrics,
            gpu_observation_summary=gpu_observation_summary,
            gpu_power_stats=gpu_power_stats,
            gpu_clock_stats=gpu_clock_stats,
            gpu_memory_clock_stats=gpu_memory_clock_stats,
            gpu_usage_stats=gpu_usage_stats,
            gpu_memory_usage_stats=gpu_memory_usage_stats,
            gpu_vram_used_stats=gpu_vram_used_stats,
            gpu_targeting=gpu_targeting,
            worker_state_summary=worker_state_summary,
            stability_interpretation=stability_interpretation,
            empty_stats=self._metric_helper.empty_stats(),
        )
