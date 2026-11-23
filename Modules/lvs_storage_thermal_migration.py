"""Explicit administrator-only legacy retirement; standard library bootstrap.

Review and copy this exact file into root-owned libexec before executing with
OS Python -I -B. Never sudo repository code. Inspection performs no mutation,
service control, account provisioning, device access or recovery repair.
"""
from contextlib import contextmanager
from pathlib import Path
import argparse
import base64
import errno
import fcntl
import grp
import hashlib
import json
import mmap
import os
import pwd
import socket
import stat
import subprocess
import sys
import tempfile
import time

STATE=Path('/var/lib/lvs-thermal')
STARTUP=Path('/run/lvs-thermal-on-demand')
UNITS=Path('/etc/systemd/system')
SOCKETS=Path('/run/lvs-thermal')
TRANSIENT_UNITS=Path('/run/systemd/transient')
ENV=dict(PATH='/usr/bin:/bin',HOME='/root',LC_ALL='C',PYTHONDONTWRITEBYTECODE='1')
HEADER=b'LVS storage recovery scope v1\n'
CONTRACT='lvs.thermal.legacy_retirement.v1'
# Exact previously approved workstation build, NOT a generic old-format escape.
EA60='integrated-ea60eaa9'
EA60_SOURCE='1e35d99bf3b6b1789e6b4bc6571f4be4357afc8e7269413657e777b8bee8dc53'
EA60_MANIFEST='dffa0d4cf30e1314a9b0d63eb9d4f071004473bc312290d84061e03d0599e7a9'
EA60_SUMS='c3e04bbb37b373b8a7a7db695f5f0ac911dbf2944e567f66199d31f8fab35d1f'
VENDOR_DROPIN=Path('/usr/lib/systemd/system/service.d/10-timeout-abort.conf')
VENDOR_DROPIN_SHA256='ae6b234f92bc22f1201a7572b59b454c9809f33c80d13f361b9674e1801acc37'
ABSENT_RECORD=b'{"historical_installation_record_absent":true}\n'
UNIT_SCAN_ROOTS=('/etc/systemd/system','/run/systemd/system','/usr/local/lib/systemd/system','/usr/lib/systemd/system','/lib/systemd/system','/run/systemd/transient','/run/systemd/generator.early','/run/systemd/generator','/run/systemd/generator.late','/etc/systemd/system.control','/run/systemd/system.control')



def require(value,reason):
    if not value:raise ValueError(reason)


def sha(data):return hashlib.sha256(data).hexdigest()


def trusted(path,directory=False):
    path=Path(path);require(path.is_absolute(),'absolute protected path required')
    for p in (path,*path.parents):
        s=p.lstat();require(s.st_uid==0 and not s.st_mode&0o022,'untrusted ownership/ancestor: '+str(p))
        require(stat.S_ISDIR(s.st_mode)if p!=path or directory else stat.S_ISREG(s.st_mode),'untrusted file type: '+str(p))
    return path


def canonical(path):
    # Only traverse root-controlled OS aliases (e.g. Bazzite /opt -> /var/opt).
    pending=list(Path(path).parts[1:]);current=Path('/');links=0
    while pending:
        part=pending.pop(0)
        if part in ('','.'):continue
        if part=='..':current=current.parent;continue
        p=current/part;s=p.lstat()
        require(s.st_uid==0,'untrusted OS directory alias')
        if stat.S_ISLNK(s.st_mode):
            links+=1;require(links<=40,'OS directory alias loop');target=Path(os.readlink(p))
            if target.is_absolute():current=Path('/');pending=list(target.parts[1:])+pending
            else:pending=list(target.parts)+pending
        else:trusted(p,directory=True);current=p
    return current


def read(path,limit=262144):
    path=trusted(path);fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
    try:
        s=os.fstat(fd);require(stat.S_ISREG(s.st_mode)and s.st_nlink==1 and s.st_size<=limit,'invalid protected file')
        value=bytearray()
        while len(value)<=limit:
            chunk=os.read(fd,min(65536,limit+1-len(value)))
            if not chunk:break
            value+=chunk
        require(len(value)==s.st_size,'changing/oversized protected file');return bytes(value)
    finally:os.close(fd)


