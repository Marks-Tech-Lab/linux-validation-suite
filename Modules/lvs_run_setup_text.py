#!/usr/bin/env python3
"""Presentation text helpers for run setup state."""

from __future__ import annotations

from typing import Any, Callable, List

from .lvs_service_models import FrontendActionSpec, RunSetupState


def setup_action_detail_value(setup: RunSetupState | None, key: str) -> str:
    if setup is None:
        return ""
    profile = setup.profile
    metadata = setup.metadata
    if key == "description":
        return metadata.description or profile.profile_name or "Not Set"
    if key == "heatsoak_minutes":
        return "Disabled" if float(setup.heatsoak_minutes or 0.0) <= 0 else f"{float(setup.heatsoak_minutes):g} min"
    if key == "stage_overrides":
        enabled = sum(1 for stage in profile.stages if stage.enabled)
        return f"{enabled}/{len(profile.stages)} enabled"
    if key == "segment_labels":
        return f"{len(setup.labels)} label(s)"
    if key == "advanced_debug_logging":
        return "Enabled" if bool(getattr(metadata, "advanced_debug_logging", False)) else "Disabled"
    if key == "review_run":
        return profile.profile_name or setup.profile_path.name
    value = str(getattr(metadata, key, "") or "").strip()
    return value or "Not Set"


def setup_action_detail_text(
    setup: RunSetupState,
    action: FrontendActionSpec,
    option_values: Callable[[str], List[str]],
) -> str:
    key = str(action.key or "").upper()
    label = str(action.label or action.target or action.action or key)
    current = str(action.detail or "").strip()
    lines = [
        "Selected Action",
        "---------------",
        f"{key} - {label}",
    ]
    if current:
        lines.append(f"Current: {current}")

    if action.action == "picker":
        options = option_values(action.target)
        lines.append("Type: picker")
        if options:
            preview = ", ".join(options[:5])
            if len(options) > 5:
                preview += f", ... ({len(options)} total)"
            lines.append(f"Options: {preview}")
        if action.target == "case_sku":
            lines.append("Note: OEM/Other selections open text entry.")
        elif action.target == "cpu_cooler":
            lines.append("Note: a description prompt follows the selected cooler type.")
        else:
            lines.append("Press Enter to choose from the list.")
    elif action.action == "input":
        lines.append("Type: text entry")
        if action.target == "heatsoak_minutes":
            lines.append("Enter minutes. Use 0 or blank to disable heatsoak.")
        elif action.target == "fan_type":
            lines.append("Enter a short fan type. Use Fan details for longer notes.")
        else:
            lines.append("Press Enter to edit this value.")
    elif action.action == "power_limit_picker":
        lines.append("Type: guided picker")
        lines.append("Choose Auto, Intel, AMD, or Other/Unknown. Auto leaves the field blank.")
    elif action.action == "stage_override_picker":
        enabled = sum(1 for stage in setup.profile.stages if stage.enabled)
        lines.append("Type: stage override")
        lines.append(f"Stages enabled: {enabled}/{len(setup.profile.stages)}")
        lines.append("Edit durations, trim windows, or enabled state for this run only.")
    elif action.action == "segment_label_picker":
        lines.append("Type: segment label editor")
        lines.append(f"Labels available: {len(setup.labels)}")
        lines.append("Edits apply to this pending run setup.")
    elif action.action == "load_history":
        lines.append("Type: history recall")
        lines.append("Loads a prior run setup. Wall wattage is never recalled.")
    elif action.action == "toggle_debug_logging":
        lines.append("Type: per-run toggle")
        lines.append("Captures extra kernel/GPU/PCIe logs and hardware snapshots into the result folder.")
        lines.append("Use this when troubleshooting GPU dropouts, driver resets, or PCIe/AER faults.")
    elif action.action == "run_selected":
        lines.append("Type: review")
        lines.append("Opens the two-step run confirmation screen.")
    else:
        lines.append("Press Enter to activate.")
    return "\n".join(lines)


def heatsoak_text(setup: RunSetupState) -> str:
    return (
        "Disabled"
        if float(setup.heatsoak_minutes or 0.0) <= 0
        else f"{float(setup.heatsoak_minutes):g} min Power Test"
    )


