"""Administrator-approved transactional installation. Standard library only.

Bootstrap this exact reviewed file into a root-owned libexec directory and verify
its independently approved digest BEFORE invoking it as root. Never sudo a
repository script. No downloads, builds, workloads, device opens or recovery reset.
"""
from __future__ import annotations
import argparse
import base64
import contextlib
import fcntl
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import shlex
import socket
import errno
import stat
import sys
import subprocess
import tempfile
import time
from uuid import uuid4

BASE=Path('/opt/lvs-thermal')
STATE=Path('/var/lib/lvs-thermal')
UNITS=Path('/etc/systemd/system')
ENV=dict(PATH='/usr/bin:/bin',HOME='/root',LC_ALL='C',PYTHONDONTWRITEBYTECODE='1')
HEADER=b'LVS storage recovery scope v1\n'


def require(ok,reason):
    if not ok:raise ValueError(reason)


def digest(data):return hashlib.sha256(data).hexdigest()


def trusted(path,directory=False):
    path=Path(path);require(path.is_absolute(),'absolute trusted path required')
    for p in (path,*path.parents):
        s=p.lstat();require(s.st_uid==0 and not s.st_mode&0o022,'unsafe ownership/ancestor: '+str(p))
        require(stat.S_ISDIR(s.st_mode)if p!=path or directory else stat.S_ISREG(s.st_mode),'unsafe type: '+str(p))
    return path


def canonical_directory(path,allow_missing=False):
    """Resolve fixed OS directory aliases only through root-controlled entries.

    Execution files still use strict link-free trusted(). This does not accept
    arbitrary prefixes or trust a symlink merely because its endpoint is safe.
    """
    path=Path(path);require(path.is_absolute(),'absolute directory required')
    pending=list(path.parts[1:]);current=Path('/');links=0
    trusted(current,directory=True)
    while pending:
        part=pending.pop(0)
        if part in ('','.'):continue
        if part=='..':current=current.parent;continue
        candidate=current/part
        try:s=os.lstat(candidate)
        except FileNotFoundError:
            require(allow_missing and not pending,'unresolved installation ancestor')
            return candidate
        if stat.S_ISLNK(s.st_mode):
            require(s.st_uid==0,'untrusted OS alias');links+=1;require(links<=40,'OS alias loop')
            target=Path(os.readlink(candidate))
            if target.is_absolute():current=Path('/');pending=list(target.parts[1:])+pending
            else:pending=list(target.parts)+pending
        else:
            require(stat.S_ISDIR(s.st_mode)and s.st_uid==0 and not s.st_mode&0o022,'unsafe canonical installation directory')
            current=candidate
    return current


