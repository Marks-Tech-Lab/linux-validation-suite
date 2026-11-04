"""Isolated bootstrap/repair fixtures; never maintain the development .venv."""
from copy import deepcopy
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import lvs_environment_manager as em
from Modules.lvs_python_environment import PYTHON_GROUPS, python_policy, requirement_pins

ROOT = Path(__file__).resolve().parents[1]


class Fixture:
    def __init__(self, directory, confirm='y'):
        self.root = Path(directory)
        (self.root/'scripts').mkdir()
        for name in ['requirements.txt','requirements-google.txt','scripts/setup_venv.sh','scripts/lvs_python_policy.sh']:
            shutil.copyfile(ROOT/name,self.root/name)
        self.base = self.root/'base-python'
        self.base.write_text('fixture base')
        self.calls = []
        self.pip = True
        self.installed = set()
        self.actual_versions = {}
        self.fail_install = False
        self.fail_ensurepip = False
        self.interrupt = False
        self.package_import_error = False
        self.pip_check_error = False
        self.info = {'version':[3,14,0], 'base_executable':str(self.base),
                     'architecture':em.platform.machine(), 'platform_tag':'fixture', 'bits':64,
                     'venv':True,'ensurepip':True}
        self.output = []
        self.manager = em.EnvironmentManager(self.root,runner=self.run,ask=lambda _:confirm,
                                             output=self.output.append,selected=str(self.base))

    def seed(self):
        v=self.root/'.venv';(v/'bin').mkdir(parents=True)
        (v/'bin/python').write_text('fixture interpreter')
        (v/'pyvenv.cfg').write_text('home = {}\ninclude-system-site-packages = false\nversion = 3.14.0\ncommand = fixture -m venv {}\n'.format(self.root,v))
        return v

    def run(self, args, **kwargs):
        self.calls.append((list(map(str,args)),kwargs))
        args=list(map(str,args));rc=0;out=''
        if '-c' in args:
            code=args[args.index('-c')+1]
            if code==em.PROBE:
                info=deepcopy(self.info)
                if args[0]==str(self.manager.python):
                    if not self.manager.python.exists():
                        raise FileNotFoundError('broken interpreter symlink')
                    info.update(prefix=str(self.manager.venv),base_prefix=str(self.root),executable=args[0])
                else:info.update(prefix=str(self.root),base_prefix=str(self.root),executable=args[0])
                out=json.dumps(info)
            elif code==em.PACKAGES:
                request=json.loads(args[-1]);out=json.dumps({
                    'packages':{n:{'installed':self.actual_versions.get(n,v) if n in self.installed else None,'expected':v,'matches':n in self.installed and self.actual_versions.get(n,v)==v} for n,v in request['pins']},
                    'imports':{n:{'importable':not self.package_import_error and (('textual' in self.installed) if n=='textual' else {'google-auth','google-api-python-client'}.issubset(self.installed))} for n in request['imports']}})
            elif code==em.GOOGLE:
                out=json.dumps({'ready':False,'credential_exists':False,'shared_drive_id_configured':False,
                                'dns_ok':False,'python_modules':{n:True for n in PYTHON_GROUPS['google']['imports']}})
            elif code in [em.NATIVE,em.DEPENDENCIES]:out='existing integration invoked'
            else:raise AssertionError(code[:80])
        elif '-m' in args:
            module=args[args.index('-m')+1]
            if module=='venv':
                assert args[-1]==str(self.root/'.venv') # final path, never a renamed temporary venv
                self.seed()
                if self.interrupt:raise KeyboardInterrupt()
            elif module=='ensurepip':
                rc=int(self.fail_ensurepip)
                if not rc:self.pip=True
                out='ensurepip unavailable' if rc else ''
            elif module=='pip':
                assert args[0]==str(self.manager.python) and '-I' in args
                assert not any(k in kwargs['env'] for k in ('PIP_TARGET','PIP_PREFIX','PIP_USER','PYTHONPATH','PYTHONHOME'))
                assert kwargs['env']['PIP_CONFIG_FILE']==os.devnull
                if '--version' in args:rc=0 if self.pip else 1
                elif 'install' in args:
                    assert '--require-virtualenv' in args and '--no-user' in args
                    if self.fail_install:rc=1;out='No matching distribution / repository unavailable'
                    else:
                        for i,a in enumerate(args):
                            if a=='-r':
                                name=Path(args[i+1]).name
                                group=next(g for g,v in PYTHON_GROUPS.items() if v['requirements']==name)
                                self.installed.update(n for n,_ in requirement_pins(self.root,group))
                                self.actual_versions.update(dict(requirement_pins(self.root,group)))
                elif 'check' in args:rc=int(self.pip_check_error);out='inconsistent dependency' if rc else 'No broken requirements found'
                else:raise AssertionError(args)
            else:raise AssertionError(args)
        else:raise AssertionError(args)
        return SimpleNamespace(returncode=rc,stdout=out)


