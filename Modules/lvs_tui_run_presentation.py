"""Textual-free run-active presentation helpers for the optional TUI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Dict, Iterable, Tuple

from .lvs_run_progress import run_event_history_text, run_status_detail_text, short_status_text


RUN_ACTIVE_SIDEBAR_TITLE = "Run Active"
RUN_ACTIVE_SIDEBAR_ROWS: Tuple[str, str] = (
    "Run in progress\n  navigation locked",
    "Esc / Back\n  request safe cancel",
)
LIVE_SYSTEM_PANE_WIDTH = 32
LIVE_SYSTEM_MIN_TERMINAL_WIDTH = 124


@dataclass(frozen=True)
class TuiRunActivePresentation:
    status: str
    detail: str
    sidebar_title: str = RUN_ACTIVE_SIDEBAR_TITLE
    sidebar_rows: Tuple[str, ...] = RUN_ACTIVE_SIDEBAR_ROWS


@dataclass(frozen=True)
class TuiRunConfirmationPresentation:
    detail: str


@dataclass(frozen=True)
class TuiLiveSystemLayout:
    visible: bool
    pane_width: int = 0


@dataclass(frozen=True)
class LiveSystemGpuMetrics:
    gpu_index: int
    load_percent: float | None = None
    temp_c: float | None = None
    power_w: float | None = None
    clock_mhz: float | None = None
    vram_used_gib: float | None = None
    vram_total_gib: float | None = None
    vram_used_percent: float | None = None
    fan_percent: float | None = None


@dataclass(frozen=True)
class LiveSystemCpuPackageMetrics:
    package_index: int
    temp_c: float | None = None
    power_w: float | None = None
    clock_mhz: float | None = None


@dataclass(frozen=True)
class LiveSystemDeviceTemp:
    device_index: int
    temp_c: float


@dataclass(frozen=True)
class LiveSystemMetrics:
    cpu_package_temp_c: float | None = None
    cpu_package_power_w: float | None = None
    cpu_clock_mhz: float | None = None
    memory_used_gib: float | None = None
    memory_total_gib: float | None = None
    memory_used_percent: float | None = None
    memory_module_temp_c: float | None = None
    storage_temp_c: float | None = None
    cpu_packages: tuple[LiveSystemCpuPackageMetrics, ...] = ()
    cpu_package_count: int = 0
    memory_modules: tuple[LiveSystemDeviceTemp, ...] = ()
    memory_module_count: int = 0
    storage_drives: tuple[LiveSystemDeviceTemp, ...] = ()
    storage_drive_count: int = 0


def live_system_layout(*, terminal_width: int | None, run_active: bool) -> TuiLiveSystemLayout:
    try:
        width = int(terminal_width or 0)
    except (TypeError, ValueError):
        width = 0
    visible = bool(run_active and width >= LIVE_SYSTEM_MIN_TERMINAL_WIDTH)
    return TuiLiveSystemLayout(visible=visible, pane_width=LIVE_SYSTEM_PANE_WIDTH if visible else 0)


def _metric_number(value: object) -> float | None:
    match = re.match(r"^\s*(-?\d+(?:\.\d+)?)", str(value or ""))
    if match is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _metric_count(value: object) -> int:
    number = _metric_number(value)
    return max(0, int(number)) if number is not None else 0


def _indexed_device_temps(fields: dict[str, object], pattern: str) -> tuple[LiveSystemDeviceTemp, ...]:
    rows: list[LiveSystemDeviceTemp] = []
    for key, value in fields.items():
        match = re.fullmatch(pattern, str(key))
        temp_c = _metric_number(value)
        if match is not None and temp_c is not None:
            rows.append(LiveSystemDeviceTemp(device_index=int(match.group(1)), temp_c=temp_c))
    return tuple(sorted(rows, key=lambda row: row.device_index))


def _cpu_package_metrics(fields: dict[str, object]) -> tuple[LiveSystemCpuPackageMetrics, ...]:
    package_indexes: set[int] = set()
    for key in fields:
        match = re.fullmatch(r"cpu_package_(\d+)_(?:temp_c|power_w|clock_mhz)", str(key))
        if match is not None:
            package_indexes.add(int(match.group(1)))
    rows = []
    for package_index in sorted(package_indexes):
        row = LiveSystemCpuPackageMetrics(
            package_index=package_index,
            temp_c=_metric_number(fields.get(f"cpu_package_{package_index}_temp_c")),
            power_w=_metric_number(fields.get(f"cpu_package_{package_index}_power_w")),
            clock_mhz=_metric_number(fields.get(f"cpu_package_{package_index}_clock_mhz")),
        )
        if any(value is not None for value in (row.temp_c, row.power_w, row.clock_mhz)):
            rows.append(row)
    return tuple(rows)


def _has_live_system_metrics(metrics: LiveSystemMetrics) -> bool:
    scalar_values = (
        metrics.cpu_package_temp_c,
        metrics.cpu_package_power_w,
        metrics.cpu_clock_mhz,
        metrics.memory_used_gib,
        metrics.memory_total_gib,
        metrics.memory_used_percent,
        metrics.memory_module_temp_c,
        metrics.storage_temp_c,
    )
    return any(value is not None for value in scalar_values) or bool(
        metrics.cpu_packages or metrics.memory_modules or metrics.storage_drives
    )


def _gpu_summary_metrics(summary: object) -> list[LiveSystemGpuMetrics]:
    rows: list[LiveSystemGpuMetrics] = []
    for chunk in str(summary or "").split(";"):
        text = chunk.strip()
        gpu_match = re.search(r"\bgpu(\d+)\b", text, flags=re.IGNORECASE)
        metric_start = re.search(r":(?=(?:busy|mem_busy|pwr|temp|clk|mclk|vram)=)", text)
        if gpu_match is None or metric_start is None:
            continue
        metric_text, _separator, state_text = text[metric_start.end():].partition("|state=")
        metrics: dict[str, str] = {}
        for part in metric_text.split(","):
            if "=" in part:
                key, value = part.split("=", 1)
                metrics[key.strip()] = value.strip()
        state: dict[str, str] = {}
        for part in state_text.split(","):
            if "=" in part:
                key, value = part.split("=", 1)
                state[key.strip()] = value.strip()
        load_percent = _metric_number(metrics.get("busy"))
        if load_percent is None:
            load_percent = _metric_number(state.get("load"))
        row = LiveSystemGpuMetrics(
            gpu_index=int(gpu_match.group(1)),
            load_percent=load_percent,
            temp_c=_metric_number(metrics.get("temp")),
            power_w=_metric_number(metrics.get("pwr")),
            clock_mhz=_metric_number(metrics.get("clk")),
            # Progress summaries derive this value from bytes / 1024**3 even
            # though their legacy rendered suffix is currently "GB".
            vram_used_gib=_metric_number(metrics.get("vram")),
            vram_total_gib=_metric_number(metrics.get("gpu_vram_total_gib")),
            vram_used_percent=_metric_number(metrics.get("gpu_vram_used_percent")),
            fan_percent=_metric_number(metrics.get("fan_percent")),
        )
        if any(
            value is not None
            for value in (
                row.load_percent,
                row.temp_c,
                row.power_w,
                row.clock_mhz,
                row.vram_used_gib,
                row.vram_total_gib,
                row.vram_used_percent,
                row.fan_percent,
            )
        ):
            rows.append(row)
    return rows


def live_system_gpu_metrics(events: Iterable[object]) -> tuple[list[LiveSystemGpuMetrics], bool]:
    event_list = list(events)
    for reverse_index, event in enumerate(reversed(event_list)):
        fields = getattr(event, "fields", {})
        if not isinstance(fields, dict):
            continue
        rows: list[LiveSystemGpuMetrics] = []
        rows.extend(_gpu_summary_metrics(fields.get("gpu_target")))
        rows.extend(_gpu_summary_metrics(fields.get("gpu_other")))
        if rows:
            by_index = {row.gpu_index: row for row in rows}
            return [by_index[index] for index in sorted(by_index)], reverse_index > 0
    return [], False


def live_system_metrics(events: Iterable[object]) -> tuple[LiveSystemMetrics, bool]:
    event_list = list(events)
    for reverse_index, event in enumerate(reversed(event_list)):
        fields = getattr(event, "fields", {})
        if not isinstance(fields, dict):
            continue
        metrics = LiveSystemMetrics(
            cpu_package_temp_c=_metric_number(fields.get("cpu_package_temp_c")),
            cpu_package_power_w=_metric_number(fields.get("cpu_package_power_w")),
            cpu_clock_mhz=_metric_number(fields.get("cpu_clock_mhz")),
            memory_used_gib=_metric_number(fields.get("memory_used_gib")),
            memory_total_gib=_metric_number(fields.get("memory_total_gib")),
            memory_used_percent=_metric_number(fields.get("memory_used_percent")),
            memory_module_temp_c=_metric_number(fields.get("memory_module_temp_c")),
            storage_temp_c=_metric_number(fields.get("storage_temp_c")),
            cpu_packages=_cpu_package_metrics(fields),
            cpu_package_count=_metric_count(fields.get("cpu_package_count")),
            memory_modules=_indexed_device_temps(fields, r"memory_module_(\d+)_temp_c"),
            memory_module_count=_metric_count(fields.get("memory_module_temp_count")),
            storage_drives=_indexed_device_temps(fields, r"storage_drive_(\d+)_temp_c"),
            storage_drive_count=_metric_count(fields.get("storage_drive_temp_count")),
        )
        if _has_live_system_metrics(metrics):
            return metrics, reverse_index > 0
    return LiveSystemMetrics(), False


def _compact_number(value: float) -> str:
    rounded = round(float(value), 1)
    return str(int(rounded)) if rounded.is_integer() else f"{rounded:.1f}"


def live_system_text(events: Iterable[object]) -> str:
    event_list = list(events)
    gpu_rows, gpu_stale = live_system_gpu_metrics(event_list)
    system, system_stale = live_system_metrics(event_list)
    has_system = _has_live_system_metrics(system)
    lines = ["Live System", "==========="]
    if not gpu_rows and not has_system:
        lines.extend(["", "Waiting for available", "run telemetry..."])
        return "\n".join(lines)
    stale = (bool(gpu_rows) and gpu_stale) or (has_system and system_stale)
    lines.extend(["", "Last progress sample" if stale else "Latest progress sample"])
    if stale:
        lines.append("(not current)")
    if system.cpu_packages:
        for package in system.cpu_packages:
            lines.extend(["", f"CPU {package.package_index}"])
            if package.temp_c is not None:
                lines.append(f"  Temp   {_compact_number(package.temp_c)} °C")
            if package.power_w is not None:
                lines.append(f"  Power  {_compact_number(package.power_w)} W")
            if package.clock_mhz is not None:
                lines.append(f"  Clock  {_compact_number(package.clock_mhz)} MHz")
        hidden_packages = max(0, system.cpu_package_count - len(system.cpu_packages))
        if hidden_packages:
            lines.append(f"  +{hidden_packages} more")
        if system.cpu_clock_mhz is not None and not any(
            package.clock_mhz is not None for package in system.cpu_packages
        ):
            lines.extend(["", "CPU Aggregate", f"  Clock  {_compact_number(system.cpu_clock_mhz)} MHz"])
    elif any(
        value is not None
        for value in (system.cpu_package_temp_c, system.cpu_package_power_w, system.cpu_clock_mhz)
    ):
        lines.extend(["", "CPU"])
        if system.cpu_package_temp_c is not None:
            lines.append(f"  Temp   {_compact_number(system.cpu_package_temp_c)} °C")
        if system.cpu_package_power_w is not None:
            lines.append(f"  Power  {_compact_number(system.cpu_package_power_w)} W")
        if system.cpu_clock_mhz is not None:
            lines.append(f"  Clock  {_compact_number(system.cpu_clock_mhz)} MHz")
    if system.memory_used_gib is not None:
        lines.extend(["", "RAM", f"  Used   {_compact_number(system.memory_used_gib)} GiB"])
        if system.memory_total_gib is not None:
            lines.append(f"  Total  {_compact_number(system.memory_total_gib)} GiB")
        if system.memory_used_percent is not None:
            lines.append(f"  Use    {_compact_number(system.memory_used_percent)}%")
    if system.memory_modules:
        lines.extend(["", "DIMM"])
        for module in system.memory_modules:
            lines.append(f"  DIMM {module.device_index}  {_compact_number(module.temp_c)} °C")
        hidden_modules = max(0, system.memory_module_count - len(system.memory_modules))
        if hidden_modules:
            lines.append(f"  +{hidden_modules} more")
        max_temp = system.memory_module_temp_c
        if max_temp is None:
            max_temp = max(module.temp_c for module in system.memory_modules)
        lines.append(f"  Max     {_compact_number(max_temp)} °C")
    elif system.memory_module_temp_c is not None:
        lines.extend(["", "DIMM", f"  Max Temp  {_compact_number(system.memory_module_temp_c)} °C"])
    if system.storage_drives:
        lines.extend(["", "Storage"])
        for drive in system.storage_drives:
            lines.append(f"  Drive {drive.device_index}  {_compact_number(drive.temp_c)} °C")
        hidden_drives = max(0, system.storage_drive_count - len(system.storage_drives))
        if hidden_drives:
            lines.append(f"  +{hidden_drives} more")
        max_temp = system.storage_temp_c
        if max_temp is None:
            max_temp = max(drive.temp_c for drive in system.storage_drives)
        lines.append(f"  Max      {_compact_number(max_temp)} °C")
    elif system.storage_temp_c is not None:
        lines.extend(["", "Storage", f"  Max Temp  {_compact_number(system.storage_temp_c)} °C"])
    for row in gpu_rows:
        lines.extend(["", f"GPU {row.gpu_index}"])
        if row.load_percent is not None:
            lines.append(f"  Load   {_compact_number(row.load_percent)}%")
        if row.temp_c is not None:
            lines.append(f"  Temp   {_compact_number(row.temp_c)} °C")
        if row.power_w is not None:
            lines.append(f"  Power  {_compact_number(row.power_w)} W")
        if row.clock_mhz is not None:
            lines.append(f"  Clock  {_compact_number(row.clock_mhz)} MHz")
        if row.vram_used_gib is not None:
            lines.append(f"  VRAM   {_compact_number(row.vram_used_gib)} GiB used")
            if row.vram_total_gib is not None:
                lines.append(f"         {_compact_number(row.vram_total_gib)} GiB total")
            if row.vram_used_percent is not None:
                lines.append(f"         {_compact_number(row.vram_used_percent)}% used")
        if row.fan_percent is not None:
            lines.append(f"  Fan    {_compact_number(row.fan_percent)}%")
    return "\n".join(lines)


def run_confirmation_presentation(
    *,
    profile_name: str,
    setup_summary: str,
    readiness_text: str,
    can_run: bool = True,
) -> TuiRunConfirmationPresentation:
    action_text = (
        "Press Run again, or press U, to start this profile.\n"
        if can_run
        else "Run is blocked. Fix the readiness issues above before starting.\n"
    )
    return TuiRunConfirmationPresentation(
        detail=(
            "Run confirmation\n"
            "================\n\n"
            f"Profile: {profile_name}\n\n"
            f"{setup_summary}\n\n"
            f"{readiness_text}\n\n"
            f"{action_text}"
            "Press Setup, Dry, Results, Profiles, or Refresh to cancel this confirmation.\n\n"
            "After the run, press W to save observed wall wattage or G to upload."
        )
    )


def initial_run_active_presentation(profile_name: str, heatsoak_minutes: float = 0.0) -> TuiRunActivePresentation:
    heatsoak_text = (
        f"Heatsoak: {float(heatsoak_minutes):g} min Power Test will run first.\n"
        if float(heatsoak_minutes or 0.0) > 0
        else ""
    )
    return TuiRunActivePresentation(
        status=f"Run active | {profile_name}",
        detail=(
            "Run In Progress\n"
            "===============\n\n"
            f"Profile: {profile_name}\n\n"
            "Status: active\n"
            f"{heatsoak_text}"
            "The workload runner is executing in the background. Live phase/progress "
            "output will appear here as it is emitted.\n\n"
            "Navigation is locked until the run reaches its post-run prompts.\n"
            "Press Esc or the footer Back action to request safe cancellation. "
            "Active workers are stopped through the same operator-stop path used for manual aborts."
        ),
    )


def _stage_label(fields: dict[str, str]) -> str:
    stage = str(fields.get("stage") or "").strip()
    name = str(fields.get("name") or "").strip()
    if stage and name and name != stage:
        return f"{stage} ({name})"
    return stage or name or "Stage"


def _stage_detail_suffix(fields: dict[str, str], *, include_target: bool = False) -> str:
    details = []
    for field in ("elapsed", "remaining", "verdict", "workload"):
        value = fields.get(field)
        if value:
            details.append(f"{field}={value}")
    if include_target:
        for field in ("target", "gpu_target"):
            value = fields.get(field)
            if value:
                details.append(f"{field}={value}")
                break
    return " | " + " | ".join(details) if details else ""


def _event_stage_status(event_type: str, fields: dict[str, str]) -> str:
    if event_type in {"stage-start", "stage-progress"}:
        return "running"
    if event_type == "stage-end":
        return str(fields.get("verdict") or "complete")
    if event_type == "stage-abort":
        return str(fields.get("verdict") or "aborted")
    if event_type == "stage-skip":
        return "skipped"
    if event_type == "heatsoak-start":
        return "running"
    if event_type == "heatsoak-progress":
        return "running"
    if event_type == "heatsoak-end":
        return str(fields.get("verdict") or "complete")
    if event_type == "heatsoak-cancel":
        return str(fields.get("verdict") or "cancelled")
    return event_type.replace("-", " ") or "event"


def stage_progress_table_text(events: Iterable[object], *, limit: int = 24, width: int = 120) -> str:
    rows: dict[str, str] = {}
    order: list[str] = []
    for event in events:
        event_type = str(getattr(event, "event_type", "") or "")
        fields = getattr(event, "fields", {}) if isinstance(getattr(event, "fields", {}), dict) else {}
        if event_type.startswith("heatsoak"):
            key = "Heatsoak"
            label = "Heatsoak"
        else:
            key = str(fields.get("stage") or "").strip()
            if not key:
                continue
            label = f"Stage {_stage_label(fields)}"
        if key not in order:
            order.append(key)
        status = _event_stage_status(event_type, fields)
        suffix = _stage_detail_suffix(fields)
        rows[key] = short_status_text(f"- {label}: {status}{suffix}", width)
    if not order:
        return "Stage Progress\n--------------\n(waiting for stage progress...)"
    selected = order[-max(1, int(limit)):]
    lines = ["Stage Progress", "--------------"]
    lines.extend(rows[key] for key in selected if key in rows)
    if len(order) > len(selected):
        lines.append(f"... {len(order) - len(selected)} earlier stage(s)")
    return "\n".join(lines)


def active_stage_line_text(status_snapshot: object, events: Iterable[object], *, width: int = 120) -> str:
    snapshot_stage = str(getattr(status_snapshot, "stage", "") or "").strip()
    latest_progress = None
    for event in events:
        if str(getattr(event, "event_type", "") or "") in {"stage-progress", "heatsoak-progress", "stage-start", "heatsoak-start"}:
            latest_progress = event
    if latest_progress is not None:
        event_type = str(getattr(latest_progress, "event_type", "") or "")
        fields = getattr(latest_progress, "fields", {}) if isinstance(getattr(latest_progress, "fields", {}), dict) else {}
        label = "Heatsoak" if event_type.startswith("heatsoak") else _stage_label(fields)
        suffix = _stage_detail_suffix(fields, include_target=True)
        return short_status_text(f"Active: {label} | {_event_stage_status(event_type, fields)}{suffix}", width)
    if snapshot_stage:
        elapsed = str(getattr(status_snapshot, "elapsed", "") or "")
        remaining = str(getattr(status_snapshot, "remaining", "") or "")
        parts = [f"Active: {snapshot_stage}", str(getattr(status_snapshot, "status", "") or "running").replace("_", " ")]
        if elapsed:
            parts.append(f"elapsed={elapsed}")
        if remaining:
            parts.append(f"remaining={remaining}")
        return short_status_text(" | ".join(parts), width)
    return "Active: waiting for stage progress..."


def output_tail_text(output_lines: Iterable[str], *, limit: int = 4, width: int = 120) -> str:
    selected = [short_status_text(line, width) for line in list(output_lines)[-max(0, int(limit)):] if str(line).strip()]
    if not selected:
        return "(no non-progress output yet)"
    return "\n".join(selected)


def run_progress_detail_text(
    *,
    profile_name: str,
    status_snapshot: object,
    phase_line: str,
    events: Iterable[object],
    output_lines: Iterable[str],
) -> str:
    output = output_tail_text(output_lines)
    latest_phase = short_status_text(phase_line or "(waiting for phase output...)", 120)
    return (
        "Run In Progress\n"
        "===============\n\n"
        f"Profile: {profile_name or '-'}\n\n"
        "Current Status\n"
        "--------------\n"
        f"{run_status_detail_text(status_snapshot)}\n"
        f"{active_stage_line_text(status_snapshot, events)}\n"
        f"Latest: {latest_phase}\n\n"
        f"{stage_progress_table_text(events)}\n\n"
        "Output Tail\n"
        "-----------\n"
        f"{output or '(no non-progress output yet)'}"
    )


def locked_run_detail_text(
    *,
    profile_name: str,
    status_snapshot: object,
    phase_line: str,
    events: Iterable[object],
    cancel_requested: bool = False,
) -> str:
    message = (
        "Run In Progress\n"
        "===============\n\n"
        f"Profile: {profile_name or '-'}\n\n"
        "Navigation and edits are locked while the workload is active.\n\n"
        "Press Esc or the footer Back action to request safe cancellation. "
        "Cancellation stops active workers and saves partial run results through the existing operator-stop path.\n\n"
        f"{run_status_detail_text(status_snapshot)}\n"
        f"Latest phase: {phase_line or '(waiting for phase output...)'}\n\n"
        f"{stage_progress_table_text(events)}\n\n"
        f"{run_event_history_text(events, limit=5)}"
    )
    if cancel_requested:
        message += "\n\nCancel requested: stopping active workers and saving partial run results."
    return message


def locked_post_run_wall_wattage_text() -> str:
    return (
        "Run Complete\n"
        "============\n\n"
        "Enter wall wattage in the input field, or leave it blank and press Enter to skip. "
        "Press Esc to cancel this prompt."
    )


def locked_post_run_upload_text() -> str:
    return (
        "Run Complete\n"
        "============\n\n"
        "Choose Upload to Google Drive or Skip upload from the sidebar. "
        "Press Esc to skip this prompt."
    )


def _artifact_status_line(result_dir: Path, artifact_names: set[str], label: str, filename: str) -> str:
    available = filename in artifact_names or (result_dir / filename).exists()
    return f"- {label}: {'available' if available else 'missing'} ({filename})"


def post_run_operator_presentation(
    base_text: str,
    *,
    result_dir: Path | None,
    artifact_item: Dict[str, Any] | None = None,
    upload_status: str = "",
) -> str:
    item = artifact_item if isinstance(artifact_item, dict) else {}
    artifact_names = {str(name) for name in item.get("artifacts") or [] if str(name)}
    lines = ["TUI Post-Run Context", "--------------------"]
    if result_dir is None:
        lines.extend(
            [
                "Result folder: not available",
                "Artifacts: not available",
                "",
                "Operator Next Steps",
                "-------------------",
                "- Review the failure text and captured phase output above.",
                "- No result-folder actions are available until a result folder exists.",
            ]
        )
        lines.extend(["", "Run / Upload Output", "-------------------", str(base_text).rstrip()])
        return "\n".join(lines) + "\n"

    lines.append(f"Latest result folder: {result_dir}")
    if item.get("kind"):
        lines.append(f"Artifact kind: {item.get('kind')}")
    if item.get("result"):
        lines.append(f"Artifact result: {item.get('result')}")
    if upload_status:
        lines.append(f"Upload status: {upload_status}")
    lines.extend(
        [
            "",
            "Artifact Availability",
            "---------------------",
            _artifact_status_line(result_dir, artifact_names, "Parsed results", "parsed_results_custom.json"),
            _artifact_status_line(result_dir, artifact_names, "Run summary", "run_summary.txt"),
            _artifact_status_line(result_dir, artifact_names, "Validation report", "result_validation.json"),
            _artifact_status_line(result_dir, artifact_names, "Pre-import sanity", "pre_import_sanity.json"),
            _artifact_status_line(result_dir, artifact_names, "Telemetry source map", "telemetry_source_map.json"),
            _artifact_status_line(result_dir, artifact_names, "Raw telemetry", "raw_telemetry.csv"),
            "",
            "Operator Next Steps",
            "-------------------",
            "- Press W to add or update observed wall wattage.",
            "- Press G to upload this latest result if Google Drive is configured.",
            "- Open Results to review this latest result, then use E for QA review, F for artifacts, V for validation, or M for pre-import.",
            "",
            "Run / Upload Output",
            "-------------------",
            str(base_text).rstrip(),
        ]
    )
    return "\n".join(lines) + "\n"
