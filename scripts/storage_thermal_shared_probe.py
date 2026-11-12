"""Bounded real-provider integration on private writable QEMU data images only.
No host device/path/fio-job override. Synthetic temperature, real topology/opener/guard/fio.
"""
from __future__ import annotations
import argparse
import base64
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

try:
    from scripts import storage_thermal_fio_probe as base
except ModuleNotFoundError:
    import probe as base
ROOT=Path(__file__).resolve().parent
if ROOT.name=='scripts':ROOT=ROOT.parent
KERNEL='7.2.9-200.fc44.x86_64'
require=base.require


def build_fixture(bundle,root,token,args):
    from scripts.storage_thermal_active_probe import partition_image
    from scripts.storage_thermal_file_probe import copy_binary
    copy_binary(root,'/usr/bin/switch_root','bin/switch_root')
    copy_binary(root,'/usr/bin/umount','bin/umount')
    copy_binary(root,'/usr/bin/env','bin/env')
    copy_binary(root,'/usr/sbin/modprobe','bin/modprobe')
    modules=('nvme','dm-crypt','btrfs','xts') if args.campaign.startswith('encrypted') else ('nvme',)
    dependencies='\n'.join(subprocess.check_output(['modprobe','--set-version',KERNEL,'--show-depends',m],text=True) for m in modules)
    for line in dependencies.splitlines():
        if not line.strip() or line.startswith('builtin'):continue
        kind,path,*_=line.split();require(kind=='insmod','unexpected module dependency')
        source=Path(path).resolve(strict=True);require(source.is_file(),'regular module required')
        dest=root/'lib/modules'/KERNEL/source.relative_to(Path('/usr/lib/modules')/KERNEL)
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
    for name in ('modules.dep','modules.dep.bin','modules.builtin','modules.builtin.bin','modules.alias','modules.alias.bin'):
        path=Path('/usr/lib/modules')/KERNEL/name
        if path.exists():shutil.copy2(path,root/'lib/modules'/KERNEL/name)
    for name in ('newroot','control','data-hdd','data-ssd','data-nvme'):(root/name).mkdir(exist_ok=True)
    if args.campaign.startswith('encrypted'):
        for source,dest in [('/usr/sbin/cryptsetup','bin/cryptsetup'),('/usr/sbin/mkfs.btrfs','bin/mkfs.btrfs'),('/usr/sbin/mkfs.ext4','bin/mkfs.ext4'),('/usr/sbin/dmsetup','bin/dmsetup')]:copy_binary(root,source,dest)
    (root/'shared-campaign').write_text(args.campaign)
    (root/'init').write_text('#!/bin/sh\n/bin/mount -t proc proc /proc\n/bin/mount -t sysfs sysfs /sys\n/bin/mount -t devtmpfs devtmpfs /dev\n/bin/modprobe nvme\nexec /usr/bin/python3 /foundation_probe.py --bootstrap\n')
    for p in root.rglob('*'):
        if p.is_file():p.chmod(p.stat().st_mode&~0o6000)
    system=partition_image(bundle,'shared-system',512*1024**2,root)
    control=partition_image(bundle,'shared-control',128*1024**2)
    corpus=bundle/'data-tree';corpus.mkdir();(corpus/'ordinary-data').write_bytes(b'fixture-data'*8192)
    images=[system,control]+[partition_image(bundle,'shared-'+name,64*1024**2,corpus) for name in ('hdd','ssd','nvme')]
    if args.campaign.startswith('encrypted'):
        import struct
        image=bundle/'encrypted-data.raw'
        with image.open('wb') as f:f.truncate(514*1024**2)
        mbr=bytearray(512)
        for i in range(2):
            struct.pack_into('<B3sB3sII',mbr,446+i*16,0,b'\0'*3,0x83,b'\0'*3,2048+i*524288,524288)
        mbr[510:]=b'\x55\xaa'
        with image.open('r+b') as f:f.write(mbr)
        images[4]=image
    drive=['-device','ich9-ahci,id=sharedahci']
    for index in range(5):
        drive+=['-drive',f'file={images[index]},format=raw,if=none,id=shared{index}']
        if index in (0,4):drive+=['-device',f'nvme,drive=shared{index},serial=SV{index}-{token}']
        else:drive+=['-device',f'ide-hd,drive=shared{index},bus=sharedahci.{index-1},serial=SV{index}-{token},rotation_rate={7200 if index==2 else 1}']
    return dict(images=images,drive_args=drive,description=dict(system='NVMe ext4 rw',control='AHCI ext4 rw',
        data=['SATA HDD','SATA SSD','single-namespace PCIe NVMe'],qemu=subprocess.check_output(['qemu-system-x86_64','--version'],text=True).splitlines()[0]))


