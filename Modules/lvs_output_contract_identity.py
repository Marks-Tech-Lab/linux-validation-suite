#!/usr/bin/env python3
"""Formal identity constants and stamping for standalone LVS artifacts."""

from __future__ import annotations

from typing import Any, Dict


CONTRACT_VERSION = 1

RUN_MANIFEST_CONTRACT_ID = "linux_validation_suite.run_manifest"
RUN_MANIFEST_KIND = "run_manifest"

DEPENDENCY_CHECK_CONTRACT_ID = "linux_validation_suite.dependency_check"
DEPENDENCY_CHECK_KIND = "dependency_check"

TELEMETRY_SOURCE_MAP_CONTRACT_ID = "linux_validation_suite.telemetry_source_map"
TELEMETRY_SOURCE_MAP_KIND = "telemetry_source_map"


def stamp_contract_identity(payload: Dict[str, Any], *, contract_id: str, kind: str) -> Dict[str, Any]:
    """Set the formal identity of an LVS-owned standalone artifact."""

    payload["contract_id"] = contract_id
    payload["contract_version"] = CONTRACT_VERSION
    payload["kind"] = kind
    return payload
