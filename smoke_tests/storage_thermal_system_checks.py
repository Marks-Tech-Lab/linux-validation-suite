"""System intent, authoritative ancestry and bounded output. No host device access."""
from copy import deepcopy
from dataclasses import asdict,replace
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from Modules.lvs_storage_thermal import ThermalConfig,pilot_rate
from Modules.lvs_storage_thermal_stage import stage_config,set_thermal_setting
from Modules.lvs_storage_thermal_system import ControlBudget,SystemAuthority,configure_targets,_BUDGET
from Modules.lvs_profile_report_artifacts import atomic_preflight_json
from smoke_tests.storage_thermal_runner_checks import TopologyFixture
from smoke_tests.storage_thermal_foundation_checks import rejects


def config(**kw):
    return ThermalConfig(access_mode='shared_readonly_opt_in',selection='individual',device_ids=['serial:sata:SERIAL-A'],
        system_device_ids=['serial:sata:SERIAL-A'],control_plane_colocation=True,
        aggregate_iops_limit=16,aggregate_bps_limit=1048576,**kw)


def run_system_authorization_checks():
    c=config();assert pilot_rate(c,c.device_ids[0],'nvme',system=True)['effective_iops']==64
    for kw in (dict(system_device_ids=True),dict(system_device_ids=['foreign']),dict(control_plane_colocation=1),dict(system_swap=1),dict(selection='all_internal'),dict(access_mode='exclusive'),dict(control_plane_colocation=False)):
        rejects(lambda:replace(c,**kw))
    from Modules.lvs_profile_models import StageConfig,ModuleStorageThermal
    s=StageConfig('x','x',60);s.modules.storage_thermal=ModuleStorageThermal(enabled=True,access_mode='shared_readonly_opt_in',selection='individual',device_ids=list(c.device_ids),aggregate_iops_limit=16,aggregate_bps_limit=1048576)
    assert not stage_config(s).system_device_ids
    set_thermal_setting(s,'thermal_system_access',json.dumps(dict(device_ids=list(c.device_ids),colocated=True,swap=False)))
    assert stage_config(s).system_device_ids==list(c.device_ids)
    saved=asdict(s.modules.storage_thermal);assert 'system_device_ids'not in saved and not any(k.startswith('_')for k in saved)
    restored=deepcopy(s);restored.modules.storage_thermal=ModuleStorageThermal(**saved);assert not stage_config(restored).system_device_ids
    rejects(lambda:configure_targets(SimpleNamespace(),c,None))


def run_system_topology_checks():
    with tempfile.TemporaryDirectory()as name:
        f=TopologyFixture(name);f.disk();(f.proc/'self/mountinfo').write_text('1 0 8:0 / / rw - ext4 /dev/sda rw\n')
        with patch('Modules.lvs_storage_thermal_targets.Path.exists',autospec=True,side_effect=lambda p:False if str(p)in('/.dockerenv','/run/.containerenv')else os.path.exists(p)):
            assert f.resolver.discover(access_mode='shared_readonly_opt_in')[0]['system_drive']
            assert not f.resolver.discover(access_mode='shared_readonly_opt_in')[0]['eligible']
            c=config();f.resolver.system_config=c
            f.resolver.system_approval=dict(contract='shared_system_readonly_v1',device_ids=c.system_device_ids,colocated=True,swap=False,worker_uid=65533,worker_gid=65533,operator_uid=1000)
            row=f.resolver.discover(access_mode='shared_readonly_opt_in')[0];assert row['eligible']and row['system_drive'] and row['system_authorization']
            assert f.resolver.revalidate(row)['eligible']
            (f.proc/'self/mountinfo').write_text('1 0 8:0 / / rw - ext4 /dev/sda rw\n2 1 8:0 / /etc/ssl rw - ext4 /dev/sda rw\n')
            rejects(lambda:f.resolver.revalidate(row))
            swap=f.root/'swap.file';swap.write_bytes(bytes(4096))
            (f.proc/'swaps').write_text(f'Filename Type Size Used Priority\n{swap} file 16 0 -1\n')
            assert not f.resolver.discover(access_mode='shared_readonly_opt_in')[0]['eligible']
            f.resolver.system_approval['swap']=True
            r=f.resolver.discover(access_mode='shared_readonly_opt_in')[0];assert r['eligible']
            (f.proc/'swaps').write_text(f'Filename Type Size Used Priority\n{swap} file 16 4 -1\n')
            assert f.resolver.revalidate(r)['eligible'],'ordinary swap occupancy invalidated topology'
            (f.proc/'swaps').write_text(f'Filename Type Size Used Priority\n{swap} file 16 4 -2\n')
            rejects(lambda:f.resolver.revalidate(r))
            (f.proc/'1/ns/mnt').unlink();r=f.resolver.discover(access_mode='shared_readonly_opt_in')[0];assert not r['eligible']and r['system_drive']and not r['topology_complete']