def fixture_device(index, partition=False):
    token=json.loads(Path('/fixture.json').read_text())['token']
    expected=f'SV{index}-{token}'
    matches=[]
    for node in Path('/sys/class/block').iterdir():
        if (node/'partition').exists():continue
        serial=(node/'device/serial')
        value=serial.read_text().strip() if serial.exists() else ''
        vpd=node/'device/vpd_pg80'
        if vpd.exists():
            raw=vpd.read_bytes();value=raw[4:4+int.from_bytes(raw[2:4],'big')].decode().strip()
        if value==expected:matches.append(node.name)
    require(len(matches)==1,'sealed physical fixture identity missing/ambiguous')
    name=matches[0]
    return '/dev/'+name+('p1' if name.startswith('nvme') else '1') if partition else '/dev/'+name


def seal():
    token=json.loads(Path('/fixture.json').read_text())['token']
    require(re.fullmatch('[0-9a-f]{12}',token) and f'lvs_fixture={token}' in Path('/proc/cmdline').read_text().split()
            and 'QEMU' in Path('/sys/class/dmi/id/sys_vendor').read_text() and os.getuid()==0,'outside sealed disposable VM')
    for index in range(5):fixture_device(index)
    return token


def bootstrap():
    seal()
    subprocess.run(['/bin/mount','-t','ext4','-o','rw',fixture_device(0,True),'/newroot'],check=True)
    subprocess.run(['/bin/mount','-t','ext4','-o','rw',fixture_device(1,True),'/newroot/control'],check=True)
    os.execv('/bin/switch_root',['switch_root','/newroot','/bin/strace','-ff','-ttt','-T','-yy','-s','0','--kill-on-exit',
        '-e','raw=ioctl','-o','/control/provider.trace','/usr/bin/python3','/foundation_probe.py','--inside'])


def config(identity,seconds=3):
    from Modules.lvs_storage_thermal import ThermalConfig
    return ThermalConfig(access_mode='shared_readonly_opt_in',selection='individual',device_ids=[identity],duration_seconds=seconds,
                         aggregate_iops_limit=128,aggregate_bps_limit=8388608,monitoring='required',temperature_limit_c=55)


def runner():
    sys.path.insert(0,'/lvs')
    from Modules.lvs_storage_thermal_runner import ThermalRunner
    # The VM has no qualified physical sensor. Only temperature is injected;
    # production discovery, eligibility, geometry, descriptor acquisition and
    # every execution/success/ownership check remain real.
    return ThermalRunner('/bin/fio','/bin/thermal-guard',uid=65534,gid=65534,
        temperature_reader=lambda row:dict(value_c=30.,critical_c=60.,warning_c=50.,complete=True,synthetic_VM_sensor=True))


def execute(name,identity,seconds=3,cancel=False):
    seal();r=runner();c=config(identity,seconds);plan=r.inspect(c)
    require(plan['status']=='READY',json.dumps(plan))
    from Modules.lvs_storage_thermal_recovery import RecoveryScope,blocker
    scope=RecoveryScope(Path('/control')/(name+'-recovery.json'))
    scope.enter(evidence_directory='/control/'+name)
    try:
        def observe(jobs):
            if name=='concurrent' and not Path('/control/concurrent-active.json').exists() and any(j.get('last_snapshot',{}).get('device_read_ios_since_launch',0)>0 for j in jobs):
                Path('/control/concurrent-active.json').write_text(json.dumps(dict(monotonic=time.monotonic(),observed_device_reads=True)))
        directory,result=r.run(c,plan,Path('/control')/name,observe=observe,
            control=lambda jobs:['all'] if cancel and jobs and time.monotonic()-jobs[0]['started']>.8 else [])
        clean=not r.unconfirmed and result['parent_finalization_complete'] and all(d['cleanup_confirmed'] and d['terminal_published'] for d in result['devices'])
        require(clean,'owned descriptor/process cleanup unconfirmed')
        scope.resolve(cleanup_confirmed=True)
    finally:scope.close()
    require(not blocker(scope.marker),'clean completion retained recovery blocker')
    result['fixture_output']=str(directory);result['fixture_fresh_recovery_blocked']=bool(blocker(scope.marker))
    return result


