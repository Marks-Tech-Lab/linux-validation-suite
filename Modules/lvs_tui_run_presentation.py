"""Textual-free run-active presentation helpers for the optional TUI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import textwrap
from typing import Any, Dict, Iterable, Tuple

from .lvs_live_telemetry import LiveCpuCore, LiveTelemetrySnapshot, LiveTelemetryValue
from .lvs_run_progress import run_event_history_text, run_status_detail_text, run_timing_detail_lines, short_status_text


RUN_ACTIVE_SIDEBAR_TITLE = "Run Active"
RUN_ACTIVE_SIDEBAR_ROWS: Tuple[str, ...] = (
    "Run in progress\n  navigation locked",
    "V\n  telemetry detail",
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
    cpu_utilization_percent: float | None = None
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
        metrics.cpu_utilization_percent,
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
            cpu_utilization_percent=_metric_number(fields.get("cpu_utilization_percent")),
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
        aggregate_lines = []
        if system.cpu_clock_mhz is not None and not any(
            package.clock_mhz is not None for package in system.cpu_packages
        ):
            aggregate_lines.append(f"  Clock  {_compact_number(system.cpu_clock_mhz)} MHz")
        if system.cpu_utilization_percent is not None:
            aggregate_lines.append(f"  Load   {_compact_number(system.cpu_utilization_percent)}%")
        if aggregate_lines:
            lines.extend(["", "CPU Aggregate", *aggregate_lines])
    elif any(
        value is not None
        for value in (
            system.cpu_package_temp_c,
            system.cpu_package_power_w,
            system.cpu_clock_mhz,
            system.cpu_utilization_percent,
        )
    ):
        lines.extend(["", "CPU"])
        if system.cpu_package_temp_c is not None:
            lines.append(f"  Temp   {_compact_number(system.cpu_package_temp_c)} °C")
        if system.cpu_package_power_w is not None:
            lines.append(f"  Power  {_compact_number(system.cpu_package_power_w)} W")
        if system.cpu_clock_mhz is not None:
            lines.append(f"  Clock  {_compact_number(system.cpu_clock_mhz)} MHz")
        if system.cpu_utilization_percent is not None:
            lines.append(f"  Load   {_compact_number(system.cpu_utilization_percent)}%")
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


def live_snapshot_is_stale(snapshot: LiveTelemetrySnapshot, now_monotonic: float) -> bool:
    age = max(0.0, float(now_monotonic) - snapshot.sampled_monotonic)
    return snapshot.state != "active" or age > max(6.0, snapshot.interval_seconds * 3.0)


def _compact_clock(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{_compact_number(value / 1000.0)}G" if value >= 1000 else f"{_compact_number(value)}M"


def _parts(*parts: str | None) -> str:
    return "  ".join(part for part in parts if part)


def _append_compact_lines(
    lines: list[str], prefix: str, parts: Iterable[str | None], *, width: int = LIVE_SYSTEM_PANE_WIDTH
) -> None:
    tokens = [part for part in parts if part]
    if not tokens:
        return
    continuation = " " * len(prefix)
    current = prefix
    for token in tokens:
        separator = "" if current == prefix else "  "
        if len(current) + len(separator) + len(token) <= width:
            current += separator + token
        else:
            lines.append(current.rstrip())
            current = continuation + token
    lines.append(current.rstrip())


def live_snapshot_text(snapshot: LiveTelemetrySnapshot, *, stale: bool = False) -> str:
    """Render a deliberately compact summary for the 32-column side pane."""
    lines = ["Live Telemetry", "=============="]
    if stale:
        lines.append("STALE snapshot")
    cpu = _parts(
        f"{_compact_number(snapshot.cpu_utilization_percent)}%" if snapshot.cpu_utilization_percent is not None else None,
        f"{_compact_number(snapshot.cpu_temperature_c)}C" if snapshot.cpu_temperature_c is not None else None,
        f"{_compact_number(snapshot.cpu_power_w)}W" if snapshot.cpu_power_w is not None else None,
    )
    if cpu:
        _append_compact_lines(lines, "CPU  ", cpu.split("  "))
        extra = (
            _compact_clock(snapshot.cpu_clock_mhz),
            f"Vcore {_compact_number(snapshot.cpu_vcore_v)}V" if snapshot.cpu_vcore_v is not None else None,
        )
        _append_compact_lines(lines, "     ", extra)
    for gpu in snapshot.gpus[:4]:
        thermal = None
        if gpu.temperature_c is not None:
            thermal = _compact_number(gpu.temperature_c)
            if gpu.hotspot_c is not None:
                thermal += f"/{_compact_number(gpu.hotspot_c)}C"
            else:
                thermal += "C"
        gpu_prefix = f"GPU{gpu.index + 1} "
        _append_compact_lines(
            lines, gpu_prefix, (
                f"{_compact_number(gpu.utilization_percent)}%" if gpu.utilization_percent is not None else None,
                thermal,
                f"{_compact_number(gpu.power_w)}W" if gpu.power_w is not None else None,
            ),
        )
        detail = (
            _compact_clock(gpu.clock_mhz),
            f"VRAM {_compact_number(gpu.vram_used_gib)}/{_compact_number(gpu.vram_total_gib)}G"
            if gpu.vram_used_gib is not None and gpu.vram_total_gib is not None
            else (f"VRAM {_compact_number(gpu.vram_used_gib)}G" if gpu.vram_used_gib is not None else None),
        )
        _append_compact_lines(lines, " " * len(gpu_prefix), detail)
        fan = None
        if gpu.fan_rpm:
            fan = f"Fan {_compact_number(gpu.fan_rpm[0].value)}r"
        elif gpu.fan_duty_percent is not None:
            fan = f"Fan {_compact_number(gpu.fan_duty_percent)}%"
        auxiliary = (
            f"VR {_compact_number(gpu.vram_temperature_c)}C" if gpu.vram_temperature_c is not None else None,
            f"busy {_compact_number(gpu.vram_busy_percent)}%" if gpu.vram_busy_percent is not None else None,
            fan,
            f"{_compact_number(gpu.vddgfx_v)}V" if gpu.vddgfx_v is not None else None,
        )
        _append_compact_lines(lines, " " * len(gpu_prefix), auxiliary)
    if len(snapshot.gpus) > 4:
        lines.append(f"GPU  +{len(snapshot.gpus) - 4} in detail")
    if snapshot.memory_used_gib is not None:
        percent = (
            snapshot.memory_used_gib / snapshot.memory_total_gib * 100.0
            if snapshot.memory_total_gib
            else None
        )
        _append_compact_lines(lines, "RAM  ", (
            f"{_compact_number(snapshot.memory_used_gib)}/{_compact_number(snapshot.memory_total_gib)}G"
            if snapshot.memory_total_gib else f"{_compact_number(snapshot.memory_used_gib)}G",
            f"{_compact_number(percent)}%" if percent is not None else None,
            f"DIMM {_compact_number(max(row.value for row in snapshot.dimm_temperatures))}C"
            if snapshot.dimm_temperatures else None,
        ))
    elif snapshot.dimm_temperatures:
        lines.append(f"DIMM max {_compact_number(max(row.value for row in snapshot.dimm_temperatures))}C")
    if snapshot.storage_temperatures:
        primary = [row for row in snapshot.storage_temperatures if "_sensor_" not in row.key]
        hottest = max(primary or snapshot.storage_temperatures, key=lambda row: row.value)
        identity = hottest.label.replace(" Composite", "")[:14]
        lines.append(f"Disk {identity} {_compact_number(hottest.value)}C")
    cooling = list(snapshot.cooling)
    for row in cooling[:3]:
        label = "CPU fan" if row.semantic == "cpu_fan" else ("Pump" if "pump" in row.semantic else row.label)
        lines.append(f"{label[:14]} {_compact_number(row.value)} RPM")
    if len(cooling) > 3:
        lines.append(f"Fans +{len(cooling) - 3} in detail")
    if snapshot.bmc_state != "unavailable":
        lines.append(f"BMC  {snapshot.bmc_state.upper()}")
    if len(lines) == 2:
        lines.extend(["", "Waiting for first sample..."])
    return "\n".join(lines)


def live_detail_content_width(terminal_width: int) -> int:
    """Conservative content width after the existing sidebar/live-pane layout."""
    width = max(40, int(terminal_width or 0))
    sidebar = min(64, max(32, int(width * 0.28)))
    live_pane = LIVE_SYSTEM_PANE_WIDTH if width >= LIVE_SYSTEM_MIN_TERMINAL_WIDTH else 0
    return max(24, width - sidebar - live_pane - 10)


def _column_lines(
    items: Iterable[str], content_width: int, *, minimum_cell_width: int = 20,
    maximum_columns: int = 6,
) -> tuple[list[str], int]:
    values = [str(item) for item in items]
    if not values:
        return [], 0
    width = max(16, int(content_width or 0))
    widest = max(len(item) for item in values)
    columns = min(maximum_columns, max(1, (width + 3) // (minimum_cell_width + 3)))
    while columns > 1:
        cell_width = (width - (columns - 1) * 3) // columns
        if widest <= cell_width:
            break
        columns -= 1
    if columns == 1:
        lines = []
        for value in values:
            lines.extend(textwrap.wrap(value, width=width, break_long_words=True, break_on_hyphens=True) or [""])
        return lines, 1
    cell_width = (width - (columns - 1) * 3) // columns
    lines = []
    for start in range(0, len(values), columns):
        row = values[start:start + columns]
        lines.append("   ".join(
            item.ljust(cell_width) if index < len(row) - 1 else item
            for index, item in enumerate(row)
        ).rstrip())
    return lines, columns


def live_detail_column_count(items: Iterable[str], content_width: int, *, minimum_cell_width: int = 20) -> int:
    return _column_lines(items, content_width, minimum_cell_width=minimum_cell_width)[1]


def _detail_values(
    title: str, rows: Iterable[LiveTelemetryValue], content_width: int
) -> list[str]:
    values = list(rows)
    if not values:
        return []
    unit_labels = {
        "celsius": "C", "degrees_c": "C", "volts": "V", "watts": "W",
        "amps": "A", "percent": "%", "rpm": "RPM",
    }
    label_counts: dict[str, int] = {}
    for row in values:
        label_counts[row.label] = label_counts.get(row.label, 0) + 1
    rendered = []
    for row in values:
        label = row.label
        if label_counts[label] > 1 and row.provider:
            label = f"{label} [{row.provider}]"
        unit = unit_labels.get(row.unit.lower(), row.unit)
        rendered.append(f"{label}: {_compact_number(row.value)} {unit}".rstrip())
    rendered_lines, _columns = _column_lines(rendered, content_width, minimum_cell_width=24)
    return ["", title, "-" * len(title), *rendered_lines]


def live_snapshot_detail_text(
    snapshot: LiveTelemetrySnapshot, *, stale: bool = False, content_width: int = 80,
    timing_snapshot: object = None,
) -> str:
    lines = ["Live Telemetry Detail", "====================="]
    if timing_snapshot is not None:
        lines.extend(["", *run_timing_detail_lines(timing_snapshot)])
    if stale:
        lines.extend(["", "Snapshot is stale; the last collected values are shown."])
    cpu_rows = []
    for label, value, unit in (
        ("Load", snapshot.cpu_utilization_percent, "%"),
        ("Package temperature", snapshot.cpu_temperature_c, "C"),
        ("Package power", snapshot.cpu_power_w, "W"),
        ("Aggregate clock", snapshot.cpu_clock_mhz, "MHz"),
        ("Measured Vcore", snapshot.cpu_vcore_v, "V"),
    ):
        if value is not None:
            cpu_rows.append(f"{label}: {_compact_number(value)} {unit}")
    if cpu_rows:
        cpu_lines, _columns = _column_lines(cpu_rows, content_width, minimum_cell_width=24)
        lines.extend(["", "CPU", "---", *cpu_lines])
    lines.extend(_detail_values("CPU packages", snapshot.cpu_packages, content_width))
    if snapshot.cpu_cores:
        groups: dict[str, list[LiveCpuCore]] = {}
        for core in snapshot.cpu_cores:
            groups.setdefault(core.core_class, []).append(core)
        labels = {"performance": "Performance cores", "efficiency": "Efficiency cores", "unknown": "CPU cores"}
        for core_class in ("performance", "efficiency", "unknown"):
            cores = groups.get(core_class, [])
            if not cores:
                continue
            lines.extend(["", f"{labels[core_class]} ({len(cores)})"])
            chunks = []
            for core in cores:
                values = _parts(
                    f"{_compact_number(core.utilization_percent)}%" if core.utilization_percent is not None else None,
                    _compact_clock(core.clock_mhz),
                )
                chunks.append(f"{core.label} {values}".rstrip())
            core_lines, _columns = _column_lines(chunks, content_width, minimum_cell_width=19)
            lines.extend(core_lines)
    for gpu in snapshot.gpus:
        rows = []
        for label, value, unit in (
            ("Load", gpu.utilization_percent, "%"), ("Core temperature", gpu.temperature_c, "C"),
            ("Hotspot", gpu.hotspot_c, "C"), ("Power", gpu.power_w, "W"),
            ("Core clock", gpu.clock_mhz, "MHz"), ("VRAM used", gpu.vram_used_gib, "GiB"),
            ("VRAM total", gpu.vram_total_gib, "GiB"), ("VRAM used", gpu.vram_used_percent, "%"),
            ("VRAM busy", gpu.vram_busy_percent, "%"), ("VRAM clock", gpu.vram_clock_mhz, "MHz"),
            ("VRAM temperature", gpu.vram_temperature_c, "C"), ("Fan duty", gpu.fan_duty_percent, "%"),
            ("VDDGFX", gpu.vddgfx_v, "V"),
            ("VDDNB", gpu.vddnb_v, "V"),
        ):
            if value is not None:
                rows.append(f"{label}: {_compact_number(value)} {unit}")
        rows.extend(f"{fan.label}: {_compact_number(fan.value)} RPM" for fan in gpu.fan_rpm)
        if rows:
            gpu_lines, _columns = _column_lines(rows, content_width, minimum_cell_width=22)
            lines.extend(["", f"GPU {gpu.index + 1}", "-----", *gpu_lines])
    lines.extend(_detail_values("Memory", snapshot.dimm_temperatures, content_width))
    lines.extend(_detail_values("Storage", snapshot.storage_temperatures, content_width))
    lines.extend(_detail_values("Cooling", snapshot.cooling, content_width))
    lines.extend(_detail_values("Voltage rails", snapshot.voltages, content_width))
    lines.extend(_detail_values("Platform", snapshot.platform, content_width))
    lines.extend(_detail_values(f"BMC ({snapshot.bmc_state})", snapshot.bmc, content_width))
    if len(lines) == 2:
        lines.extend(["", "Waiting for the first collected telemetry sample."])
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
    snapshot_status = str(getattr(status_snapshot, "status", "") or "")
    if snapshot_status in {"stage_preparing", "cpu_tuning", "cpu_tuned"}:
        return short_status_text(
            f"Active: {snapshot_stage or 'next stage'} | preparing",
            width,
        )
    if snapshot_status in {"stage_complete", "stage_skipped", "between_stages"}:
        return "Active: between stages"
    if snapshot_status in {"manual_abort_requested", "stage_aborted", "run_aborted"}:
        return short_status_text(f"Active: {snapshot_stage or 'stage'} | stopping", width)
    if snapshot_status in {"run_complete", "run_failed", "run_finalizing"}:
        return "Active: run stopped"
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
    timing_snapshot: object = None,
) -> str:
    output = output_tail_text(output_lines)
    latest_phase = short_status_text(phase_line or "(waiting for phase output...)", 120)
    return (
        "Run In Progress\n"
        "===============\n\n"
        f"Profile: {profile_name or '-'}\n\n"
        "Current Status\n"
        "--------------\n"
        f"{run_status_detail_text(status_snapshot, timing_snapshot)}\n"
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
    timing_snapshot: object = None,
) -> str:
    message = (
        "Run In Progress\n"
        "===============\n\n"
        f"Profile: {profile_name or '-'}\n\n"
        "Navigation and edits are locked while the workload is active.\n\n"
        "Press Esc or the footer Back action to request safe cancellation. "
        "Cancellation stops active workers and saves partial run results through the existing operator-stop path.\n\n"
        f"{run_status_detail_text(status_snapshot, timing_snapshot)}\n"
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
