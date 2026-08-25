#!/usr/bin/env python3
"""Local IPMI/BMC snapshot parsing and slow-cadence collection."""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


BMC_REFRESH_INTERVAL_SECONDS = 60.0
BMC_STALE_AFTER_SECONDS = 180.0
BMC_COMMAND_TIMEOUT_SECONDS = 8.0

_UNAVAILABLE = {
    "",
    "na",
    "n/a",
    "disabled",
    "no reading",
    "not readable",
    "not available",
}
_THRESHOLD_NAMES = (
    "lower_nonrecoverable",
    "lower_critical",
    "lower_noncritical",
    "upper_noncritical",
    "upper_critical",
    "upper_nonrecoverable",
)


@dataclass(frozen=True)
class BmcSensor:
    """One parsed BMC sensor row."""

    raw_label: str
    normalized_label: str
    sensor_number: str = ""
    entity_id: Optional[int] = None
    entity_instance: Optional[int] = None
    sensor_type: str = ""
    raw_reading: str = ""
    raw_units: str = ""
    metric_class: str = ""
    normalized_value: Optional[float] = None
    normalized_units: str = ""
    component_class: str = "other_platform"
    component_locator: str = ""
    confidence: str = "medium"
    status: str = ""
    thresholds: Mapping[str, Optional[float]] = field(default_factory=dict)
    discrete_state: str = ""

    @property
    def identity(self) -> Tuple[Any, ...]:
        return (
            self.sensor_number,
            self.entity_id if self.entity_id is not None else -1,
            self.entity_instance if self.entity_instance is not None else -1,
            self.metric_class,
            self.normalized_units,
            self.normalized_label,
        )

    def as_dict(self) -> Dict[str, Any]:
        result = {
            "provider": "ipmi_bmc",
            "raw_label": self.raw_label,
            "normalized_label": self.normalized_label,
            "sensor_number": self.sensor_number,
            "entity_id": self.entity_id,
            "entity_instance": self.entity_instance,
            "sensor_type": self.sensor_type,
            "raw_reading": self.raw_reading,
            "raw_units": self.raw_units,
            "metric_class": self.metric_class,
            "normalized_value": self.normalized_value,
            "normalized_units": self.normalized_units,
            "component_class": self.component_class,
            "component_locator": self.component_locator,
            "confidence": self.confidence,
            "status": self.status,
            "thresholds": dict(self.thresholds),
            "discrete_state": self.discrete_state,
        }
        if any(value is not None for value in self.thresholds.values()):
            result["threshold_source"] = "ipmitool sensor"
        return result


@dataclass(frozen=True)
class BmcSnapshot:
    """An immutable completed BMC command snapshot."""

    provider: str
    command: str
    access_mode: str
    captured_at: str
    captured_monotonic: float
    status: str
    sensors: Tuple[BmcSensor, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "command": self.command,
            "access_mode": self.access_mode,
            "captured_at": self.captured_at,
            "status": self.status,
            "sensors": [sensor.as_dict() for sensor in self.sensors],
        }


@dataclass(frozen=True)
class BmcCommandResult:
    command: Tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


def normalize_bmc_label(label: str) -> str:
    return "_".join(re.findall(r"[a-z0-9]+", str(label or "").lower()))


def _unit_definition(raw_units: str) -> Tuple[str, str, str]:
    unit = " ".join(str(raw_units or "").strip().lower().split())
    if unit in {"degrees c", "degree c", "degrees celsius", "c", "deg c"}:
        return "temperature", "c", "c"
    if unit in {"volts", "volt", "v"}:
        return "voltage", "v", "v"
    if unit in {"amps", "amp", "amperes", "ampere", "a"}:
        return "current", "a", "a"
    if unit in {"watts", "watt", "w"}:
        return "power", "w", "w"
    if unit in {"rpm", "revolutions per minute"}:
        return "rotational", "rpm", "rpm"
    if unit in {"percent", "%", "percentage"}:
        return "percentage", "percent", "percent"
    return "", "", ""