def sync(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def atomic(path,data):
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.install-')
    try:
        with os.fdopen(fd,'wb')as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.chmod(name,0o644);os.replace(name,path);sync(path.parent)
    finally:
        if os.path.exists(name):os.unlink(name)


def regular_at(name,limit,directory=None):
    # Inspect a pinned O_PATH inode BEFORE opening it for I/O. A substituted
    # FIFO/device cannot block validation or invoke a block-device open method.
    pin=os.open(name,os.O_PATH|os.O_CLOEXEC|os.O_NOFOLLOW,dir_fd=directory)
    try:
        s=os.fstat(pin);require(stat.S_ISREG(s.st_mode)and s.st_nlink==1 and s.st_size<=limit,'invalid input file')
        fd=os.open('/proc/self/fd/'+str(pin),os.O_RDONLY|os.O_CLOEXEC|os.O_NONBLOCK)
        try:
            data=os.read(fd,s.st_size+1);after=os.fstat(fd)
            require((s.st_dev,s.st_ino)==(after.st_dev,after.st_ino)and after.st_nlink==1 and len(data)==s.st_size and len(data)<=limit,'input changed/oversized');return data
        finally:os.close(fd)
    finally:os.close(pin)


def read_regular(path,limit):return regular_at(path,limit)


def relative(name):
    require(type(name)is str and len(name)<=512 and not any(ord(c)<32 or ord(c)==127 or c=='\\'for c in name)and not name.startswith('/')and all(p not in ('','..','.')for p in name.split('/')),'unsafe manifest pathname')
    return name


def source_file(root,name,limit):
    """Pin every directory component; an untrusted source cannot redirect copy."""
    parts=relative(name).split('/');fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=nxt
        return regular_at(parts[-1],limit,fd)
    finally:os.close(fd)


def clean_journal(marker):
    trusted(marker);v=json.loads(read_regular(marker,65536));lease=v.get('lease_identity')
    require(v.get('contract_id')=='lvs.storage_thermal.execution_intent'and type(v.get('version'))is int and v['version']==1 and v.get('state')=='CLEAN'and v.get('cleanup_confirmed')is True and type(v.get('token'))is str and bool(v['token'])and type(v.get('owner_pid'))is int,'unresolved/corrupt canonical recovery; installation cannot clear it')
    require(lease is None or type(lease)is list and len(lease)==2 and all(type(x)is int and 0<=x<2**64 for x in lease),'invalid canonical lease identity')
    return v


@contextlib.contextmanager
def recovery_gate(state):
    """Lock the existing never-unlinked anchor without creating/rewriting it."""
    marker=state/'storage_thermal_recovery_required.json';anchor=Path(str(marker)+'.scope');fd=None
    try:
        if anchor.exists()or anchor.is_symlink():
            trusted(anchor);fd=os.open(anchor,os.O_RDONLY|os.O_NOFOLLOW);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            actual=os.fstat(fd);named=anchor.lstat()
            require(actual.st_nlink==1 and (actual.st_dev,actual.st_ino)==(named.st_dev,named.st_ino)and os.pread(fd,len(HEADER)+1,0)==HEADER,'invalid canonical anchor')
            require(marker.exists(),'canonical journal missing beside anchor')
        if marker.exists()or marker.is_symlink():
            require(fd is not None,'canonical journal lacks its anchor');clean_journal(marker)
        yield fd
    finally:
        if fd is not None:os.close(fd)


def worker_account():
    try:account=pwd.getpwnam('lvs-thermal-worker')
    except KeyError:
        tool=trusted(Path('/usr/sbin/useradd').resolve())
        shell=next((p for p in (Path('/usr/sbin/nologin'),Path('/sbin/nologin'))if p.exists()),None)
        require(shell is not None,'install the distro non-login shell first');trusted(shell.resolve())
        subprocess.run([str(tool),'--system','--user-group','--no-create-home','--home-dir','/nonexistent','--shell',str(shell),'lvs-thermal-worker'],check=True,env=ENV,timeout=30)
        account=pwd.getpwnam('lvs-thermal-worker')
    require(account.pw_uid>0 and account.pw_gid>0 and account.pw_dir=='/nonexistent'and account.pw_shell in ('/sbin/nologin','/usr/sbin/nologin','/bin/false'),'unsafe existing worker account')
    require(not any(p.pw_name!=account.pw_name and(p.pw_uid==account.pw_uid or p.pw_gid==account.pw_gid)for p in pwd.getpwall()),'worker UID/group must not be shared with another account')
    groups=grp.getgrall();require(not any(account.pw_name in g.gr_mem for g in groups),'worker supplementary membership is forbidden')
    group=grp.getgrgid(account.pw_gid);require(group.gr_name==account.pw_name and not group.gr_mem,'worker group is not private')
    locked=False
    with Path('/etc/shadow').open()as shadow:
        for entry in shadow:
            if entry.split(':',1)[0]==account.pw_name:
                locked=entry.split(':')[1].startswith(('!','*'));break
    require(locked,'worker account must be password locked')
    return account.pw_uid,account.pw_gid


class Systemd:
    def __init__(self,base=BASE):self.base=Path(base)
    def preflight(self):
        version=self.run('--version').stdout.splitlines()[0]
        match=re.match(r'systemd (\d+)',version)
        require(match is not None and int(match[1])>=235,'routine installation needs systemd 235+; retain the reviewed manual session workflow on unqualified managers')
        require(Path('/proc/1/comm').read_text().strip()=='systemd','native systemd PID1 required')
        require(os.readlink('/proc/self/ns/mnt')==os.readlink('/proc/1/ns/mnt'),'installer namespace differs from native PID1')
    def run(self,*args,check=True):
        tool=trusted(Path('/usr/bin/systemctl').resolve())
        result=subprocess.run([str(tool),*args],capture_output=True,text=True,check=False,timeout=60,env=ENV)
        if check and result.returncode:raise RuntimeError('systemctl '+str(args)+': '+result.stderr[:1500])
        return result
    def verify_dropins(self,unit):
        value=self.run('show',unit,'--property=DropInPaths','--value',check=False)
        require(value.returncode==0 or not value.stdout.strip(),'cannot inspect service overrides')
        unsafe={'Environment','EnvironmentFile','PassEnvironment','User','Group','SupplementaryGroups','DynamicUser','RootDirectory','RootImage','BindPaths','BindReadOnlyPaths','TemporaryFileSystem','MountImages','ExtensionImages','WorkingDirectory','PAMName','StandardInput','StandardOutput','StandardError','RuntimeDirectory','StateDirectory','CacheDirectory','LogsDirectory','ConfigurationDirectory','OnFailure','OnSuccess','SuccessAction','FailureAction','StartLimitAction','JobTimeoutAction'}
        for name in shlex.split(value.stdout):
            p=trusted(Path(name));text=read_regular(p,65536).decode()
            for line in text.splitlines():
                key=line.partition('=')[0].strip()
                require(not(key.startswith('Exec')or 'Credential'in key or key in unsafe),'unsupported execution/identity override: '+str(p)+': '+key)

    def verify_unit(self,unit):
        fragment=self.run('show',unit,'--property=FragmentPath','--value').stdout.strip()
        require(fragment==str(UNITS/unit),'unexpected service fragment')
        path=trusted(Path(fragment));text=read_regular(path,65536).decode()
        commands=[l for l in text.splitlines()if l.startswith('ExecStart=')]
        require(len(commands)==1 and re.fullmatch(r'ExecStart=/usr/bin/python3 -I -B '+re.escape(str(self.base))+r'/[A-Za-z0-9_.-]+/launch\.py --serve-integrated',commands[0]),'unexpected service executable')
        self.verify_dropins(unit)

    def enabled(self,unit):return self.run('is-enabled','--quiet',unit,check=False).returncode==0
    def enable(self,unit,value):self.run('enable'if value else'disable',unit)
    def quiescent(self,unit):
        result=self.run('show',unit,'--property=ControlGroup','--value',check=False)
        if result.returncode:
            state=self.run('show',unit,'--property=LoadState','--value',check=False).stdout.strip()
            require(state=='not-found','unable to prove service cgroup state')
            return not self.active(unit)
        group=result.stdout.strip()
        if not group:return not self.active(unit)
        require(group.startswith('/')and '..'not in Path(group).parts,'invalid service cgroup')
        # A nonempty manager group needs independently readable membership.
        # Never mistake an unknown/v1 mount layout for a deleted v2 cgroup.
        if not Path('/sys/fs/cgroup/cgroup.controllers').is_file():return False
        path=Path('/sys/fs/cgroup')/group.lstrip('/')
        if not path.exists():return not self.active(unit)
        return not self.active(unit)and all(not p.read_text().strip()for p in path.rglob('cgroup.procs'))and not(path/'cgroup.procs').read_text().strip()
    def active(self,unit):return self.run('is-active','--quiet',unit,check=False).returncode==0
    def old_unit(self,unit,path):
        fragment=self.run('show',unit,'--property=FragmentPath','--value',check=False).stdout.strip()
        p=Path(fragment)if fragment else path
        if not p.exists():return None
        trusted(p);return read_regular(p,65536)
    def stop(self,unit):
        self.run('stop',unit,check=False);require(not self.active(unit),'service failed to stop')
        require(self.quiescent(unit),'service cgroup still owns processes; preserve recovery and inspect it')
    def start(self,unit):self.run('daemon-reload');self.verify_unit(unit);self.run('start',unit);require(self.active(unit),'service not active')


class Installer:
    def __init__(self,base=BASE,state=STATE,units=UNITS,service=None,socket_root=Path('/run/lvs-thermal')):
        self.base,self.state,self.units=map(Path,(base,state,units));self.service=service or Systemd(self.base);self.socket_root=Path(socket_root)

    def check(self,path):
        trusted(path,directory=True)
        data=subprocess.check_output(['/usr/bin/python3','-I','-B',str(path/'launch.py'),'--verify-installation'],env=ENV,timeout=45)
        value=json.loads(data);require(value.get('status')=='VERIFIED','installed component self-test failed');return value

    def health(self,path,manifest):
        # Execute only verified root-owned code, as the authorized normal user.
        code="import sys,json;sys.path.insert(0,sys.argv[1]);from Modules.lvs_storage_thermal_runtime import rpc;print(json.dumps(rpc('health')))"
        deadline=time.monotonic()+30;last='service socket not ready'
        while time.monotonic()<deadline:
            try:
                raw=subprocess.check_output(['/usr/bin/python3','-I','-B','-c',code,str(path/'runtime')],user=manifest['uid'],group=manifest['gid'],extra_groups=[],env=ENV,timeout=min(10,max(.1,deadline-time.monotonic())),stderr=subprocess.PIPE)
                value=json.loads(raw)
            except (subprocess.SubprocessError,ValueError)as exc:
                detail=getattr(exc,'stderr',None)
                last=(detail.decode(errors='replace')if isinstance(detail,bytes)else str(detail or type(exc).__name__))[-1200:]
                time.sleep(.2);continue
            require(value.get('source')==manifest['source']and value.get('status')=='AVAILABLE'and value.get('root')==str(path)and value.get('worker_uid')==manifest['worker_uid']and value.get('worker_gid')==manifest['worker_gid']and value.get('bootstrap_sha256')==manifest['files']['runtime/build/storage_thermal_launch.so']and value.get('guard_sha256')==manifest['files']['runtime/build/storage_thermal_guard']and value.get('fio_sha256')==manifest['files']['runtime/build/fio']and value.get('postexec_sha256')==manifest['files']['runtime/build/storage_thermal_confidential.so'],'service source/tool/identity mismatch');return value
        raise ValueError('Service metadata health deadline: '+last)

    def unit(self,path):
        return ('[Unit]\nDescription=LVS trusted Thermal Assist\n[Service]\nType=exec\nUMask=0077\nKillMode=mixed\nTimeoutStopSec=45\nLimitCORE=0\nRuntimeDirectory=lvs-thermal\nRuntimeDirectoryMode=0755\nRuntimeDirectoryPreserve=yes\nExecStart=/usr/bin/python3 -I -B '+str(path/'launch.py')+' --serve-integrated\n[Install]\nWantedBy=multi-user.target\n').encode()

    def reconcile_endpoint(self,unit,uid,gid):
        path=self.socket_root/(str(uid)+'.sock')
        if not(path.exists()or path.is_symlink()):return
        require(self.service.quiescent(unit),'service cgroup still owns processes; endpoint cannot be reconciled')
        trusted(path.parent,directory=True);before=path.lstat()
        require(stat.S_ISSOCK(before.st_mode)and before.st_uid==0 and before.st_gid==gid,'untrusted stale endpoint')
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)as probe:
            probe.settimeout(.3)
            try:probe.connect(str(path))
            except OSError as exc:require(exc.errno==errno.ECONNREFUSED,'endpoint state not proven stale')
            else:raise ValueError('another runtime is listening; never replace its endpoint')
        after=path.lstat();require((before.st_dev,before.st_ino)==(after.st_dev,after.st_ino),'endpoint identity changed')
        path.unlink();sync(path.parent)

    def previous(self,data,uid):
        if data is None:return None
        names={name for base in {BASE,self.base}for name in re.findall(r'(?<![A-Za-z0-9_/.-])'+re.escape(str(base))+r'/[A-Za-z0-9_.-]+/launch\.py(?![A-Za-z0-9_/.-])',data.decode())}
        require(len(names)==1,'previous unit is not a supported trusted LVS deployment')
        path=canonical_directory(Path(names.pop()).parent);trusted(path,directory=True)
        manifest=path/'manifest.json';trusted(manifest);m=json.loads(read_regular(manifest,262144))
        require(m.get('contract')=='lvs.storage_thermal.offline_bundle.v1'and m.get('uid')==uid and m.get('gid')==pwd.getpwuid(uid).pw_gid and type(m.get('files'))is dict and 0<len(m['files'])<=1024 and {'launch.py','runtime/build/fio','runtime/build/storage_thermal_guard','runtime/build/storage_thermal_launch.so'}<=set(m['files'])and(m.get('source')or{}).get('status')=='complete','previous installation identity invalid')
        for name,h in m['files'].items():
            p=path/relative(name);trusted(p);require(digest(read_regular(p,32*1024**2))==h,'previous trusted deployment changed')
        # Preserve the approved launcher/identity, never replay arbitrary unit
        # shell commands, environment assignments or user-writable executables.
        return self.unit(path)

    def rollback(self,uid,_locked=False):
        if not _locked:
            if isinstance(self.service,Systemd):self.service.preflight()
            trusted(self.state,directory=True)
            fd=os.open(self.state/'install.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
            try:
                trusted(self.state/'install.lock');fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                return self.rollback(uid,_locked=True)
            finally:os.close(fd)
        record=self.state/f'installation-{uid}.json';trusted(record);r=json.loads(read_regular(record,262144));unit=f'lvs-thermal-{uid}.service';path=self.units/unit
        previous=r['previous_unit'];data=base64.b64decode(previous)if previous is not None else None
        require(data is None or digest(data)==r['previous_unit_sha256'],'rollback unit identity invalid')
        with recovery_gate(self.state):
            self.service.stop(unit)
            # The stored previous unit is root-approved. Canonical CLEAN and
            # quiescent cgroup are required even for stale socket reconciliation.
            group=pwd.getpwuid(uid).pw_gid
            self.reconcile_endpoint(unit,uid,group)
            if data is None:
                self.service.enable(unit,False)
                if path.exists():trusted(path);path.unlink();sync(path.parent)
            else:atomic(path,data)
            self.service.run('daemon-reload')
            if data is not None:self.service.enable(unit,r.get('previous_enabled',False))
            if r['previous_active']:self.service.start(unit)
            r['phase']='rolled_back';atomic(record,json.dumps(r).encode())
        return dict(status='ROLLED_BACK',previous_installation_preserved=True,recovery='unchanged')

    def install(self,bundle,approved_manifest):
        if isinstance(self.service,Systemd):self.service.preflight()
        require(re.fullmatch('[a-f0-9]{64}',approved_manifest)is not None,'explicit approved manifest SHA-256 required')
        bundle=Path(bundle);raw=source_file(bundle,'manifest.json',262144);require(digest(raw)==approved_manifest,'manifest differs from administrator approval');m=json.loads(raw)
        require(m.get('contract')=='lvs.storage_thermal.offline_bundle.v1','unsupported bundle')
        for key in ('uid','gid'):require(type(m.get(key))is int and 0<m[key]<2**32-1,'invalid operator identity')
        require(pwd.getpwuid(m['uid']).pw_gid==m['gid'],'operator identity mismatch')
        require(type(m.get('files'))is dict and 0<len(m['files'])<=1024,'invalid file inventory')
        for name,h in m['files'].items():relative(name);require(type(h)is str and re.fullmatch('[a-f0-9]{64}',h),'invalid file digest')
        actual=set();entries=0
        for directory,dirs,files in os.walk(bundle,followlinks=False):
            entries+=len(dirs)+len(files);require(entries<=2048 and len(Path(directory).relative_to(bundle).parts)<=16,'oversized directory inventory')
            for name in dirs+files:
                p=Path(directory)/name;require(not p.is_symlink(),'source symlink forbidden')
            for name in files:actual.add(str((Path(directory)/name).relative_to(bundle)))
            require(len(actual)<=1026,'oversized source inventory')
        require(actual==set(m['files'])|{'manifest.json','SHA256SUMS'},'unexpected bundle inventory')
        for p in (self.base,self.state,self.units):
            if not p.exists():trusted(p.parent,directory=True);p.mkdir(mode=0o755);sync(p.parent)
            trusted(p,directory=True)
        # Public code traversal and the established IPC-directory correction.
        # Never alter block-device permissions or canonical journal modes.
        self.base.chmod(0o755)
        trusted(self.socket_root.parent,directory=True)
        if not self.socket_root.exists():self.socket_root.mkdir(mode=0o755)
        trusted(self.socket_root,directory=True);self.socket_root.chmod(0o755)
        lock=os.open(self.state/'install.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            trusted(self.state/'install.lock');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with recovery_gate(self.state):pass
            record=self.state/f'installation-{m["uid"]}.json';unit=f'lvs-thermal-{m["uid"]}.service';unitpath=self.units/unit
            if record.exists():
                trusted(record);old=json.loads(read_regular(record,262144))
                require(old['phase']in ('active','rolled_back'),'interrupted installation: use explicit rollback first')
                if old['phase']=='active'and old['input_manifest']==approved_manifest:
                    target=Path(old['deployment']);self.check(target)
                    if unitpath.exists():trusted(unitpath);require(read_regular(unitpath,65536)==self.unit(target),'installed unit changed; review external modifications')
                    if isinstance(self.service,Systemd):self.service.verify_dropins(unit)
                    actual=json.loads(read_regular(target/'manifest.json',262144));require(worker_account()==(actual['worker_uid'],actual['worker_gid']),'worker identity changed')
                    with recovery_gate(self.state):
                        if not self.service.active(unit):
                            self.service.stop(unit);self.reconcile_endpoint(unit,m['uid'],m['gid'])
                            if not unitpath.exists():atomic(unitpath,self.unit(target))
                            self.service.start(unit)
                        self.service.enable(unit,True)
                    actual=json.loads(read_regular(target/'manifest.json',262144));return dict(status='UNCHANGED',deployment=str(target),health=self.health(target,actual))
            stage=self.base/('.stage-'+uuid4().hex);stage.mkdir(mode=0o700);total=0
            # No source entry is executed. Root copies a bounded pinned snapshot.
            for name,h in m['files'].items():
                data=source_file(bundle,name,32*1024**2);total+=len(data);require(total<=256*1024**2,'bundle exceeds size bound');require(digest(data)==h,'approved bytes changed: '+name)
                p=stage/name;p.parent.mkdir(parents=True,exist_ok=True);
                with p.open('wb')as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
                p.chmod(0o755 if name.endswith(('storage_thermal_guard','storage_thermal_confidential.so'))else 0o644)
            checksums=source_file(bundle,'SHA256SUMS',262144).decode();expected=''.join(h+'  '+n+'\n'for n,h in sorted(dict(m['files'],**{'manifest.json':digest(raw)}).items()))
            require(checksums==expected,'checksum list inconsistent')
            provenance=json.loads(read_regular(stage/'preparation.json',262144));require(provenance.get('source')==m['source']and provenance.get('fio_sha256')==m['files']['runtime/build/fio'],'missing approved preparation provenance')
            for name in ('storage_thermal_guard.c','storage_thermal_launch.c','storage_thermal_confidential.c'):
                require(provenance['native_sources'][name]==m['files']['runtime/native/'+name],'native build/source mismatch')
            uid,gid=worker_account();require(uid!=m['uid'],'operator cannot be worker');m.update(worker_uid=uid,worker_gid=gid)
            (stage/'runtime/build/fio').chmod(0o711)
            for p in stage.rglob('*'):
                if p.is_dir():p.chmod(0o755)
            stage.chmod(0o755)
            atomic(stage/'manifest.json',(json.dumps(m,indent=2)+'\n').encode())
            hashes=dict(m['files'],**{'manifest.json':digest((stage/'manifest.json').read_bytes())});atomic(stage/'SHA256SUMS',''.join(h+'  '+n+'\n'for n,h in sorted(hashes.items())).encode())
            self.check(stage)  # only administrator-approved, now root-owned bytes
            target=self.base/f'runtime-{m["uid"]}-{approved_manifest[:24]}'
            for directory in sorted((p for p in stage.rglob('*')if p.is_dir()),key=lambda p:len(p.parts),reverse=True):sync(directory)
            sync(stage)
            if target.exists():
                trusted(target,directory=True);require(read_regular(target/'manifest.json',262144)==(stage/'manifest.json').read_bytes(),'existing version differs');self.check(target);shutil.rmtree(stage)
            else:os.rename(stage,target);sync(self.base)
            oldunit=self.previous(self.service.old_unit(unit,unitpath),m['uid'])
            if isinstance(self.service,Systemd):self.service.verify_dropins(unit)
            active=self.service.active(unit)
            r=dict(version=1,phase='prepared',input_manifest=approved_manifest,deployment=str(target),previous_unit=base64.b64encode(oldunit).decode()if oldunit else None,previous_unit_sha256=digest(oldunit)if oldunit else None,previous_active=active,previous_enabled=self.service.enabled(unit))
            require(active or oldunit is not None or not(self.socket_root/(str(m['uid'])+'.sock')).exists(),'unmanaged/competing runtime endpoint; stop its approved supervisor first')
            began=False
            try:
                with recovery_gate(self.state)as held:
                    atomic(record,json.dumps(r).encode());began=True;self.service.stop(unit);self.reconcile_endpoint(unit,m['uid'],m['gid'])
                    if held is None:
                        with recovery_gate(self.state):pass
                    else:
                        anchor=Path(str(self.state/'storage_thermal_recovery_required.json')+'.scope')
                        require(anchor.stat().st_ino==os.fstat(held).st_ino,'canonical anchor changed')
                        clean_journal(self.state/'storage_thermal_recovery_required.json')
                    r['phase']='promoting';atomic(record,json.dumps(r).encode())
                    data=self.unit(target)
                    atomic(unitpath,data);self.service.start(unit);self.service.enable(unit,True)
                health=self.health(target,m);require(not health.get('recovery_blocker'),'canonical recovery is blocked')
                r['phase']='active';atomic(record,json.dumps(r).encode())
                health=self.health(target,m);require(not health.get('installation_blocker'),'installation activation was not observed')
            except BaseException:
                if began:self.rollback(m['uid'],_locked=True)
                raise
            return dict(status='INSTALLED',deployment=str(target),health=health,recovery='unchanged',worker_uid=uid,worker_gid=gid)
        finally:os.close(lock)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--bundle',type=Path);parser.add_argument('--manifest-sha256');parser.add_argument('--rollback',type=int);parser.add_argument('--approve',action='store_true');args=parser.parse_args()
    require(os.getuid()==0 and args.approve,'explicit administrator invocation and --approve required')
    trusted(Path(__file__).absolute());trusted(Path('/usr/bin/python3').resolve())
    require(Path(sys.executable).resolve()==Path('/usr/bin/python3').resolve()and sys.flags.isolated and sys.dont_write_bytecode,'invoke the trusted system Python with -I -B')
    installer=Installer(base=canonical_directory(BASE,allow_missing=True))
    if args.rollback is not None:require(args.rollback>0 and args.bundle is None,'invalid rollback');result=installer.rollback(args.rollback)
    else:require(args.bundle is not None and args.manifest_sha256 is not None,'bundle and approved manifest required');result=installer.install(args.bundle,args.manifest_sha256)
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError,KeyError)as exc:
        print(json.dumps(dict(status='FAILED',reason=str(exc),action='Previous version material is retained. Inspect installation state; use explicit rollback only when canonical recovery permits it. Never clear ARMED.')));raise SystemExit(1)
