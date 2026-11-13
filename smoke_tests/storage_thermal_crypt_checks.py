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


def run_overlay_layer_syntax_checks():
    from Modules.lvs_storage_thermal_mounts import overlay_layers
    def parse(options):return overlay_layers('1 0 0:42 / / ro - overlay overlay '+options)[0]
    assert parse(r'ro,lowerdir=/lower\072name:/second::/data\054name')==[
        ('lower',Path('/lower:name')),('lower',Path('/second')),('data',Path('/data,name'))]
    assert parse(r'ro,lowerdir+=/lower:literal,datadir+=/data\040space,datadir+=/other')==[
        ('lower',Path('/lower:literal')),('data',Path('/data space')),('data',Path('/other'))]
    assert parse(r'ro,lowerdir=/lower\:name,upperdir=/upper\,name,workdir=/work')==[
        ('lower',Path('/lower:name')),('upperdir',Path('/upper,name')),('workdir',Path('/work'))]
    for bad in ('ro','lowerdir=relative','lowerdir=/a/../b','lowerdir=/a,lowerdir=/b',
                'lowerdir=/a,lowerdir+=/b','lowerdir=/a,upperdir=/u','lowerdir=/a:::b',
                'lowerdir=/a:','lowerdir=/a,datadir=/unsupported','lowerdir+=',
                'lowerdir=/a,datadir+=/data\\'):
        rejects(lambda:parse(bad))


def run_ostree_boot_record_checks():
    import ctypes
    from Modules.lvs_storage_thermal_mounts import boot_record
    try:g=ctypes.CDLL('libglib-2.0.so.0')
    except OSError:
        with patch('Modules.lvs_storage_thermal_mounts.ctypes.CDLL',side_effect=OSError('missing')):
            with tempfile.NamedTemporaryFile() as f:
                f.write(b'x');f.flush();rejects(lambda:boot_record(Path(f.name),owner=os.getuid()))
        return  # Optional OS capability, not a new installation requirement.
    ptr=ctypes.c_void_p
    for name,args,result in [('g_variant_parse',[ptr,ctypes.c_char_p,ptr,ptr,ptr],ptr),
        ('g_variant_get_size',[ptr],ctypes.c_size_t),('g_variant_get_data',[ptr],ptr),('g_variant_unref',[ptr],None)]:
        fn=getattr(g,name);fn.argtypes=args;fn.restype=result
    def encoded(value):
        v=g.g_variant_parse(None,value.encode(),None,None,None);assert v
        try:return ctypes.string_at(g.g_variant_get_data(v),g.g_variant_get_size(v))
        finally:g.g_variant_unref(v)
    valid="{'composefs': <true>, 'root.transient': <false>, 'root.transient-ro': <false>, 'backing-root-device-inode': <(uint64 40, uint64 999)>}"
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/'booted';p.write_bytes(encoded(valid));p.chmod(0o600)
        assert boot_record(p,owner=os.getuid())['backing-root-device-inode']==(40,999)
        with patch('Modules.lvs_storage_thermal_mounts.ctypes.CDLL',side_effect=OSError('missing')):rejects(lambda:boot_record(p,owner=os.getuid()))
        for bad in (valid.replace('<true>',"<'true'>"),valid.replace('uint64 40','int64 40'),
                    valid.replace("'composefs': <true>,",''),valid.replace("'composefs': <true>,","'composefs': <true>, 'composefs': <false>,")):
            p.write_bytes(encoded(bad));rejects(lambda:boot_record(p,owner=os.getuid()))
        p.write_bytes(b'not a GVariant');rejects(lambda:boot_record(p,owner=os.getuid()))
        p.write_bytes(encoded(valid));p.chmod(0o622);rejects(lambda:boot_record(p,owner=os.getuid()))
        p.chmod(0o600);link=Path(d)/'link';link.symlink_to(p);rejects(lambda:boot_record(link,owner=os.getuid()))