def sync(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:os.fsync(fd)
    finally:os.close(fd)


def atomic(path,data):
    fd,name=tempfile.mkstemp(prefix='.retirement-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb')as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.chmod(name,0o600);os.replace(name,path);sync(path.parent)
    finally:
        if os.path.exists(name):os.unlink(name)


def write_json(path,value):atomic(path,(json.dumps(value,sort_keys=True,indent=2)+'\n').encode())


def tool(name):return str(trusted(Path('/usr/bin/'+name).resolve()))


def ctl(*args):
    p=subprocess.run([tool('systemctl'),*args],env=ENV,capture_output=True,text=True,timeout=30)
    require(p.returncode==0,'systemctl '+str(args)+': '+p.stderr[-1000:]);return p.stdout.strip()


def properties(unit):
    names=('LoadState','ActiveState','SubState','MainPID','ControlGroup','FragmentPath','DropInPaths','UnitFileState','Transient','NeedDaemonReload','Triggers','TriggeredBy')
    data=ctl('show',unit,*('--property='+n for n in names))
    rows=dict(line.split('=',1)for line in data.splitlines()if '='in line)
    require(set(rows)==set(names),'incomplete manager inspection');return rows


def effective_policy(unit):
    names=('Type','KillMode','KillSignal','FinalKillSignal','WatchdogSignal','SendSIGKILL','SendSIGHUP','TimeoutStopUSec','TimeoutAbortUSec','TimeoutStartFailureMode','TimeoutStopFailureMode','Restart','Delegate','User','Group','DynamicUser','UMask','ExecStart','ExecStop','ExecStopPost','ExecReload','RootDirectory','RootImage')
    data=ctl('show','--all',unit,*('--property='+n for n in names))
    rows=dict(line.split('=',1)for line in data.splitlines()if '='in line)
    # systemctl suppresses empty Exec command arrays even with --all (unlike
    # empty scalar strings). Nonempty hooks are printed and rejected below; the
    # exact fragment and qualified drop-in independently forbid such hooks.
    for name in ('ExecStop','ExecStopPost','ExecReload'):rows.setdefault(name,'')
    require(set(rows)==set(names),'incomplete effective historical service policy')
    return rows


def qualified_dropins(value,historical=False):
    if not value:return []
    require(historical and value==str(VENDOR_DROPIN),'unqualified service drop-in path(s)')
    require(sha(read(VENDOR_DROPIN,65536))==VENDOR_DROPIN_SHA256,'Fedora vendor drop-in content changed')
    return [dict(path=str(VENDOR_DROPIN),sha256=VENDOR_DROPIN_SHA256)]


def historical_policy(unit,prop,approved=None,*,pending_own_mask=False):
    dropins=qualified_dropins(prop['DropInPaths'],historical=True)
    require(not prop['Triggers']and not prop['TriggeredBy']and(prop['NeedDaemonReload']=='no'or pending_own_mask and prop['NeedDaemonReload']=='yes'),'unreviewed historical trigger or pending reload')
    # A completed transaction may be masked/collected: the original service
    # policy no longer exists in the manager. Its approved vendor bytes must
    # nevertheless remain protected and unchanged before further admin actions.
    if approved is not None:
        original=approved.get('dropins',[])
        for item in original:
            require(item==dict(path=str(VENDOR_DROPIN),sha256=VENDOR_DROPIN_SHA256)and sha(read(VENDOR_DROPIN,65536))==VENDOR_DROPIN_SHA256,'approved vendor policy changed')
        require(not dropins or dropins==original,'unapproved vendor policy appeared during transaction')
    loaded=prop['Transient']=='yes'and prop['FragmentPath']==str(TRANSIENT_UNITS/unit)
    if not loaded:return approved
    policy=effective_policy(unit)
    expected=dict(Type='exec',KillMode='mixed',KillSignal='15',FinalKillSignal='9',WatchdogSignal='6',SendSIGKILL='yes',SendSIGHUP='no',TimeoutStopUSec='45s',TimeoutAbortUSec='45s',TimeoutStartFailureMode='terminate',TimeoutStopFailureMode='abort'if dropins else'terminate',Restart='no',Delegate='no',User='',Group='',DynamicUser='no',UMask='0077',ExecStop='',ExecStopPost='',ExecReload='',RootDirectory='',RootImage='')
    for name,value in expected.items():require(policy[name]==value,'unqualified effective historical '+name+': '+policy[name])
    command='/usr/bin/env -i PATH=/usr/bin:/bin HOME=/root LC_ALL=C /usr/bin/python3 -I -B /opt/lvs-thermal/'+EA60+'/launch.py --serve-integrated'
    start=policy['ExecStart'];require(start.startswith('{ path=/usr/bin/env ; argv[]='+command+' ; ignore_errors=no ; ')and start.count('{')==1 and start.count('}')==1,'unqualified effective historical ExecStart')
    # Exclude volatile execution timestamps/PIDs from the approval, while binding
    # the exact executable/argv and every relevant stable stop/identity property.
    policy=dict(policy,ExecStart=command)
    value=dict(dropins=dropins,effective=policy)
    if approved is not None:require(value==approved,'historical shutdown policy changed since approval')
    return value


def require_native():
    require(Path('/proc/1/comm').read_text().strip()=='systemd','native systemd PID1 required')
    require(os.readlink('/proc/self/ns/mnt')==os.readlink('/proc/1/ns/mnt'),'native mount namespace required')
    require(Path('/sys/fs/cgroup/cgroup.controllers').is_file(),'unified cgroup v2 required')


def journal():
    marker=STATE/'storage_thermal_recovery_required.json';raw=read(marker,65536);v=json.loads(raw)
    require(v.get('contract_id')=='lvs.storage_thermal.execution_intent'and type(v.get('version'))is int and v['version']==1 and v.get('state')=='CLEAN'and v.get('cleanup_confirmed')is True and type(v.get('owner_pid'))is int and type(v.get('token'))is str and bool(v['token']),'canonical recovery is not verifiably CLEAN')
    lease=v.get('lease_identity');require(lease is None or type(lease)is list and len(lease)==2 and all(type(x)is int and 0<=x<2**64 for x in lease),'invalid canonical lease identity')
    return raw


@contextmanager
def locks(change=False,historical=False):
    """Global order: legacy install -> transient startup -> existing anchor.

    No scope creation, missing recovery acceptance, journal rewrite or repair.
    Inspection opens only existing locks. A missing startup lock is safe while
    install.lock is held: all new startups now take install.lock first.
    """
    fds=[]
    try:
        trusted(STATE,directory=True)
        for p in (STATE/'install.lock',STARTUP/'startup.lock',STATE/'storage_thermal_recovery_required.json.scope'):
            if p==STATE/'install.lock'and not(p.exists()or p.is_symlink())and historical:
                if not change:continue  # old generation never had this lock
                # Explicit administration creates only serialization metadata,
                # never a journal/anchor. Full CLEAN validation still precedes
                # every deployment/unit/socket/record mutation.
                try:
                    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC,0o600);os.fsync(fd);os.close(fd);sync(STATE)
                except FileExistsError:pass
            if p==STARTUP/'startup.lock'and not(p.exists()or p.is_symlink()):
                if STARTUP.exists()or STARTUP.is_symlink():trusted(STARTUP,directory=True)
                # install.lock prevents every cooperating startup from creating
                # this absent lock until inspection/retirement releases it.
                continue
            trusted(p);fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
            fds.append(fd);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            s=os.fstat(fd);n=p.lstat();require(s.st_nlink==1 and(s.st_dev,s.st_ino)==(n.st_dev,n.st_ino),'maintenance lock identity changed')
            if p.name.endswith('.scope'):require(os.pread(fd,len(HEADER)+1,0)==HEADER,'invalid existing recovery anchor')
        def validate():
            for fd in fds:
                actual=os.fstat(fd);require(actual.st_nlink==1,'maintenance anchor unlinked')
                target=Path(os.readlink('/proc/self/fd/'+str(fd)))
                named=target.lstat();require((actual.st_dev,actual.st_ino)==(named.st_dev,named.st_ino),'maintenance authority replaced')
            journal()
        validate();yield
        validate()
    finally:
        for fd in reversed(fds):os.close(fd)


def unit_bytes(path):
    return ('[Unit]\nDescription=LVS trusted Thermal Assist\n[Service]\nType=exec\nUMask=0077\nKillMode=mixed\nTimeoutStopSec=45\nLimitCORE=0\nRuntimeDirectory=lvs-thermal\nRuntimeDirectoryMode=0755\nRuntimeDirectoryPreserve=yes\nExecStart=/usr/bin/python3 -I -B '+str(path/'launch.py')+' --serve-integrated\n[Install]\nWantedBy=multi-user.target\n').encode()


