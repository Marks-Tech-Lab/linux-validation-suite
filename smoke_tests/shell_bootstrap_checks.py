"""POSIX bootstrap fixtures: no real installation, Bash or Python on test PATH."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def checkout(directory):
    root=Path(directory)/'LVS bootstrap';(root/'scripts').mkdir(parents=True)
    for name in ['setup.sh','scripts/lvs_python_bootstrap.sh','scripts/lvs_python_policy.sh','scripts/setup_venv.sh']:
        shutil.copyfile(ROOT/name,root/name)
    (root/'path').mkdir()
    return root


def fake_python(root,name='python3.14',version='3.14.1',support=True,base=None):
    path=root/'path'/name
    valid=tuple(map(int,version.split('.')[:2])) >= (3,10)
    path.write_text('''#!/bin/sh
printf '%s\\n' "$0 $*" >> {calls}
for arg do
 case $arg in */lvs_environment_manager.py)
  printf '%s\\n' "$0" "$@" > {delegation}
  printf '%s\\n' 'MANAGER_DELEGATED'
  exit 0 ;;
 esac
done
case "$*" in
 *ensurepip.version*)
  {support} ;;
 *'_base_executable'*) printf '%s\\n' {base}; exit 0 ;;
 *'print(sys.version_info.major'*) printf '%s\\n' {spaces}; exit {status} ;;
 *'-m venv '*)
  for final do :; done
  /bin/mkdir -p "$final/bin"
  /bin/cp "$0" "$final/bin/python"
  exit 0 ;;
 *'-m pip '*) exit 0 ;;
 *) printf '%s\\n' {version}; exit {status} ;;
esac
'''.format(calls=shlex.quote(str(root/'python.calls')),delegation=shlex.quote(str(root/'delegation.args')),
           support='exit 0' if support else "printf '%s\\n' 'No module named ensurepip' >&2; exit 1",
           base=shlex.quote(str(base or path)),spaces=shlex.quote(version.replace('.',' ')),
           version=shlex.quote(version),status=0 if valid else 1))
    path.chmod(0o755)
    return path


def shell(root,*args,override=None):
    env={**os.environ,'PATH':str(root/'path'),'PYTHONDONTWRITEBYTECODE':'1'}
    env.pop('PYTHON',None)
    if override is not None:env['PYTHON']=str(override)
    return subprocess.run(['/bin/sh',str(root/'setup.sh'),*map(str,args)],cwd=root,env=env,
                          capture_output=True,text=True,timeout=15)


def run_posix_bootstrap_discovery_checks():
    for name in ['setup.sh','scripts/lvs_python_bootstrap.sh','scripts/lvs_python_policy.sh']:
        subprocess.run(['/bin/sh','-n',str(ROOT/name)],check=True)
    with TemporaryDirectory() as directory:
        root=checkout(directory)
        help_result=shell(root,'--help');assert help_result.returncode==0 and 'No OS packages' in help_result.stdout
        result=shell(root);assert result.returncode==1 and 'No usable Python' in result.stderr
        assert not (root/'delegation.args').exists() and not (root/'.venv').exists()
        fake_python(root,'python3','3.9.9')
        result=shell(root);assert result.returncode==1 and 'below 3.10' in result.stderr
        compatible=fake_python(root,'python3.11','3.11.9')
        result=shell(root,'--check','--wheelhouse',root/'local wheels')
        assert result.returncode==0 and 'MANAGER_DELEGATED' in result.stdout
        args=(root/'delegation.args').read_text().splitlines()
        assert str(compatible) in args and str(root/'local wheels') in args and '--check' in args
        assert not (root/'.venv').exists()
        # Tested Python is preferred over newer available versions.
        tested=fake_python(root);fake_python(root,'python3.99','3.99.0')
        result=shell(root);assert result.returncode==0
        args=(root/'delegation.args').read_text().splitlines()
        assert str(tested) in args and '--python' not in args


def run_posix_bootstrap_override_checks():
    with TemporaryDirectory() as directory:
        root=checkout(directory);default=fake_python(root);custom=fake_python(root,'selected python','3.12.9')
        result=shell(root,override=custom);assert result.returncode==0
        assert str(custom) in (root/'delegation.args').read_text().splitlines()
        result=shell(root,'--python',custom,override=default);assert result.returncode==0
        assert str(custom) in (root/'delegation.args').read_text().splitlines()
        for override in [root/'absent',fake_python(root,'old','3.8.9')]:
            (root/'delegation.args').unlink(missing_ok=True)
            result=shell(root,override=override)
            assert result.returncode==1 and 'Explicit Python override is unusable' in result.stderr
            assert not (root/'delegation.args').exists()
        assert shell(root,'--python').returncode==2
        base=fake_python(root,'base-python','3.13.9')
        active=fake_python(root,'active-venv-python','3.13.9',base=base)
        result=shell(root,override=active);assert result.returncode==0
        args=(root/'delegation.args').read_text().splitlines()
        assert args[0]==str(base) and args[args.index('--python')+1]==str(base)


def run_posix_bootstrap_prerequisite_guidance_checks():
    with TemporaryDirectory() as directory:
        root=checkout(directory);python=fake_python(root,support=False)
        # Tripwires prove no sudo, pip or system installer is ever invoked.
        for name in ['sudo','pip','apt-get','dnf','rpm-ostree']:
            p=root/'path'/name;p.write_text('#!/bin/sh\nprintf invoked > '+shlex.quote(str(root/'installer.called'))+'\nexit 99\n');p.chmod(0o755)
        result=shell(root)
        assert result.returncode==0 and 'MANAGER_DELEGATED' in result.stdout
        assert 'ensurepip' in result.stderr and 'creation/rebuild requires' in result.stderr
        assert not (root/'installer.called').exists() and not (root/'.venv').exists()
        # Resolving prerequisites and rerunning resumes the ordinary manager.
        fake_python(root,support=True);result=shell(root)
        assert result.returncode==0 and 'creation/rebuild requires' not in result.stderr
        for release,expected,forbidden in [
            ('ID=debian\nVERSION_ID=13\n','apt-get install python3 python3-venv','dnf install'),
            ('ID=ubuntu\nID_LIKE=debian\n','python3-venv','dnf install'),
            ('ID=fedora\n','dnf provides','apt-get install'),
            ('ID=bazzite\nID_LIKE="fedora"\n','Image-based system','dnf install'),
            ('ID=unknown\n','distro/image administrator','apt-get install'),
        ]:
            os_release=root/'os-release';os_release.write_text(release+'IGNORED="$(touch unsafe)"\n')
            command='. "$1"; lvs_python_guidance "$2" "$3"'
            result=subprocess.run(['/bin/sh','-c',command,'bootstrap',str(root/'scripts/lvs_python_bootstrap.sh'),str(os_release),str(root/'no-ostree')],
                cwd=root,env={**os.environ,'PATH':str(root/'path')},capture_output=True,text=True,check=True)
            assert expected in result.stderr and forbidden not in result.stderr
            assert 'sudo is not assumed' in result.stderr and not (root/'installer.called').exists()
            assert not (root/'unsafe').exists()
        # An actual image-based marker overrides mutable distro assumptions.
        marker=root/'ostree';marker.touch();os_release.write_text('ID=fedora\n')
        result=subprocess.run(['/bin/sh','-c',command,'bootstrap',str(root/'scripts/lvs_python_bootstrap.sh'),str(os_release),str(marker)],
                              capture_output=True,text=True,check=True)
        assert 'Image-based system' in result.stderr and 'dnf install' not in result.stderr


def run_posix_bootstrap_delegation_legacy_checks():
    with TemporaryDirectory() as directory:
        root=checkout(directory);(root/'Modules').mkdir()
        for name in ['lvs_environment_manager.py','Modules/lvs_python_environment.py','requirements.txt','requirements-google.txt']:
            shutil.copyfile(ROOT/name,root/name)
        # Real stdlib-only diagnostics in a fresh checkout: no venv/site packages,
        # Bash, pip or compiler on PATH. The explicit base Python is the sole tool.
        base=getattr(sys,'_base_executable',sys.executable)
        result=shell(root,'--check',override=base)
        assert result.returncode==0,(result.stdout,result.stderr)
        report=json.loads(result.stdout)
        assert report['kind']=='python_environment_inspection' and not report['python_baseline_ready']
        assert not (root/'.venv').exists()
    bash=shutil.which('bash')
    if bash is None:
        print('Legacy Bash workflow check unavailable; POSIX/no-Bash checks above completed')
        return
    with TemporaryDirectory() as directory:
        root=checkout(directory);python=fake_python(root)
        env={**os.environ,'PATH':str(root/'path')+os.pathsep+'/usr/bin:/bin','PYTHON':str(python)}
        result=subprocess.run([bash,str(root/'scripts/setup_venv.sh')],cwd=root,env=env,capture_output=True,text=True)
        assert result.returncode==0,(result.stdout,result.stderr)
        calls=(root/'python.calls').read_text()
        assert '-m venv '+str(root/'.venv') in calls
        assert str(root/'.venv/bin/python')+' -m pip install --upgrade pip' in calls
        assert '-m pip install -r '+str(root/'requirements.txt') in calls
        # Existing compatible venv is reused, with PYTHON override retained.
        (root/'python.calls').write_text('')
        result=subprocess.run([bash,str(root/'scripts/setup_venv.sh')],cwd=root,env=env,capture_output=True,text=True)
        assert result.returncode==0 and '-m venv ' not in (root/'python.calls').read_text()

    with TemporaryDirectory() as directory:
        root=checkout(directory);python=fake_python(root,support=False)
        env={**os.environ,'PATH':str(root/'path')+os.pathsep+'/usr/bin:/bin','PYTHON':str(python)}
        result=subprocess.run([bash,str(root/'scripts/setup_venv.sh')],cwd=root,env=env,capture_output=True,text=True)
        assert result.returncode==1 and 'ensurepip' in result.stderr
        assert not (root/'.venv').exists() and '-m pip install' not in (root/'python.calls').read_text()
