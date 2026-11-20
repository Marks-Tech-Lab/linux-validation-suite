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


def prepare(profile, manager, authorize):
    """After final confirmation/overrides, before handing work to any run thread.

    Existing authenticated runtime remains the only supported transport in this
    step. Missing runtime never triggers sudo or an installation fallback.
    """
    from .lvs_storage_thermal import stage_config
    from .lvs_storage_thermal_runtime import inspect
    from .lvs_storage_thermal_runtime import preview as execution_readiness
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Thermal Assist preparation requires the frontend thread')
    previous=profile.__dict__.pop('_thermal_execution_preparation', {})
    if previous.get('lease') is not None:previous['lease'].close()
    if manager is not None:manager.thermal_source_approval=''
    plans = {}
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
            plans[identity] = execution_readiness(stage_config(stage))
            plans[identity]['execution_ready'] = True
            plans[identity]['requires_consent'] = bool(
                plans[identity].get('status') == 'READY' and
                stage_config(stage).monitoring == 'approved_unmonitored')
        except (OSError, ValueError, RuntimeError) as exc:
            plans[identity] = blocked(plans[identity], str(exc))
    if authorized and lease is None and any(p.get('status')=='READY'and(p.get('installed_runtime')or{}).get('runtime_mode')=='lvs.thermal.transient.data.v1'for p in plans.values()):
        try:
            from .lvs_storage_thermal_transient import Hold
            lease=Hold()
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