def deployment(path,uid):
    path=trusted(Path(path),directory=True)
    require(path.parent==canonical(Path('/opt/lvs-thermal'))and path.name.startswith('runtime-'+str(uid)+'-'),'unknown deployment location')
    raw=read(path/'manifest.json');m=json.loads(raw)
    require(m.get('contract')=='lvs.storage_thermal.offline_bundle.v1'and m.get('uid')==uid and type(m['uid'])is int and m.get('gid')==pwd.getpwuid(uid).pw_gid and type(m.get('files'))is dict and 1<=len(m['files'])<=1024,'invalid legacy manifest')
    require({'launch.py','preparation.json','runtime/build/fio','runtime/build/storage_thermal_guard','runtime/build/storage_thermal_launch.so','runtime/build/storage_thermal_confidential.so'}<=set(m['files']),'incomplete legacy executable inventory')
    actual=set();entries=0
    for directory,dirs,files in os.walk(path,followlinks=False):
        entries+=len(dirs)+len(files);require(entries<=2048,'oversized deployment')
        for name in dirs:trusted(Path(directory)/name,directory=True)
        for name in files:actual.add(str((Path(directory)/name).relative_to(path)))
    require(actual==set(m['files'])|{'manifest.json','SHA256SUMS'},'unexpected deployed files')
    for name,h in m['files'].items():
        require(type(name)is str and not name.startswith('/')and all(p not in ('','.','..')for p in name.split('/')),'unsafe deployment inventory')
        require(type(h)is str and len(h)==64 and sha(read(path/name,33554432))==h,'altered deployed component: '+name)
    expected=''.join(h+'  '+n+'\n'for n,h in sorted(dict(m['files'],**{'manifest.json':sha(raw)}).items()))
    require(read(path/'SHA256SUMS').decode()==expected,'deployment checksum list changed')
    def scoped(name):
        p=Path(name)
        if any(x.startswith('.')or x=='__pycache__'for x in p.parts):return False
        if len(p.parts)==1:return p.suffix in ('.py','.sh')or(p.name.startswith('requirements')and p.suffix=='.txt')
        return ((p.parts[0]=='Modules'and p.suffix=='.py')or(p.parts[0]=='native'and p.suffix in ('.py','.c','.h','.comp','.glsl'))or(p.parts[0]=='scripts'and p.suffix=='.sh')or(p.parts[0]=='profiles'and len(p.parts)==2 and p.suffix=='.json'))
    records=sorted([[n[8:],h]for n,h in m['files'].items()if n.startswith('runtime/')and scoped(n[8:])])
    source=dict(scope='lvs_execution_source_v1',algorithm='sha256',file_count=len(records),digest=sha(json.dumps(['lvs_execution_source_v1',records],sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()),status='complete',error_count=0)
    require(m.get('source')==source and {'linux_validation_suite.py','Modules/lvs_core.py','native/cpu_stress_helper.c','native/memory_stress_helper.c'}<={n for n,h in records},'legacy source fingerprint mismatch')
    preparation=json.loads(read(path/'preparation.json'))
    require(preparation.get('contract')=='lvs.storage_thermal.preparation.v1'and preparation.get('source')==source and preparation.get('fio_sha256')==m['files']['runtime/build/fio']and preparation.get('fio_version')=='fio-3.42'and (m.get('backend')or{}).get('fio_version')=='fio-3.42','legacy source/tool build evidence inconsistent')
    for name in ('storage_thermal_guard.c','storage_thermal_launch.c','storage_thermal_confidential.c'):
        require(preparation['native_sources'][name]==m['files']['runtime/native/'+name],'legacy native source/build evidence inconsistent')
    account=pwd.getpwnam('lvs-thermal-worker')
    require((account.pw_uid,account.pw_gid)==(m.get('worker_uid'),m.get('worker_gid'))and account.pw_uid>0 and account.pw_uid!=uid and account.pw_dir=='/nonexistent'and account.pw_shell in ('/sbin/nologin','/usr/sbin/nologin','/bin/false'),'unexpected legacy worker identity')
    require(not any(a.pw_name!=account.pw_name and(a.pw_uid==account.pw_uid or a.pw_gid==account.pw_gid)for a in pwd.getpwall()),'shared legacy worker UID/GID')
    g=grp.getgrgid(account.pw_gid);require(g.gr_name==account.pw_name and not g.gr_mem and not any(account.pw_name in g.gr_mem for g in grp.getgrall()),'legacy worker group not private')
    # Do not expose the password field in any report or approval document.
    with trusted(Path('/etc/shadow')).open()as stream:
        locked=any(line.split(':',1)[0]==account.pw_name and line.split(':')[1].startswith(('!','*'))for line in stream)
    require(locked,'legacy worker login state changed')
    return m,sha(raw)


def historical_deployment(path,uid):
    path=trusted(Path(path),directory=True)
    require(path.parent==canonical(Path('/opt/lvs-thermal'))and path.name==EA60,'unrecognized historical deployment')
    raw=read(path/'manifest.json');require(sha(raw)==EA60_MANIFEST,'historical manifest differs from independent approval')
    m=json.loads(raw)
    require(set(m)=={'contract','source','uid','gid','files','backend'}and m['contract']=='lvs.storage_thermal.offline_bundle.v1'and m['uid']==uid and m['gid']==pwd.getpwuid(uid).pw_gid,'historical operator/format mismatch')
    require(m['source']==dict(scope='lvs_execution_source_v1',algorithm='sha256',file_count=392,digest=EA60_SOURCE,status='complete',error_count=0)and len(m['files'])==397,'historical generation mismatch')
    require(sha(read(path/'SHA256SUMS'))==EA60_SUMS,'historical checksum approval mismatch')
    actual=set()
    for directory,dirs,files in os.walk(path,followlinks=False):
        for name in dirs:trusted(Path(directory)/name,directory=True)
        for name in files:actual.add(str((Path(directory)/name).relative_to(path)))
        require(len(actual)<=399,'unexpected historical inventory')
    require(actual==set(m['files'])|{'manifest.json','SHA256SUMS'},'unexpected historical files')
    for name,h in m['files'].items():
        require(not name.startswith('/')and all(p not in ('','.','..')for p in name.split('/'))and sha(read(path/name,33554432))==h,'historical executable/source bytes changed')
    expected=''.join(h+'  '+n+'\n'for n,h in sorted(dict(m['files'],**{'manifest.json':sha(raw)}).items()))
    require(read(path/'SHA256SUMS').decode()==expected,'historical checksum inventory inconsistent')
    return m,sha(raw)


def historical_unit():
    launch='/opt/lvs-thermal/'+EA60+'/launch.py'
    return ('# This is a transient unit file, created programmatically via the systemd API. Do not edit.\n'
        '[Unit]\nDescription=[systemd-run] /usr/bin/env -i PATH=/usr/bin:/bin HOME=/root LC_ALL=C /usr/bin/python3 -I -B '+launch+' --serve-integrated\n'
        'CollectMode=inactive-or-failed\n\n[Service]\nType=exec\nKillMode=mixed\nTimeoutStopSec=45s\nUMask=0077\nExecStart=\n'
        'ExecStart="/usr/bin/env" "-i" "PATH=/usr/bin:/bin" "HOME=/root" "LC_ALL=C" "/usr/bin/python3" "-I" "-B" "'+launch+'" "--serve-integrated"\n').encode()


def mapping_identity(path):
    # stat().st_dev is NOT necessarily /proc/maps' superblock device (Btrfs
    # subvolumes on the workstation demonstrate this). Establish the kernel
    # token from a read-only VMA of this verified descriptor, without executing
    # its code or requiring privileged map_files/debugger access.
    def rows():
        return [line.split(maxsplit=5)for line in Path('/proc/self/maps').read_bytes().splitlines()]
    pin=os.open(path,os.O_PATH|os.O_NOFOLLOW|os.O_CLOEXEC);fd=None
    try:
        s=os.fstat(pin);require(stat.S_ISREG(s.st_mode)and s.st_nlink==1 and 0<s.st_size<=33554432,'invalid mapping proof descriptor')
        fd=os.open('/proc/self/fd/'+str(pin),os.O_RDONLY|os.O_CLOEXEC)
        before={r[0]for r in rows()if len(r)>=5 and int(r[4])}
        with mmap.mmap(fd,0,flags=mmap.MAP_PRIVATE,prot=mmap.PROT_READ):
            added=[r for r in rows()if len(r)>=5 and int(r[4])and r[0]not in before]
            require(len(added)==1,'ambiguous file-mapping capability observation')
            row=added[0];start,end=(int(x,16)for x in row[0].split(b'-'));page=os.sysconf('SC_PAGESIZE')
            require(row[1]==b'r--p'and int(row[2],16)==0 and end-start==((s.st_size+page-1)//page)*page,'unexpected read-only mapping proof')
            major,minor=(int(x,16)for x in row[3].split(b':'));return os.makedev(major,minor),int(row[4])
    finally:
        if fd is not None:os.close(fd)
        os.close(pin)


def historical_processes(path,main):
    # Historical workers ran as the operator UID. That is NOT a dedicated UID;
    # unrelated operator processes are legitimate. Accepted old seccomp/ownership
    # keeps descendants in the root-owned service cgroup. Additionally detect
    # escaped launchers, executable inodes and the pinned bootstrap mapping.
    files=(path/'runtime/build/fio',path/'runtime/build/storage_thermal_guard',path/'runtime/build/storage_thermal_launch.so')
    identities={(p.stat().st_dev,p.stat().st_ino)for p in files}
    mapped_identities={mapping_identity(p)for p in files}
    launches={str(path/'launch.py').encode(),str(Path('/opt/lvs-thermal')/EA60/'launch.py').encode()}
    for row in Path('/proc').iterdir():
        if not row.name.isdigit()or int(row.name)in (os.getpid(),main):continue
        try:
            try:exe=(row/'exe').stat()
            except FileNotFoundError:
                require(not(row/'cmdline').read_bytes(),'unresolved userspace executable');continue
            require((exe.st_dev,exe.st_ino)not in identities,'historical executable remains outside approved main')
            require(not launches.intersection((row/'cmdline').read_bytes().split(b'\0')),'historical launcher remains outside approved main')
            # Stream numeric mapping identity; do not retain paths or impose a
            # total-map-size exclusion on high-resource hosts.
            with (row/'maps').open('rb')as stream:
                for line in stream:
                    fields=line.split(maxsplit=5);require(len(fields)>=5,'incomplete process mapping observation')
                    major,minor=fields[3].split(b':');device=os.makedev(int(major,16),int(minor,16));inode=int(fields[4])
                    require((device,inode)not in mapped_identities,'possible historical bootstrap/executable mapping remains; complete quiescence required')
        except (FileNotFoundError,ProcessLookupError):continue


def scan_stamp(s,full=False):
    value=(s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_rdev)
    return value+(s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns)if full else value


def scan_resolve(path,observations):
    """Observe aliases without trusting their ownership or executing anything.

    Ancestors bind identity, not unrelated directory activity; enumerated
    directories, symlinks and candidate files also bind mutation timestamps.
    """
    def observe(p,s,full=False):
        value=scan_stamp(s,full);previous=observations.get(p)
        require(previous is None or previous[:min(len(previous),len(value))]==value[:min(len(previous),len(value))],'changing unit scan path: '+str(p))
        if previous is None or len(value)>len(previous):observations[p]=value
        require(len(observations)<=262144,'unit scan observation budget exceeded')
    current=Path('/');observe(current,current.lstat());pending=list(Path(path).parts[1:]);links=0
    while pending:
        part=pending.pop(0)
        if part in ('','.'):continue
        if part=='..':current=current.parent;continue
        p=current/part;s=p.lstat();link=stat.S_ISLNK(s.st_mode);observe(p,s,link or not pending)
        if link:
            links+=1;require(links<=40,'unit scan symlink loop: '+str(path));target=Path(os.readlink(p))
            if target.is_absolute():current=Path('/');pending=list(target.parts[1:])+pending
            else:pending=list(target.parts)+pending
        else:
            require(not pending or stat.S_ISDIR(s.st_mode),'non-directory unit scan ancestor: '+str(p));current=p
    s=current.lstat();observe(current,s,True);return current,s


def scan_unit(path,observations):
    """Bounded observation, not executable/source approval. Never open a device.

    O_PATH pins the object before a read-capable descriptor is obtained through
    procfs. Thus a replacement cannot redirect the read-open to a special file.
    """
    resolved,s=scan_resolve(path,observations)
    if resolved==Path('/dev/null')and stat.S_ISCHR(s.st_mode)and s.st_rdev==os.makedev(1,3):return b'',resolved
    require(stat.S_ISREG(s.st_mode),'uninspectable unit candidate: '+str(path))
    pin=os.open(resolved,os.O_PATH|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        require(scan_stamp(os.fstat(pin),True)==scan_stamp(s,True),'unit candidate replaced: '+str(path))
        fd=os.open('/proc/self/fd/'+str(pin),os.O_RDONLY|os.O_NONBLOCK|os.O_CLOEXEC)
        try:
            require(scan_stamp(os.fstat(fd),True)==scan_stamp(s,True)and s.st_size<=65536,'changing/oversized unit candidate: '+str(path))
            data=bytearray()
            while len(data)<=65536:
                chunk=os.read(fd,min(65536,65537-len(data)))
                if not chunk:break
                data+=chunk
            require(len(data)==s.st_size and scan_stamp(os.fstat(fd),True)==scan_stamp(s,True),'changing unit content: '+str(path))
            return bytes(data),resolved
        finally:os.close(fd)
    except OSError as exc:raise ValueError('unreadable unit candidate '+str(path)+': '+str(exc))from exc
    finally:os.close(pin)


def no_alternate_unit(unit,path):
    observations={};roots=set();count=0;total=0
    historical=path.name==EA60
    approved=(TRANSIENT_UNITS if historical else UNITS)/unit
    expected=historical_unit()if historical else unit_bytes(path)
    needles=(str(path).encode(),str(Path('/opt/lvs-thermal')/path.name).encode())
    def walk(base,ancestors):
        nonlocal count,total
        resolved,s=scan_resolve(base,observations);identity=(s.st_dev,s.st_ino)
        require(stat.S_ISDIR(s.st_mode)and identity not in ancestors and len(ancestors)<128,'uninspectable/recursive unit directory: '+str(base))
        # scandir raises on unreadable directories; never silently omit a tree.
        with os.scandir(resolved)as entries:
            for entry in entries:
                count+=1;require(count<=65536,'unit scan entry budget exceeded')
                p=base/entry.name
                if entry.name.endswith(('.service','.conf')):
                    data,target=scan_unit(p,observations);total+=len(data);require(total<=67108864,'unit scan byte budget exceeded')
                    if target.is_relative_to(path)or any(n in data for n in needles):
                        require(p==approved and data==expected,'alternate unit references legacy deployment: '+str(p))
                        # Only the exact approved unit is trusted, never merely
                        # a basename, inode alias or matching text in a vendor file.
                        require(read(p,65536)==data,'approved unit changed during scan')
                else:
                    target,info=scan_resolve(p,observations)
                    if stat.S_ISDIR(info.st_mode):walk(p,ancestors|{identity})
    try:
        for directory in UNIT_SCAN_ROOTS:
            base=Path(directory)
            try:base.lstat()
            except FileNotFoundError:continue
            resolved,s=scan_resolve(base,observations);identity=(s.st_dev,s.st_ino)
            if identity in roots:continue  # e.g. /lib -> /usr/lib
            roots.add(identity);walk(base,set())
        for p,stamp in observations.items():
            require(scan_stamp(p.lstat(),len(stamp)>6)==stamp,'unit scan path changed: '+str(p))
    except OSError as exc:raise ValueError('incomplete systemd unit scan: '+str(exc))from exc


def no_transient():
    rows=ctl('list-units','--all','--plain','--no-legend','lvs-thermal-demand-*.service')
    for line in rows.splitlines():
        fields=line.split();require(len(fields)>=4,'incomplete transient unit inspection')
        require(fields[2]in ('inactive','failed'),'transient service still owns authority')
        value=properties(fields[0]);require(value['MainPID']=='0','transient main process remains')
        group=value['ControlGroup']
        if group:
            require(group.startswith('/')and '..'not in Path(group).parts,'unknown transient cgroup')
            directory=Path('/sys/fs/cgroup')/group.lstrip('/')
            if directory.exists():
                require(all(not p.read_text().strip()for p in (directory/'cgroup.procs',*directory.rglob('*/cgroup.procs'))),'transient descendants remain')


def no_other_legacy(unit):
    for line in ctl('list-units','--all','--plain','--no-legend','lvs-thermal-*.service').splitlines():
        fields=line.split()
        if len(fields)<4:continue
        name=fields[0]
        if name!=unit and name.startswith('lvs-thermal-')and name.removeprefix('lvs-thermal-').removesuffix('.service').isdigit():
            require(fields[2]in ('inactive','failed'),'another legacy service owns the global scope')


def process_identity(pid):
    fields=Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()
    return dict(pid=pid,start_ticks=int(fields[19]))


def quiescent(unit,path,worker_uid,allow_main=False,historical=False):
    p=properties(unit);require(p['ActiveState']in ('active','inactive','failed'),'service transition in progress')
    main=int(p['MainPID']);group=p['ControlGroup'];members=set()
    if group:
        require(group.startswith('/')and '..'not in Path(group).parts,'invalid cgroup path')
        cg=Path('/sys/fs/cgroup')/group.lstrip('/')
        if cg.exists():
            for entry in (cg/'cgroup.procs',*cg.rglob('*/cgroup.procs')):members.update(int(x)for x in entry.read_text().split())
    permitted={main}if allow_main and main>1 else set()
    require(members==permitted and(bool(main)==bool(permitted)),'legacy clients/workers or unresolved cgroup membership remain')
    if main:
        require(Path('/proc',str(main),'exe').resolve()==Path('/usr/bin/python3').resolve(),'unexpected legacy main executable')
        argv=Path('/proc',str(main),'cmdline').read_bytes().split(b'\0')[:-1]
        launch=Path('/opt/lvs-thermal')/EA60/'launch.py'if historical else path/'launch.py'
        require(argv==[b'/usr/bin/python3',b'-I',b'-B',str(launch).encode(),b'--serve-integrated'],'unexpected legacy main command')
    if historical:
        historical_processes(path,main)
        return process_identity(main)if main else None
    # A worker escaped from the group or an independent old launcher is unsafe.
    for row in Path('/proc').iterdir():
        if not row.name.isdigit()or int(row.name)==os.getpid():continue
        try:
            status=(row/'status').read_text();uids=next(x for x in status.splitlines()if x.startswith('Uid:')).split()[1:]
            if worker_uid in map(int,uids):raise ValueError('legacy worker identity still has processes')
            cmd=(row/'cmdline').read_bytes().split(b'\0')
            require(str(path/'launch.py').encode()not in cmd or int(row.name)==main,'unmanaged legacy launcher remains')
        except (FileNotFoundError,ProcessLookupError):continue
    return process_identity(main)if main else None


def endpoint_info(uid,gid,main):
    path=SOCKETS/(str(uid)+'.sock')
    if not(path.exists()or path.is_symlink()):
        require(main is None,'legacy main has no established endpoint');return None
    trusted(path.parent,directory=True);s=path.lstat()
    require(stat.S_ISSOCK(s.st_mode)and s.st_uid==0 and s.st_gid==gid and not s.st_mode&0o007,'untrusted legacy socket')
    # Identify the kernel listener and its owning process without connecting:
    # even a health RPC would fork a handler and disturb quiescence inspection.
    entries=[line.split(maxsplit=7)for line in Path('/proc/net/unix').read_text().splitlines()[1:]]
    rows=[r for r in entries if len(r)==8 and r[7]==str(path)]
    if main is not None:
        require(len(rows)==1 and rows[0][3:6]==['00010000','0001','01'],'legacy listener state unknown')
        require(process_identity(main['pid'])==main,'legacy main changed during socket inspection')
        wanted='socket:['+rows[0][6]+']';found=False
        for fd in Path('/proc',str(main['pid']),'fd').iterdir():
            try:found=found or os.readlink(fd)==wanted
            except FileNotFoundError:continue
        require(found and process_identity(main['pid'])==main,'endpoint is not owned by approved legacy main')
    else:require(not rows,'unknown live socket owner')
    return dict(device=s.st_dev,inode=s.st_ino,gid=s.st_gid,mode=stat.S_IMODE(s.st_mode),main=main)


def masked(unit):
    trusted(UNITS,directory=True)
    p=UNITS/unit
    return p.is_symlink()and os.readlink(p)=='/dev/null'and p.lstat().st_uid==0


def retired_record(uid):
    """Shared startup/service gate. No RPC, root changes or recovery assumption."""
    r=json.loads(read(STATE/f'installation-{uid}.json'))
    require(set(r)=={'phase','contract','transaction','approval'}and r['phase']=='retired'and r['contract']==CONTRACT,'installation is not retired')
    name=r['transaction'];require(type(name)is str and name==str(uid)+'-'+r['approval'][:24]and len(r['approval'])==64,'invalid retirement identity')
    d=trusted(STATE/'retirements'/name,directory=True);t=json.loads(read(d/'state.json'));e=read(d/'approval.json')
    require(t==dict(contract=CONTRACT,phase='RETIRED',approval=r['approval'])and sha(e)==r['approval'],'retirement incomplete/changed')
    v=json.loads(e);require(v['uid']==uid and v['unit']==f'lvs-thermal-{uid}.service'and masked(v['unit']),'legacy service not persistently masked')
    require(sha(read(d/'original-record.json'))==v['record_sha256']and sha(read(d/'original-unit'))==v['unit_sha256'],'retirement audit material changed')
    anchor=trusted(STATE/'storage_thermal_recovery_required.json.scope').stat()
    require([anchor.st_dev,anchor.st_ino]==v['anchor'],'retirement anchor changed')
    return v


class Migration:
    def __init__(self,uid,checkpoint=None,*,historical_ea60=False):
        require(type(uid)is int and 0<uid<2**32-1,'positive operator UID required')
        self.historical_ea60=historical_ea60
        self.uid=uid;self.unit=f'lvs-thermal-{uid}.service';self.record=STATE/f'installation-{uid}.json';self.checkpoint=checkpoint or(lambda _:None)

    def inspect(self):
        require_native()
        with locks(historical=self.historical_ea60):return self._inspect()

    def _inspect(self):
        no_transient();no_other_legacy(self.unit)
        if self.historical_ea60:return self._inspect_historical()
        raw=read(self.record);r=json.loads(raw)
        require(r.get('version')==1 and type(r.get('version'))is int and r.get('phase')=='active','unknown, inactive or interrupted legacy installation')
        path=Path(r['deployment']);m,mh=deployment(path,self.uid)
        require(type(r.get('input_manifest'))is str and len(r['input_manifest'])==64 and all(c in '0123456789abcdef'for c in r['input_manifest']),'missing prior administrator approval')
        require(path.name=='runtime-'+str(self.uid)+'-'+r['input_manifest'][:24],'deployment differs from original installer approval')
        p=properties(self.unit);require(not p['DropInPaths']and not p['Triggers']and not p['TriggeredBy']and p['Transient']=='no'and p['NeedDaemonReload']=='no','legacy unit overrides/triggers or manager state not qualified')
        require(p['FragmentPath']==str(UNITS/self.unit)and p['UnitFileState']in ('enabled','disabled'),'unknown installed unit/enablement')
        unit=read(UNITS/self.unit,65536);require(unit==unit_bytes(path),'legacy unit was altered')
        no_alternate_unit(self.unit,path)
        main=quiescent(self.unit,path,m['worker_uid'],allow_main=True)
        sock=endpoint_info(self.uid,m['gid'],main)
        anchor=(STATE/'storage_thermal_recovery_required.json.scope').stat()
        value=dict(contract=CONTRACT,uid=self.uid,gid=m['gid'],unit=self.unit,deployment=str(path),manifest_sha256=mh,source=m['source'],worker_uid=m['worker_uid'],worker_gid=m['worker_gid'],record_sha256=sha(raw),unit_sha256=sha(unit),enabled=p['UnitFileState'],main=main,socket=sock,anchor=[anchor.st_dev,anchor.st_ino],journal_sha256=sha(journal()))
        evidence=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
        return dict(status='REVIEW_REQUIRED',approval_sha256=sha(evidence),deployment=value)

    def _inspect_historical(self):
        require(not(self.record.exists()or self.record.is_symlink()),'historical generation must have no installation record')
        path=canonical(Path('/opt/lvs-thermal'))/EA60;m,mh=historical_deployment(path,self.uid)
        require(not(UNITS/self.unit).exists()and not(UNITS/self.unit).is_symlink(),'historical permanent unit conflict')
        prop=properties(self.unit);fragment=TRANSIENT_UNITS/self.unit
        require(prop['Transient']=='yes'and prop['FragmentPath']==str(fragment)and prop['UnitFileState']=='transient'and prop['NeedDaemonReload']=='no','unrecognized historical transient unit')
        policy=historical_policy(self.unit,prop)
        raw=read(fragment,65536);require(raw==historical_unit(),'historical unit bytes differ from reviewed command')
        no_alternate_unit(self.unit,path)
        main=quiescent(self.unit,path,None,allow_main=True,historical=True)
        sock=endpoint_info(self.uid,m['gid'],main);anchor=(STATE/'storage_thermal_recovery_required.json.scope').stat()
        value=dict(contract=CONTRACT,uid=self.uid,gid=m['gid'],unit=self.unit,deployment=str(path),manifest_sha256=mh,source=m['source'],worker_uid=None,worker_gid=None,ownership_model='historical-cgroup-and-pinned-inodes',shutdown_policy=policy,historical_ea60=True,record_absent=True,record_sha256=sha(ABSENT_RECORD),unit_sha256=sha(raw),enabled='transient',main=main,socket=sock,anchor=[anchor.st_dev,anchor.st_ino],journal_sha256=sha(journal()))
        evidence=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
        return dict(status='REVIEW_REQUIRED',approval_sha256=sha(evidence),deployment=value)

    def _policy(self,prop,v,*,allow_pending=False):
        if self.historical_ea60:
            approved=v.get('shutdown_policy')
            if approved is None:require(not prop['DropInPaths'],'old approval did not authorize vendor drop-ins')
            pending=allow_pending and prop['NeedDaemonReload']=='yes'and masked(self.unit)and self._unit_ok(v)
            return historical_policy(self.unit,prop,approved,pending_own_mask=pending)
        require(not prop['DropInPaths']and not prop['Triggers']and not prop['TriggeredBy'],'unreviewed service override/trigger')

    def _quiescent(self,v,allow_main=False):
        return quiescent(self.unit,Path(v['deployment']),v['worker_uid'],allow_main=allow_main,historical=bool(v.get('historical_ea60')))

    def _unit_ok(self,v):
        fragment=TRANSIENT_UNITS/self.unit
        if self.historical_ea60 and(fragment.exists()or fragment.is_symlink()):
            require(sha(read(fragment,65536))==v['unit_sha256'],'historical transient fragment changed')
        if masked(self.unit):return True
        if not self.historical_ea60:return sha(read(UNITS/self.unit,65536))==v['unit_sha256']
        require(not(UNITS/self.unit).exists()and not(UNITS/self.unit).is_symlink(),'unknown historical permanent unit')
        prop=properties(self.unit);fragment=TRANSIENT_UNITS/self.unit
        if prop['FragmentPath']==str(fragment):return sha(read(fragment,65536))==v['unit_sha256']
        return prop['LoadState']=='not-found'and prop['MainPID']=='0'

    def _wait_state(self,condition,reason):
        deadline=time.monotonic()+5
        while not condition():
            require(time.monotonic()<deadline,reason);time.sleep(.1)


    def _state(self,d,phase,approval):
        write_json(d/'state.json',dict(contract=CONTRACT,phase=phase,approval=approval));self.checkpoint(phase)

    def _pending(self,approval):
        require(type(approval)is str and len(approval)==64 and all(c in '0123456789abcdef'for c in approval),'exact administrator approval SHA-256 required')
        return STATE/'retirements'/(str(self.uid)+'-'+approval[:24])

    def retire(self,approval):
        require_native()
        with locks(change=True,historical=self.historical_ea60):
            d=self._pending(approval)
            if not d.exists():
                v=self._inspect();require(v['approval_sha256']==approval,'identified deployment changed since independent approval')
                # Immutable audit snapshots precede any legacy mutation.
                parent=d.parent
                if not parent.exists():parent.mkdir(mode=0o700);sync(parent.parent)
                trusted(parent,directory=True)
                staging=Path(tempfile.mkdtemp(prefix='.audit-',dir=parent))
                # Incomplete audit staging is retained but never mistaken for a
                # transaction. No live installation bytes change before rename.
                atomic(staging/'approval.json',(json.dumps(v['deployment'],sort_keys=True,indent=2)+'\n').encode())
                atomic(staging/'original-record.json',ABSENT_RECORD if self.historical_ea60 else read(self.record));atomic(staging/'original-unit',read((TRANSIENT_UNITS if self.historical_ea60 else UNITS)/self.unit,65536))
                write_json(staging/'state.json',dict(contract=CONTRACT,phase='PREPARED',approval=approval))
                sync(staging);os.rename(staging,d);sync(parent);self.checkpoint('PREPARED')
            return self._finish(d,approval)

    def _load(self,d,approval):
        trusted(d,directory=True);v=json.loads(read(d/'approval.json'));t=json.loads(read(d/'state.json'))
        require(sha(read(d/'approval.json'))==approval and v['uid']==self.uid and t['contract']==CONTRACT and t['approval']==approval,'transaction approval changed')
        require(sha(read(d/'original-record.json'))==v['record_sha256']and sha(read(d/'original-unit'))==v['unit_sha256'],'transaction archive changed')
        require(bool(v.get('historical_ea60'))==self.historical_ea60,'explicit historical mode must match the transaction')
        m,h=(historical_deployment if self.historical_ea60 else deployment)(Path(v['deployment']),self.uid);require(h==v['manifest_sha256'],'preserved legacy deployment changed')
        anchor=(STATE/'storage_thermal_recovery_required.json.scope').stat()
        require([anchor.st_dev,anchor.st_ino]==v['anchor'],'canonical anchor replaced since approval')
        no_alternate_unit(self.unit,Path(v['deployment']))
        self._policy(properties(self.unit),v,allow_pending=True)
        return v,t

    def _check_record(self,d,v,approval,original=False):
        if original and v.get('historical_ea60')and not(self.record.exists()or self.record.is_symlink()):return
        raw=read(self.record)
        if original and sha(raw)==v['record_sha256']:return
        r=json.loads(raw)
        require(r==dict(phase='retiring',contract=CONTRACT,transaction=d.name,approval=approval)or r==dict(phase='retired',contract=CONTRACT,transaction=d.name,approval=approval),'installation authority changed')

    def _finish(self,d,approval):
        v,t=self._load(d,approval);no_transient();no_other_legacy(self.unit)
        require(t['phase']in ('PREPARED','MASKED','STOPPED','SOCKET_RECONCILED','RETIRED'),'rollback/incomplete transaction requires explicit rollback')
        self._check_record(d,v,approval,original=t['phase']=='PREPARED')
        if t['phase']=='RETIRED':retired_record(self.uid);return dict(status='RETIRED',transaction=str(d),recovery='unchanged')
        path=Path(v['deployment']);main=self._quiescent(v,allow_main=True)
        require(main is None or main==v['main'],'legacy service generation changed since approval')
        # Revalidate unit independently on resume, including the pre-mask window.
        require(self._unit_ok(v),'legacy unit changed during transaction')
        props=properties(self.unit);self._policy(props,v,allow_pending=True)
        write_json(self.record,dict(phase='retiring',contract=CONTRACT,transaction=d.name,approval=approval))
        if not self.historical_ea60:ctl('disable',self.unit)
        if not masked(self.unit):
            temporary=UNITS/('.retire-'+d.name)
            if temporary.exists()or temporary.is_symlink():
                require(temporary.is_symlink()and temporary.lstat().st_uid==0 and os.readlink(temporary)=='/dev/null','unexpected mask staging entry')
            else:os.symlink('/dev/null',temporary)
            os.replace(temporary,UNITS/self.unit);sync(UNITS)
        ctl('daemon-reload');self._policy(properties(self.unit),v);self._state(d,'MASKED',approval)
        ctl('stop',self.unit);self._quiescent(v);self._state(d,'STOPPED',approval)
        self._reconcile_fragment(v)
        self._endpoint(v)
        self._state(d,'SOCKET_RECONCILED',approval)
        self._wait_state(lambda:masked(self.unit)and properties(self.unit)['UnitFileState']=='masked','persistent legacy mask missing')
        journal();write_json(self.record,dict(phase='retired',contract=CONTRACT,transaction=d.name,approval=approval))
        self._state(d,'RETIRED',approval);retired_record(self.uid)
        return dict(status='RETIRED',transaction=str(d),recovery='unchanged',legacy_tree_and_account='tree retained; operator identity unchanged'if self.historical_ea60 else'retained')

    def _reconcile_fragment(self,v):
        if self.historical_ea60:
            self._policy(properties(self.unit),v)
            fragment=TRANSIENT_UNITS/self.unit
            if fragment.exists()or fragment.is_symlink():
                require(sha(read(fragment,65536))==v['unit_sha256'],'historical transient fragment changed after stop')
                fragment.unlink();sync(fragment.parent)
            ctl('daemon-reload')


    def _endpoint(self,v):
        target=SOCKETS/(str(self.uid)+'.sock')
        if target.exists()or target.is_symlink():
            before=endpoint_info(self.uid,v['gid'],None)
            require(v['socket']is not None and (before['device'],before['inode'])==(v['socket']['device'],v['socket']['inode']),'socket identity changed')
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)as probe:
                probe.settimeout(.3)
                try:probe.connect(str(target))
                except OSError as exc:require(exc.errno==errno.ECONNREFUSED,'socket not proven stale')
                else:raise ValueError('live socket cannot be reconciled')
            after=target.lstat();require((before['device'],before['inode'])==(after.st_dev,after.st_ino),'socket changed during reconciliation')
            target.unlink();sync(target.parent)

    def rollback(self,approval):
        require_native()
        with locks(change=True,historical=self.historical_ea60):
            d=self._pending(approval);v,t=self._load(d,approval);no_transient();no_other_legacy(self.unit)
            require(t['phase']in ('PREPARED','MASKED','STOPPED','SOCKET_RECONCILED','RETIRED','ROLLING_BACK','ROLLED_BACK'),'unknown rollback phase')
            self._check_record(d,v,approval,original=t['phase']in ('PREPARED','ROLLING_BACK','ROLLED_BACK'))
            require(self._unit_ok(v),'unreviewed unit cannot be restored')
            props=properties(self.unit);self._policy(props,v,allow_pending=True)
            main=self._quiescent(v,allow_main=True)
            require(main is None or main==v['main'],'legacy service generation changed since approval')
            self._state(d,'ROLLING_BACK',approval)
            if not self.historical_ea60 or properties(self.unit)['LoadState']!='not-found':ctl('stop',self.unit)
            self._quiescent(v)
            self._reconcile_fragment(v)
            self._endpoint(v)
            if self.historical_ea60:
                if masked(self.unit):(UNITS/self.unit).unlink();sync(UNITS)
                ctl('daemon-reload')
                self._wait_state(lambda:properties(self.unit)['LoadState']=='not-found','historical transient unit not collected')
                journal();self.record.unlink(missing_ok=True);sync(STATE)
            else:
                ctl('disable',self.unit)
                atomic(UNITS/self.unit,read(d/'original-unit',65536));os.chmod(UNITS/self.unit,0o644);sync(UNITS)
                ctl('daemon-reload');require(properties(self.unit)['UnitFileState']=='disabled','rollback enablement uncertain')
                journal();atomic(self.record,read(d/'original-record.json'))
            self._state(d,'ROLLED_BACK',approval)
            return dict(status='ROLLED_BACK',legacy_service='stopped; transient unit not recreated; separate authorization required'if self.historical_ea60 else'stopped and disabled; separate authorization required to start',recovery='unchanged',transaction=str(d))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--inspect',type=int);p.add_argument('--retire',type=int);p.add_argument('--rollback',type=int);p.add_argument('--approve-sha256');p.add_argument('--historical-ea60',action='store_true');a=p.parse_args()
    require(os.getuid()==0,'explicit administrator invocation required; no automatic elevation')
    trusted(Path(__file__).absolute());trusted(Path(sys.executable).resolve())
    require(Path(sys.executable).resolve()==Path('/usr/bin/python3').resolve()and sys.flags.isolated and sys.dont_write_bytecode,'use trusted OS Python -I -B')
    require(sum(x is not None for x in (a.inspect,a.retire,a.rollback))==1,'select one operation')
    if a.inspect is not None:require(a.approve_sha256 is None,'inspection does not approve a transition');v=Migration(a.inspect,historical_ea60=a.historical_ea60).inspect()
    elif a.retire is not None:v=Migration(a.retire,historical_ea60=a.historical_ea60).retire(a.approve_sha256)
    else:v=Migration(a.rollback,historical_ea60=a.historical_ea60).rollback(a.approve_sha256)
    print(json.dumps(v,indent=2))


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError)as exc:
        print(json.dumps(dict(status='BLOCKED',reason=str(exc),recovery='never changed; retain evidence and obtain separate administrator review')));raise SystemExit(1)
