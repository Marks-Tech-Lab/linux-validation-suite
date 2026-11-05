"""Passive thermal inventory, conservative topology proof, exclusive descriptor handoff.

No SMART/blkid probes, device writes or privilege changes. Active stack providers
are not implemented; uncertain host topology is a blocker, not an empty set.
"""
from __future__ import annotations

from collections import Counter
import fcntl
import math
import os
from pathlib import Path
import re
import stat
import struct

from .lvs_storage_inventory import build_storage_device_entry, clean_storage_value
from .lvs_storage_benchmark_target import parse_mountinfo, StorageTargetResolver
from .lvs_telemetry_storage_sources import looks_like_storage_hwmon, sensor_label
from .lvs_telemetry_cpu import read_temperature_path


def text(path: Path, default: str = '') -> str:
    try:
        return path.read_text().strip()
    except (OSError, UnicodeError):
        return default


class ThermalTargets:
    def __init__(self, sys_class=Path('/sys/class/block'), dev_root=Path('/dev'),
                 proc=Path('/proc'), udev=Path('/run/udev/data'), hwmon=Path('/sys/class/hwmon'),
                 sys_fs_btrfs=Path('/sys/fs/btrfs')):
        self.sys_class, self.dev_root, self.proc, self.udev, self.hwmon = map(Path, (sys_class,dev_root,proc,udev,hwmon))
        self.sys_fs_btrfs=Path(sys_fs_btrfs)

    def leaves(self, name: str, seen=()) -> set[str]:
        if name in seen or not (self.sys_class/name).exists():
            raise ValueError('missing/cyclic block topology')
        node = self.sys_class/name
        if (node/'partition').exists():
            return self.leaves(node.resolve().parent.name, (*seen,name))
        children = list((node/'slaves').iterdir())
        if children:
            return set().union(*(self.leaves(c.name, (*seen,name)) for c in children))
        return {name}

    def topology(self) -> tuple[set[str],set[str],list[str]]:
        active, system, problems = set(), set(), []
        try:
            # Refuse known containers; mount visibility plus O_EXCL is required.
            if Path('/.dockerenv').exists() or Path('/run/.containerenv').exists():
                problems.append('container host-storage visibility is not proven')
            if (self.proc/'self/ns/mnt').stat().st_ino != (self.proc/'1/ns/mnt').stat().st_ino:
                problems.append('mount namespace differs from PID 1')
            mounts = parse_mountinfo((self.proc/'self/mountinfo').read_text())
            pools=self.proc/'spl/kstat/zfs'
            if pools.is_dir() and any(p.is_dir() for p in pools.iterdir()):
                problems.append('active ZFS pool physical membership has no approved provider')
            if not any(str(m.mount_point)=='/' for m in mounts):
                raise ValueError('root mount is not visible')
            bydev = {text(n/'dev'):n.name for n in self.sys_class.iterdir() if text(n/'dev')}
            memory_fs = {'proc','sysfs','devtmpfs','devpts','tmpfs','ramfs','rootfs','cgroup','cgroup2',
                         'securityfs','debugfs','tracefs','pstore','configfs','mqueue','hugetlbfs','fusectl',
                         'bpf','autofs','efivarfs','rpc_pipefs','binfmt_misc'}
            for mount in mounts:
                if mount.filesystem in memory_fs:
                    continue
                if mount.filesystem=='btrfs':
                    resolver=StorageTargetResolver(sys_class_block=self.sys_class,sys_fs_btrfs=self.sys_fs_btrfs)
                    members=resolver._mount_leaves_with_source(mount)[0]
                else:
                    name = bydev.get(mount.major_minor)
                    members=self.leaves(name) if name else None
                if members is None:
                    # Network-only mounts don't consume a local block target.
                    if mount.filesystem in {'nfs','nfs4','cifs','smb3','9p'}:
                        continue
                    raise ValueError(f'{mount.filesystem} mount {mount.mount_point}: physical membership unresolved')
                active |= members
                if str(mount.mount_point) in ('/','/boot','/boot/efi','/usr','/var'):
                    system |= members
            swaps = (self.proc/'swaps').read_text().splitlines()
            for row in swaps[1:]:
                fields = row.split()
                if not fields:
                    continue
                path = Path(re.sub(r'\\([0-7]{3})',lambda m:chr(int(m[1],8)),fields[0]))
                st = path.stat()
                key = f'{os.major(st.st_rdev if stat.S_ISBLK(st.st_mode) else st.st_dev)}:{os.minor(st.st_rdev if stat.S_ISBLK(st.st_mode) else st.st_dev)}'
                if key not in bydev:
                    raise ValueError('swap physical membership unresolved')
                active |= self.leaves(bydev[key]); system |= self.leaves(bydev[key])
        except (OSError, ValueError) as error:
            problems.append(str(error))
        return active, system, problems

    def sensors(self, node: Path) -> list[dict]:
        result = []
        try:
            device = (node/'device').resolve(strict=True)
        except OSError:
            return result
        for monitor in sorted(self.hwmon.glob('hwmon*')):
            try:
                monitor.resolve(strict=True).relative_to(device)
            except (OSError, ValueError):
                continue
            name = text(monitor/'name')
            if not looks_like_storage_hwmon(name, monitor):
                continue
            for path in sorted(monitor.glob('temp*_input')):
                result.append(dict(path=str(path.resolve()), label=sensor_label(path),
                                   critical_path=str(path.with_name(path.name.replace('_input','_crit')).resolve()),
                                   low_critical_path=str(path.with_name(path.name.replace('_input','_lcrit')).resolve()),
                                   warning_path=str(path.with_name(path.name.replace('_input','_max')).resolve()),
                                   association='exact_sysfs_device_ancestor'))
        return result

    def discover(self) -> list[dict]:
        active, system, topology_problems = self.topology()
        records = []
        for node in sorted(self.sys_class.iterdir()):
            if (node/'partition').exists():
                continue  # whole devices displayed; partitions still participate in topology
            name = node.name; canonical = str(node.resolve())
            dev = text(node/'dev'); props = {}
            for line in text(self.udev/f'b{dev}').splitlines():
                if line.startswith('E:') and '=' in line:
                    k,v=line[2:].split('=',1);props[k]=v
            entry = build_storage_device_entry(node)
            serial = clean_storage_value(text(node/'device/serial') or props.get('ID_SERIAL_SHORT',''))
            wwn = clean_storage_value(text(node/'wwid') or text(node/'device/wwid') or props.get('ID_WWN','')).lower()
            usb = '/usb' in canonical or props.get('ID_BUS')=='usb'
            virtual = '/virtual/' in canonical or name.startswith(('loop','ram','zram','dm-','md','nbd','rbd','sr'))
            raid_drivers={'megaraid_sas','hpsa','smartpqi','aacraid','cciss','3w-9xxx','3w-sas','arcmsr','hptiop','pmcraid'}
            controller_raid=any((p/'driver').is_symlink() and (p/'driver').resolve().name in raid_drivers for p in node.resolve().parents)
            virtual=virtual or controller_raid or bool(text(node/'device/raid_level'))
            removable = text(node/'removable')
            transport = ('usb' if usb else 'nvme' if name.startswith('nvme') else
                         'sata' if re.search(r'/ata\d+/',canonical) else
                         'sas' if '/end_device-' in canonical and '/port-' in canonical else 'unknown')
            # Positive direct ATA / SAS end-device topology, not controller/model guesses.
            direct = transport in ('sata','sas') and not any(s in canonical.lower() for s in ('/raid','/virtual/','/usb'))
            if transport=='sas':
                ends=[p for p in node.resolve().parents if p.name.startswith('end_device-')]
                direct=direct and any(text(p/'sas_device'/p.name/'sas_address') for p in ends)
            rotating = text(node/'queue/rotational')
            drive_class = 'nvme' if transport=='nvme' else 'hdd' if rotating=='1' else 'ssd' if rotating=='0' else 'unknown'
            stable = f'wwn:{wwn}' if wwn else f'serial:{transport}:{serial}' if serial else ''
            reasons = list(topology_problems)
            if not stable: reasons.append('authoritative serial/WWN unavailable')
            if removable != '0': reasons.append('removable/internal classification uncertain or removable')
            if virtual or usb: reasons.append('virtual/USB backend has no execution proof')
            if drive_class != 'hdd': reasons.append('only inactive physical HDD execution is approved')
            if not direct: reasons.append('independent physical ATA/SAS end-device path not proven')
            try:
                related = [node]+[c for c in self.sys_class.iterdir() if (c/'partition').exists() and c.resolve().parent==node.resolve()]
                if any(list((c/'holders').iterdir()) or ((c/'slaves').is_dir() and list((c/'slaves').iterdir())) for c in related):
                    reasons.append('active or aggregated storage ownership')
                if (node/'device/raid_level').exists() or (node/'device/raid_component').exists():
                    reasons.append('controller RAID member/volume backend is not approved')
                signatures = [props.get('ID_FS_TYPE','')]
                for child in related[1:]:
                    signatures.append(text(self.udev/f'b{text(child/"dev")}'))
                if any(any(mark in s for mark in ('zfs_member','linux_raid_member','LVM2_member','bcache','mpath')) for s in signatures):
                    reasons.append('storage-stack member signature; raw access not approved')
                size = int(text(node/'size'))*512
                logical = int(text(node/'queue/logical_block_size'))
                major,minor = map(int,dev.split(':'))
                if size<=0 or logical<=0: raise ValueError('invalid geometry')
            except (OSError, ValueError):
                reasons.append('incomplete device geometry/topology');size=0;logical=0;major=minor=-1
            if name in active: reasons.append('mounted/system/swap device is active')
            path = self.dev_root/name
            if not os.access(path,os.R_OK): reasons.append('read permission unavailable; no automatic permission changes')
            identity = dict(device_id=stable or f'unresolved:{dev}:{name}', name=name, path=str(path),
                            sysfs=canonical, major=major, minor=minor, size_bytes=size,
                            logical_sector=logical, serial=serial, wwn=wwn)
            records.append(dict(device_id=identity['device_id'], identity=identity, model=entry['Model'],
                                transport=transport, drive_class=drive_class, internal=removable=='0' and not usb and not virtual,
                                excluded_automatic=usb or virtual, system_drive=name in system,
                                eligible=not reasons, reasons=reasons, sensors=self.sensors(node)))
        duplicates = Counter(r['device_id'] for r in records)
        for row in records:
            if duplicates[row['device_id']]>1:
                row['eligible']=False;row['reasons'].append('duplicate/ambiguous physical identity')
        return records

    def revalidate(self, expected: dict) -> dict:
        matches = [r for r in self.discover() if r['device_id']==expected['device_id']]
        if len(matches)!=1 or not matches[0]['eligible'] or matches[0]['identity'] != expected['identity']:
            raise ValueError('device identity, permissions or active topology changed')
        return matches[0]

    def output_safe(self, path: Path, records: list[dict]):
        """Reports may not be stored on a selected target; no content is opened."""
        path=Path(path).resolve()
        while not path.exists():path=path.parent
        candidates=[m for m in parse_mountinfo((self.proc/'self/mountinfo').read_text())
                    if path==m.mount_point or m.mount_point in path.parents]
        if not candidates:raise ValueError('results filesystem cannot be identified')
        mount=max(candidates,key=lambda m:len(m.mount_point.parts))
        if mount.filesystem in ('tmpfs','ramfs','rootfs'):return
        resolver=StorageTargetResolver(sys_class_block=self.sys_class,sys_fs_btrfs=self.sys_fs_btrfs)
        leaves=resolver._mount_leaves_with_source(mount)[0]
        if leaves & {r['identity']['name'] for r in records}:
            raise ValueError('result destination is on a selected target')

    def open(self, expected: dict) -> int:
        self.revalidate(expected)
        fd = os.open(expected['identity']['path'],os.O_RDONLY|os.O_DIRECT|os.O_EXCL|os.O_CLOEXEC|os.O_NOFOLLOW)
        try:
            info=os.fstat(fd); identity=expected['identity']
            size=struct.unpack('Q',fcntl.ioctl(fd,0x80081272,bytes(8)))[0]
            logical=struct.unpack('I',fcntl.ioctl(fd,0x1268,bytes(4)))[0]
            flags=fcntl.fcntl(fd,fcntl.F_GETFL)
            if (not stat.S_ISBLK(info.st_mode) or (os.major(info.st_rdev),os.minor(info.st_rdev))!=(identity['major'],identity['minor'])
                    or size!=identity['size_bytes'] or logical!=identity['logical_sector']
                    or flags & os.O_ACCMODE != os.O_RDONLY or not flags & os.O_DIRECT):
                raise ValueError('opened descriptor identity/geometry/flags mismatch')
            self.revalidate(expected)
            return fd
        except BaseException:
            os.close(fd);raise


