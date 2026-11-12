"""Encrypted ancestry / atomic-system classification. No host device access."""
from copy import deepcopy
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from Modules.lvs_storage_thermal_crypt import crypt_status
from smoke_tests.storage_thermal_runner_checks import TopologyFixture
from smoke_tests.storage_thermal_foundation_checks import rejects


def mapping(f,base,name='dm-0'):
    node=f.root/'virtual'/name;node.mkdir(parents=True);(f.sys/name).symlink_to(node)
    for d in ('dm','holders','slaves'):(node/d).mkdir()
    (node/'slaves'/base.name).symlink_to(base)
    (base/'holders'/name).symlink_to(node)
    for p,v in {'dev':'252:'+name.split('-')[-1],'size':'32768','dm/uuid':'CRYPT-LUKS2-'+'a'*32+'-fixture'}.items():(node/p).write_text(v)
    return node


def run_crypt_kernel_status_checks():
    with tempfile.TemporaryDirectory() as d:
        f=TopologyFixture(d);base=f.disk();node=mapping(f,base);control=Path(d)/'control';control.write_bytes(b'')
        calls=[]
        def ioctl(fd,cmd,data,mutate):
            assert cmd==0xC138FD0C and struct.unpack_from('=I',data,28)[0]==1<<11
            assert not struct.unpack_from('=I',data,28)[0]&(1<<4)  # never keys/table
            calls.append(cmd);struct.pack_into('=III',data,12,360,312,1);struct.pack_into('=II',data,28,1<<5,3)
            data[176:305]=(node/'dm/uuid').read_bytes().ljust(129,b'\0')
            struct.pack_into('=QQiI16s',data,312,0,32768,0,48,b'crypt')
        with patch('Modules.lvs_storage_thermal_crypt.os.fstat',return_value=SimpleNamespace(st_mode=0o20600)),patch('Modules.lvs_storage_thermal_crypt.fcntl.ioctl',side_effect=ioctl):
            assert crypt_status(node,control)['event']==3 and len(calls)==2
            for target,flags in ((b'integrity',1<<5),(b'thin',1<<5),(b'cache',1<<5),(b'crypt',(1<<5)|(1<<6)),(b'crypt',(1<<5)|(1<<1)),(b'crypt',(1<<5)|(1<<8))):
                def bad(fd,cmd,data,mutate):
                    ioctl(fd,cmd,data,mutate);struct.pack_into('=I',data,28,flags);data[336:352]=target.ljust(16,b'\0')
                with patch('Modules.lvs_storage_thermal_crypt.fcntl.ioctl',side_effect=bad):rejects(lambda:crypt_status(node,control))
        (node/'dm/uuid').write_text('CRYPT-PLAIN-fixture');rejects(lambda:crypt_status(node,control))


def run_crypt_topology_checks():
    with tempfile.TemporaryDirectory() as d:
        f=TopologyFixture(d);disk=f.disk();dm=mapping(f,disk)
        proof=dict(device='252:0',uuid=(dm/'dm/uuid').read_text(),event=1,sectors=32768)
        with patch('Modules.lvs_storage_thermal_targets.crypt_status',return_value=proof):
            row=next(r for r in f.resolver.discover(access_mode='shared_readonly_opt_in') if r['identity']['name']=='sda');assert row['eligible'] and row['holder_proofs']
            assert not next(r for r in f.resolver.discover() if r['identity']['name']=='sda')['eligible']  # exclusive unchanged
            (f.proc/'self/mountinfo').write_text('1 0 0:1 / / rw - rootfs rootfs rw\n2 1 252:0 / /var/home/operator/data rw - ext4 /dev/dm-0 rw\n')
            row=next(r for r in f.resolver.discover(access_mode='shared_readonly_opt_in') if r['identity']['name']=='sda');assert row['eligible'] and row['mounted_or_active'] and row['system_drive'] is False
            expected=deepcopy(row)
            with patch('Modules.lvs_storage_thermal_targets.crypt_status',return_value={**proof,'event':2}):rejects(lambda:f.resolver.revalidate(expected))
            for point in ('/','/boot','/var/lib','/etc'):
                (f.proc/'self/mountinfo').write_text('1 0 0:1 / / rw - rootfs rootfs rw\n2 1 252:0 / '+point+' rw - ext4 /dev/dm-0 rw\n')
                r=next(r for r in f.resolver.discover(access_mode='shared_readonly_opt_in') if r['identity']['name']=='sda');assert r['system_drive'] and not r['eligible']
            (f.proc/'self/mountinfo').write_text('1 0 0:1 / / rw - rootfs rootfs rw\n')
            # Two logical Btrfs members on the SAME physical drive are still
            # an unqualified multi-device filesystem, not a single-device proof.
            dm2=mapping(f,disk,'dm-1')
            btrfs=f.root/'btrfs';(btrfs/'uuid/devices/dm-0').mkdir(parents=True);(btrfs/'uuid/devices/dm-1').mkdir()
            f.resolver.sys_fs_btrfs=btrfs
            (f.proc/'self/mountinfo').write_text('1 0 0:1 / / rw - rootfs rootfs rw\n2 1 0:8 / /data rw - btrfs /dev/dm-0 rw\n')
            row=next(r for r in f.resolver.discover(access_mode='shared_readonly_opt_in') if r['identity']['name']=='sda')
            assert not row['eligible'] and any('multi-device' in why for why in row['reasons'])
            (btrfs/'uuid/devices/dm-1').rmdir()
            assert next(r for r in f.resolver.discover(access_mode='shared_readonly_opt_in') if r['identity']['name']=='sda')['eligible']
            (f.proc/'self/mountinfo').write_text('1 0 0:1 / / rw - rootfs rootfs rw\n')
            (dm/'holders/unknown').mkdir();assert not next(r for r in f.resolver.discover(access_mode='shared_readonly_opt_in') if r['identity']['name']=='sda')['eligible'];(dm/'holders/unknown').rmdir()
            (f.proc/'1/ns/mnt').unlink()
            row=next(r for r in f.resolver.discover(access_mode='shared_readonly_opt_in') if r['identity']['name']=='sda');assert not row['eligible'] and row['system_drive'] is None and row['mounted_or_active'] is None and row['classification_status']=='incomplete'