def run_bazzite_composefs_topology_checks():
    """Sanitized observed workstation shape, actual discovery/revalidation; no devices.

    Root-owned OS witness is injected; boot-record codec is tested independently.
    Only private regular files, fake sysfs and fake mapping INFO responses are used.
    """
    with tempfile.TemporaryDirectory() as d:
        f=TopologyFixture(d)
        # Two PCIe controllers, one namespace each; five partition-backed LUKS2s.
        (f.root/'nvme').mkdir();nodes=[];mappings=[]
        for index in range(2):
            controller=f.root/'pci/nvme'/f'nvme{index}';node=controller/f'nvme{index}n1';node.mkdir(parents=True)
            for sub in ('queue','holders','slaves'):(node/sub).mkdir()
            (node/'device').symlink_to(controller)
            for name,value in {'serial':f'OPAQUE-{index}','transport':'pcie','model':'Sanitized NVMe'}.items():(controller/name).write_text(value)
            for name,value in {'size':'65536','dev':f'259:{index}','removable':'0','queue/rotational':'0','queue/logical_block_size':'512'}.items():(node/name).write_text(value)
            (f.sys/node.name).symlink_to(node);(f.root/'nvme'/controller.name).symlink_to(controller)
            (f.dev/node.name).write_bytes(b'fixture');nodes.append(node)
        for index,drive in enumerate((1,0,0,0,1)):
            node=nodes[drive];part=node/(node.name+f'p{index+1}');part.mkdir()
            (f.sys/part.name).symlink_to(part)
            for sub in ('holders','slaves'):(part/sub).mkdir()
            (part/'partition').write_text(str(index+1));(part/'dev').write_text(f'259:{index+10}');(part/'size').write_text('32768')
            mappings.append(mapping(f,part,f'dm-{index}'))
            (f.root/f'btrfs/fs{index}/devices'/f'dm-{index}').mkdir(parents=True)
        f.resolver.sys_fs_btrfs=f.root/'btrfs'
        backing=f.root/'sysroot';deployment=backing/'ostree/deploy/os/deploy/opaque.0';deployment.mkdir(parents=True)
        image=deployment/'.ostree.cfs';image.write_bytes(b'opaque metadata image')
        (backing/'ostree/repo/objects').mkdir(parents=True)
        bootlink=backing/'ostree/boot.0/os/opaque/0';bootlink.parent.mkdir(parents=True);bootlink.symlink_to(deployment)
        (f.proc/'cmdline').write_text('quiet ostree=/ostree/boot.0/os/opaque/0')
        identity=deployment.stat();record={'composefs':True,'root.transient':False,'root.transient-ro':False,
                                         'backing-root-device-inode':(identity.st_dev,identity.st_ino)}
        rootline=f'1 0 0:42 / / ro - overlay composefs ro,lowerdir+=/run/ostree/.private/cfsroot-lower,datadir+={backing}/ostree/repo/objects,redirect_dir=on,metacopy=on'
        lines=[rootline,f'2 1 0:40 / {backing} rw - btrfs /dev/dm-0 rw',
               '3 1 0:40 /etc /etc rw - btrfs /dev/dm-0 rw',
               '4 1 0:40 /var /var rw - btrfs /dev/dm-0 rw',
               '5 1 0:41 / /boot rw - btrfs /dev/dm-4 rw',
               '6 1 0:50 / /var/home/operator/data-a rw - btrfs /dev/dm-1 rw',
               '7 1 0:51 / /var/home/operator/data-b rw - btrfs /dev/dm-2 rw',
               '8 1 0:52 / /var/home/operator/data-c rw - btrfs /dev/dm-3 rw',
               '9 1 0:9 / /sys/fs/selinux rw - selinuxfs selinuxfs rw',
               '10 1 0:10 / /run/user/1000/doc rw - fuse.portal portal rw',
               '11 1 0:11 / /run/user/1000/gvfs rw - fuse.gvfsd-fuse gvfs rw']
        def write(records): (f.proc/'self/mountinfo').write_text('\n'.join(records)+'\n')
        def proof(node):return dict(device=(node/'dev').read_text(),uuid=(node/'dm/uuid').read_text(),event=1,sectors=32768)
        real_stat=Path.stat
        def trusted_image(path,*args,**kwargs):
            st=real_stat(path,*args,**kwargs)
            if path==image:return SimpleNamespace(st_mode=st.st_mode,st_uid=0)
            return st
        with patch('Modules.lvs_storage_thermal_mounts.boot_record',return_value=record),patch.object(Path,'stat',trusted_image),patch('Modules.lvs_storage_thermal_targets.crypt_status',side_effect=proof):
            write(lines)
            def rows():return {r['identity']['name']:r for r in f.resolver.discover(access_mode='shared_readonly_opt_in') if r['transport']=='nvme'}
            current=rows();data=current['nvme0n1'];system=current['nvme1n1']
            assert data['eligible'] and data['system_drive'] is False and data['topology_complete'],data
            assert system['system_drive'] is True and not system['eligible'] and system['topology_complete'],system
            assert len(data['holder_proofs'])==3 and len(system['holder_proofs'])==2 and len(current)==2
            assert f.resolver.revalidate(data)['eligible']
            # Same data drive becomes system when an essential subtree appears.
            write(lines+['12 1 0:50 /certs /etc/ssl rw - btrfs /dev/dm-1 rw'])
            assert rows()['nvme0n1']['system_drive'] is True;rejects(lambda:f.resolver.revalidate(data))
            for extra in ('12 1 0:91 / /unknown rw - mystery source rw',
                          '12 1 0:91 / /usr/bin rw - fuse.portal portal rw'):
                write(lines+[extra]);result=rows()
                assert not result['nvme0n1']['eligible'] and result['nvme0n1']['system_drive'] is None
                assert result['nvme1n1']['system_drive'] is True
                assert '/unknown' in ' '.join(result['nvme0n1']['reasons']) or '/usr/bin' in ' '.join(result['nvme0n1']['reasons'])
            write(lines+[rootline.replace('1 0 0:42','99 0 0:42').replace('metacopy=on','metacopy=off')])
            assert not rows()['nvme0n1']['eligible']  # identical mount identity, conflicting options
            for bad in (rootline.replace('lowerdir+=','unknownlayer='),rootline.replace('datadir+=','datadir='),rootline.replace('metacopy=on','metacopy=off')):
                write([bad,*lines[1:]]);assert not rows()['nvme0n1']['eligible']
            write(lines)
            for changed in ({**record,'backing-root-device-inode':(0,0)},{**record,'composefs':False},{**record,'root.transient':True}):
                with patch('Modules.lvs_storage_thermal_mounts.boot_record',return_value=changed):
                    result=rows();assert not result['nvme0n1']['eligible'] and result['nvme1n1']['system_drive'] is True
            with patch('Modules.lvs_storage_thermal_mounts.boot_record',side_effect=ValueError('untrusted boot record')):
                assert not rows()['nvme0n1']['eligible']
            (f.proc/'cmdline').write_text('quiet')
            assert not rows()['nvme0n1']['eligible']
            (f.proc/'cmdline').write_text('ostree=/ostree/boot.0/os/opaque/0')
            image.rename(deployment/'saved')
            assert not rows()['nvme0n1']['eligible']
            (deployment/'saved').rename(image)
            write(lines+[f'12 1 0:50 / {backing} rw - btrfs /dev/dm-1 rw'])
            assert not rows()['nvme0n1']['eligible']  # conflicting visible backing mounts
            write(lines)
            # The metadata image and data-only layers are independently mapped.
            other=f.root/'metadata';other.mkdir();moved=other/'.ostree.cfs';image.unlink();image.symlink_to(moved);moved.write_bytes(b'image')
            def moved_trust(path,*a,**kw):
                st=real_stat(path,*a,**kw)
                return SimpleNamespace(st_mode=st.st_mode,st_uid=0) if path==moved else st
            with patch.object(Path,'stat',moved_trust):
                write(lines+[f'12 1 0:50 / {other} rw - btrfs /dev/dm-1 rw'])
                assert rows()['nvme0n1']['system_drive'] is True
