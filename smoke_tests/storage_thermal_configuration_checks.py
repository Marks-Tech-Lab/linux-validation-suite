"""Guided CLI/TUI configuration; private fixtures only, no host authorization/I/O."""
from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import asdict
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from Modules.lvs_storage_thermal import ThermalConfig, stage_config, pilot_rate
from Modules.lvs_storage_thermal_configuration import fields, apply, automatic_limits, drive_label
from Modules.lvs_storage_thermal_execution import prepare, execution_scope, execution_plan, key
from Modules.lvs_service_models import ProfileEditState
from smoke_tests.configuration_workflow_checks import Service, _source
from smoke_tests.storage_thermal_execution_checks import fixture


def rows():
    return [dict(device_id=f'wwn:private-{i}', model=f'Example {kind}', identity=dict(size_bytes=2**40),
                 drive_class=kind, internal=True, system_drive=False, eligible=True, reasons=[])
            for i,kind in enumerate(('hdd','ssd','nvme'))]


def reject(call):
    try:call()
    except ValueError:return
    raise AssertionError('invalid configuration accepted')


def run_thermal_guided_configuration_checks():
    with TemporaryDirectory() as directory:
        service=Service(Path(directory));source=_source(service);before=source.read_bytes()
        edit=service.create_profile_edit(source);stage=edit.profile.stages[0];old=deepcopy(stage)
        edit.profile.menu_description='Operator-authored description'
        edit.labels[0]=stage.display_label='Custom stage label'
        def change(k,v):return apply(edit,0,'thermal_ui_'+k,v,service.validator,rows())
        assert old.modules.storage_thermal.access_mode=='exclusive'
        assert old.modules.storage_thermal.budget_mode=='manual'
        change('enabled','true');m=edit.profile.stages[0].modules.storage_thermal
        assert m.enabled and m.access_mode=='shared_readonly_opt_in' and m.budget_mode=='automatic'
        assert m.monitoring=='required' and not stage_config(edit.profile.stages[0]).system_device_ids
        assert set(stage_config(edit.profile.stages[0]).to_dict())==set(ThermalConfig().to_dict())
        assert [f.key for f in fields(edit.profile.stages[0])]==['thermal_ui_'+k for k in ('enabled','targets','intensity','system','protection','advanced')]
        for section in ('thermal','thermal_advanced','thermal_drives','thermal_per_drive'):
            for f in fields(edit.profile.stages[0],section,rows()):
                assert 'JSON' not in f.label and not any(d['device_id'] in f.label for d in rows())
        change('drive:wwn:private-0','true');change('drive:wwn:private-2','true')
        change('percent:wwn:private-2','25')
        change('rate_mode','advanced');change('iops','8');change('mib','0.5')
        assert stage_config(edit.profile.stages[0]).bandwidth_bytes_per_second==524288
        change('intensity','25') # Normal percentage selection exits custom mode.
        c=stage_config(edit.profile.stages[0]);assert c.rate_mode=='percent' and c.iops is None and c.intensity_percent==25
        visible = {f.attribute for f in fields(edit.profile.stages[0], 'thermal_advanced')}
        assert not visible & {'aggregate_iops', 'aggregate_mib', 'iops', 'mib', 'system_intensity'}
        change('manual_caps','80 / 5')
        visible = {f.attribute for f in fields(edit.profile.stages[0], 'thermal_advanced')}
        assert {'aggregate_iops', 'aggregate_mib'} <= visible
        assert stage_config(edit.profile.stages[0]).aggregate_bps_limit==5242880
        for k,v in [('intensity','101'),('intensity','true'),('block_kib','3'),('block_kib','12'),('warning','NaN'),
                    ('mib','Infinity'),('aggregate_mib','0.00000001'),('system','true'),('protection','optional'),('targets','bogus')]:
            snapshot=deepcopy(edit.profile);reject(lambda:change(k,v));assert edit.profile==snapshot,(k,v)
        snapshot=deepcopy(edit.profile)
        reject(lambda:apply(edit,0,'thermal_ui_drive:wwn:private-1','true',service.validator,
                            [dict(rows()[1],system_drive=True)]));assert edit.profile==snapshot
        assert 'System' in drive_label(dict(rows()[0],system_drive=None))
        assert '1024 GiB' in drive_label(rows()[0])
        edit.profile.stages[0].modules.storage_thermal._system_device_ids=['untrusted-private-intent']
        change('enabled','true');assert not stage_config(edit.profile.stages[0]).system_device_ids
        # Authoring serializes intent, never resolved budgets or private authorization.
        edit.profile.stages[0].modules.storage_thermal._resolved_aggregate_limits=(8,524288)
        saved=service.save_profile_copy_selection(service.create_profile_copy_selection(edit,mode='save_as'),'Guided')
        data=saved.profile_path.read_text()
        assert 'automatic' in data and '_resolved' not in data and '_system_device_ids' not in data
        loaded=service.profile_loader.load_profile(saved.profile_path)
        assert stage_config(loaded.stages[0]).aggregate_iops_limit==1
        assert source.read_bytes()==before and edit.profile.menu_description=='Operator-authored description'
        assert edit.profile.stages[0].display_label=='Custom stage label'


