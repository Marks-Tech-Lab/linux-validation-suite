"""Presentation-only CPU ISA ordering through real CLI/TUI adapters; no workloads."""
from __future__ import annotations

import asyncio
import contextlib
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from Modules.lvs_profile_editor import ProfileEditor
from Modules.lvs_stage_configuration import stage_settings
from smoke_tests.cli_configuration_checks import Host
from smoke_tests.configuration_workflow_checks import ROOT, Service, _source


def _expected(catalog):
    return ['auto', *sorted((v for v in catalog if v != 'auto'), key=str.casefold)]


def run_cpu_instruction_order_checks():
    original=list(ProfileEditor.CPU_INSTRUCTION_OPTIONS)
    expected=_expected(original)
    assert ProfileEditor.cpu_instruction_options()==expected
    assert original==ProfileEditor.CPU_INSTRUCTION_OPTIONS  # Never reorder policy/catalog data.
    with patch.object(ProfileEditor,'CPU_INSTRUCTION_OPTIONS',['z','Auto','A']):
        assert ProfileEditor.cpu_instruction_options()==['Auto','A','z']
    with patch.object(ProfileEditor,'CPU_INSTRUCTION_OPTIONS',['zToken','Btoken','auto','atoken']):
        assert ProfileEditor.cpu_instruction_options()==['auto','atoken','Btoken','zToken']
    with TemporaryDirectory(dir=ROOT) as tmp:
        service=Service(Path(tmp));source=_source(service);before=source.read_bytes()
        edit=service.create_profile_edit(source)
        # A future catalog addition is reflected immediately by every presenter.
        for catalog in [original, [*reversed(original),'aaa_future']]:
            with patch.object(ProfileEditor,'CPU_INSTRUCTION_OPTIONS',catalog):
                expected=_expected(catalog)
                spec=service.profile_stage_picker_spec(edit,0,'cpu_instruction')
                setting=next(s for s in stage_settings(edit.profile.stages[0],service.profile_editor) if s.key=='cpu_instruction')
                assert list(setting.options)==spec.options==expected
                from Modules.lvs_tui_picker_presentation import profile_edit_picker_presentation
                presentation=profile_edit_picker_presentation(spec,'fixture')
                assert presentation.labels[0].startswith('Auto')
                assert presentation.selected_index==expected.index('sve_fp32_fma')
                assert setting.option_labels[0]=='Auto'
                for index,value in enumerate(expected,1):
                    out=io.StringIO()
                    with contextlib.redirect_stdout(out):
                        selected=Host(service,[str(index)]).profile_cli._choose_cpu_instruction_set('neon_dotprod')
                    assert selected==value,(index,value,selected)
                    assert '1. Auto' in out.getvalue()
                for answer in ['', '0', '-1','999']:
                    with contextlib.redirect_stdout(io.StringIO()):
                        assert Host(service,[answer]).profile_cli._choose_cpu_instruction_set('neon_dotprod')=='neon_dotprod'
                with contextlib.redirect_stdout(io.StringIO()):
                    assert Host(service,['NEON_I8MM']).profile_cli._choose_cpu_instruction_set()=='neon_i8mm'
                    profile=service.profile_loader.load_profile(source)
                    labels=service.profile_loader.load_segment_labels(source,profile)
                    fields=stage_settings(profile.stages[0],service.profile_editor)
                    row=next(i+1 for i,s in enumerate(fields) if s.key=='cpu_instruction')
                    host=Host(service,[str(row),str(expected.index('neon_i8mm')+1),''])
                    host.profile_cli.configure_stage_workloads(profile,0,labels,run_only=True)
                    assert profile.stages[0].modules.cpu.instruction_set=='neon_i8mm'
                assert source.read_bytes()==before
                assert service.create_run_setup(source).profile.stages[0].modules.cpu.instruction_set=='sve_fp32_fma'
        assert original==ProfileEditor.CPU_INSTRUCTION_OPTIONS


def run_tui_cpu_instruction_order_checks():
    try:
        from Modules.lvs_tui_app import LinuxValidationSuiteTui
    except ModuleNotFoundError as error:
        if error.name!='textual':raise
        print('SKIP optional Textual pilot; shared presentation/CLI checks still run')
        return

    class App(LinuxValidationSuiteTui):
        def _refresh_live_system_pane(self):pass

    async def check():
        with TemporaryDirectory(dir=ROOT) as tmp:
            service=Service(Path(tmp));source=_source(service);before=source.read_bytes()
            app=App(service)
            async with app.run_test(size=(150,55)) as pilot:
                await pilot.pause()
                await app.action_edit_profile()
                expected=_expected(ProfileEditor.CPU_INSTRUCTION_OPTIONS)
                await app._open_profile_stage_picker('cpu_instruction',stage_index=0)
                assert app.profile_edit_picker_options==expected
                assert app.query_one('#items').index==expected.index('sve_fp32_fma')
                app.query_one('#items').index=expected.index('neon_i8mm')
                await pilot.press('enter');await pilot.pause()
                assert app.profile_edit.profile.stages[0].modules.cpu.instruction_set=='neon_i8mm'
                assert source.read_bytes()==before
                service.save_profile_edit(app.profile_edit)
                assert service.profile_loader.load_profile(source).stages[0].modules.cpu.instruction_set=='neon_i8mm'
                saved=source.read_bytes()
                await app.action_show_profiles();await app.action_setup_run()
                await app._handle_stage_override_choice('Configure Stage Workloads (this run only)')
                await app._select_setup_picker_option(app.setup_picker_options[0])
                # A new choice shifts indexes while this application is already open.
                catalog=[*ProfileEditor.CPU_INSTRUCTION_OPTIONS,'aaa_future']
                with patch.object(ProfileEditor,'CPU_INSTRUCTION_OPTIONS',catalog):
                    await app._show_stage_configuration()
                    row=next(i+1 for i,s in enumerate(app.stage_configuration_fields) if s.key=='cpu_instruction')
                    await app._activate_stage_configuration_item(row)
                    expected=_expected(catalog)
                    assert app.profile_edit_picker_options==expected
                    assert app.query_one('#items').index==expected.index('neon_i8mm')
                    app.query_one('#items').index=expected.index('neon_dotprod')
                    await pilot.press('enter');await pilot.pause()
                    assert app.run_setup.profile.stages[0].modules.cpu.instruction_set=='neon_dotprod'
                    await app._activate_stage_configuration_item(row)
                    await pilot.press('escape');await pilot.pause()
                    assert app.run_setup.profile.stages[0].modules.cpu.instruction_set=='neon_dotprod'
                assert source.read_bytes()==saved
                assert service.create_run_setup(source).profile.stages[0].modules.cpu.instruction_set=='neon_i8mm'
    asyncio.run(check())
