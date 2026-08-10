#!/usr/bin/env python3
"""CPU backend preference normalization and selection policy."""

from __future__ import annotations

from typing import Dict


CPU_BACKEND_PREFERENCES = ("auto", "native", "stress_ng", "python_fallback")
CPU_BACKEND_IDENTITIES = {
    "native": "cpu_native_helper",
    "stress_ng": "stress_ng",
    "python_fallback": "python_fallback",
}
CPU_BACKEND_AUTO_ORDER = ("cpu_native_helper", "stress_ng", "python_fallback")


def normalize_cpu_backend_preference(value: str) -> str:
    normalized = str(value or "auto").strip().lower().replace("-", "_") or "auto"
    return normalized if normalized in CPU_BACKEND_PREFERENCES else "auto"


def select_cpu_backend(preference: str, availability: Dict[str, bool]) -> str:
    normalized = normalize_cpu_backend_preference(preference)
    if normalized != "auto":
        backend = CPU_BACKEND_IDENTITIES[normalized]
        return backend if availability.get(backend) else "none"
    for backend in CPU_BACKEND_AUTO_ORDER:
        if availability.get(backend):
            return backend
    return "none"
