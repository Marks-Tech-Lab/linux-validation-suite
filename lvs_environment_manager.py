#!/usr/bin/env python3
"""Numbered-menu LVS bootstrap/maintenance utility. Standard library only.

No LVS runtime import or native build occurs at startup. Runtime integrations run
only on request, in a validated target .venv subprocess. No shell/elevation/global
pip is used. This file intentionally avoids modern typing syntax so an older
Python can explain the project's newer minimum and select another interpreter.
"""
import argparse
import datetime
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
from pathlib import Path
from uuid import uuid4

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from Modules.lvs_python_environment import PYTHON_GROUPS, python_policy, requirement_pins

MARKER = '.lvs-environment.json'
PROBE = '''import sys, os, platform, sysconfig, json, importlib.util
print(json.dumps(dict(version=list(sys.version_info[:3]), executable=sys.executable,
 prefix=sys.prefix, base_prefix=getattr(sys,'base_prefix',sys.prefix),
 base_executable=getattr(sys,'_base_executable',sys.executable),
 architecture=platform.machine(), platform_tag=sysconfig.get_platform(),
 bits=__import__('struct').calcsize('P')*8,
 venv=importlib.util.find_spec('venv') is not None,
 ensurepip=importlib.util.find_spec('ensurepip') is not None)))'''
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


