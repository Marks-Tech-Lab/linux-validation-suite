"""Independent audit contradiction matrix, synthetic evidence and no drive access."""
import copy,json,os,tempfile,sys,traceback
from pathlib import Path
from types import SimpleNamespace
from Modules.lvs_storage_thermal import ThermalResult,ThermalConfig,pilot_rate
from Modules.lvs_storage_thermal_results import evidence_run,register_stage,summarize_run,summary_text,normalize
from Modules.lvs_storage_thermal_stage import ThermalStageSession
from Modules.lvs_run_artifacts import write_final_run_artifacts
from Modules.lvs_run_models import StageWindow
from Modules.lvs_profile_models import ValidationProfile
from Modules.lvs_summary_text import SummaryTextBuilder
from Modules.lvs_storage_thermal_launch import prepare

ROOT=Path.cwd()

def build(root,run,*,stage_id='s1',begin=1000,seconds=120):
 cfg=json.loads(json.dumps(ThermalConfig(duration_seconds=seconds).to_dict()))
 backend=dict(status='available',stage_admission_protocol='v2',fio={'sha256':'fio-current'},guard={'sha256':'guard-current'})
 src={'source':{'digest':'current-source','status':'complete','file_count':387}}
 identity={'stable':'AUDIT-HDD','major':8,'minor':0}
 rate=pilot_rate(ThermalConfig(**cfg),'audit-drive','hdd')
 guard=dict(contract_id='lvs.storage_thermal.guard',contract_version=1,pid=12345,uid=1000,gid=1000,capabilities=0,seccomp=2,no_new_privs=1,readonly_direct=True,supplementary_groups=0,extra_fds_closed=0)
 d=ThermalResult('audit-drive',identity,state='completed',source_provenance=src,executable_provenance=backend,effective_rate=copy.deepcopy(rate),started_monotonic=begin+.1,ended_monotonic=begin+seconds+.1,launch_requested_monotonic=begin,duration_completed=True,cleanup_confirmed=True,terminal_published=True,identity_unchanged=True,guard_confirmed=True,provenance_confirmed=True,exit_code=0,read_ios=1800,read_bytes=1800*65536,temperature_status='monitored').to_dict()
 d.update(configured_duration_seconds=seconds,pid=12345,guard_evidence=guard,fio_activity={'active_seconds':seconds,'achieved_iops':1800/seconds,'achieved_bps':1800*65536/seconds})
 plan=dict(status='READY',configuration=cfg,backend=backend,source_provenance=src,selected_devices=['audit-drive'],runnable_devices=['audit-drive'],devices=[dict(device_id='audit-drive',identity=identity,selected=True,state='ready',rate=copy.deepcopy(rate))])
 ctx=dict(version=1,run_id=run['run_id'],session_id='audit-'+stage_id,stage_id=stage_id,run_directory=os.path.abspath(root),started_ns=int(begin*1e9),deadline_ns=int((begin+seconds)*1e9),lease_identity=[10,20])
 own=dict(protocol='lvs-storage-thermal-stage-admission-v2',lease_identity=[10,20],cleanup_confirmed=True,publication_error='',revocation_error='',workers=[dict(pid=12345,phase='committed',group_ready=True,descriptor_offered=True,io_admission='committed',reaped=True,exit_code=0,cleanup_confirmed=True,committed_monotonic_ns=int((begin+.05)*1e9))])
 p=dict(source_provenance=copy.deepcopy(src),contract_id='lvs.storage_thermal.manifest',contract_version=1,status='completed',verdict='PASS',requested=True,execution_started=True,parent_finalization_complete=True,configuration=cfg,requested_devices=['audit-drive'],executed_devices=['audit-drive'],unexecuted_devices=[],devices=[d],readiness=copy.deepcopy(plan),stage_launch_ownership=own,execution_context=ctx,cleanup_confirmed=True,terminal_published=True)
 return p,copy.deepcopy(plan),copy.deepcopy(ctx),copy.deepcopy(own)

def publish(root,w):
 root=Path(root)
 parser=SimpleNamespace(summarize=lambda *a:dict(Segments=[]));exporter=SimpleNamespace(build=lambda *a:dict(Result='PASS',Segments=[]))
 return write_final_run_artifacts(run_dir=root,manifest_payload={},app_name='LVS',app_version='audit',profile=ValidationProfile('audit'),metadata=ValidationProfile('audit'),started_iso=w.started_iso,ended_iso=w.ended_iso,total_elapsed=w.duration_seconds,system_info={'Hardware':{'Gpu':[],'Cpu':{}}},telemetry=SimpleNamespace(samples=[],interval_seconds=1),stage_windows=[w],executed_plan=[dict(stage_id=w.stage_id)],recovery_report={},skipped_stages=[],run_aborted=False,keep_raw_telemetry=False,export_compatibility_json=True,export_extended_json=False,segment_parser=parser,exporter=exporter,summary_exporter=SummaryTextBuilder(),stage_sensor_events=lambda w:[],stage_faults=lambda w:[],capture_run_end=lambda **k:None)