def run_thermal_guided_cli_checks():
    from Modules.lvs_profile_cli_editor import ProfileCliEditor
    from Modules.lvs_stage_configuration import stage_settings
    with TemporaryDirectory() as directory:
        service=Service(Path(directory));source=_source(service);before=source.read_bytes()
        p=service.create_profile_edit(source).profile
        folder=len([f for f in stage_settings(p.stages[0],service.profile_editor) if not f.key.startswith('thermal_')])+1
        # Real operator menu: folder, enable, physical picker, select NVMe, back,
        # percentage, advanced read size, back twice, leave workload screen.
        answers=iter([str(folder),'1','2','2','6','3','2','b','3','25','6','4','64','b','b','b'])
        host=SimpleNamespace(profile_editor=service.profile_editor,profile_edit_controller=service.profile_edit_controller,
                             profile_save=service.profile_save,_input=lambda _:next(answers))
        output=io.StringIO()
        with patch('Modules.lvs_storage_thermal_configuration.drive_choices',return_value=rows()),redirect_stdout(output):
            ProfileCliEditor(host).configure_stage_workloads(p,0,['fixture'],run_only=True)
        m=p.stages[0].modules.storage_thermal
        assert m.enabled and m.device_ids==['wwn:private-2'] and m.intensity_percent==25
        assert m.access_mode=='shared_readonly_opt_in' and m.budget_mode=='automatic'
        assert 'Example nvme' in output.getvalue() and 'MiB/s' in output.getvalue()
        assert 'wwn:private' not in output.getvalue() and 'JSON' not in output.getvalue()
        assert source.read_bytes()==before


def run_thermal_automatic_budget_checks():
    # Deterministic low/high-resource, mixed-class, unknown and duplicate coverage.
    config=ThermalConfig(access_mode='shared_readonly_opt_in',aggregate_iops_limit=1,aggregate_bps_limit=1)
    def plan(config, devices):
        return dict(targets=[dict(r,rate=pilot_rate(config,r['device_id'],r['drive_class']))for r in devices])
    assert automatic_limits(config,plan(config,rows()))==(207,207*65536)
    assert automatic_limits(config,dict(targets=[])) is None
    assert automatic_limits(config,dict(targets=[dict(plan(config,rows())['targets'][0],eligible=False)])) is None
    system=dict(plan(config,rows())['targets'][0],system_drive=True)
    assert automatic_limits(config,dict(targets=[system])) is None
    uncertain=dict(plan(config,rows())['targets'][0],system_drive=None)
    assert automatic_limits(config,dict(targets=[uncertain])) is None
    bad=plan(config,rows());bad['targets'][0]['rate']['effective_iops']=1000
    reject(lambda:automatic_limits(config,bad))
    reject(lambda:automatic_limits(config,plan(config,rows()+[rows()[0]])))
    huge=[dict(rows()[i%3],device_id=f'id:{i}')for i in range(100)]
    assert automatic_limits(config,plan(config,huge))[0]==sum(pilot_rate(config,r['device_id'],r['drive_class'])['effective_iops']for r in huge)
    reject(lambda:automatic_limits(config,dict(targets=[dict(rows()[0],drive_class='unknown',rate={})])))
    profile,stage=fixture();m=stage.modules.storage_thermal
    m.access_mode='shared_readonly_opt_in';m.budget_mode='automatic'
    profile.stages.append(deepcopy(stage)) # same intent, independently bound stages
    manager=Mock();manager.sudo_noninteractive_ready.return_value=True
    calls=[]
    def readiness(c):
        calls.append(c.to_dict());result=plan(c,rows())
        result.update(status='READY' if c.aggregate_iops_limit==207 else 'BLOCKED',backend=dict(status='available'),
                      configuration=c.to_dict(),runnable_devices=[r['device_id']for r in rows()])
        return result
    with patch('Modules.lvs_storage_thermal_runtime.inspect',return_value=dict(status='DEFERRED')),patch('Modules.lvs_storage_thermal_runtime.preview',side_effect=readiness):
        plans=prepare(profile,manager,None)
        assert len(plans)==1 and len(calls)==4 and [c['aggregate_iops_limit']for c in calls]==[1,207,1,207]
        assert set(plans)=={key(stage)}
        with execution_scope(profile):assert execution_plan(stage)['status']=='READY'
        # Changed intent cannot inherit old aggregate authority.
        m.intensity_percent=25
        with execution_scope(profile):assert execution_plan(stage)['status']=='BLOCKED'
    with patch('Modules.lvs_storage_thermal_runtime.inspect',return_value=dict(status='DEFERRED')),patch('Modules.lvs_storage_thermal_runtime.preview',return_value=dict(targets=[],status='BLOCKED')):
        plans=prepare(profile,manager,None)
        assert all(p['status']=='BLOCKED' for p in plans.values()) and m.__dict__.get('_resolved_aggregate_limits') is None