def run_crypt_atomic_overlay_checks():
    with tempfile.TemporaryDirectory() as d:
        f=TopologyFixture(d);first=f.disk();second=f.disk('sdb',serial='DATA');(first/'wwid').write_text('first');(second/'wwid').write_text('second')
        backing=Path(d)/'sysroot'
        for name in ('deploy','upper','work'):(backing/name).mkdir(parents=True)
        text=f'1 0 8:0 / {backing} rw - ext4 /dev/sda rw\n2 1 0:42 / / rw - overlay overlay rw,lowerdir={backing}/deploy,upperdir={backing}/upper,workdir={backing}/work\n3 2 8:1 / /var/home/data rw - ext4 /dev/sdb rw\n'
        (f.proc/'self/mountinfo').write_text(text)
        rows=f.resolver.discover(access_mode='shared_readonly_opt_in');assert rows[0]['system_drive'] and not rows[0]['eligible'];assert rows[1]['eligible'] and not rows[1]['system_drive']
        (f.proc/'self/mountinfo').write_text(text.replace(f'lowerdir={backing}/deploy','lowerdir=unresolved'))
        assert all(not r['eligible'] and not r['topology_complete'] for r in f.resolver.discover(access_mode='shared_readonly_opt_in'))


def run_thermal_deployment_checks():
    from scripts.storage_thermal_prepare import LAUNCHER,prepare
    import ast,subprocess,sys,hashlib
    ast.parse(LAUNCHER)
    with tempfile.TemporaryDirectory() as d:
        launcher=Path(d)/'launch.py';launcher.write_text(LAUNCHER)
        attempted=subprocess.run([sys.executable,'-I',str(launcher),'--fio','/untrusted'],capture_output=True,text=True,timeout=5)
        assert attempted.returncode!=0  # never elevate or accept arbitrary execution paths
        fio=Path(d)/'fio';fio.write_bytes(b'fixture native input');fio.chmod(0o755)
        def build(command,**kwargs):Path(command[command.index('-o')+1]).write_bytes(b'fixture compiled bytes')
        with patch('Modules.lvs_native_helpers.find_c_compiler',return_value='/fixture/compiler'),patch('scripts.storage_thermal_prepare.subprocess.run',side_effect=build),patch('Modules.lvs_storage_thermal_backend.capability',return_value={'status':'available'}):
            result=prepare(Path(d)/'bundle',fio)
        import json
        manifest=json.loads((Path(result['directory'])/'manifest.json').read_text())
        assert manifest['source']==result['source']
        for name,digest in manifest['files'].items():assert hashlib.sha256((Path(result['directory'])/name).read_bytes()).hexdigest()==digest
        assert (Path(result['directory'])/'runtime/scripts/storage_thermal_acceptance.py').is_file()
        assert not (Path(result['directory'])/'runtime/settings').exists()
        assert not (Path(result['directory'])/'runtime/.git').exists()
        rejects(lambda:prepare(Path(d)/'bundle',fio))  # no overwrite of a prior prepared scope
        linked=Path(d)/'fio-link';linked.symlink_to(fio)
        rejects(lambda:prepare(Path(d)/'other',linked))
        from Modules.lvs_storage_thermal_recovery import RecoveryScope
        source=Path(d)/'unresolved-source';(source/'build').mkdir(parents=True)
        scope=RecoveryScope(source/'build/storage_thermal_recovery_required.json').enter(evidence_directory='fixture')
        try:rejects(lambda:prepare(Path(d)/'cannot-bypass',fio,root=source))
        finally:scope.close()
        rejects(lambda:prepare(Path(d)/'still-cannot-bypass',fio,root=source))


