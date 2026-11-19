"""Sealed-VM-only qualification of the installed integrated production path.

No host entrypoint: imported only by the existing private-image QEMU campaign.
Temperature and primary processes are simulated; topology, opener, fio, guard,
RPC credentials, leases, ownership, recovery and stage lifecycle are real.
"""
from pathlib import Path
import inspect
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime


def primary(plan,config,path,seconds,cancel_after=None,temperature_stop=False,death_control=False):
    from Modules.lvs_profile_models import StageConfig,StageModules,ModuleCpu,ModuleStorageThermal,ValidationProfile
    from Modules.lvs_run_models import StageWindow
    from Modules.lvs_stage_execution import execute_stage_runtime
    from Modules.lvs_storage_thermal_stage import apply_profile_decisions,preview
    from Modules.lvs_storage_thermal_results import evidence_run
    from dataclasses import fields
    names={f.name for f in fields(ModuleStorageThermal)}
    thermal={k:v for k,v in config.items() if k in names and k!='enabled'}
    stage=StageConfig('integrated-proof','CPU',seconds,modules=StageModules(cpu=ModuleCpu(enabled=True),storage_thermal=ModuleStorageThermal(enabled=True,**thermal)))
    stage.normalization.trim_start_seconds=0;stage.normalization.trim_end_seconds=0
    if config.get('system_device_ids'):
        from Modules.lvs_storage_thermal_stage import set_thermal_setting
        set_thermal_setting(stage,'thermal_system_access',json.dumps(dict(device_ids=config['system_device_ids'],colocated=config['control_plane_colocation'],swap=config['system_swap'])))
    plan=preview(stage)
    assert plan['status']=='READY',plan
    item=dict(storage_thermal=plan)
    apply_profile_decisions(ValidationProfile('sealed',stages=[stage]),[item])
    args={}
    for key,param in inspect.signature(execute_stage_runtime).parameters.items():
        if param.default is inspect.Parameter.empty:args[key]=lambda *a,**k:None
    for key in ('profile_name','display_name','stage_started_iso','cpu_kernel_flavor','cpu_backend','cpu_mode_requested','cpu_mode_resolved',
                'cpu_tuning_policy','gpu_3d_backend_preference','gpu_3d_backend_resolved','vram_backend_preference','vram_backend_resolved','gpu_target_mode','operator_stop_source'):args[key]=''
    begin=time.monotonic();samples=[];sessions=[];activity=[None]
    from Modules.lvs_storage_thermal_stage import ThermalStageSession
    from unittest.mock import patch
    def session_factory(*args,**kwargs):
        session=ThermalStageSession(*args,**kwargs);sessions.append(session);return session
    def sample():
        samples.append(time.monotonic()-begin)
        if activity[0] is None and any((r.get('observation') or {}).get('device_read_ios_since_launch',0)>0
                for session in sessions for r in (session.last_live or {}).get('devices',[])):activity[0]=time.monotonic()
        if temperature_stop and activity[0] is not None and time.monotonic()-activity[0]>2:
            Path('/control/user/sensor-hot').write_text('fixture')
        if death_control and activity[0] is not None:
            Path('/control/user/kill-ready').touch()
    def cancelled():return bool(cancel_after and activity[0] is not None and time.monotonic()-activity[0]>=cancel_after)
    args.update(stage_window_cls=StageWindow,stage=stage,run_dir=path,stage_plan=item,stage_start=begin,stage_started_iso=datetime.now().astimezone().isoformat(),
        cpu_tuned_avg_power_w=None,gpu_targets=[],gpu_workers_initial=[],gpu_lifecycle_backends=set(),gpu_retune_events=[],stage_error_events=[],stage_failure_reasons=[],
        stage_verdict='pass',stage_aborted=False,stage_abort_reason='',run_aborted=False,abort_on_worker_error=False,abort_on_fail_threshold=False,
        telemetry_interval_seconds=.2,progress_interval_seconds=30,strict_threshold_recommendation_warnings=False,
        launch_stage_processes=lambda *a:[],stop_stage_processes=lambda *a:None,
        telemetry_collect_once=sample,poll_stage_process_failures=lambda *a:[],stage_sensor_events=lambda *a:[],
        maybe_retune_gpu_processes=lambda p,*a:p,stage_target_gpu_progress_summary=lambda *a:'',effective_gpu_retune_cooldown_seconds=lambda *a:20,
        worker_result_events_func=lambda *a:([],[]),utilization_events_func=lambda *a:[],backend_effectiveness_events_func=lambda *a:[],vram_attainment_events_func=lambda *a:[],
        now_local_iso=lambda:datetime.now().astimezone().isoformat(),monotonic=time.monotonic,sleep=time.sleep,
        cancel_check=cancelled if cancel_after else None)
    with evidence_run(path),patch('Modules.lvs_storage_thermal_stage.ThermalStageSession',side_effect=session_factory):result=execute_stage_runtime(**args)
    return dict(primary_verdict=result.stage_verdict,stage_elapsed=result.stage_elapsed,telemetry=samples,
                aborted=result.stage_aborted,auxiliary=result.stage_completion.stage_window.storage_thermal_summary)