def rejects(call, text=None):
    try:call()
    except (em.EnvironmentError,OSError,ValueError) as error:
        if text:assert text in str(error),str(error)
    else:raise AssertionError('Invalid maintenance operation accepted')


def run_environment_bootstrap_checks():
    # -I and -S exclude user/PYTHONPATH/site packages. No pip/Textual/gcc needed.
    result=subprocess.run([sys.executable,'-I','-S',str(ROOT/'lvs_environment_manager.py'),'--help'],capture_output=True,text=True,check=True)
    assert 'wheelhouse' in result.stdout
    result=subprocess.run([sys.executable,'-I','-S',str(ROOT/'lvs_environment_manager.py')],input='8\n',capture_output=True,text=True,check=True)
    assert '1. Check environment' in result.stdout and '8. Exit' in result.stdout
    for name in ['lvs_environment_manager.py','Modules/lvs_python_environment.py']:
        ast.parse((ROOT/name).read_text(),feature_version=(3,6))
    probe="import sys;sys.path.insert(0,sys.argv[1]);import lvs_environment_manager;print('Modules.lvs_core' in sys.modules);print('textual' in sys.modules)"
    result=subprocess.check_output([sys.executable,'-I','-S','-c',probe,str(ROOT)],text=True)
    assert result.splitlines()==['False','False']
    assert python_policy(ROOT)=={'minimum':(3,10),'tested':(3,14)}
    assert requirement_pins(ROOT,'baseline')[0][0]=='textual'
    assert requirement_pins(ROOT,'baseline')[0][1] in (ROOT/'requirements.txt').read_text()
    with TemporaryDirectory() as tmp:
        f=Fixture(tmp);f.info['version']=[3,9,0]
        rejects(f.manager.selected_python,'minimum')
        assert not (f.root/'.venv').exists()
        f.info['version']=[3,14,0];f.info['venv']=False
        rejects(f.manager.create_or_repair,'venv/ensurepip')
        assert not (f.root/'.venv').exists()
        f.info['venv']=True;f.info['ensurepip']=False
        rejects(f.manager.create_or_repair,'venv/ensurepip')
        assert not (f.root/'.venv').exists()


def run_environment_install_sync_checks():
    with TemporaryDirectory() as tmp, patch.dict(os.environ,{'PIP_TARGET':'/unrelated','PIP_USER':'1','PYTHONPATH':'/unrelated'}):
        f=Fixture(tmp);sentinel=f.root/'results'/'retained.json';sentinel.parent.mkdir();sentinel.write_text('retained')
        assert f.manager.create_or_repair()
        report=f.manager.diagnostics();assert report['python_baseline_ready']
        assert report['scope']=='bootstrap_python_only_not_hardware_readiness'
        assert not all(v['matches'] for v in report['python_groups']['google']['packages'].values())
        state=f.manager.inspect();assert state['valid'] and state['pip']
        assert (f.root/'.venv'/em.MARKER).exists()
        assert not any('--upgrade' in args for args,_ in f.calls)
        assert f.manager.sync() and sentinel.read_text()=='retained'
        assert f.manager.sync('google');assert f.manager.groups()==['baseline','google']
        (f.manager.venv/em.MARKER).unlink()
        f.actual_versions['google-auth']='old-version'
        assert f.manager.groups()==['baseline','google'] # retain/sync installed optional pins even when stale
        assert f.manager.sync()
        drive=f.manager.google_readiness()
        assert all(v['matches'] for v in drive['python_dependencies']['packages'].values())
        assert drive['existing_uploader_readiness']['ready'] is False
        assert not drive['existing_uploader_readiness']['credential_exists']
        assert not drive['existing_uploader_readiness']['shared_drive_id_configured']
        assert not drive['existing_uploader_readiness']['dns_ok']
        assert drive['python_dependencies_installed'] and drive['python_modules_importable']
        assert drive['overall_uploader_readiness'] is False
        # Offline install preserves project pins and never upgrades packaging tools.
        wheels=f.root/'wheels';wheels.mkdir();f.manager.wheelhouse=wheels
        assert f.manager.sync()
        assert any('--no-index' in args and '--find-links' in args for args,_ in f.calls)
        f.fail_install=True;rejects(f.manager.sync,'repository unavailable')
        assert f.manager.inspect()['valid'] and sentinel.read_text()=='retained'
        f.fail_install=False
        f.manager.wheelhouse=f.root/'absent-local-packages'
        rejects(f.manager.sync,'Local package directory')
        f.manager.wheelhouse=wheels
        f.package_import_error=True
        rejects(f.manager.sync,'Post-install')
        f.package_import_error=False;f.pip_check_error=True
        rejects(f.manager.sync,'inconsistent')
        assert sentinel.read_text()=='retained'