def run_thermal_audit_matrix_checks():
    cases=[]
    def setpath(path,value):
     def f(p,a):
      x=p
      for k in path[:-1]:x=x[k]
      if value is DELETE:x.pop(path[-1],None)
      else:x[path[-1]]=copy.deepcopy(value)
     return f
    DELETE=object()
    def case(name,path,value,expected='ERROR'):cases.append((name,setpath(path,value),expected))
    cases.append(('valid_full',lambda p,a:None,'COMPLETED'))
    for key in ('duration_completed','cleanup_confirmed','terminal_published','identity_unchanged','guard_confirmed','provenance_confirmed'):
     case('device_'+key,['devices',0,key],False)
    for key in ('write_ios','discard_ios','flush_ios','errors','outstanding_descriptors'):
     case('device_'+key,['devices',0,key],1)
    for key,value in [('read_ios',0),('read_ios',True),('read_bytes',1),('exit_code',7),('started_monotonic',None),('ended_monotonic',float('nan')),('configured_duration_seconds',1),('fio_activity',{}),('identity',{'stable':'old'}),('source_provenance',{}),('executable_provenance',{})]:
     case('device_'+key+'_'+repr(value),['devices',0,key],value)
    case('short_0.01s',['devices',0,'ended_monotonic'],1000.11)
    case('fio_0.01s',['devices',0,'fio_activity','active_seconds'],.01)
    case('deadline_plus_1000',['devices',0,'ended_monotonic'],2120)
    case('launch_before_window',['devices',0,'launch_requested_monotonic'],999,'COMPLETED')
    case('commit_before_window',['stage_launch_ownership','workers',0,'committed_monotonic_ns'],999000000000)
    for key,val in [('exit_code',7),('reaped',False),('cleanup_confirmed',False),('phase','created'),('launch_failed',True),('group_ready',False),('descriptor_offered',False),('pid',999),('io_admission','not_requested')]:
     case('owner_'+key,['stage_launch_ownership','workers',0,key],val)
    for key,val in [('protocol','old-protocol'),('protocol',DELETE),('cleanup_confirmed',False),('lease_identity',[11,21])]:case('ownership_'+key+'_'+str(val),['stage_launch_ownership',key],val)
    for key,val in [('readonly_direct',False),('seccomp',0),('capabilities',123),('no_new_privs',0),('uid',0),('gid',0),('contract_id','wrong.guard'),('contract_version',99),('pid',999)]:
     case('guard_witness_'+key,['devices',0,'guard_evidence',key],val)
    for key,val in [('requested',False),('requested','false'),('execution_started',False),('execution_started',0),('execution_started','false'),('status','not_run'),('auxiliary_outcome','STOPPED'),('auxiliary_outcome','ERROR'),('operator_cancelled',True),('cleanup_confirmed',False),('terminal_published',False),('contract_version',True),('contract_id','wrong')]:
     case('aggregate_'+key+'_'+str(val),[key],val,'STOPPED' if key in ('operator_cancelled','auxiliary_outcome') and val in (True,'STOPPED') else 'ERROR')
    case('old_run',['execution_context','run_id'],'PREVIOUS_RUN')
    case('old_stage',['execution_context','stage_id'],'PREVIOUS_STAGE')
    case('old_device',['devices',0,'device_id'],'old-device')
    case('wrong_eligible',['executed_devices'],['not-selected'])
    case('missing_config',['configuration'],{})
    case('duration_exceeds_request',['configuration','duration_seconds'],121)
    case('duration_no_declared_shortening',['configuration','duration_seconds'],60)
    case('changed_rate',['configuration','intensity_percent'],99)
    case('missing_device',['devices'],[])
    case('root_failure',['failure'],'known failure')
    # Tolerance boundaries, with raw times intentionally synthetic.
    for delta,expected in [(.049,'COMPLETED'),(.051,'ERROR')]:
     def bound(p,a,delta=delta):p['devices'][0]['fio_activity']['active_seconds']=120+delta
     cases.append(('activity_boundary_'+str(delta),bound,expected))
    def fail_notrun(p,a):
     p.update(verdict='BLOCKED',requested=False,execution_started=False,executed_devices=[]);p['devices'][0].update(exit_code=7,state='failed',read_ios=15,read_bytes=15*65536)
    cases.append(('original_failed_NOT_RUN',fail_notrun,'ERROR'))
    def failed_boot(p,a):p['stage_launch_ownership']['workers'].append(dict(pid=555,phase='created',group_ready=False,descriptor_offered=False,io_admission='not_requested',reaped=True,exit_code=7,cleanup_confirmed=True,launch_failed=True))
    cases.append(('original_extra_failed_bootstrap',failed_boot,'ERROR'))
    def duplicate(p,a):p['stage_launch_ownership']['workers'].append(copy.deepcopy(p['stage_launch_ownership']['workers'][0]))
    cases.append(('duplicate_owner',duplicate,'ERROR'))
    def body_false_cleanup(p,a):a['cleanup_confirmed']=False;a['workers'][0].update(cleanup_confirmed=False,reaped=False,exit_code=None)
    cases.append(('independent_cleanup_false',body_false_cleanup,'ERROR'))
    def raw_provenance(p,a):p['source_provenance_end']={'source':{'status':'complete','digest':'CHANGED'}}
    cases.append(('source_end_changed',raw_provenance,'ERROR'))
    def unavailable(p,a):
     p.update(verdict='BLOCKED',status='not_run',execution_started=False,devices=[],executed_devices=[],stage_launch_ownership=None)
     p['readiness']['devices'][0].update(state='blocked',reasons=['unavailable'])
     cases_dummy=None
    cases.append(('valid_unavailable',unavailable,'NOT_RUN'))
    def zero(p,a):
     unavailable(p,a);p['configuration']['intensity_percent']=0;p['readiness']['configuration']['intensity_percent']=0
     p['readiness']['devices'][0].update(state='skipped',reasons=['zero intensity'])
    cases.append(('valid_zero_intensity',zero,'NOT_RUN'))
    def shorten(p,a):
     p['configuration']['duration_seconds']=60;p['stage_window_shortened']=True
     p['devices'][0].update(ended_monotonic=1060.1,configured_duration_seconds=60,fio_activity={'active_seconds':60})
    cases.append(('valid_shortened',shorten,'COMPLETED_WITH_WARNINGS'))
    def partial(p,a):
     p['verdict']='WARN';p['requested_devices'].append('blocked');p['readiness']['devices'].append(dict(device_id='blocked',identity={'stable':'BLOCKED'},selected=True,state='blocked',reasons=['active']))
    cases.append(('valid_partial',partial,'COMPLETED_WITH_WARNINGS'))
    def stopped(p,a):
     p['verdict']='INCOMPLETE';p['devices'][0].update(state='cancelled',exit_code=-15,duration_completed=False,ended_monotonic=1001,fio_activity={'active_seconds':.9})
     p['stage_launch_ownership']['workers'][0]['exit_code']=-15
    cases.append(('valid_cancelled',stopped,'STOPPED'))
    def mixed(p,a):
     p['verdict']='FAIL';d=copy.deepcopy(p['devices'][0]);d.update(device_id='second',identity={'stable':'SECOND','major':8,'minor':1},pid=54321,exit_code=7,state='failed',errors=1,guard_evidence=dict(d['guard_evidence'],pid=54321))
     p['devices'].append(d);p['executed_devices'].append('second');p['requested_devices'].append('second')
     w=copy.deepcopy(p['stage_launch_ownership']['workers'][0]);w.update(pid=54321,exit_code=7);p['stage_launch_ownership']['workers'].append(w)
     p['readiness']['devices'].append(dict(device_id='second',identity=d['identity'],selected=True,state='ready'))
    cases.append(('valid_mixed',mixed,'ERROR'))
    case('valid_late_start',['devices',0,'started_monotonic'],1010,'COMPLETED')
    case('observation_inside',['devices',0,'ended_monotonic'],1120.299,'COMPLETED')
    case('observation_outside',['devices',0,'ended_monotonic'],1120.301,'ERROR')


    def exact_short(p,a):p['devices'][0].update(ended_monotonic=1000.11,read_ios=1,read_bytes=65536,fio_activity={'active_seconds':.01})
    cases.append(('exact_original_0.01_for_120',exact_short,'ERROR'))
    def bad_guard_stopped(p,a):p['devices'][0]['guard_evidence']['readonly_direct']=False;p['auxiliary_outcome']='STOPPED'
    cases.append(('combined_guard_and_stopped',bad_guard_stopped,'ERROR'))
    def changed_source_header(p,a):p['source_provenance_end']={'source':{'digest':'CHANGED','status':'complete'}};p['contract_version']=True
    cases.append(('combined_source_and_header',changed_source_header,'ERROR'))
    def short_stopped(p,a):exact_short(p,a);p['auxiliary_outcome']='STOPPED'
    cases.append(('combined_short_and_stopped',short_stopped,'ERROR'))
    def cleanup_false_notrun(p,a):p['devices'][0]['cleanup_confirmed']=False;fail_notrun(p,a)
    cases.append(('combined_cleanup_and_notrun',cleanup_false_notrun,'ERROR'))

    def omitted_terminal(p,a):
     p.update(verdict='BLOCKED',status='not_run',requested=False,execution_started=False,devices=[],executed_devices=[],stage_launch_ownership=None)
     a['workers'][0]['exit_code']=7
    cases.append(('independent_failed_execution_omitted',omitted_terminal,'ERROR'))
    def omitted_unreaped(p,a):
     omitted_terminal(p,a);a['cleanup_confirmed']=False
     a['workers'][0].update(reaped=False,exit_code=None,cleanup_confirmed=False)
    cases.append(('independent_unreaped_execution_omitted',omitted_unreaped,'ERROR'))
    case('missing_root_version',['contract_version'],DELETE)
    case('foreign_root_version',['contract_version'],99)
    case('guard_boolean_version',['devices',0,'guard_evidence','contract_version'],True)
    # Fresh final-audit counterexamples: keep child counters internally valid.
    case('root_initial_changed',['source_provenance','source','digest'],'DIFFERENT-SOURCE')
    def root_with_endpoint(p,a):
     p['source_provenance_end']=copy.deepcopy(p['source_provenance'])
     p['source_provenance']['source']['digest']='DIFFERENT-SOURCE'
    cases.append(('root_changed_with_valid_endpoint',root_with_endpoint,'ERROR'))
    case('missing_required_root_source',['source_provenance'],None)
    case('valid_optional_endpoint_missing',['source_provenance_end'],DELETE,'COMPLETED')
    def valid_endpoint(p,a):p['source_provenance_end']=copy.deepcopy(p['source_provenance'])
    cases.append(('valid_matching_endpoint',valid_endpoint,'COMPLETED'))
    def bad_size(p,a):
     p['devices'][0]['effective_rate'].update(block_size=4096,effective_bps=15*4096)
     p['devices'][0]['read_bytes']=p['devices'][0]['read_ios']*4096
     p['devices'][0]['fio_activity']['achieved_bps']=15*4096
    cases.append(('unauthorized_4k_read',bad_size,'ERROR'))
    def bad_rate(p,a):
     p['devices'][0]['effective_rate'].update(effective_iops=1000000,effective_bps=65536000000,requested_iops=1000000.0)
     p['devices'][0].update(read_ios=120000000,read_bytes=120000000*65536)
     p['devices'][0]['fio_activity'].update(achieved_iops=1000000,achieved_bps=65536000000)
    cases.append(('unauthorized_million_iops',bad_rate,'ERROR'))
    case('missing_effective_rate',['devices',0,'effective_rate'],{})
    def command(p,a,iops):p['devices'][0]['command']=['/guard','--fio-fd','9','1000','1000','8','0','65536','65536',str(iops),'120']
    cases.append(('unauthorized_recorded_command',lambda p,a:command(p,a,1000000),'ERROR'))
    cases.append(('valid_recorded_command',lambda p,a:command(p,a,15),'COMPLETED'))
    def slower(p,a):
     p['devices'][0].update(read_ios=60,read_bytes=60*65536,fio_activity=dict(active_seconds=120,achieved_iops=.5,achieved_bps=.5*65536))
    cases.append(('valid_slower_throughput',slower,'COMPLETED'))
    def authorized_lower(p,a):
     p['configuration']['intensity_percent']=25
     p['readiness']['configuration']=copy.deepcopy(p['configuration'])
     rate=pilot_rate(ThermalConfig(**p['configuration']),'audit-drive','hdd')
     p['devices'][0]['effective_rate']=copy.deepcopy(rate);p['readiness']['devices'][0]['rate']=copy.deepcopy(rate)
    cases.append(('authorized_lower_rate',authorized_lower,'COMPLETED'))
    def classes(p,a):
     d=copy.deepcopy(p['devices'][0]);d.update(device_id='synthetic-ssd',identity={'stable':'SSD','major':8,'minor':1},pid=54321)
     d['guard_evidence']['pid']=54321
     rate=pilot_rate(ThermalConfig(**p['configuration']),d['device_id'],'ssd')
     d['effective_rate']=copy.deepcopy(rate);d.update(read_ios=rate['effective_iops']*120,read_bytes=rate['effective_bps']*120)
     d['fio_activity'].update(achieved_iops=rate['effective_iops'],achieved_bps=rate['effective_bps'])
     p['devices'].append(d);p['requested_devices'].append(d['device_id']);p['executed_devices'].append(d['device_id'])
     p['readiness']['devices'].append(dict(device_id=d['device_id'],identity=d['identity'],state='ready',selected=True,rate=copy.deepcopy(rate)))
     owner=copy.deepcopy(p['stage_launch_ownership']['workers'][0]);owner['pid']=54321;p['stage_launch_ownership']['workers'].append(owner)
    # Arithmetic evidence fixture only: production SSD eligibility stays blocked.
    cases.append(('valid_multi_class_evidence',classes,'COMPLETED'))
    rows=[]
    with tempfile.TemporaryDirectory(prefix='lvs-matrix-') as work:
     AUDIT=Path(work)/'diagnostics';AUDIT.mkdir()
     prepare(Path(work)/'bootstrap')
     for i,(name,mutate,expected) in enumerate(cases):
      root=Path(work)/str(i);root.mkdir()
      with evidence_run(root) as run:
       p,plan,ctx,own=build(root,run);a=copy.deepcopy(own)
       mutate(p,a)
       # Intrinsic ownership contradictions are also published independently so the
       # validator cannot reject merely because a secondary copy differs.
       if name in ('valid_unavailable','valid_zero_intensity','valid_partial','valid_mixed','authorized_lower_rate','valid_multi_class_evidence'):plan=copy.deepcopy(p['readiness'])
       if name in ('valid_unavailable','valid_zero_intensity'):a=None
       if name.startswith(('owner_','ownership_')) or name in ('original_extra_failed_bootstrap','duplicate_owner','valid_cancelled','valid_mixed','valid_multi_class_evidence'):a=copy.deepcopy(p['stage_launch_ownership'])
       st=SimpleNamespace(id='s1',duration_seconds=120)
       s=ThermalStageSession(st,plan,root,clock=lambda:1120.2,recovery_marker=root/'intent');s.context=ctx;s.closed_ns=int(1120e9);s.primary_end_ns=int(1120e9);s.process=SimpleNamespace(poll=lambda:0)
       s.directory.mkdir(parents=True);(s.directory/'completion.json').write_text(json.dumps(p));(s.directory/'launch_ownership.json').write_text(json.dumps(a))
       s._read_terminal();terminal=s.evidence.get('auxiliary_outcome')
       w=StageWindow(stage_id='s1',stage_type='CPU Load',display_name='CPU',started_iso='2026-11-10T00:00:00',ended_iso='2026-11-10T00:02:00',started_monotonic=1000,ended_monotonic=1120,duration_seconds=120,trim_start_seconds=0,trim_end_seconds=0,verdict='pass');w.storage_thermal_summary=s.evidence
       register_stage(w,s)
       pub=publish(root,w);manifest=json.loads((root/'run_manifest.json').read_text())
       whole=manifest['storage_thermal_summary']['auxiliary_outcome']
       row=dict(name=name,expected=expected,terminal=terminal,stage=w.storage_thermal_summary.get('auxiliary_outcome'),whole=whole,primary=pub.overall_verdict,cleanup=s.evidence.get('cleanup_confirmed'),errors=s.evidence.get('session_errors') or s.evidence.get('evidence_errors'),failure=s.evidence.get('failure'),drive_outcomes=[d['auxiliary_outcome'] for d in s.evidence.get('drive_outcomes',[])])
       rows.append(row)
       print('CASE',name,'expected='+expected,'terminal='+str(terminal),'whole='+str(whole),'primary='+str(pub.overall_verdict),flush=True)
       if terminal!=expected or whole!=expected:
        (AUDIT/(str(i)+'-input.json')).write_text(json.dumps(dict(payload=p,ownership=a,context=ctx,readiness=plan),indent=2));print('COUNTEREXAMPLE',json.dumps(row),flush=True)
    print('MATRIX',len(rows),'cases;',sum(r['terminal']==r['expected'] and r['whole']==r['expected'] for r in rows),'expected outcomes',flush=True)
    assert all(r['terminal']==r['expected'] and r['whole']==r['expected'] for r in rows),[r for r in rows if r['terminal']!=r['expected'] or r['whole']!=r['expected']]
    assert next(r for r in rows if r['name']=='independent_cleanup_false')['cleanup'] is False


