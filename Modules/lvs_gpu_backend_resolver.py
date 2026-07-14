#!/usr/bin/env python3
"""GPU backend support summary and resolution helpers."""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional


TargetSupportCallback = Callable[[str, Optional[Dict[str, Any]], str], Dict[str, Any]]
BackendAvailabilityCallback = Callable[[str, str], bool]
BackendSupportSummaryCallback = Callable[[str, List[Dict[str, Any]], str], Dict[str, Any]]


def gpu_backend_support_summary(
    *,
    backend: str,
    targets: List[Dict[str, Any]],
    workload: str,
    target_support: TargetSupportCallback,
) -> Dict[str, Any]:
    target_list: Iterable[Optional[Dict[str, Any]]] = targets or [None]
    supported_targets: List[Dict[str, Any]] = []
    unsupported_targets: List[Dict[str, Any]] = []
    for target in target_list:
        report = target_support(backend, target, workload)
        if report.get("supported"):
            supported_targets.append(report)
        else:
            unsupported_targets.append(report)
    return {
        "backend": backend,
        "workload": workload,
        "supported": not unsupported_targets,
        "supported_targets": supported_targets,
        "unsupported_targets": unsupported_targets,
    }


def resolve_gpu_backend_for_targets(
    *,
    candidates: List[str],
    targets: List[Dict[str, Any]],
    workload: str,
    backend_available: BackendAvailabilityCallback,
    support_summary: BackendSupportSummaryCallback,
) -> Dict[str, Any]:
    candidate_reports: List[Dict[str, Any]] = []
    best_partial_report: Optional[Dict[str, Any]] = None
    for backend in candidates:
        available = backend_available(backend, workload)
        if not available:
            candidate_reports.append(
                {
                    "backend": backend,
                    "available": False,
                    "support": None,
                }
            )
            continue
        support = support_summary(backend, targets, workload)
        candidate_reports.append(
            {
                "backend": backend,
                "available": True,
                "support": support,
            }
        )
        if support.get("supported"):
            return {
                "backend": backend,
                "candidate_reports": candidate_reports,
                "support": support,
                "partial": False,
            }
        if support.get("supported_targets"):
            if best_partial_report is None or len(support.get("supported_targets", [])) > len((best_partial_report.get("support") or {}).get("supported_targets", [])):
                best_partial_report = {
                    "backend": backend,
                    "candidate_reports": list(candidate_reports),
                    "support": support,
                    "partial": True,
                }
    if best_partial_report is not None:
        return best_partial_report
    return {
        "backend": "none",
        "candidate_reports": candidate_reports,
        "support": None,
        "partial": False,
    }
