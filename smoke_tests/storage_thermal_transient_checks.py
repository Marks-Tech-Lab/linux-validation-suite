"""On-demand boundary controls. Root/service tests execute only in sealed VMs."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import os
import subprocess
import sys

from Modules.lvs_storage_thermal_transient import ROOT_STAGER,MODE,Hold
from Modules.lvs_storage_thermal_execution import prepare,execution_scope
from smoke_tests.storage_thermal_execution_checks import fixture


def run_thermal_transient_candidate_checks():
    from Modules.lvs_storage_thermal_runtime import inspect
    from Modules.lvs_storage_thermal import stage_config
    _,s=fixture()
    with patch('Modules.lvs_storage_thermal_runtime.owned_path',side_effect=FileNotFoundError),patch('Modules.lvs_storage_thermal_runtime.on_demand_candidate',return_value=True),patch('Modules.lvs_storage_thermal_runtime.rpc',side_effect=AssertionError('preview RPC')),patch('subprocess.run',side_effect=AssertionError('preview process')):
        result=inspect(stage_config(s));assert result['status']=='DEFERRED'and result['on_demand_startup']and not result['execution_ready']
    with patch('Modules.lvs_storage_thermal_runtime.owned_path',side_effect=FileNotFoundError),patch('Modules.lvs_storage_thermal_runtime.on_demand_candidate',return_value=False):
        try:inspect(stage_config(s))
        except ValueError:pass
        else:raise AssertionError('unsupported supervisor accepted')


def run_thermal_transient_approval_checks():
    p,s=fixture();manager=Mock();manager.sudo_noninteractive_ready.return_value=True
    passive=dict(status='DEFERRED',on_demand_startup=True)
    approved=dict(source={'digest':'a'*64},manifest_sha256='b'*64, stager_sha256='c'*64,
                  commit='d'*40, build={'fio_version':'fio-3.42'}, bundle='/tmp/fixture')
    lease=Mock()
    with patch('Modules.lvs_storage_thermal_runtime.inspect',return_value=passive),patch('Modules.lvs_storage_thermal_transient.prepare_candidate',return_value=approved),patch('Modules.lvs_storage_thermal_transient.start_and_hold',return_value=lease)as start,patch('Modules.lvs_storage_thermal_runtime.preview',return_value=dict(status='READY')):
        deny=Mock(return_value=False);plans=prepare(p,manager,deny)
        assert list(plans.values())[0]['status']=='BLOCKED';deny.assert_called_once();start.assert_not_called()
        manager.sudo_noninteractive_ready.assert_called_once()  # cached sudo is NOT source approval
        yes=Mock(return_value=True);plans=prepare(p,manager,yes)
        assert list(plans.values())[0]['execution_ready'];yes.assert_called_once();start.assert_called_once_with(approved)
        with execution_scope(p):pass
        lease.close.assert_called()
        lease.reset_mock()
        with patch('Modules.lvs_storage_thermal_runtime.preview',return_value=dict(status='BLOCKED')):
            prepare(p,manager,yes)
        lease.close.assert_called_once()
        yes.assert_called_once()  # exact approval reused without prompting
        changed = dict(approved, manifest_sha256='e'*64)
        with patch('Modules.lvs_storage_thermal_transient.prepare_candidate',return_value=changed):
            prepare(p,manager,deny)
        assert deny.call_count == 2 and start.call_count == 2
    from tempfile import TemporaryDirectory
    import json
    from Modules.lvs_storage_thermal_transient import _candidate_unchanged, digest
    with TemporaryDirectory() as directory:
        root = Path(directory)
        tool = root / 'fixture-tool'
        compiler = root / 'fixture-compiler'
        tool.write_bytes(b'approved tool')
        compiler.write_bytes(b'approved compiler')
        manifest = root / 'manifest.json'
        manifest.write_text(json.dumps({'files': {tool.name: digest(tool)}}))
        candidate = dict(approved, bundle=directory, manifest_sha256=digest(manifest),
                         fio_sha256='fixture-fio', build={'compiler': {
                             'path': str(compiler.resolve()), 'sha256': digest(compiler)}})
        identities = (candidate['source'], candidate['commit'], candidate['fio_sha256'], candidate['stager_sha256'])
        with patch('Modules.lvs_native_helpers.find_c_compiler', return_value=str(compiler)):
            assert _candidate_unchanged(candidate, *identities)
            assert not _candidate_unchanged(candidate, {'digest': 'changed'}, *identities[1:])
            tool.write_bytes(b'changed tool')
            assert not _candidate_unchanged(candidate, *identities)
            tool.write_bytes(b'approved tool')
            compiler.write_bytes(b'changed compiler')
            assert not _candidate_unchanged(candidate, *identities)
    from Modules.lvs_storage_thermal_system import SystemAuthority
    try:SystemAuthority('/unused',dict(runtime_mode=MODE)).worker()
    except ValueError as e:assert 'data drives only'in str(e)
    else:raise AssertionError('temporary system access authorized')


def run_thermal_transient_stager_checks():
    from scripts.storage_thermal_transient_probe import client
    with patch('pathlib.Path.read_text',side_effect=FileNotFoundError('no VM seal')),patch('Modules.lvs_storage_thermal_runtime.preview',side_effect=AssertionError('host workload path')):
        try:client('not-a-host-target')
        except FileNotFoundError:pass
        else:raise AssertionError('unsealed client accepted')
    from Modules.lvs_storage_thermal_transient import start
    with patch('Modules.lvs_storage_thermal_transient.tool',side_effect=lambda name:'/trusted/'+name),patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='{}',stderr=''))as run:
        start(dict(bundle='/approved/snapshot',manifest_sha256='a'*64,executable='/untrusted/ignored'))
        argv=run.call_args.args[0]
        assert argv[:6]==['/trusted/sudo','-n','/trusted/python3','-I','-B','-c']
        assert argv[6]==ROOT_STAGER and '/untrusted/ignored'not in argv
    # A normal process can never turn the stager into an unprivileged fallback.
    # Even when CI runs as root, this child is deliberately non-root.
    kw=dict(user=65534,group=65534,extra_groups=())if os.geteuid()==0 else{}
    r=subprocess.run(['/usr/bin/python3','-I','-B','-c',ROOT_STAGER,'/nonexistent','0'*64,'1000'],capture_output=True,text=True,timeout=5,**kw)
    assert r.returncode and 'explicit sudo bootstrap required'in r.stderr
    # Actual protected-copy, symlink/type, version and startup tests are VM-only.
    compile(ROOT_STAGER,'fixed-root-stager','exec')


def run_thermal_transient_lifetime_checks():
    hold=Hold.__new__(Hold);connection=Mock();hold.connection=connection
    hold.close();hold.close();connection.close.assert_called_once()
    from Modules.lvs_run_executor import RunExecutor,RunExecutionError
    from Modules.lvs_run_launch import RunLaunchCoordinator,RunLaunchRequest
    from Modules.lvs_run_metadata import RunMetadata
    for capture in (False,True):
        p,s=fixture();lease=Mock();p._thermal_execution_preparation=dict(stages=[],plans={},lease=lease)
        executor=RunExecutor(settings=SimpleNamespace(),profile_loader=None,orchestrator=Mock(),default_run_metadata=lambda _:RunMetadata(),ensure_enhanced_telemetry_ready=lambda:False,run_heatsoak_if_requested=lambda *a,**k:False)
        request=RunLaunchRequest(Path('fixture'),setup=SimpleNamespace(profile=p,labels=['CPU']))
        try:
            if capture:RunLaunchCoordinator(executor).run_prepared_capture(request)
            else:assert RunLaunchCoordinator(executor).run_prepared_direct(request)is None
        except RunExecutionError:assert capture
        lease.close.assert_called_once();executor.orchestrator.run.assert_not_called()
    p,s=fixture();lease=Mock();p._thermal_execution_preparation=dict(lease=lease)
    with patch('Modules.lvs_run_executor.build_profile_run_context',side_effect=ValueError('invalid metadata')):
        try:executor._profile_run_context(Path('fixture'),None,SimpleNamespace(profile=p))
        except ValueError:pass
        else:raise AssertionError('bad metadata accepted')
    lease.close.assert_called_once();assert not hasattr(p,'_thermal_execution_preparation')
