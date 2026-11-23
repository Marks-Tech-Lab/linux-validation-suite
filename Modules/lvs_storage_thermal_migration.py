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
import os
import pwd
import socket
import stat
import subprocess
import sys
import tempfile

STATE=Path('/var/lib/lvs-thermal')
STARTUP=Path('/run/lvs-thermal-on-demand')
UNITS=Path('/etc/systemd/system')
SOCKETS=Path('/run/lvs-thermal')
ENV=dict(PATH='/usr/bin:/bin',HOME='/root',LC_ALL='C',PYTHONDONTWRITEBYTECODE='1')
HEADER=b'LVS storage recovery scope v1\n'
CONTRACT='lvs.thermal.legacy_retirement.v1'


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
def locks(change=False):
    """Global order: legacy install -> transient startup -> existing anchor.

    No scope creation, missing recovery acceptance, journal rewrite or repair.
    Inspection opens only existing locks. A missing startup lock is safe while
    install.lock is held: all new startups now take install.lock first.
    """
    fds=[]
    try:
        trusted(STATE,directory=True)
        for p in (STATE/'install.lock',STARTUP/'startup.lock',STATE/'storage_thermal_recovery_required.json.scope'):
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


def no_alternate_unit(unit,path):
    for directory in ('/etc/systemd/system','/run/systemd/system','/usr/lib/systemd/system'):
        base=Path(directory)
        if not base.exists():continue
        for p in base.rglob('*.service'):
            if p.name==unit:continue
            # A known deployment referenced by any second unit is ambiguous,
            # even if that alternate unit is currently stopped.
            if p.is_symlink():
                resolved=p.resolve(strict=True)
                if not resolved.is_file():continue
                p=resolved
            if str(path/'launch.py').encode()in read(p,65536):raise ValueError('alternate unit references legacy deployment')


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


