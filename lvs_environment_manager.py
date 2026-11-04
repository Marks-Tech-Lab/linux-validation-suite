#!/usr/bin/env python3
"""Numbered-menu LVS bootstrap/maintenance utility. Standard library only.

No LVS runtime import or native build occurs at startup. Runtime integrations run
only on request, in a validated target .venv subprocess. No shell/elevation/global
pip is used. This file intentionally avoids modern typing syntax so an older
Python can explain the project's newer minimum and select another interpreter.
"""
import argparse
import datetime
import contextlib
import fcntl
import functools
import importlib.util
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import stat
import tempfile
from pathlib import Path
from uuid import uuid4

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from Modules.lvs_python_environment import PYTHON_GROUPS, python_policy, requirement_pins
from Modules.lvs_environment_ui import EnvironmentScreens, CustomizeEnvironment, plain_text

MARKER = '.lvs-environment.json'
LOCK = '.lvs-environment-maintenance.lock'
OPERATION = '.lvs-environment-operation.json'
PROBE = '''import sys, os, platform, sysconfig, json, importlib.util
def available(name):
 try:
  module=__import__(name)
  if name=='ensurepip':module.version()
  return True
 except Exception:return False
print(json.dumps(dict(version=list(sys.version_info[:3]), executable=sys.executable,
 prefix=sys.prefix, base_prefix=getattr(sys,'base_prefix',sys.prefix),
 base_executable=getattr(sys,'_base_executable',sys.executable),
 architecture=platform.machine(), platform_tag=sysconfig.get_platform(),
 bits=__import__('struct').calcsize('P')*8,
 implementation=platform.python_implementation(), soabi=sysconfig.get_config_var('SOABI'),
 cache_tag=getattr(sys.implementation,'cache_tag',None),
 free_threaded=bool(sysconfig.get_config_var('Py_GIL_DISABLED')),
 venv=available('venv'), ensurepip=available('ensurepip'))))'''
PACKAGES = '''import importlib, importlib.metadata, json, sys
request=json.loads(sys.argv[1]); result={'packages':{},'imports':{}}
for name,expected in request['pins']:
 try:
  actual=importlib.metadata.version(name)
  result['packages'][name]={'installed':actual,'expected':expected,'matches':actual==expected}
 except importlib.metadata.PackageNotFoundError:
  result['packages'][name]={'installed':None,'expected':expected,'matches':False}
for name in request['imports']:
 try: importlib.import_module(name); result['imports'][name]={'importable':True}
 except Exception as e: result['imports'][name]={'importable':False,'error':str(e)}
print(json.dumps(result))'''

# This bridge is not imported by the bootstrap process. It reuses the uploader's
# exact readiness contract and does not read or print credential contents.
GOOGLE = '''import sys,json,dataclasses
from pathlib import Path
sys.path.insert(0,sys.argv[1]);sys.dont_write_bytecode=True
from Modules.lvs_settings import GlobalSettings
from Modules.lvs_google_drive_uploader import GoogleDriveUploader
path=Path('settings/global_settings.json')
raw=json.loads(path.read_text()) if path.exists() else {}
allowed={f.name for f in dataclasses.fields(GlobalSettings)}
settings=GlobalSettings(**{k:v for k,v in raw.items() if k in allowed})
print(json.dumps(GoogleDriveUploader(settings).readiness()))'''

DEPENDENCIES = '''import sys,json,dataclasses
from pathlib import Path
sys.path.insert(0,sys.argv[1]);sys.dont_write_bytecode=True
from Modules.lvs_settings import GlobalSettings
from Modules.lvs_cli_compat import ValidationOrchestrator
from Modules.lvs_dependency_reports import DependencyReportManager
from Modules.lvs_google_drive_uploader import GoogleDriveUploader
path=Path('settings/global_settings.json')
raw=json.loads(path.read_text()) if path.exists() else {}
allowed={f.name for f in dataclasses.fields(GlobalSettings)}
settings=GlobalSettings(**{k:v for k,v in raw.items() if k in allowed})
settings.privileged_helper_enabled=False
settings.privileged_helper_prompt_for_sudo=False
manager=DependencyReportManager(settings,ValidationOrchestrator(settings),GoogleDriveUploader(settings).readiness)
result=manager.run_dependency_check(settings.results_dir)
print(result.summary_text)
print('Saved existing LVS dependency report: '+str(result.report_dir))'''

NATIVE = '''import sys,json,os,shutil,tempfile,datetime
from pathlib import Path
sys.path.insert(0,sys.argv[1]);sys.dont_write_bytecode=True
from Modules.lvs_native_helpers import NativeHelperRuntimeService,find_c_compiler
from Modules.lvs_cpu_architecture import native_cpu_helper_binary_name,normalize_cpu_architecture
from Modules.lvs_memory_architecture import native_memory_helper_binary_name
from Modules.lvs_native_binary_provenance import executable_snapshot
from Modules.lvs_source_provenance import collect_source_provenance
import platform
root=Path(sys.argv[1]);arch=normalize_cpu_architecture(platform.machine());compiler=find_c_compiler()
if arch not in ('arm64','x86_64'):raise RuntimeError('Native helper maintenance supports existing x86-64/AArch64 targets only')
if not compiler:raise RuntimeError('No existing LVS C compiler (gcc/cc) found; Python environment remains usable')
build=root/'build'
if build.is_symlink():raise RuntimeError('Refusing symlinked build directory')
build.mkdir(exist_ok=True)
runtime=NativeHelperRuntimeService(command_env=lambda:dict(os.environ))
source_identity=collect_source_provenance(root)['source']
with tempfile.TemporaryDirectory(prefix='environment-manager-',dir=str(build)) as tmp:
 for family,name in [('cpu',native_cpu_helper_binary_name(platform.machine())),('memory',native_memory_helper_binary_name(platform.machine()))]:
  candidate=Path(tmp)/name
  status=runtime.helper_status(cache_key=family,source=root/'native'/(family+'_stress_helper.c'),
   binary=candidate,compiler_path=lambda:compiler,reason_label=family,
   readiness_command=(lambda p:[p,'--mode','scalar','--print-resolved-mode']) if family=='cpu' else (lambda p:[p,'--help']))
  if not status.get('available') or not status.get('built'):raise RuntimeError(str(status))
  identity=executable_snapshot(candidate)
  expected='aarch64' if arch=='arm64' else 'x86_64'
  if identity.get('architecture')!=expected or identity.get('status')!='observed':raise RuntimeError('Compiled helper identity failed: '+str(identity))
  if collect_source_provenance(root)['source']!=source_identity:raise RuntimeError('Source changed during helper compilation; no readiness claim')
  final=build/name;backup=None
  if final.exists() or final.is_symlink():
   if final.is_symlink() or executable_snapshot(final).get('status')!='observed':raise RuntimeError('Refusing to replace unrelated/non-ELF helper path: '+str(final))
   backup=build/(name+'.backup-'+datetime.datetime.now().strftime('%Y%m%dT%H%M%S%f'))
   final.rename(backup);print('Previous helper retained: '+str(backup))
  try:os.replace(str(candidate),str(final))
  except BaseException:
   if backup is not None and not final.exists():backup.rename(final)
   raise
  final_identity=executable_snapshot(final)
  if final_identity.get('sha256')!=identity.get('sha256'):raise RuntimeError('Published helper identity changed')
  print(json.dumps(dict(family=family,build=status,identity=final_identity,source=source_identity)))
print('Build/query readiness only; no workload or physical ISA acceptance claimed')'''