def unprivileged(identity):
    from Modules.lvs_storage_thermal import ThermalConfig
    from Modules.lvs_storage_thermal_runtime import preview,rpc
    config=ThermalConfig(access_mode='shared_readonly_opt_in',selection='individual',device_ids=[identity],
        intensity_percent=25,aggregate_iops_limit=128,aggregate_bps_limit=8388608,duration_seconds=8,temperature_limit_c=60)
    results={}
    plan=preview(config);assert plan['status']=='READY',plan
    for case,seconds,cancel in [('complete',60,None),('cancel',60,2),('short',2,None),('temperature',60,None)]:
        effective=ThermalConfig(**dict(config.to_dict(),duration_seconds=seconds));plan=preview(effective)
        directory=Path('/control/user')/case;directory.mkdir()
        result=primary(plan,effective.to_dict(),directory,seconds,cancel,case=='temperature')
        Path('/control/user/sensor-hot').unlink(missing_ok=True)
        results[case]=result
        (directory/'result.json').write_text(json.dumps(result,indent=2))
        assert len(result['telemetry'])>=2
        assert seconds<=result['stage_elapsed']<seconds+1 if cancel is None else result['aborted']
        assert result['primary_verdict']=='pass' if cancel is None else result['aborted']
        if case=='complete':
            assert result['auxiliary']['auxiliary_outcome'] in ('COMPLETED_WITH_WARNINGS','STOPPED'),result
            assert result['auxiliary']['executed_devices']==[identity],result
        if case=='cancel':assert result['auxiliary']['cleanup_confirmed'] and result['auxiliary']['executed_devices']==[identity] and result['auxiliary']['auxiliary_outcome']=='STOPPED',result
        if case=='temperature':assert result['auxiliary']['auxiliary_outcome']=='STOPPED' and result['auxiliary']['cleanup_confirmed'],result
    try:rpc('arbitrary-exec',command=['/bin/true'])
    except OSError:results['arbitrary_operation_rejected']=True
    else:raise AssertionError('arbitrary privileged operation accepted')
    try:rpc('terminal',session='../escape')
    except OSError:results['path_escape_rejected']=True
    else:raise AssertionError('arbitrary privileged path accepted')
    bad=config.to_dict();bad['intensity_percent']=True
    try:rpc('inspect',configuration=bad)
    except OSError:results['invalid_configuration_rejected']=True
    else:raise AssertionError('boolean intensity accepted')
    Path('/control/user/result.json').write_text(json.dumps(results,indent=2))


