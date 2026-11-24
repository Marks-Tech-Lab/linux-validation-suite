"""Run-local frontend preparation; no installer, elevation or service startup.

Only the foreground frontend supplies interactive authorization. Execution consumes
one configuration-bound preparation; passive previews never load a bootstrap.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import threading

_PLANS = ContextVar('thermal_execution_plans', default=None)


def key(stage):
    from .lvs_storage_thermal import stage_config
    return json.dumps(stage_config(stage).to_dict(), sort_keys=True)


def schedule(profile):
    # Bind stage order/count and enabled scope as well as individual settings.
    return [key(stage) if getattr(stage, 'enabled', False) and
            getattr(getattr(stage.modules, 'storage_thermal', None), 'enabled', False)
            else None for stage in getattr(profile, 'stages', ())]


def blocked(plan, reason):
    value = deepcopy(plan)
    value.update(status='BLOCKED', execution_ready=False, inspection_only=False,
                 preparation_required=False, commands=[], runnable_devices=[])
    value['reasons'] = list(value.get('reasons') or []) + [reason]
    return value


def release_preparation(profile):
    """Discard one-use preparation and close liveness only; never certify CLEAN."""
    receipt = profile.__dict__.pop('_thermal_execution_preparation', {})
    if receipt.get('lease') is not None:
        receipt['lease'].close()


def preparation_text(profile, plans):
    """Pure presentation of final effective plans; no inspection or authorization."""
    from .lvs_storage_thermal_results import storage_thermal_access_text
    from .lvs_storage_thermal_configuration import drive_label
    groups = {}
    for index, stage in enumerate(profile.stages, 1):
        if stage.enabled and stage.modules.storage_thermal.enabled:
            groups.setdefault(key(stage), []).append(str(index))
    if not groups:
        return ''
    lines = ['Thermal Assist preparation review — no workloads started.',
             'These results do not determine primary CPU/GPU/RAM PASS/FAIL.']
    for identity, stages in groups.items():
        plan = plans.get(identity) or {}
        config = json.loads(identity)
        authoritative = plan.get('execution_ready') is True
        backend_available = plan.get('backend', {}).get('status') == 'available'
        global_blocker = plan.get('status') != 'READY' and (
            plan.get('eligibility_status') == 'ELIGIBLE' or
            any(d.get('selected') and d.get('state') == 'ready' for d in plan.get('devices', [])))
        prepared = authoritative and backend_available and not global_blocker
        ready = list(plan.get('runnable_devices') or []) if prepared and plan.get('status') == 'READY' else []
        excluded = list(plan.get('blocked_devices') or [])
        names = {r['device_id']: drive_label(r) for r in plan.get('targets', []) if r.get('model')}
        def named(devices):return ', '.join(names.get(d, d) for d in devices) or '(none)'
        outcome = ('PREPARATION FAILED / UNAVAILABLE' if not prepared else
                   'ZERO ELIGIBLE DRIVES — Thermal Assist NOT_RUN' if not ready else
                   'PARTIAL COVERAGE — listed eligible subset only' if excluded or plan.get('partial_coverage') else
                   'ELIGIBLE TARGETS — execution pending')
        lines += [f"Stage(s) {', '.join(stages)}: {outcome}",
                  '  Access contract: ' + storage_thermal_access_text(config['access_mode']),
                  ('  Authoritative readiness inspection completed.' if prepared else
                   '  Executable readiness unavailable; no hardware rejection is implied.'),
                  f"  {config['duration_seconds']}s per stage; monitoring={config['monitoring']}; "
                  f"stop={config['temperature_limit_c'] if config['temperature_limit_c'] is not None else 'device-derived'} C; "
                  f"aggregate={config['aggregate_iops_limit'] if config['aggregate_iops_limit'] is not None else 'unset'} IOPS / "
                  f"{config['aggregate_bps_limit'] if config['aggregate_bps_limit'] is not None else 'unset'} B/s",
                  f"  Eligible ({len(ready)}): {named(ready)}",
                  f"  Excluded requested targets ({len(excluded)}): {named(excluded)}"]
        lines.append(f"  Requested: {config['block_size']} byte reads, QD{config['queue_depth']}; "
                     f"{config['rate_mode']}, ordinary {config['intensity_percent']}% / system {config['system_intensity_percent']}%")
        for row in plan.get('targets', []):
            if row['device_id'] in ready:
                rate = row.get('rate') or {}
                lines.append(f"  {names.get(row['device_id'], row['device_id'])}: planned {rate.get('effective_iops', 'unavailable')} IOPS / "
                             f"{rate.get('effective_bps', 'unavailable')} B/s (not achieved activity)")
        reasons = list(plan.get('reasons') or [])
        if not backend_available:reasons += plan.get('backend', {}).get('reasons') or []
        reasons += [names.get(d['device_id'], d['device_id']) + ': ' + '; '.join(d.get('reasons') or [])
                    for d in plan.get('devices', []) if d.get('selected') and d.get('reasons')]
        if not plan:reasons.append('No final preparation result for this effective configuration.')
        lines.extend('  ' + reason for reason in dict.fromkeys(reasons))
    lines += ['Continue approves only the listed eligible subset, subject to existing coverage consent, '
              'final admission and revalidation. No new system or unmonitored authorization is granted.',
              'Workload limits do not bound all initialization, kernel or other application I/O.',
              '1. Continue run (primary validation can continue with Thermal Assist unavailable)',
              '2. Return to setup — readiness only / cancel launch [default]; release runtime hold']
    return '\n'.join(lines)


def prepare(profile, manager, authorize):
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Thermal Assist preparation requires the frontend thread')
    try:
        return _prepare(profile, manager, authorize)
    except BaseException:
        release_preparation(profile)
        raise


def _prepare(profile, manager, authorize):
    """After final confirmation/overrides, before handing work to any run thread.

    Authoritative inspection uses the authenticated runtime. On-demand startup
    requires foreground exact-source approval and the existing privilege manager;
    passive configuration/inspection never performs this work.
    """
    from .lvs_storage_thermal import stage_config
    from .lvs_storage_thermal_runtime import inspect
    from .lvs_storage_thermal_runtime import preview as execution_readiness
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Thermal Assist preparation requires the frontend thread')
    release_preparation(profile)
    if manager is not None:manager.thermal_source_approval=''
    plans = {}
    for stage in profile.stages:
        stage.modules.storage_thermal.__dict__.pop('_resolved_aggregate_limits', None)
    for stage in profile.stages:
        if stage.enabled and getattr(stage.modules.storage_thermal, 'enabled', False):
            config = stage_config(stage)
            try:
                plans[key(stage)] = inspect(config)
                plans[key(stage)]['requires_consent'] = False
            except (OSError, ValueError, RuntimeError) as exc:
                plans[key(stage)] = blocked(dict(configuration=config.to_dict(),
                    devices=[], targets=[], selected_devices=[], blocked_devices=[],
                    backend=dict(status='unavailable'), requires_consent=False), str(exc))
    ready = any(p.get('status') in {'READY', 'DEFERRED'} for p in plans.values())
    startup=any(p.get('on_demand_startup')for p in plans.values());approval=None;lease=None
    if startup and ready:
        try:
            from .lvs_storage_thermal_transient import prepare_candidate,approval_text
            approval=prepare_candidate()
            if manager is None:raise ValueError('Privilege manager unavailable')
            manager.thermal_source_approval=approval_text(approval)
        except (OSError,ValueError,RuntimeError)as exc:
            plans={k:blocked(p,str(exc))for k,p in plans.items()};ready=False
    authorized = False
    reason = 'Thermal Assist execution authorization unavailable or declined'
    if ready:
        try:
            authorized = bool(manager is not None and (
                (not startup and manager.sudo_noninteractive_ready()) or (authorize is not None and authorize())))
            if authorized:
                manager.start_keepalive()
        except (OSError, RuntimeError) as exc:
            reason = 'Thermal Assist authorization unavailable: ' + str(exc)
    if authorized and startup:
        try:
            from .lvs_storage_thermal_transient import start_and_hold
            lease=start_and_hold(approval)
            profile._thermal_execution_preparation = dict(lease=lease)
        except (OSError,ValueError,RuntimeError)as exc:
            authorized=False;reason=str(exc)
    for stage in profile.stages:
        if not stage.enabled or not getattr(stage.modules.storage_thermal, 'enabled', False):
            continue
        identity = key(stage)
        if plans[identity].get('status') not in {'READY', 'DEFERRED'}:
            continue
        if not authorized:
            plans[identity] = blocked(plans[identity], reason)
            continue
        try:
            plan = execution_readiness(stage_config(stage))
            if getattr(stage.modules.storage_thermal, 'budget_mode', 'manual') == 'automatic':
                from .lvs_storage_thermal_configuration import automatic_limits
                limits = automatic_limits(stage_config(stage), plan)
                if limits is not None:
                    stage.modules.storage_thermal._resolved_aggregate_limits = limits
                    plan = execution_readiness(stage_config(stage))
                else:
                    plan = blocked(plan, 'Automatic budgets unresolved: no qualified monitored nonzero-rate data targets')
                identity = key(stage)
            plans[identity] = plan
            plans[identity]['execution_ready'] = True
            plans[identity]['requires_consent'] = bool(
                plans[identity].get('status') == 'READY' and
                stage_config(stage).monitoring == 'approved_unmonitored')
        except (OSError, ValueError, RuntimeError) as exc:
            plans[key(stage)] = blocked(plans.get(identity, {}), str(exc))
    plans = {identity: plans[identity] for identity in schedule(profile) if identity is not None}
    if authorized and lease is None and any(p.get('status')=='READY'and(p.get('installed_runtime')or{}).get('runtime_mode')=='lvs.thermal.transient.data.v1'for p in plans.values()):
        try:
            from .lvs_storage_thermal_transient import Hold
            lease=Hold()
            profile._thermal_execution_preparation = dict(lease=lease)
        except OSError as exc:plans={k:blocked(p,str(exc))for k,p in plans.items()}
    if lease is not None and not any(p.get('status')=='READY'for p in plans.values()):
        lease.close();lease=None  # unavailable storage must not pin an idle root helper
    profile._thermal_execution_preparation = dict(stages=schedule(profile), plans=deepcopy(plans),lease=lease)
    return deepcopy(plans)


@contextmanager
def execution_scope(profile, preparation=None):
    # One execution only. Changes to effective configuration cannot reuse a plan.
    receipt = profile.__dict__.pop('_thermal_execution_preparation', {}) if preparation is None else preparation
    plans = receipt.get('plans', {}) if receipt.get('stages') == schedule(profile) else {}
    token = _PLANS.set(plans)
    try:
        yield
    finally:
        _PLANS.reset(token)
        if receipt.get('lease') is not None:receipt['lease'].close()


def execution_plan(stage):
    plans = _PLANS.get()
    if plans is None:
        return None
    from .lvs_storage_thermal import stage_config
    return deepcopy(plans.get(key(stage)) or dict(status='BLOCKED', execution_ready=False,
        configuration=stage_config(stage).to_dict(),
        requires_consent=False, devices=[], targets=[], selected_devices=[], runnable_devices=[], blocked_devices=[], commands=[],
        backend=dict(status='unavailable'), reasons=['Final run-local Thermal Assist preparation missing or configuration changed']))