def run_system_budget_checks():
    with tempfile.TemporaryDirectory()as name:
        b=ControlBudget(1);assert b.space(name)['required_free_bytes']>b.limit
        b.limit=b.used+100;token=_BUDGET.set(b)
        try:
            p=Path(name)/'one.json';atomic_preflight_json(p,{'small':True});before=p.read_bytes()
            try:atomic_preflight_json(p,{'large':'x'*200})
            except OSError:pass
            else:raise AssertionError('write budget ignored')
            assert p.read_bytes()==before
        finally:_BUDGET.reset(token)
        with patch('Modules.lvs_storage_thermal_system.os.statvfs',return_value=SimpleNamespace(f_bavail=0,f_frsize=4096)):
            try:b.space(name)
            except OSError:pass
            else:raise AssertionError('ENOSPC admission permitted')


def run_system_confidentiality_policy_checks():
    with tempfile.TemporaryDirectory()as name:
        root=Path(name);fio=root/'runtime/build/fio';fio.parent.mkdir(parents=True);fio.write_bytes(b'fixture');fio.chmod(0o711)
        original=Path.read_text
        read=lambda p,*a,**k:'0'if str(p)=='/proc/sys/fs/suid_dumpable'else original(p,*a,**k)
        hook=fio.with_name('storage_thermal_confidential.so');hook.write_bytes(b'fixture trusted hook')
        import hashlib
        manifest=dict(uid=1000,gid=1000,worker_uid=65533,worker_gid=65533,files={'runtime/build/storage_thermal_confidential.so':hashlib.sha256(hook.read_bytes()).hexdigest()},backend={'postexec_confidentiality':{'status':'verified'}})
        with patch('Modules.lvs_storage_thermal_system.pwd.getpwuid',return_value=SimpleNamespace(pw_name='lvs-thermal-worker',pw_gid=65533,pw_shell='/sbin/nologin')),patch('Modules.lvs_storage_thermal_system.os.geteuid',return_value=0),patch('Modules.lvs_storage_thermal_system.owned_path',side_effect=lambda p:p),patch.object(Path,'read_text',read):
            assert SystemAuthority(root,manifest).approve(config())['worker_uid']==65533
            with patch.object(Path,'read_text',lambda p,*a,**k:'2'if str(p)=='/proc/sys/fs/suid_dumpable'else original(p,*a,**k)):
                assert SystemAuthority(root,manifest).worker(confidential=False)==(65533,65533)
                assert SystemAuthority(root,manifest).approve(config())['postexec_required']is True
                rejects(lambda:SystemAuthority(root,dict(manifest,files={})).approve(config()))
            fio.chmod(0o755);rejects(lambda:SystemAuthority(root,manifest).approve(config()));fio.chmod(0o711)
            for worker in (0,True,1000):rejects(lambda:SystemAuthority(root,dict(manifest,worker_uid=worker)).approve(config()))
            rejects(lambda:SystemAuthority(root,dict(uid=1000,gid=1000)).approve(config()))


