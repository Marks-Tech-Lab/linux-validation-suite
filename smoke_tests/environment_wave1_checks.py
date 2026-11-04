"""Wave 1 maintenance fixtures; all environments and lock files are temporary."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

import lvs_environment_manager as em
from smoke_tests.environment_manager_checks import Fixture, rejects, ROOT


def prepared(directory):
    f=Fixture(directory)
    f.info.update(implementation='CPython',soabi='cpython-314-test',cache_tag='cpython-314',free_threaded=False)
    assert f.manager.create_or_repair()
    return f


def run_environment_upgrade_identity_checks():
    with TemporaryDirectory() as directory:
        f=prepared(directory);marker=f.manager.venv/em.MARKER;original=marker.read_bytes()
        f.info['version']=[3,14,1]
        assert f.manager.inspect()['valid']
        assert any('patch update' in v for v in f.manager.inspect()['warnings'])
        f.base.write_text('replacement at same executable path')
        assert any('bytes changed' in v for v in f.manager.inspect()['warnings'])
        assert f.manager.diagnostics()['recommendation']['action']=='reuse'
        assert marker.read_bytes()==original # inspection cannot rewrite identity
        for key,value in [('soabi','incompatible-abi'),('bits',32),('implementation','another-python'),('free_threaded',True)]:
            old=f.info[key];f.info[key]=value
            assert not f.manager.inspect()['valid'],key
            f.info[key]=old
        alias=f.root/'base-alias';alias.symlink_to(f.base)
        record=json.loads(original);record['base_executable']=str(alias);marker.write_text(json.dumps(record))
        assert f.manager.inspect()['valid'] # path aliases are not upgrades
        marker.write_bytes(original)
        f.info['version']=[3,15,0]
        assert not f.manager.inspect()['valid']
        assert f.manager.diagnostics()['recommendation']['action']=='rebuild'
        assert f.manager.rebuild() and f.manager.inspect()['valid']
        assert list(f.root.glob('.venv.backup-*'))
    with TemporaryDirectory() as directory:
        f=prepared(directory);f.base.unlink()
        assert not f.manager.inspect()['valid']
        assert any('no longer exists' in v for v in f.manager.inspect()['issues'])
    with TemporaryDirectory() as directory:
        f=prepared(directory);marker=f.manager.venv/em.MARKER;record=json.loads(marker.read_text())
        old_os=record['os'];record['os']=dict(old_os,VERSION_ID='previous')
        marker.write_text(json.dumps(record));assert f.manager.inspect()['valid']
        record['os']=dict(old_os,ID='different-distro');marker.write_text(json.dumps(record))
        assert not f.manager.inspect()['valid']
        record['os']=old_os;record['optional_groups']=None;marker.write_text(json.dumps(record))
        assert not f.manager.inspect()['valid'];assert f.manager.groups()==['baseline']
    with TemporaryDirectory() as directory:
        f=prepared(directory);(f.manager.venv/em.MARKER).unlink()
        assert f.manager.inspect()['valid'] and any('Unmarked' in x for x in f.manager.inspect()['warnings'])
        f.package_import_error=True
        assert f.manager.diagnostics()['recommendation']['action']=='sync'
        f.package_import_error=False;f.pip_check_error=True
        assert f.manager.diagnostics()['recommendation']['action']=='sync'


def run_environment_guided_workflow_checks():
    with TemporaryDirectory() as directory:
        f=prepared(directory)
        f.manager.show_inspection(f.manager.diagnostics())
        assert any('Recommended action: Keep using this environment' in v for v in f.output)
        assert not any('"contract_id"' in v for v in f.output)
        f.pip=False;assert f.manager.diagnostics()['recommendation']['action']=='repair'
        # Continue directly from inspection to repair, without another main menu.
        with patch.object(f.manager,'choose_python'),patch.object(f.manager,'choose_packages'):
            assert f.manager.guided_maintenance()
        assert f.manager.diagnostics()['python_baseline_ready']
        f.info['version']=[3,15,0]
        with patch.object(f.manager,'choose_python'),patch.object(f.manager,'choose_packages'):
            assert f.manager.guided_maintenance('sync') # incompatible sync is redirected to rebuild
        assert f.manager.inspect()['valid'] and list(f.root.glob('.venv.backup-*'))
        f.manager.ask=lambda _: '2';f.package_import_error=True
        count=len(f.calls);assert not f.manager.guided_maintenance()
        assert not any('install' in args for args,_ in f.calls[count:])
        f.package_import_error=False;f.pip=False;f.info['ensurepip']=False
        assert f.manager.diagnostics()['recommendation']['action']=='manual'
    with TemporaryDirectory() as directory:
        f=Fixture(directory);f.manager.selected=None
        wrong=dict(f.info,architecture='not-this-machine',prefix='base',base_prefix='base')
        old=dict(f.info,version=[3,9,9],prefix='base',base_prefix='base')
        good=dict(f.info,prefix='base',base_prefix='base')
        with patch.object(f.manager,'candidates',return_value=[{'path':'wrong','details':wrong},{'path':'old','details':old},{'path':str(f.base),'details':good}]):
            assert f.manager.selected_python()[0]==str(f.base)


def run_environment_maintenance_lock_checks():
    with TemporaryDirectory() as directory:
        f=Fixture(directory);other=em.EnvironmentManager(f.root)
        before=set(f.root.iterdir());assert f.manager.lock_status()=='idle';assert set(f.root.iterdir())==before
        with f.manager.maintenance_lock():
            assert other.lock_status()=='active'
            rejects(other.create_or_repair,'Another environment maintenance')
            code='import sys;sys.path.insert(0,sys.argv[1]);import lvs_environment_manager as e\nm=e.EnvironmentManager(sys.argv[2])\ntry:\n with m.maintenance_lock():pass\nexcept e.EnvironmentError:sys.exit(17)'
            result=subprocess.run([sys.executable,'-B','-I','-c',code,str(ROOT),str(f.root)],capture_output=True)
            assert result.returncode==17,result.stderr
        with other.maintenance_lock():pass # persistent file/PID is not a stale lease
        # The installer's inherited FD retains the kernel lock after the manager
        # closes its own reference (also what happens when the manager dies).
        with f.manager.maintenance_lock():
            child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(1)'],pass_fds=(f.manager._lock_fd,))
        try:rejects(other.create_or_repair,'Another environment maintenance')
        finally:child.wait(timeout=5)
        with other.maintenance_lock():pass
        (f.root/em.LOCK).unlink();sentinel=f.root/'keep';sentinel.write_text('unchanged')
        (f.root/em.LOCK).symlink_to(sentinel)
        rejects(other.create_or_repair);assert sentinel.read_text()=='unchanged'
        (f.root/em.LOCK).unlink();(f.root/em.LOCK).write_text('unrelated')
        rejects(other.create_or_repair,'unrelated');assert (f.root/em.LOCK).read_text()=='unrelated'


def interrupted(f, with_backup=True):
    old=f.manager.path_identity(f.manager.venv);record={'operation':'rebuild','status':'running','groups':['baseline','google'],'old_identity':old}
    if with_backup:
        backup=f.manager.unique_backup('backup');f.manager.venv.rename(backup);record['backup']=str(backup)
    f.manager.venv.mkdir();(f.manager.venv/'partial').write_text('preserve partial')
    record['new_identity']=f.manager.path_identity(f.manager.venv);f.manager.save_operation(record)
    return record


def run_environment_interrupted_recovery_checks():
    with TemporaryDirectory() as directory:
        f=prepared(directory);assert f.manager.sync('google')
        (f.manager.venv/'keep').write_text('old environment')
        record=interrupted(f)
        assert f.manager.diagnostics()['recommendation']['action']=='recover'
        rejects(f.manager.rebuild,'interrupted')
        f.manager.ask=lambda _: '2';assert not f.manager.recover_interrupted()
        assert Path(record['backup']).exists()
        f.manager.ask=lambda _: '1';assert f.manager.recover_interrupted()
        assert (f.manager.venv/'keep').read_text()=='old environment'
        assert (next(f.root.glob('.venv.failed-*'))/'partial').read_text()=='preserve partial'
        assert f.manager.groups()==['baseline','google']
    with TemporaryDirectory() as directory:
        f=Fixture(directory);interrupted(f,False)
        assert f.manager.recover_interrupted() and not f.manager.venv.exists()
        assert f.manager.create_or_repair()
    with TemporaryDirectory() as directory:
        f=prepared(directory);record=interrupted(f)
        original=Path.rename
        def fail(path,target):
            if path==Path(record['backup']):raise OSError('restore denied')
            return original(path,target)
        with patch.object(Path,'rename',fail):rejects(f.manager.recover_interrupted,'restore denied')
        assert Path(record['backup']).exists() and list(f.root.glob('.venv.failed-*'))
        assert f.manager.recover_interrupted() # retry restoration without deleting evidence
    with TemporaryDirectory() as directory:
        f=prepared(directory);record=interrupted(f)
        record['new_identity']=[0,0];f.manager.save_operation(record)
        rejects(f.manager.recover_interrupted,'identity');assert (f.manager.venv/'partial').exists()
        record['status']='cleanup_unconfirmed';f.manager.save_operation(record)
        rejects(f.manager.create_or_repair,'unconfirmed')
        assert f.manager.diagnostics()['recommendation']['action']=='manual'


def run_environment_partial_sync_safety_checks():
    for failure in ['interrupt','cleanup_unconfirmed']:
        with TemporaryDirectory() as directory:
            f=prepared(directory);original=f.manager.runner;cfg=(f.manager.venv/'pyvenv.cfg').read_bytes()
            def interrupted_install(args,**kwargs):
                if '-m' in args and args[args.index('-m')+1]=='pip' and 'install' in args:
                    f.actual_versions['textual']='partial'
                    if failure=='interrupt':raise KeyboardInterrupt()
                    raise em.EnvironmentProcessError('injected unconfirmed installer')
                return original(args,**kwargs)
            f.manager.runner=interrupted_install
            try:f.manager.sync('google')
            except (KeyboardInterrupt,em.EnvironmentProcessError):pass
            else:raise AssertionError('Interrupted sync reported success')
            assert (f.manager.venv/'pyvenv.cfg').read_bytes()==cfg
            assert not list(f.root.glob('.venv.backup-*'))
            assert f.manager.operation_record()['status']==('failed' if failure=='interrupt' else failure)
            assert f.manager.groups()==['baseline','google']
            assert f.manager.diagnostics()['recommendation']['action']==('sync' if failure=='interrupt' else 'manual')
    with TemporaryDirectory() as directory:
        f=prepared(directory);(f.manager.venv/'keep').write_text('recoverable')
        original=f.manager.runner
        def disk_full(args,**kwargs):
            if '-m' in args and args[args.index('-m')+1]=='pip' and 'install' in args:
                return subprocess.CompletedProcess(args,1,'No space left on device')
            return original(args,**kwargs)
        f.manager.runner=disk_full;rejects(f.manager.rebuild,'No space left')
        assert (f.manager.venv/'keep').read_text()=='recoverable'
        assert list(f.root.glob('.venv.failed-*'))
        assert any('Previous environment restored: compatible' in line for line in f.output)
        assert not any('"recorded_environment"' in line for line in f.output)
    with TemporaryDirectory() as directory:
        f=prepared(directory);sentinel=f.root/'results';sentinel.mkdir();(sentinel/'keep').write_text('evidence')
        f.fail_install=True;rejects(lambda:f.manager.sync('google'),'repository unavailable')
        assert f.manager.operation_record()['status']=='failed'
        assert f.manager.groups()==['baseline','google'] # preserve intent before marker publication
        f.fail_install=False;assert f.manager.rebuild()
        assert f.manager.diagnostics()['python_selected_groups_ready']
        assert f.manager.groups()==['baseline','google'] and (sentinel/'keep').read_text()=='evidence'
        before=(f.manager.venv/'pyvenv.cfg').read_bytes()
        with patch.object(f.manager,'save_operation',side_effect=OSError('No space left on device')):
            rejects(f.manager.rebuild,'No space left')
        assert (f.manager.venv/'pyvenv.cfg').read_bytes()==before
        marker=f.manager.venv/em.MARKER
        unrelated=f.root/'unrelated';unrelated.write_text('retain')
        # Atomic marker publication must not follow a preexisting .tmp symlink.
        (f.manager.venv/(em.MARKER+'.tmp')).symlink_to(unrelated)
        assert f.manager.sync() and unrelated.read_text()=='retain'
        record=json.loads(marker.read_text());assert record['optional_groups']==['google']


def run_environment_real_upgrade_portability_checks():
    candidates=[getattr(sys,'_base_executable',sys.executable),shutil.which('python3'),shutil.which('python3.14')]
    seen=set()
    for candidate in candidates:
        if not candidate:continue
        base=str(Path(candidate).resolve())
        if base in seen:continue
        seen.add(base)
        supported=subprocess.run([base,'-I','-c','import venv'],capture_output=True).returncode==0
        if not supported:
            print('SKIP optional installed interpreter without venv:',base)
            continue
        with TemporaryDirectory(prefix="lvs Wave1's ") as directory:
            root=Path(directory);(root/'scripts').mkdir()
            shutil.copyfile(ROOT/'scripts/lvs_python_policy.sh',root/'scripts/lvs_python_policy.sh')
            subprocess.run([base,'-I','-m','venv','--without-pip',str(root/'.venv')],check=True,capture_output=True)
            manager=em.EnvironmentManager(root,selected=base)
            assert manager.inspect()['valid']
            with manager.maintenance_lock():manager.write_marker(['baseline','google'])
            with manager.maintenance_lock():manager.save_operation({'operation':'synchronize','status':'completed','groups':['baseline','google']})
            state=manager.inspect();assert state['valid'] and state['recorded_environment']['abi']['soabi']
            cfg=manager.venv/'pyvenv.cfg';text=cfg.read_text();version=state['interpreter']['version'];previous='{}.{}.0'.format(*version)
            changed='\n'.join('version = '+previous if l.startswith('version = ') else l for l in text.splitlines())+'\n'
            cfg.write_text(changed);assert manager.inspect()['valid'] # patch update remains compatible
            cfg.write_text(text.replace('version = '+'.'.join(map(str,version)),'version = 3.9.0'))
            assert not manager.inspect()['valid'];cfg.write_text(text)
            destination=root/'relocated';manager.venv.rename(destination)
            # Reuse at another project root must not silently accept old script paths.
            moved=root/'moved';moved.mkdir();shutil.copytree(root/'scripts',moved/'scripts');destination.rename(moved/'.venv')
            relocated=em.EnvironmentManager(moved,selected=base)
            assert not relocated.inspect()['valid']
            assert not relocated.inspect().get('maintenance_error')
            assert relocated.diagnostics()['recommendation']['action']=='rebuild'
