"""Mount-backed target resolution and safety policy for Storage Benchmark v1."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


GIB = 1024**3
MAX_TEST_SIZE_GIB = 8
_REJECTED_PREFIXES = ("loop", "ram", "zram", "nbd", "rbd", "sr", "fd")
_REJECTED_FILESYSTEMS = {
    "overlay", "tmpfs", "ramfs", "squashfs", "nfs", "nfs4", "cifs", "9p",
    "proc", "sysfs", "devtmpfs", "fuse.sshfs", "ceph", "glusterfs",
    "btrfs", "zfs",
}


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

    @property
    def primary_block_name(self) -> str:
        return Path(self.physical_devices[0]).name


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
        disk_usage: Callable[[str | Path], shutil._ntuple_diskusage] = shutil.disk_usage,
    ) -> None:
        self.mountinfo_path = mountinfo_path
        self.sys_dev_block = sys_dev_block
        self.sys_class_block = sys_class_block
        self.sys_class_nvme = sys_class_nvme
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

    def _mount_leaves(self, mount: MountRecord) -> set[str]:
        dev_link = self.sys_dev_block / mount.major_minor
        if not dev_link.exists():
            raise ValueError("mount cannot be mapped through /sys/dev/block")
        return self._leaves(dev_link.resolve().name)

    def resolve(
        self,
        selected_path: Path,
        *,
        test_size_gib: int,
        root_confirmation: str | None = None,
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
        if mount.filesystem.lower() in _REJECTED_FILESYSTEMS or mount.filesystem.lower().startswith("fuse"):
            raise ValueError(f"unsupported target filesystem: {mount.filesystem}")
        leaves = sorted(self._mount_leaves(mount))
        if len(leaves) != 1:
            raise ValueError("v1 requires exactly one confidently resolved physical storage device")
        self._validate_leaf(leaves[0])
        usage = self.disk_usage(path)
        size_bytes = int(test_size_gib) * GIB
        required = 2 * size_bytes + max(2 * GIB, size_bytes)
        if usage.free < required:
            raise ValueError(f"insufficient free space: {required} bytes required")
        is_system = mount.mount_point == Path("/")
        if not is_system:
            root_mount = next(
                (record for record in parse_mountinfo(self.mountinfo_path.read_text(encoding="utf-8", errors="replace"))
                 if record.mount_point == Path("/")),
                None,
            )
            if root_mount is not None:
                try:
                    is_system = bool(set(leaves) & self._mount_leaves(root_mount))
                except ValueError:
                    # An unresolvable root mapping must not weaken validation of
                    # an otherwise confidently isolated non-root target.
                    pass
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
        )

    def revalidate(self, target: StorageBenchmarkTarget) -> None:
        path = target.target_path.resolve(strict=True)
        mount = self._mount_for(path)
        if path.stat().st_dev != target.stat_device or mount.major_minor != target.major_minor or mount.source != target.mount_source:
            raise RuntimeError("benchmark target mount changed during the run")