def run(deployment,identity):
    # This root entrypoint is never a host launcher.
    assert os.getuid()==0 and 'QEMU' in Path('/sys/class/dmi/id/sys_vendor').read_text()
    assert 'lvs_fixture=' in Path('/proc/cmdline').read_text()
    Path('/run').chmod(0o755)  # tmpfs fixture must model the native root-owned /run
    # Explicit fixture-only sensor injection in the generated guest launcher.
    launcher=deployment/'launch.py';text=launcher.read_text()
    needle="if integrated_serve or integrated_client:\n"
    injection='''if integrated_serve or integrated_client:
 from pathlib import Path
 from Modules.lvs_storage_thermal_service import RuntimePolicy
 original_runner=RuntimePolicy.runner
 def synthetic_runner(self):
  runner=original_runner(self)
  runner.temperature=lambda row:dict(value_c=65. if Path('/control/user/sensor-hot').exists() else 30.,critical_c=70.,warning_c=55.,complete=True,synthetic_VM_sensor=True)
  return runner
 RuntimePolicy.runner=synthetic_runner
'''
    assert needle in text
    launcher.write_text(text.replace(needle,injection))
    m=json.loads((deployment/'manifest.json').read_text());import hashlib
    m['files']['launch.py']=hashlib.sha256(launcher.read_bytes()).hexdigest()
    (deployment/'manifest.json').write_text(json.dumps(m))
    control=Path('/control/user');control.mkdir();os.chown(control,1000,1000);control.chmod(0o700)
    # Primary code is ordinary-user source; only the installed service is root.
    build=Path('/lvs/build');build.mkdir(exist_ok=True)
    import shutil
    shutil.copy2(deployment/'runtime/build/storage_thermal_launch.so',build/'storage_thermal_launch.so')
    server=subprocess.Popen(['/usr/bin/python3','-I','-B',str(launcher),'--serve-integrated'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        end=time.monotonic()+15
        while not Path('/run/lvs-thermal/1000.sock').exists() and time.monotonic()<end:
            assert server.poll() is None,server.communicate();time.sleep(.05)
        assert Path('/run/lvs-thermal/1000.sock').exists(),'runtime not listening'
        child=os.fork()
        if child==0:
            try:
                os.setgroups([]);os.setgid(1000);os.setuid(1000)
                os.execv('/usr/bin/python3',['/usr/bin/python3','-B','/lvs/scripts/storage_thermal_integrated_probe.py','--client',identity])
            except BaseException:
                import traceback;traceback.print_exc();os._exit(1)
            os._exit(0)
        _,status=os.waitpid(child,0)
        assert os.waitstatus_to_exitcode(status)==0,'unprivileged integrated caller failed'
        result=json.loads((control/'result.json').read_text())
        from Modules.lvs_storage_thermal_recovery import blocker,read_state,RecoveryScope
        marker=Path('/var/lib/lvs-thermal/storage_thermal_recovery_required.json')
        assert not blocker(marker) and read_state(marker)['state']=='CLEAN'
        result['canonical_CLEAN']=True
        # A conventional standalone owner excludes the integrated preview too.
        scope=RecoveryScope(marker).enter(evidence_directory='/control')
        try:
            child=os.fork()
            if child==0:
                try:
                    os.setgroups([]);os.setgid(1000);os.setuid(1000)
                    os.execv('/usr/bin/python3',['/usr/bin/python3','-B','/lvs/scripts/storage_thermal_integrated_probe.py','--blocked-client',identity])
                except BaseException:os._exit(1)
                os._exit(0)
            _,status=os.waitpid(child,0);assert os.waitstatus_to_exitcode(status)==0
            result['standalone_mutual_exclusion']=True
        finally:scope.resolve(cleanup_confirmed=True);scope.close()
        # Every request re-verifies installed tool bytes, not merely the socket.
        guard=deployment/'runtime/build/storage_thermal_guard';original=guard.read_bytes()
        try:
            guard.write_bytes(original+b'tampered')
            p=subprocess.run(['/usr/bin/python3','-B','/lvs/scripts/storage_thermal_integrated_probe.py','--untrusted-client',identity],
                preexec_fn=lambda:(os.setgroups([]),os.setgid(1000),os.setuid(1000)),timeout=20)
            assert p.returncode==0;result['untrusted_tool_rejected']=True
        finally:guard.write_bytes(original)
        # Wrong credentials never reach privileged topology/device operations.
        p=subprocess.run(['/usr/bin/python3','-B','/lvs/scripts/storage_thermal_integrated_probe.py','--untrusted-client',identity],
            preexec_fn=lambda:(os.setgroups([]),os.setgid(1001),os.setuid(1001)),timeout=20)
        assert p.returncode==0;result['missing_authorization_rejected']=True
        # Kill only the fixture-owned handler with a stable pidfd after real reads.
        # This is intentionally last: unresolved ARMED must survive, never cleared.
        p=subprocess.Popen(['/usr/bin/python3','-B','/lvs/scripts/storage_thermal_integrated_probe.py','--death-client',identity],
            preexec_fn=lambda:(os.setgroups([]),os.setgid(1000),os.setuid(1000)))
        limit=time.monotonic()+55
        while not (control/'kill-ready').exists() and time.monotonic()<limit:
            assert p.poll() is None,'client exited before real device activity';time.sleep(.1)
        assert (control/'kill-ready').exists(),'no real activity before handler-death control'
        children=Path(f'/proc/{server.pid}/task/{server.pid}/children').read_text().split()
        handlers=[int(v) for v in children if b'--integrated-client' in Path(f'/proc/{v}/cmdline').read_bytes()]
        assert len(handlers)==1,handlers
        authority=os.pidfd_open(handlers[0])
        try:signal.pidfd_send_signal(authority,signal.SIGKILL)
        finally:os.close(authority)
        assert p.wait(timeout=70)==0
        result['handler_death']=json.loads((control/'death/result.json').read_text())
        assert read_state(marker)['state']=='ARMED' and blocker(marker)
        fresh=subprocess.run(['/usr/bin/python3','-B','-c',
            "import sys;sys.path.insert(0,'/lvs');from pathlib import Path;from Modules.lvs_storage_thermal_recovery import blocker;assert blocker(Path('/var/lib/lvs-thermal/storage_thermal_recovery_required.json'))"],timeout=10)
        assert fresh.returncode==0;result['fresh_process_ARMED_blocker']=True
        return result
    finally:
        server.terminate()
        try:server.wait(timeout=10)
        except subprocess.TimeoutExpired:server.kill();server.wait()
        out,err=server.communicate();Path('/control/runtime.stderr').write_bytes(err)
        shutil.copytree('/var/lib/lvs-thermal','/control/runtime-state',dirs_exist_ok=True)


if __name__=='__main__':
    assert (os.getuid()==1000 or os.getuid()==1001 and sys.argv[1]=='--untrusted-client') and 'QEMU' in Path('/sys/class/dmi/id/sys_vendor').read_text() and 'lvs_fixture=' in Path('/proc/cmdline').read_text(),'not a sealed unprivileged VM fixture'
    sys.path.insert(0,'/lvs')
    if sys.argv[1]=='--client':unprivileged(sys.argv[2])
    elif sys.argv[1]=='--untrusted-client':
        from Modules.lvs_storage_thermal_runtime import rpc
        from Modules.lvs_storage_thermal import ThermalConfig
        try:rpc('inspect',configuration=ThermalConfig().to_dict())
        except (OSError,ValueError,EOFError):pass
        else:raise AssertionError('untrusted runtime request accepted')
    elif sys.argv[1]=='--death-client':
        from Modules.lvs_storage_thermal import ThermalConfig
        config=ThermalConfig(access_mode='shared_readonly_opt_in',selection='individual',device_ids=[sys.argv[2]],
            intensity_percent=25,aggregate_iops_limit=128,aggregate_bps_limit=8388608,duration_seconds=40,temperature_limit_c=60)
        directory=Path('/control/user/death');directory.mkdir()
        result=primary(None,config.to_dict(),directory,40,death_control=True)
        (directory/'result.json').write_text(json.dumps(result,indent=2))
        assert result['primary_verdict']=='pass' and result['auxiliary']['auxiliary_outcome']=='ERROR',result
        assert result['auxiliary']['cleanup_confirmed'] is False,result
    elif sys.argv[1]=='--blocked-client':
        from Modules.lvs_storage_thermal import ThermalConfig
        from Modules.lvs_storage_thermal_runtime import preview
        result=preview(ThermalConfig(access_mode='shared_readonly_opt_in',selection='individual',device_ids=[sys.argv[2]],aggregate_iops_limit=128,aggregate_bps_limit=8388608))
        assert result['status']=='BLOCKED',result
    else:raise ValueError('unknown sealed client operation')