def run_setup_summary_text(
    setup: RunSetupState,
    *,
    mode_label: str,
    suite_department: Any,
    production: bool,
) -> str:
    profile = setup.profile
    labels = setup.labels
    metadata = setup.metadata
    lines: List[str] = [
        "Run Setup",
        "=========",
        "",
        "Current Run",
        "-----------",
        f"Mode: {mode_label}",
        f"Department: {metadata.dept or suite_department or 'Production'}",
        f"Profile: {setup.profile_path.name}",
        f"Description: {metadata.description or profile.profile_name}",
        f"Heatsoak: {heatsoak_text(setup)}",
        f"Advanced debug logging: {'Enabled' if bool(metadata.advanced_debug_logging) else 'Disabled'}",
    ]
    if production:
        lines.extend(
            [
                "",
                "Configuration",
                "-------------",
                f"Case/SKU: {metadata.case_sku or 'Not Set'}",
                f"PSU wattage: {metadata.psu_wattage or 'Not Set'}",
                f"PSU rating: {metadata.psu_rating or 'Not Set'}",
                f"Power limit: {metadata.power_limit_data or 'Not Set'}",
                f"CPU cooler: {metadata.cpu_cooler or 'Not Set'}",
                f"Fan type: {metadata.fan_type or 'Not Set'}",
                f"Fan details: {metadata.fan_details or 'Not Set'}",
            ]
        )
    lines.extend(
        [
            "",
            "Setup Controls",
            "--------------",
        ]
    )
    if production:
        lines.extend(
            [
                "- 1 Case/SKU picker (OEM/Other opens text entry)",
                "- 4 PSU wattage text entry",
                "- 5 PSU rating picker",
                "- 6 Power limit picker (Auto/Intel/AMD/Other)",
                "- 7 CPU cooler picker (optional description follows)",
                "- 8 Fan type text entry (M opens fan details)",
                "- 9 Fan details text entry",
            ]
        )
    lines.extend(
        [
            "- 2 Description text entry",
            "- 3 Heatsoak minutes text entry",
            "- O Stage durations / trim / enabled",
            "- L Segment labels for this run",
            "- H Load previous setup",
            "- D Advanced debug logging toggle",
            "- U / Run starts two-step confirmation",
            "",
            "Segments",
            "--------",
        ]
    )
    for index, stage in enumerate(profile.stages, start=1):
        label = labels[index - 1] if index - 1 < len(labels) else stage.name
        state = "enabled" if stage.enabled else "disabled"
        lines.append(f"- {index}. {label} [{stage.name}] {stage.duration_seconds}s, {state}")
    return "\n".join(lines)


def run_setup_overview_text(
    setup: RunSetupState,
    *,
    mode_label: str,
    suite_department: Any,
    production: bool,
) -> str:
    profile = setup.profile
    labels = setup.labels
    metadata = setup.metadata
    enabled_count = sum(1 for stage in profile.stages if bool(stage.enabled))
    disabled_count = len(profile.stages) - enabled_count
    lines: List[str] = [
        "Run Setup",
        "=========",
        "",
        "Current Run",
        "-----------",
        f"Mode: {mode_label}",
        f"Department: {metadata.dept or suite_department or 'Production'}",
        f"Profile: {setup.profile_path.name}",
        f"Description: {metadata.description or profile.profile_name}",
        f"Heatsoak: {heatsoak_text(setup)}",
        f"Advanced debug logging: {'Enabled' if bool(metadata.advanced_debug_logging) else 'Disabled'}",
    ]
    if production:
        lines.extend(
            [
                "",
                "System Configuration",
                "--------------------",
                f"Case/SKU: {metadata.case_sku or 'Not Set'}",
                f"PSU: {metadata.psu_wattage or 'Not Set'} / {metadata.psu_rating or 'Not Set'}",
                f"Power limit: {metadata.power_limit_data or 'Not Set'}",
                f"CPU cooler: {metadata.cpu_cooler or 'Not Set'}",
                f"Fan type: {metadata.fan_type or 'Not Set'}",
                f"Fan details: {metadata.fan_details or 'Not Set'}",
            ]
        )
    lines.extend(
        [
            "",
            "Stages",
            "------",
            f"Total: {len(profile.stages)} | Enabled: {enabled_count} | Disabled: {disabled_count}",
        ]
    )
    for index, stage in enumerate(profile.stages, start=1):
        label = labels[index - 1] if index - 1 < len(labels) else stage.name
        state = "enabled" if stage.enabled else "disabled"
        trim = f"trim {stage.normalization.trim_start_seconds}/{stage.normalization.trim_end_seconds}s"
        lines.append(f"{index}. {label}: {stage.duration_seconds}s, {state}, {trim}")
    lines.extend(
        [
            "",
            "Use the left Run Setup list to edit values. Select Review and run when ready.",
        ]
    )
    return "\n".join(lines)
