"""Mount-backed target resolution and safety policy for Storage Benchmark v1."""

from __future__ import annotations

import os
import math
import re
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable


GIB = 1024**3
MAX_TEST_SIZE_GIB = 8
_REJECTED_PREFIXES = ("loop", "ram", "zram", "nbd", "rbd", "sr", "fd")
_REJECTED_FILESYSTEMS = {
    "overlay", "tmpfs", "ramfs", "squashfs", "nfs", "nfs4", "cifs", "9p",
    "proc", "sysfs", "devtmpfs", "fuse.sshfs", "ceph", "glusterfs",
    "zfs", "bcachefs",
}
_COW_FILESYSTEMS = {"btrfs"}


@dataclass(frozen=True)
class MountRecord:
    major_minor: str
    mount_point: Path
    filesystem: str
    source: str


@dataclass(frozen=True)
class StorageBenchmarkTarget:
    target_path: Path
    mount_point: Path
    mount_source: str
    major_minor: str
    physical_devices: tuple[str, ...]
    is_system_drive: bool
    free_bytes: int
    stat_device: int
    filesystem_type: str = ""
    is_cow: bool = False
    filesystem_policy: str = "supported_direct_io"
    mapping_source: str = "sys_dev_block"
    resolution_warning: str = ""
    used_percent_at_selection: float | None = None
    total_bytes_at_selection: int | None = None
    used_bytes_at_selection: int | None = None
    free_bytes_at_selection: int | None = None
    selection_phase: str = ""

    @property
    def primary_block_name(self) -> str:
        return Path(self.physical_devices[0]).name


@dataclass(frozen=True)
class StorageBenchmarkSkippedTarget:
    device: str
    model: str
    reason: str
    eligible_internal: bool
    target_path: Path | None = None
    filesystem_type: str = ""
    filesystem_policy: str = ""
    is_cow: bool | None = None
    mapping_source: str = ""
    resolution_warning: str = ""
    used_percent_at_selection: float | None = None
    total_bytes_at_selection: int | None = None
    used_bytes_at_selection: int | None = None
    free_bytes_at_selection: int | None = None
    selection_phase: str = ""


@dataclass(frozen=True)
class StorageBenchmarkBatchPlan:
    targets: tuple[StorageBenchmarkTarget, ...]
    target_models: dict[str, str]
    skipped_targets: tuple[StorageBenchmarkSkippedTarget, ...]
    root_confirmation_required: bool = False


class LowOccupancyTargetIneligible(ValueError):
    """A safely resolved target no longer satisfies low-occupancy policy."""

    def __init__(self, message: str, target: StorageBenchmarkTarget | None = None) -> None:
        super().__init__(message)
        self.target = target


def _unescape_mount(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), value)


def parse_mountinfo(text: str) -> list[MountRecord]:
    records: list[MountRecord] = []
    for line in text.splitlines():
        fields = line.split()
        if "-" not in fields or len(fields) < 10:
            continue
        separator = fields.index("-")
        if separator + 2 >= len(fields):
            continue
        records.append(MountRecord(
            major_minor=fields[2],
            mount_point=Path(_unescape_mount(fields[4])),
            filesystem=fields[separator + 1],
            source=_unescape_mount(fields[separator + 2]),
        ))
    return records