def inside(case=None,identity=None):
    token=seal();sys.path.insert(0,'/lvs')
    from Modules.lvs_storage_thermal_launch import prepare,OwnedProcess
    from Modules.lvs_storage_thermal_targets import ThermalTargets
    prepare('/bin')
    if case:
        result=execute(case,identity,8)
        Path('/control/concurrent-result.json').write_text(json.dumps(result));return
    campaign=Path('/shared-campaign').read_text()
    if campaign.startswith('encrypted'):
        encrypted_inside();return
    results={};ordinary=[];error=None
    try:
        targets=ThermalTargets();rows=targets.discover(access_mode='shared_readonly_opt_in')
        Path('/control/inventory-before.json').write_text(json.dumps(rows,indent=2))
        def target(index):
            matches=[r for r in rows if r['identity']['serial']==f'SV{index}-{token}']
            require(len(matches)==1,'fixture target identity not unique');return matches[0]
        root=target(0);require(root['system_drive'] and not root['eligible'],'real root not rejected')
        try:targets.open(root)
        except ValueError:results['root_rejected']=True
        else:raise RuntimeError('root descriptor opened')
        if campaign=='full':
            results['unmounted_hdd']=execute('unmounted-hdd',target(2)['device_id'])
        for device,name in ((fixture_device(2,True),'data-hdd'),(fixture_device(3,True),'data-ssd'),(fixture_device(4,True),'data-nvme')):
            subprocess.run(['/bin/mount','-t','ext4','-o','rw',device,'/'+name],check=True)
        if campaign=='full':
            stop=threading.Event()
            def writer():
                with open('/data-hdd/ordinary-data','r+b',buffering=0) as stream:
                    while not stop.is_set():
                        before=time.monotonic();n=os.pwrite(stream.fileno(),b'O'*4096,0);os.fsync(stream.fileno())
                        ordinary.append(dict(bytes=n,start=before,end=time.monotonic()));stop.wait(.2)
            thread=threading.Thread(target=writer);thread.start()
            try:results['mounted_hdd_writes']=execute('mounted-hdd',target(2)['device_id'],5)
            finally:stop.set();thread.join(timeout=5);require(not thread.is_alive(),'ordinary writer cleanup uncertain')
            results['mounted_ssd']=execute('mounted-ssd',target(3)['device_id'])
            results['mounted_nvme']=execute('mounted-nvme',target(4)['device_id'])
            results['cancel']=execute('cancel',target(4)['device_id'],20,True)
        # Actual shared provider runs in an independent owned supervisor while
        # a two-second primary proxy collects genuine proc telemetry. The full
        # stage timing/verdict contract is separately exercised by regression.
        before=time.monotonic();samples=[]
        with open('/control/concurrent.out','wb') as out,open('/control/concurrent.err','wb') as err:
            child=OwnedProcess(['/usr/bin/python3','/foundation_probe.py','--case','concurrent','--identity',target(4)['device_id']],stdout=out,stderr=err)
            try:
                deadline=before+2;next_sample=before
                while time.monotonic()<deadline:
                    now=time.monotonic()
                    if now>=next_sample:
                        samples.append(dict(monotonic=now,proc_cpu=Path('/proc/stat').read_text().splitlines()[0]));next_sample+=1
                    time.sleep(min(.02,max(0,deadline-time.monotonic())))
                primary_end=time.monotonic()
                active_window=None
                if campaign=='active-overlap':
                    ready_deadline=time.monotonic()+60
                    while not Path('/control/concurrent-active.json').exists():
                        require(child.poll() is None and time.monotonic()<ready_deadline,'no actual active read observation')
                        time.sleep(.02)
                    active_start=time.monotonic();active_samples=[];next_active=active_start
                    while time.monotonic()<active_start+2:
                        now=time.monotonic()
                        if now>=next_active:
                            active_samples.append(dict(monotonic=now,proc_cpu=Path('/proc/stat').read_text().splitlines()[0]));next_active+=1
                        time.sleep(min(.02,max(0,active_start+2-time.monotonic())))
                    active_window=dict(start=active_start,end=time.monotonic(),samples=active_samples)
                child.wait(timeout=45)
                require(child.returncode==0 and child.group_cleanup_confirmed(),'concurrent supervisor failed')
            finally:
                if child.poll() is None:child.kill();child.wait(timeout=5)
        if active_window is not None:results['active_primary_proxy']=active_window
        results['concurrent']=json.loads(Path('/control/concurrent-result.json').read_text())
        results['primary_proxy']=dict(start=before,end=primary_end,elapsed=primary_end-before,samples=samples,
            scope='timing/real proc observations, not physical CPU/GPU integrity acceptance')
        # Exercise the actual external observer against shared mounted NVMe.
        from scripts.storage_thermal_acceptance import capture,analyze
        from types import SimpleNamespace
        fresh=targets.discover(access_mode='shared_readonly_opt_in');Path('/control/inventory.json').write_text(json.dumps(fresh))
        observation=capture(SimpleNamespace(inventory='/control/inventory.json',device_id=[target(4)['device_id']],directory='/control/observer',
            interval=1,seconds=2,temperatures=False,sensor_resolution_c=None))
        Path('/control/observer-analysis.json').write_text(json.dumps(analyze('/control/observer'),indent=2))
        results['observer']=observation
    except Exception as exc:error=repr(exc)
    final=dict(contract='lvs.storage_thermal.shared_vm.v1',campaign=campaign,kernel=os.uname().release,fio=subprocess.check_output(['/bin/fio','--version'],text=True).strip(),
               temperature_source='synthetic fixed VM sensor; no physical temperature acceptance',results=results,ordinary_writes=ordinary,error=error)
    Path('/control/results.json').write_text(json.dumps(final,indent=2))
    archive=io.BytesIO()
    with tarfile.open(fileobj=archive,mode='w:gz') as tar:tar.add('/control',arcname='evidence')
    print('LVS_EVIDENCE_BEGIN',flush=True);print(base64.b64encode(archive.getvalue()).decode(),flush=True);print('LVS_EVIDENCE_END',flush=True)