def run_environment_repair_identity_checks():
    with TemporaryDirectory() as tmp:
        f=Fixture(tmp);f.seed();f.pip=False;assert not f.manager.inspect()['pip']
        f.fail_ensurepip=True;rejects(f.manager.create_or_repair,'ensurepip unavailable')
        assert f.manager.python.exists()
        f.fail_ensurepip=False;assert f.manager.create_or_repair()
        marker=f.manager.venv/em.MARKER;recorded=json.loads(marker.read_text())
        for key,value in [('architecture','other-architecture'),('root','/previous/project'),('os',{'ID':'other-linux'}),('machine_id','other-machine')]:
            bad=dict(recorded);bad[key]=value;marker.write_text(json.dumps(bad));assert not f.manager.inspect()['valid'];marker.write_text(json.dumps(recorded))
        marker.write_text('broken JSON');assert not f.manager.inspect()['valid'];marker.write_text(json.dumps(recorded))
        cfg=f.manager.venv/'pyvenv.cfg';normal=cfg.read_text()
        cfg.write_text(normal.replace('version = 3.14.0','version = 3.13.0'));assert not f.manager.inspect()['valid']
        cfg.write_text(normal.replace(str(f.manager.venv),'/old/.venv'));assert not f.manager.inspect()['valid']
        cfg.write_text(normal.replace('include-system-site-packages = false','include-system-site-packages = true'));assert not f.manager.inspect()['valid']
        cfg.write_text(normal)
        base_info=deepcopy(f.info)
        f.info['version']=[3,13,0]
        rejects(lambda:f.manager.check_selected_matches({'interpreter':base_info}),'differs')
        f.info=base_info
        recorded['optional_groups']=['google'];marker.write_text(json.dumps(recorded))
        f.manager.python.unlink();f.manager.python.symlink_to('/missing/python');assert not f.manager.inspect()['valid']
        assert f.manager.groups()==['baseline','google']
    # Architecture identity is not inferred from CPU model names.
    for architecture in ['aarch64','x86_64']:
        with TemporaryDirectory() as tmp, patch.object(em.platform,'machine',return_value=architecture):
            f=Fixture(tmp);assert f.manager.create_or_repair()
            assert f.manager.inspect()['valid']
            f.info['architecture']='x86_64' if architecture=='aarch64' else 'aarch64'
            assert not f.manager.inspect()['valid']


