"""Version-1 thermal contracts and pure pilot planning. No discovery or execution.

These provisional activity ceilings are NOT hardware/thermal acceptance. The
standalone runner and active-stack providers are intentionally not implemented.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any

VERSION = 1
POLICY = 'thermal_pilot_v1'
GROUPS = ('all_internal', 'sata_sas', 'nvme', 'hdd', 'ssd', 'individual')
STATES = ('discovered', 'selected', 'blocked', 'ready', 'running', 'completed',
          'failed', 'cancelled', 'incomplete', 'skipped')
# 64 KiB reference operations, deliberately low pilot ceilings; not rated IOPS.
CEILINGS = {'hdd': (30, 2 * 1024**2), 'ssd': (128, 8 * 1024**2),
            'nvme': (256, 16 * 1024**2)}


def integer(value: Any, low: int, high: int, name: str) -> None:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer between {low} and {high}')


@dataclass(frozen=True)
class ThermalConfig:
    contract_id: str = 'lvs.storage_thermal.config'
    contract_version: int = VERSION
    selection: str = 'all_internal'
    device_ids: tuple[str, ...] = ()
    intensity_percent: int = 50
    system_intensity_percent: int = 25
    per_device_percent: dict[str, int] = field(default_factory=dict)
    duration_seconds: int = 120
    block_size: int = 65536
    rate_mode: str = 'percent'
    iops: int | None = None
    bandwidth_bytes_per_second: int | None = None
    monitoring: str = 'required'
    unmonitored_approval: str = ''
    temperature_limit_c: float | None = None
    scheduling: str = 'normal'
    queue_depth: int = 1
    policy: str = POLICY

    def __post_init__(self):
        if (self.contract_id != 'lvs.storage_thermal.config' or self.contract_version != VERSION
                or type(self.contract_version) is not int or self.policy != POLICY):
            raise ValueError('unsupported thermal configuration contract/policy')
        if self.selection not in GROUPS or self.scheduling != 'normal' or self.queue_depth != 1:
            raise ValueError('unsupported selection/scheduling/queue depth')
        integer(self.queue_depth, 1, 1, 'queue depth')
        if not isinstance(self.per_device_percent, dict):
            raise ValueError('per-device overrides must be a mapping')
        if not isinstance(self.device_ids, (tuple, list)) or any(not isinstance(v, str) or not v.strip() for v in self.device_ids):
            raise ValueError('invalid stable device IDs')
        if len(set(self.device_ids)) != len(self.device_ids) or (self.selection == 'individual' and not self.device_ids):
            raise ValueError('individual selection needs distinct device IDs')
        for value in (self.intensity_percent, self.system_intensity_percent, *self.per_device_percent.values()):
            integer(value, 0, 100, 'intensity')
        if any(not isinstance(k, str) or not k.strip() for k in self.per_device_percent):
            raise ValueError('per-device overrides require stable IDs')
        integer(self.duration_seconds, 1, 86400, 'duration')
        integer(self.block_size, 4096, 1048576, 'read size')
        if self.block_size & (self.block_size - 1):
            raise ValueError('read size must be a power of two')
        if self.rate_mode not in ('percent', 'advanced'):
            raise ValueError('unsupported rate mode')
        if self.rate_mode == 'percent' and (self.iops is not None or self.bandwidth_bytes_per_second is not None):
            raise ValueError('percentage and advanced rates are distinct modes')
        if self.rate_mode == 'advanced' and self.iops is None and self.bandwidth_bytes_per_second is None:
            raise ValueError('advanced mode needs a rate')
        for name, value in (('IOPS', self.iops), ('bandwidth', self.bandwidth_bytes_per_second)):
            if value is not None:
                integer(value, 1, 2**40, name)
        if self.monitoring not in ('required', 'approved_unmonitored'):
            raise ValueError('unsupported monitoring policy')
        if not isinstance(self.unmonitored_approval, str) or (self.monitoring == 'approved_unmonitored' and not self.unmonitored_approval.strip()):
            raise ValueError('unmonitored activity requires explicit approval evidence')
        if self.temperature_limit_c is not None and (type(self.temperature_limit_c) not in (int, float)
                or not math.isfinite(self.temperature_limit_c) or not 0 < self.temperature_limit_c < 200):
            raise ValueError('invalid temperature limit; no default safety threshold is assumed')

    def to_dict(self):
        return asdict(self)


def pilot_rate(config: ThermalConfig, device_id: str, drive_class: str, *, system: bool = False) -> dict:
    ThermalConfig(**config.to_dict())  # revalidate nested mutable JSON containers
    if drive_class not in CEILINGS:
        raise ValueError('unknown drive class; no capacity/model-based fallback')
    maximum_iops, maximum_bps = CEILINGS[drive_class]
    percent = config.per_device_percent.get(device_id,
                config.system_intensity_percent if system else config.intensity_percent)
    limits = [maximum_iops, maximum_bps / config.block_size]
    if config.rate_mode == 'percent':
        requested = min(limits) * percent / 100
    else:
        if config.iops is not None:
            limits.append(config.iops)
        if config.bandwidth_bytes_per_second is not None:
            limits.append(config.bandwidth_bytes_per_second / config.block_size)
        requested = min(limits)
    effective = math.floor(requested)
    if requested > 0 and effective == 0:
        raise ValueError('requested rate below one IOPS; no upward rounding or hidden burst mode')
    return dict(policy=POLICY, provisional=True, drive_class=drive_class,
                requested_percent=percent if config.rate_mode == 'percent' else None,
                rate_mode=config.rate_mode, ceiling_iops=maximum_iops, ceiling_bps=maximum_bps,
                requested_iops=requested, effective_iops=effective,
                effective_bps=effective * config.block_size, block_size=config.block_size,
                rounding='floor_to_whole_iops', physical_thermal_acceptance=False)


@dataclass
class ThermalDevice:
    device_id: str
    identity: dict[str, Any]
    state: str = 'discovered'
    selected: bool = False
    system_drive: bool = False
    reasons: list[str] = field(default_factory=list)
    rate: dict[str, Any] = field(default_factory=dict)

    def validate(self):
        if not self.device_id or not isinstance(self.identity, dict) or self.state not in STATES:
            raise ValueError('invalid device contract')
        if self.state == 'blocked' and not self.reasons:
            raise ValueError('blocked devices require reasons')
        if self.state in ('ready', 'running', 'completed') and not self.selected:
            raise ValueError('execution state requires selection')
        if self.system_drive and self.state in ('ready', 'running', 'completed'):
            raise ValueError('system-drive execution has no approved backend')


def readiness(config: ThermalConfig, devices: list[ThermalDevice], backend: dict,
              *, source_provenance: dict | None = None, hardware_identity: dict | None = None) -> dict:
    """Serialize a caller's resolved evidence; never discovers or authorizes devices."""
    ThermalConfig(**config.to_dict())
    for device in devices:
        device.validate()
    if len({d.device_id for d in devices}) != len(devices):
        raise ValueError('duplicate physical targets')
    runnable = [d.device_id for d in devices if d.selected and d.state == 'ready']
    blocked = [d.device_id for d in devices if d.selected and d.state == 'blocked']
    ok = bool(runnable) and not blocked and backend.get('status') == 'available'
    return dict(contract_id='lvs.storage_thermal.readiness', contract_version=VERSION,
                status='BLOCKED', eligibility_status='ELIGIBLE' if ok else 'BLOCKED',
                completion_scope='readiness_only_not_execution',
                configuration=config.to_dict(), devices=[asdict(d) for d in devices], backend=backend,
                source_provenance=source_provenance or {}, hardware_identity=hardware_identity or {},
                candidate_devices=runnable if ok else [], runnable_devices=[], blocked_devices=blocked,
                commands=[], launch_implemented=False,
                reasons=['standalone runner not implemented in Stage 2B-1'])