def run_thermal_audit_registration_checks():
    with tempfile.TemporaryDirectory() as temp:
        prepare(Path(temp)/'launch')
        with evidence_run(temp) as run:
            windows=[]
            for i in range(2):
                p,plan,ctx,own=build(temp,run,stage_id='s'+str(i),begin=1000+i*200)
                if i==0:p['failure']='independently recorded failure'
                w=StageWindow(stage_id=ctx['stage_id'],stage_type='CPU Load',display_name=ctx['stage_id'],
                    started_iso='2026-11-10T00:00:00',ended_iso='2026-11-10T00:02:00',
                    started_monotonic=ctx['started_ns']/1e9,ended_monotonic=ctx['deadline_ns']/1e9,
                    duration_seconds=120,trim_start_seconds=0,trim_end_seconds=0,verdict='pass')
                w.storage_thermal_summary=p
                register_stage(w,SimpleNamespace(context=ctx,plan=plan,terminal_observation=dict(
                    ownership=own,observed_ns=ctx['deadline_ns']+200000000,closed_ns=ctx['deadline_ns'])))
                windows.append(w)
            assert summarize_run(windows,run_dir=temp)['auxiliary_outcome']=='ERROR'
            assert summarize_run([windows[1]],run_dir=temp)['auxiliary_outcome']=='ERROR'
            assert publish(temp,windows[1]).overall_verdict=='pass'
            assert json.loads((Path(temp)/'run_manifest.json').read_text())['storage_thermal_summary']['auxiliary_outcome']=='ERROR'
        for field,value in [('contract_id','foreign'),('contract_version',99),('contract_version',True)]:
            with evidence_run(temp) as run:
                p,plan,ctx,own=build(temp,run)
                w=windows[0];w.stage_id=ctx['stage_id'];w.started_monotonic=1000;w.storage_thermal_summary=dict(p,**{field:value})
                register_stage(w,SimpleNamespace(context=ctx,plan=plan,terminal_observation=dict(ownership=own,observed_ns=int(1120.2e9))))
                assert publish(temp,w).overall_verdict=='pass'
                assert json.loads((Path(temp)/'run_manifest.json').read_text())['storage_thermal_summary']['auxiliary_outcome']=='ERROR'
    print('  Registered ERROR omission and foreign/boolean headers: ERROR at actual primary publication; primary PASS preserved')