class EnvironmentManager:
    def __init__(self, root=None, runner=None, ask=input, output=print, selected=None, wheelhouse=None):
        self.root = Path(root or Path(__file__).resolve().parent).resolve()
        self.venv = self.root / '.venv'
        self.python = self.venv / 'bin/python'
        self.runner = runner or run_managed_command
        self.ask = ask
        self.output = output
        self.selected = str(selected) if selected else None
        self.wheelhouse = Path(wheelhouse).expanduser().resolve() if wheelhouse else None

    def command(self, args, timeout=60, capture=True):
        env = {k: v for k, v in os.environ.items() if not k.startswith('PIP_')
               and k not in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV')}
        env.update(PIP_CONFIG_FILE=os.devnull, PYTHONDONTWRITEBYTECODE='1')
        args = [str(a) for a in args]
        if len(args) > 1 and args[1] == '-I':
            args.insert(1, '-B')
        kwargs = dict(cwd=str(self.root), env=env, timeout=timeout, universal_newlines=True)
        if capture:
            kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            return self.runner([str(a) for a in args], **kwargs)
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
                    if 'error' not in info and tuple(info['version'][:2]) >= policy['minimum']:
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
        if marker.exists():
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
                                ('os', system_environment()['distribution']), ('machine_id', machine_identity())]:
                if recorded.get(key) != actual:
                    result['issues'].append('Recorded {} differs; rebuild for the current machine/OS'.format(key))
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
        for group in recorded.get('optional_groups', []):
            if group in PYTHON_GROUPS and group not in selected:
                selected.append(group)
        if state['valid'] and 'google' not in selected:
            check = self.packages('google')
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

    def write_marker(self, groups):
        _, info = self.selected_python()
        payload = {'root': str(self.root), 'architecture': normalized_arch(platform.machine()),
                   'os': system_environment()['distribution'], 'base_executable': info['base_executable'],
                   'python_version': info['version'], 'machine_id': machine_identity(), 'optional_groups': [g for g in groups if g != 'baseline']}
        temp = self.venv / (MARKER + '.tmp')
        temp.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        os.replace(str(temp), str(self.venv / MARKER))

    def install(self, groups):
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
        for group in groups:
            check = self.packages(group)
            if not all(v['matches'] for v in check['packages'].values()) or not all(v['importable'] for v in check['imports'].values()):
                raise EnvironmentError('Post-install package/import verification failed: ' + json.dumps(check))
        self.write_marker(groups)
        self.output('Synchronized and independently verified: ' + ', '.join(groups))

    def confirm(self, message):
        return self.ask(message + ' [y/N]: ').strip().lower() in ('y', 'yes')

    def check_selected_matches(self, state):
        _, selected = self.selected_python()
        current = state['interpreter']
        if (selected['version'][:2] != current['version'][:2]
                or Path(selected['base_executable']).resolve() != Path(current['base_executable']).resolve()):
            raise EnvironmentError('Selected base interpreter differs from .venv; use explicit rebuild')

    def ensure_pip(self):
        if not self.command([self.python, '-I', '-m', 'pip', '--version']).returncode == 0:
            self.checked([self.python, '-I', '-m', 'ensurepip', '--upgrade'])

    def create_or_repair(self):
        if not self.confirm('Stop LVS/other installers first. Create/reuse .venv, repair pip and install project pins? Network unless a wheelhouse is selected.'):
            return False
        selected, info = self.selected_python()
        if not self.venv.exists() and not self.venv.is_symlink():
            return self.replace_environment(selected, ['baseline'])
        state = self.require_environment()
        self.check_selected_matches(state)
        self.ensure_pip()
        self.install(self.groups())
        return True

    def sync(self, group=None):
        state = self.require_environment()
        self.check_selected_matches(state)
        groups = self.groups()
        if group and group not in groups:
            groups.append(group)
        if not self.confirm('Synchronize {} to requirement-file pins? Network unless local packages selected.'.format(', '.join(groups))):
            return False
        self.ensure_pip()
        self.install(groups)
        return True

    def unique_backup(self, label):
        return self.root / ('.venv.' + label + '-' + datetime.datetime.now().strftime('%Y%m%dT%H%M%S%f') + '-' + uuid4().hex[:12])

    def replace_environment(self, selected, groups):
        support = self.probe(selected)
        if 'error' in support or not support.get('venv') or not support.get('ensurepip'):
            raise EnvironmentError('Selected Python lacks usable venv/ensurepip support; consult the distro/image Python provider. Existing environment was not moved.')
        # No temporary-path venv: installed scripts must name the final .venv.
        backup = None
        if self.venv.exists() or self.venv.is_symlink():
            if self.venv.is_symlink() or not (self.venv / 'pyvenv.cfg').is_file() or (self.venv / 'pyvenv.cfg').is_symlink():
                raise EnvironmentError('Refusing to replace an unrelated/symlinked .venv path')
            backup = self.unique_backup('backup')
            self.venv.rename(backup)
            self.output('Previous environment retained: ' + str(backup))
        try:
            self.checked([selected, '-I', '-m', 'venv', str(self.venv)], timeout=180)
            self.require_environment()
            self.ensure_pip()
            self.install(groups)
        except BaseException as original_error:
            if getattr(original_error, 'cleanup_unconfirmed', False):
                raise EnvironmentError('Installation process cleanup is unconfirmed; replacement left in place, previous backup retained at {}. Stop the processes before manual recovery.'.format(backup))
            try:
                if self.venv.exists() or self.venv.is_symlink():
                    failed = self.unique_backup('failed')
                    self.venv.rename(failed)
                    self.output('Partial replacement retained: ' + str(failed))
                if backup is not None:
                    backup.rename(self.venv)
                    self.output('Previous environment restored; current assessment: ' + json.dumps(self.inspect()))
            except (OSError, EnvironmentError) as recovery_error:
                raise EnvironmentError('Rebuild failed: {}; recovery incomplete: {}. Previous backup: {}. Inspect .venv before use.'.format(
                    original_error, recovery_error, backup))
            raise
        return True

    def rebuild(self):
        selected, info = self.selected_python()
        groups = self.groups()
        if not self.confirm('Rebuild at .venv using {}? Free disk: {} bytes. Existing environment will be backed up; no backup is deleted.'.format(selected, shutil.disk_usage(str(self.root)).free)):
            return False
        return self.replace_environment(selected, groups)

    def upgrade_tools(self):
        self.require_environment()
        if self.wheelhouse:
            raise EnvironmentError('Packaging-tool upgrade is an explicit online action; normal offline synchronization remains available')
        if self.confirm('Explicitly upgrade pip/setuptools/wheel (separate from project pin synchronization)?'):
            self.ensure_pip()
            self.checked(self.pip_command(['install', '--no-user', '--upgrade', 'pip', 'setuptools', 'wheel']), timeout=900)
            self.checked(self.pip_command(['check']))

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
        self.checked([self.python, '-I', '-c', code, str(self.root)], timeout=600, capture=False)
        return True

    def diagnostics(self):
        policy = python_policy(self.root)
        state = self.inspect()
        try:
            selected = self.selected_python()[0]
        except EnvironmentError as error:
            selected = {'unavailable': str(error)}
        report = {'contract_id': 'linux_validation_suite.environment_manager', 'contract_version': 1,
                  'kind': 'python_environment_inspection', 'scope': 'bootstrap_python_only_not_hardware_readiness',
                  'project_root': str(self.root), 'system': system_environment(), 'python_policy': policy,
                  'active_interpreter': sys.executable, 'active_version': list(sys.version_info[:3]),
                  'selected_interpreter': selected, 'environment': state,
                  'free_disk_bytes': shutil.disk_usage(str(self.root)).free,
                  'selected_version_tested': (self.probe(selected)['version'][:2] == list(policy['tested'])) if isinstance(selected, str) else False,
                  'available_interpreters': self.candidates(),
                  'package_source': str(self.wheelhouse) if self.wheelhouse else 'online index; network/wheel availability not yet established'}
        if state['valid']:
            report['python_groups'] = {g: self.packages(g) for g in PYTHON_GROUPS}
            if state['pip']:
                check = self.command(self.pip_command(['check']))
                report['pip_consistency'] = {'ok': check.returncode == 0, 'detail': check.stdout}
        baseline = report.get('python_groups', {}).get('baseline', {})
        report['python_baseline_ready'] = bool(state['valid'] and state['pip']
            and report.get('pip_consistency', {}).get('ok')
            and baseline.get('packages') and all(v['matches'] for v in baseline['packages'].values())
            and baseline.get('imports') and all(v['importable'] for v in baseline['imports'].values()))
        return report

    def choose_python(self):
        options = self.candidates()
        for i, option in enumerate(options, 1):
            self.output('{}. {} {}'.format(i, option['path'], option['details'].get('version', option['details'].get('error'))))
        raw = self.ask('Python number, installed interpreter path, or Enter to keep current/default: ').strip()
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

    def menu(self):
        while True:
            self.output('\nLVS Environment Manager\n'
                        '1. Check environment and dependencies\n2. Create or repair .venv\n'
                        '3. Update/synchronize .venv\n4. Manage optional Python dependency groups\n'
                        '5. Rebuild .venv for this machine\n6. Build/verify native helpers\n'
                        '7. Run/open LVS dependency checker\n8. Exit')
            try:
                choice = self.ask('Choose [1]: ').strip() or '1'
                if choice == '8':
                    return
                if choice == '1':
                    self.output(json.dumps(self.diagnostics(), indent=2))
                elif choice in ('2', '5'):
                    self.choose_python(); self.choose_packages()
                    self.create_or_repair() if choice == '2' else self.rebuild()
                elif choice == '3':
                    sub = self.ask('1. Synchronize project pins  2. Explicit packaging-tool upgrade  3. Select Python  [Enter = back]: ').strip()
                    if sub == '1':self.choose_packages();self.sync()
                    elif sub == '2':self.upgrade_tools()
                    elif sub == '3':self.choose_python()
                elif choice == '4':
                    sub = self.ask('1. Install/sync Google dependencies  2. Check Google imports/readiness  [Enter = back]: ').strip()
                    if sub == '1':self.choose_packages();self.sync('google')
                    elif sub == '2':self.output(json.dumps(self.google_readiness(), indent=2))
                elif choice == '6':
                    self.bridge(NATIVE, 'Build current-machine helpers from source, preserve previous binaries, and run only readiness queries?')
                elif choice == '7':
                    self.bridge(DEPENDENCIES, 'Run authoritative LVS dependency check (may build/query helpers and DNS; saves a new report; no sudo)?')
                else:
                    self.output('Choose a number from 1 to 8.')
            except EOFError:
                self.output('Input closed. Existing environments and backups are retained.');return
            except KeyboardInterrupt:
                self.output('\nOperation interrupted. Inspect environment status before resuming.')
            except (EnvironmentError, OSError, ValueError, KeyError) as error:
                self.output('Operation could not complete: ' + str(error))
                self.output('No system packages were installed. For venv/ensurepip/compiler support, consult the detected distro or immutable-image documentation. Missing wheels/repositories require a supported interpreter/package source; an interrupted pip install can be repaired by re-synchronizing.')


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
