"""Sealed VM only. Actual root stager, transient systemd and guarded data I/O."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import time
import re
from types import SimpleNamespace


def client_seal():
    token=json.loads(Path('/fixture.json').read_text())['token']
    if (not re.fullmatch('[0-9a-f]{12}',token) or
            'lvs_fixture='+token not in Path('/proc/cmdline').read_text().split() or
            'QEMU'not in Path('/sys/class/dmi/id/sys_vendor').read_text()or os.getuid()!=1000):
        raise RuntimeError('outside sealed disposable VM client')


def client(identity, death=False, concurrent=False):
    client_seal()
    from Modules.lvs_storage_thermal import ThermalConfig
    from Modules.lvs_storage_thermal_execution import execution_scope
    from Modules.lvs_run_launch import RunLaunchCoordinator,RunLaunchRequest
    from Modules.lvs_run_metadata import RunMetadata
    from scripts.storage_thermal_integrated_probe import primary
    c=ThermalConfig(access_mode='shared_readonly_opt_in',selection='individual',device_ids=[identity],rate_mode='advanced',iops=8,bandwidth_bytes_per_second=524288,aggregate_iops_limit=16,aggregate_bps_limit=1048576,temperature_limit_c=60)
    results={}
    cases=[('death',35,None)]if death else[('normal',35,None)]if concurrent else[('normal',35,None),('cancel',45,2)]
    for case,seconds,cancel in cases:
        contexts=[]
        def preparation(profile):
            setup=SimpleNamespace(profile=profile,profile_path=Path('/lvs/fixture.json'),metadata=RunMetadata(),heatsoak_minutes=0)
            RunLaunchCoordinator(SimpleNamespace()).prepare_execution(RunLaunchRequest.from_setup(setup),privilege_manager=SimpleNamespace(sudo_noninteractive_ready=lambda:True,start_keepalive=lambda:None),authorize=lambda:False)
            scope=execution_scope(profile);scope.__enter__();contexts.append(scope)
        dest=Path('/control/user')/case;dest.mkdir()
        try:r=primary(None,dict(c.to_dict(),duration_seconds=seconds),dest,seconds,cancel_after=cancel,death_control=(death or concurrent),prepare_execution=preparation)
        finally:
            for scope in reversed(contexts):scope.__exit__(None,None,None)
        results[case]=r
        if death:
            assert r['primary_verdict']=='pass' and r['auxiliary']['auxiliary_outcome']=='ERROR' and not r['auxiliary']['cleanup_confirmed'],r
            continue
        assert r['auxiliary']['cleanup_confirmed'] and r['auxiliary']['executed_devices']==[identity],r
        assert sum(d.get('read_ios',0)for d in r['auxiliary']['devices'])>0,r
        assert r['auxiliary']['auxiliary_outcome']=='STOPPED'if cancel else r['primary_verdict']=='pass'
    if concurrent:
        Path('/control/user/client.json').write_text(json.dumps(results,indent=2));return
    if death:
        Path('/control/user/death.json').write_text(json.dumps(results,indent=2));return
    from Modules.lvs_storage_thermal_runtime import preview,rpc
    from dataclasses import replace
    rows=rpc('inspect',configuration=c.to_dict())['devices'];root=next(r for r in rows if r['system_drive'])
    try:preview(replace(c,device_ids=[root['device_id']],system_device_ids=[root['device_id']],control_plane_colocation=True))
    except (OSError,ValueError):results['system_access_blocked']=True
    else:raise AssertionError('temporary system access accepted')
    Path('/control/user/phase1.json').write_text(json.dumps(results,indent=2))
    end=time.monotonic()+120
    while not Path('/control/user/restart-ready').exists():
        if time.monotonic()>end:raise RuntimeError('fixture restart timeout')
        time.sleep(.2)
    assert preview(c)['status']=='READY'
    results['same_frontend_restart_verified']=True
    Path('/control/user/client.json').write_text(json.dumps(results,indent=2))


def run(bundle,identity,proof_only=False,concurrent_only=False):
    from __main__ import seal
    seal()
    from Modules.lvs_storage_thermal_transient import ROOT_STAGER,digest,ENV,systemctl
    from Modules.lvs_storage_thermal_recovery import blocker,read_state
    # Ordinary pre-existing operator, not a Thermal Assist service account.
    Path('/etc/passwd').write_text('root:x:0:0:root:/root:/bin/sh\noperator:x:1000:1000:operator:/control/user:/bin/sh\n')
    Path('/etc/group').write_text('root:x:0:\noperator:x:1000:\n')
    # No permanent worker account is provisioned. Record exact static databases.
    before={p:Path(p).read_bytes()for p in ('/etc/passwd','/etc/group')}
    # Guest-only sensor: data I/O is genuine, temperatures are synthetic.
    launcher=bundle/'launch.py';text=launcher.read_text();needle='if integrated_serve or integrated_client:\n'
    injection='''if integrated_serve or integrated_client:
 from Modules.lvs_storage_thermal_service import RuntimePolicy
 original=RuntimePolicy.runner
 def fixture(self):
  runner=original(self);runner.temperature=lambda row:dict(value_c=30.,critical_c=70.,warning_c=55.,complete=True,synthetic_VM_sensor=True);return runner
 RuntimePolicy.runner=fixture
'''
    launcher.write_text(text.replace(needle,injection))
    m=json.loads((bundle/'manifest.json').read_text());m['files']['launch.py']=digest(launcher)
    (bundle/'manifest.json').write_text(json.dumps(m));approved=digest(bundle/'manifest.json')
    import shutil
    source_input=Path('/control/user-source');shutil.copytree(bundle,source_input)
    for item in (source_input,*source_input.rglob('*')):os.chown(item,1000,1000)
    def invoke(source=source_input,approval=approved):
        return subprocess.run(['/usr/bin/python3','-I','-B','-c',ROOT_STAGER,str(source),approval,'1000'],env=dict(ENV,SUDO_UID='1000'),capture_output=True,text=True,timeout=90,umask=0o077)
    def start():
        result=invoke()
        if result.returncode:raise RuntimeError(result.stderr[-5000:])
        return json.loads(result.stdout)
    import socket
    negatives={}
    bad=Path('/control/bad-source');shutil.copytree(source_input,bad)
    for item in (bad,*bad.rglob('*')):os.chown(item,1000,1000)
    bm=json.loads((bad/'manifest.json').read_text());bm['source']['digest']='0'*64
    entry=bad/'runtime/Modules/lvs_storage_thermal_transient.py';original_entry=entry.read_bytes()
    entry.write_bytes(b"raise RuntimeError('UNTRUSTED SNAPSHOT CODE EXECUTED')\n"+original_entry)
    bm['files']['runtime/Modules/lvs_storage_thermal_transient.py']=digest(entry)
    (bad/'manifest.json').write_text(json.dumps(bm));r=invoke(bad,digest(bad/'manifest.json'))
    assert r.returncode and 'before import'in r.stderr and 'UNTRUSTED SNAPSHOT CODE EXECUTED'not in r.stderr;negatives['source_mismatch_before_import']=True
    entry.write_bytes(original_entry)
    bm=json.loads((bundle/'manifest.json').read_text());bm['backend']['fio_version']='fio-0'
    (bad/'manifest.json').write_text(json.dumps(bm));r=invoke(bad,digest(bad/'manifest.json'))
    assert r.returncode and 'version evidence mismatch'in r.stderr;negatives['failed_initialization']=True
    marker=Path('/var/lib/lvs-thermal/storage_thermal_recovery_required.json')
    assert not marker.exists()
    record=marker.parent/'installation-1000.json';record.write_text('retained fixture installation record')
    r=invoke();assert r.returncode and record.read_text()=='retained fixture installation record'
    negatives['installation_record_preserved']=True;record.unlink()
    # Existing root-service ownership is a separate conflict, never stopped by
    # production startup. Only the fixture stops its own legacy stand-in.
    subprocess.run(['/usr/bin/systemd-run','--quiet','--collect','--unit=lvs-thermal-1000','--property=Type=exec','/usr/bin/python3','-I','-B',str(bundle/'launch.py'),'--serve-integrated'],check=True)
    legacy=systemctl('show','lvs-thermal-1000.service','--property=MainPID','--value')
    r=invoke();assert r.returncode and systemctl('show','lvs-thermal-1000.service','--property=MainPID','--value')==legacy
    negatives['legacy_service_untouched']=True;systemctl('stop','lvs-thermal-1000.service')
    endpoint=Path('/run/lvs-thermal/1000.sock');endpoint.parent.mkdir(exist_ok=True);endpoint.parent.chmod(0o755)
    stale=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);stale.bind(str(endpoint));stale.close();ino=endpoint.stat().st_ino
    r=invoke();assert r.returncode and endpoint.stat().st_ino==ino
    negatives['unknown_stale_endpoint_preserved']=True;endpoint.unlink()
    if proof_only:
        assert not marker.exists()and all(Path(p).read_bytes()==value for p,value in before.items())
        return dict(contract='lvs.storage_thermal.transient_proofs_vm.v1',source=m['source'],negative_controls=negatives,no_admission=True)
    first=start();root=Path(first['root']);manifest=json.loads((root/'manifest.json').read_text());unit=manifest['unit']
    out=dict(contract='lvs.storage_thermal.transient_vm.v1',source=m['source'],startup=first,negative_controls=negatives)
    Path('/control/user').mkdir(exist_ok=True);os.chown('/control/user',1000,1000)
    end=time.monotonic()+20
    while not Path('/run/lvs-thermal/1000.sock').exists():
        if time.monotonic()>end:
            raise RuntimeError(systemctl('status',unit,check=False))
        time.sleep(.1)
    command=['/usr/bin/python3','-B','/lvs/scripts/storage_thermal_transient_probe.py','--client',identity]
    if concurrent_only:
        Path('/control/user/kill-ready').unlink(missing_ok=True)
        log=Path('/control/concurrent-client.log').open('w')
        active=subprocess.Popen(command+['--concurrent'],user=1000,group=1000,extra_groups=(),stdout=log,stderr=log,env=dict(PATH='/usr/bin:/bin',PYTHONPATH='/lvs'))
        end=time.monotonic()+60
        while not Path('/control/user/kill-ready').exists()and active.poll()is None:
            if time.monotonic()>end:raise RuntimeError('no active worker for concurrency proof')
            time.sleep(.1)
        assert active.poll()is None,Path('/control/concurrent-client.log').read_text()[-5000:]
        main=systemctl('show',unit,'--property=MainPID','--value')
        contender=subprocess.run(['/usr/bin/python3','-B','/lvs/scripts/storage_thermal_transient_probe.py','--inspect',identity],user=1000,group=1000,extra_groups=(),capture_output=True,text=True,env=dict(PATH='/usr/bin:/bin',PYTHONPATH='/lvs'),timeout=30)
        assert contender.returncode==0,contender.stderr
        assert systemctl('show',unit,'--property=MainPID','--value')==main
        active.wait(timeout=90);log.close();assert active.returncode==0,Path('/control/concurrent-client.log').read_text()[-5000:]
        r=json.loads(Path('/control/user/client.json').read_text())['normal'];a=r['auxiliary']
        assert a['cleanup_confirmed']and len(a['devices'])==1
        for d in a['devices']:
            assert d['read_ios']>0 and d['guard_confirmed']and d['provenance_confirmed']
            assert all(d[k]==0 for k in ('write_ios','discard_ios','flush_ios','errors'))
        out['client']=r;out['concurrent_readiness_blocked']=True
        out['canonical_CLEAN']=read_state(marker)['state']=='CLEAN'and not blocker(marker)
        end=time.monotonic()+50
        while root.exists()and time.monotonic()<end:time.sleep(.2)
        assert not root.exists();assert all(Path(p).read_bytes()==value for p,value in before.items())
        out['idle_cleanup']=True;out['contract']='lvs.storage_thermal.transient_concurrency_vm.v1'
        return out
    stdout=Path('/control/client.stdout').open('w');stderr=Path('/control/client.stderr').open('w')
    process=subprocess.Popen(command,user=1000,group=1000,extra_groups=(),stdout=stdout,stderr=stderr,env=dict(PATH='/usr/bin:/bin',PYTHONPATH='/lvs'))
    def until(predicate,seconds=180):
        end=time.monotonic()+seconds
        while not predicate():
            if time.monotonic()>end:raise RuntimeError('fixture deadline: '+Path('/control/client.stderr').read_text()[-3000:])
            time.sleep(.2)
    until(lambda:Path('/control/user/phase1.json').exists()or process.poll()is not None)
    assert process.poll()is None,Path('/control/client.stderr').read_text()[-6000:]
    marker=Path('/var/lib/lvs-thermal/storage_thermal_recovery_required.json')
    out['canonical_CLEAN']=read_state(marker)['state']=='CLEAN'and not blocker(marker)
    out['dynamic_identity']=all(Path(p).read_bytes()==value for p,value in before.items()) and manifest['worker_uid']!=1000
    out['guarded_execution']=True
    until(lambda:not root.exists(),50);out['idle_cleanup']=True
    until(lambda:systemctl('is-active',manifest['identity_unit'],check=False)!='active',10)
    out['identity_released_after_cleanup']=True
    second=start();second_root=Path(second['root'])
    until(lambda:Path('/run/lvs-thermal/1000.sock').exists(),20)
    Path('/control/user/restart-ready').touch();process.wait(timeout=30)
    stdout.close();stderr.close()
    assert process.returncode==0,Path('/control/client.stderr').read_text()[-6000:]
    out['client']=json.loads(Path('/control/user/client.json').read_text())
    until(lambda:not second_root.exists(),50)
    out['no_permanent_unit']=not Path('/etc/systemd/system'/Path(unit)).exists()
    third=start();third_root=Path(third['root']);until(lambda:Path('/run/lvs-thermal/1000.sock').exists(),20)
    Path('/control/user/kill-ready').unlink(missing_ok=True)
    death_out=Path('/control/death.stdout').open('w');death_err=Path('/control/death.stderr').open('w')
    death=subprocess.Popen(command+['--death'],user=1000,group=1000,extra_groups=(),stdout=death_out,stderr=death_err,env=dict(PATH='/usr/bin:/bin',PYTHONPATH='/lvs'))
    until(lambda:Path('/control/user/kill-ready').exists()or death.poll()is not None,60)
    assert death.poll()is None,Path('/control/death.stderr').read_text()[-5000:]
    systemctl('kill',third['unit'],'--kill-whom=main','--signal=SIGKILL')
    death.wait(timeout=90);death_out.close();death_err.close()
    assert death.returncode==0,Path('/control/death.stderr').read_text()[-6000:]
    out['death']=json.loads(Path('/control/user/death.json').read_text())
    proof=subprocess.check_output(['/usr/bin/python3','-I','-B','-c',"import sys,json;from pathlib import Path;sys.path.insert(0,'/lvs');from Modules.lvs_storage_thermal_recovery import blocker,read_state;p=Path('/var/lib/lvs-thermal/storage_thermal_recovery_required.json');print(json.dumps(dict(state=read_state(p)['state'],blocker=blocker(p))))"],text=True)
    out['fresh_process_recovery']=json.loads(proof)
    assert out['fresh_process_recovery']['state']=='ARMED'and out['fresh_process_recovery']['blocker']
    out['uncertain_runtime_retained']=third_root.exists();assert out['uncertain_runtime_retained']
    third_manifest=json.loads((third_root/'manifest.json').read_text())
    out['uncertain_identity_retained']=systemctl('is-active',third_manifest['identity_unit'],check=False)=='active';assert out['uncertain_identity_retained']
    assert invoke().returncode
    out['restart_refuses_ARMED']=True
    assert all(Path(p).read_bytes()==value for p,value in before.items())
    return out


def contender(identity):
    client_seal()
    from Modules.lvs_profile_models import ValidationProfile,StageConfig,StageModules,ModuleStorageThermal,ModuleCpu
    from Modules.lvs_run_launch import RunLaunchCoordinator,RunLaunchRequest
    from Modules.lvs_run_metadata import RunMetadata
    module=ModuleStorageThermal(enabled=True,access_mode='shared_readonly_opt_in',selection='individual',device_ids=[identity],rate_mode='advanced',iops=8,bandwidth_bytes_per_second=524288,aggregate_iops_limit=16,aggregate_bps_limit=1048576,temperature_limit_c=60)
    p=ValidationProfile('contender',stages=[StageConfig('contender','CPU',12,modules=StageModules(cpu=ModuleCpu(enabled=True),storage_thermal=module))])
    setup=SimpleNamespace(profile=p,profile_path=Path('/lvs/fixture.json'),metadata=RunMetadata(),heatsoak_minutes=0)
    plans=RunLaunchCoordinator(SimpleNamespace()).prepare_execution(RunLaunchRequest.from_setup(setup),privilege_manager=SimpleNamespace(sudo_noninteractive_ready=lambda:True,start_keepalive=lambda:None),authorize=lambda:False)
    assert plans and all(r['status']=='BLOCKED'and not r.get('runnable_devices') for r in plans.values()),plans
    assert any('recovery'in str(r.get('reasons')).lower()or'ownership'in str(r.get('reasons')).lower()for r in plans.values()),plans
    assert p._thermal_execution_preparation.get('lease')is None


if __name__=='__main__':
    if len(sys.argv)in (3,4)and sys.argv[1]=='--client':client(sys.argv[2],len(sys.argv)==4 and sys.argv[3]=='--death',len(sys.argv)==4 and sys.argv[3]=='--concurrent')
    elif len(sys.argv)==3 and sys.argv[1]=='--inspect':contender(sys.argv[2])
    else:raise SystemExit('sealed VM entry only')