def run_thermal_audit_creation_identity_checks():
    import time
    from Modules.lvs_storage_thermal_launch import OwnedProcess
    with tempfile.TemporaryDirectory() as root:
        prepare(root)
        def child(code='import time;time.sleep(10)'):
            return OwnedProcess([sys.executable,'-B','-c',code])
        def cleanup(p):
            if p.poll() is None:p.kill()
            p.wait(timeout=2)
        p,v=child(),child();original=p.pid
        try:
            p.pid=v.pid;p.terminate()
            assert p.wait(timeout=2)==-15
            assert v.poll() is None,'Wrong numeric process group was signaled'
        finally:
            p.pid=original
            cleanup(p);cleanup(v)
        p,v=child(),child('pass');original=p.pid
        try:
            v.wait(timeout=2);p.pid=v.pid
            assert p.poll() is None,'Wrong child was reaped'
            p.kill();assert p.wait(timeout=2)==-9
        finally:
            p.pid=original;cleanup(p);cleanup(v)
    print('  Public PID substitution cannot redirect signals, process-group targeting, or reaping; unrelated fixture remains alive')
    # The project interpreter may lack pidfd APIs. Exercise the same fixture
    # through an installed standard-library interpreter that supplies them.
    import signal,subprocess
    host=Path('/usr/bin/python3')
    if not hasattr(os,'pidfd_open') and host.exists():
        probe=subprocess.run([str(host),'-c',"import os;raise SystemExit(not hasattr(os,'pidfd_open'))"],capture_output=True,timeout=5)
        if probe.returncode==0:
            result=subprocess.run([str(host),'-B','-c',
                'from smoke_tests.storage_thermal_audit_matrix_checks import run_thermal_audit_creation_identity_checks as check;check()'],
                capture_output=True,text=True,timeout=20,env={**os.environ,'PYTHONPATH':str(ROOT),'PYTHONDONTWRITEBYTECODE':'1'})
            assert result.returncode==0,result.stdout+result.stderr
            print('  Host pidfd signaling/reaping identity fixture: PASS')


