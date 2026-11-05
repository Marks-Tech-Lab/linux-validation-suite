"""Synthetic-VM end-to-end standalone-runner proof. NO host block-device input.

Uses sealed QEMU serial/token identity before allowing the virtual fixture to
stand in for a physical HDD. This test-only resolver is never exposed by the
production entrypoint. Full production guard and descriptor opener are used.
"""
import argparse
import base64
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time

try:import storage_thermal_fio_probe as base
except ModuleNotFoundError:
    try:from scripts import storage_thermal_fio_probe as base
    except ModuleNotFoundError:import probe as base


def verify(result):
    base.require(result['contract_id']=='lvs.storage_thermal.runner_fixture.v1','wrong fixture evidence')
    for name in ('normal','retry'):
        r=result['runs'][name]
        base.require(r['verdict']=='WARN' and r['parent_finalization_complete'],'normal unmonitored run failed')
        base.require(r['devices'][0]['cleanup_confirmed'] and r['devices'][0]['guard_confirmed'],'guard/cleanup missing')
        base.require(r['devices'][0]['read_ios']>0 and r['devices'][0]['write_ios']==0,'read-only activity missing')
    base.require(result['runs']['cancel']['verdict']=='INCOMPLETE','cancellation became PASS')
    base.require(result['runs']['cancel']['devices'][0]['cleanup_confirmed'],'cancel cleanup unconfirmed')


def inside():
    sys.path.insert(0,'/lvs')
    from Modules.lvs_storage_thermal import ThermalConfig
    from Modules.lvs_storage_thermal_targets import ThermalTargets
    from Modules.lvs_storage_thermal_runner import ThermalRunner,approve_unmonitored
    from Modules.lvs_profile_report_artifacts import atomic_preflight_json
    token=json.loads(Path('/fixture.json').read_text())['token']
    def seal():
        base.validate_fixture(token,Path('/proc/cmdline').read_text(),Path('/sys/class/dmi/id/sys_vendor').read_text(),
                              Path('/sys/block/vda/serial').read_text().strip(),int(Path('/sys/block/vda/size').read_text())*512,os.getuid())
    seal()
    class FixtureTargets(ThermalTargets):
        def discover(self):
            seal()
            major,minor=map(int,Path('/sys/block/vda/dev').read_text().split(':'))
            identity=dict(device_id='fixture:'+token,name='vda',path='/dev/vda',sysfs=str(Path('/sys/class/block/vda').resolve()),
                          major=major,minor=minor,size_bytes=base.SIZE,logical_sector=512,serial='LVS-'+token,wwn='')
            return [dict(device_id=identity['device_id'],identity=identity,model='QEMU disposable fixture ONLY',transport='fixture',
                         drive_class='hdd',internal=True,excluded_automatic=False,system_drive=False,
                         eligible=True,reasons=[],sensors=[])]
    runner=ThermalRunner('/bin/fio','/bin/thermal-guard',targets=FixtureTargets(),uid=65534,gid=65534)
    results={};counts={}
    def publish(path,payload):
        counts[str(path)]=counts.get(str(path),0)+1
        if 'retry' in str(path.parent.parent) and path.parent.name=='worker_results' and counts[str(path)]==1:
            raise OSError('injected transient worker publication failure')
        atomic_preflight_json(path,payload)
    runner.publish=publish
    for name in ('normal','cancel','retry'):
        config=ThermalConfig(duration_seconds=3 if name!='cancel' else 20,monitoring='approved_unmonitored',unmonitored_approval='pending')
        config=approve_unmonitored(config,[f'fixture:{token}'],'explicit sealed synthetic fixture approval')
        plan=runner.inspect(config)
        if plan['status']!='READY':raise RuntimeError(json.dumps(plan))
        def control(jobs):
            return ['all'] if name=='cancel' and jobs and time.monotonic()-jobs[0]['started']>.8 else []
        directory,result=runner.run(config,plan,Path('/evidence')/name,control=control)
        results[name]=result
    result=dict(contract_id='lvs.storage_thermal.runner_fixture.v1',runs=results)
    Path('/evidence/results.json').write_text(json.dumps(result,indent=2))


def guest():
    Path('/evidence').mkdir()
    p=subprocess.run(['/bin/strace','-ff','-ttt','-yy','-s','0','--kill-on-exit','-o','/evidence/runner.trace',
                      '/usr/bin/python3','/foundation_probe.py','--inside'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90)
    Path('/evidence/driver.stdout').write_bytes(p.stdout);Path('/evidence/driver.stderr').write_bytes(p.stderr)
    if p.returncode:
        print(p.stderr.decode(errors='replace'),flush=True);raise RuntimeError('synthetic runner failed')
    archive=io.BytesIO()
    with tarfile.open(fileobj=archive,mode='w:gz') as tar:tar.add('/evidence',arcname='evidence')
    print('LVS_EVIDENCE_BEGIN',flush=True);print(base64.b64encode(archive.getvalue()).decode(),flush=True);print('LVS_EVIDENCE_END',flush=True)


if __name__=='__main__':
    if '--inside' in sys.argv:inside()
    elif Path('/fixture.json').exists():guest()
    else:
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from Modules.lvs_source_provenance import _source_snapshot
        parser=argparse.ArgumentParser(description=__doc__)
        for name in ('fio','old-fio','guard','strace','kernel','python'):parser.add_argument('--'+name,required=True)
        args=parser.parse_args();root=Path(__file__).resolve().parents[1]
        snapshot,content=_source_snapshot(root);base.require(snapshot['status']=='complete','incomplete source')
        files=[(root/path,'/lvs/'+path) for path in content]
        base.host(args,guest_script=Path(__file__).resolve(),verifier=verify,extra_files=files)