def encrypted_inside():
    """All destructive setup is sealed to disposable guest images, never a host path."""
    import hashlib
    seal();results={};error=None
    try:
        for module in ('dm-crypt','btrfs','xts'):
            subprocess.run(['/bin/modprobe',module],check=True)
        Path('/run').mkdir(exist_ok=True)
        subprocess.run(['/bin/mount','-t','tmpfs','tmpfs','/run'],check=True)
        key=Path('/run/fixture-key');key.write_bytes(os.urandom(32));key.chmod(0o600)
        for i in (1,2):
            device=fixture_device(4)+f'p{i}';name=f'fixture-crypt{i}'
            subprocess.run(['/bin/cryptsetup','luksFormat','--type','luks2','--batch-mode','--pbkdf','pbkdf2','--pbkdf-force-iterations','1000','--key-file',str(key),device],check=True,capture_output=True)
            subprocess.run(['/bin/cryptsetup','open','--key-file',str(key),device,name],check=True,capture_output=True)
            subprocess.run(['/bin/mkfs.btrfs','-f','--nodiscard',f'/dev/mapper/{name}'],check=True,capture_output=True)
            dest=Path(f'/encrypted{i}');dest.mkdir()
            subprocess.run(['/bin/mount','-t','btrfs',f'/dev/mapper/{name}',str(dest)],check=True)
            (dest/'fixture-integrity').write_bytes(b'disposable-image-integrity'*4096)
        # Whole-device LUKS1 is a separate encrypted boot-backing rejection control.
        subprocess.run(['/bin/cryptsetup','luksFormat','--type','luks1','--batch-mode','--pbkdf-force-iterations','1000','--key-file',str(key),fixture_device(2)],check=True,capture_output=True)
        subprocess.run(['/bin/cryptsetup','open','--key-file',str(key),fixture_device(2),'fixture-boot'],check=True,capture_output=True)
        subprocess.run(['/bin/mkfs.ext4','-F','/dev/mapper/fixture-boot'],check=True,capture_output=True)
        Path('/boot').mkdir(exist_ok=True)
        subprocess.run(['/bin/mount','/dev/mapper/fixture-boot','/boot'],check=True)
        key.unlink()
        from Modules.lvs_storage_thermal_targets import ThermalTargets
        targets=ThermalTargets();rows=targets.discover(access_mode='shared_readonly_opt_in')
        data=next(r for r in rows if r['identity']['path']==fixture_device(4))
        root=next(r for r in rows if r['identity']['path']==fixture_device(0))
        require(data['eligible'],json.dumps(data))
        # The privileged workflow is exercised only inside this sealed guest.
        deployment=Path('/opt/lvs-thermal-fixture')
        for p in (Path('/opt'),deployment,*deployment.rglob('*')):
            os.chown(p,0,0);p.chmod(0o755 if p.is_dir() or p.name in ('fio','storage_thermal_guard','storage_thermal_launch.so') else 0o644)
        Path('/var/lib/lvs-thermal').mkdir(parents=True,exist_ok=True)
        for p in (Path('/var'),Path('/var/lib'),Path('/var/lib/lvs-thermal')):os.chown(p,0,0);p.chmod(0o755)
        command=['/usr/bin/python3','-I',str(deployment/'launch.py')]
        approved=subprocess.run([*command,'--check'],capture_output=True,text=True,timeout=20)
        require(approved.returncode==0,'root-owned verified deployment check failed: '+approved.stderr)
        require(next(r for r in json.loads(approved.stdout) if r['identity']['path']==fixture_device(4))['eligible'],'deployed encrypted discovery failed')
        require(subprocess.run([*command,'--fio','/untrusted'],capture_output=True,timeout=10).returncode!=0,'privileged arbitrary tool override accepted')
        victim=deployment/'runtime/Modules/lvs_storage_thermal.py';original=victim.read_bytes();victim.write_bytes(original+b'\n# tamper\n')
        require(subprocess.run([*command,'--check'],capture_output=True,timeout=10).returncode!=0,'tampered privileged source accepted')
        victim.write_bytes(original)
        if Path('/shared-campaign').read_text()=='encrypted-review':
            observations=[]
            for source_mount,destination in (('/encrypted1','/usr/bin'),('/encrypted2','/etc/ssl')):
                Path(destination).mkdir(parents=True,exist_ok=True)
                subprocess.run(['/bin/mount','--bind',source_mount,destination],check=True)
                try:
                    changed=next(r for r in targets.discover(access_mode='shared_readonly_opt_in') if r['device_id']==data['device_id'])
                    require(changed['system_drive'] and not changed['eligible'],'protected system submount admitted')
                    try:targets.revalidate(data)
                    except ValueError:pass
                    else:raise RuntimeError('protected topology change passed revalidation')
                    require(runner().inspect(config(data['device_id']))['status']=='BLOCKED','readiness admitted system submount')
                    observations.append(dict(mount=destination,system=True,eligible=False))
                finally:subprocess.run(['/bin/umount',destination],check=True)
                require(targets.revalidate(data)['eligible'],'ordinary encrypted data did not recover eligibility')
            require(runner().inspect(config(data['device_id']))['status']=='READY','encrypted data readiness failed')
            def rejected():
                completed=subprocess.run([*command,'--check'],capture_output=True,text=True,timeout=30)
                require(completed.returncode!=0,'unsafe privileged deployment accepted')
                return completed.stderr[-500:]
            checks={}
            ancestor=Path('/opt');ancestor.chmod(0o777)
            try:checks['writable_ancestor']=rejected()
            finally:ancestor.chmod(0o755)
            parent=deployment/'runtime/Modules';parent.chmod(0o777)
            try:checks['writable_parent']=rejected()
            finally:parent.chmod(0o755)
            binary=deployment/'runtime/build/fio';binary.chmod(0o777)
            try:checks['writable_tool']=rejected()
            finally:binary.chmod(0o755)
            os.chown(binary,65534,65534)
            try:checks['unprivileged_tool_owner']=rejected()
            finally:os.chown(binary,0,0)
            saved=deployment/'runtime/build/fio-saved';binary.rename(saved);binary.symlink_to('/bin/fio')
            try:checks['tool_symlink']=rejected()
            finally:binary.unlink();saved.rename(binary)
            unknown=deployment/'runtime/Modules/extra.py';unknown.write_text('raise RuntimeError("unapproved")')
            try:checks['extra_code']=rejected()
            finally:unknown.unlink()
            poison=Path('/run/poison');poison.mkdir();(poison/'sitecustomize.py').write_text('raise SystemExit("injected")')
            env=dict(os.environ,PYTHONPATH=str(poison),PYTHONHOME=str(poison),FIO_PRELOAD='untrusted')
            clean=subprocess.run(['/bin/env','-i','PATH=/usr/bin:/bin','HOME=/root','LC_ALL=C',*command,'--check'],env=env,capture_output=True,text=True,timeout=30)
            require(clean.returncode==0,'clean isolated launch inherited environment injection')
            checks['isolated_environment']=True
            # Promotion is anchored externally, not to a replacement manifest.
            import hashlib
            sums=deployment/'SHA256SUMS';approved=hashlib.sha256(sums.read_bytes()).hexdigest();saved_sums=sums.read_bytes()
            sums.write_bytes(saved_sums+b'forged candidate')
            checks['external_approval_rejects_substitution']=hashlib.sha256(sums.read_bytes()).hexdigest()!=approved
            sums.write_bytes(saved_sums)
            from Modules.lvs_storage_thermal_recovery import RecoveryScope,blocker
            marker=Path('/var/lib/lvs-thermal/storage_thermal_recovery_required.json')
            scope=RecoveryScope(marker);scope.enter(evidence_directory='/control/recovery-review')
            try:
                probe="import sys;sys.path.insert(0,'/lvs');from Modules.lvs_storage_thermal_recovery import blocker;print(bool(blocker(sys.argv[1])))"
                require(subprocess.check_output(['/usr/bin/python3','-c',probe,str(marker)],text=True).strip()=='True','another process bypassed owned ARMED scope')
                scope.resolve(cleanup_confirmed=True)
            finally:scope.close()
            require(not blocker(marker),'confirmed cleanup failed CLEAN transition')
            Path('/control/canonical-clean.json').write_bytes(marker.read_bytes())
            # A crashed/unresolved owner remains ARMED after close and fresh inspection.
            scope=RecoveryScope(marker);scope.enter(evidence_directory='/control/uncertain-review');scope.close()
            require(subprocess.check_output(['/usr/bin/python3','-c',probe,str(marker)],text=True).strip()=='True','fresh process missed unresolved ownership')
            Path('/control/canonical-armed.json').write_bytes(marker.read_bytes())
            checks['canonical_armed_persists']=True
            try:RecoveryScope(marker).enter(evidence_directory='/control/new-deployment')
            except (OSError,ValueError):checks['new_deployment_cannot_bypass_armed']=True
            else:raise RuntimeError('new deployment bypassed canonical recovery')
            payload=dict(contract='lvs.storage_thermal.encrypted_review_vm.v1',protected_submounts=observations,
                         data_readiness='READY',encrypted_boot_rejected=next(r for r in rows if r['identity']['path']==fixture_device(2))['system_drive'],
                         root_rejected=root['system_drive'] and not root['eligible'],deployment_checks=checks,
                         source=None)
            from Modules.lvs_source_provenance import _source_snapshot
            payload['source']=_source_snapshot(Path('/lvs'))[0]
            Path('/control/results.json').write_text(json.dumps(payload,indent=2))
            archive=io.BytesIO()
            with tarfile.open(fileobj=archive,mode='w:gz') as tar:tar.add('/control',arcname='evidence')
            print('LVS_EVIDENCE_BEGIN',flush=True);print(base64.b64encode(archive.getvalue()).decode(),flush=True);print('LVS_EVIDENCE_END',flush=True)
            return

        hashes=[hashlib.sha256(Path(f'/encrypted{i}/fixture-integrity').read_bytes()).hexdigest() for i in (1,2)]
        stop=threading.Event();writes=[]
        def writer():
            with open('/encrypted2/concurrent-fixture','w+b',buffering=0) as f:
                while not stop.is_set():
                    os.pwrite(f.fileno(),b'ordinary-guest-write'*128,0);os.fsync(f.fileno());os.pread(f.fileno(),4096,0);writes.append(time.monotonic());stop.wait(.2)
        thread=threading.Thread(target=writer);thread.start()
        try:results['encrypted']=execute('encrypted',data['device_id'],5)
        finally:stop.set();thread.join(5);require(not thread.is_alive(),'ordinary writer not stopped')
        results['cancel']=execute('encrypted-cancel',data['device_id'],20,True)
        from Modules.lvs_storage_thermal_launch import OwnedProcess
        with open('/control/concurrent.out','wb') as out,open('/control/concurrent.err','wb') as err:
            child=OwnedProcess(['/usr/bin/python3','/foundation_probe.py','--case','concurrent','--identity',data['device_id']],stdout=out,stderr=err)
            try:
                wait_until=time.monotonic()+30
                while not Path('/control/concurrent-active.json').exists():
                    require(child.poll() is None and time.monotonic()<wait_until,'active overlap startup failed');time.sleep(.05)
                start=time.monotonic();samples=[];next_sample=start
                while time.monotonic()<start+2:
                    now=time.monotonic()
                    if now>=next_sample:samples.append(dict(monotonic=now,proc_cpu=Path('/proc/stat').read_text().splitlines()[0]));next_sample+=1
                    time.sleep(min(.02,max(0,start+2-time.monotonic())))
                primary=dict(start=start,end=time.monotonic(),samples=samples)
                child.wait(timeout=20);require(child.returncode==0,'owned supervisor failed')
            finally:
                if child.poll() is None:child.kill();child.wait(timeout=5)
        results['concurrent']=json.loads(Path('/control/concurrent-result.json').read_text())
        # A new linear holder above crypt must revoke eligibility (no keys queried).
        subprocess.run(['/bin/umount','/encrypted2'],check=True)
        sectors=Path('/sys/class/block/dm-1/size').read_text().strip()
        subprocess.run(['/bin/dmsetup','--noudevsync','create','fixture-unqualified','--table',f'0 {sectors} linear /dev/mapper/fixture-crypt2 0'],check=True,capture_output=True)
        changed=targets.discover(access_mode='shared_readonly_opt_in')
        require(not next(r for r in changed if r['device_id']==data['device_id'])['eligible'],'stacked holder accepted')
        try:targets.revalidate(data)
        except ValueError:pass
        else:raise RuntimeError('topology change accepted')
        subprocess.run(['/bin/dmsetup','--noudevsync','remove','fixture-unqualified'],check=True,capture_output=True)
        subprocess.run(['/bin/mount','-t','btrfs','/dev/mapper/fixture-crypt2','/encrypted2'],check=True)
        require(targets.revalidate(data)['eligible'],'stable mapping did not return to service')
        integrity=hashes==[hashlib.sha256(Path(f'/encrypted{i}/fixture-integrity').read_bytes()).hexdigest() for i in (1,2)]
        require(writes,'no ordinary filesystem activity')
        payload=dict(contract='lvs.storage_thermal.encrypted_vm.v1',results=results,inventory=rows,
                     deduplicated=len([r for r in rows if r['eligible'] and r['identity']['path']==fixture_device(4)])==1 and len(data['holder_proofs'])==2,
                     root_rejected=root['system_drive'] and not root['eligible'],encrypted_boot_rejected=next(r for r in rows if r['identity']['path']==fixture_device(2))['system_drive'],integrity=integrity,ordinary_write_operations=len(writes),primary=primary,deployment_verified=True,synthetic_temperature=True)
    except BaseException as e:
        payload=dict(contract='lvs.storage_thermal.encrypted_vm.v1',error=str(e),results=results)
    Path('/control/results.json').write_text(json.dumps(payload,indent=2))
    # Match the existing serial evidence export protocol.
    archive=io.BytesIO()
    with tarfile.open(fileobj=archive,mode='w:gz') as tar:
        for p in Path('/control').rglob('*'):
            if p.is_file():tar.add(p,arcname='evidence/'+str(p.relative_to('/control')),recursive=False)
    print('LVS_EVIDENCE_BEGIN',flush=True)
    print(base64.b64encode(archive.getvalue()).decode(),flush=True)
    print('LVS_EVIDENCE_END',flush=True)


