from __future__ import annotations

from typing import Any, Dict, List, Optional

from .lvs_segment_formatting import format_analysis_window, format_segment_duration
from .lvs_segment_parser_services import build_segment_parser_services


class SegmentParser:
    def __init__(self, strict_threshold_recommendation_warnings: bool = False) -> None:
        self.strict_threshold_recommendation_warnings = bool(strict_threshold_recommendation_warnings)
        self._services = build_segment_parser_services(self._window_has_operator_stop)
        self._cpu_metrics = self._services.cpu_metrics
        self._gpu_targeting = self._services.gpu_targeting
        self._segment_metric_context = self._services.segment_metric_context
        self._segment_documents = self._services.segment_documents

    def _window_has_operator_stop(self, window: StageWindow) -> bool:
        return any(
            str(event.get("category") or "").strip().lower() == "operator_stop"
            for event in [*window.error_events, *window.system_faults]
            if isinstance(event, dict)
        )

    def _effective_strict_threshold_recommendation_warnings(self, window: StageWindow) -> bool:
        stage_override = getattr(window, "strict_threshold_recommendation_warnings", None)
        if stage_override is not None:
            return bool(stage_override)
        return bool(self.strict_threshold_recommendation_warnings)

    def summarize(
        self,
        windows: List[StageWindow],
        telemetry: TelemetryCollector,
        gpu_inventory: Optional[List[Dict[str, Any]]] = None,
        cpu_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        segment_details: Dict[str, Any] = {}
        segments: List[Dict[str, Any]] = []
        gpu_names = self._gpu_targeting.name_map(gpu_inventory or [], telemetry)
        gpu_order = self._gpu_targeting.order_map(gpu_inventory or [], telemetry)
        gpu_device_classes = self._gpu_targeting.device_class_map(gpu_inventory or [], telemetry)
        cpu_package_metadata = self._cpu_metrics.package_metadata(cpu_info or {})
        for idx, window in enumerate(windows, start=1):
            analysis_window = format_analysis_window(window)
            detail_key, detail, segment = self._segment_documents.build(
                self._segment_metric_context.build(
                    index=idx,
                    window=window,
                    telemetry=telemetry,
                    gpu_inventory=gpu_inventory or [],
                    gpu_names=gpu_names,
                    gpu_order=gpu_order,
                    gpu_device_classes=gpu_device_classes,
                    cpu_package_metadata=cpu_package_metadata,
                    duration=format_segment_duration(window.duration_seconds),
                    analysis_window=analysis_window,
                    strict_threshold_enabled=self._effective_strict_threshold_recommendation_warnings(window),
                )
            )
            segment_details[detail_key] = detail
            segments.append(segment)
        return {"SegmentDetails": segment_details, "Segments": segments}