def run_thermal_audit_cancel_barrier_checks():
    import time,functools
    from unittest.mock import patch
    from Modules import lvs_stage_execution as runtime
    from smoke_tests.storage_thermal_stage_checks import _run_primary_with_aux
    from smoke_tests.storage_thermal_foundation_checks import compile_guard
    code=r'''
import sys,os,json,time
from pathlib import Path
from Modules.lvs_storage_thermal_stage import StageChannel,SharedAdmission
from smoke_tests.storage_thermal_stage_checks import NativeAdmissionFixture
channel=StageChannel(*map(int,sys.argv[1].split(':')));b=b''
while b'\n' not in b:b+=channel.recv(65536)
r=json.loads(b.split(b'\n')[0]);channel.sendall((json.dumps(dict(ready=True,lease=r['stage_lease_id']))+'\n').encode());b=b''
while b'\n' not in b:b+=channel.recv(65536)
permission=json.loads(b.split(b'\n')[0]);assert permission['run']
start=r['stage_deadline']-2
time.sleep(max(0,start+.8-time.monotonic()))
f=NativeAdmissionFixture(Path(sys.argv[2])/'native',Path(sys.argv[3]),seconds=3)
f.state.close()
f.state=SharedAdmission(r['admission_fd'],r['admission_identity']);f.lease.admission=f.state
f.lease.deadline=r['stage_deadline'];f.lease.deadline_ns=int(f.lease.deadline*1e9)
try:
 p=f.launch();p.wait(timeout=1)
 Path(sys.argv[2],'native_result.json').write_text(json.dumps(dict(at=time.monotonic()-start,closed_before_cleanup=f.state.closed(),exit=p.returncode,committed='COMMITTED' in f.text(),stderr=f.text())))
except Exception as exc:
 Path(sys.argv[2],'native_result.json').write_text(json.dumps(dict(at=time.monotonic()-start,closed_before_cleanup=f.state.closed(),committed=False,rejected=str(exc),stderr=f.text())))
finally:f.close()
'''
    with tempfile.TemporaryDirectory() as root:
     root=Path(root);guard=compile_guard(root);sessions=[];timing={};original=runtime.execute_stage_runtime
     def factory(st,p,rd,**kw):
      t=ThermalStageSession(st,{'status':'READY'},root,launch_args=[sys.executable,'-B','-c',code,'{channel}',str(root),str(guard)],recovery_marker=root/'intent',**kw);sessions.append(t);return t
     @functools.wraps(original)
     def wrapped(**kw):
      origin=kw['stage_start']
      def stop(workers):timing['cpu_cleanup_start']=time.monotonic()-origin;time.sleep(1);timing['cpu_cleanup_end']=time.monotonic()-origin
      kw['stop_stage_processes']=stop
      return original(**kw)
     origin=time.monotonic()
     def cancel():
      now=time.monotonic()
      if now-origin>.4:
       timing.setdefault('cancel_requested',now-origin);return True
      return False
     with patch.object(runtime,'execute_stage_runtime',new=wrapped):
      result,args,_=_run_primary_with_aux(None,session_factory=factory,real_clock=True,telemetry_interval=.05,cancel_check=cancel)
     timing.update(native=json.loads((root/'native_result.json').read_text()),primary_elapsed=result.stage_elapsed,aborted=result.stage_aborted,telemetry=args['telemetry_times'])
     print(json.dumps(timing,indent=2));assert not timing['native']['committed'] and timing['native']['closed_before_cleanup']
     assert timing['native']['at']<timing['cpu_cleanup_end'] and len(timing['telemetry'])>=4