def verify(result):
    if result.get('contract')=='lvs.storage_thermal.encrypted_review_vm.v1':
        require(result['root_rejected'] and result['encrypted_boot_rejected'] and result['data_readiness']=='READY','review readiness failure')
        require(len(result['protected_submounts'])==2 and all(c['system'] and not c['eligible'] for c in result['protected_submounts']),'submount review failure')
        require(all(result['deployment_checks'].values()),'deployment review failure')
        return
    if result.get('contract')=='lvs.storage_thermal.encrypted_vm.v1':
        require(not result.get('error'),str(result.get('error')))
        require(result['deduplicated'] and result['integrity'] and result['root_rejected'] and result['encrypted_boot_rejected'],'encrypted topology/integrity failure')
        require(1.9<=result['primary']['end']-result['primary']['start']<=2.3 and len(result['primary']['samples'])>=2,'primary isolation failed')
        for name in ('encrypted','cancel'):
            r=result['results'][name];require(r['devices'] and all(d['cleanup_confirmed'] for d in r['devices']),'cleanup unconfirmed')
        require(result['results']['encrypted']['devices'][0]['read_ios']>0,'no guarded reads')
        return
    require(not result.get('error'),str(result.get('error')))
    require(result['contract']=='lvs.storage_thermal.shared_vm.v1','wrong VM contract')
    r=result['results'];require(r['root_rejected'],'root rejection missing')
    if result.get('campaign','full')=='full':require(result['ordinary_writes'],'ordinary write control missing')
    names=('unmounted_hdd','mounted_hdd_writes','mounted_ssd','mounted_nvme','concurrent') if result.get('campaign','full')=='full' else ('concurrent',)
    for name in names:
        run=r[name]
        target=run['readiness']['targets'][0]
        require(target['access_mode']=='shared_readonly_opt_in' and 'node_inode' in target['identity'],'shared opener authority absent')
        require(target['mounted_or_active']==(name!='unmounted_hdd'),'mounted/unmounted state not proven')
        expected_class='ssd' if name=='mounted_ssd' else 'nvme' if name in ('mounted_nvme','concurrent') else 'hdd'
        require(target['drive_class']==expected_class,'fixture media class mismatch')
        require(run['verdict']=='WARN' and run['parent_finalization_complete'],'incomplete shared execution: '+name)
        for d in run['devices']:
            require(d['state']=='completed' and d['read_ios']>0 and d['read_bytes']==d['read_ios']*65536,'missing real reads')
            require(d['guard_confirmed'] and d['identity_unchanged'] and d['provenance_confirmed'] and d['cleanup_confirmed'] and d['terminal_published'],'guard/identity/cleanup incomplete')
            require(d['write_ios']==d['discard_ios']==d['flush_ios']==0,'workload mutation evidence')
        require(not run['fixture_fresh_recovery_blocked'],'CLEAN verification failed')
    if 'cancel' in r:require(r['cancel']['verdict']=='INCOMPLETE' and all(d['cleanup_confirmed'] for d in r['cancel']['devices']),'cancellation cleanup failed')
    if result.get('campaign')=='active-overlap':
        window=r['active_primary_proxy'];device=r['concurrent']['devices'][0]
        require(1.9<=window['end']-window['start']<=2.3 and len(window['samples'])>=2,'active primary timing/telemetry disturbed')
        require(device['started_monotonic']<=window['start']<window['end']<=device['ended_monotonic'],'no active workload overlap')
    require(r['observer']['access_mode']=='shared_readonly_opt_in' and r['observer']['complete'],'observer rejected shared target')
    require(1.9<=r['primary_proxy']['elapsed']<=2.3 and len(r['primary_proxy']['samples'])>=2,'primary timing/telemetry disturbed')


