"""Root-only installed Thermal Assist session service.

Reached only through the independently approved root-owned launcher. The normal
frontend imports the unprivileged transport, never this service entrypoint.
"""
from __future__ import annotations
import array
import hashlib
import os
from pathlib import Path
import select
import signal
import socket
import stat
import struct
import subprocess
import sys
import time
from uuid import uuid4
from .lvs_storage_thermal_runtime import (STATE,SOCKET_ROOT,MAX_CLIENTS,
    configuration,owned_path,token,require,send,receive,endpoint)


class RuntimePolicy:
    def __init__(self,root,manifest,generation,peer_pid):
        self.root=Path(root);self.manifest=manifest;self.generation=token(generation)
        self.uid=manifest['uid'];self.gid=manifest['gid'];self.peer_pid=peer_pid
        require(type(self.uid) is int and type(self.gid) is int and self.uid>0 and self.gid>0,'explicit non-root operator identity required')
        self.marker=STATE/'storage_thermal_recovery_required.json'

    def runner(self):
        from .lvs_storage_thermal_runner import ThermalRunner
        return ThermalRunner(self.root/'runtime/build/fio',self.root/'runtime/build/storage_thermal_guard',uid=self.uid,gid=self.gid)

    def directory(self,session):return STATE/'integrated'/str(self.uid)/token(session)

    def request(self,request,descriptors):
        require(type(request) is dict,'stage request object required')
        require(set(request)=={'plan','execution_context','directory','supervisor_parent_pid','recovery_marker','stage_deadline','stage_lease_id','admission_fd','admission_identity'},'invalid stage envelope')
        plan=request['plan'];configuration(plan['configuration'])
        require(plan['installed_runtime']['generation']==self.generation,'stale runtime generation')
        require(plan['installed_runtime']['source']==self.manifest['source'],'foreign runtime source')
        deadline=request['stage_deadline'];now=time.monotonic()
        require(type(deadline) in (int,float) and now<deadline<=now+86400,'invalid stage deadline')
        session=token(request['stage_lease_id']);context=request['execution_context']
        require(type(context) is dict and set(context)=={'version','run_id','session_id','stage_id','run_directory','started_ns','deadline_ns','lease_identity'},'complete execution context required')
        require(type(context['version']) is int and context['version']==1 and context['session_id']==session,'session binding mismatch')
        require(type(context['run_directory']) is str and len(context['run_directory'])<=4096 and os.path.isabs(context['run_directory']),'invalid primary evidence identity')
        require(not self.directory(session).exists() and not self.directory(session).is_symlink(),'session already exists; evidence cannot be overwritten')
        require(type(context['deadline_ns']) is int and context['deadline_ns']==int(deadline*1e9),'deadline context mismatch')
        require(type(context['started_ns']) is int and 0<context['started_ns']<context['deadline_ns'],'invalid stage window')
        require(context['deadline_ns']-context['started_ns']<=86400*10**9,'stage window exceeds contract')
        require(abs(context['deadline_ns']-context['started_ns']-plan['configuration']['duration_seconds']*10**9)<=1000,'configuration/window mismatch')
        require(type(context['stage_id']) is str and 0<len(context['stage_id'])<=256,'invalid stage identity')
        require(type(context['run_id']) is str and 0<len(context['run_id'])<=128,'invalid run identity')
        # Peer is the owned proxy; its parent must be the primary coordinator.
        row=Path(f'/proc/{self.peer_pid}/stat').read_text().rsplit(')',1)[1].split()
        require(type(request['supervisor_parent_pid']) is int and int(row[1])==request['supervisor_parent_pid'],'primary/proxy ancestry mismatch')
        from .lvs_storage_thermal_stage import SharedAdmission
        admission=SharedAdmission(os.dup(descriptors[2]),request['admission_identity'])
        try:require(list(admission.verified_identity())==context['lease_identity'],'lease context mismatch')
        finally:admission.close()
        for fd,mode in zip(descriptors[:2],(os.O_RDONLY,os.O_WRONLY)):
            import fcntl
            require(stat.S_ISFIFO(os.fstat(fd).st_mode) and fcntl.fcntl(fd,fcntl.F_GETFL)&os.O_ACCMODE==mode,'stage pipe identity/type mismatch')
        result=dict(request,directory=str(self.directory(session)),recovery_marker=str(self.marker),
                    supervisor_parent_pid=os.getppid(),admission_fd=descriptors[2])
        # No child/caller path is ever a privileged publication destination.
        return result



