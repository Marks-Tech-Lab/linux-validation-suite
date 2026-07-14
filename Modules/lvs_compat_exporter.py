#!/usr/bin/env python3
"""Compatibility export adapter shared by CLI/TUI/GUI frontends."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .lvs_compat_export_builder import build_compatibility_export_document
from .lvs_compat_export_helpers import (
    gpu_detail_export_sort_key,
    gpu_source_device_class,
    gpu_temp_export_name,
    gpu_worker_backend_name,
    resolve_gpu_source_device_name,
    resolve_gpu_worker_device_name,
    run_manually_aborted,
    should_blank_gpu_power_source,
)
from .lvs_compat_export_gpu import (
    build_compatibility_gpu_section,
    build_gpu_power_details,
    build_gpu_worker_metric_test,
    build_gpu_worker_validation_detail,
)
from .lvs_core import APP_NAME, APP_VERSION
from .lvs_export_contract import build_export_contract
from .lvs_gpu_export_helpers import (
    enumerate_gpu_devices,
    gpu_device_entry_score,
    has_meaningful_gpu_value,
    merge_gpu_device_entries,
    normalize_gpu_interface,
)


class CompatibilityExporter:
    def __init__(self, app_name: str = APP_NAME, app_version: str = APP_VERSION) -> None:
        self.app_name = app_name
        self.app_version = app_version

    def _run_manually_aborted(self, windows: List[Any]) -> bool:
        return run_manually_aborted(windows)

    def build(
        self,
        metadata: Any,
        started_iso: str,
        ended_iso: str,
        elapsed_seconds: float,
        system_info: Dict[str, Any],
        parser_output: Dict[str, Any],
        telemetry: Any,
        windows: List[Any],
        recovery_report: Optional[Dict[str, Any]] = None,
        skipped_stages: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        gpu_power_details = self._build_gpu_power_details(system_info, telemetry)
        gpu_validation_details = self._normalized_gpu_worker_results(windows, system_info)
        export_contract = self._build_export_contract()
        return build_compatibility_export_document(
            metadata=metadata,
            started_iso=started_iso,
            ended_iso=ended_iso,
            elapsed_seconds=elapsed_seconds,
            system_info=system_info,
            parser_output=parser_output,
            windows=windows,
            samples=telemetry.samples,
            app_version=self.app_version,
            export_contract=export_contract,
            gpu_section=self._build_gpu_section(system_info, parser_output, windows),
            gpu_power_details=gpu_power_details,
            gpu_validation_details=gpu_validation_details,
            recovery_report=recovery_report,
            skipped_stages=skipped_stages,
        )

    def _build_export_contract(self) -> Dict[str, Any]:
        return build_export_contract(self.app_name, self.app_version)

    def _build_gpu_section(
        self,
        system_info: Dict[str, Any],
        parser_output: Dict[str, Any],
        windows: List[Any],
    ) -> Dict[str, Any]:
        segments = parser_output.get("Segments", [])
        return build_compatibility_gpu_section(
            gpu_devices=self._enumerate_gpu_devices(system_info["Hardware"].get("Gpu", [])),
            segments=segments,
            worker_metric_tests={
                "gpu_3d_errors": self._build_gpu_worker_metric_test(windows, system_info, "gpu_3d", "error_count"),
                "gpu_3d_api_errors": self._build_gpu_worker_metric_test(windows, system_info, "gpu_3d", "gl_error_count"),
                "gpu_3d_draw_mismatches": self._build_gpu_worker_metric_test(windows, system_info, "gpu_3d", "draw_mismatch_count"),
                "gpu_vram_errors": self._build_gpu_worker_metric_test(windows, system_info, "vram", "error_count"),
                "gpu_vram_api_errors": self._build_gpu_worker_metric_test(windows, system_info, "vram", "gl_error_count"),
                "gpu_vram_mismatches": self._build_gpu_worker_metric_test(windows, system_info, "vram", "vram_mismatch_count"),
                "gpu_vram_shortfall": self._build_gpu_worker_metric_test(windows, system_info, "vram", "allocation_shortfall_bytes"),
            },
        )

    def _enumerate_gpu_devices(self, gpus: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return enumerate_gpu_devices(gpus)

    def _merge_gpu_device_entries(
        self,
        primary: Dict[str, Any],
        candidate: Dict[str, Any],
        normalized_slot: str,
    ) -> Dict[str, Any]:
        return merge_gpu_device_entries(primary, candidate, normalized_slot)

    def _gpu_device_entry_score(self, gpu: Dict[str, Any]) -> int:
        return gpu_device_entry_score(gpu)

    def _has_meaningful_gpu_value(self, value: Any) -> bool:
        return has_meaningful_gpu_value(value)

    def _normalize_gpu_interface(self, value: Any) -> str:
        return normalize_gpu_interface(value)

    def _gpu_temp_export_name(self, gpu: Dict[str, Any]) -> str:
        return gpu_temp_export_name(gpu)

    def _build_gpu_power_details(
        self,
        system_info: Dict[str, Any],
        telemetry: Any,
    ) -> Optional[List[Dict[str, Any]]]:
        return build_gpu_power_details(
            gpu_sources=telemetry._gpu_sources,
            samples=telemetry.samples,
            should_blank_source=lambda source, values: self._should_blank_gpu_power_source(source, system_info, values),
            source_device_name=lambda source: self._resolve_gpu_source_device_name(source, system_info),
            sort_key=lambda item: self._gpu_detail_export_sort_key(item, system_info),
        )

    def _should_blank_gpu_power_source(
        self,
        source: Dict[str, Any],
        system_info: Dict[str, Any],
        values: List[Any],
    ) -> bool:
        return should_blank_gpu_power_source(
            source,
            self._enumerate_gpu_devices(system_info.get("Hardware", {}).get("Gpu", [])),
            values,
        )

    def _gpu_source_device_class(
        self,
        source: Dict[str, Any],
        system_info: Dict[str, Any],
    ) -> str:
        return gpu_source_device_class(
            source,
            self._enumerate_gpu_devices(system_info.get("Hardware", {}).get("Gpu", [])),
        )

    def _gpu_detail_export_sort_key(
        self,
        item: Dict[str, Any],
        system_info: Dict[str, Any],
    ) -> tuple[int, str]:
        return gpu_detail_export_sort_key(
            item,
            self._enumerate_gpu_devices(system_info.get("Hardware", {}).get("Gpu", [])),
        )

    def _resolve_gpu_source_device_name(
        self,
        source: Dict[str, Any],
        system_info: Dict[str, Any],
    ) -> str:
        return resolve_gpu_source_device_name(
            source,
            self._enumerate_gpu_devices(system_info.get("Hardware", {}).get("Gpu", [])),
        )

    def _normalized_gpu_worker_results(
        self,
        windows: List[Any],
        system_info: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        details: List[Dict[str, Any]] = []
        stage_order = {window.display_name: index for index, window in enumerate(windows)}
        for window in windows:
            for payload in window.worker_results:
                if str(payload.get("kind") or "").lower() != "gpu":
                    continue
                details.append(
                    build_gpu_worker_validation_detail(
                        stage_name=window.display_name,
                        stage_type=window.stage_type,
                        stage_verdict=window.verdict,
                        payload=payload,
                        backend_name=self._gpu_worker_backend_name(payload),
                        device_name=self._resolve_gpu_worker_device_name(payload, system_info),
                    )
                )
        return sorted(
            details,
            key=lambda item: (
                stage_order.get(str(item.get("Stage") or ""), 9999),
                self._gpu_detail_export_sort_key(item, system_info),
            ),
        )

    def _gpu_worker_backend_name(self, payload: Dict[str, Any]) -> str:
        return gpu_worker_backend_name(payload)

    def _resolve_gpu_worker_device_name(
        self,
        payload: Dict[str, Any],
        system_info: Dict[str, Any],
    ) -> str:
        return resolve_gpu_worker_device_name(
            payload,
            self._enumerate_gpu_devices(system_info.get("Hardware", {}).get("Gpu", [])),
        )

    def _build_gpu_worker_metric_test(
        self,
        windows: List[Any],
        system_info: Dict[str, Any],
        mode: str,
        metric_key: str,
    ) -> List[Dict[str, Any]]:
        return build_gpu_worker_metric_test(
            windows=windows,
            mode=mode,
            metric_key=metric_key,
            device_name_resolver=lambda payload: self._resolve_gpu_worker_device_name(payload, system_info),
        )
