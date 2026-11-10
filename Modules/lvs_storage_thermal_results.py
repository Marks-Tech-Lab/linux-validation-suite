"""Independent auxiliary outcomes; never evaluates primary hardware validation."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import os
import json
from uuid import uuid4

_ACTIVE_RUN = ContextVar("thermal_evidence_run", default=None)


@contextmanager
def evidence_run(run_dir):
    """Primary-owned, in-memory run authority; never reconstructed from JSON."""
    registry=dict(run_id=uuid4().hex,run_directory=os.path.abspath(run_dir),windows={})
    token=_ACTIVE_RUN.set(registry)
    try:yield registry
    finally:_ACTIVE_RUN.reset(token)


def run_identity(run_dir):
    run=_ACTIVE_RUN.get()
    return run["run_id"] if run and run["run_directory"]==os.path.abspath(run_dir) else None


def register_stage(window, session):
    run=_ACTIVE_RUN.get()
    if run is None:return
    if id(window) in run['windows']:raise ValueError('Stage authority is already registered')
    context=deepcopy(session.context)
    if context.get("run_id")!=run["run_id"] or context.get("run_directory")!=run["run_directory"]:
        raise ValueError("Stage authority does not belong to current run")
    readiness=deepcopy(session.plan);observation=deepcopy(session.terminal_observation)
    payload=deepcopy(getattr(window,'storage_thermal_summary',None))
    if not isinstance(payload,dict):raise ValueError('Primary final auxiliary disposition missing')
    errors=validate_terminal(payload,readiness,context,observation)
    if errors:payload['session_errors']=list(dict.fromkeys(list(payload.get('session_errors') or [])+errors))
    final=normalize(payload,readiness=readiness)
    run["windows"][id(window)]=(window,dict(context=context,readiness=readiness,
        observation=observation,final=dict(generation=uuid4().hex,
            material=_final_material(final),result=deepcopy(final))))
    window.storage_thermal_summary=deepcopy(final)


_FINAL_FIELDS = (
    'contract_id','contract_version','verdict','status','auxiliary_outcome',
    'requested','execution_started','operator_cancelled','configuration',
    'requested_stage_configuration','stage_window_shortened','execution_context','readiness','stage_readiness',
    'requested_devices','executed_devices','unexecuted_devices','blocked_devices','devices',
    'stage_launch_ownership','independent_launch_ownership','source_provenance','source_provenance_end',
    'parent_finalization_complete','cleanup_confirmed','terminal_published',
    'failure','adapter_error','publication_error','publication_integrity',
    'persistent_recovery_required','recovery_reason','recovery_publication_error',
    'evidence_errors','session_errors','rejected_terminal_evidence','supervisor_forced_kill',
    'admission_revocation_confirmed','admission_revocation_error',
    'primary_window_ended_monotonic','stage_deadline_monotonic',
)


def _final_material(payload):
    # This is an in-memory comparison, never a publication of nonfinite values.
    # Rejected raw observations can contain NaN; preserve their error disposition.
    return json.dumps({k:payload[k] for k in _FINAL_FIELDS if k in payload},
                      sort_keys=True,separators=(',',':'),allow_nan=True)


OUTCOMES = ('COMPLETED', 'COMPLETED_WITH_WARNINGS', 'NOT_RUN', 'STOPPED', 'ERROR')


def not_run(reason, *, requested=True, readiness=None):
    return normalize(dict(contract_id='lvs.storage_thermal.auxiliary_stage',contract_version=1,verdict='BLOCKED', status='not_run', requested=requested,
        execution_started=False, executed_devices=[], devices=[], cleanup_confirmed=True,
        terminal_published=True, reasons=[reason], readiness=readiness or {}))


def error_result(reason, *, readiness=None, cleanup_confirmed=True):
    return normalize(dict(contract_id='lvs.storage_thermal.auxiliary_stage',contract_version=1,verdict='INCOMPLETE', status='incomplete', requested=True,
        execution_started=True, executed_devices=[], devices=[], cleanup_confirmed=cleanup_confirmed,
        terminal_published=False, failure=str(reason), readiness=readiness or {}))


def _source_errors(value, expected, label, *, required=False):
    """Source-tree identity only; executable hashes and Git metadata differ."""
    if value is None and not required:return []
    source=value.get('source') if isinstance(value,dict) else None
    if (not isinstance(source,dict) or source.get('status')!='complete'
            or not isinstance(source.get('digest'),str) or not source['digest']):
        return ['Missing or invalid '+label+' source identity']
    errors=[]
    if isinstance(expected,dict) and expected:
        if source['digest']!=expected.get('digest'):errors.append(label+' source differs from authority')
        for key in ('scope','algorithm','file_count'):
            if key in source and key in expected and (type(source[key]) is not type(expected[key]) or source[key]!=expected[key]):
                errors.append(label+' source metadata differs from authority: '+key)
    return errors


def _rate_errors(row,configuration,planned,plan):
    """Resolved limits are authority; achieved throughput is an observation.

    V1 has no child-authorized adaptive rate protocol. A different rate needs a
    newly authorized effective plan before launch. Shortened duration keeps rates.
    """
    actual=row.get('effective_rate');expected=planned.get('rate')
    if not isinstance(expected,dict) or not expected:
        return ['Authoritative resolved rate missing: '+row['device_id']]
    if not isinstance(actual,dict) or json.dumps(actual,sort_keys=True)!=json.dumps(expected,sort_keys=True):
        return ['Effective device rate/read size differs from authoritative readiness: '+row['device_id']]
    if type(actual.get('block_size')) is not int or actual['block_size']!=(configuration or {}).get('block_size'):
        return ['Device read size differs from effective configuration']
    # The recorded command is supplementary evidence, not a new authorization.
    # Actual production readiness lists commands; a successful worker must retain
    # its fixed guard command whenever that expectation was recorded.
    command=row.get('command')
    required=any(c.get('device_id')==row['device_id'] for c in plan.get('commands',[]))
    if command is None:return ['Recorded fio guard configuration missing'] if required else []
    try:
        if not isinstance(command,list) or len(command)!=11 or command[1]!='--fio-fd':raise ValueError()
        if any(type(v) is not str for v in command):raise ValueError()
        values=[int(v) for v in command[2:]]
        if values[0]<3:raise ValueError()
        guard=row.get('guard_evidence') or {};identity=planned.get('identity') or {}
        if values[1:3]!=[guard.get('uid'),guard.get('gid')]:raise ValueError()
        if values[3:5]!=[identity.get('major'),identity.get('minor')]:raise ValueError()
        if identity.get('size_bytes') is not None and values[5]!=identity['size_bytes']:raise ValueError()
        if values[6:]!=[actual['block_size'],actual['effective_iops'],configuration['duration_seconds']]:raise ValueError()
        path=((plan.get('backend') or {}).get('guard') or {}).get('path')
        if path and command[0]!=path:raise ValueError()
    except (ValueError,KeyError,TypeError):return ['Recorded guard/fio command contradicts authoritative configuration']
    return []


def device_completion_errors(row,configuration,plan):
    from .lvs_storage_thermal import result_successful,device_timing_errors
    if not result_successful(row):return ['Device lacks strict successful terminal evidence: '+str(row.get('device_id') if isinstance(row,dict) else '?')]
    errors=[]
    expected={r['device_id']:r.get('identity') for r in plan.get('devices') or []}
    if row['identity']!=expected.get(row['device_id']):errors.append('Device identity conflicts with readiness: '+row['device_id'])
    planned=next((r for r in plan.get('devices',[]) if r.get('device_id')==row['device_id']),{})
    errors.extend(_rate_errors(row,configuration,planned,plan))
    errors.extend(device_timing_errors(row,(configuration or {}).get('duration_seconds')))
    if type(row.get('configured_duration_seconds')) is not int or row.get('configured_duration_seconds') != (configuration or {}).get('duration_seconds'):
        errors.append('Device configured duration differs from effective configuration')
    guard=row.get('guard_evidence')
    if not isinstance(guard,dict):errors.append('Missing native guard witnesses')
    else:
        for key,value in (('contract_id','lvs.storage_thermal.guard'),('contract_version',1),
                          ('readonly_direct',True),('seccomp',2),('capabilities',0),('no_new_privs',1)):
            if type(guard.get(key)) is not type(value) or guard.get(key)!=value:
                errors.append('Contradictory or missing native guard witness: '+key)
        for key in ('uid','gid'):
            if type(guard.get(key)) is not int or guard[key]<=0:errors.append('Invalid reduced guard identity: '+key)
        if guard.get('pid')!=row.get('pid'):errors.append('Guard identity differs from worker')
    backend=plan.get('backend') or {};observed=row.get('executable_provenance') or {}
    for name in ('fio','guard'):
        if backend.get(name) is not None and observed.get(name)!=backend[name]:errors.append('Executable provenance differs from current readiness: '+name)
    source=(plan.get('source_provenance') or {}).get('source') or {}
    errors.extend(_source_errors(row.get('source_provenance'),source,'Device',required=True))
    return errors


def successful_terminal_errors(payload, readiness=None):
    """Reconcile aggregate success against the authoritative device contract.

    This validates evidence, never changes underlying observations or primary
    verdicts. Blocked/nonselected and zero-rate rows need no execution record.
    """
    from .lvs_storage_thermal import result_successful
    if payload.get('verdict') not in ('PASS','WARN'): return []
    errors=[]
    configured=(payload.get('configuration') or {}).get('duration_seconds')
    if type(configured) is not int or configured<1:errors.append('Missing effective configured duration')
    if payload.get('requested') is False or payload.get('execution_started') is False:
        errors.append('Successful execution contradicts disabled/not-started evidence')
    if payload.get('parent_finalization_complete') is not True:
        errors.append('Aggregate success lacks complete parent finalization')
    rows=payload.get('devices')
    if not isinstance(rows,list) or not rows:
        return errors+['Aggregate success lacks executed device records']
    def ids(value, label):
        if (not isinstance(value,list) or any(not isinstance(v,str) or not v for v in value)
                or len(set(value))!=len(value)):
            errors.append(label+' must contain distinct stable device identities');return set()
        return set(value)
    executed=ids(payload.get('executed_devices'),'executed_devices')
    requested=ids(payload.get('requested_devices'),'requested_devices')
    recorded=[r.get('device_id') if isinstance(r,dict) else None for r in rows]
    records=ids(recorded,'device records')
    if not executed or executed!=records:errors.append('Executed identities conflict with device records')
    if not executed<=requested:errors.append('Executed devices were not requested')
    plan=readiness if readiness is not None else payload.get('stage_readiness') or payload.get('readiness') or {}
    planned=plan.get('devices') or []
    if not isinstance(planned,list) or any(not isinstance(r,dict) for r in planned):
        return errors+['Malformed readiness device evidence']
    ids([r.get('device_id') for r in planned],'readiness devices')
    selected={r.get('device_id') for r in planned if r.get('selected')}
    eligible={r.get('device_id') for r in planned if r.get('selected') and r.get('state') in ('ready','running','completed')}
    if requested!=selected:errors.append('Requested identities conflict with selected readiness coverage')
    if executed!=eligible:errors.append('Success does not reconcile all eligible devices')
    if payload.get('verdict')=='PASS' and any(r.get('selected') and r.get('state')=='blocked' for r in planned):
        errors.append('Unqualified PASS contradicts blocked requested coverage')
    for row in rows:errors.extend(device_completion_errors(row,payload.get('configuration'),plan))
    if payload.get('verdict')=='PASS' and any(r.get('temperature_status')!='monitored' or r.get('temperature_warning') for r in rows if isinstance(r,dict)):
        errors.append('Unqualified PASS contradicts limited/warning temperature coverage')
    if payload.get('unexecuted_devices'):errors.append('Success contains unexecuted eligible devices')
    return errors


def execution_facts(payload):
    """Facts cannot be negated by requested=false, BLOCKED, or started=false."""
    devices=payload.get('devices') or []
    ownership=payload.get('stage_launch_ownership') or {}
    return bool(payload.get('execution_started') is True or payload.get('executed_devices') or
        any(isinstance(d,dict) and (d.get('pid') or d.get('started_monotonic') is not None or
            d.get('exit_code') is not None or d.get('guard_evidence') or d.get('guard_confirmed') is True or any(d.get(k,0) for k in ('read_ios','read_bytes','errors')) or
            d.get('state') in ('running','completed','failed','cancelled','incomplete')) for d in devices) or
        any(w.get('io_admission')=='committed' or w.get('descriptor_offered') or w.get('launch_failed') or w.get('exit_code') not in (None,0) for w in ownership.get('workers',[])))


def ownership_errors(payload, context=None, expected=None):
    errors=[];ownership=payload.get('stage_launch_ownership')
    if ownership is None:
        return ['Missing native ownership evidence'] if expected is not None or context is not None and execution_facts(payload) else []
    if not isinstance(ownership,dict):return ['Malformed native ownership evidence']
    if ownership.get('protocol')!='lvs-storage-thermal-stage-admission-v2':errors.append('Unsupported native ownership protocol')
    if expected is not None and ownership!=expected:errors.append('Terminal ownership differs from independently published registry')
    if context is not None and ownership.get('lease_identity')!=context.get('lease_identity'):errors.append('Native ownership lease mismatch')
    workers=ownership.get('workers')
    if not isinstance(workers,list) or any(not isinstance(w,dict) for w in workers):return errors+['Malformed native worker registry']
    if ownership.get('cleanup_confirmed') is not True or any(w.get('cleanup_confirmed') is not True for w in workers):errors.append('Native ownership cleanup is unconfirmed')
    pids=[w.get('pid') for w in workers]
    if any(type(pid) is not int or pid<1 for pid in pids) or len(set(pids))!=len(pids):errors.append('Missing or duplicate native worker identity')
    devices=payload.get('devices') or []
    committed=[w for w in workers if w.get('io_admission')=='committed']
    if {w.get('pid') for w in committed}!={d.get('pid') for d in devices}:errors.append('Worker identities do not reconcile with device records')
    for w in workers:
        if w.get('launch_failed'):errors.append('Native bootstrap launch failed')
        if w.get('io_admission')!='committed':errors.append('Uncommitted native bootstrap cannot establish successful execution')
        d=next((d for d in devices if d.get('pid')==w.get('pid')),None)
        if w.get('phase')!='committed' or w.get('group_ready') is not True or w.get('descriptor_offered') is not True:
            errors.append('Native bootstrap phase/descriptor evidence is contradictory')
        if w.get('reaped') is not True or type(w.get('exit_code')) is not int:errors.append('Native worker reaping/exit evidence missing')
        if d is not None:
            if w.get('exit_code')!=d.get('exit_code'):errors.append('Native/device process exits disagree')
            stopped=d.get('state')=='cancelled' or d.get('safety_stop') is True
            if w.get('exit_code')!=0 and not stopped and payload.get('verdict') in ('PASS','WARN'):errors.append('Native worker exited unsuccessfully')
            guard=d.get('guard_evidence') or {}
            if d.get('state')=='completed' and guard.get('pid')!=w.get('pid'):errors.append('Guard PID does not match native owner')
        if context is not None:
            stamp=w.get('committed_monotonic_ns')
            if type(stamp) is not int or not context['started_ns']<=stamp<context['deadline_ns']:errors.append('Native admission outside authorized session')
            elif d is not None and isinstance(d.get('started_monotonic'),(int,float)) and d['started_monotonic']+.1<stamp/1e9:
                errors.append('Device start predates native admission')
    return errors


def validate_terminal(payload, readiness=None, context=None, observation=None):
    """One acceptance policy for normalization, session completion and run export."""
    if not isinstance(payload,dict):return ['Malformed terminal record']
    errors=[]
    readiness=readiness if readiness is not None else payload.get('stage_readiness') or payload.get('readiness') or {}
    if payload.get('contract_id') not in ('lvs.storage_thermal.manifest','lvs.storage_thermal.auxiliary_stage'):
        errors.append('Unrecognized storage completion contract')
    if type(payload.get('contract_version')) is not int or payload.get('contract_version')!=1:
        errors.append('Unsupported storage completion contract version')
    for key in ('requested','execution_started','operator_cancelled','stage_window_shortened'):
        if key in payload and type(payload[key]) is not bool:errors.append('Invalid boolean declaration: '+key)
    if payload.get('verdict') in ('PASS','WARN'):
        for key in ('requested','execution_started','cleanup_confirmed','terminal_published','parent_finalization_complete'):
            if type(payload.get(key)) is not bool:errors.append('Missing or invalid completion boolean: '+key)
    if payload.get('verdict') in ('PASS','WARN') and payload.get('status')!='completed':
        errors.append('Successful verdict contradicts completion status')
    if payload.get('auxiliary_outcome') not in (None,*OUTCOMES):errors.append('Unknown auxiliary outcome')
    errors+=successful_terminal_errors(payload,readiness)
    source=(readiness.get('source_provenance') or {}).get('source') or {}
    success=payload.get('verdict') in ('PASS','WARN') or any(d.get('state')=='completed' for d in payload.get('devices',[]))
    if success:errors.extend(_source_errors(readiness.get('source_provenance'),None,'Readiness',required=True))
    errors.extend(_source_errors(payload.get('source_provenance'),source,'Root initial',required=success))
    # V1 derived auxiliary records can omit the redundant endpoint. Its presence
    # never changes validation of the required initial/device/parent identities.
    errors.extend(_source_errors(payload.get('source_provenance_end'),source,'Root endpoint'))
    errors+=ownership_errors(payload,context,(observation or {}).get('ownership'))
    if context is None:return list(dict.fromkeys(errors))
    if payload.get('execution_context')!=context:errors.append('Completion does not belong to current run/stage/lease generation')
    independent=(observation or {}).get('ownership')
    if execution_facts(payload) or independent is not None and execution_facts({'stage_launch_ownership':independent}):
        if not execution_facts(payload):errors.append('Terminal omits independently observed execution')
        expected=(readiness or {}).get('configuration') or {};actual=payload.get('configuration') or {}
        if not isinstance(actual,dict):return errors+['Malformed execution configuration']
        omitted={'duration_seconds','unmonitored_approval'}
        if json.dumps({k:v for k,v in actual.items() if k not in omitted},sort_keys=True)!=json.dumps({k:v for k,v in expected.items() if k not in omitted},sort_keys=True):
            errors.append('Effective execution configuration differs from current authority')
        duration=actual.get('duration_seconds');requested=expected.get('duration_seconds',0)
        if type(duration) is not int or not 0<duration<=requested:errors.append('Execution duration outside current approved bounds')
        if type(duration) is int and duration<requested and payload.get('stage_window_shortened') is not True:
            errors.append('Shortened execution must report reduced coverage')
        from .lvs_storage_thermal import device_timing_errors
        rows={r.get('device_id'):r for r in (readiness or {}).get('devices',[]) if r.get('selected')}
        for d in payload.get('devices') or []:
            expected_row=rows.get(d.get('device_id'))
            if not expected_row or d.get('identity')!=expected_row.get('identity'):errors.append('Execution identity differs from current selected device')
            if d.get('state')=='completed':
                if payload.get('verdict') not in ('PASS','WARN'):errors.extend(device_completion_errors(d,actual,readiness or {}))
                errors.extend(device_timing_errors(d,duration,context,(observation or {}).get('observed_ns'),(observation or {}).get('closed_ns'),
                    next((w.get('committed_monotonic_ns') for w in (payload.get('stage_launch_ownership') or {}).get('workers',[]) if w.get('pid')==d.get('pid')),None)))
        if observation is not None and observation.get('ownership') is None:errors.append('Independently published native ownership missing')
    return list(dict.fromkeys(errors))


def session_errors(payload, readiness, context, observation=None):
    return validate_terminal(payload,readiness,context,observation)


def _outcome(payload, requested, *, device=False):
    if payload.get('auxiliary_outcome')=='ERROR' or payload.get('publication_integrity') is False or payload.get('publication_error'):return 'ERROR'
    devices = payload.get('devices') or []
    facts=execution_facts(payload)
    ownership=payload.get('stage_launch_ownership') or {}
    if ownership.get('cleanup_confirmed') is False or ownership.get('publication_error') or ownership.get('revocation_error'):return 'ERROR'
    if payload.get('evidence_errors') or payload.get('session_errors'):return 'ERROR'
    if facts and (not requested or payload.get('execution_started') is False or not payload.get('executed_devices') or payload.get('verdict')=='BLOCKED'):return 'ERROR'
    if any((d.get('state') in ('failed','incomplete') or d.get('exit_code') not in (None,0))
           and not (d.get('safety_stop') or d.get('state')=='cancelled') for d in devices):return 'ERROR'
    if payload.get('verdict') in ('PASS','WARN'):
        if device:
            from .lvs_storage_thermal import result_successful
            if not devices or any(not result_successful(d) for d in devices):return 'ERROR'
        elif successful_terminal_errors(payload):return 'ERROR'
    if payload.get('cleanup_confirmed') is False or payload.get('terminal_published') is False:
        return 'ERROR'
    if payload.get('failure') or any(d.get('errors', 0) or d.get('forced_kill') or d.get('shutdown_timed_out')
            or not d.get('cleanup_confirmed') or not d.get('terminal_published') for d in devices):
        return 'ERROR'
    if any(any(term in str(d.get('stop_reason','')).lower() for term in ('provider unavailable','activity evidence missing','worker evidence invalid','log exceeded bound')) for d in devices):
        return 'ERROR'
    if payload.get('auxiliary_outcome')=='STOPPED':return 'STOPPED'
    if any(d.get('safety_stop') or d.get('state')=='cancelled' for d in devices) or payload.get('operator_cancelled'):
        return 'STOPPED'
    if payload.get('verdict') in ('PASS','WARN','FAIL','INCOMPLETE') and not payload.get('executed_devices'):
        return 'ERROR'
    if not requested or payload.get('execution_started') is False or not payload.get('executed_devices'):
        return 'NOT_RUN' if not payload.get('execution_started') else 'ERROR'
    verdict = payload.get('verdict')
    if verdict == 'PASS':return 'COMPLETED_WITH_WARNINGS' if payload.get('stage_window_shortened') else 'COMPLETED'
    if verdict == 'WARN':return 'COMPLETED_WITH_WARNINGS'
    return 'ERROR'


def normalize(payload, *, requested=None, readiness=None):
    """Keep original verdict/counters intact; add independent operator outcomes."""
    result = deepcopy(payload)
    if readiness is not None:result['stage_readiness'] = deepcopy(readiness)
    if requested is None:requested = result.get('requested', True)
    result['requested'] = requested
    if readiness is not None and not result.get('readiness'):result['readiness']=deepcopy(readiness)
    errors=validate_terminal(result,readiness=readiness)
    if errors:result['evidence_errors']=list(dict.fromkeys(list(result.get('evidence_errors') or [])+errors))
    result['auxiliary_outcome'] = _outcome(result, requested)
    result['heating_effectiveness'] = 'not_accepted'
    result['primary_validation_gating'] = False
    plan = result.get('stage_readiness') or result.get('readiness') or {}
    rows = plan.get('devices') or []
    executed = {d['device_id']:d for d in result.get('devices',[]) if d.get('device_id')}
    result['coverage'] = dict(
        discovered=[d['device_id'] for d in rows],
        selected=[d['device_id'] for d in rows if d.get('selected')],
        eligible=[d['device_id'] for d in rows if d.get('state') in ('ready','running','completed')],
        exercised=list(result.get('executed_devices') or []),
        excluded=[dict(device_id=d['device_id'], reasons=d.get('reasons',[]), state=d.get('state'))
                  for d in rows if not d.get('selected') or d.get('state') in ('blocked','skipped')])
    if result.get('session_errors'):
        result['coverage']['claimed_exercised']=result['coverage']['exercised']
        result['coverage']['exercised']=[]
    result['drive_outcomes'] = []
    for identity in dict.fromkeys([d['device_id'] for d in rows]+list(executed)):
        drive = deepcopy(executed.get(identity) or {})
        row = next((d for d in rows if d['device_id']==identity), {})
        if drive:
            drive_result=dict(devices=[drive],executed_devices=[identity],verdict='PASS' if drive.get('state')=='completed' else 'INCOMPLETE')
            if (drive.get('temperature_status')!='monitored' or drive.get('temperature_warning')) and drive_result['verdict']=='PASS':drive_result['verdict']='WARN'
            device_errors=device_completion_errors(drive,result.get('configuration'),plan) if drive.get('state')=='completed' else []
            outcome='ERROR' if result.get('session_errors') or device_errors else _outcome(drive_result, True, device=True)
        else:outcome='NOT_RUN';device_errors=[]
        result['drive_outcomes'].append(dict(device_id=identity,auxiliary_outcome=outcome,
            selected=bool(row.get('selected')), reasons=row.get('reasons',[]),evidence_errors=device_errors,
            execution={k:drive.get(k) for k in ('state','read_ios','read_bytes','errors','stop_reason',
                'started_monotonic','ended_monotonic','effective_rate','fio_activity','fio_cpu',
                'temperature_status','temperature_start_c','temperature_end_c','temperature_peak_c',
                'cleanup_confirmed','terminal_published')},
            configured_rate=row.get('rate',{})))
    return result


def summarize_run(windows, *, run_dir=None):
    stages=[];seen=set();seen_windows=set();seen_finals=set();run=_ACTIVE_RUN.get()
    windows=list(windows)
    submitted={id(w) for w in windows}
    omitted=[a[0] for key,a in (run['windows'].items() if run else ()) if key not in submitted]
    windows.extend(omitted)
    for window in windows:
        payload=getattr(window,'storage_thermal_summary',None)
        if payload is None:payload=not_run('Thermal Assist disabled',requested=False)
        authority=run['windows'].get(id(window)) if run else None
        errors=['Registered stage result omitted from whole-run submission'] if id(window) not in submitted else []
        if id(window) in seen_windows:errors.append('Duplicate current stage window')
        seen_windows.add(id(window))
        if authority or execution_facts(payload) or payload.get('verdict') in ('PASS','WARN'):
            if (not authority or authority[0] is not window or run_dir is not None and
                    run['run_directory']!=os.path.abspath(run_dir)):
                errors.append('No current-run primary registration for stage evidence')
            else:
                a=authority[1];c=a['context'];key=c.get('session_id')
                if key in seen:errors.append('Duplicate stage/session result')
                seen.add(key)
                if c.get('stage_id')!=window.stage_id or c.get('run_id')!=run['run_id']:errors.append('Stage/run registration mismatch')
                if abs(c['started_ns']/1e9-window.started_monotonic)>.1:errors.append('Registered stage timeline differs from current window')
                errors+=validate_terminal(payload,a['readiness'],c,a['observation'])
                final=a.get('final')
                if (not isinstance(final,dict) or not isinstance(final.get('generation'),str)
                        or not final['generation'] or not isinstance(final.get('result'),dict)
                        or final.get('material')!=_final_material(final['result'])):
                    errors.append('Missing or inconsistent primary final disposition')
                else:
                    if final['generation'] in seen_finals:errors.append('Duplicate primary final disposition')
                    seen_finals.add(final['generation'])
                    candidate=normalize(payload,readiness=a['readiness'])
                    if _final_material(candidate)!=final['material']:
                        submitted_payload=deepcopy(payload)
                        payload=deepcopy(final['result'])
                        previous_rejection=submitted_payload.get('rejected_terminal_evidence')
                        payload['rejected_terminal_evidence']=previous_rejection if isinstance(previous_rejection,dict) else submitted_payload
                        errors.append('Submitted evidence conflicts with primary final disposition')
                    payload=dict(payload,final_disposition_generation=final['generation'])
        if errors:
            rejected=payload.get('rejected_terminal_evidence')
            payload=dict(payload,session_errors=list(dict.fromkeys(list(payload.get('session_errors') or [])+errors)),
                rejected_terminal_evidence=deepcopy(rejected if isinstance(rejected,dict) else payload))
        normalized=normalize(payload,readiness=authority[1]['readiness'] if authority else None)
        window.storage_thermal_summary=normalized
        compact={key:normalized.get(key) for key in ('auxiliary_outcome','requested','coverage',
            'drive_outcomes','failure','reasons','cleanup_confirmed','terminal_published',
            'final_disposition_generation','evidence_directory','post_primary_shutdown_seconds','stage_session_seconds','evidence_errors','session_errors','rejected_terminal_evidence')}
        stages.append(dict(stage_id=window.stage_id,display_name=window.display_name,result=compact))
    counts=Counter(s['result']['auxiliary_outcome'] for s in stages)
    requested=[s['result'] for s in stages if s['result']['requested']]
    outcomes={s['result']['auxiliary_outcome'] for s in stages
              if s['result']['requested'] or s['result']['auxiliary_outcome']=='ERROR'}
    overall=('ERROR' if 'ERROR' in outcomes else 'STOPPED' if 'STOPPED' in outcomes else
        'COMPLETED_WITH_WARNINGS' if 'COMPLETED_WITH_WARNINGS' in outcomes or
            ('COMPLETED' in outcomes and 'NOT_RUN' in outcomes) else
        'COMPLETED' if 'COMPLETED' in outcomes else 'NOT_RUN')
    return dict(contract_id='lvs.storage_thermal.auxiliary_summary',contract_version=1,
        auxiliary_outcome=overall,primary_validation_gating=False,
        stage_outcome_counts={key:counts[key] for key in OUTCOMES},stages=stages,
        heating_effectiveness='not_accepted',storage_integrity='not_tested')


def summary_text(summary):
    lines=[f"Storage Thermal Assist (independent auxiliary): {summary['auxiliary_outcome']}",
           'Does not determine CPU/GPU/RAM validation PASS/FAIL.']
    for stage in summary['stages']:
        r=stage['result']
        lines.append(f"{stage['display_name']}: {r['auxiliary_outcome']}; exercised {len(r['coverage']['exercised'])} drive(s)")
        for d in r['drive_outcomes']:
            e=d['execution'];lines.append(f"  {d['device_id']}: {d['auxiliary_outcome']}; reads={e.get('read_ios',0)}; bytes={e.get('read_bytes',0)}; peak={e.get('temperature_peak_c')} C; reasons={d['reasons']}; stop={e.get('stop_reason','')}")
        if r.get('failure'):lines.append('  '+r['failure'])
        lines.extend('  Evidence error: '+e for e in (r.get('evidence_errors') or []))
        lines.extend('  '+s for s in (r.get('reasons') or []))
    if summary.get('publication_error'):lines.append('Auxiliary reporting error: '+summary['publication_error'])
    lines.append('Read activity does not establish heating effectiveness or storage integrity.')
    return '\n'.join(lines)+'\n'


def reporting_error(phase, exc):
    """Literal, JSON-safe fallback independent of normalization/rendering code."""
    try: detail = str(exc)[:2000]
    except Exception: detail = 'Exception detail unavailable'
    return dict(contract_id='lvs.storage_thermal.auxiliary_summary', contract_version=1,
        auxiliary_outcome='ERROR', primary_validation_gating=False, stages=[],
        stage_outcome_counts={}, publication_integrity=False,
        publication_error=phase+': '+type(exc).__name__+': '+detail,
        heating_effectiveness='not_accepted', storage_integrity='not_tested')


def reporting_error_text(summary):
    return ('Storage Thermal Assist (independent auxiliary): ERROR\n'
            'Does not determine CPU/GPU/RAM validation PASS/FAIL.\n'
            +summary['publication_error']+'\nAuxiliary observations unavailable; no thermal success claimed.\n')


def publish_run_summary(run_dir, summary, publish=None):
    """Auxiliary report failures never throw into primary run publication."""
    from pathlib import Path
    from .lvs_profile_report_artifacts import atomic_preflight_json
    result=deepcopy(summary)
    result.setdefault('publication_integrity',True)
    try:
        # A disabled/unavailable auxiliary has no critical worker evidence to
        # duplicate. Its complete NOT_RUN remains in the primary manifest/text.
        from .lvs_storage_thermal_launch import ready
        if not ready() and result.get('auxiliary_outcome')=='NOT_RUN':
            result['separate_auxiliary_artifacts']='not_written; launcher unavailable; primary manifest is authority'
            return result
        # Render faults remain contained; filesystem latency runs in a child.
        rendered=summary_text(result)
        if publish is not None:
            # Explicit injectable publisher is used only by isolated unit tests.
            publish(Path(run_dir)/'storage_thermal_summary.json',result)
        else:
            from .lvs_storage_thermal_recovery import evidence_operation
            evidence_operation('--publish-summary',run_dir,payload=dict(summary=result,text=rendered))
    except Exception as exc:
        result.update(auxiliary_outcome='ERROR',publication_integrity=False,publication_error=str(exc))
    return result


def readiness_lines(report):
    """Separate non-gating coverage display, collapsed across unchanged stages."""
    import json
    groups={}
    for stage in report.get('plan',[]):
        plan=stage.get('storage_thermal')
        if not stage.get('enabled',True) or not plan:continue
        reasons=list(plan.get('reasons') or [])
        if plan.get('backend',{}).get('status')!='available':reasons+=plan.get('backend',{}).get('reasons') or []
        for d in plan.get('devices',[]):
            if d.get('selected') and d.get('reasons'):reasons.append(d['device_id']+': '+'; '.join(d['reasons']))
        permitted=plan.get('execution_permitted',False)
        if plan.get('requires_consent') and not permitted:reasons.append('Bounded unmonitored approval missing or declined; primary validation may continue without storage')
        outcome='READY (execution pending)' if permitted else 'NOT_RUN'
        entry=dict(outcome=outcome,selection=plan.get('configuration',{}).get('selection'),
                   eligible=plan.get('runnable_devices',[]),excluded=plan.get('blocked_devices',[]),reasons=reasons)
        key=json.dumps(entry,sort_keys=True)
        groups.setdefault(key,dict(entry,count=0))['count']+=1
    if not groups:return []
    lines=['Storage Thermal Assist — independent, non-gating:']
    for g in groups.values():
        lines.append(f"  {g['count']} stage(s): {g['outcome']}; eligible {len(g['eligible'])}, excluded {len(g['excluded'])}; selection={g['selection']}")
        lines.extend('    '+reason for reason in dict.fromkeys(g['reasons']))
    return lines
