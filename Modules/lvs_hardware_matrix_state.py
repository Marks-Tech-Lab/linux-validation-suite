"""Local hardware/result validation matrix state helpers.

The committed hardware matrix is a public coverage definition. This module
handles optional ignored local state that can map those categories to retained
result folders on a maintainer workstation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


MATRIX_CONTRACT_ID = "linux_validation_suite.hardware_result_validation_matrix"
STATE_CONTRACT_ID = "linux_validation_suite.hardware_result_validation_state"
STATE_CONTRACT_VERSION = 1
DEFAULT_STATE_FILE = "hardware_result_validation_state.json"
DEFAULT_MATRIX_FILE = "hardware_result_validation_matrix.json"


def load_hardware_matrix(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def matrix_categories(matrix: dict[str, Any]) -> set[str]:
    entries = matrix.get("entries") if isinstance(matrix.get("entries"), list) else []
    return {str(entry.get("category")) for entry in entries if isinstance(entry, dict) and entry.get("category")}


def matrix_state_file(matrix: dict[str, Any]) -> str:
    state_file = matrix.get("local_state_file")
    return str(state_file) if state_file else DEFAULT_STATE_FILE


def empty_hardware_matrix_state(matrix: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_id": STATE_CONTRACT_ID,
        "contract_version": STATE_CONTRACT_VERSION,
        "kind": "local_retained_result_state",
        "generated": True,
        "entries": [
            {
                "category": category,
                "status": "missing",
                "missing_reason": "no local retained result mapped",
            }
            for category in sorted(matrix_categories(matrix))
        ],
    }


def normalize_hardware_matrix_state(state: dict[str, Any], matrix: dict[str, Any]) -> dict[str, Any]:
    categories = matrix_categories(matrix)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()

    entries = state.get("entries") if isinstance(state.get("entries"), list) else []
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        category = str(raw_entry.get("category") or "")
        if not category or category not in categories or category in seen:
            continue
        entry = dict(raw_entry)
        status = str(entry.get("status") or "missing")
        if status == "available":
            status = "confirmed"
        if status not in {"confirmed", "missing", "stale", "candidate"}:
            status = "missing"
        entry["status"] = status
        if status == "missing" and not entry.get("missing_reason"):
            entry["missing_reason"] = "no local retained result mapped"
        normalized.append(entry)
        seen.add(category)

    for category in sorted(categories - seen):
        normalized.append(
            {
                "category": category,
                "status": "missing",
                "missing_reason": "no local retained result mapped",
            }
        )

    normalized.sort(key=lambda item: str(item.get("category") or ""))
    return {
        "contract_id": STATE_CONTRACT_ID,
        "contract_version": STATE_CONTRACT_VERSION,
        "kind": "local_retained_result_state",
        "generated": bool(state.get("generated", True)),
        "entries": normalized,
    }


def load_hardware_matrix_state(path: Path, matrix: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return empty_hardware_matrix_state(matrix)
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return empty_hardware_matrix_state(matrix)
    if not isinstance(data, dict):
        return empty_hardware_matrix_state(matrix)
    return normalize_hardware_matrix_state(data, matrix)


def result_dir_has_required_artifacts(result_dir: Path) -> bool:
    return result_dir.is_dir() and (result_dir / "parsed_results_custom.json").is_file()


def validate_hardware_matrix_state(state: dict[str, Any], root: Path) -> dict[str, Any]:
    confirmed: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []

    entries = state.get("entries") if isinstance(state.get("entries"), list) else []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status") or "missing")
        if status in {"confirmed", "available"}:
            result_dir = root / str(entry.get("path") or "")
            if result_dir_has_required_artifacts(result_dir):
                confirmed.append(entry)
            else:
                stale_entry = dict(entry)
                stale_entry["status"] = "stale"
                stale_entry["stale_reason"] = "result folder or parsed_results_custom.json is missing"
                stale.append(stale_entry)
        elif status == "candidate":
            candidates.append(entry)
        else:
            missing.append(entry)

    return {
        "confirmed": confirmed,
        "missing": missing,
        "stale": stale,
        "candidates": candidates,
        "counts": {
            "confirmed_valid": len(confirmed),
            "missing": len(missing),
            "stale": len(stale),
            "candidate": len(candidates),
        },
    }


def prune_stale_hardware_matrix_state(state: dict[str, Any], root: Path) -> dict[str, Any]:
    pruned_entries: list[dict[str, Any]] = []
    entries = state.get("entries") if isinstance(state.get("entries"), list) else []
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        entry = dict(raw_entry)
        status = str(entry.get("status") or "missing")
        if status in {"confirmed", "available", "candidate"} and entry.get("path"):
            result_dir = root / str(entry.get("path") or "")
            if not result_dir_has_required_artifacts(result_dir):
                entry = {
                    "category": entry.get("category"),
                    "status": "missing",
                    "missing_reason": "retained result path was stale and was pruned",
                    "previous_path": entry.get("path"),
                }
        pruned_entries.append(entry)

    pruned = dict(state)
    pruned["entries"] = pruned_entries
    return pruned


def discover_hardware_matrix_state(
    matrix: dict[str, Any],
    results_dir: Path,
    existing_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = normalize_hardware_matrix_state(existing_state or empty_hardware_matrix_state(matrix), matrix)
    entries_by_category = {
        str(entry.get("category")): dict(entry)
        for entry in state.get("entries", [])
        if isinstance(entry, dict) and entry.get("category")
    }

    parsed_paths = sorted(results_dir.rglob("parsed_results_custom.json")) if results_dir.exists() else []
    for parsed_path in parsed_paths:
        result_dir = parsed_path.parent
        evidence = _result_discovery_evidence(result_dir, parsed_path)
        for category, confidence in _category_matches_for_evidence(evidence).items():
            current = entries_by_category.get(category)
            if current and current.get("status") in {"confirmed", "available"}:
                continue
            if current and current.get("status") == "candidate" and confidence == "candidate":
                continue
            rel_path = result_dir.as_posix()
            try:
                rel_path = result_dir.relative_to(results_dir.parent).as_posix()
            except ValueError:
                pass
            entries_by_category[category] = {
                "category": category,
                "status": confidence,
                "path": rel_path,
                "source": "local_discovery",
                "evidence": evidence,
            }

    return normalize_hardware_matrix_state({"entries": list(entries_by_category.values()), "generated": True}, matrix)


def rebuild_hardware_matrix_state(matrix: dict[str, Any], results_dir: Path) -> dict[str, Any]:
    return discover_hardware_matrix_state(matrix, results_dir, empty_hardware_matrix_state(matrix))


def refresh_hardware_matrix_state(root: Path) -> dict[str, Any]:
    """Prune, discover, and save optional retained-result state below *root*."""
    root = root.resolve()
    matrix_path = root / DEFAULT_MATRIX_FILE
    matrix = load_hardware_matrix(matrix_path)
    if not matrix or not matrix_categories(matrix):
        raise ValueError(f"hardware matrix is missing or invalid: {matrix_path}")

    state_path = root / matrix_state_file(matrix)
    if state_path.exists():
        try:
            raw_state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"existing hardware matrix state is unreadable: {state_path}") from exc
        if not isinstance(raw_state, dict):
            raise ValueError(f"existing hardware matrix state is not a JSON object: {state_path}")
        existing_state = normalize_hardware_matrix_state(raw_state, matrix)
    else:
        existing_state = empty_hardware_matrix_state(matrix)

    stale_count = _count_stale_path_mappings(existing_state, root)
    pruned_state = prune_stale_hardware_matrix_state(existing_state, root)
    discovered_state = discover_hardware_matrix_state(matrix, root / "results", pruned_state)
    state_path.write_text(json.dumps(discovered_state, indent=2) + "\n", encoding="utf-8")

    counts = validate_hardware_matrix_state(discovered_state, root)["counts"]
    return {
        "confirmed": counts["confirmed_valid"],
        "missing": counts["missing"],
        "stale_pruned": stale_count,
        "candidate": counts["candidate"],
        "state_file": str(state_path),
    }


def _count_stale_path_mappings(state: dict[str, Any], root: Path) -> int:
    entries = state.get("entries") if isinstance(state.get("entries"), list) else []
    return sum(
        1
        for entry in entries
        if isinstance(entry, dict)
        and str(entry.get("status") or "missing") in {"confirmed", "available", "candidate"}
        and entry.get("path")
        and not result_dir_has_required_artifacts(root / str(entry.get("path")))
    )


def _result_discovery_evidence(result_dir: Path, parsed_path: Path) -> dict[str, Any]:
    parsed = _read_json(parsed_path)
    manifest = _read_json(result_dir / "run_manifest.json")
    source_map = _read_json(result_dir / "telemetry_source_map.json")
    text = json.dumps({"parsed": parsed, "manifest": manifest, "source_map": source_map}, sort_keys=True).lower()

    profile = _first_string(
        parsed,
        (
            ("Metadata", "ProfileName"),
            ("Metadata", "Profile"),
            ("RunSummary", "ProfileName"),
            ("ProfileName",),
            ("profile_name",),
        ),
    )
    result = _first_string(
        parsed,
        (
            ("FinalResult",),
            ("Result",),
            ("Metadata", "Result"),
            ("Metadata", "ReportSummary", "Result"),
            ("ReportSummary", "Result"),
        ),
    )
    outcome = _first_string(
        parsed,
        (
            ("OutcomeClass",),
            ("Metadata", "ReportSummary", "OutcomeClass"),
            ("ReportSummary", "OutcomeClass"),
            ("StabilityInterpretation", "OutcomeClass"),
        ),
    )
    package_count = _first_int(
        parsed,
        (
            ("Cpu", "PackageCount"),
            ("SystemInfo", "Cpu", "PackageCount"),
            ("SystemInfo", "Hardware", "Cpu", "PackageCount"),
            ("SystemInfo", "Hardware", "PackageCount"),
        ),
    )
    telemetry_privilege = _telemetry_privilege_evidence(manifest, source_map)
    structured_gpu_text = json.dumps(
        {
            "gpu": parsed.get("Gpu"),
            "gpu_details": parsed.get("GpuDetails"),
            "system_gpu": _nested_value(parsed, ("SystemInfo", "Gpu")),
            "metadata_dgpu": _nested_value(parsed, ("Metadata", "DgpuName")),
            "metadata_dgpus": _nested_value(parsed, ("Metadata", "DiscreteGpuNames")),
        },
        sort_keys=True,
    ).lower()
    explicit_clean = _looks_clean(result, outcome, "")
    explicit_warning_or_failure = _looks_warning_or_failure(result, outcome, "")
    return {
        "profile": profile,
        "result": result,
        "outcome_class": outcome,
        "package_count": package_count,
        "telemetry_privilege": telemetry_privilege,
        "has_nvidia": "nvidia" in text,
        "has_nvidia_structured": "nvidia" in structured_gpu_text,
        "has_amd_gpu": "radeon" in text or "amd gpu" in text or "vddgfx" in text,
        "has_amd_gpu_structured": any(
            token in structured_gpu_text for token in ("radeon", "amd gpu", "advanced micro devices")
        ),
        "has_integrated_gpu": "igpu" in text or "integrated gpu" in text or "intel graphics" in text,
        "has_integrated_gpu_structured": any(
            token in structured_gpu_text for token in ("igpu", "integrated gpu", "intel graphics")
        ),
        "has_heatsoak": "heatsoak" in text,
        "has_heatsoak_explicit": _explicit_heatsoak_enabled(parsed, manifest),
        "has_gpu": "gpu" in text,
        "has_vram": "vram" in text,
        "is_clean": _looks_clean(result, outcome, text),
        "is_clean_explicit": explicit_clean,
        "is_warning_or_failure": _looks_warning_or_failure(result, outcome, text),
        "is_warning_or_failure_explicit": explicit_warning_or_failure,
    }


def _categories_for_evidence(evidence: dict[str, Any]) -> list[str]:
    return list(_category_matches_for_evidence(evidence))


def _category_matches_for_evidence(evidence: dict[str, Any]) -> dict[str, str]:
    matches: dict[str, str] = {}
    clean = bool(evidence.get("is_clean"))
    clean_explicit = bool(evidence.get("is_clean_explicit"))
    warning_or_failure = bool(evidence.get("is_warning_or_failure"))
    warning_or_failure_explicit = bool(evidence.get("is_warning_or_failure_explicit"))
    package_count = evidence.get("package_count")
    privilege = evidence.get("telemetry_privilege") if isinstance(evidence.get("telemetry_privilege"), dict) else {}
    source_mode = str(privilege.get("source_mode") or "").lower()

    if package_count == 1 and clean:
        matches["single_cpu_clean_run"] = "confirmed" if clean_explicit else "candidate"
    if isinstance(package_count, int) and package_count >= 2:
        matches["dual_cpu_package_topology_run"] = "confirmed"
    if evidence.get("has_nvidia") and clean:
        matches["nvidia_dgpu_clean_run"] = (
            "confirmed" if evidence.get("has_nvidia_structured") and clean_explicit else "candidate"
        )
    if evidence.get("has_nvidia") and warning_or_failure:
        matches["nvidia_dgpu_warning_failure_run"] = (
            "confirmed"
            if evidence.get("has_nvidia_structured") and warning_or_failure_explicit
            else "candidate"
        )
    if evidence.get("has_amd_gpu") or evidence.get("has_integrated_gpu"):
        structured_gpu = evidence.get("has_amd_gpu_structured") or evidence.get("has_integrated_gpu_structured")
        matches["amd_gpu_or_igpu_run"] = "confirmed" if structured_gpu else "candidate"
    if source_mode in {"sudo_telemetry", "root_process", "privileged"} or privilege.get("sudo_sources_used") is True:
        matches["privileged_telemetry_run"] = "confirmed"
    if source_mode == "unprivileged" or privilege.get("sudo_sources_used") is False:
        matches["no_privileged_telemetry_run"] = "confirmed"
    if evidence.get("has_heatsoak"):
        matches["heatsoak_run"] = "confirmed" if evidence.get("has_heatsoak_explicit") else "candidate"
    if evidence.get("has_gpu") and evidence.get("has_vram") and warning_or_failure:
        matches["gpu_vram_warning_failure_case"] = "candidate"
    if clean:
        matches["clean_passing_run"] = "confirmed" if clean_explicit else "candidate"

    return matches


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _first_string(data: dict[str, Any], paths: tuple[tuple[str, ...], ...]) -> str | None:
    for path in paths:
        value: Any = data
        for key in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _first_int(data: dict[str, Any], paths: tuple[tuple[str, ...], ...]) -> int | None:
    for path in paths:
        value: Any = data
        for key in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        if isinstance(value, int):
            return value
    return None


def _telemetry_privilege_evidence(manifest: dict[str, Any], source_map: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        _nested_dict(manifest, ("telemetry_capabilities", "telemetry_privilege")),
        _nested_dict(source_map, ("telemetry_privilege",)),
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    return {}


def _nested_dict(data: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    value: Any = data
    for key in path:
        if not isinstance(value, dict):
            return {}
        value = value.get(key)
    return value if isinstance(value, dict) else {}


def _nested_value(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = data
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _explicit_heatsoak_enabled(parsed: dict[str, Any], manifest: dict[str, Any]) -> bool:
    values = (
        _nested_value(parsed, ("Heatsoak", "Enabled")),
        _nested_value(parsed, ("Metadata", "HeatsoakEnabled")),
        _nested_value(parsed, ("Metadata", "Heatsoak", "Enabled")),
        _nested_value(manifest, ("heatsoak", "enabled")),
        _nested_value(manifest, ("heatsoak_enabled",)),
    )
    return any(value is True or (isinstance(value, (int, float)) and value > 0) for value in values)


def _looks_clean(result: str | None, outcome: str | None, text: str) -> bool:
    joined = " ".join(value.lower() for value in (result, outcome) if value)
    if any(token in joined for token in ("fail", "error", "warning", "warn", "aborted", "cancel")):
        return False
    if any(token in joined for token in ("pass", "passed", "clean", "success", "completed")):
        return True
    return "no issues found" in text or "all evaluated rules passed" in text


def _looks_warning_or_failure(result: str | None, outcome: str | None, text: str) -> bool:
    joined = " ".join(value.lower() for value in (result, outcome) if value)
    return any(token in joined for token in ("fail", "failed", "error", "warning", "warn"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Maintain optional local hardware validation matrix state.")
    parser.add_argument("command", choices=("rebuild",))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        summary = refresh_hardware_matrix_state(args.root)
    except (OSError, ValueError) as exc:
        print(f"hardware matrix state rebuild failed: {exc}", file=sys.stderr)
        return 1

    print(f"confirmed: {summary['confirmed']}")
    print(f"missing: {summary['missing']}")
    print(f"stale/pruned: {summary['stale_pruned']}")
    print(f"candidate: {summary['candidate']}")
    print(f"state file: {summary['state_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
