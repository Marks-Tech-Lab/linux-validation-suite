#!/usr/bin/env python3
"""Result-folder validation check helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


EXPECTED_SUPPORT_FILES = [
    "run_summary.txt",
    "run_manifest.json",
    "run_metadata.json",
    "profile_used.json",
    "system_info.json",
]

OPTIONAL_SUPPORT_FILES = [
    "extended_results.json",
    "raw_telemetry.csv",
]


def result_profile_name_candidates(parsed: Dict[str, Any]) -> List[str]:
    parsed = parsed if isinstance(parsed, dict) else {}
    metadata = parsed.get("Metadata") if isinstance(parsed.get("Metadata"), dict) else {}
    system_info = parsed.get("SystemInfo") if isinstance(parsed.get("SystemInfo"), dict) else {}
    test_info = system_info.get("TestInfo") if isinstance(system_info.get("TestInfo"), dict) else {}
    raw_candidates = [
        parsed.get("ProfileName"),
        parsed.get("profile_name"),
        metadata.get("ProfileName"),
        metadata.get("Profile"),
    ]
    config_file = (
        metadata.get("TestConfigFile")
        or metadata.get("ConfigFile")
        or test_info.get("ConfigFile")
        or parsed.get("ConfigFile")
    )
    if config_file:
        raw_candidates.append(Path(str(config_file)).stem)
    for value in (
        parsed.get("TestName"),
        metadata.get("TestName"),
        metadata.get("ProfileDisplayName"),
        test_info.get("TestName"),
    ):
        if value:
            raw_candidates.append(value)
            text = str(value).strip()
            suffix = " Linux Validation"
            if text.endswith(suffix):
                raw_candidates.append(text[: -len(suffix)].strip())
    candidates: List[str] = []
    seen: set[str] = set()
    for value in raw_candidates:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        candidates.append(text)
    return candidates


def profile_name_matches_result(profile_name: str, result_candidates: List[str]) -> bool:
    normalized_profile = str(profile_name or "").strip().lower()
    if not normalized_profile:
        return False
    return any(normalized_profile == str(candidate or "").strip().lower() for candidate in result_candidates)


def validate_support_files(
    result_dir: Path,
    parsed: Dict[str, Any],
    summary_exporter: Any,
) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    missing_support = [name for name in EXPECTED_SUPPORT_FILES if not (result_dir / name).exists()]
    present_support = [
        name
        for name in EXPECTED_SUPPORT_FILES + OPTIONAL_SUPPORT_FILES
        if (result_dir / name).exists()
    ]
    support_files_check = {
        "expected": list(EXPECTED_SUPPORT_FILES),
        "optional": list(OPTIONAL_SUPPORT_FILES),
        "present": present_support,
        "missing": missing_support,
        "ok": not missing_support,
    }
    for name in missing_support:
        issues.append(
            {
                "severity": "warning",
                "category": "support_files",
                "message": f"{name} is missing from the result folder",
                "details": {},
            }
        )

    run_summary_path = result_dir / "run_summary.txt"
    run_summary_check = {
        "present": run_summary_path.exists(),
        "empty": False,
        "current": None,
        "readable": True,
    }
    if run_summary_path.exists():
        try:
            run_summary_text = run_summary_path.read_text(encoding="utf-8")
            if not run_summary_text.strip():
                run_summary_check["empty"] = True
                issues.append(
                    {
                        "severity": "warning",
                        "category": "support_files",
                        "message": "run_summary.txt exists but is empty",
                        "details": {},
                    }
                )
            else:
                expected_summary_text = summary_exporter.build(parsed)
                run_summary_check["current"] = run_summary_text == expected_summary_text
                if not run_summary_check["current"]:
                    issues.append(
                        {
                            "severity": "warning",
                            "category": "support_files",
                            "message": "run_summary.txt does not match the current parsed_results_custom.json summary",
                            "details": {},
                        }
                    )
        except Exception as exc:
            run_summary_check["readable"] = False
            issues.append(
                {
                    "severity": "warning",
                    "category": "support_files",
                    "message": f"run_summary.txt could not be read: {exc}",
                    "details": {},
                }
            )

    return {
        "checks": {
            "support_files": support_files_check,
            "run_summary": run_summary_check,
        },
        "issues": issues,
    }


def validate_profile_used(result_dir: Path, parsed: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    profile_used_path = result_dir / "profile_used.json"
    profile_used_check: Dict[str, Any] = {
        "present": profile_used_path.exists(),
        "readable": True,
        "profile_name": "",
        "stage_count": 0,
        "enabled_stage_count": 0,
        "matches_result_profile_name": None,
        "matches_segment_count": None,
        "duration_mismatches": [],
    }
    if profile_used_path.exists():
        try:
            loaded_profile = json.loads(profile_used_path.read_text(encoding="utf-8"))
            if not isinstance(loaded_profile, dict):
                raise ValueError("profile_used.json root is not an object")
            profile_used_check["profile_name"] = str(loaded_profile.get("profile_name") or "")
            profile_stages = loaded_profile.get("stages") if isinstance(loaded_profile.get("stages"), list) else []
            enabled_profile_stages = [
                stage
                for stage in profile_stages
                if isinstance(stage, dict) and bool(stage.get("enabled", True))
            ]
            profile_used_check["stage_count"] = len(profile_stages)
            profile_used_check["enabled_stage_count"] = len(enabled_profile_stages)
            result_profile_names = result_profile_name_candidates(parsed)
            profile_used_check["result_profile_name_candidates"] = result_profile_names
            if result_profile_names:
                profile_used_check["matches_result_profile_name"] = profile_name_matches_result(
                    profile_used_check["profile_name"],
                    result_profile_names,
                )
                if not profile_used_check["matches_result_profile_name"]:
                    issues.append(
                        {
                            "severity": "warning",
                            "category": "profile_used",
                            "message": "profile_used.json profile_name does not match result profile name",
                            "details": {
                                "profile_used": profile_used_check["profile_name"],
                                "result_candidates": result_profile_names,
                            },
                        }
                    )
            parsed_segments = parsed.get("Segments") if isinstance(parsed.get("Segments"), list) else []
            profile_used_check["matches_segment_count"] = len(enabled_profile_stages) == len(parsed_segments)
            if not profile_used_check["matches_segment_count"]:
                result_state = str(parsed.get("Result") or parsed.get("result") or "").strip().lower()
                aborted_partial_run = (
                    result_state in {"aborted", "manually_aborted", "manual_abort"}
                    and len(parsed_segments) <= len(enabled_profile_stages)
                )
                profile_used_check["partial_segment_count_expected"] = aborted_partial_run
                if not aborted_partial_run:
                    issues.append(
                        {
                            "severity": "warning",
                            "category": "profile_used",
                            "message": "profile_used.json enabled stage count does not match parsed Segments count",
                            "details": {
                                "profile_used_enabled_stages": len(enabled_profile_stages),
                                "segments": len(parsed_segments),
                            },
                        }
                    )
            for stage_index, (profile_stage, segment) in enumerate(zip(enabled_profile_stages, parsed_segments), start=1):
                if not isinstance(profile_stage, dict) or not isinstance(segment, dict):
                    continue
                try:
                    profile_duration = int(profile_stage.get("duration_seconds") or 0)
                except Exception:
                    profile_duration = -1
                try:
                    segment_duration = int(segment.get("Duration") or 0)
                except Exception:
                    segment_duration = -1
                if profile_duration >= 0 and segment_duration >= 0 and profile_duration != segment_duration:
                    mismatch = {
                        "stage_index": stage_index,
                        "profile_duration_seconds": profile_duration,
                        "segment_duration_seconds": segment_duration,
                    }
                    profile_used_check["duration_mismatches"].append(mismatch)
                    issues.append(
                        {
                            "severity": "warning",
                            "category": "profile_used",
                            "message": f"profile_used.json stage {stage_index} duration does not match parsed segment duration",
                            "details": mismatch,
                        }
                    )
        except Exception as exc:
            profile_used_check["readable"] = False
            issues.append(
                {
                    "severity": "warning",
                    "category": "profile_used",
                    "message": f"profile_used.json could not be read: {exc}",
                    "details": {},
                }
            )

    return {"checks": {"profile_used": profile_used_check}, "issues": issues}


def validate_run_manifest(result_dir: Path, parsed: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    run_manifest_path = result_dir / "run_manifest.json"
    run_manifest_check: Dict[str, Any] = {
        "present": run_manifest_path.exists(),
        "readable": True,
        "profile_name": "",
        "verdict": "",
        "executed_plan_count": 0,
        "stage_window_count": 0,
        "skipped_stage_count": 0,
        "matches_result_profile_name": None,
        "matches_segment_count": None,
        "matches_verdict": None,
    }
    if run_manifest_path.exists():
        try:
            run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
            if not isinstance(run_manifest, dict):
                raise ValueError("run_manifest.json root is not an object")
            executed_plan = run_manifest.get("executed_plan") if isinstance(run_manifest.get("executed_plan"), list) else []
            stage_windows_payload = run_manifest.get("stage_windows") if isinstance(run_manifest.get("stage_windows"), list) else []
            skipped_payload = run_manifest.get("skipped_stages") if isinstance(run_manifest.get("skipped_stages"), list) else []
            run_manifest_check["profile_name"] = str(run_manifest.get("profile_name") or "")
            run_manifest_check["verdict"] = str(run_manifest.get("verdict") or "")
            run_manifest_check["executed_plan_count"] = len(executed_plan)
            run_manifest_check["stage_window_count"] = len(stage_windows_payload)
            run_manifest_check["skipped_stage_count"] = len(skipped_payload)
            result_profile_names = result_profile_name_candidates(parsed)
            run_manifest_check["result_profile_name_candidates"] = result_profile_names
            if result_profile_names:
                run_manifest_check["matches_result_profile_name"] = profile_name_matches_result(
                    run_manifest_check["profile_name"],
                    result_profile_names,
                )
                if not run_manifest_check["matches_result_profile_name"]:
                    issues.append(
                        {
                            "severity": "warning",
                            "category": "run_manifest",
                            "message": "run_manifest.json profile_name does not match result profile name",
                            "details": {
                                "run_manifest": run_manifest_check["profile_name"],
                                "result_candidates": result_profile_names,
                            },
                        }
                    )
            parsed_segments = parsed.get("Segments") if isinstance(parsed.get("Segments"), list) else []
            run_manifest_check["matches_segment_count"] = (
                len(executed_plan) == len(parsed_segments)
                and len(stage_windows_payload) == len(parsed_segments)
            )
            if not run_manifest_check["matches_segment_count"]:
                issues.append(
                    {
                        "severity": "warning",
                        "category": "run_manifest",
                        "message": "run_manifest.json executed stage counts do not match parsed Segments count",
                        "details": {
                            "executed_plan": len(executed_plan),
                            "stage_windows": len(stage_windows_payload),
                            "segments": len(parsed_segments),
                        },
                    }
                )
            parsed_result = str(parsed.get("result") or parsed.get("Result") or "").strip().lower()
            manifest_verdict = run_manifest_check["verdict"].strip().lower()
            expected_manifest_result = {
                "finished": "pass",
                "warning": "warning",
                "failed": "fail",
                "aborted": "aborted",
                "manually_aborted": "manually_aborted",
                "manual_abort": "manually_aborted",
            }.get(parsed_result, parsed_result)
            if parsed_result:
                run_manifest_check["matches_verdict"] = manifest_verdict == expected_manifest_result
                if not run_manifest_check["matches_verdict"]:
                    issues.append(
                        {
                            "severity": "warning",
                            "category": "run_manifest",
                            "message": "run_manifest.json verdict does not match parsed result",
                            "details": {
                                "run_manifest": manifest_verdict,
                                "parsed_result": parsed_result,
                                "expected_manifest": expected_manifest_result,
                            },
                        }
                    )
            if len(executed_plan) != len(stage_windows_payload):
                issues.append(
                    {
                        "severity": "warning",
                        "category": "run_manifest",
                        "message": "run_manifest.json executed_plan count does not match stage_windows count",
                        "details": {
                            "executed_plan": len(executed_plan),
                            "stage_windows": len(stage_windows_payload),
                        },
                    }
                )
        except Exception as exc:
            run_manifest_check["readable"] = False
            issues.append(
                {
                    "severity": "warning",
                    "category": "run_manifest",
                    "message": f"run_manifest.json could not be read: {exc}",
                    "details": {},
                }
            )

    return {"checks": {"run_manifest": run_manifest_check}, "issues": issues}


def validate_run_metadata(result_dir: Path, parsed: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    run_metadata_path = result_dir / "run_metadata.json"
    run_metadata_check: Dict[str, Any] = {
        "present": run_metadata_path.exists(),
        "readable": True,
        "serial": "",
        "order": "",
        "dept": "",
        "operator_present": False,
        "field_mismatches": [],
    }
    if run_metadata_path.exists():
        try:
            run_metadata = json.loads(run_metadata_path.read_text(encoding="utf-8"))
            if not isinstance(run_metadata, dict):
                raise ValueError("run_metadata.json root is not an object")
            run_metadata_check["serial"] = str(run_metadata.get("serial") or "")
            run_metadata_check["order"] = str(run_metadata.get("order") or "")
            run_metadata_check["dept"] = str(run_metadata.get("dept") or "")
            run_metadata_check["operator_present"] = bool(str(run_metadata.get("operator") or "").strip())
            metadata_block = parsed.get("Metadata") if isinstance(parsed.get("Metadata"), dict) else {}
            field_pairs = (
                ("serial", "serial", "top-level serial"),
                ("serial", "Serial", "top-level Serial"),
                ("serial", "SerialNumber", "Metadata.SerialNumber"),
                ("order", "order", "top-level order"),
                ("order", "Order", "top-level Order"),
                ("dept", "dept", "top-level dept"),
                ("dept", "Department", "top-level Department"),
                ("dept", "Department", "Metadata.Department"),
            )
            for metadata_key, parsed_key, label_text in field_pairs:
                expected = str(run_metadata.get(metadata_key) or "")
                source = metadata_block if label_text.startswith("Metadata.") else parsed
                actual = str(source.get(parsed_key) or "") if isinstance(source, dict) else ""
                if expected != actual:
                    mismatch = {"field": label_text, "run_metadata": expected, "parsed": actual}
                    run_metadata_check["field_mismatches"].append(mismatch)
                    issues.append(
                        {
                            "severity": "warning",
                            "category": "run_metadata",
                            "message": f"run_metadata.json {metadata_key} does not match {label_text}",
                            "details": mismatch,
                        }
                    )
            notes_expected = str(run_metadata.get("notes") or "-")
            notes_actual = str(metadata_block.get("Notes") or "") if isinstance(metadata_block, dict) else ""
            if notes_expected != notes_actual:
                mismatch = {"field": "Metadata.Notes", "run_metadata": notes_expected, "parsed": notes_actual}
                run_metadata_check["field_mismatches"].append(mismatch)
                issues.append(
                    {
                        "severity": "warning",
                        "category": "run_metadata",
                        "message": "run_metadata.json notes do not match Metadata.Notes",
                        "details": mismatch,
                    }
                )
            wattage_expected = str(run_metadata.get("wall_wattage") or "-")
            wattage_actual = str(metadata_block.get("MaxWallWattage") or "") if isinstance(metadata_block, dict) else ""
            if wattage_expected != wattage_actual:
                mismatch = {"field": "Metadata.MaxWallWattage", "run_metadata": wattage_expected, "parsed": wattage_actual}
                run_metadata_check["field_mismatches"].append(mismatch)
                issues.append(
                    {
                        "severity": "warning",
                        "category": "run_metadata",
                        "message": "run_metadata.json wall_wattage does not match Metadata.MaxWallWattage",
                        "details": mismatch,
                    }
                )
        except Exception as exc:
            run_metadata_check["readable"] = False
            issues.append(
                {
                    "severity": "warning",
                    "category": "run_metadata",
                    "message": f"run_metadata.json could not be read: {exc}",
                    "details": {},
                }
            )

    return {"checks": {"run_metadata": run_metadata_check}, "issues": issues}


def validate_system_info(result_dir: Path, parsed: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    system_info_path = result_dir / "system_info.json"
    system_info_check: Dict[str, Any] = {
        "present": system_info_path.exists(),
        "readable": True,
        "matches_export": None,
        "test_name": "",
        "config_file": "",
        "cpu_name": "",
        "gpu_count": 0,
        "field_mismatches": [],
    }
    if system_info_path.exists():
        try:
            system_info_file = json.loads(system_info_path.read_text(encoding="utf-8"))
            if not isinstance(system_info_file, dict):
                raise ValueError("system_info.json root is not an object")
            parsed_system_info = parsed.get("SystemInfo") if isinstance(parsed.get("SystemInfo"), dict) else {}
            system_info_check["matches_export"] = system_info_file == parsed_system_info
            test_info = system_info_file.get("TestInfo") if isinstance(system_info_file.get("TestInfo"), dict) else {}
            hardware = system_info_file.get("Hardware") if isinstance(system_info_file.get("Hardware"), dict) else {}
            cpu_info = hardware.get("Cpu") if isinstance(hardware.get("Cpu"), dict) else {}
            gpu_info = hardware.get("Gpu") if isinstance(hardware.get("Gpu"), list) else []
            system_info_check["test_name"] = str(test_info.get("TestName") or "")
            system_info_check["config_file"] = str(test_info.get("ConfigFile") or "")
            system_info_check["cpu_name"] = str(cpu_info.get("Name") or "")
            system_info_check["gpu_count"] = len(gpu_info)
            if not parsed_system_info:
                issues.append(
                    {
                        "severity": "warning",
                        "category": "system_info",
                        "message": "parsed_results_custom.json SystemInfo is missing or malformed",
                        "details": {},
                    }
                )
            elif not system_info_check["matches_export"]:
                issues.append(
                    {
                        "severity": "warning",
                        "category": "system_info",
                        "message": "system_info.json does not match parsed_results_custom.json SystemInfo",
                        "details": {},
                    }
                )
            metadata_block = parsed.get("Metadata") if isinstance(parsed.get("Metadata"), dict) else {}
            field_pairs = (
                ("TestInfo.TestName", system_info_check["test_name"], metadata_block.get("TestName")),
                ("TestInfo.ConfigFile", system_info_check["config_file"], metadata_block.get("TestConfigFile")),
                ("Hardware.Cpu.Name", system_info_check["cpu_name"], metadata_block.get("CpuName")),
            )
            for field_name, file_value, export_value in field_pairs:
                export_text = str(export_value or "")
                if file_value and export_text and file_value != export_text:
                    mismatch = {
                        "field": field_name,
                        "system_info": file_value,
                        "export": export_text,
                    }
                    system_info_check["field_mismatches"].append(mismatch)
                    issues.append(
                        {
                            "severity": "warning",
                            "category": "system_info",
                            "message": f"system_info.json {field_name} does not match exported metadata",
                            "details": mismatch,
                        }
                    )
        except Exception as exc:
            system_info_check["readable"] = False
            issues.append(
                {
                    "severity": "warning",
                    "category": "system_info",
                    "message": f"system_info.json could not be read: {exc}",
                    "details": {},
                }
            )

    return {"checks": {"system_info": system_info_check}, "issues": issues}