class EnvironmentError(RuntimeError):
    pass


class EnvironmentProcessError(EnvironmentError):
    cleanup_unconfirmed = True


def run_managed_command(args, **kwargs):
    """Cancel the entire owned command group before recovering environment paths."""
    timeout = kwargs.pop('timeout', 60)
    process = subprocess.Popen(args, start_new_session=True, **kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as error:
            raise EnvironmentProcessError('Cannot terminate installer process group: ' + str(error))
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            raise EnvironmentProcessError('Command group termination could not be confirmed; inspect processes before restoring an environment')
        raise


def maintenance_operation(function):
    @functools.wraps(function)
    def locked(self, *args, **kwargs):
        with self.maintenance_lock():
            return function(self, *args, **kwargs)
    return locked


def normalized_arch(value):
    value = value.lower()
    return {'amd64': 'x86_64', 'aarch64': 'arm64'}.get(value, value)


def system_environment(os_release='/etc/os-release'):
    data = {}
    try:
        for line in Path(os_release).read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.startswith('#'):
                key, value = line.split('=', 1)
                words = shlex.split(value)
                data[key] = words[0] if len(words) == 1 else value
    except (OSError, ValueError):
        pass
    managers = [name for name in ('apt-get', 'dnf', 'rpm-ostree', 'bootc', 'pacman', 'zypper', 'apk') if shutil.which(name)]
    immutable = (Path('/run/ostree-booted').exists() or 'bazzite' in data.get('ID', '').lower()
                 or bool(data.get('OSTREE_VERSION')))
    return {'distribution': data, 'system': platform.system(), 'architecture': platform.machine(), 'kernel': platform.release(),
            'package_managers': managers, 'immutable_or_image_based': immutable,
            'image_tools_present': [name for name in managers if name in ('rpm-ostree', 'bootc')],
            'system_package_action': 'guidance only; no automatic installation',
            'provider_resolution': 'deferred; use distro/image documentation for Python venv/ensurepip and gcc/cc'}


def machine_identity():
    try:
        return hashlib.sha256(Path('/etc/machine-id').read_bytes().strip()).hexdigest()
    except OSError:
        return 'hostname:' + platform.node()


def interpreter_abi(info):
    return {key: info.get(key) for key in ('implementation', 'soabi', 'cache_tag', 'bits', 'free_threaded')}


def executable_digest(path):
    try:
        path=Path(path)
        if path.stat().st_size > 128 * 1024 * 1024:return None
        digest=hashlib.sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda:handle.read(1024*1024), b''):digest.update(chunk)
        return digest.hexdigest()
    except OSError:return None


