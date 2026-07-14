from __future__ import annotations

"""Frontend-neutral helpers for the TUI run-setup adapter."""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from Modules.lvs_run_setup_controller import RunSetupPromptCallbacks


@dataclass(frozen=True)
class PowerLimitTransition:
    action: str
    metadata_value: str = ""
    next_field: str = ""
    next_label: str = ""
    next_blank_default: str = ""
    picker: str = ""
    reset_parts: bool = False
    parts_update: Dict[str, str] = field(default_factory=dict)


def parse_tui_heatsoak_minutes(raw_value: str, current: float) -> float:
    text = str(raw_value or "").strip()
    if not text:
        return float(current or 0.0)
    try:
        return max(0.0, min(24.0 * 60.0, float(text)))
    except Exception:
        return float(current or 0.0)


def run_setup_passthrough_callbacks(service: Any, notify: Callable[[str], None]) -> RunSetupPromptCallbacks:
    return RunSetupPromptCallbacks(
        load_history=lambda metadata: metadata,
        stage_overrides=lambda profile: None,
        edit_labels=lambda labels: labels,
        select_case_sku=lambda current: current,
        select_psu_rating=lambda current: current,
        select_cpu_cooler=lambda current: current,
        enter_power_limit=lambda current: current,
        enter_description=lambda current: current,
        enter_heatsoak_minutes=lambda current: float(current or 0.0),
        enter_psu_wattage=lambda current: current,
        enter_fan_type=lambda fan_type, fan_details: (fan_type, fan_details),
        enter_fan_details=lambda current: current,
        enter_raw=lambda label: "",
        normalize_labels=lambda profile, labels: list(labels),
        department=lambda: str(service.settings.suite_department or "Production"),
        update_pending_heatsoak=lambda minutes: None,
        notify=notify,
    )


def run_setup_input_callbacks(service: Any, raw_value: str, notify: Callable[[str], None]) -> RunSetupPromptCallbacks:
    return RunSetupPromptCallbacks(
        load_history=lambda metadata: metadata,
        stage_overrides=lambda profile: None,
        edit_labels=lambda labels: labels,
        select_case_sku=lambda current: current,
        select_psu_rating=lambda current: current,
        select_cpu_cooler=lambda current: current,
        enter_power_limit=lambda current: raw_value or current,
        enter_description=lambda current: raw_value or current,
        enter_heatsoak_minutes=lambda current: parse_tui_heatsoak_minutes(raw_value, current),
        enter_psu_wattage=lambda current: raw_value,
        enter_fan_type=lambda fan_type, fan_details: (raw_value or fan_type, fan_details),
        enter_fan_details=lambda current: raw_value or current,
        enter_raw=lambda label: raw_value,
        normalize_labels=lambda profile, labels: list(labels),
        department=lambda: str(service.settings.suite_department or "Production"),
        update_pending_heatsoak=lambda minutes: None,
        notify=notify,
    )


def run_setup_readiness_text(service: Any, setup: Any) -> str:
    try:
        prepared = service.prepare_setup_run_flow(setup, save_blocked_report=False)
        return prepared_run_readiness_text(prepared)
    except Exception as exc:
        return "\n".join(
            [
                "Run Readiness",
                "-------------",
                "Status: preview unavailable",
                f"Preflight preview unavailable: {exc}",
            ]
        )


def prepared_run_readiness_text(prepared: Any) -> str:
    readiness = getattr(prepared, "readiness", None)
    validation = getattr(readiness, "validation", {}) if readiness is not None else {}
    if not isinstance(validation, dict):
        validation = {}
    profile_errors = list(validation.get("errors") or [])
    profile_warnings = list(validation.get("warnings") or [])
    preflight_decision = getattr(prepared, "preflight_decision", None)
    preflight_action = getattr(prepared, "preflight_action", None)
    report = getattr(preflight_decision, "report", {}) if preflight_decision is not None else {}
    if not isinstance(report, dict):
        report = {}
    blocked = bool(getattr(preflight_action, "blocked", False))
    status = "blocked" if blocked else "ready"
    lines = [
        "Run Readiness",
        "-------------",
        f"Status: {status}",
    ]
    if profile_errors:
        lines.append(f"Profile validation: {len(profile_errors)} error(s)")
        lines.extend(f"  [error] {message}" for message in profile_errors[:5])
    elif profile_warnings:
        lines.append(f"Profile validation: {len(profile_warnings)} warning(s)")
        lines.extend(f"  [warn] {message}" for message in profile_warnings[:5])
    else:
        lines.append("Profile validation: no issues")

    runnable = bool(getattr(preflight_decision, "runnable", False)) if preflight_decision is not None else False
    preflight_status = "runnable" if runnable else "not runnable"
    lines.append(
        f"Preflight: {preflight_status}, runnable stages "
        f"{report.get('runnable_stage_count', 0)}/"
        f"{report.get('enabled_stage_count', 0)}"
    )
    skipped_stage_count = int(getattr(preflight_action, "skipped_stage_count", 0) or 0)
    if skipped_stage_count:
        lines.append(f"Skipped stages: {skipped_stage_count}")
    skip_notice = getattr(preflight_action, "skip_notice", None)
    if skip_notice:
        lines.append(str(skip_notice))
    for message in list(getattr(preflight_action, "errors", []) or [])[:5]:
        lines.append(f"  [error] {message}")
    for message in list(getattr(preflight_action, "warnings", []) or [])[:5]:
        lines.append(f"  [warn] {message}")
    if blocked:
        lines.append("Run blocked: fix the preflight/profile issues above before starting.")
    report_dir = getattr(preflight_action, "report_dir", None)
    if report_dir:
        lines.append(f"Preflight report: {report_dir}")
    return "\n".join(lines)


