"""Shared operator configuration, with no privileged inspection or workload I/O."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation

GROUP_LABELS = ('All eligible internal data drives', 'SATA/SAS data drives', 'NVMe data drives',
                'Hard disks', 'Solid-state drives', 'Choose physical drives…')


def drive_choices():
    # Exclusive discovery is passive: sysfs/udev/mount metadata only. It does
    # not perform shared dm-crypt ioctl qualification or read temperatures.
    from .lvs_storage_thermal_targets import TargetResolver
    rows = TargetResolver().discover()
    return [r for r in rows if r['internal'] and not r['excluded_automatic']
            and r['device_id'].startswith(('wwn:', 'serial:'))]


def drive_label(row):
    size = row.get('identity', {}).get('size_bytes', 0) / 1024**3
    role = 'System — excluded' if row.get('system_drive') is True else 'Data' if row.get('system_drive') is False else 'System status unknown'
    node = str(row.get('identity', {}).get('path', '')).rsplit('/', 1)[-1]
    return (f'{node} · ' if node else '') + f"{str(row.get('model') or 'Unidentified drive')[:28]} · {size:.0f} GiB · {role}"


def fields(stage, section='thermal', rows=()):
    from types import SimpleNamespace
    from .lvs_storage_thermal import GROUPS
    m = stage.modules.storage_thermal
    def item(key, label, value, options=(), labels=()):
        return SimpleNamespace(key='thermal_ui_'+key, label=label, module='storage_thermal', attribute=key, value=value, options=tuple(options), option_labels=tuple(labels))
    if section in ('thermal_drives','thermal_per_drive'):
        result = []
        known = {r['device_id'] for r in rows}
        rows = list(rows) + [dict(device_id=d,model='Unavailable saved selection',system_drive=None)
                             for d in dict.fromkeys([*m.device_ids, *m.per_device_percent]) if d not in known]
        for row in rows:
            d = row['device_id'];label = drive_label(row)
            if section=='thermal_drives':
                result.append(item('drive:'+d,label,d in m.device_ids,('false','true'),('Not selected','Selected')))
            elif d in m.device_ids or d in m.per_device_percent:
                result.append(item('percent:'+d,label,m.per_device_percent.get(d,'default')))
        return result
    if section=='thermal_advanced':
        settings = [item('provider','Access provider',m.access_mode,('exclusive','shared_readonly_opt_in'),('Exclusive inactive HDD','Experimental shared data')),
                item('budget_mode','Aggregate budgets',m.budget_mode,('automatic','manual'),('Automatic from qualified rates','Manual caps')),
                item('aggregate_iops','Manual total IOPS',m.aggregate_iops_limit if m.aggregate_iops_limit is not None else 'auto'),
                item('aggregate_mib','Manual total MiB/s',m.aggregate_bps_limit/1024**2 if m.aggregate_bps_limit is not None else 'auto'),
                item('rate_mode','Per-drive rate mode',m.rate_mode,('percent','advanced'),('Percentage policy','Custom IOPS / MiB/s')),
                item('iops','Custom per-drive IOPS',m.iops if m.iops is not None else 'auto'),
                item('mib','Custom per-drive MiB/s',m.bandwidth_bytes_per_second/1024**2 if m.bandwidth_bytes_per_second is not None else 'auto'),
                item('block_kib','Read size (KiB)',m.block_size//1024,('4','8','16','32','64','128','256','512','1024')),
                item('warning','Warning temperature °C',m.temperature_warning_c if m.temperature_warning_c is not None else 'device'),
                item('stop','Stop temperature °C',m.temperature_limit_c if m.temperature_limit_c is not None else 'device'),
                item('perdrive','Per-drive intensity…','Open')]
        hidden = set()
        if m.budget_mode == 'automatic':
            hidden.update(('aggregate_iops', 'aggregate_mib'))
        if m.rate_mode == 'percent':
            hidden.update(('iops', 'mib'))
        return [setting for setting in settings if setting.attribute not in hidden]
    group = GROUP_LABELS[GROUPS.index(m.selection)]
    if m.selection=='individual':group=f'{len(m.device_ids)} physical drive(s)'
    return [item('enabled','Enabled',m.enabled,('false','true'),('Off','On — recommended data setup')),
            item('targets','Drives',group,GROUPS,GROUP_LABELS),
            item('intensity','Intensity (%)',m.intensity_percent),
            item('system','Include system drives',False,('false',),('Off — qualification required',)),
            item('protection','Temperature protection','required' if m.monitoring == 'required' else 'Legacy unmonitored request',('required',),('Required',)),
            item('advanced','Advanced…','Open')]


def help_text(section='thermal'):
    if section=='thermal_advanced':
        return ('Advanced changes do not expand eligibility. Automatic budgets use authoritative physical-device rates; '
                'To switch to manual, enter both caps as IOPS / MiB/s. Enter auto to clear optional rates, device for sensor-derived '
                'temperature limits. Custom rate mode begins at 1 IOPS until edited. MiB/s means 1,048,576 bytes/s. '
                'These caps do not bound OS, kernel or initialization I/O.')
    return ('Enabled → On selects the experimental shared read-only data provider and automatic aggregate budgets. '
            'It supports qualified internal HDD/SSD/NVMe data drives, mounted or unmounted; '
            'execution requires informed foreground authorization and final readiness review. '
            'Existing saved settings are preserved until edited. System drives stay excluded: the on-demand '
            'worker identity has not been qualified for system access. Required temperature monitoring cannot be disabled. '
            'Drive-picker information is passive and is not execution eligibility. Private authorization is never saved.')


def apply(edit, index, key, raw, validator, rows=()):
    """One validated transaction; no frontend can partially mutate a profile."""
    from .lvs_storage_thermal import stage_config, GROUPS
    candidate = deepcopy(edit);stage=candidate.profile.stages[index];m=stage.modules.storage_thermal
    name=key.removeprefix('thermal_ui_');text=str(raw).strip()
    def whole(value,low,high):
        if not value.isascii() or not value.isdecimal() or not low<=int(value)<=high:raise ValueError(f'Enter a whole number from {low} to {high}')
        return int(value)
    def mib(value):
        if value.lower()=='auto':return None
        try:n=Decimal(value)*1048576
        except InvalidOperation:raise ValueError('Enter MiB/s or auto')from None
        if not n.is_finite() or n!=n.to_integral_value() or not 1<=n<=2**40:raise ValueError('Enter positive MiB/s representable in whole bytes')
        return int(n)
    if name=='enabled':
        if text not in ('true','false'):raise ValueError('Choose On or Off')
        m.enabled=text=='true'
        if m.enabled:
            m.access_mode='shared_readonly_opt_in';m.budget_mode='automatic';m.monitoring='required'
            for k in ('_system_device_ids','_control_plane_colocation','_system_swap'):m.__dict__.pop(k,None)
    elif name=='targets':
        if text not in GROUPS or text=='individual'and not m.device_ids:raise ValueError('Choose physical drives using the picker')
        m.selection=text
    elif name.startswith('drive:'):
        d=name[6:];row=next((r for r in rows if r['device_id']==d),None)
        if text not in ('true','false'):raise ValueError('Choose Selected or Not selected')
        if text=='true' and (row is None or row.get('system_drive') is True):raise ValueError('This drive is unavailable or system access is not qualified')
        ids=list(m.device_ids)
        if text=='true'and d not in ids:ids.append(d)
        if text=='false'and d in ids:ids.remove(d)
        if not ids:raise ValueError('Select another drive first, or disable Thermal Assist')
        m.selection='individual';m.device_ids=ids
    elif name=='intensity':
        m.intensity_percent=whole(text,0,100);m.rate_mode='percent';m.iops=None;m.bandwidth_bytes_per_second=None
    elif name=='system':
        if text!='false':raise ValueError('System inclusion requires separately qualified run-local authorization; unavailable here')
        for k in ('_system_device_ids','_control_plane_colocation','_system_swap'):m.__dict__.pop(k,None)
    elif name=='protection':
        if text!='required':raise ValueError('Temperature monitoring is required')
        m.monitoring='required'
    elif name=='provider':
        if text not in ('exclusive','shared_readonly_opt_in'):raise ValueError('Choose a supported provider')
        m.access_mode=text
        if text=='shared_readonly_opt_in':m.monitoring='required';m.budget_mode='automatic'
    elif name=='budget_mode':
        if text not in ('automatic','manual'):raise ValueError('Choose automatic or manual')
        m.budget_mode=text
    elif name == 'manual_caps':
        parts = text.split('/')
        if len(parts) != 2:
            raise ValueError('Enter total IOPS / MiB/s, for example 128 / 8')
        m.aggregate_iops_limit = whole(parts[0].strip(), 1, 2**40)
        m.aggregate_bps_limit = mib(parts[1].strip())
        if m.aggregate_bps_limit is None:
            raise ValueError('Manual bandwidth cap is required')
        m.budget_mode = 'manual'
    elif name=='aggregate_iops':m.aggregate_iops_limit=None if text=='auto'else whole(text,1,2**40)
    elif name=='aggregate_mib':m.aggregate_bps_limit=mib(text)
    elif name=='rate_mode':
        if text not in ('percent','advanced'):raise ValueError('Choose percentage or custom rates')
        m.rate_mode=text
        if text=='percent':m.iops=None;m.bandwidth_bytes_per_second=None
        elif m.iops is None and m.bandwidth_bytes_per_second is None:m.iops=1
    elif name=='iops':m.iops=None if text=='auto'else whole(text,1,2**40)
    elif name=='mib':m.bandwidth_bytes_per_second=mib(text)
    elif name=='block_kib':m.block_size=whole(text,4,1024)*1024
    elif name in ('warning','stop'):
        if text.lower()=='device':v=None
        else:
            try:v=float(text)
            except ValueError:raise ValueError('Enter degrees C or device')from None
        setattr(m,'temperature_warning_c'if name=='warning'else'temperature_limit_c',v)
    elif name=='system_intensity':m.system_intensity_percent=whole(text,0,100)
    elif name.startswith('percent:'):
        d=name[8:]
        if text=='default':m.per_device_percent.pop(d,None)
        elif d not in m.device_ids:raise ValueError('Choose an individually selected drive first')
        else:m.per_device_percent[d]=whole(text,0,100)
    else:raise ValueError('Unknown Thermal Assist control')
    m.__dict__.pop('_resolved_aggregate_limits',None)
    stage_config(stage)
    errors=validator.validate(candidate.profile,candidate.labels)['errors']
    if errors:raise ValueError('; '.join(errors))
    edit.profile,edit.labels,edit.dirty=candidate.profile,candidate.labels,True
    return 'Updated'


def automatic_limits(config, plan):
    """Sum established rates for authoritative eligible physical data devices.

    No capacity/model proxies, new per-device ceilings or eligibility grants.
    The final ordinary readiness pass rechecks all admission constraints.
    """
    from .lvs_storage_thermal import pilot_rate
    seen=set();iops=bps=0
    for row in plan.get('targets',[]):
        if not row.get('eligible') or not row.get('internal') or row.get('system_drive') is not False:continue
        if any(not reason.startswith(('aggregate IOPS budget exceeded','aggregate bandwidth budget exceeded')) for reason in row.get('reasons',[])):continue
        d=row['device_id']
        if d in seen:raise ValueError('Duplicate physical target in automatic budget')
        seen.add(d);rate=pilot_rate(config,d,row['drive_class'],system=False)
        if any(row['rate'].get(k)!=rate[k]for k in ('effective_iops','effective_bps','block_size')):raise ValueError('Automatic budget rate evidence disagrees with authorized policy')
        iops+=rate['effective_iops'];bps+=rate['effective_bps']
    return (iops,bps)if iops and bps else None
