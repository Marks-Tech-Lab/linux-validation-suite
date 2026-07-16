"""Output-schema safety helpers used by the smoke suite.

These checks distinguish LVS-owned schema properties from explicitly embedded
legacy or external payloads. They do not normalize or rewrite artifacts.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


SNAKE_CASE_KEY = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")

LEGACY_PARSER_FACING_FIELDS = {
    "Segments",
    "SegmentDetails",
    "Metadata",
    "SystemInfo",
    "Motherboard",
    "Memory",
    "Storage",
    "Gpu",
    "Cpu",
    "CpuCores",
}

LEGACY_ADDITIVE_FIELDS = {
    "ExportContract",
    "ReportSummary",
    "StabilityInterpretation",
}

LEGACY_EXPORT_CONTRACT_FIELDS = {
    "Schema",
    "Producer",
    "ProducerVersion",
    "ReferenceProject",
    "ReferenceExporter",
    "ReferenceImporter",
    "CompatibilityMode",
    "ParserSafeAdditiveFields",
    "RequiresLegacyImporterUpdate",
    "Policy",
    "StableConsumerFields",
}

LEGACY_REPORT_SUMMARY_FIELDS = {
    "Schema",
    "ReferenceContract",
    "Result",
    "StageCount",
    "StageOutcomes",
    "GpuWorkerSummary",
    "ActionItems",
    "ActionItemDetails",
    "ActionItemCategoryCounts",
    "ActionItemSeverityCounts",
    "ImportNotes",
}

QA_REVIEW_REQUIRED_FIELDS = {
    "app_name",
    "app_version",
    "contract_id",
    "contract_version",
    "kind",
    "started",
    "ended",
    "result_folder",
    "identity",
    "decisions",
    "validation_status",
    "validation",
    "import_readiness",
    "pre_import_sanity",
    "summary_refresh",
    "comparison_readiness",
    "comparison",
    "artifact_availability",
    "worker_failure_evidence",
    "action_item_summary",
    "telemetry_stability_warning_summary",
}

QA_BATCH_REQUIRED_FIELDS = {
    "app_name",
    "app_version",
    "contract_id",
    "contract_version",
    "kind",
    "started",
    "ended",
    "results_dir",
    "counts",
    "items",
}


def _path_matches(path: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    return len(path) == len(pattern) and all(
        expected == "*" or expected == actual
        for actual, expected in zip(path, pattern)
    )


def assert_snake_case_keys(
    payload: Any,
    *,
    excluded_subtrees: Iterable[tuple[str, ...]] = (),
    label: str = "payload",
) -> None:
    """Assert recursively that LVS-owned dictionary keys use snake_case.

    ``excluded_subtrees`` is an explicit boundary allowlist. A ``*`` component
    matches a list index or a dynamic dictionary key at that path depth.
    """

    exclusions = tuple(tuple(pattern) for pattern in excluded_subtrees)
    violations: list[str] = []

    def walk(value: Any, path: tuple[str, ...]) -> None:
        if any(_path_matches(path, pattern) for pattern in exclusions):
            return
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key)
                child_path = (*path, key_text)
                if not SNAKE_CASE_KEY.fullmatch(key_text):
                    violations.append(".".join(child_path))
                walk(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, (*path, str(index)))

    walk(payload, ())
    assert not violations, f"{label} has non-snake_case LVS keys: {violations}"


def assert_contract_identity(
    payload: dict[str, Any],
    *,
    contract_id: str,
    contract_version: int,
    kind: str,
    label: str,
) -> None:
    """Protect the required identity of a versioned LVS external contract."""

    assert payload.get("contract_id") == contract_id, f"{label} contract_id changed"
    assert payload.get("contract_version") == contract_version, f"{label} contract_version changed"
    assert payload.get("kind") == kind, f"{label} kind changed"


def assert_required_fields(payload: dict[str, Any], fields: set[str], *, label: str) -> None:
    """Detect accidental removal or renaming of required contract properties."""

    missing = sorted(fields.difference(payload))
    assert not missing, f"{label} is missing required fields: {missing}"


def assert_legacy_custom_result_contract(
    payload: dict[str, Any],
    *,
    require_report_summary_alias: bool = False,
) -> None:
    """Protect exact OCCT/custom-result compatibility names and mirrors."""

    assert_required_fields(
        payload,
        LEGACY_PARSER_FACING_FIELDS | LEGACY_ADDITIVE_FIELDS,
        label="parsed_results_custom.json",
    )
    export_contract = payload.get("ExportContract")
    assert isinstance(export_contract, dict), "legacy ExportContract must remain an object"
    assert_required_fields(
        export_contract,
        LEGACY_EXPORT_CONTRACT_FIELDS,
        label="parsed_results_custom.json ExportContract",
    )
    assert export_contract.get("RequiresLegacyImporterUpdate") is False, (
        "legacy compatibility must not require an importer update"
    )

    report_summary = payload.get("ReportSummary")
    assert isinstance(report_summary, dict), "legacy ReportSummary must remain an object"
    assert_required_fields(
        report_summary,
        LEGACY_REPORT_SUMMARY_FIELDS,
        label="parsed_results_custom.json ReportSummary",
    )
    metadata = payload.get("Metadata")
    assert isinstance(metadata, dict), "legacy Metadata must remain an object"
    assert metadata.get("ExportContract") == export_contract, "Metadata.ExportContract mirror changed"
    assert metadata.get("ReportSummary") == report_summary, "Metadata.ReportSummary mirror changed"
    if require_report_summary_alias:
        assert payload.get("report_summary") == report_summary, "report_summary compatibility alias changed"