def run_environment_rebuild_preservation_checks():
    # A timed-out installer must not leave descendants writing to the restored
    # environment. This fixture only sleeps; it performs no installation/workload.
    with TemporaryDirectory() as tmp:
        pidfile=Path(tmp)/'child.pid'
        code="import subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);Path(sys.argv[1]).write_text(str(p.pid));time.sleep(30)"
        try:
            em.run_managed_command([sys.executable,'-B','-c',code,str(pidfile)],timeout=.5,
                                   stdout=subprocess.PIPE,stderr=subprocess.STDOUT,universal_newlines=True)
        except subprocess.TimeoutExpired:pass
        else:raise AssertionError('Installer timeout ignored')
        pid=int(pidfile.read_text());deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            status=Path('/proc')/str(pid)/'stat'
            if not status.exists() or status.read_text().split(') ')[1].startswith('Z'):break
            time.sleep(.01)
        else:raise AssertionError('Cancelled installer descendant remains running')
    fake=SimpleNamespace(pid=12345,communicate=__import__('unittest.mock',fromlist=['Mock']).Mock(side_effect=[KeyboardInterrupt(),(None,None)]))
    with patch.object(em.subprocess,'Popen',return_value=fake),patch.object(em.os,'killpg') as kill:
        try:em.run_managed_command(['fixture'],timeout=1)
        except KeyboardInterrupt:pass
        else:raise AssertionError('Cancellation swallowed')
        kill.assert_called_once_with(12345,em.signal.SIGKILL)
    for failure in ['install','interrupt']:
        with TemporaryDirectory() as tmp:
            f=Fixture(tmp);v=f.seed();(v/'keep.txt').write_text('old installation')
            if failure=='install':f.fail_install=True
            else:f.interrupt=True
            try:f.manager.rebuild()
            except (em.EnvironmentError,KeyboardInterrupt):pass
            else:raise AssertionError('Rebuild failure not surfaced')
            assert (v/'keep.txt').read_text()=='old installation'
            assert list(f.root.glob('.venv.failed-*'))
            assert not list(f.root.glob('.venv.backup-*')) # restored, not destroyed
            assert f.manager.inspect()['valid']
    with TemporaryDirectory() as tmp:
        f=Fixture(tmp);v=f.seed();(v/'keep.txt').write_text('old installation');f.fail_install=True
        rename=Path.rename
        def fail_restore(path,target):
            if path.name.startswith('.venv.backup-'):raise OSError('injected restore failure')
            return rename(path,target)
        with patch.object(Path,'rename',fail_restore):
            rejects(f.manager.rebuild,'recovery incomplete')
        assert (next(f.root.glob('.venv.backup-*'))/'keep.txt').read_text()=='old installation'
        assert list(f.root.glob('.venv.failed-*')) and not v.exists()
    with TemporaryDirectory() as tmp:
        f=Fixture(tmp);v=f.seed();(v/'keep.txt').write_text('old installation')
        original=f.manager.runner
        def unknown_cleanup(args,**kwargs):
            if '-m' in args and args[args.index('-m')+1]=='venv':
                f.seed();raise em.EnvironmentProcessError('injected unreaped installer')
            return original(args,**kwargs)
        f.manager.runner=unknown_cleanup
        rejects(f.manager.rebuild,'cleanup is unconfirmed')
        assert v.exists() and (next(f.root.glob('.venv.backup-*'))/'keep.txt').read_text()=='old installation'
        assert not list(f.root.glob('.venv.failed-*')) # no path restoration while a process may still write
    with TemporaryDirectory() as tmp:
        f=Fixture(tmp);v=f.seed();(v/'keep.txt').write_text('old installation')
        assert f.manager.rebuild();backups=list(f.root.glob('.venv.backup-*'));assert len(backups)==1
        assert (backups[0]/'keep.txt').read_text()=='old installation'
        assert f.manager.inspect()['valid'] and str(v) in (v/'pyvenv.cfg').read_text()
    with TemporaryDirectory() as tmp:
        f=Fixture(tmp,confirm='n');f.seed();before=(f.manager.venv/'pyvenv.cfg').read_bytes()
        assert f.manager.rebuild() is False and f.manager.create_or_repair() is False
        assert not any('-m' in a and a[a.index('-m')+1] in ['venv','ensurepip','pip'] and ('install' in a or 'venv' in a) for a,_ in f.calls)
        assert (f.manager.venv/'pyvenv.cfg').read_bytes()==before
    for symlink in [False,True]:
        with TemporaryDirectory() as tmp:
            f=Fixture(tmp);unrelated=f.root/'unrelated';unrelated.mkdir();(unrelated/'keep').write_text('keep')
            if symlink:f.manager.venv.symlink_to(unrelated)
            else:f.manager.venv.mkdir();(f.manager.venv/'keep').write_text('keep')
            rejects(f.manager.rebuild,'unrelated')
            assert (unrelated/'keep').read_text()=='keep'