def selected(record: dict, config) -> bool:
    if config.selection=='individual':
        return record['device_id'] in config.device_ids
    if record['excluded_automatic'] or not record['internal']:
        return False
    return (config.selection=='all_internal'
            or config.selection=='sata_sas' and record['transport'] in ('sata','sas')
            or config.selection=='nvme' and record['transport']=='nvme'
            or config.selection in ('hdd','ssd') and (record['drive_class']=='hdd' if config.selection=='hdd' else record['drive_class'] in ('ssd','nvme')))


def temperature(record: dict) -> dict:
    readings=[];critical=[];warnings=[];low=[]
    for source in record['sensors']:
        value=read_temperature_path(Path(source['path']))
        if value is not None and math.isfinite(value) and -40<=value<200:
            readings.append(value)
        for field,values in (('critical_path',critical),('warning_path',warnings)):
            try:
                limit=float(text(Path(source[field])))/1000
                if math.isfinite(limit) and 0<limit<200:values.append(limit)
            except (KeyError,ValueError):pass
        try:
            lower=float(text(Path(source['low_critical_path'])))/1000
            if math.isfinite(lower) and -40<=lower<100:low.append(lower)
        except (KeyError,ValueError):pass
    return dict(value_c=max(readings) if readings else None,
                critical_c=min(critical) if critical else None, warning_c=min(warnings) if warnings else None,
                low_critical_c=max(low) if low else None,
                complete=bool(readings) and len(readings)==len(record['sensors']))