def run_system_evidence_checks():
    from Modules.lvs_storage_thermal_results import _rate_errors
    c=config().to_dict();planned=dict(system_drive=True,system_authorization=dict(worker_uid=65533,worker_gid=65533))
    row=dict(device_id=c['device_ids'][0],guard_evidence=dict(uid=1000,gid=1000),system_authorization=planned['system_authorization'])
    assert 'System execution' in _rate_errors(row,c,planned,{})[0]
    # The actual reader and primary publisher enforce the same system proof.
    from smoke_tests.storage_thermal_audit_matrix_checks import build,publish
    from Modules.lvs_storage_thermal_results import evidence_run,register_stage
    from Modules.lvs_storage_thermal_stage import ThermalStageSession
    from Modules.lvs_run_models import StageWindow
    for mutation in ('valid','missing','foreign','operator_uid','stale_generation','cleanup_uncertain','missing_post','dumpable_post','unsynced_post','foreign_post'):
        with tempfile.TemporaryDirectory()as name, evidence_run(name)as run:
            root=Path(name)
            from Modules.lvs_storage_thermal_launch import prepare
            prepare(root/'bootstrap')
            p,plan,ctx,own=build(root,run)
            cfg=replace(ThermalConfig(),access_mode='shared_readonly_opt_in',selection='individual',device_ids=['audit-drive'],system_device_ids=['audit-drive'],control_plane_colocation=True,aggregate_iops_limit=16,aggregate_bps_limit=1048576).to_dict()
            proof=dict(contract='shared_system_readonly_v1',physical_id='audit-drive',device_ids=['audit-drive'],colocated=True,swap=False,worker_uid=65533,worker_gid=65533,operator_uid=1000,topology_generation='a'*64,postexec_required=True,confidentiality='separate_uid_postexec_nondumpable_v1')
            p['configuration']=cfg;plan['configuration']=deepcopy(cfg)
            plan['devices'][0]['identity']['size_bytes']=1024**3
            p['devices'][0]['identity']['size_bytes']=1024**3
            plan['devices'][0].update(system_drive=True,system_authorization=deepcopy(proof))
            p['readiness']=deepcopy(plan)
            d=p['devices'][0];d.update(access_mode='shared_readonly_opt_in',system_authorization=deepcopy(proof));d['guard_evidence'].update(uid=65533,gid=65533)
            d['guard_evidence']['postexec_confidentiality']=dict(contract_id='lvs.storage_thermal.postexec',version=1,pid=d['pid'],uid=65533,gid=65533,dumpable=0,state_locked=True,thread_sync=True,target_deferred=True,parent=321,major=plan['devices'][0]['identity']['major'],minor=plan['devices'][0]['identity']['minor'],size=plan['devices'][0]['identity']['size_bytes'])
            if mutation=='missing_post':d['guard_evidence'].pop('postexec_confidentiality')
            if mutation=='dumpable_post':d['guard_evidence']['postexec_confidentiality']['dumpable']=2
            if mutation=='unsynced_post':d['guard_evidence']['postexec_confidentiality']['thread_sync']=False
            if mutation=='foreign_post':d['guard_evidence']['postexec_confidentiality']['pid']+=1
            if mutation=='missing':d.pop('system_authorization')
            if mutation=='foreign':d['system_authorization']['physical_id']='foreign'
            if mutation=='operator_uid':d['guard_evidence']['uid']=1000
            if mutation=='stale_generation':d['system_authorization']['topology_generation']='b'*64
            if mutation=='cleanup_uncertain':own['cleanup_confirmed']=False;own['workers'][0].update(reaped=False,cleanup_confirmed=False,exit_code=None)
            s=ThermalStageSession(SimpleNamespace(id='s1',duration_seconds=120),plan,root,clock=lambda:1120.2,recovery_marker=root/'intent')
            s.context=ctx;s.closed_ns=int(1120e9);s.primary_end_ns=int(1120e9);s.process=SimpleNamespace(poll=lambda:0)
            s.directory.mkdir(parents=True);(s.directory/'completion.json').write_text(json.dumps(p));(s.directory/'launch_ownership.json').write_text(json.dumps(own))
            s._read_terminal()
            w=StageWindow(stage_id='s1',stage_type='CPU Load',display_name='CPU',started_iso='2026-11-10T00:00:00',ended_iso='2026-11-10T00:02:00',started_monotonic=1000,ended_monotonic=1120,duration_seconds=120,trim_start_seconds=0,trim_end_seconds=0,verdict='pass')
            w.storage_thermal_summary=s.evidence;register_stage(w,s);pub=publish(root,w)
            whole=json.loads((root/'run_manifest.json').read_text())['storage_thermal_summary']['auxiliary_outcome']
            expected='COMPLETED_WITH_WARNINGS'if mutation=='valid'else'ERROR'
            assert s.evidence['auxiliary_outcome']==whole==expected,(mutation,s.evidence,whole)
            assert pub.overall_verdict=='pass'
            if mutation=='cleanup_uncertain':assert not s.evidence['cleanup_confirmed']
            print('System evidence',mutation,expected,'reader/publisher; primary PASS preserved')