def stage_index_from_option(selected: str, stage_count: int) -> Optional[int]:
    prefix = str(selected or "").split(".", 1)[0].strip()
    try:
        index = int(prefix) - 1
    except Exception:
        return None
    if index < 0 or index >= stage_count:
        return None
    return index


def normalize_power_watts(value: str) -> str:
    text = str(value or "").strip().upper()
    return text[:-1].strip() if text.endswith("W") else text


def power_limit_vendor_transition(selected: str) -> PowerLimitTransition:
    choice = str(selected or "").strip()
    lowered = choice.lower()
    if lowered == "auto":
        return PowerLimitTransition("set_metadata", metadata_value="Auto")
    if lowered == "intel":
        return PowerLimitTransition(
            "input",
            next_field="power_limit_intel_pl1",
            next_label="Intel PL1 (Enter for Auto)",
            next_blank_default="Auto",
            reset_parts=True,
        )
    if lowered == "amd":
        return PowerLimitTransition(
            "input",
            next_field="power_limit_amd_power",
            next_label="AMD power limit watts (Enter for Auto)",
            next_blank_default="Auto",
            reset_parts=True,
        )
    return PowerLimitTransition(
        "input",
        next_field="power_limit_data",
        next_label="Power limit (Enter for Auto)",
        next_blank_default="Auto",
    )


def power_limit_amd_type_transition(selected: str, parts: Dict[str, str]) -> PowerLimitTransition:
    power_type = str(selected or "").strip() or "PPT"
    update = {"amd_type": power_type}
    if power_type.lower() == "other":
        return PowerLimitTransition(
            "input",
            next_field="power_limit_amd_other",
            next_label="AMD power limit Other info (Enter for N/A)",
            next_blank_default="N/A",
            parts_update=update,
        )
    power = str(parts.get("amd_power", ""))
    return PowerLimitTransition(
        "set_metadata",
        metadata_value=f"(MB) {power}W-{power_type}" if power else "Auto",
        parts_update=update,
    )


def power_limit_input_transition(field: str, value: str, parts: Dict[str, str]) -> PowerLimitTransition:
    normalized = str(value or "").strip() or "Auto"
    if normalized.lower() == "auto":
        normalized = "Auto"
    if field == "power_limit_data":
        return PowerLimitTransition("set_metadata", metadata_value=normalized)
    if field == "power_limit_intel_pl1":
        if normalized == "Auto":
            return PowerLimitTransition("set_metadata", metadata_value="Auto")
        return PowerLimitTransition(
            "input",
            next_field="power_limit_intel_pl2",
            next_label="Intel PL2 (Enter for Auto)",
            next_blank_default="Auto",
            parts_update={"pl1": normalized},
        )
    if field == "power_limit_intel_pl2":
        return PowerLimitTransition(
            "input",
            next_field="power_limit_intel_turbo",
            next_label="Intel Turbo Timer (Enter for Auto)",
            next_blank_default="Auto",
            parts_update={"pl2": normalized},
        )
    if field == "power_limit_intel_turbo":
        pl1 = parts.get("pl1", "Auto")
        pl2 = parts.get("pl2", "Auto")
        return PowerLimitTransition(
            "set_metadata",
            metadata_value=(
                "Auto"
                if pl1 == "Auto" and pl2 == "Auto" and normalized == "Auto"
                else f"PL1:{pl1}|PL2:{pl2}|Turbo:{normalized}"
            ),
        )
    if field == "power_limit_amd_power":
        if normalized == "Auto":
            return PowerLimitTransition("set_metadata", metadata_value="Auto")
        return PowerLimitTransition(
            "picker",
            picker="amd_power_limit_type",
            parts_update={"amd_power": normalize_power_watts(normalized)},
        )
    if field == "power_limit_amd_other":
        power = parts.get("amd_power", "")
        power_type = parts.get("amd_type", "Other")
        other = normalized or "N/A"
        return PowerLimitTransition(
            "set_metadata",
            metadata_value=(
                f"(MB) {power}W-{power_type}"
                if other == "N/A"
                else f"(MB) {power}W-{power_type}|Other:{other}"
            ),
        )
    return PowerLimitTransition("noop")