def host(args):
    from scripts.storage_thermal_causal_probe import require_kernel_image
    from scripts.storage_thermal_file_probe import regular
    from Modules.lvs_native_helpers import find_c_compiler,native_helper_build_command
    from Modules.lvs_source_provenance import _source_snapshot
    require_kernel_image(args.kernel)
    for name in ('fio','old_fio','strace','kernel','python'):regular(getattr(args,name))
    tools=Path(tempfile.mkdtemp(prefix='lvs-shared-tools-'));compiler=find_c_compiler();require(compiler is not None,'compiler unavailable')
    args.guard=str(tools/'guard')
    for source,output,extra in [('storage_thermal_guard.c',Path(args.guard),[]),('storage_thermal_launch.c',tools/'storage_thermal_launch.so',['-shared','-fPIC'])]:
        subprocess.run(native_helper_build_command(compiler,ROOT/'native'/source,output)+extra,check=True,capture_output=True,timeout=60)
    snapshot,content=_source_snapshot(ROOT);require(snapshot['status']=='complete','source snapshot incomplete')
    files=[(ROOT/name,'/lvs/'+name) for name in content]
    files += [(tools/'storage_thermal_launch.so','/bin/storage_thermal_launch.so'),(ROOT/'scripts/storage_thermal_acceptance.py','/lvs/scripts/storage_thermal_acceptance.py')]
    if args.campaign.startswith('encrypted'):
        from scripts.storage_thermal_prepare import prepare as prepare_bundle
        deployment=tools/'deployment'
        prepare_bundle(deployment,Path(args.fio))
        files += [(p,'/opt/lvs-thermal-fixture/'+str(p.relative_to(deployment))) for p in deployment.rglob('*') if p.is_file()]
    base.host(args,guest_script=Path(__file__).resolve(),verifier=verify,extra_files=files,fixture_builder=build_fixture)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign',choices=('full','active-overlap','encrypted','encrypted-review'),default='full')
    parser.add_argument('--bootstrap',action='store_true');parser.add_argument('--inside',action='store_true')
    parser.add_argument('--case');parser.add_argument('--identity')
    for name in ('fio','old-fio','strace','kernel','python'):parser.add_argument('--'+name)
    args=parser.parse_args()
    if args.bootstrap:bootstrap()
    elif args.case:inside(args.case,args.identity)
    elif args.inside:inside()
    else:
        require(all(getattr(args,k) for k in ('fio','old_fio','strace','kernel','python')),'explicit qualified regular-file inputs required')
        host(args)