def run_environment_integration_checks():
    with TemporaryDirectory() as tmp:
        f=Fixture(tmp);f.seed()
        assert f.manager.bridge(em.DEPENDENCIES,'existing checker?')
        assert f.manager.bridge(em.NATIVE,'existing helpers?')
        assert any(em.DEPENDENCIES in a for a,_ in f.calls)
        assert any(em.NATIVE in a for a,_ in f.calls)
        assert 'DependencyReportManager' in em.DEPENDENCIES and 'run_dependency_check' in em.DEPENDENCIES
        assert 'SettingsManager' not in em.DEPENDENCIES
        assert 'privileged_helper_enabled=False' in em.DEPENDENCIES
        assert 'NativeHelperRuntimeService' in em.NATIVE and 'executable_snapshot' in em.NATIVE
        assert 'native_cpu_helper_binary_name' in em.NATIVE and 'native_memory_helper_binary_name' in em.NATIVE
        assert '--print-resolved-mode' in em.NATIVE and '--help' in em.NATIVE
        assert 'TemporaryDirectory' in em.NATIVE # fresh-source builds, not stale existing binary acceptance
        f.manager.ask=lambda _: 'n';count=len(f.calls);assert f.manager.bridge(em.NATIVE,'cancel?') is False
        assert all('-c' in a and a[a.index('-c')+1]==em.PROBE or '-m' in a and '--version' in a for a,_ in f.calls[count:])
        answers=iter(['invalid','8']);f.manager.ask=lambda _:next(answers);f.manager.menu()
        assert any('1 to 8' in line for line in f.output)
        f.manager.ask=lambda _:(_ for _ in ()).throw(EOFError());f.manager.menu()
    # Real integration with the existing compiler-discovery path: no compiler,
    # no build directory creation, no native workload and no environment writes.
    result=subprocess.run([sys.executable,'-I','-c',em.NATIVE,str(ROOT)],cwd=str(ROOT),
                          env={**os.environ,'PATH':'','PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True)
    assert result.returncode!=0 and 'No existing LVS C compiler' in result.stderr
    with TemporaryDirectory() as tmp:
        path=Path(tmp)/'os-release';path.write_text('ID=bazzite\nPRETTY_NAME="Bazzite Linux"\nVERSION_ID=44\n')
        with patch.object(em.shutil,'which',side_effect=lambda n:'/usr/bin/'+n if n=='rpm-ostree' else None):
            system=em.system_environment(path)
        assert system['immutable_or_image_based'] and system['distribution']['ID']=='bazzite'
        assert system['system_package_action'].startswith('guidance only')


def run_environment_real_venv_checks():
    # The only real venv creation is an isolated temporary environment, without
    # pip/downloads. All install/failure cases above are deterministic fixtures.
    with TemporaryDirectory() as tmp:
        f=Fixture(tmp)
        base=getattr(sys,'_base_executable',sys.executable)
        subprocess.run([base,'-I','-m','venv','--without-pip',str(f.manager.venv)],check=True,capture_output=True)
        manager=em.EnvironmentManager(f.root,selected=base)
        state=manager.inspect();assert state['valid'],state
        assert state['pip'] is False
        assert Path(state['interpreter']['prefix']).resolve()==manager.venv
    # CPython does not shell-quote pyvenv.cfg's command destination. Exercise
    # genuine fresh environments, including whitespace and unmatched quotes,
    # while retaining relocation rejection and never installing packages.
    with TemporaryDirectory() as tmp:
        for name in ['project with spaces', "project's files"]:
            root=Path(tmp)/name;root.mkdir()
            f=Fixture(root)
            base=getattr(sys,'_base_executable',sys.executable)
            subprocess.run([base,'-I','-m','venv','--without-pip',str(f.manager.venv)],check=True,capture_output=True)
            manager=em.EnvironmentManager(root,selected=base)
            assert manager.inspect()['valid'],manager.inspect()
            cfg=manager.venv/'pyvenv.cfg';text=cfg.read_text()
            command=next(line for line in text.splitlines() if line.startswith('command = '))
            # A different recorded destination must still require a rebuild.
            cfg.write_text(text.replace(command,'command = fixture -m venv /previous/.venv'))
            assert not manager.inspect()['valid']
            import shlex
            cfg.write_text(text.replace(command,'command = fixture -m venv '+shlex.quote(str(manager.venv))))
            assert manager.inspect()['valid'],manager.inspect()