def run_crypt_system_submount_checks():
    """Actual discovery, not just the path predicate; all endpoints are fixtures."""
    protected=('/usr/bin','/etc/ssl','/boot/efi/vendor','/usr/local/lib','/var/lib/postgresql',
               '/var/log/journal','/var/cache/apps','/var/spool/mail','/var/tmp/work')
    data=('/var/home/operator/data','/home/operator/data','/mnt/data','/media/data',
          '/usr-data','/etc-backup','/bootleg','/var/library','/var/logs','/var/cache-data')
    for encrypted in (False,True):
        with tempfile.TemporaryDirectory() as d:
            f=TopologyFixture(d);system=f.disk('sda');disk=f.disk('sdb',serial='SECOND')
            (system/'wwid').write_text('system');(disk/'wwid').write_text('data')
            major,source='8:1','/dev/sdb';proof={}
            if encrypted:
                dm=mapping(f,disk);major,source='252:0','/dev/dm-0'
                proof=dict(device=major,uuid=(dm/'dm/uuid').read_text(),event=1,sectors=32768)
            def mount_at(point,*,extra='',bind_root='/'):
                (f.proc/'self/mountinfo').write_text(f'1 0 8:0 / / rw - ext4 /dev/sda rw\n2 1 {major} {bind_root} {point} rw - ext4 {source} rw\n'+extra)
            def row():return next(r for r in f.resolver.discover(access_mode='shared_readonly_opt_in') if r['identity']['name']=='sdb')
            with patch('Modules.lvs_storage_thermal_targets.crypt_status',return_value=proof):
                for point in protected+data:
                    mount_at(point);r=row();expect=point in protected
                    assert r['system_drive'] is expect and r['eligible'] is not expect and r['mounted_or_active'] and r['topology_complete'],(encrypted,point,r)
                    assert any('mounted/system/swap' in x for x in r['reasons']) is expect
                # Another volume/mount on the same physical disk does not erase OS use.
                mount_at('/usr/bin',extra=f'3 1 {major} / /mnt/data rw - ext4 {source} rw\n')
                assert row()['system_drive'] and not row()['eligible']
                # Mount root fields identify a bind/subvolume, but destination OS role
                # and the physical backing major/minor remain authoritative.
                mount_at('/etc/ssl',bind_root='/config/certificates');assert row()['system_drive'] and not row()['eligible']
                mount_at('/var/home/operator/data');before=row();assert f.resolver.revalidate(before)['eligible']
                mount_at('/usr/bin');rejects(lambda:f.resolver.revalidate(before))
                # Aliased OS paths are resolved before finding their containing mounts.
                mount_at('/mnt/system-tools')
                resolve=Path.resolve
                def alias(path,*args,**kwargs):
                    return Path('/mnt/system-tools') if path==Path('/usr') else resolve(path,*args,**kwargs)
                with patch.object(Path,'resolve',alias):assert row()['system_drive'] and not row()['eligible']
                # Missing required ancestry never claims a confirmed non-system disk.
                (f.proc/'self/mountinfo').write_text('1 0 8:0 / / rw - ext4 /dev/sda rw\n2 1 250:99 / /usr/bin rw - ext4 /dev/missing rw\n')
                r=row();assert not r['eligible'] and r['system_drive'] is None and not r['topology_complete']
                # Partition ancestry participates in the same proof.
                part=disk/'sdb1';part.mkdir();(f.sys/'sdb1').symlink_to(part)
                (part/'partition').write_text('1');(part/'dev').write_text('8:2');(part/'holders').mkdir()
                (f.proc/'self/mountinfo').write_text('1 0 8:0 / / rw - ext4 /dev/sda rw\n2 1 8:2 / /usr/bin rw - ext4 /dev/sdb1 rw\n')
                assert row()['system_drive'] and not row()['eligible']
                # Btrfs subvolume and bind aliases on an encrypted/direct member.
                btrfs=f.root/'system-btrfs';member='dm-0' if encrypted else 'sdb'
                (btrfs/'uuid/devices'/member).mkdir(parents=True);f.resolver.sys_fs_btrfs=btrfs
                (f.proc/'self/mountinfo').write_text(f'1 0 8:0 / / rw - ext4 /dev/sda rw\n2 1 0:8 /@certs /etc/ssl rw - btrfs {source} rw\n')
                assert row()['system_drive'] and not row()['eligible']