@dataclass
class ThermalResult:
    device_id: str
    identity: dict[str, Any]
    contract_id: str = 'lvs.storage_thermal.result'
    contract_version: int = VERSION
    state: str = 'selected'
    activity_scope: str = 'unverified'
    source_provenance: dict = field(default_factory=dict)
    executable_provenance: dict = field(default_factory=dict)
    effective_rate: dict = field(default_factory=dict)
    started_monotonic: float | None = None
    ended_monotonic: float | None = None
    duration_completed: bool = False
    cleanup_confirmed: bool = False
    terminal_published: bool = False
    identity_unchanged: bool = False
    guard_confirmed: bool = False
    provenance_confirmed: bool = False
    forced_kill: bool = False
    shutdown_timed_out: bool = False
    safety_stop: bool = False
    exit_code: int | None = None
    read_ios: int = 0
    read_bytes: int = 0
    write_ios: int = 0
    discard_ios: int = 0
    flush_ios: int = 0
    errors: int = 0
    outstanding_descriptors: int = 0
    temperature_status: str = 'unmeasured'
    heating_status: str = 'unmeasured'
    stop_reason: str = ''

    def to_dict(self):
        if self.state not in STATES or not self.device_id or not isinstance(self.identity, dict):
            raise ValueError('invalid result contract')
        return asdict(self)


def result_successful(record: dict) -> bool:
    """Strict terminal contract; arithmetic/integrity verification is not claimed."""
    if not isinstance(record, dict):
        return False
    required = ('duration_completed', 'cleanup_confirmed', 'terminal_published', 'identity_unchanged', 'provenance_confirmed')
    rate = record.get('effective_rate')
    if not isinstance(rate, dict):
        return False
    block_size = rate.get('block_size')
    if type(block_size) is not int or not 4096 <= block_size <= 1048576 or block_size & (block_size-1):
        return False
    started, ended = record.get('started_monotonic'), record.get('ended_monotonic')
    if (type(started) not in (int, float) or type(ended) not in (int, float)
            or not math.isfinite(started) or not math.isfinite(ended) or ended < started):
        return False
    return (record.get('contract_id') == 'lvs.storage_thermal.result'
            and type(record.get('contract_version')) is int and record['contract_version'] == VERSION
            and record.get('state') == 'completed'
            and isinstance(record.get('device_id'), str) and bool(record['device_id'].strip())
            and isinstance(record.get('identity'), dict) and bool(record['identity'])
            and all(isinstance(record.get(k), dict) and bool(record[k]) for k in
                    ('source_provenance', 'executable_provenance'))
            and all(record.get(k) is False for k in ('forced_kill', 'shutdown_timed_out', 'safety_stop'))
            and all(record.get(k) is True for k in required)
            and type(record.get('exit_code')) is int and record['exit_code'] == 0
            and type(record.get('read_ios')) is int and record['read_ios'] > 0
            and type(record.get('read_bytes')) is int and record['read_bytes'] == record['read_ios'] * block_size
            and all(type(record.get(k)) is int and record[k] == 0 for k in
                    ('errors', 'write_ios', 'discard_ios', 'flush_ios', 'outstanding_descriptors'))
            and record.get('guard_confirmed') is True)
