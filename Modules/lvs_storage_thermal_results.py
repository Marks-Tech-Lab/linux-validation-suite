"""Independent auxiliary outcomes; never evaluates primary hardware validation."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

OUTCOMES = ('COMPLETED', 'COMPLETED_WITH_WARNINGS', 'NOT_RUN', 'STOPPED', 'ERROR')


def not_run(reason, *, requested=True, readiness=None):
    return normalize(dict(verdict='BLOCKED', status='not_run', requested=requested,
        execution_started=False, executed_devices=[], devices=[], cleanup_confirmed=True,
        terminal_published=True, reasons=[reason], readiness=readiness or {}))


def error_result(reason, *, readiness=None, cleanup_confirmed=True):
    return normalize(dict(verdict='INCOMPLETE', status='incomplete', requested=True,
        execution_started=True, executed_devices=[], devices=[], cleanup_confirmed=cleanup_confirmed,
        terminal_published=False, failure=str(reason), readiness=readiness or {}))


def _outcome(payload, requested):
    devices = payload.get('devices') or []
    if payload.get('cleanup_confirmed') is False or payload.get('terminal_published') is False:
        return 'ERROR'
    if payload.get('failure') or any(d.get('errors', 0) or d.get('forced_kill') or d.get('shutdown_timed_out')
            or not d.get('cleanup_confirmed') or not d.get('terminal_published') for d in devices):
        return 'ERROR'
    if any(any(term in str(d.get('stop_reason','')).lower() for term in ('provider unavailable','activity evidence missing','worker evidence invalid','log exceeded bound')) for d in devices):
        return 'ERROR'
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
    result.setdefault('contract_id','lvs.storage_thermal.auxiliary_stage')
    result.setdefault('contract_version',1)
    if readiness is not None:result['stage_readiness'] = deepcopy(readiness)
    if requested is None:requested = result.get('requested', True)
    result['requested'] = requested
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
    result['drive_outcomes'] = []
    for identity in dict.fromkeys([d['device_id'] for d in rows]+list(executed)):
        drive = deepcopy(executed.get(identity) or {})
        row = next((d for d in rows if d['device_id']==identity), {})
        if drive:
            drive_result=dict(devices=[drive],executed_devices=[identity],verdict='PASS' if drive.get('state')=='completed' else 'INCOMPLETE')
            if (drive.get('temperature_status')!='monitored' or drive.get('temperature_warning')) and drive_result['verdict']=='PASS':drive_result['verdict']='WARN'
            outcome=_outcome(drive_result, True)
        else:outcome='NOT_RUN'
        result['drive_outcomes'].append(dict(device_id=identity,auxiliary_outcome=outcome,
            selected=bool(row.get('selected')), reasons=row.get('reasons',[]),
            execution={k:drive.get(k) for k in ('state','read_ios','read_bytes','errors','stop_reason',
                'started_monotonic','ended_monotonic','effective_rate','fio_activity','fio_cpu',
                'temperature_status','temperature_start_c','temperature_end_c','temperature_peak_c',
                'cleanup_confirmed','terminal_published')},
            configured_rate=row.get('rate',{})))
    return result


def summarize_run(windows):
    stages=[]
    for window in windows:
        payload=getattr(window,'storage_thermal_summary',None)
        if payload is None:payload=not_run('Thermal Assist disabled',requested=False)
        normalized=normalize(payload)
        compact={key:normalized.get(key) for key in ('auxiliary_outcome','requested','coverage',
            'drive_outcomes','failure','reasons','cleanup_confirmed','terminal_published',
            'evidence_directory','post_primary_shutdown_seconds','stage_session_seconds')}
        stages.append(dict(stage_id=window.stage_id,display_name=window.display_name,result=compact))
    counts=Counter(s['result']['auxiliary_outcome'] for s in stages)
    requested=[s['result'] for s in stages if s['result']['requested']]
    outcomes={s['auxiliary_outcome'] for s in requested}
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
        # The main manifest is final authority, including publication failures.
        observations=summary_text(result).splitlines()[1:]
        (Path(run_dir)/'storage_thermal_summary.txt').write_text(
            'Storage Thermal Assist observations\nAuthority: run_manifest.json storage_thermal_summary\n'+'\n'.join(observations)+'\n')
        (publish or atomic_preflight_json)(Path(run_dir)/'storage_thermal_summary.json',result)
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