class EnvironmentManager:
    def __init__(self, root=None, runner=None, ask=input, output=print, selected=None, wheelhouse=None, screens=None):
        self.root = Path(root or Path(__file__).resolve().parent).resolve()
        self.venv = self.root / '.venv'
        self.python = self.venv / 'bin/python'
        self.runner = runner or run_managed_command
        self.ask = ask
        self.output = output
        self.selected = str(selected) if selected else None
        self.wheelhouse = Path(wheelhouse).expanduser().resolve() if wheelhouse else None
        self._lock_fd = None
        self._rebuilding = False
        self.screens=screens or EnvironmentScreens(ask=lambda prompt:self.ask(prompt),output=output)
        self._ui_mode=False
        self._custom_allowed=False
        self._technical_output=[]
        self._operation_log=[]

    @contextlib.contextmanager
    def maintenance_lock(self):
        """Stable inode, separate from the runtime lock; never unlink on exit."""
        if self._lock_fd is not None:
            yield
            return
        path = self.root / LOCK
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise EnvironmentError('Refusing an unrelated maintenance lock path')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise EnvironmentError('Another environment maintenance operation is active; wait and retry. External pip/LVS must also be stopped.')
            content = os.read(fd, 4096)
            if content and not content.startswith(b'LVS environment maintenance\n'):
                raise EnvironmentError('Refusing an unrelated maintenance lock file')
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, ('LVS environment maintenance\nPID={}\n'.format(os.getpid())).encode())
            self._lock_fd = fd
            yield
        finally:
            self._lock_fd = None
            # Closing, rather than LOCK_UN, preserves an inherited installer's
            # lease if the manager dies while that installer is still running.
            os.close(fd)

    def operation_record(self):
        path = self.root / OPERATION
        if not path.exists() and not path.is_symlink():
            return {}
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            raise EnvironmentError('Invalid maintenance operation record; preserve it and resolve manually')
        value = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(value, dict) or not isinstance(value.get('root'),str)
                or value.get('kind') != 'lvs_environment_operation'
                or value.get('operation') not in ('rebuild','synchronize','tools')
                or value.get('status') not in ('running','completed','failed','restored','cleanup_unconfirmed')
                or not isinstance(value.get('groups'),list)
                or any(not isinstance(g,str) or g not in PYTHON_GROUPS for g in value['groups'])):
            raise EnvironmentError('Unrecognized maintenance operation record; preserve it and resolve manually')
        return value

    def save_operation(self, value):
        value = dict(value, root=str(self.root), kind='lvs_environment_operation', version=1, updated_at=datetime.datetime.now().isoformat())
        fd, name = tempfile.mkstemp(prefix=OPERATION + '.', dir=str(self.root))
        try:
            with os.fdopen(fd, 'w') as handle:
                json.dump(value, handle, indent=2);handle.flush();os.fsync(handle.fileno())
            os.replace(name, str(self.root / OPERATION))
            directory=os.open(str(self.root),os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(directory)
            finally:os.close(directory)
        finally:
            if os.path.exists(name):os.unlink(name)

    def check_pending_operation(self):
        record = self.operation_record()
        if record and record['root']!=str(self.root) and record['status'] in ('running','cleanup_unconfirmed'):
            raise EnvironmentError('Unresolved operation belongs to another project path. Retain its evidence and resolve manually before maintenance.')
        if record.get('status') == 'cleanup_unconfirmed':
            raise EnvironmentError('Previous installer cleanup is unconfirmed. Retain all environments/backups, stop installer processes and resolve the operation record manually before maintenance.')
        if record.get('operation') == 'rebuild' and record.get('status') == 'running':
            raise EnvironmentError('Previous rebuild was interrupted; use guided inspection/recovery before changing .venv')
        return record

    @staticmethod
    def path_identity(path):
        if path.is_symlink():return None
        try:
            s=path.stat()
            return [s.st_dev,s.st_ino] if stat.S_ISDIR(s.st_mode) else None
        except FileNotFoundError:return None

    def command(self, args, timeout=60, capture=True):
        env = {k: v for k, v in os.environ.items() if not k.startswith('PIP_')
               and k not in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV')}
        env.update(PIP_CONFIG_FILE=os.devnull, PYTHONDONTWRITEBYTECODE='1')
        args = [str(a) for a in args]
        if len(args) > 1 and args[1] == '-I':
            args.insert(1, '-B')
        kwargs = dict(cwd=str(self.root), env=env, timeout=timeout, universal_newlines=True)
        if self._lock_fd is not None and self.runner is run_managed_command:
            kwargs['pass_fds'] = (self._lock_fd,)
        if capture:
            kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            result=self.runner([str(a) for a in args], **kwargs)
            if self._ui_mode and result.stdout:
                self._technical_output.append('Command output: '+args[0]+'\n'+str(result.stdout))
            return result
        except (OSError, subprocess.TimeoutExpired) as error:
            raise EnvironmentError('Command unavailable or timed out: {}: {}'.format(args[0], error))

    def checked(self, args, timeout=60, capture=True):
        result = self.command(args, timeout, capture)
        if result.returncode:
            raise EnvironmentError('Command failed (exit {}): {}\n{}'.format(
                result.returncode, ' '.join(str(a) for a in args[:5]), (result.stdout or '')[-5000:]))
        return result

    def probe(self, executable):
        try:
            result = self.checked([executable, '-I', '-c', PROBE], timeout=8)
            value = json.loads(result.stdout)
            if not isinstance(value, dict) or len(value['version']) != 3:
                raise ValueError('invalid interpreter response')
            return value
        except (EnvironmentError, ValueError, KeyError) as error:
            return {'error': str(error)}

    def candidates(self):
        policy = python_policy(self.root)
        tested = 'python{}.{}'.format(*policy['tested'])
        names = [tested, getattr(sys, '_base_executable', sys.executable), 'python3']
        for directory in os.environ.get('PATH', '').split(os.pathsep):
            if directory:
                try:
                    names += [str(p) for p in sorted(Path(directory).glob('python3.*')) if re.fullmatch(r'python3\.\d+', p.name)]
                except OSError:
                    pass
        result, seen = [], set()
        for name in names:
            found = shutil.which(name)
            if not found:
                continue
            resolved = str(Path(found).resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            info = self.probe(resolved)
            result.append({'path': resolved, 'details': info})
            if len(result) >= 32:
                break
        return result

    def selected_python(self):
        policy = python_policy(self.root)
        if self.selected is None:
            existing = self.inspect()
            if existing['valid']:
                self.selected = existing['interpreter']['base_executable']
            else:
                for item in self.candidates():
                    info = item['details']
                    if ('error' not in info and tuple(info['version'][:2]) >= policy['minimum']
                            and info.get('prefix')==info.get('base_prefix')
                            and normalized_arch(info['architecture'])==normalized_arch(platform.machine())
                            and info.get('venv') and info.get('ensurepip')):
                        self.selected = item['path']
                        break
        if not self.selected:
            raise EnvironmentError('Install Python {}.{} or newer; tested {}.{}'.format(
                *(policy['minimum'] + policy['tested'])))
        info = self.probe(self.selected)
        if 'error' in info or tuple(info['version'][:2]) < policy['minimum']:
            raise EnvironmentError('Selected interpreter does not meet project minimum: ' + str(info))
        if info['prefix'] != info['base_prefix']:
            raise EnvironmentError('Select a base interpreter, not another virtual environment')
        if normalized_arch(info['architecture']) != normalized_arch(platform.machine()):
            raise EnvironmentError('Selected interpreter architecture differs from this machine')
        return self.selected, info

    def inspect(self):
        result = {'path': str(self.venv), 'valid': False, 'issues': [], 'warnings': [], 'pip': False}
        result['retained_environments'] = sorted(str(p) for pattern in ('.venv.backup-*', '.venv.failed-*') for p in self.root.glob(pattern))
        try:
            result['maintenance'] = self.operation_record()
        except (EnvironmentError, ValueError, OSError) as error:
            result['issues'].append(str(error))
            result['maintenance_error']=str(error)
        cfg = self.venv / 'pyvenv.cfg'
        if self.venv.is_symlink():
            result['issues'].append('.venv is a symlink; refusing maintenance through it')
            return result
        if not self.venv.exists():
            result['issues'].append('.venv is absent')
            return result
        if not self.venv.is_dir() or not cfg.is_file() or cfg.is_symlink():
            result['issues'].append('Existing path is not a recognized venv; preserve it and resolve manually')
            return result
        fields = {}
        try:
            cfg_text = cfg.read_text(encoding='utf-8')
        except (OSError, UnicodeError) as error:
            result['issues'].append('Unreadable venv configuration: ' + str(error))
            return result
        for line in cfg_text.splitlines():
            if '=' in line:
                key, value = line.split('=', 1)
                fields[key.strip()] = value.strip()
        result['configuration'] = fields
        if fields.get('include-system-site-packages', '').lower() != 'false':
            result['issues'].append('System site packages are enabled or isolation is unconfirmed; rebuild a self-contained venv')
        info = self.probe(self.python)
        result['interpreter'] = info
        if 'error' in info:
            result['issues'].append('Venv interpreter is missing, stale, incompatible, or not executable: ' + info['error'])
            return result
        if Path(info['prefix']).resolve() != self.venv or info['prefix'] == info['base_prefix']:
            result['issues'].append('Interpreter is not isolated at the intended .venv path')
        if tuple(info['version'][:2]) < python_policy(self.root)['minimum']:
            result['issues'].append('Venv Python is below project minimum')
        if not Path(info['base_executable']).exists():
            result['issues'].append('Base interpreter no longer exists')
        else:
            base = self.probe(info['base_executable'])
            if 'error' in base:
                result['issues'].append('Base interpreter cannot be verified: ' + base['error'])
            elif (base['version'][:2] != info['version'][:2] or interpreter_abi(base) != interpreter_abi(info)):
                result['issues'].append('Base interpreter and environment Python/ABI differ; rebuild')
        if fields.get('home') and not Path(fields['home']).exists():
            result['issues'].append('pyvenv.cfg home is stale')
        recorded_version = fields.get('version', '').split('.')[:2]
        if recorded_version and recorded_version != [str(x) for x in info['version'][:2]]:
            result['issues'].append('Python minor version changed since environment creation')
        if normalized_arch(info['architecture']) != normalized_arch(platform.machine()):
            result['issues'].append('Environment architecture differs from this machine')
        if fields.get('command'):
            # CPython writes an unquoted absolute destination here, including
            # spaces or shell metacharacters. It is descriptive text, not a
            # shell command. Recognize that literal suffix before considering
            # producers that do quote their final argument. Never execute it.
            command = fields['command']
            if not command.endswith(' ' + str(self.venv)):
                try:
                    words = shlex.split(command)
                except ValueError:
                    words = []
                    result['issues'].append('Malformed creation command in pyvenv.cfg')
                if words and Path(words[-1]).resolve() != self.venv:
                    result['issues'].append('Creation path differs: relocated environment requires rebuild')
        pip_script = self.venv / 'bin/pip'
        if pip_script.is_file():
            try:
                with pip_script.open(encoding='utf-8') as handle:
                    first = handle.readline().strip()
                if first.startswith('#!') and '/.venv/' in first and str(self.venv) not in first:
                    result['issues'].append('Installed pip script has a stale environment shebang')
            except (OSError, UnicodeError) as error:
                result['issues'].append('Unreadable pip script: ' + str(error))
        marker = self.venv / MARKER
        if marker.exists() or marker.is_symlink():
            try:
                if marker.is_symlink():
                    raise ValueError('marker is a symlink')
                recorded = json.loads(marker.read_text(encoding='utf-8'))
                if not isinstance(recorded, dict):
                    raise ValueError('marker must be an object')
            except (OSError, ValueError) as error:
                result['issues'].append('Invalid environment marker: ' + str(error))
                recorded = {}
            result['recorded_environment'] = recorded
            for key, actual in [('root', str(self.root)), ('architecture', normalized_arch(platform.machine())),
                                ('machine_id', machine_identity())]:
                if recorded.get(key) != actual:
                    result['issues'].append('Recorded {} differs; rebuild for the current machine/OS'.format(key))
            old_os=recorded.get('os', {});current_os=system_environment()['distribution']
            if not isinstance(old_os,dict) or any(old_os.get(k) != current_os.get(k) for k in ('ID','VARIANT_ID')):
                result['issues'].append('Recorded os distribution differs; rebuild for the current machine/OS')
            elif old_os != current_os:
                result['warnings'].append('OS release metadata changed; verify imports and pip consistency before reuse')
            version=recorded.get('python_version')
            if not isinstance(version,list) or len(version)!=3 or any(type(v) is not int for v in version):
                result['issues'].append('Invalid recorded Python version')
            elif version[:2] != info['version'][:2]:
                result['issues'].append('Recorded Python minor version differs; rebuild instead of reusing site-packages')
            elif version != info['version']:
                result['warnings'].append('Python patch update detected; verify installed packages, no rebuild required by version alone')
            old_base=recorded.get('base_executable')
            if not isinstance(old_base,str) or Path(old_base).resolve() != Path(info['base_executable']).resolve():
                result['issues'].append('Recorded base interpreter changed; select a compatible interpreter and rebuild')
            if 'abi' in recorded and recorded['abi'] != interpreter_abi(info):
                result['issues'].append('Recorded Python ABI differs; rebuild')
            elif 'abi' not in recorded:
                result['warnings'].append('Legacy marker has no historical ABI identity; current ABI and package checks remain authoritative')
            old_digest=recorded.get('base_sha256')
            if old_digest and old_digest != executable_digest(info['base_executable']):
                result['warnings'].append('Base executable bytes changed; verify package imports and pip consistency; compatible patch replacements may be reused')
            optional=recorded.get('optional_groups',[])
            if not isinstance(optional,list) or any(not isinstance(v,str) or v not in PYTHON_GROUPS for v in optional):
                result['issues'].append('Invalid optional dependency metadata; preserve the record for recovery')
        else:
            result['warnings'].append('Unmarked environment: historical machine/OS provenance is unknown; rebuild after transfer')
        result['valid'] = not result['issues']
        if result['valid']:
            try:
                result['pip'] = self.command([self.python, '-I', '-m', 'pip', '--version']).returncode == 0
            except EnvironmentError as error:
                result['pip_error'] = str(error)
        return result

    def groups(self):
        selected = ['baseline']
        state = self.inspect()
        recorded = state.get('recorded_environment', {})
        marker = self.venv / MARKER
        if not recorded and not self.venv.is_symlink() and marker.is_file() and not marker.is_symlink():
            try:
                candidate = json.loads(marker.read_text(encoding='utf-8'))
                if isinstance(candidate, dict):
                    recorded = candidate
            except (OSError, ValueError):
                pass
        optional=recorded.get('optional_groups', [])
        for group in optional if isinstance(optional,list) else []:
            if group in PYTHON_GROUPS and group not in selected:
                selected.append(group)
        pending=state.get('maintenance',{})
        for group in pending.get('groups',[]) if isinstance(pending.get('groups',[]),list) else []:
            if group in PYTHON_GROUPS and group not in selected:selected.append(group)
        if state['valid'] and 'google' not in selected:
            try:check = self.packages('google')
            except (EnvironmentError,ValueError):check={'packages':{}}
            if check['packages'] and all(v['installed'] is not None for v in check['packages'].values()):
                selected.append('google')
        return selected

    def packages(self, group):
        request = {'pins': requirement_pins(self.root, group), 'imports': PYTHON_GROUPS[group]['imports']}
        result = self.checked([self.python, '-I', '-c', PACKAGES, json.dumps(request)], timeout=30)
        return json.loads(result.stdout)

    def require_environment(self):
        state = self.inspect()
        if not state['valid']:
            raise EnvironmentError('Create/repair or explicitly rebuild first: ' + '; '.join(state['issues']))
        return state

    def pip_command(self, arguments):
        return [self.python, '-I', '-m', 'pip', '--require-virtualenv', '--disable-pip-version-check', *arguments]

    @maintenance_operation
    def write_marker(self, groups):
        if not self._rebuilding:self.check_pending_operation()
        info = self.require_environment()['interpreter']
        payload = {'root': str(self.root), 'architecture': normalized_arch(platform.machine()),
                   'os': system_environment()['distribution'], 'base_executable': info['base_executable'],
                   'python_version': info['version'], 'abi': interpreter_abi(info),
                   'base_sha256':executable_digest(info['base_executable']),
                   'machine_id': machine_identity(), 'optional_groups': [g for g in groups if g != 'baseline']}
        fd,name=tempfile.mkstemp(prefix=MARKER+'.',dir=str(self.venv))
        try:
            with os.fdopen(fd,'w') as handle:
                json.dump(payload,handle,indent=2);handle.flush();os.fsync(handle.fileno())
            os.replace(name,str(self.venv / MARKER))
            directory=os.open(str(self.venv),os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(directory)
            finally:os.close(directory)
        finally:
            if os.path.exists(name):os.unlink(name)

    @maintenance_operation
    def install(self, groups):
        if not self._rebuilding:self.check_pending_operation()
        self.require_environment()
        if self.wheelhouse and not self.wheelhouse.is_dir():
            raise EnvironmentError('Local package directory does not exist: ' + str(self.wheelhouse))
        options = ['install', '--no-input', '--no-user']
        if self.wheelhouse:
            options += ['--no-index', '--find-links', str(self.wheelhouse)]
        for group in groups:
            options += ['-r', str(self.root / PYTHON_GROUPS[group]['requirements'])]
        self.output('Installing requirement pins using the environment interpreter; package resolution/downloads may take time.')
        self.checked(self.pip_command(options), timeout=900)
        self.checked(self.pip_command(['check']))
        self.verify_groups(groups)
        self.write_marker(groups)
        self.output('Synchronized and independently verified: ' + ', '.join(groups))

    def verify_groups(self, groups):
        for group in groups:
            check = self.packages(group)
            if not all(v['matches'] for v in check['packages'].values()) or not all(v['importable'] for v in check['imports'].values()):
                raise EnvironmentError('Post-install package/import verification failed: ' + json.dumps(check))

    @maintenance_operation
    def synchronize_groups(self, groups, tools=False):
        self.check_pending_operation()
        record={'operation':'tools' if tools else 'synchronize','status':'running','groups':groups}
        self.save_operation(record)
        try:
            self.ensure_pip()
            if tools:
                self.checked(self.pip_command(['install','--no-user','--upgrade','pip','setuptools','wheel']),timeout=900)
                self.checked(self.pip_command(['check']))
                self.verify_groups(groups)
                self.write_marker(groups)
            else:self.install(groups)
        except BaseException as error:
            self.save_operation(dict(record,status='cleanup_unconfirmed' if getattr(error,'cleanup_unconfirmed',False) else 'failed',error=str(error),
                                     recovery='Installation may be partial. Stop external installers, inspect, and repeat pin synchronization after resolving the failure.'))
            raise
        self.save_operation(dict(record,status='completed'))

    def confirm(self, message, action='Continue with this operation'):
        message=re.sub(r'Free disk space: (\d+) bytes\.',lambda match:'Free disk space: {:.1f} GiB.'.format(int(match.group(1))/(1024.0**3)),message)
        approved=self.screens.confirm(message,action,custom=self._ui_mode and self._custom_allowed)
        if approved and self._ui_mode:self.screens.write('Working. Please wait; Ctrl-C interrupts the operation.')
        return approved

    def check_selected_matches(self, state):
        _, selected = self.selected_python()
        current = state['interpreter']
        if (selected['version'][:2] != current['version'][:2]
                or interpreter_abi(selected) != interpreter_abi(current)
                or Path(selected['base_executable']).resolve() != Path(current['base_executable']).resolve()):
            raise EnvironmentError('Selected base interpreter differs from .venv; use explicit rebuild')

    @maintenance_operation
    def ensure_pip(self):
        if not self._rebuilding:self.check_pending_operation()
        self.require_environment()
        if not self.command([self.python, '-I', '-m', 'pip', '--version']).returncode == 0:
            self.checked([self.python, '-I', '-m', 'ensurepip', '--upgrade'])

    @maintenance_operation
    def create_or_repair(self):
        self.check_pending_operation()
        if not self.confirm('Set up or repair this project’s Python environment and install the required package versions. '
                            'Existing project files and optional package selections are preserved. '
                            'Stop LVS and external installers first. An existing environment is updated in place; this is not a backup/rollback operation.',
                            'Set up or repair Python environment'):
            return False
        selected, info = self.selected_python()
        if not self.venv.exists() and not self.venv.is_symlink():
            return self.replace_environment(selected, self.groups())
        state = self.require_environment()
        self.check_selected_matches(state)
        self.synchronize_groups(self.groups())
        return True

    @maintenance_operation
    def sync(self, group=None):
        self.check_pending_operation()
        state = self.require_environment()
        self.check_selected_matches(state)
        groups = self.groups()
        if group and group not in groups:
            groups.append(group)
        if not self.confirm('Update installed Python packages for {} to the versions required by LVS. '
                            'This updates the existing environment in place; it does not create a rollback backup. '
                            'Project files, results and settings are preserved. Stop LVS and external installers first.'.format(', '.join(groups)),
                            'Update installed Python packages'):
            return False
        self.synchronize_groups(groups)
        return True

    def unique_backup(self, label):
        return self.root / ('.venv.' + label + '-' + datetime.datetime.now().strftime('%Y%m%dT%H%M%S%f') + '-' + uuid4().hex[:12])

    @maintenance_operation
    def replace_environment(self, selected, groups):
        self.check_pending_operation()
        support = self.probe(selected)
        if 'error' in support or not support.get('venv') or not support.get('ensurepip'):
            raise EnvironmentError('Selected Python lacks usable venv/ensurepip support; consult the distro/image Python provider. Existing environment was not moved.')
        # No temporary-path venv: installed scripts must name the final .venv.
        backup = None
        record={'operation':'rebuild','status':'running','groups':groups,'selected_python':str(selected),
                'old_identity':self.path_identity(self.venv)}
        if self.venv.exists() or self.venv.is_symlink():
            if self.venv.is_symlink() or not (self.venv / 'pyvenv.cfg').is_file() or (self.venv / 'pyvenv.cfg').is_symlink():
                raise EnvironmentError('Refusing to replace an unrelated/symlinked .venv path')
            backup = self.unique_backup('backup')
            record['backup']=str(backup)
        self.save_operation(record)
        if backup is not None:
            self.venv.rename(backup)
            self.output('Previous environment retained: ' + str(backup))
        self._rebuilding = True
        try:
            self.venv.mkdir(mode=0o700)
            record['new_identity']=self.path_identity(self.venv)
            self.save_operation(record)
            self.checked([selected, '-I', '-m', 'venv', str(self.venv)], timeout=180)
            self.require_environment()
            self.ensure_pip()
            self.install(groups)
        except BaseException as original_error:
            if getattr(original_error, 'cleanup_unconfirmed', False):
                self.save_operation(dict(record,status='cleanup_unconfirmed',error=str(original_error)))
                raise EnvironmentError('Installation process cleanup is unconfirmed; replacement left in place, previous backup retained at {}. Stop the processes before manual recovery.'.format(backup))
            try:
                if self.venv.exists() or self.venv.is_symlink():
                    failed = self.unique_backup('failed')
                    self.venv.rename(failed)
                    self.output('Partial replacement retained: ' + str(failed))
                if backup is not None:
                    backup.rename(self.venv)
                    restored=self.inspect()
                    self.output('Previous environment restored: {}. Inspect before resuming. {}'.format(
                        'compatible' if restored['valid'] else 'not reusable', '; '.join(restored['issues'])))
                self.save_operation(dict(record,status='restored' if backup is not None else 'failed',error=str(original_error)))
            except (OSError, EnvironmentError) as recovery_error:
                raise EnvironmentError('Rebuild failed: {}; recovery incomplete: {}. Previous backup: {}. Inspect .venv before use.'.format(
                    original_error, recovery_error, backup))
            raise
        finally:
            self._rebuilding = False
        self.save_operation(dict(record,status='completed'))
        return True

    @maintenance_operation
    def rebuild(self):
        self.check_pending_operation()
        selected, info = self.selected_python()
        groups = self.groups()
        if not self.confirm('Build a fresh Python environment at .venv using {}. Free disk space: {} bytes. '
                            'The previous environment will be saved as a backup; no backup is deleted. '
                            'Known optional packages are carried forward. Project files, results and settings are preserved. '
                            'Stop LVS and external installers first.'.format(selected, shutil.disk_usage(str(self.root)).free),
                            'Rebuild Python environment'):
            return False
        return self.replace_environment(selected, groups)

    @maintenance_operation
    def upgrade_tools(self):
        self.check_pending_operation()
        self.require_environment()
        if self.wheelhouse:
            raise EnvironmentError('Packaging-tool upgrade is an explicit online action; normal offline synchronization remains available')
        if self.confirm('Update pip, setuptools and wheel from the online package index. '
                        'This is separate from updating LVS’s required packages; installed packages are checked afterward.',
                        'Update Python installation tools'):
            self.synchronize_groups(self.groups(),tools=True)
            return True
        return False

    def google_readiness(self):
        self.require_environment()
        result = {'python_dependencies': self.packages('google')}
        try:
            raw = self.checked([self.python, '-I', '-c', GOOGLE, str(self.root)], timeout=20)
            result['existing_uploader_readiness'] = json.loads(raw.stdout)
        except (EnvironmentError, ValueError) as error:
            result['existing_uploader_readiness'] = {'status': 'unavailable', 'error': str(error)}
        result['python_dependencies_installed'] = all(v['matches'] for v in result['python_dependencies']['packages'].values())
        result['python_modules_importable'] = all(v['importable'] for v in result['python_dependencies']['imports'].values())
        result['overall_uploader_readiness'] = (result['python_dependencies_installed'] and result['python_modules_importable']
                                                and result['existing_uploader_readiness'].get('ready') is True)
        result['limitations'] = 'Uploader readiness uses module discovery, credential-file presence, shared-drive configuration and DNS; it is not authenticated API/TLS/access verification.'
        return result

    def bridge(self, code, label):
        self.require_environment()
        if not self.confirm(label):
            return False
        self.checked([self.python, '-I', '-c', code, str(self.root)], timeout=600, capture=self._ui_mode)
        return True

    def diagnostics(self):
        policy = python_policy(self.root)
        state = self.inspect()
        try:
            selected,selected_info = self.selected_python()
        except EnvironmentError as error:
            selected = {'unavailable': str(error)}
            selected_info={}
        report = {'contract_id': 'linux_validation_suite.environment_manager', 'contract_version': 1,
                  'kind': 'python_environment_inspection', 'scope': 'bootstrap_python_only_not_hardware_readiness',
                  'project_root': str(self.root), 'system': system_environment(), 'python_policy': policy,
                  'active_interpreter': sys.executable, 'active_version': list(sys.version_info[:3]),
                  'selected_interpreter': selected, 'environment': state,
                  'selected_interpreter_details':selected_info,
                  'free_disk_bytes': shutil.disk_usage(str(self.root)).free,
                  'selected_version_tested': selected_info.get('version',[])[:2] == list(policy['tested']),
                  'available_interpreters': self.candidates(),
                  'package_source': str(self.wheelhouse) if self.wheelhouse else 'online index; network/wheel availability not yet established'}
        if state['valid']:
            report['python_groups'] = {}
            for group in PYTHON_GROUPS:
                try:report['python_groups'][group]=self.packages(group)
                except EnvironmentError as error:report['python_groups'][group]={'error':str(error)}
            if state['pip']:
                check = self.command(self.pip_command(['check']))
                report['pip_consistency'] = {'ok': check.returncode == 0, 'detail': check.stdout}
        baseline = report.get('python_groups', {}).get('baseline', {})
        report['python_baseline_ready'] = bool(state['valid'] and state['pip']
            and report.get('pip_consistency', {}).get('ok')
            and baseline.get('packages') and all(v['matches'] for v in baseline['packages'].values())
            and baseline.get('imports') and all(v['importable'] for v in baseline['imports'].values()))
        report['selected_optional_groups'] = self.groups()[1:]
        report['python_selected_groups_ready'] = report['python_baseline_ready'] and all(
            self.group_ready(report.get('python_groups',{}).get(group,{})) for group in report['selected_optional_groups'])
        report['maintenance_lock'] = self.lock_status()
        if report['maintenance_lock'] in ('active','unavailable'):
            report['python_baseline_ready']=False
            report['python_selected_groups_ready']=False
        report['recommendation'] = self.recommendation(report)
        return report

    @staticmethod
    def group_ready(value):
        return bool(value.get('packages') and value.get('imports')
                    and all(v['matches'] for v in value['packages'].values())
                    and all(v['importable'] for v in value['imports'].values()))

    def lock_status(self):
        if self._lock_fd is not None:return 'owned_by_this_operation'
        try:
            fd=os.open(str(self.root/LOCK),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        except FileNotFoundError:return 'idle'
        except OSError:return 'unavailable'
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):return 'unavailable'
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return 'active'
            return 'idle'
        finally:os.close(fd)

    def recommendation(self, report):
        state=report['environment'];record=state.get('maintenance',{})
        if report.get('maintenance_lock') in ('active','unavailable'):
            return {'action':'wait','reason':'Maintenance is active or its lock cannot be inspected; resolve it before modifying the environment.'}
        if state.get('maintenance_error'):
            return {'action':'manual','reason':state['maintenance_error']}
        if record.get('status')=='cleanup_unconfirmed':
            return {'action':'manual','reason':'Installer cleanup was not confirmed. Retain backups, stop installer processes, then resolve the operation record manually.'}
        if record and record['root']!=str(self.root) and record['status']=='running':
            return {'action':'manual','reason':'Unresolved maintenance belongs to another path; do not automatically restore foreign backup paths.'}
        if record.get('operation')=='rebuild' and record.get('status')=='running':
            return {'action':'recover','reason':'An interrupted rebuild has retained recovery evidence. Review and restore the previous environment or retain the partial creation.'}
        if not isinstance(report['selected_interpreter'],str):
            return {'action':'select','reason':'Select a suitable installed base Python; the previous selection is unavailable or unsuitable.'}
        if not state['valid']:
            if self.venv.is_symlink() or (self.venv.exists() and (not self.venv.is_dir() or not (self.venv/'pyvenv.cfg').is_file())):
                return {'action':'manual','reason':'Unrelated/unrecognized .venv path: preserve it and resolve manually; it will not be overwritten.'}
            return {'action':'rebuild' if self.venv.exists() else 'create','reason':'; '.join(state['issues'])}
        chosen=report['selected_interpreter_details'];current=state['interpreter']
        if (Path(chosen['base_executable']).resolve()!=Path(current['base_executable']).resolve()
                or chosen['version'][:2]!=current['version'][:2] or interpreter_abi(chosen)!=interpreter_abi(current)):
            return {'action':'rebuild','reason':'Chosen Python differs from the existing environment; build fresh site-packages with the selected interpreter.'}
        if not state['pip']:
            if not state.get('interpreter',{}).get('ensurepip'):
                return {'action':'manual','reason':'pip and usable ensurepip are unavailable. Resolve matching Python venv/ensurepip prerequisites, or select another compatible Python and explicitly rebuild. No package command is run automatically.'}
            return {'action':'repair','reason':'Repair pip with this environment’s ensurepip, then verify project pins/imports.'}
        if not report['python_selected_groups_ready']:
            return {'action':'sync','reason':'Direct pins, imports or pip consistency need repair; synchronize the selected groups.'}
        return {'action':'reuse','reason':'Compatible environment and selected package groups verified. Reuse it; synchronize only when requested.'}

    @staticmethod
    def action_label(action):
        return {'reuse':'Keep using this environment', 'repair':'Repair Python environment',
                'create':'Set up Python environment', 'sync':'Update installed Python packages',
                'rebuild':'Rebuild Python environment', 'recover':'Recover interrupted setup',
                'select':'Choose an installed Python', 'wait':'Wait for maintenance to finish',
                'manual':'Resolve the reported problem first'}.get(action,action)

    def show_inspection(self, report):
        state=report['environment'];info=state.get('interpreter',{})
        action=report['recommendation']['action']
        reasons={
            'reuse':'Python and the selected packages passed the health checks.',
            'repair':'The package installer is unavailable. Repair is supported by this Python installation.',
            'create':'This project does not have its own Python environment yet.',
            'sync':'Some package versions, imports or dependency checks need attention.',
            'rebuild':'The current environment does not match the selected Python or this project location/system.',
            'recover':'A previous setup stopped before it finished. Saved recovery information is available.',
            'select':'The previous Python selection is unavailable or unsuitable.',
            'wait':'Another maintenance operation is active, or its lock could not be checked.',
            'manual':'The environment cannot be changed safely until the reported problem is resolved.'}
        self.screens.write('Current status: '+('Ready to use' if report['python_selected_groups_ready'] and action=='reuse' else 'Needs attention'))
        if 'version' in info:
            self.screens.write('Environment Python: {} ({})'.format('.'.join(map(str,info['version'])),self.python))
        selected=report.get('selected_interpreter_details',{})
        if 'version' in selected:
            self.screens.write('Selected Python: {} ({})'.format('.'.join(map(str,selected['version'])),report['selected_interpreter']))
        self.screens.write('Required packages: '+('Verified' if report['python_baseline_ready'] else 'Need checking or repair'))
        self.screens.write('Google Drive packages: '+('Selected' if 'google' in report['selected_optional_groups'] else 'Optional; not selected'))
        self.screens.write('Recommended action: '+self.action_label(action))
        self.screens.write('Why: '+reasons.get(action,'See technical details.'))
        if action in ('manual','wait'):
            self.screens.write('Important: '+report['recommendation']['reason'])
        for path in state.get('retained_environments',[])[:3]:self.screens.write('Saved environment: '+path)
        if len(state.get('retained_environments',[]))>3:self.screens.write('Additional saved environments are listed in technical details.')
        if any('Unmarked' in value for value in state['warnings']):
            self.screens.write('Note: this older environment has no recorded machine history.')
        self.screens.write('Technical details include the full health checks, package names and interpreter identity.')

    @maintenance_operation
    def recover_interrupted(self):
        record=self.operation_record()
        if record.get('status')!='running' or record.get('operation')!='rebuild':
            raise EnvironmentError('No automatically recoverable interrupted rebuild. Inspect retained paths manually.')
        if record['root']!=str(self.root):raise EnvironmentError('Refusing recovery from a foreign project path')
        backup=Path(record['backup']) if record.get('backup') else None
        if backup is not None:
            if (backup.parent==self.root and backup.name.startswith('.venv.backup-')
                    and record.get('old_identity') and not backup.exists()
                    and self.path_identity(self.venv)==record['old_identity']):
                self.save_operation(dict(record,status='restored'));return True
            if backup.parent!=self.root or not backup.name.startswith('.venv.backup-') or self.path_identity(backup)!=record.get('old_identity'):
                raise EnvironmentError('Backup identity cannot be verified; retain paths for manual recovery')
        if self.venv.exists() or self.venv.is_symlink():
            if not record.get('new_identity') or self.path_identity(self.venv)!=record['new_identity']:
                # A crash before the old rename leaves the original in place.
                if backup is not None and self.path_identity(self.venv)==record.get('old_identity') and not backup.exists():
                    self.save_operation(dict(record,status='restored'));return True
                raise EnvironmentError('Replacement identity cannot be verified; no path will be moved')
        if not self.confirm('Save the unfinished environment and restore the verified backup, if one exists. '
                            'No environment will be deleted. Stop external installers first.', 'Recover interrupted setup'):
            return False
        if self.venv.exists():
            failed=self.unique_backup('failed');self.venv.rename(failed);self.output('Partial creation retained: '+str(failed))
        if backup is not None:
            backup.rename(self.venv);self.output('Previous environment restored. Its current compatibility must still be checked.')
        self.save_operation(dict(record,status='restored' if backup is not None else 'failed'))
        return True

    def guided_maintenance(self, requested=None):
        self._custom_allowed=False
        report=self.diagnostics();self.show_inspection(report)
        if self._ui_mode:self._technical_output.append(json.dumps(report,indent=2))
        action=requested or report['recommendation']['action']
        if report['recommendation']['action'] in ('wait','manual','recover'):action=report['recommendation']['action']
        elif requested!='rebuild' and report['recommendation']['action'] in ('create','repair','rebuild'):
            action=report['recommendation']['action']
        if action in ('wait','manual','reuse'):return False
        if action=='select':
            self.choose_python()
            return self.guided_maintenance(requested)
        if action=='recover':
            return self.perform(self.recover_interrupted)
        self.screens.write('Package source: '+(str(self.wheelhouse) if self.wheelhouse else 'Online package index'))
        self.screens.write('A virtual environment keeps this project’s Python packages separate from system packages.')
        self._custom_allowed=self._ui_mode
        try:
            if action=='rebuild':return self.perform(self.rebuild)
            if action in ('create','repair'):return self.perform(self.create_or_repair)
            return self.perform(lambda:self.sync('google' if requested=='google' else None))
        except CustomizeEnvironment:
            self.advanced_settings()
            return self.guided_maintenance(requested)
        finally:self._custom_allowed=False

    def choose_python(self):
        options = self.candidates()
        for i, option in enumerate(options, 1):
            self.output('{}. {} {}'.format(i, option['path'], option['details'].get('version', option['details'].get('error'))))
        raw = self.ask('Python number, installed interpreter path, or Enter to keep current/default: ').strip()
        if not raw and self.selected and 'error' in self.probe(self.selected):
            self.output('Previously selected interpreter is unavailable; selecting a suitable installed default.')
            self.selected=None
        if raw:
            if raw.isdigit():
                if not 1 <= int(raw) <= len(options):
                    raise EnvironmentError('Interpreter option is out of range')
                raw = options[int(raw)-1]['path']
            old = self.selected
            self.selected = raw
            try:
                self.selected_python()
            except BaseException:
                self.selected = old
                raise
        self.output('Selected: ' + self.selected_python()[0])

    def choose_packages(self):
        raw = self.ask('Local wheel/package directory (Enter = online index): ').strip()
        if raw:
            path = Path(raw).expanduser().resolve()
            if not path.is_dir():
                raise EnvironmentError('Not a local package directory')
            self.wheelhouse = path
        else:
            self.wheelhouse = None

    def perform(self, function):
        """Collect backend chatter for optional details, without changing its work."""
        if not self._ui_mode:return function()
        previous=self.output
        self.output=lambda value:self._operation_log.append(str(value))
        try:return function()
        finally:self.output=previous

    def advanced_settings(self):
        while True:
            self.screens.open('Advanced settings — this session only')
            self.screens.write('1. Choose an installed Python\n2. Choose online or local packages\n3. Return to the operation')
            choice=self.ask('Choose [3]: ').strip() or '3'
            if choice=='3':return
            if choice=='1':self.choose_python()
            elif choice=='2':self.choose_packages()
            else:
                if self.screens.results('Invalid choice',['Choose 1, 2 or 3.'])=='exit':raise EOFError()

    @staticmethod
    def short_error(error):
        lines=[line.strip() for line in plain_text(error).splitlines() if line.strip()]
        useful=[line for line in lines if any(word in line.lower() for word in ('error','unavailable','denied','no space','unconfirmed','failed'))]
        message=(useful[-1] if useful else lines[-1]) if lines else 'The operation could not complete.'
        return message if len(message)<=300 else message[:297]+'...'

    def run_screen(self, title, function, health=False, summary=None):
        self.screens.open(title)
        self._ui_mode=True;self._technical_output=[];self._operation_log=[]
        report=None;follow=None;lines=[]
        try:
            if health:
                report=function();self.show_inspection(report)
                self._technical_output.append(json.dumps(report,indent=2))
                action=report['recommendation']['action']
                if action not in ('reuse','manual','wait'):follow=self.action_label(action)
                lines=['Health check finished. No environment or package changes were made.']
            else:
                result=function()
                lines=[('Cancelled. No operation was performed.' if result is False else
                        (summary or 'Operation completed. See the notes below for any saved environments.'))]
        except KeyboardInterrupt as error:
            lines=['Operation interrupted. Check environment health before trying again.']
            self._technical_output.append('KeyboardInterrupt: '+str(error))
        except EOFError:
            lines=['Input closed. No further operation will be started.']
        except (EnvironmentError,OSError,ValueError,KeyError) as error:
            lines=['Operation did not complete.',self.short_error(str(error))]
            self._technical_output.append(str(error))
        finally:
            self._ui_mode=False;self._custom_allowed=False
        for message in self._operation_log:
            if any(word in message.lower() for word in ('backup','retained','restored','cleanup','partial')):
                message=message.replace('Previous environment retained:', 'Previous environment saved as backup:')
                message=message.replace('Partial replacement retained:', 'Unfinished environment saved for recovery:').replace('Partial creation retained:', 'Unfinished environment saved for recovery:')
                message=message.replace('Inspect before resuming.', 'Check environment health before continuing.')
                if message not in lines:lines.append(message)
        try:
            record=self.operation_record()
            if record.get('status') in ('failed','running','cleanup_unconfirmed'):
                if record.get('operation') in ('synchronize','tools'):
                    lines.append('The package update may be partial. It has not been rolled back. Check health, then retry after resolving the problem.')
                elif record.get('status')=='cleanup_unconfirmed':
                    lines.append('Installer cleanup is not confirmed. Keep all environments and backups; stop installer processes before manual recovery.')
                else:lines.append('Setup recovery may still be needed. Keep saved environments and check health before continuing.')
        except (EnvironmentError,OSError,ValueError) as error:
            lines.append('Recovery information could not be read. Keep all saved environments and review technical details.')
            self._technical_output.append(str(error))
        details='\n\n'.join(self._technical_output+self._operation_log)
        reply=self.screens.results(title+' — results',lines,details,follow)
        if reply=='follow':
            return self.run_screen('Recommended maintenance',self.guided_maintenance)
        return reply

    def choose_submenu(self, title, text, back):
        self.screens.open(title);self.screens.write(text)
        return self.ask('Choose [{}]: '.format(back)).strip() or str(back)

    def google_status_screen(self):
        value=self.google_readiness()
        self._technical_output.append(json.dumps(value,indent=2))
        self.screens.write('Google Python packages: '+('Required versions installed' if value['python_dependencies_installed'] else 'Need installation or update'))
        self.screens.write('Google Python imports: '+('Working' if value['python_modules_importable'] else 'Unavailable'))
        readiness=value['existing_uploader_readiness']
        for key,label in [('credential_exists','Credentials file'),('shared_drive_id_configured','Shared Drive configuration'),('dns_ok','Google DNS lookup')]:
            state=readiness.get(key)
            self.screens.write(label+': '+('Available' if state is True else 'Not ready' if state is False else 'Not checked'))
        self.screens.write('Uploader readiness: '+('Ready according to the existing checks' if value['overall_uploader_readiness'] else 'Not ready'))
        self.screens.write('These checks do not authenticate or test upload permissions.')
        return True

    def menu(self):
        while True:
            self.screens.open('LVS Environment Manager')
            self.screens.write('1. Check environment health\n2. Set up or repair Python environment\n'
                               '3. Update installed Python packages\n4. Google Drive packages and readiness\n'
                               '5. Rebuild Python environment\n6. Build or check native helper programs\n'
                               '7. Run the full LVS dependency check\n8. Exit')
            try:
                choice=self.ask('Choose [1]: ').strip() or '1'
                if choice=='8':return
                if choice=='1':reply=self.run_screen('Environment health',self.diagnostics,health=True)
                elif choice=='2':reply=self.run_screen('Set up or repair Python environment',lambda:self.guided_maintenance('repair'))
                elif choice=='5':reply=self.run_screen('Rebuild Python environment',lambda:self.guided_maintenance('rebuild'))
                elif choice=='3':
                    sub=self.choose_submenu('Python package maintenance',
                        '1. Update the packages required by LVS\n2. Update pip and build tools (advanced)\n'
                        '3. Choose Python for the next operation (advanced)\n4. Choose package source (advanced)\n5. Back to the menu',5)
                    if sub=='5':continue
                    if sub=='1':reply=self.run_screen('Update installed Python packages',lambda:self.guided_maintenance('sync'))
                    elif sub=='2':reply=self.run_screen('Update Python installation tools',lambda:self.perform(self.upgrade_tools))
                    elif sub=='3':reply=self.run_screen('Choose Python',self.choose_python,summary='Python selection reviewed. This choice applies to this manager session; the environment was not replaced.')
                    elif sub=='4':reply=self.run_screen('Choose package source',self.choose_packages,summary='Package source reviewed. No packages were changed.')
                    else:reply=self.screens.results('Invalid choice',['Choose one of the listed numbers.'])
                elif choice=='4':
                    sub=self.choose_submenu('Google Drive support','1. Install or update Google Drive packages\n2. Check Google Drive readiness\n3. Back to the menu',3)
                    if sub=='3':continue
                    if sub=='1':reply=self.run_screen('Google Drive packages',lambda:self.guided_maintenance('google'),
                        summary='The selected maintenance step finished. If setup or rebuilding was needed first, choose Google Drive packages again to add them.')
                    elif sub=='2':reply=self.run_screen('Google Drive readiness',self.google_status_screen,summary='Google Drive readiness check finished. No package changes were made.')
                    else:reply=self.screens.results('Invalid choice',['Choose one of the listed numbers.'])
                elif choice=='6':reply=self.run_screen('Native helper programs',lambda:self.perform(lambda:self.bridge(NATIVE,
                    'Build helper programs for this machine, save existing programs as backups and run readiness queries only? No stress workload will run.')),
                    summary='Native helper build/check finished. This does not establish physical ISA acceptance.')
                elif choice=='7':reply=self.run_screen('Full LVS dependency check',lambda:self.perform(lambda:self.bridge(DEPENDENCIES,
                    'Run the existing LVS dependency check and save its report? It may build/query helpers and check DNS; no system packages will be installed.')),
                    summary='Dependency check finished. Review the full findings and saved-report location in technical details; this is not a hardware PASS.')
                else:reply=self.screens.results('Invalid choice',['Choose a number from 1 to 8.'])
                if reply=='exit':return
            except (EOFError,KeyboardInterrupt):
                self.screens.write('\nClosing the manager. No further operation will be started.');return



def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='print local bootstrap diagnostics without installing/building')
    parser.add_argument('--python', dest='selected', help='explicit installed base Python interpreter')
    parser.add_argument('--wheelhouse', help='offline local packages; pip uses --no-index --find-links')
    args = parser.parse_args(argv)
    manager = EnvironmentManager(selected=args.selected, wheelhouse=args.wheelhouse)
    if args.check:
        try:
            print(json.dumps(manager.diagnostics(), indent=2));return 0
        except (EnvironmentError, OSError, ValueError, KeyError) as error:
            print('Environment diagnostics incomplete: ' + str(error));return 1
    manager.menu()
    return 0


if __name__ == '__main__':
    sys.exit(main())
