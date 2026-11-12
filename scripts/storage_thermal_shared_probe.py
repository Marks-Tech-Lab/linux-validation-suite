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
    copy_binary(root,'/usr/sbin/modprobe','bin/modprobe')
    dependencies=subprocess.check_output(['modprobe','--set-version',KERNEL,'--show-depends','nvme'],text=True)
    for line in dependencies.splitlines():
        kind,path,*_=line.split();require(kind=='insmod','unexpected NVMe module dependency')
        source=Path(path).resolve(strict=True);require(source.is_file(),'regular module required')
        dest=root/'lib/modules'/KERNEL/source.relative_to(Path('/usr/lib/modules')/KERNEL)
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
    for name in ('modules.dep','modules.dep.bin','modules.builtin','modules.builtin.bin','modules.alias','modules.alias.bin'):
        path=Path('/usr/lib/modules')/KERNEL/name
        if path.exists():shutil.copy2(path,root/'lib/modules'/KERNEL/name)
    for name in ('newroot','control','data-hdd','data-ssd','data-nvme'):(root/name).mkdir(exist_ok=True)
    (root/'shared-campaign').write_text(args.campaign)
    (root/'init').write_text('#!/bin/sh\n/bin/mount -t proc proc /proc\n/bin/mount -t sysfs sysfs /sys\n/bin/mount -t devtmpfs devtmpfs /dev\n/bin/modprobe nvme\nexec /usr/bin/python3 /foundation_probe.py --bootstrap\n')
    for p in root.rglob('*'):
        if p.is_file():p.chmod(p.stat().st_mode&~0o6000)
    system=partition_image(bundle,'shared-system',512*1024**2,root)
    control=partition_image(bundle,'shared-control',128*1024**2)
    corpus=bundle/'data-tree';corpus.mkdir();(corpus/'ordinary-data').write_bytes(b'fixture-data'*8192)
    images=[system,control]+[partition_image(bundle,'shared-'+name,64*1024**2,corpus) for name in ('hdd','ssd','nvme')]
    drive=['-device','ich9-ahci,id=sharedahci']
    for index in range(5):
        drive+=['-drive',f'file={images[index]},format=raw,if=none,id=shared{index}']
        if index in (0,4):drive+=['-device',f'nvme,drive=shared{index},serial=SV{index}-{token}']
        else:drive+=['-device',f'ide-hd,drive=shared{index},bus=sharedahci.{index-1},serial=SV{index}-{token},rotation_rate={7200 if index==2 else 1}']
    return dict(images=images,drive_args=drive,description=dict(system='NVMe ext4 rw',control='AHCI ext4 rw',
        data=['SATA HDD','SATA SSD','single-namespace PCIe NVMe'],qemu=subprocess.check_output(['qemu-system-x86_64','--version'],text=True).splitlines()[0]))


def seal():
    token=json.loads(Path('/fixture.json').read_text())['token']
    require(re.fullmatch('[0-9a-f]{12}',token) and f'lvs_fixture={token}' in Path('/proc/cmdline').read_text().split()
            and 'QEMU' in Path('/sys/class/dmi/id/sys_vendor').read_text() and os.getuid()==0,'outside sealed disposable VM')
    require(Path('/sys/class/nvme/nvme0/serial').read_text().strip()=='SV0-'+token,'wrong system fixture')
    require(Path('/sys/class/nvme/nvme1/serial').read_text().strip()=='SV4-'+token,'wrong NVMe data fixture')
    for index,name in ((1,'sda'),(2,'sdb'),(3,'sdc')):
        value=Path(f'/sys/class/block/{name}/device/vpd_pg80').read_bytes()
        require(value[4:4+int.from_bytes(value[2:4],'big')].decode().strip()==f'SV{index}-{token}','wrong AHCI fixture')
    return token


def bootstrap():
    seal()
    subprocess.run(['/bin/mount','-t','ext4','-o','rw','/dev/nvme0n1p1','/newroot'],check=True)
    subprocess.run(['/bin/mount','-t','ext4','-o','rw','/dev/sda1','/newroot/control'],check=True)
    os.execv('/bin/switch_root',['switch_root','/newroot','/bin/strace','-ff','-ttt','-T','-yy','-s','0','--kill-on-exit',
        '-o','/control/provider.trace','/usr/bin/python3','/foundation_probe.py','--inside'])


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
        for device,name in (('/dev/sdb1','data-hdd'),('/dev/sdc1','data-ssd'),('/dev/nvme1n1p1','data-nvme')):
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


def verify(result):
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
    base.host(args,guest_script=Path(__file__).resolve(),verifier=verify,extra_files=files,fixture_builder=build_fixture)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign',choices=('full','active-overlap'),default='full')
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