def _number(raw: str) -> Optional[float]:
    text = str(raw or "").strip()
    if text.lower() in _UNAVAILABLE or text.lower().startswith("0x"):
        return None
    match = re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text)
    if not match:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _valid_numeric_value(metric_class: str, value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    if metric_class == "temperature" and value <= -273.15:
        return None
    return round(value, 3)


def _parse_sensor_number(raw: str) -> str:
    text = str(raw or "").strip().lower()
    match = re.fullmatch(r"(?:0x)?([0-9a-f]+)h?", text)
    if not match:
        return text
    return format(int(match.group(1), 16), "x")


def _parse_entity(raw: str) -> Tuple[Optional[int], Optional[int]]:
    match = re.fullmatch(r"\s*(\d+)\s*\.\s*(\d+)\s*", str(raw or ""))
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def classify_bmc_component(
    label: str,
    metric_class: str,
    entity_id: Optional[int] = None,
) -> Tuple[str, str, str]:
    """Return conservative component class, locator, and confidence."""
    normalized = normalize_bmc_label(label)
    compact = normalized.replace("_", "")

    dimm = re.search(r"(?:cpu\d+_?)?dimm_?([a-z]+\d+)", normalized)
    ddr_slot = re.search(r"ddr\d*_?([a-z]+\d+)(?:_|$)", normalized)
    if dimm or ddr_slot:
        slot = (dimm or ddr_slot).group(1)
        cpu = re.search(r"cpu(\d+)", compact)
        locator = f"cpu{cpu.group(1)}_dimm{slot}" if cpu else f"dimm_{slot}"
        return "memory_module", locator, "high"

    if "memory_vrm" in normalized or "mem_vrm" in normalized or "dram_vrm" in normalized:
        return "memory_vrm", normalized, "high"
    if any(token in normalized.split("_") for token in ("ddr", "dram", "memory", "mem")) and any(
        token in normalized for token in ("vdd", "vddq", "vpp", "rail")
    ):
        return "memory_rail", normalized, "high"
    if normalized in {"memory_power", "dram_power", "ddr_power"}:
        return "memory_rail", normalized, "high"

    if "vrm_mos" in normalized or "vrm_mosfet" in normalized:
        return "vrm_mos", normalized, "high"
    if re.search(r"(?:^|_)vrm(?:_|$)", normalized):
        return "vrm", normalized, "high"
    if re.search(r"(?:^|_)(?:pch|chipset)(?:_|$)", normalized):
        return "pch", normalized, "high"
    if re.search(r"(?:^|_)(?:motherboard|mainboard|mb)(?:_|$)", normalized):
        return "motherboard", normalized, "high"
    if re.search(r"(?:^|_)system(?:_|$)", normalized):
        return "system", normalized, "high"
    if re.search(r"(?:^|_)inlet(?:_|$)", normalized):
        return "inlet", normalized, "high"
    if re.search(r"(?:^|_)ambient(?:_|$)", normalized):
        return "ambient", normalized, "high"
    if re.search(r"(?:^|_)outlet(?:_|$)", normalized):
        return "outlet", normalized, "high"
    if re.search(r"(?:^|_)(?:psu\d*|power_supply\d*)(?:_|$)", normalized):
        return "psu", normalized, "high"
    if metric_class == "rotational" and re.search(r"(?:^|_)pump\d*(?:_|$)", normalized):
        return "pump", normalized, "high"
    if metric_class == "rotational" and re.search(r"(?:^|_)fan\d*(?:_|$)", normalized):
        return "fan", normalized, "high"
    if re.search(r"(?:^|_)(?:cpu|socket)\d*(?:_|$)", normalized) or normalized.startswith("temp_cpu"):
        component = "socket" if "socket" in normalized else "cpu"
        return component, normalized, "high"
    if re.search(r"(?:^|_)(?:nic|lan)\d*(?:_|$)", normalized):
        return "nic", normalized, "high"
    if re.search(r"(?:^|_)gpu\d*(?:_|$)", normalized):
        return "gpu", normalized, "high"
    if re.search(r"(?:^|_)(?:nvme|ssd|hdd|drive)\d*(?:_|$)", normalized):
        return "storage", normalized, "high"
    if re.search(r"(?:^|_)bmc(?:_|$)", normalized):
        return "bmc", normalized, "high"

    # Entity metadata corroborates an explicit label but does not create a
    # friendly physical classification by itself.
    confidence = "medium" if entity_id is not None else "low"
    return "other_platform", normalized, confidence


def parse_ipmitool_sdr_elist(text: str) -> Tuple[BmcSensor, ...]:
    sensors: List[BmcSensor] = []
    for line in str(text or "").splitlines():
        if "|" not in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 5 or not parts[0]:
            continue
        raw_label, raw_number, status, raw_entity = parts[:4]
        reading = " | ".join(parts[4:]).strip()
        entity_id, entity_instance = _parse_entity(raw_entity)
        reading_match = re.fullmatch(
            r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s+(.+?)\s*",
            reading,
        )
        raw_value = reading_match.group(1) if reading_match else reading
        raw_units = reading_match.group(2) if reading_match else ""
        metric_class, normalized_units, _ = _unit_definition(raw_units)
        value = _valid_numeric_value(metric_class, _number(raw_value)) if metric_class else None
        component, locator, confidence = classify_bmc_component(raw_label, metric_class, entity_id)
        discrete = "" if metric_class else reading
        sensors.append(
            BmcSensor(
                raw_label=raw_label,
                normalized_label=normalize_bmc_label(raw_label),
                sensor_number=_parse_sensor_number(raw_number),
                entity_id=entity_id,
                entity_instance=entity_instance,
                sensor_type=metric_class or "discrete",
                raw_reading=raw_value,
                raw_units=raw_units,
                metric_class=metric_class,
                normalized_value=value,
                normalized_units=normalized_units,
                component_class=component,
                component_locator=locator,
                confidence=confidence,
                status=status,
                discrete_state=discrete,
            )
        )
    return tuple(sensors)


def parse_ipmitool_sensor(text: str) -> Tuple[BmcSensor, ...]:
    sensors: List[BmcSensor] = []
    for line in str(text or "").splitlines():
        if "|" not in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 4 or not parts[0]:
            continue
        raw_label, raw_reading, raw_units, status = parts[:4]
        metric_class, normalized_units, _ = _unit_definition(raw_units)
        if not metric_class:
            sensors.append(
                BmcSensor(
                    raw_label=raw_label,
                    normalized_label=normalize_bmc_label(raw_label),
                    sensor_type="discrete",
                    raw_reading=raw_reading,
                    status=status,
                    discrete_state=raw_reading,
                    confidence="low",
                )
            )
            continue
        value = _valid_numeric_value(metric_class, _number(raw_reading))
        component, locator, confidence = classify_bmc_component(raw_label, metric_class)
        thresholds: Dict[str, Optional[float]] = {}
        for name, raw in zip(_THRESHOLD_NAMES, parts[4:10]):
            thresholds[name] = _valid_numeric_value(metric_class, _number(raw))
        sensors.append(
            BmcSensor(
                raw_label=raw_label,
                normalized_label=normalize_bmc_label(raw_label),
                sensor_type=metric_class,
                raw_reading=raw_reading,
                raw_units=raw_units,
                metric_class=metric_class,
                normalized_value=value,
                normalized_units=normalized_units,
                component_class=component,
                component_locator=locator,
                confidence=confidence,
                status=status,
                thresholds=thresholds,
            )
        )
    return tuple(sensors)


def attach_bmc_thresholds(
    sensors: Iterable[BmcSensor],
    threshold_sensors: Iterable[BmcSensor],
) -> Tuple[BmcSensor, ...]:
    sensor_list = tuple(sensors)
    by_label_unit: Dict[Tuple[str, str], List[BmcSensor]] = {}
    by_label: Dict[str, List[BmcSensor]] = {}
    for threshold in threshold_sensors:
        if threshold.metric_class:
            by_label_unit.setdefault((threshold.normalized_label, threshold.normalized_units), []).append(threshold)
            by_label.setdefault(threshold.normalized_label, []).append(threshold)
    recurring_label_unit_counts: Dict[Tuple[str, str], int] = {}
    recurring_label_counts: Dict[str, int] = {}
    for sensor in sensor_list:
        key = (sensor.normalized_label, sensor.normalized_units)
        recurring_label_unit_counts[key] = recurring_label_unit_counts.get(key, 0) + 1
        recurring_label_counts[sensor.normalized_label] = (
            recurring_label_counts.get(sensor.normalized_label, 0) + 1
        )

    result: List[BmcSensor] = []
    for sensor in sensor_list:
        matches = by_label_unit.get((sensor.normalized_label, sensor.normalized_units), [])
        recurring_count = recurring_label_unit_counts.get(
            (sensor.normalized_label, sensor.normalized_units), 0
        )
        if not sensor.metric_class:
            matches = by_label.get(sensor.normalized_label, [])
            recurring_count = recurring_label_counts.get(sensor.normalized_label, 0)
        # ``ipmitool sensor`` lacks SDR sensor/entity identity. Correlate its
        # static thresholds only when label/unit identity is unique on both
        # sides; missing metadata is safer than cross-attribution.
        if len(matches) != 1 or recurring_count != 1:
            result.append(sensor)
            continue
        metadata = matches[0]
        if sensor.metric_class:
            result.append(replace(sensor, thresholds=dict(metadata.thresholds)))
            continue
        component, locator, confidence = classify_bmc_component(
            sensor.raw_label, metadata.metric_class, sensor.entity_id
        )
        result.append(
            replace(
                sensor,
                sensor_type=metadata.sensor_type,
                raw_units=metadata.raw_units,
                metric_class=metadata.metric_class,
                normalized_units=metadata.normalized_units,
                component_class=component,
                component_locator=locator,
                confidence=confidence,
                thresholds=dict(metadata.thresholds),
                discrete_state="",
            )
        )
    return tuple(result)


def append_static_bmc_discrete_sensors(
    sensors: Iterable[BmcSensor], static_sensors: Iterable[BmcSensor]
) -> Tuple[BmcSensor, ...]:
    """Retain static discrete rows omitted by some ``sdr elist`` outputs."""
    result = list(sensors)
    existing = {(sensor.normalized_label, sensor.metric_class) for sensor in result}
    for sensor in static_sensors:
        identity = (sensor.normalized_label, sensor.metric_class)
        if sensor.metric_class or not sensor.discrete_state or identity in existing:
            continue
        result.append(sensor)
        existing.add(identity)
    return tuple(result)


def bmc_sensor_identity(sensor: BmcSensor) -> Tuple[Any, ...]:
    return sensor.identity


def _key_suffix(sensor: BmcSensor) -> str:
    return {
        "temperature": "c",
        "voltage": "v",
        "current": "a",
        "power": "w",
        "rotational": "rpm",
        "percentage": "percent",
    }.get(sensor.metric_class, sensor.normalized_units)


def build_bmc_source_catalog(sensors: Iterable[BmcSensor]) -> Tuple[Dict[str, Any], ...]:
    numeric = sorted((sensor for sensor in sensors if sensor.metric_class), key=bmc_sensor_identity)
    by_base: Dict[Tuple[str, str], List[BmcSensor]] = {}
    for sensor in numeric:
        slug = sensor.normalized_label or sensor.metric_class
        by_base.setdefault((f"bmc_{slug}", _key_suffix(sensor)), []).append(sensor)
    sources: List[Dict[str, Any]] = []
    for base, suffix in sorted(by_base):
        matches = sorted(by_base[(base, suffix)], key=bmc_sensor_identity)
        for index, sensor in enumerate(matches):
            key = f"{base}_{suffix}" if len(matches) == 1 else f"{base}_{index}_{suffix}"
            sources.append(
                {
                    "key": key,
                    "kind": "ipmi_bmc",
                    "path": "ipmitool",
                    "provider": "ipmi_bmc",
                    "label": sensor.raw_label,
                    "raw_label": sensor.raw_label,
                    "normalized_label": sensor.normalized_label,
                    "sensor_number": sensor.sensor_number,
                    "entity_id": sensor.entity_id,
                    "entity_instance": sensor.entity_instance,
                    "sensor_type": sensor.sensor_type,
                    "metric_class": sensor.metric_class,
                    "raw_units": sensor.raw_units,
                    "normalized_units": sensor.normalized_units,
                    "component_classification": sensor.component_class,
                    "component_locator": sensor.component_locator,
                    "confidence": sensor.confidence,
                    "canonical_identity": list(sensor.identity),
                    "thresholds": dict(sensor.thresholds),
                    "threshold_source": "ipmitool sensor"
                    if any(value is not None for value in sensor.thresholds.values())
                    else "",
                    "sampling_mode": "latest_completed_snapshot",
                    "native_refresh_interval_seconds": BMC_REFRESH_INTERVAL_SECONDS,
                    "stale_after_seconds": BMC_STALE_AFTER_SECONDS,
                }
            )
    return tuple(sources)


def bmc_snapshot_evidence(snapshot: Optional[BmcSnapshot]) -> List[Dict[str, Any]]:
    if snapshot is None:
        return []
    return [sensor.as_dict() for sensor in snapshot.sensors]


def bmc_thermal_compatibility(snapshot: Optional[BmcSnapshot]) -> List[Dict[str, Any]]:
    if snapshot is None:
        return []
    records: List[Dict[str, Any]] = []
    for sensor in snapshot.sensors:
        if sensor.metric_class != "temperature" or sensor.normalized_value is None:
            continue
        compatibility_component = (
            sensor.component_class
            if sensor.component_class in {"cpu", "memory_module", "vrm", "pch", "psu", "nic"}
            else "platform"
        )
        record: Dict[str, Any] = {
            "component_class": compatibility_component,
            "provider": "ipmi_bmc",
            "label": sensor.raw_label,
            "temperature_c": sensor.normalized_value,
            "source": snapshot.command,
            "evidence": {
                "temperature_c": {
                    "provider": "ipmi_bmc",
                    "source": snapshot.command,
                    "raw_field": sensor.raw_label,
                    "raw_value": sensor.raw_reading,
                    "raw_units": sensor.raw_units,
                    "normalized_value": sensor.normalized_value,
                    "normalized_units": "c",
                    "semantic_classification": "bmc_sensor_current",
                    "confidence": sensor.confidence,
                    "derived": False,
                }
            },
        }
        for old_name, new_name in (
            ("upper_noncritical", "upper_noncritical_c"),
            ("upper_critical", "upper_critical_c"),
            ("upper_nonrecoverable", "upper_nonrecoverable_c"),
        ):
            value = sensor.thresholds.get(old_name)
            if value is not None:
                record[new_name] = value
                record["evidence"][new_name] = {
                    "provider": "ipmi_bmc",
                    "source": "ipmitool sensor",
                    "raw_field": old_name,
                    "raw_value": value,
                    "raw_units": sensor.raw_units,
                    "normalized_value": value,
                    "normalized_units": "c",
                    "semantic_classification": old_name,
                    "confidence": sensor.confidence,
                    "derived": False,
                }
        records.append(record)
    return records


RunCommand = Callable[[Sequence[str], float, Mapping[str, str]], BmcCommandResult]


def run_bmc_command(
    command: Sequence[str], timeout: float, environment: Mapping[str, str]
) -> BmcCommandResult:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=dict(environment),
        )
        return BmcCommandResult(
            command=tuple(command),
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
    except subprocess.TimeoutExpired as exc:
        return BmcCommandResult(
            command=tuple(command),
            returncode=-1,
            stdout=str(exc.stdout or ""),
            stderr=str(exc.stderr or ""),
            timed_out=True,
        )
    except Exception as exc:
        return BmcCommandResult(tuple(command), -1, stderr=str(exc))


def local_bmc_available(
    dev_root: Path = Path("/dev"), ipmi_root: Path = Path("/sys/class/ipmi")
) -> bool:
    return bool(list(dev_root.glob("ipmi*")) or list(ipmi_root.glob("ipmi*")))


class BmcSnapshotProvider:
    """Own one nonblocking, slow-cadence local-ipmitool snapshot stream."""

    def __init__(
        self,
        *,
        command_exists: Callable[[str], bool] = lambda name: shutil.which(name) is not None,
        command_env: Callable[[], Mapping[str, str]] = lambda: os.environ.copy(),
        local_available: Callable[[], bool] = local_bmc_available,
        privileged_helper_enabled: bool = False,
        refresh_interval_seconds: float = BMC_REFRESH_INTERVAL_SECONDS,
        stale_after_seconds: float = BMC_STALE_AFTER_SECONDS,
        command_timeout_seconds: float = BMC_COMMAND_TIMEOUT_SECONDS,
        run_command: RunCommand = run_bmc_command,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], str] = lambda: datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        enabled: bool = True,
    ) -> None:
        self.refresh_interval_seconds = float(refresh_interval_seconds)
        self.stale_after_seconds = float(stale_after_seconds)
        self.command_timeout_seconds = float(command_timeout_seconds)
        self._command_env = command_env
        self._privileged_helper_enabled = bool(privileged_helper_enabled)
        self._run_command = run_command
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._lock = threading.Lock()
        self._snapshot: Optional[BmcSnapshot] = None
        self._catalog: Tuple[Dict[str, Any], ...] = ()
        self._future: Optional[Future[Optional[BmcSnapshot]]] = None
        self._executor: Optional[ThreadPoolExecutor] = None
        self._last_attempt = float("-inf")
        self._access_mode = ""
        self._direct_permission_denied = False
        self._access_blocked = False
        self._command_variant: Tuple[str, ...] = ()
        self._thresholds: Tuple[BmcSensor, ...] = ()
        self._closed = False
        self.available = bool(enabled and command_exists("ipmitool") and local_available())
        if self.available:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lvs-bmc")
            self.request_refresh()

    def _command_prefixes(self) -> List[Tuple[str, ...]]:
        if self._access_mode == "direct":
            return [("ipmitool",)]
        if self._access_mode == "sudo":
            return [("sudo", "-n", "ipmitool")]
        prefixes = [] if self._direct_permission_denied else [("ipmitool",)]
        if self._privileged_helper_enabled and os.geteuid() != 0 and shutil.which("sudo"):
            prefixes.append(("sudo", "-n", "ipmitool"))
        return prefixes

    @staticmethod
    def _permission_failure(result: BmcCommandResult) -> bool:
        message = f"{result.stdout}\n{result.stderr}".lower()
        return any(token in message for token in ("permission denied", "insufficient privilege", "could not open device"))

    def _is_closed(self) -> bool:
        with self._lock:
            return self._closed

    def _run_with_access(self, arguments: Sequence[str]) -> Optional[BmcCommandResult]:
        if self._access_blocked:
            return None
        for prefix in self._command_prefixes():
            if self._is_closed():
                return None
            environment = dict(self._command_env())
            environment["LC_ALL"] = "C"
            result = self._run_command(
                (*prefix, *arguments), self.command_timeout_seconds, environment
            )
            if result.returncode == 0 and result.stdout.strip():
                self._access_mode = "sudo" if prefix[0] == "sudo" else "direct"
                return result
            if self._permission_failure(result):
                if prefix[0] == "sudo":
                    self._access_blocked = True
                    break
                self._direct_permission_denied = True
                continue
            break
        return None

    def _refresh(self) -> Optional[BmcSnapshot]:
        variants = [self._command_variant] if self._command_variant else [
            ("sdr", "elist", "full"),
            ("sdr", "elist"),
            ("sensor",),
        ]
        parsed: Tuple[BmcSensor, ...] = ()
        selected: Tuple[str, ...] = ()
        for variant in variants:
            if self._is_closed():
                return None
            result = self._run_with_access(variant)
            if result is None:
                continue
            candidate = parse_ipmitool_sensor(result.stdout) if variant == ("sensor",) else parse_ipmitool_sdr_elist(result.stdout)
            if candidate:
                parsed = candidate
                selected = tuple(variant)
                break
        if not parsed:
            return None
        if self._is_closed():
            return None
        self._command_variant = selected
        if selected == ("sensor",):
            self._thresholds = parsed
        if not self._thresholds and not self._is_closed():
            threshold_result = self._run_with_access(("sensor",))
            if threshold_result is not None:
                self._thresholds = parse_ipmitool_sensor(threshold_result.stdout)
        parsed = attach_bmc_thresholds(parsed, self._thresholds)
        parsed = append_static_bmc_discrete_sensors(parsed, self._thresholds)
        if self._is_closed():
            return None
        captured_monotonic = self._monotonic()
        return BmcSnapshot(
            provider="ipmi_bmc",
            command=" ".join(("ipmitool", *selected)),
            access_mode=self._access_mode or "direct",
            captured_at=self._wall_clock(),
            captured_monotonic=captured_monotonic,
            status="ok",
            sensors=parsed,
        )

    def request_refresh(self, now: Optional[float] = None) -> None:
        current = self._monotonic() if now is None else float(now)
        with self._lock:
            if self._closed or not self.available or self._access_blocked or self._executor is None:
                return
            if self._future is not None and not self._future.done():
                return
            if current - self._last_attempt < self.refresh_interval_seconds:
                return
            self._last_attempt = current
            self._future = self._executor.submit(self._refresh)

    def poll(self, now: Optional[float] = None) -> Optional[BmcSnapshot]:
        current = self._monotonic() if now is None else float(now)
        completed: Optional[Future[Optional[BmcSnapshot]]] = None
        with self._lock:
            if self._future is not None and self._future.done():
                completed = self._future
                self._future = None
        if completed is not None:
            try:
                candidate = completed.result(timeout=0)
            except Exception:
                candidate = None
            if candidate is not None:
                with self._lock:
                    self._snapshot = candidate
                    if not self._catalog:
                        self._catalog = build_bmc_source_catalog(candidate.sensors)
                    else:
                        by_identity = {sensor.identity: sensor for sensor in candidate.sensors}
                        self._catalog = tuple(
                            {
                                **source,
                                "thresholds": dict(by_identity[tuple(source.get("canonical_identity") or ())].thresholds),
                            }
                            if tuple(source.get("canonical_identity") or ()) in by_identity
                            else source
                            for source in self._catalog
                        )
        self.request_refresh(current)
        return self.latest_snapshot(current)

    def latest_snapshot(self, now: Optional[float] = None) -> Optional[BmcSnapshot]:
        current = self._monotonic() if now is None else float(now)
        with self._lock:
            snapshot = self._snapshot
        if snapshot is None or current - snapshot.captured_monotonic >= self.stale_after_seconds:
            return None
        return snapshot

    def source_catalog(self) -> List[Dict[str, Any]]:
        with self._lock:
            snapshot = self._snapshot
            catalog = self._catalog
        last_success = snapshot.captured_at if snapshot is not None else ""
        command = snapshot.command if snapshot is not None else ""
        access_mode = snapshot.access_mode if snapshot is not None else ""
        return [
            {
                **dict(source),
                "command": command,
                "access_mode": access_mode,
                "last_successful_snapshot_at": last_success,
                "last_snapshot_status": snapshot.status if snapshot is not None else "",
                "native_refresh_interval_seconds": self.refresh_interval_seconds,
                "stale_after_seconds": self.stale_after_seconds,
            }
            for source in catalog
        ]

    def sample_values(self, now: Optional[float] = None) -> Dict[str, Optional[float]]:
        current = self._monotonic() if now is None else float(now)
        snapshot = self.poll(current)
        catalog = self.source_catalog()
        values: Dict[str, Optional[float]] = {str(source["key"]): None for source in catalog}
        if snapshot is None:
            return values
        by_identity = {sensor.identity: sensor for sensor in snapshot.sensors}
        for source in catalog:
            identity = tuple(source.get("canonical_identity") or ())
            sensor = by_identity.get(identity)
            if sensor is not None:
                values[str(source["key"])] = sensor.normalized_value
        return values

    def snapshot_for_evidence(self) -> Optional[BmcSnapshot]:
        self.poll()
        with self._lock:
            return self._snapshot

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