def quiescent(unit,path,worker_uid,allow_main=False):
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
        require(argv==[b'/usr/bin/python3',b'-I',b'-B',str(path/'launch.py').encode(),b'--serve-integrated'],'unexpected legacy main command')
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
    def __init__(self,uid,checkpoint=None):
        require(type(uid)is int and 0<uid<2**32-1,'positive operator UID required')
        self.uid=uid;self.unit=f'lvs-thermal-{uid}.service';self.record=STATE/f'installation-{uid}.json';self.checkpoint=checkpoint or(lambda _:None)

    def inspect(self):
        require_native()
        with locks():return self._inspect()

    def _inspect(self):
        no_transient();no_other_legacy(self.unit);raw=read(self.record);r=json.loads(raw)
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

    def _state(self,d,phase,approval):
        write_json(d/'state.json',dict(contract=CONTRACT,phase=phase,approval=approval));self.checkpoint(phase)

    def _pending(self,approval):
        require(type(approval)is str and len(approval)==64 and all(c in '0123456789abcdef'for c in approval),'exact administrator approval SHA-256 required')
        return STATE/'retirements'/(str(self.uid)+'-'+approval[:24])

    def retire(self,approval):
        require_native()
        with locks(change=True):
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
                atomic(staging/'original-record.json',read(self.record));atomic(staging/'original-unit',read(UNITS/self.unit,65536))
                write_json(staging/'state.json',dict(contract=CONTRACT,phase='PREPARED',approval=approval))
                sync(staging);os.rename(staging,d);sync(parent);self.checkpoint('PREPARED')
            return self._finish(d,approval)

    def _load(self,d,approval):
        trusted(d,directory=True);v=json.loads(read(d/'approval.json'));t=json.loads(read(d/'state.json'))
        require(sha(read(d/'approval.json'))==approval and v['uid']==self.uid and t['contract']==CONTRACT and t['approval']==approval,'transaction approval changed')
        require(sha(read(d/'original-record.json'))==v['record_sha256']and sha(read(d/'original-unit'))==v['unit_sha256'],'transaction archive changed')
        m,h=deployment(Path(v['deployment']),self.uid);require(h==v['manifest_sha256'],'preserved legacy deployment changed')
        anchor=(STATE/'storage_thermal_recovery_required.json.scope').stat()
        require([anchor.st_dev,anchor.st_ino]==v['anchor'],'canonical anchor replaced since approval')
        no_alternate_unit(self.unit,Path(v['deployment']))
        return v,t

    def _check_record(self,d,v,approval,original=False):
        raw=read(self.record)
        if original and sha(raw)==v['record_sha256']:return
        r=json.loads(raw)
        require(r==dict(phase='retiring',contract=CONTRACT,transaction=d.name,approval=approval)or r==dict(phase='retired',contract=CONTRACT,transaction=d.name,approval=approval),'installation authority changed')

    def _finish(self,d,approval):
        v,t=self._load(d,approval);no_transient();no_other_legacy(self.unit)
        require(t['phase']in ('PREPARED','MASKED','STOPPED','SOCKET_RECONCILED','RETIRED'),'rollback/incomplete transaction requires explicit rollback')
        self._check_record(d,v,approval,original=t['phase']=='PREPARED')
        if t['phase']=='RETIRED':retired_record(self.uid);return dict(status='RETIRED',transaction=str(d),recovery='unchanged')
        path=Path(v['deployment']);main=quiescent(self.unit,path,v['worker_uid'],allow_main=True)
        require(main is None or main==v['main'],'legacy service generation changed since approval')
        # Revalidate unit independently on resume, including the pre-mask window.
        require(masked(self.unit)or sha(read(UNITS/self.unit,65536))==v['unit_sha256'],'legacy unit changed during transaction')
        props=properties(self.unit);require(not props['DropInPaths']and not props['Triggers']and not props['TriggeredBy'],'unreviewed service override/trigger')
        write_json(self.record,dict(phase='retiring',contract=CONTRACT,transaction=d.name,approval=approval))
        ctl('disable',self.unit)
        if not masked(self.unit):
            temporary=UNITS/('.retire-'+d.name)
            if temporary.exists()or temporary.is_symlink():
                require(temporary.is_symlink()and temporary.lstat().st_uid==0 and os.readlink(temporary)=='/dev/null','unexpected mask staging entry')
            else:os.symlink('/dev/null',temporary)
            os.replace(temporary,UNITS/self.unit);sync(UNITS)
        ctl('daemon-reload');self._state(d,'MASKED',approval)
        ctl('stop',self.unit);quiescent(self.unit,path,v['worker_uid']);self._state(d,'STOPPED',approval)
        self._endpoint(v)
        self._state(d,'SOCKET_RECONCILED',approval)
        require(masked(self.unit)and properties(self.unit)['UnitFileState']=='masked','persistent legacy mask missing')
        journal();write_json(self.record,dict(phase='retired',contract=CONTRACT,transaction=d.name,approval=approval))
        self._state(d,'RETIRED',approval);retired_record(self.uid)
        return dict(status='RETIRED',transaction=str(d),recovery='unchanged',legacy_tree_and_account='retained')

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
        with locks(change=True):
            d=self._pending(approval);v,t=self._load(d,approval);no_transient();no_other_legacy(self.unit)
            require(t['phase']in ('PREPARED','MASKED','STOPPED','SOCKET_RECONCILED','RETIRED','ROLLING_BACK','ROLLED_BACK'),'unknown rollback phase')
            self._check_record(d,v,approval,original=t['phase']in ('PREPARED','ROLLING_BACK','ROLLED_BACK'))
            require(masked(self.unit)or sha(read(UNITS/self.unit,65536))==v['unit_sha256'],'unreviewed unit cannot be restored')
            props=properties(self.unit);require(not props['DropInPaths']and not props['Triggers']and not props['TriggeredBy'],'unreviewed rollback override')
            main=quiescent(self.unit,Path(v['deployment']),v['worker_uid'],allow_main=True)
            require(main is None or main==v['main'],'legacy service generation changed since approval')
            self._state(d,'ROLLING_BACK',approval)
            ctl('stop',self.unit);quiescent(self.unit,Path(v['deployment']),v['worker_uid'])
            self._endpoint(v)
            ctl('disable',self.unit)
            atomic(UNITS/self.unit,read(d/'original-unit',65536));os.chmod(UNITS/self.unit,0o644);sync(UNITS)
            ctl('daemon-reload');require(properties(self.unit)['UnitFileState']=='disabled','rollback enablement uncertain')
            journal();atomic(self.record,read(d/'original-record.json'))
            self._state(d,'ROLLED_BACK',approval)
            return dict(status='ROLLED_BACK',legacy_service='stopped and disabled; separate authorization required to start',recovery='unchanged',transaction=str(d))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--inspect',type=int);p.add_argument('--retire',type=int);p.add_argument('--rollback',type=int);p.add_argument('--approve-sha256');a=p.parse_args()
    require(os.getuid()==0,'explicit administrator invocation required; no automatic elevation')
    trusted(Path(__file__).absolute());trusted(Path(sys.executable).resolve())
    require(Path(sys.executable).resolve()==Path('/usr/bin/python3').resolve()and sys.flags.isolated and sys.dont_write_bytecode,'use trusted OS Python -I -B')
    require(sum(x is not None for x in (a.inspect,a.retire,a.rollback))==1,'select one operation')
    if a.inspect is not None:require(a.approve_sha256 is None,'inspection does not approve a transition');v=Migration(a.inspect).inspect()
    elif a.retire is not None:v=Migration(a.retire).retire(a.approve_sha256)
    else:v=Migration(a.rollback).rollback(a.approve_sha256)
    print(json.dumps(v,indent=2))


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError)as exc:
        print(json.dumps(dict(status='BLOCKED',reason=str(exc),recovery='never changed; retain evidence and obtain separate administrator review')));raise SystemExit(1)