class StorageTargetResolver:
    def __init__(
        self,
        *,
        mountinfo_path: Path = Path("/proc/self/mountinfo"),
        sys_dev_block: Path = Path("/sys/dev/block"),
        sys_class_block: Path = Path("/sys/class/block"),
        sys_class_nvme: Path = Path("/sys/class/nvme"),
        sys_fs_btrfs: Path = Path("/sys/fs/btrfs"),
        disk_usage: Callable[[str | Path], shutil._ntuple_diskusage] = shutil.disk_usage,
    ) -> None:
        self.mountinfo_path = mountinfo_path
        self.sys_dev_block = sys_dev_block
        self.sys_class_block = sys_class_block
        self.sys_class_nvme = sys_class_nvme
        self.sys_fs_btrfs = sys_fs_btrfs
        self.disk_usage = disk_usage

    def _mount_for(self, path: Path) -> MountRecord:
        candidates = []
        for record in parse_mountinfo(self.mountinfo_path.read_text(encoding="utf-8", errors="replace")):
            try:
                path.relative_to(record.mount_point)
            except ValueError:
                continue
            candidates.append(record)
        if not candidates:
            raise ValueError("target is not backed by a visible mount")
        return max(candidates, key=lambda item: len(item.mount_point.parts))

    def _whole_disk_name(self, name: str) -> str:
        link = self.sys_class_block / name
        if not link.exists():
            raise ValueError(f"block device {name} is absent from sysfs")
        resolved = link.resolve()
        if (link / "partition").exists() or (resolved / "partition").exists():
            return resolved.parent.name
        return name

    def _leaves(self, name: str, seen: set[str] | None = None) -> set[str]:
        visited = seen or set()
        if name in visited:
            raise ValueError("cycle detected in block-device stack")
        visited.add(name)
        slaves = self.sys_class_block / name / "slaves"
        children = [child.name for child in slaves.iterdir()] if slaves.is_dir() else []
        if not children:
            return {self._whole_disk_name(name)}
        leaves: set[str] = set()
        for child in children:
            leaves.update(self._leaves(child, visited.copy()))
        return leaves

    def _validate_leaf(self, name: str) -> None:
        if name.startswith(_REJECTED_PREFIXES) or name.startswith(("dm-", "md")):
            raise ValueError(f"unsupported virtual storage leaf: {name}")
        link = self.sys_class_block / name
        resolved = link.resolve()
        resolved_text = str(resolved).lower()
        if "/virtual/" in resolved_text:
            raise ValueError(f"virtual storage target is not supported: {name}")
        try:
            removable = (link / "removable").read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(f"cannot confidently classify {name}: {exc}") from exc
        if removable != "0":
            raise ValueError(f"removable storage target is not supported: {name}")
        if "/usb" in resolved_text or "usb" in [part.lower() for part in resolved.parts]:
            raise ValueError(f"USB storage target is not supported: {name}")
        if any(marker in resolved_text for marker in ("iscsi", "/rport-", "nvme-fabrics")):
            raise ValueError(f"network-backed storage target is not supported: {name}")
        size_path = link / "size"
        try:
            if int(size_path.read_text(encoding="utf-8").strip()) <= 0:
                raise ValueError(f"zero-capacity storage target: {name}")
        except OSError as exc:
            raise ValueError(f"cannot confirm capacity for {name}: {exc}") from exc
        controller = re.match(r"(nvme\d+)", name)
        if controller:
            transport_path = self.sys_class_nvme / controller.group(1) / "transport"
            if transport_path.exists():
                transport = transport_path.read_text(encoding="utf-8").strip().lower()
                if transport not in {"pcie", "pci"}:
                    raise ValueError(f"remote NVMe transport is not supported: {transport or 'unknown'}")

    def _mapper_block_name(self, mapper_name: str) -> str | None:
        if not self.sys_class_block.exists():
            return None
        for link in self.sys_class_block.iterdir():
            name_path = link / "dm" / "name"
            try:
                if name_path.read_text(encoding="utf-8").strip() == mapper_name:
                    return link.name
            except OSError:
                continue
        return None

    def _mount_block_name(self, mount: MountRecord) -> tuple[str, str]:
        dev_link = self.sys_dev_block / mount.major_minor
        if dev_link.exists():
            return dev_link.resolve().name, "sys_dev_block"
        source = str(mount.source or "")
        if source.startswith("/dev/mapper/"):
            block_name = self._mapper_block_name(Path(source).name)
            if block_name:
                return block_name, "mount_source_device_mapper"
        if source.startswith("/dev/"):
            block_name = Path(source).name
            if (self.sys_class_block / block_name).exists():
                return block_name, "mount_source_sysfs"
        raise ValueError("mount cannot be mapped through /sys/dev/block or its named mount source")

    def _btrfs_leaves(self, source_block: str) -> set[str]:
        if not self.sys_fs_btrfs.is_dir():
            raise ValueError("cannot confirm that the btrfs workspace uses exactly one physical device")
        matches: list[set[str]] = []
        for filesystem in self.sys_fs_btrfs.iterdir():
            devices = filesystem / "devices"
            if not devices.is_dir():
                continue
            names = {entry.name for entry in devices.iterdir()}
            if source_block not in names:
                continue
            leaves: set[str] = set()
            for name in names:
                leaves.update(self._leaves(name))
            matches.append(leaves)
        if len(matches) != 1:
            raise ValueError("cannot uniquely identify the btrfs device set for this workspace")
        return matches[0]

    def _mount_leaves_with_source(self, mount: MountRecord) -> tuple[set[str], str]:
        block_name, mapping_source = self._mount_block_name(mount)
        if mount.filesystem.lower() == "btrfs":
            return self._btrfs_leaves(block_name), f"{mapping_source}+btrfs_devices"
        return self._leaves(block_name), mapping_source

    def _mount_leaves(self, mount: MountRecord) -> set[str]:
        return self._mount_leaves_with_source(mount)[0]

    @staticmethod
    def _filesystem_policy(filesystem: str) -> tuple[str, bool, str]:
        normalized = str(filesystem or "").strip().lower()
        if normalized in _REJECTED_FILESYSTEMS or normalized.startswith("fuse"):
            return "unsupported", False, f"unsupported target filesystem: {normalized or 'unknown'}"
        if normalized in _COW_FILESYSTEMS:
            return (
                "cow_supported_with_warning",
                True,
                f"{normalized} is copy-on-write; benchmark results can differ from raw-device behavior",
            )
        return "supported_direct_io", False, ""

    def _device_model(self, name: str) -> str:
        path = self.sys_class_block / name / "device" / "model"
        try:
            return path.read_text(encoding="utf-8", errors="replace").strip() or name
        except OSError:
            return name

    def _whole_disk_names(self) -> list[str]:
        names: list[str] = []
        if not self.sys_class_block.exists():
            return names
        for link in sorted(self.sys_class_block.iterdir(), key=lambda item: item.name):
            name = link.name
            if name.startswith(_REJECTED_PREFIXES) or name.startswith(("dm-", "md")):
                continue
            try:
                resolved = link.resolve()
            except OSError:
                continue
            if (link / "partition").exists() or (resolved / "partition").exists():
                continue
            names.append(name)
        return names

    @staticmethod
    def _mount_choice_key(record: MountRecord, path: Path, workspace_source: str) -> tuple[int, int, str]:
        # Prefer a writable path the operator is already using, then their home,
        # then a writable mount root. Physical ownership is validated separately.
        source_rank = {"current_working_directory": 0, "user_home": 1, "mount_point": 2}
        return (source_rank.get(workspace_source, 3), len(path.parts), str(path))

    def _writable_directories_for_mount(self, record: MountRecord) -> list[tuple[Path, str]]:
        candidates: list[tuple[Path, str]] = []
        for candidate, source in (
            (Path.cwd(), "current_working_directory"),
            (Path.home(), "user_home"),
            (record.mount_point, "mount_point"),
        ):
            try:
                path = candidate.expanduser().resolve(strict=True)
                candidate_mount = self._mount_for(path)
                same_physical_device = self._mount_leaves(candidate_mount) == self._mount_leaves(record)
            except (OSError, ValueError):
                continue
            if same_physical_device and path.is_dir() and os.access(path, os.W_OK | os.X_OK):
                if path not in {item[0] for item in candidates}:
                    candidates.append((path, source))
        return candidates

    def _system_leaves(self, records: list[MountRecord]) -> set[str]:
        leaves: set[str] = set()
        system_mounts = {Path("/"), Path("/etc"), Path("/usr"), Path("/var"), Path("/sysroot")}
        for record in records:
            if record.mount_point not in system_mounts:
                continue
            try:
                leaves.update(self._mount_leaves(record))
            except ValueError:
                continue
        return leaves

    @staticmethod
    def validate_max_used_percent(value: Any) -> float:
        try:
            threshold = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("max_used_percent must be a finite number from 0.0 through 100.0") from exc
        if not math.isfinite(threshold) or not 0.0 <= threshold <= 100.0:
            raise ValueError("max_used_percent must be a finite number from 0.0 through 100.0")
        return threshold

    @staticmethod
    def _required_free_bytes(test_size_gib: int) -> int:
        size_bytes = int(test_size_gib) * GIB
        return 2 * size_bytes + max(2 * GIB, size_bytes)

    def _occupancy_target(
        self,
        target: StorageBenchmarkTarget,
        *,
        test_size_gib: int,
        max_used_percent: float,
        selection_phase: str,
        refresh_usage: bool,
    ) -> StorageBenchmarkTarget:
        threshold = self.validate_max_used_percent(max_used_percent)
        if refresh_usage:
            try:
                usage = self.disk_usage(target.target_path)
            except Exception as exc:
                raise LowOccupancyTargetIneligible(
                    f"selected filesystem usage could not be measured safely: {exc}", target
                ) from exc
            total_bytes = int(usage.total)
            used_bytes = int(usage.used)
            free_bytes = int(usage.free)
        else:
            total_bytes = int(target.total_bytes_at_selection or 0)
            used_bytes = int(target.used_bytes_at_selection or 0)
            free_bytes = int(target.free_bytes_at_selection if target.free_bytes_at_selection is not None else target.free_bytes)
        if total_bytes <= 0:
            raise LowOccupancyTargetIneligible(
                "selected filesystem reports zero or invalid total capacity", target
            )
        used_percent = 100.0 * used_bytes / total_bytes
        measured = replace(
            target,
            free_bytes=free_bytes,
            used_percent_at_selection=used_percent,
            total_bytes_at_selection=total_bytes,
            used_bytes_at_selection=used_bytes,
            free_bytes_at_selection=free_bytes,
            selection_phase=selection_phase,
        )
        if used_percent > threshold:
            raise LowOccupancyTargetIneligible(
                f"selected filesystem usage {used_percent:.2f}% exceeds configured maximum {threshold:.2f}%",
                measured,
            )
        required = self._required_free_bytes(test_size_gib)
        if free_bytes < required:
            raise LowOccupancyTargetIneligible(
                f"insufficient free space: {required} bytes required, {free_bytes} bytes available",
                measured,
            )
        return measured

    def revalidate_low_occupancy(
        self,
        target: StorageBenchmarkTarget,
        *,
        test_size_gib: int,
        max_used_percent: float,
    ) -> StorageBenchmarkTarget:
        self.revalidate(target)
        records = parse_mountinfo(self.mountinfo_path.read_text(encoding="utf-8", errors="replace"))
        physical_names = {Path(device).name for device in target.physical_devices}
        if target.is_system_drive or physical_names & self._system_leaves(records):
            raise LowOccupancyTargetIneligible(
                "root/system drive is always excluded by all_internal_non_root_low_occupancy",
                target,
            )
        return self._occupancy_target(
            target,
            test_size_gib=test_size_gib,
            max_used_percent=max_used_percent,
            selection_phase="execution_recheck",
            refresh_usage=True,
        )

    def discover_all_eligible(
        self,
        *,
        test_size_gib: int,
        root_confirmation: str | None = None,
        max_used_percent: float | None = None,
        exclude_system_drives: bool = False,
    ) -> StorageBenchmarkBatchPlan:
        """Discover one deterministic safe mounted directory per internal drive."""
        if not 1 <= int(test_size_gib) <= MAX_TEST_SIZE_GIB:
            raise ValueError("test size must be between 1 and 8 GiB")
        records = parse_mountinfo(self.mountinfo_path.read_text(encoding="utf-8", errors="replace"))
        threshold = (
            self.validate_max_used_percent(max_used_percent)
            if max_used_percent is not None else None
        )
        system_leaves = self._system_leaves(records) if exclude_system_drives else set()
        mounts_by_leaf: dict[str, list[MountRecord]] = {}
        ambiguous_by_leaf: dict[str, list[str]] = {}
        for record in records:
            try:
                leaves = self._mount_leaves(record)
            except ValueError:
                continue
            if len(leaves) != 1:
                for leaf in leaves:
                    ambiguous_by_leaf.setdefault(leaf, []).append(str(record.mount_point))
                continue
            leaf = next(iter(leaves))
            mounts_by_leaf.setdefault(leaf, []).append(record)

        targets: list[StorageBenchmarkTarget] = []
        skipped: list[StorageBenchmarkSkippedTarget] = []
        models: dict[str, str] = {}
        root_required = False
        for name in self._whole_disk_names():
            device = f"/dev/{name}"
            model = self._device_model(name)
            models[device] = model
            try:
                self._validate_leaf(name)
            except ValueError as exc:
                skipped.append(StorageBenchmarkSkippedTarget(device, model, str(exc), False))
                continue
            if name in system_leaves:
                skipped.append(StorageBenchmarkSkippedTarget(
                    device,
                    model,
                    "root/system drive is always excluded by all_internal_non_root_low_occupancy",
                    True,
                    selection_phase="discovery",
                ))
                continue
            candidates = mounts_by_leaf.get(name, [])
            if not candidates:
                reason = (
                    "only ambiguous multi-device storage stacks are mounted"
                    if ambiguous_by_leaf.get(name)
                    else "no mounted writable directory maps to this internal drive"
                )
                skipped.append(StorageBenchmarkSkippedTarget(device, model, reason, True))
                continue
            safe_candidates: list[tuple[MountRecord, Path, str]] = []
            for record in candidates:
                policy, _is_cow, _warning = self._filesystem_policy(record.filesystem)
                if policy == "unsupported":
                    continue
                for path, workspace_source in self._writable_directories_for_mount(record):
                    safe_candidates.append((record, path, workspace_source))
            if not safe_candidates:
                skipped.append(StorageBenchmarkSkippedTarget(
                    device, model, "mounted paths are not writable or use an unsupported filesystem", True
                ))
                continue
            selected, selected_path, workspace_source = min(
                safe_candidates,
                key=lambda item: self._mount_choice_key(item[0], item[1], item[2]),
            )
            try:
                target = self.resolve(
                    selected_path,
                    test_size_gib=test_size_gib,
                    root_confirmation=None if exclude_system_drives else root_confirmation,
                    check_free_space=threshold is None,
                )
            except OSError as exc:
                if threshold is None:
                    raise
                skipped.append(StorageBenchmarkSkippedTarget(
                    device=device,
                    model=model,
                    reason=f"selected filesystem usage could not be measured safely: {exc}",
                    eligible_internal=True,
                    target_path=selected_path,
                    filesystem_type=selected.filesystem.lower(),
                    selection_phase="discovery",
                ))
                continue
            except ValueError as exc:
                if "BENCHMARK ROOT" in str(exc):
                    root_required = True
                skipped.append(StorageBenchmarkSkippedTarget(device, model, str(exc), True))
                continue
            except Exception as exc:
                if threshold is None:
                    raise
                skipped.append(StorageBenchmarkSkippedTarget(
                    device=device,
                    model=model,
                    reason=f"selected filesystem usage could not be measured safely: {exc}",
                    eligible_internal=True,
                    target_path=selected_path,
                    filesystem_type=selected.filesystem.lower(),
                    selection_phase="discovery",
                ))
                continue
            if threshold is not None:
                try:
                    target = self._occupancy_target(
                        target,
                        test_size_gib=test_size_gib,
                        max_used_percent=threshold,
                        selection_phase="discovery",
                        refresh_usage=False,
                    )
                except LowOccupancyTargetIneligible as exc:
                    measured = exc.target or target
                    skipped.append(StorageBenchmarkSkippedTarget(
                        device=device,
                        model=model,
                        reason=str(exc),
                        eligible_internal=True,
                        target_path=measured.target_path,
                        filesystem_type=measured.filesystem_type,
                        filesystem_policy=measured.filesystem_policy,
                        is_cow=measured.is_cow,
                        mapping_source=measured.mapping_source,
                        resolution_warning=measured.resolution_warning,
                        used_percent_at_selection=measured.used_percent_at_selection,
                        total_bytes_at_selection=measured.total_bytes_at_selection,
                        used_bytes_at_selection=measured.used_bytes_at_selection,
                        free_bytes_at_selection=measured.free_bytes_at_selection,
                        selection_phase="discovery",
                    ))
                    continue
            selection_warnings: list[str] = []
            if workspace_source != "mount_point":
                selection_warnings.append(
                    f"Writable workspace selected from {workspace_source.replace('_', ' ')} "
                    "because the filesystem mount root is not the benchmark workspace."
                )
            distinct_paths = {path for _record, path, _source in safe_candidates}
            if len(distinct_paths) > 1:
                selection_warnings.append(
                    f"Multiple safe workspaces map to {device}; selected {selected_path} deterministically."
                )
            if selection_warnings:
                target = replace(
                    target,
                    mapping_source=f"{target.mapping_source}+{workspace_source}",
                    resolution_warning="; ".join(
                        filter(None, (target.resolution_warning, *selection_warnings))
                    ),
                )
            targets.append(target)
        targets.sort(key=lambda item: (item.primary_block_name, str(item.target_path)))
        skipped.sort(key=lambda item: item.device)
        return StorageBenchmarkBatchPlan(
            targets=tuple(targets),
            target_models=models,
            skipped_targets=tuple(skipped),
            root_confirmation_required=root_required,
        )

    def discover_all_internal_non_root_low_occupancy(
        self,
        *,
        test_size_gib: int,
        max_used_percent: float = 3.0,
    ) -> StorageBenchmarkBatchPlan:
        return self.discover_all_eligible(
            test_size_gib=test_size_gib,
            max_used_percent=max_used_percent,
            exclude_system_drives=True,
        )

    def resolve(
        self,
        selected_path: Path,
        *,
        test_size_gib: int,
        root_confirmation: str | None = None,
        check_free_space: bool = True,
    ) -> StorageBenchmarkTarget:
        if str(selected_path).startswith("/dev/"):
            raise ValueError("raw block-device paths are never accepted")
        path = selected_path.expanduser().resolve(strict=True)
        if not path.is_dir():
            raise ValueError("benchmark target must be a directory")
        if not os.access(path, os.W_OK | os.X_OK):
            raise ValueError("benchmark target directory is not writable")
        if not 1 <= int(test_size_gib) <= MAX_TEST_SIZE_GIB:
            raise ValueError("test size must be between 1 and 8 GiB")
        mount = self._mount_for(path)
        filesystem_policy, is_cow, resolution_warning = self._filesystem_policy(mount.filesystem)
        if filesystem_policy == "unsupported":
            raise ValueError(resolution_warning)
        leaves_set, mapping_source = self._mount_leaves_with_source(mount)
        leaves = sorted(leaves_set)
        if len(leaves) != 1:
            raise ValueError("v1 requires exactly one confidently resolved physical storage device")
        self._validate_leaf(leaves[0])
        usage = self.disk_usage(path)
        size_bytes = int(test_size_gib) * GIB
        required = self._required_free_bytes(test_size_gib)
        if check_free_space and usage.free < required:
            raise ValueError(f"insufficient free space: {required} bytes required")
        records = parse_mountinfo(self.mountinfo_path.read_text(encoding="utf-8", errors="replace"))
        is_system = mount.mount_point == Path("/") or bool(set(leaves) & self._system_leaves(records))
        if is_system:
            if root_confirmation != "BENCHMARK ROOT":
                raise ValueError("root/system drive requires typed confirmation: BENCHMARK ROOT")
            if usage.free - 2 * size_bytes < 10 * GIB:
                raise ValueError("root/system drive must retain at least 10 GiB after allocation")
        return StorageBenchmarkTarget(
            target_path=path,
            mount_point=mount.mount_point,
            mount_source=mount.source,
            major_minor=mount.major_minor,
            physical_devices=tuple(f"/dev/{name}" for name in leaves),
            is_system_drive=is_system,
            free_bytes=usage.free,
            stat_device=path.stat().st_dev,
            filesystem_type=mount.filesystem.lower(),
            is_cow=is_cow,
            filesystem_policy=filesystem_policy,
            mapping_source=mapping_source,
            resolution_warning=resolution_warning,
            used_percent_at_selection=(100.0 * int(usage.used) / int(usage.total)) if int(usage.total) > 0 else None,
            total_bytes_at_selection=int(usage.total),
            used_bytes_at_selection=int(usage.used),
            free_bytes_at_selection=int(usage.free),
        )

    def revalidate(self, target: StorageBenchmarkTarget) -> None:
        path = target.target_path.resolve(strict=True)
        mount = self._mount_for(path)
        leaves = tuple(sorted(f"/dev/{name}" for name in self._mount_leaves(mount)))
        if (
            path.stat().st_dev != target.stat_device
            or mount.major_minor != target.major_minor
            or mount.source != target.mount_source
            or leaves != tuple(sorted(target.physical_devices))
            or (target.filesystem_type and mount.filesystem.lower() != target.filesystem_type)
        ):
            raise RuntimeError("benchmark target mount changed during the run")
