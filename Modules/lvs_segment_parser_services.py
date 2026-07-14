from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .lvs_segment_cpu_clocks import CpuClockMetricSectionBuilder
from .lvs_segment_cpu_metrics import CpuMetricSectionBuilder
from .lvs_segment_document_builder import SegmentDocumentBuilder
from .lvs_segment_gpu_metrics import GpuMetricSectionBuilder
from .lvs_segment_gpu_targeting import GpuTargetingResolver
from .lvs_segment_gpu_worker_summary import GpuWorkerStateSummaryBuilder
from .lvs_segment_metric_context import SegmentMetricContextBuilder
from .lvs_segment_metric_helpers import SegmentMetricHelper
from .lvs_segment_temperature_metrics import TemperatureMetricSectionBuilder
from .lvs_stage_stability import StageStabilityInterpreter
from .lvs_worker_integrity import worker_integrity_error_count
from .lvs_gpu_backend_catalog import GPU_3D_BACKEND_CATALOG


WindowPredicateFn = Callable[[Any], bool]


@dataclass(frozen=True)
class SegmentParserServices:
    metric_helper: SegmentMetricHelper
    cpu_clocks: CpuClockMetricSectionBuilder
    cpu_metrics: CpuMetricSectionBuilder
    gpu_targeting: GpuTargetingResolver
    gpu_metrics: GpuMetricSectionBuilder
    gpu_worker_summary: GpuWorkerStateSummaryBuilder
    temperature_metrics: TemperatureMetricSectionBuilder
    stage_stability: StageStabilityInterpreter
    segment_metric_context: SegmentMetricContextBuilder
    segment_documents: SegmentDocumentBuilder
    worker_integrity_error_count: Callable[[list[dict[str, Any]]], int]


def build_segment_parser_services(window_has_operator_stop: WindowPredicateFn) -> SegmentParserServices:
    metric_helper = SegmentMetricHelper()
    cpu_clocks = CpuClockMetricSectionBuilder(
        metric_stats=metric_helper.metric_stats,
    )
    cpu_metrics = CpuMetricSectionBuilder(
        metric_stats=metric_helper.metric_stats,
        aggregate_core_clock_stats=cpu_clocks.aggregate_core_clock_stats,
    )
    gpu_targeting = GpuTargetingResolver(
        worker_integrity_error_count=worker_integrity_error_count,
    )
    gpu_metrics = GpuMetricSectionBuilder(
        metric_stats=metric_helper.metric_stats,
        metric_sustain_summary=metric_helper.metric_sustain_summary,
        gpu_display_name=gpu_targeting.display_name,
        duplicate_safe_gpu_name=gpu_targeting.duplicate_safe_name,
        should_blank_gpu_power_stats=metric_helper.should_blank_gpu_power_stats,
    )
    temperature_metrics = TemperatureMetricSectionBuilder(
        metric_stats=metric_helper.metric_stats,
        gpu_export_sort_key=gpu_targeting.export_sort_key,
        gpu_index_from_key=gpu_targeting.index_from_key,
        gpu_display_name=gpu_targeting.display_name,
        duplicate_safe_gpu_name=gpu_targeting.duplicate_safe_name,
    )
    stage_stability = StageStabilityInterpreter(
        window_has_operator_stop=window_has_operator_stop,
        worker_integrity_error_count=worker_integrity_error_count,
        gpu_load_quality_counts=gpu_metrics.load_quality_counts,
    )
    gpu_worker_summary = GpuWorkerStateSummaryBuilder()
    return SegmentParserServices(
        metric_helper=metric_helper,
        cpu_clocks=cpu_clocks,
        cpu_metrics=cpu_metrics,
        gpu_targeting=gpu_targeting,
        gpu_metrics=gpu_metrics,
        gpu_worker_summary=gpu_worker_summary,
        temperature_metrics=temperature_metrics,
        stage_stability=stage_stability,
        segment_metric_context=SegmentMetricContextBuilder(
            metric_helper=metric_helper,
            cpu_clocks=cpu_clocks,
            cpu_metrics=cpu_metrics,
            gpu_targeting=gpu_targeting,
            gpu_metrics=gpu_metrics,
            gpu_worker_summary=gpu_worker_summary,
            temperature_metrics=temperature_metrics,
            stage_stability=stage_stability,
        ),
        segment_documents=SegmentDocumentBuilder(GPU_3D_BACKEND_CATALOG),
        worker_integrity_error_count=worker_integrity_error_count,
    )