def client(root,manifest,generation):
    conn=socket.socket(fileno=os.dup(0));conn.settimeout(3);received=[]
    try:
        pid,uid,gid=struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        require(uid==manifest['uid'] and gid==manifest['gid'] and pid>1,'unauthorized runtime peer')
        for namespace in ('mnt','user','time'):
            reference=Path('/proc/1/ns')/namespace
            if not reference.exists() and namespace=='time':continue
            native=reference.stat();peer=os.stat(f'/proc/{pid}/ns/{namespace}')
            require((native.st_dev,native.st_ino)==(peer.st_dev,peer.st_ino),'client namespace is not the native host: '+namespace)
        policy=RuntimePolicy(root,manifest,generation,pid)
        from .lvs_storage_thermal_launch import prepare
        prepare(Path(root)/'runtime/build',allow_build=False)
        data,anc,flags,_=conn.recvmsg(1,socket.CMSG_SPACE(3*array.array('i').itemsize),socket.MSG_CMSG_CLOEXEC)
        for level,kind,raw in anc:
            require(level==socket.SOL_SOCKET and kind==socket.SCM_RIGHTS,'unexpected descriptor metadata')
            a=array.array('i');a.frombytes(raw[:len(raw)-len(raw)%a.itemsize]);received.extend(a)
        require(not flags&(socket.MSG_CTRUNC|socket.MSG_TRUNC),'truncated runtime request')
        if data==b'J':
            require(not received,'unexpected descriptors')
            request=receive(conn);op=request.get('operation')
            if op=='inspect':
                require(set(request)=={'operation','configuration'},'invalid inspect envelope')
                from .lvs_storage_thermal_stage import inspect_stage
                from .lvs_storage_thermal_recovery import blocker
                config=configuration(request['configuration']);runner=policy.runner();result=inspect_stage(runner,config)
                candidates=[r for r in result.get('targets',[]) if r.get('state')=='ready']
                runner.targets.output_safe(policy.root,candidates)
                runner.targets.output_safe(STATE,candidates)
                reason=blocker(policy.marker)
                if reason:result.update(status='BLOCKED',reasons=list(result.get('reasons',[]))+[reason],runnable_devices=[])
                result['installed_runtime']=dict(source=manifest['source'],generation=generation,root=str(root),
                    bootstrap_sha256=manifest['files']['runtime/build/storage_thermal_launch.so'])
                send(conn,result)
            elif op=='terminal':
                require(set(request)=={'operation','session'},'invalid terminal envelope')
                from .lvs_storage_thermal_recovery import evidence_operation
                send(conn,evidence_operation('--read-terminal',policy.directory(request['session']),policy.marker))
            else:raise ValueError('unsupported installed operation')
        elif data==b'F':
            require(len(received)==3,'exactly three stage descriptors required')
            from .lvs_storage_thermal_stage import channel_worker
            # Parent death/closed channel and native lease checks remain in force.
            conn.setblocking(False)
            def disconnected():
                try:
                    data=conn.recv(1,socket.MSG_PEEK)
                    if data:policy.transport_error='Unexpected data after stage descriptor handoff'
                    return True  # EOF or unsolicited input both stop the lease
                except BlockingIOError:return False
                except OSError:return True
            policy.disconnected=disconnected
            code=channel_worker(f'{received[0]}:{received[1]}',runtime=policy,descriptors=received)
            received=received[2:]  # channel_worker closed its pipes; never close a reused descriptor
            conn.settimeout(1);send(conn,dict(clean=code==0))
        else:raise ValueError('unknown installed protocol')
        return 0
    except BaseException as exc:
        try:conn.settimeout(1);send(conn,dict(error=str(exc)[:1024],clean=False))
        except (OSError,ValueError):pass
        return 1
    finally:
        for fd in received:
            try:os.close(fd)
            except OSError:pass
        conn.close()


def serve(root,manifest):
    require(os.getuid()==0,'operator-authorized installed root runtime required')
    root=owned_path(Path(root).resolve(),directory=True);owned_path(STATE,directory=True)
    # Caller is the already verified installed launcher. Recheck every identity.
    for name,digest in manifest['files'].items():
        p=owned_path(root/name);require(hashlib.sha256(p.read_bytes()).hexdigest()==digest,'installed runtime changed')
    from .lvs_storage_thermal_launch import prepare,OwnedProcess
    prepare(root/'runtime/build',allow_build=False)
    uid=manifest['uid'];gid=manifest['gid'];require(type(uid) is int and uid>0 and type(gid) is int and gid>0,'invalid operator identity')
    if not SOCKET_ROOT.exists():SOCKET_ROOT.mkdir(mode=0o755)
    owned_path(SOCKET_ROOT,directory=True)
    target=endpoint(uid);require(not target.exists() and not target.is_symlink(),'runtime endpoint already exists; do not overwrite')
    # Session artifact parents are exclusively root-owned, never caller paths.
    for p in (STATE/'integrated',STATE/'integrated'/str(uid)):
        if not p.exists():p.mkdir(mode=0o755)
        owned_path(p,directory=True)
    listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);children=[];generation=uuid4().hex;stop=[False];bound_identity=None
    for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):signal.signal(sig,lambda *_:stop.__setitem__(0,True))
    try:
        listener.bind(str(target));bound=target.lstat();bound_identity=(bound.st_dev,bound.st_ino)
        os.chown(target,0,gid);os.chmod(target,0o660);listener.listen(MAX_CLIENTS);listener.setblocking(False)
        while not stop[0]:
            for child in children[:]:
                if child.poll() is not None and child.group_cleanup_confirmed():children.remove(child)
            if not select.select([listener],[],[],.1)[0]:continue
            conn,_=listener.accept()
            try:
                _,peer_uid,peer_gid=struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                if peer_uid!=uid or peer_gid!=gid or len(children)>=MAX_CLIENTS:continue
                argv=[sys.executable,'-I','-B',str(root/'launch.py'),'--integrated-client',generation]
                children.append(OwnedProcess(argv,stdin=conn.fileno(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True))
            finally:conn.close()
    finally:
        listener.close()
        try:
            bound=target.lstat()
            if bound_identity==(bound.st_dev,bound.st_ino):target.unlink()
        except FileNotFoundError:pass
        for child in children:
            try:
                child.terminate()
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=2)
            except OSError:pass  # durable ARMED obligations are never cleared here
    return 0
