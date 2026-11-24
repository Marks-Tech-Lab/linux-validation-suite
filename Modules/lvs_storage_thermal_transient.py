"""On-demand data runtime. No permanent unit, account, install record or updater.

The operator approves exact source/tool/bootstrap bytes, not merely sudo reuse.
ROOT_STAGER is the narrow reviewed OS-Python bootstrap: it does not import or
execute repository Python. Only its protected, hash-verified copy may execute.
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import os
import pwd
import re
import socket
import stat
import subprocess
import sys
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
BASE=Path('/run/lvs-thermal-on-demand')
MODE='lvs.thermal.transient.data.v1'
ENV=dict(PATH='/usr/bin:/bin',HOME='/root',LC_ALL='C',PYTHONDONTWRITEBYTECODE='1')
# Fixed code, no interpolation, shell, eval, repository import or arbitrary entry.
# The reviewed manifest is an operator approval input, not a self-attestation.
ROOT_STAGER=r'''
import os,sys,json,hashlib,stat,tempfile
from pathlib import Path
if os.getuid()!=0 or len(sys.argv)!=4:raise SystemExit('explicit sudo bootstrap required')
source,approved,expected_uid=sys.argv[1:]
uid=int(os.environ.get('SUDO_UID','-1'))
if uid<=0 or str(uid)!=expected_uid or len(approved)!=64 or any(c not in '0123456789abcdef'for c in approved):raise SystemExit('operator/approval mismatch')
os.environ.clear();os.environ.update(PATH='/usr/bin:/bin',HOME='/root',LC_ALL='C',PYTHONDONTWRITEBYTECODE='1')
def trusted(p):
 for a in (p,*p.parents):
  s=a.lstat()
  if s.st_uid!=0 or s.st_mode&0o022 or not stat.S_ISDIR(s.st_mode):raise SystemExit('unsafe runtime ancestor')
def read(root,name,limit):
 parts=name.split('/')
 if not parts or any(x in ('','.','..')for x in parts)or name.startswith('/')or len(name)>512:raise SystemExit('unsafe input path')
 fd=os.open(root,os.O_PATH|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  for part in parts[:-1]:
   nxt=os.open(part,os.O_PATH|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd);os.close(fd);fd=nxt
  pin=os.open(parts[-1],os.O_PATH|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
  try:
   s=os.fstat(pin)
   if not stat.S_ISREG(s.st_mode)or s.st_uid!=uid or s.st_mode&0o022 or s.st_nlink!=1 or s.st_size>limit:raise SystemExit('invalid source file ownership/type/size')
   actual=os.open('/proc/self/fd/'+str(pin),os.O_RDONLY|os.O_NONBLOCK|os.O_CLOEXEC)
   try:
    data=bytearray()
    while len(data)<=limit:
     part=os.read(actual,min(65536,limit+1-len(data)))
     if not part:break
     data+=part
    if len(data)!=s.st_size or len(data)>limit:raise SystemExit('changing source')
    return bytes(data)
   finally:os.close(actual)
  finally:os.close(pin)
 finally:os.close(fd)
raw=read(source,'manifest.json',262144)
if hashlib.sha256(raw).hexdigest()!=approved:raise SystemExit('unapproved manifest')
m=json.loads(raw)
if set(m)!={'contract','source','uid','gid','files','backend'}or m.get('contract')!='lvs.storage_thermal.offline_bundle.v1'or type(m.get('uid'))is not int or m['uid']!=uid or type(m.get('files'))is not dict or not 1<=len(m['files'])<=1024:raise SystemExit('invalid approved inventory')
base=Path('/run/lvs-thermal-on-demand');trusted(base.parent)
try:
 base.mkdir(mode=0o755);base.chmod(0o755)
except FileExistsError:pass
trusted(base)
if base.stat().st_mode&0o555!=0o555:raise SystemExit('existing runtime root is not traversable')
root=Path(tempfile.mkdtemp(prefix=str(uid)+'-',dir=base));total=0
for name,h in m['files'].items():
 if type(name)is not str or type(h)is not str or len(h)!=64:raise SystemExit('invalid approved entry')
 data=read(source,name,33554432);total+=len(data)
 if total>268435456 or hashlib.sha256(data).hexdigest()!=h:raise SystemExit('approved bytes changed')
 p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);p.chmod(0o644)
(root/'manifest.json').write_bytes(raw)
# Verify the v1 execution-source protocol BEFORE importing any snapshot code.
def in_scope(name):
 p=Path(name)
 if any(x.startswith('.')or x=='__pycache__'for x in p.parts):return False
 if len(p.parts)==1:return p.suffix in ('.py','.sh')or(p.name.startswith('requirements')and p.suffix=='.txt')
 return ((p.parts[0]=='Modules'and p.suffix=='.py')or(p.parts[0]=='native'and p.suffix in ('.py','.c','.h','.comp','.glsl'))or(p.parts[0]=='scripts'and p.suffix=='.sh')or(p.parts[0]=='profiles'and len(p.parts)==2 and p.suffix=='.json'))
records=sorted([[n[8:],h]for n,h in m['files'].items()if n.startswith('runtime/')and in_scope(n[8:])])
extras={'launch.py','preparation.json','runtime/scripts/storage_thermal_acceptance.py','runtime/build/fio','runtime/build/storage_thermal_guard','runtime/build/storage_thermal_launch.so','runtime/build/storage_thermal_confidential.so'}
if set(m['files'])!={('runtime/'+n)for n,h in records}|extras:raise SystemExit('unexpected executable snapshot inventory')
required={'linux_validation_suite.py','Modules/lvs_core.py','native/cpu_stress_helper.c','native/memory_stress_helper.c'}
fingerprint=hashlib.sha256(json.dumps(['lvs_execution_source_v1',records],sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
expected=dict(scope='lvs_execution_source_v1',algorithm='sha256',file_count=len(records),digest=fingerprint,status='complete',error_count=0)
if m.get('source')!=expected or type(m['source'].get('file_count'))is not int or type(m['source'].get('error_count'))is not int or not required<={n for n,h in records}:raise SystemExit('execution-source approval mismatch before import')
# No user code has run. All subsequent imports are protected approved bytes.
root.chmod(0o755);sys.path.insert(0,str(root/'runtime'));sys.dont_write_bytecode=True
from Modules.lvs_storage_thermal_transient import bootstrap
print(json.dumps(bootstrap(root,approved)),flush=True)
'''


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tool(name):
    from .lvs_storage_thermal_system import owned_path
    return str(owned_path(Path('/usr/bin/'+name).resolve()))


def candidate():
    """Local metadata only; never start a process or elevate during inspection."""
    from .lvs_storage_thermal_runtime import on_demand_candidate
    return on_demand_candidate()


def prepare_candidate(*, previous=None):
    """Unprivileged build using existing source/native/fio preparation helpers."""
    if os.getuid()==0:raise ValueError('Prepare as the normal LVS operator')
    from .lvs_source_provenance import _source_snapshot,collect_source_provenance
    from scripts.storage_thermal_prepare import prepare
    source=_source_snapshot(ROOT)[0];git=collect_source_provenance(ROOT)['git']
    if source['status']!='complete' or git.get('scoped_commit_match')is not True or git.get('tracked_worktree_state')!='clean':
        raise ValueError('On-demand elevation requires a clean, committed approved execution source')
    # fio approval is the existing Wave 1 cache, not PATH or an override.
    cache=ROOT/'build/thermal-runtime';approval=json.loads((cache/'fio-approval.json').read_text());fio=cache/'fio'
    if fio.is_symlink() or digest(fio)!=approval['sha256']:raise ValueError('Approved fio cache changed')
    stager_sha256 = hashlib.sha256(ROOT_STAGER.encode()).hexdigest()
    if previous is not None and _candidate_unchanged(previous, source, git['commit'],
                                                       approval['sha256'], stager_sha256):
        return previous
    parent=ROOT/'build/thermal-on-demand';parent.mkdir(exist_ok=True)
    destination=parent/(source['digest'][:20]+'-'+uuid4().hex[:12])
    result=prepare(destination,fio)
    m=json.loads((destination/'manifest.json').read_text())
    if m['source']!=source or m['files']['runtime/build/fio']!=approval['sha256']:raise ValueError('Prepared authority mismatch')
    return dict(bundle=str(destination),manifest_sha256=result['manifest_sha256'],source=source,commit=git['commit'],
                tools={k:v for k,v in m['files'].items()if k.startswith('runtime/build/')},
                build=json.loads((destination/'preparation.json').read_text()),
                fio_sha256=approval['sha256'],stager_sha256=stager_sha256)


def _candidate_unchanged(previous, source, commit, fio_sha256, stager_sha256):
    """Recheck a previously approved snapshot. Root still pins every byte again."""
    from .lvs_native_helpers import find_c_compiler
    try:
        if (previous['source'], previous['commit'], previous['fio_sha256'], previous['stager_sha256']) != (
                source, commit, fio_sha256, stager_sha256):
            return False
        compiler = Path(find_c_compiler()).resolve()
        recorded = previous['build']['compiler']
        if str(compiler) != recorded['path'] or digest(compiler) != recorded['sha256']:
            return False
        root = Path(previous['bundle'])
        raw = (root / 'manifest.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != previous['manifest_sha256']:
            return False
        files = json.loads(raw)['files']
        return all(not (root / name).is_symlink() and digest(root / name) == expected
                   for name, expected in files.items())
    except (OSError, KeyError, ValueError, TypeError):
        return False


def approval_text(value):
    """Concise approval with an exact identity and a full local evidence path."""
    return (
        'Authorize a temporary privileged Thermal Assist helper for internal data drives?\n'
        f"Commit {value['commit']}\nExecution source SHA-256 {value['source']['digest']}\n"
        f"Prepared manifest SHA-256 {value['manifest_sha256']}\n"
        f"Qualified {value['build']['fio_version']}; native guard and bootstrap verified.\n"
        'Approve only if you trust this source and its tools. Approval applies to these exact bytes in this LVS session.\n'
        f"Full compiler, tool and file evidence: {value['bundle']}"
    )


def approval_identity(value):
    """Bind reuse to the exact root bootstrap and manifest bytes."""
    return value['stager_sha256'], value['manifest_sha256']


def start(value):
    """Only after foreground exact-source approval and existing sudo validation."""
    command=[tool('sudo'),'-n',tool('python3'),'-I','-B','-c',ROOT_STAGER,value['bundle'],value['manifest_sha256'],str(os.getuid())]
    result=subprocess.run(command,check=False,capture_output=True,text=True,timeout=90)
    if result.returncode:raise OSError('Temporary runtime bootstrap refused: '+result.stderr[-1800:])
    return json.loads(result.stdout)


def systemctl(*args,check=True):
    result=subprocess.run([tool('systemctl'),*args],env=ENV,capture_output=True,text=True,timeout=30)
    if check and result.returncode:raise ValueError('systemd operation failed: '+result.stderr[-1000:])
    return result.stdout.strip()


def identity(root,manifest):
    """Reserve a dynamic UID with a process-free active transient identity unit.

    It is released only after confirmed root-service quiescence and recovery.
    Neither /etc/passwd nor /etc/group is modified. System access is forbidden.
    """
    from .lvs_storage_thermal_system import owned_path
    unit=manifest['identity_unit'];name=unit.removesuffix('.service')
    if not re.fullmatch('lvs-ta-[a-f0-9]{16}',name):raise ValueError('invalid identity unit')
    try:pwd.getpwnam(name)
    except KeyError:pass
    else:raise ValueError('dynamic name already allocated')
    out=root/'identity.json'
    program='import os,json;print(json.dumps([os.getuid(),os.getgid()]))'
    subprocess.run([tool('systemd-run'),'--quiet','--unit='+unit,'--property=Type=oneshot','--property=RemainAfterExit=yes',
        '--property=DynamicUser=yes','--property=User='+name,'--property=UMask=0077','--property=StandardOutput=file:'+str(out),
        tool('python3'),'-I','-B','-c',program],check=True,capture_output=True,env=ENV,timeout=30)
    end=time.monotonic()+15
    while systemctl('show',unit,'--property=SubState','--value')!='exited':
        if time.monotonic()>=end:raise ValueError('dynamic identity not established')
        time.sleep(.1)
    owned_path(out);uid,gid=json.loads(out.read_text())
    if any(type(x)is not int or not 61184<=x<=65519 for x in (uid,gid))or uid==manifest['uid']:
        raise ValueError('invalid dynamic identity allocation')
    if any(p.pw_uid==uid and p.pw_name!=name for p in pwd.getpwall()):raise ValueError('dynamic UID collides with static account')
    return uid,gid


def verify_identity(manifest):
    unit=manifest['identity_unit'];name=unit.removesuffix('.service')
    if (systemctl('show',unit,'--property=ActiveState','--value')!='active' or
        systemctl('show',unit,'--property=DynamicUser','--value')!='yes' or
        systemctl('show',unit,'--property=User','--value')!=name):raise ValueError('dynamic identity reservation lost')
    account=pwd.getpwnam(name)
    if (account.pw_uid,account.pw_gid)!=(manifest['worker_uid'],manifest['worker_gid']):raise ValueError('dynamic identity changed')


@contextmanager
def canonical_gate():
    """Maintenance inspection under the existing anchor; never create/clear it."""
    import fcntl
    from .lvs_storage_thermal_runtime import STATE
    from .lvs_storage_thermal_recovery import anchor_path,read_state,HEADER
    from .lvs_storage_thermal_system import owned_path
    marker=STATE/'storage_thermal_recovery_required.json';anchor=anchor_path(marker);fd=None
    try:
        if anchor.exists()or anchor.is_symlink():
            owned_path(anchor);fd=os.open(anchor,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            actual=os.fstat(fd);named=anchor.lstat()
            if actual.st_nlink!=1 or (actual.st_dev,actual.st_ino)!=(named.st_dev,named.st_ino)or os.pread(fd,len(HEADER)+1,0)!=HEADER:raise ValueError('Canonical anchor identity invalid')
            owned_path(marker)
            if read_state(marker)['state']!='CLEAN':raise ValueError('Unresolved canonical ARMED obligation')
        elif marker.exists()or marker.is_symlink():raise ValueError('Orphan canonical journal')
        yield
    finally:
        if fd is not None:os.close(fd)


def bootstrap(root,approved):
    """Entry from ROOT_STAGER only, using a fully protected approved snapshot."""
    from .lvs_storage_thermal_system import owned_path
    from .lvs_source_provenance import _source_snapshot
    from .lvs_storage_thermal_recovery import blocker
    import fcntl
    root=owned_path(Path(root),directory=True);m=json.loads((root/'manifest.json').read_text())
    if digest(root/'manifest.json')!=approved or _source_snapshot(root/'runtime')[0]!=m['source']:raise ValueError('source approval differs')
    p=json.loads((root/'preparation.json').read_text())
    if p.get('source')!=m['source']or p.get('fio_sha256')!=m['files']['runtime/build/fio']or (m.get('backend')or{}).get('fio_version')!='fio-3.42':raise ValueError('approved build/tool version evidence mismatch')
    for name in ('storage_thermal_guard.c','storage_thermal_launch.c','storage_thermal_confidential.c'):
        if (p.get('native_sources')or{}).get(name)!=m['files']['runtime/native/'+name]:raise ValueError('native build/source provenance mismatch')
    if pwd.getpwuid(m['uid']).pw_gid!=m['gid']:raise ValueError('operator group differs')
    if Path('/proc/1/comm').read_text().strip()!='systemd':raise ValueError('native systemd required')
    if not Path('/sys/fs/cgroup/cgroup.controllers').is_file():raise ValueError('On-demand cleanup qualification requires unified cgroup v2')
    if os.readlink('/proc/self/ns/mnt')!=os.readlink('/proc/1/ns/mnt'):raise ValueError('native mount namespace required')
    for p in root.rglob('*'):
        if p.is_dir():p.chmod(0o755)
    # Same global order as legacy retirement/installer: install -> startup ->
    # canonical anchor. Never let a migration race the ownership conflict check.
    from .lvs_storage_thermal_runtime import STATE
    if not STATE.exists():owned_path(STATE.parent,directory=True);STATE.mkdir(mode=0o755);STATE.chmod(0o755)
    owned_path(STATE,directory=True)
    install=os.open(STATE/'install.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
    lock=None
    try:
        owned_path(STATE/'install.lock');fcntl.flock(install,fcntl.LOCK_EX|fcntl.LOCK_NB)
        lock=os.open(BASE/'startup.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
        owned_path(BASE/'startup.lock');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        uid=m['uid'];old=f'lvs-thermal-{uid}.service'
        # Existing installed or transient deployments are never stopped/overwritten.
        from .lvs_storage_thermal_runtime import endpoint,STATE,SOCKET_ROOT
        record=STATE/f'installation-{uid}.json'
        if record.exists()or record.is_symlink():
            from .lvs_storage_thermal_migration import retired_record
            retired_record(uid)  # incomplete, unknown and legacy active records block
        if endpoint(uid).exists()or systemctl('is-active',old,check=False)=='active' or systemctl('is-active',f'lvs-thermal-demand-{uid}.service',check=False)not in ('inactive','failed','unknown',''):
            raise ValueError('Existing installed/runtime ownership conflicts; migration requires separate review')
        for p in (STATE,):
            if not p.exists():owned_path(p.parent,directory=True);p.mkdir(mode=0o755);p.chmod(0o755)
            owned_path(p,directory=True)
        if not SOCKET_ROOT.exists():
            SOCKET_ROOT.mkdir(mode=0o755);SOCKET_ROOT.chmod(0o755)
        owned_path(SOCKET_ROOT,directory=True)
        if SOCKET_ROOT.stat().st_mode&0o555!=0o555:raise ValueError('Runtime directory is not traversable; existing permissions are not repaired automatically')
        if blocker(STATE/'storage_thermal_recovery_required.json'):raise ValueError('Canonical recovery blocks startup')
        gate=canonical_gate();gate.__enter__()
        try:
            return _launch(root,m)
        finally:gate.__exit__(None,None,None)
    finally:
        if lock is not None:os.close(lock)
        os.close(install)


def _launch(root,m):
    """Caller holds startup serialization and canonical maintenance authority."""
    uid=m['uid']
    m.update(runtime_mode=MODE,identity_unit='lvs-ta-'+uuid4().hex[:16]+'.service',unit='lvs-thermal-demand-'+str(uid)+'.service')
    worker_uid,worker_gid=identity(root,m);m.update(worker_uid=worker_uid,worker_gid=worker_gid)
    m['files']['identity.json']=digest(root/'identity.json')
    (root/'runtime/build/fio').chmod(0o711)
    (root/'runtime/build/storage_thermal_guard').chmod(0o755)
    (root/'runtime/build/storage_thermal_confidential.so').chmod(0o755)
    (root/'manifest.json').write_text(json.dumps(m));(root/'manifest.json').chmod(0o644)
    hashes=dict(m['files'],**{'manifest.json':digest(root/'manifest.json')})
    (root/'SHA256SUMS').write_text(''.join(h+'  '+n+'\n'for n,h in sorted(hashes.items())))
    from .lvs_storage_thermal_backend import capability
    proof=capability(str(root/'runtime/build/fio'),str(root/'runtime/build/storage_thermal_guard'),uid=worker_uid,gid=worker_gid)
    if proof.get('status')!='available'or (proof.get('postexec_confidentiality')or{}).get('status')!='verified':raise ValueError('Temporary worker protection not verified')
    verify_identity(m)
    # Manifest authority reflects the actual dynamic worker, never its creator.
    m['backend']=proof;(root/'manifest.json').write_text(json.dumps(m))
    hashes['manifest.json']=digest(root/'manifest.json');(root/'SHA256SUMS').write_text(''.join(h+'  '+n+'\n'for n,h in sorted(hashes.items())))
    cleanup=tool('python3')+' -I -B '+str(root/'launch.py')+' --cleanup-transient'
    subprocess.run([tool('systemd-run'),'--quiet','--collect','--unit='+m['unit'],'--property=Type=exec','--property=KillMode=control-group',
        '--property=TimeoutStopSec=20','--property=UMask=0077','--property=Requires='+m['identity_unit'],'--property=BindsTo='+m['identity_unit'],'--property=After='+m['identity_unit'],
        '--property=ExecStopPost='+cleanup,tool('python3'),'-I','-B',str(root/'launch.py'),'--serve-integrated'],check=True,capture_output=True,env=ENV,timeout=30)
    return dict(status='STARTED',root=str(root),source=m['source'],unit=m['unit'],worker_uid=worker_uid,worker_gid=worker_gid)

class Hold:
    """Liveness only. Closing it never supplies cleanup or journal authority."""
    def __init__(self):
        from .lvs_storage_thermal_runtime import connect,send,receive
        self.connection=connect(15)
        try:
            self.connection.sendall(b'J');send(self.connection,dict(operation='hold'))
            value=receive(self.connection)
            if value.get('error') or not value.get('generation'):raise OSError('Temporary runtime hold refused')
        except BaseException:self.close();raise
    def close(self):
        if self.connection is not None:self.connection.close();self.connection=None


def start_and_hold(approved):
    from .lvs_storage_thermal_runtime import rpc
    start(approved)
    end=time.monotonic()+20
    while True:
        try:
            health=rpc('health')
            if health.get('source')!=approved['source'] or health.get('runtime_mode')!=MODE:raise ValueError('Temporary runtime source/mode mismatch')
            return Hold()
        except OSError:
            if time.monotonic()>=end:raise
            time.sleep(.1)


def cleanup(root,manifest):
    """Called by transient ExecStopPost; uncertainty retains runtime and UID lease."""
    from .lvs_storage_thermal_system import owned_path
    from .lvs_storage_thermal_recovery import blocker
    from .lvs_storage_thermal_runtime import STATE
    import shutil,errno
    root=owned_path(Path(root),directory=True)
    if root.parent!=BASE or manifest.get('runtime_mode')!=MODE:raise ValueError('not a temporary runtime')
    with canonical_gate():
        return _cleanup_quiescent(root,manifest)


def _cleanup_quiescent(root,manifest):
    import shutil,errno
    group=systemctl('show',manifest['unit'],'--property=ControlGroup','--value')
    if not group.startswith('/')or '..'in Path(group).parts:raise ValueError('unknown service group')
    procs={int(x)for x in (Path('/sys/fs/cgroup')/group.lstrip('/')/'cgroup.procs').read_text().split()}
    if procs-{os.getpid()}:raise ValueError('owned service processes remain; retain temporary runtime')
    from .lvs_storage_thermal_runtime import endpoint
    target=endpoint(manifest['uid'])
    if target.exists():
        before=target.lstat()
        if not stat.S_ISSOCK(before.st_mode)or before.st_uid!=0:raise ValueError('Untrusted stale endpoint')
        probe=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);probe.settimeout(1)
        try:
            try:probe.connect(str(target))
            except OSError as exc:
                if exc.errno!=errno.ECONNREFUSED:raise
            else:raise ValueError('Live endpoint cannot be cleaned')
        finally:probe.close()
        after=target.lstat()
        if (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino):raise ValueError('Endpoint changed')
        target.unlink()
    # After= orders identity stop after this unit's stop. Waiting here would
    # deadlock ExecStopPost against its own ordering dependency.
    systemctl('--no-block','stop',manifest['identity_unit'])
    shutil.rmtree(root)