def run_thermal_audit_missing_evidence_checks():
    with tempfile.TemporaryDirectory() as root:
        prepare(Path(root)/'launch')
        for mode in ('missing','corrupt','missing_registry','missing_records'):
            directory=Path(root)/mode;directory.mkdir()
            with evidence_run(directory) as run:
                p,plan,ctx,own=build(directory,run)
                s=ThermalStageSession(SimpleNamespace(id='s1',duration_seconds=120),plan,directory,
                    clock=lambda:1120.2,recovery_marker=directory/'intent')
                s.context=ctx;s.closed_ns=int(1120e9);s.process=SimpleNamespace(poll=lambda:0)
                s.directory.mkdir(parents=True)
                if mode!='missing_registry':(s.directory/'launch_ownership.json').write_text(json.dumps(own))
                if mode=='corrupt':(s.directory/'completion.json').write_text('{truncated')
                elif mode!='missing':
                    if mode=='missing_records':p.update(devices=[],executed_devices=[],stage_launch_ownership=None,requested=False,execution_started=False,verdict='BLOCKED')
                    (s.directory/'completion.json').write_text(json.dumps(p))
                s._read_terminal()
                assert s.evidence['auxiliary_outcome']=='ERROR',(mode,s.evidence)
                assert s.evidence['cleanup_confirmed'] is False,(mode,s.evidence)
    print('  Missing/corrupt terminal and omitted registry/device evidence: ERROR, cleanup not certified')