def run_thermal_automatic_runner_planning_checks():
    # Real production planner, temperatures/capability/private regular-file fixtures only.
    from smoke_tests.storage_thermal_runner_checks import RunnerFixture
    with TemporaryDirectory() as directory:
        f=RunnerFixture(directory,3)
        for r,kind in zip(f.rows,('hdd','ssd','nvme')):r['drive_class']=kind
        config=ThermalConfig(access_mode='shared_readonly_opt_in',aggregate_iops_limit=1,aggregate_bps_limit=1)
        probe=f.runner.plan(config,f.rows,f.backend)
        assert probe['status']!='READY'
        limits=automatic_limits(config,probe);assert limits==(207,13565952)
        from dataclasses import replace
        ready=f.runner.plan(replace(config,aggregate_iops_limit=limits[0],aggregate_bps_limit=limits[1]),f.rows,f.backend)
        assert ready['status']=='READY' and len(ready['commands'])==3
        assert sum(d['rate']['effective_iops']for d in ready['devices'])==207
        f.rows[0].update(system_drive=True, eligible=False, reasons=['system access blocked'])
        probe=f.runner.plan(config,f.rows,f.backend)
        limits=automatic_limits(config,probe)
        assert limits==(192,12582912)
        shared=f.runner.plan(replace(config,aggregate_iops_limit=limits[0],aggregate_bps_limit=limits[1]),f.rows,f.backend)
        assert shared['status']=='READY' and not shared['partial_coverage']
        assert f.rows[0]['device_id'] not in shared['selected_devices']
        f.rows[0].update(system_drive=None, reasons=['unknown topology'])
        shared=f.runner.plan(replace(config,aggregate_iops_limit=limits[0],aggregate_bps_limit=limits[1]),f.rows,f.backend)
        assert shared['status']=='READY' and shared['partial_coverage']
        assert f.rows[0]['device_id'] in shared['blocked_devices']
        f.temp=None
        probe=f.runner.plan(config,f.rows,f.backend)
        assert automatic_limits(config,probe) is None # missing monitoring never supplies budgets
        f.temp=30
        f.runner.budget=lambda:dict(memory_budget=1,memory_available=2,fd_limit=4)
        probe=f.runner.plan(config,f.rows,f.backend)
        assert automatic_limits(config,probe) is None # resource constraints are not hidden


def run_thermal_guided_tui_checks():
    import asyncio
    try:
        from Modules.lvs_tui_app import LinuxValidationSuiteTui
    except ModuleNotFoundError as exc:
        if exc.name != 'textual':raise
        print('SKIP optional Textual pilot');return
    class App(LinuxValidationSuiteTui):
        def _refresh_live_system_pane(self):pass
        def _set_detail(self,text):
            self.detail=text;super()._set_detail(text)
        async def _replace_sidebar_labels(self,view,labels,**kwargs):
            self.labels=list(labels)
            await super()._replace_sidebar_labels(view,labels,**kwargs)
    async def check():
        with TemporaryDirectory() as directory:
            service=Service(Path(directory));source=_source(service);before=source.read_bytes()
            service.thermal_drive_choices=Mock(return_value=rows()+[dict(rows()[0],device_id='wwn:system',system_drive=True)])
            app=App(service)
            async with app.run_test(size=(110,40))as pilot:
                await pilot.pause();await app.action_show_profiles();await app.action_setup_run()
                await app._open_stage_configuration(0,for_run=True)
                async def activate(key):
                    index=next(i+1 for i,f in enumerate(app.stage_configuration_fields)if f.key==key)
                    await app._activate_stage_configuration_item(index);await pilot.pause()
                async def choose(value):
                    app.query_one('#items').index=app.profile_edit_picker_options.index(value)
                    await pilot.press('enter');await pilot.pause()
                await activate('thermal_ui_open')
                await activate('thermal_ui_enabled');await choose('true')
                await activate('thermal_ui_targets');await choose('individual')
                service.thermal_drive_choices.assert_called_once()
                assert 'Example nvme' in '\n'.join(app.labels) and 'wwn:' not in '\n'.join(app.labels)
                await activate('thermal_ui_drive:wwn:system');await choose('true')
                assert 'Setting unchanged' in app.detail
                await activate('thermal_ui_drive:wwn:private-2');await choose('true')
                assert app.run_setup.profile.stages[0].modules.storage_thermal.device_ids==['wwn:private-2']
                await app._leave_stage_configuration();await activate('thermal_ui_advanced')
                await activate('thermal_ui_block_kib');await choose('128')
                assert app.run_setup.profile.stages[0].modules.storage_thermal.block_size==131072
                await activate('thermal_ui_perdrive')
                assert len(app.stage_configuration_fields)==1
                await activate('thermal_ui_percent:wwn:private-2')
                app.query_one('#setup-input').value='25'
                await pilot.press('enter');await pilot.pause()
                assert app.run_setup.profile.stages[0].modules.storage_thermal.per_device_percent=={'wwn:private-2':25}
                await app._leave_stage_configuration();await app._leave_stage_configuration()
                assert 'run override' in '\n'.join(app.labels)
                assert not any('JSON' in row or 'system_access' in row for row in app.labels)
                await app._leave_stage_configuration();await app._leave_stage_configuration()
                assert source.read_bytes()==before
    asyncio.run(check())