def _current_window(root,p,plan,ctx,own):
    session=ThermalStageSession(SimpleNamespace(id=ctx['stage_id'],duration_seconds=ctx['deadline_ns']//1000000000-ctx['started_ns']//1000000000),
        plan,root,clock=lambda:ctx['deadline_ns']/1e9+.2,recovery_marker=Path(root)/'intent')
    session.context=copy.deepcopy(ctx);session.closed_ns=ctx['deadline_ns'];session.primary_end_ns=ctx['deadline_ns']
    session.process=SimpleNamespace(poll=lambda:0);session.directory.mkdir(parents=True)
    (session.directory/'completion.json').write_text(json.dumps(p))
    (session.directory/'launch_ownership.json').write_text(json.dumps(own))
    session._read_terminal()
    window=StageWindow(stage_id=ctx['stage_id'],stage_type='CPU Load',display_name=ctx['stage_id'],
        started_iso='2026-11-10T00:00:00',ended_iso='2026-11-10T00:02:00',started_monotonic=ctx['started_ns']/1e9,
        ended_monotonic=ctx['deadline_ns']/1e9,duration_seconds=(ctx['deadline_ns']-ctx['started_ns'])/1e9,
        trim_start_seconds=0,trim_end_seconds=0,verdict='pass')
    window.storage_thermal_summary=copy.deepcopy(session.evidence)
    return session,window


def run_thermal_final_disposition_checks():
    from Modules.lvs_storage_thermal_results import _ACTIVE_RUN
    with tempfile.TemporaryDirectory() as work:
        root=Path(work);prepare(root/'launch')
        for fault in ('publication','cleanup','finalization','stopped','partial','missing_final','duplicate_final','registration_invalid_source'):
            folder=root/fault;folder.mkdir()
            with evidence_run(folder) as run:
                p,plan,ctx,own=build(folder,run)
                session,w=_current_window(folder,p,plan,ctx,own)
                earlier=copy.deepcopy(w.storage_thermal_summary)
                if fault=='publication':w.storage_thermal_summary.update(auxiliary_outcome='ERROR',publication_integrity=False,publication_error='parent publication failed')
                if fault=='cleanup':w.storage_thermal_summary.update(auxiliary_outcome='ERROR',cleanup_confirmed=False,persistent_recovery_required=True,recovery_reason='primary cleanup uncertain')
                if fault=='finalization':w.storage_thermal_summary.update(auxiliary_outcome='ERROR',failure='primary finalizer exception')
                if fault=='stopped':w.storage_thermal_summary.update(auxiliary_outcome='STOPPED',operator_cancelled=True)
                if fault=='partial':
                    w.storage_thermal_summary.update(verdict='WARN',auxiliary_outcome='COMPLETED_WITH_WARNINGS')
                if fault=='registration_invalid_source':w.storage_thermal_summary['source_provenance']['source']['digest']='FOREIGN'
                register_stage(w,session)
                if fault=='registration_invalid_source':assert w.storage_thermal_summary['auxiliary_outcome']=='ERROR'
                if fault in ('publication','cleanup','finalization'):w.storage_thermal_summary=earlier
                if fault=='missing_final':run['windows'][id(w)][1].pop('final')
                if fault=='duplicate_final':
                    p2,a2,c2,o2=build(folder,run,stage_id='s2',begin=1200)
                    s2,w2=_current_window(folder,p2,a2,c2,o2);register_stage(w2,s2)
                    run['windows'][id(w2)][1]['final']['generation']=run['windows'][id(w)][1]['final']['generation']
                    assert summarize_run([w,w2],run_dir=folder)['auxiliary_outcome']=='ERROR'
                primary=publish(folder,w)
                observed=json.loads((folder/'run_manifest.json').read_text())['storage_thermal_summary']
                expected='STOPPED' if fault=='stopped' else 'COMPLETED_WITH_WARNINGS' if fault=='partial' else 'ERROR'
                assert observed['auxiliary_outcome']==expected,(fault,observed)
                assert primary.overall_verdict=='pass'
                if fault=='cleanup':assert w.storage_thermal_summary['cleanup_confirmed'] is False and w.storage_thermal_summary['persistent_recovery_required'] is True
                if fault in ('finalization','publication','cleanup'):assert w.storage_thermal_summary.get('rejected_terminal_evidence')
        # Exact reproduction: a real parent finalization exception on the shared
        # stage runtime, then replay of its earlier valid child terminal.
        from smoke_tests.storage_thermal_stage_checks import _run_primary_with_aux
        from Modules import lvs_stage_execution as runtime
        from unittest.mock import patch
        import functools
        with evidence_run(root) as run:
            saved={}
            def factory(st,plan,rd,**kw):
                body,a,c,own=build(root,run,stage_id=st.id,begin=kw['stage_deadline']-2,seconds=2)
                saved['terminal']=copy.deepcopy(body)
                def failed(**kw):raise OSError('injected actual parent-side auxiliary finalization failure')
                return SimpleNamespace(context=c,plan=a,terminal_observation=dict(ownership=own,observed_ns=c['deadline_ns']+200000000,closed_ns=c['deadline_ns']),
                    start=lambda:None,poll=lambda:None,revoke_admission=lambda:None,live_summary=lambda:'',finish=failed,request_stop=lambda *a:None,_latch_cleanup=lambda *a:None)
            original=runtime.execute_stage_runtime
            @functools.wraps(original)
            def call(**kw):kw['run_dir']=root;return original(**kw)
            with patch.object(runtime,'execute_stage_runtime',new=call):result,args,_=_run_primary_with_aux(None,session_factory=factory,real_clock=True)
            w=result.stage_completion.stage_window
            assert result.stage_verdict=='pass' and w.storage_thermal_summary['auxiliary_outcome']=='ERROR'
            assert len(args['telemetry_times'])>=2
            w.storage_thermal_summary=copy.deepcopy(saved['terminal'])
            primary=publish(root,w);report=json.loads((root/'run_manifest.json').read_text())
            assert primary.overall_verdict=='pass' and report['storage_thermal_summary']['auxiliary_outcome']=='ERROR'
            assert 'finalization failure' in w.storage_thermal_summary['failure']
            print('  real finalization exception -> registered ERROR -> same-stage terminal replay: ERROR; primary PASS; elapsed',result.stage_elapsed,'telemetry',args['telemetry_times'])


def run_thermal_coordinator_authority_checks():
    import time,signal,subprocess
    from unittest.mock import patch
    from Modules.lvs_storage_thermal_launch import OwnedProcess
    from Modules.lvs_storage_thermal_stage import _UNCONFIRMED
    with tempfile.TemporaryDirectory() as work:
        root=Path(work);prepare(root/'launch')
        for mode in ('stop','timeout','already_reaped','lost_pidfd','concurrent_cancel'):
            if mode=='lost_pidfd' and not hasattr(os,'pidfd_open'):continue
            p=OwnedProcess([sys.executable,'-B','-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print("READY",flush=True);time.sleep(10)'],stdout=subprocess.PIPE)
            v=OwnedProcess([sys.executable,'-B','-c','import time;time.sleep(10)'])
            # Setup handshake belongs to the test, never primary stage startup.
            limit=time.monotonic()+2;data=b''
            while b'READY' not in data and time.monotonic()<limit:
                try:data+=os.read(p.stdout.fileno(),128)
                except BlockingIOError:time.sleep(.001)
            assert b'READY' in data
            original=p.pid;backup=None;oldfd=None
            session=ThermalStageSession(SimpleNamespace(id=mode,duration_seconds=2),dict(status='READY'),root/mode,
                recovery_marker=root/(mode+'-intent'),signal_group=lambda *a:(_ for _ in ()).throw(AssertionError('raw group signal invoked')))
            session.process=p
            try:
                p.pid=v.pid;p.pgid=v.pid  # public diagnostic attributes confer no authority
                try:p._creation.pgid=v.pid;raise AssertionError('Creation group is mutable')
                except AttributeError:pass
                if mode=='already_reaped':p.kill();p.wait(timeout=2)
                if mode=='lost_pidfd':
                    oldfd=p.pidfd;backup=os.dup(oldfd);os.close(oldfd);p.pidfd=None
                    session.end_stage();session.finish()
                    assert session.evidence['cleanup_confirmed'] is False
                    assert session.evidence['persistent_recovery_required'] is True
                    assert v.poll() is None
                    continue
                if mode=='timeout':
                    wait=p.wait;count=[0]
                    def delayed(timeout=None):
                        count[0]+=1
                        if count[0]==1:raise subprocess.TimeoutExpired('injected wait deadline',timeout)
                        return wait(timeout=timeout)
                    with patch.object(p,'wait',side_effect=delayed):session.finish()
                    assert p.returncode==-signal.SIGKILL
                elif mode=='concurrent_cancel':
                    import threading
                    threads=[threading.Thread(target=session.end_stage) for _ in range(8)]
                    for thread in threads:thread.start()
                    for thread in threads:thread.join(1)
                    assert not any(t.is_alive() for t in threads)
                else:session.end_stage()
                assert v.poll() is None,(mode,'unrelated child was signaled')
                if mode!='already_reaped' and p.poll() is None:p.kill()
                p.wait(timeout=2)
                assert v.poll() is None,(mode,'unrelated child was reaped')
                print('  coordinator',mode,'original exit',p.returncode,'unrelated child alive; owned identity preserved')
            finally:
                if backup is not None:
                    os.dup2(backup,oldfd);os.close(backup);p.pidfd=oldfd
                p.pid=original
                for child in (p,v):
                    if child.poll() is None:child.kill()
                    child.wait(timeout=2)
                    if child.stdout is not None:child.stdout.close()
                _UNCONFIRMED.pop(str(session.marker),None)
        # Re-run on a pidfd-capable installed interpreter if the project runtime
        # lacks these APIs, retaining the same actual coordinator call paths.
        host=Path('/usr/bin/python3')
        if not hasattr(os,'pidfd_open') and host.exists():
            probe=subprocess.run([str(host),'-c',"import os;raise SystemExit(not hasattr(os,'pidfd_open'))"],capture_output=True,timeout=5)
            if probe.returncode==0:
                result=subprocess.run([str(host),'-B','-c','from smoke_tests.storage_thermal_audit_matrix_checks import run_thermal_coordinator_authority_checks as check;check()'],
                    capture_output=True,text=True,timeout=30,env={**os.environ,'PYTHONPATH':str(ROOT),'PYTHONDONTWRITEBYTECODE':'1'})
                assert result.returncode==0,result.stdout+result.stderr
                print(result.stdout)
