"""Authenticated installed-runtime transport; no workload engine or sudo policy.

The operator starts the verified root-owned launcher's session service. Clients
remain unprivileged. Only bounded configuration and existing stage descriptors
cross this boundary; executable paths and persistent state are server-owned.
"""
from __future__ import annotations
import array
from dataclasses import fields
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import stat
import struct
import subprocess
import sys
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
STATE=Path('/var/lib/lvs-thermal')
SOCKET_ROOT=Path('/run/lvs-thermal')
MAX_PACKET=8*1024**2
MAX_CLIENTS=4


def require(value,reason):
    if not value:raise ValueError(reason)


def configuration(value):
    from .lvs_storage_thermal import ThermalConfig
    require(type(value) is dict,'configuration must be an object')
    require(set(value)=={f.name for f in fields(ThermalConfig)},'complete configuration with no extra fields required')
    result=ThermalConfig(**value)
    require(result.monitoring=='required','installed integration requires reliable temperature monitoring')
    return result


from .lvs_storage_thermal_system import owned_path


def endpoint(uid=None):return SOCKET_ROOT/(str(os.getuid() if uid is None else uid)+'.sock')


def token(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{32}',value),'invalid session identity')
    return value


def _exact(conn,length,deadline):
    data=bytearray()
    while len(data)<length:
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('runtime framing deadline')
        conn.settimeout(remaining)
        part=conn.recv(min(65536,length-len(data)))
        if not part:raise EOFError('runtime connection closed')
        data.extend(part)
    return bytes(data)


def send(conn,value):
    data=json.dumps(value,allow_nan=False).encode()
    require(len(data)<=MAX_PACKET,'runtime response limit')
    conn.sendall(struct.pack('!I',len(data))+data)


def receive(conn):
    previous=conn.gettimeout();deadline=time.monotonic()+(previous if previous is not None else 3)
    try:
        size=struct.unpack('!I',_exact(conn,4,deadline))[0]
        require(size<=MAX_PACKET,'runtime message limit')
        value=json.loads(_exact(conn,size,deadline))
        require(type(value) is dict,'runtime envelope must be an object')
        return value
    finally:conn.settimeout(previous)


def connect(timeout=3):
    owned_path(SOCKET_ROOT,directory=True)
    path=endpoint();s=path.lstat()
    require(stat.S_ISSOCK(s.st_mode) and s.st_uid==0 and not s.st_mode&0o007,'untrusted runtime socket')
    conn=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    try:
        conn.settimeout(timeout);conn.connect(str(path))
        pid,uid,gid=struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        require(uid==0 and pid>1,'runtime peer is not root')
        return conn
    except BaseException:conn.close();raise


def rpc(op,**payload):
    try:
        with connect(15) as conn:
            conn.sendall(b'J');send(conn,dict(operation=op,**payload))
            result=receive(conn)
            if result.get('error'):raise OSError(result['error'])
            return result
    except (EOFError,ValueError,KeyError,TypeError) as exc:
        raise OSError('Installed runtime unavailable or invalid response: '+str(exc)) from exc


def preview(config):
    try:return _preview(config)
    except (EOFError,KeyError,TypeError) as exc:
        raise OSError('Installed runtime readiness is incomplete: '+str(exc)) from exc


def inspect(config):
    """Local metadata only: no RPC, subprocess, sudo, native load or host write.

    Socket presence is not proof that a service is live, compatible or eligible.
    Those authoritative checks belong to confirmed execution preparation.
    """
    owned_path(SOCKET_ROOT,directory=True)
    s = endpoint().lstat()
    require(stat.S_ISSOCK(s.st_mode) and s.st_uid==0 and not s.st_mode&0o007,
            'trusted Thermal Assist endpoint unavailable')
    return dict(status='DEFERRED', inspection_only=True, preparation_required=True,
        execution_ready=False, configuration=config.to_dict(), devices=[], targets=[],
        selected_devices=[], runnable_devices=[], blocked_devices=[], commands=[],
        backend=dict(status='unverified'),
        reasons=['Execution readiness pending final run confirmation and authorization'])


def _inspect(config):
    result=rpc('inspect',configuration=config.to_dict())
    from .lvs_source_provenance import _source_snapshot
    require(result['installed_runtime']['source']==_source_snapshot(ROOT)[0],'installed runtime/source mismatch; use ./setup.sh → 9 to prepare an approved update; restart LVS after promotion')
    info=result['installed_runtime']
    binary=owned_path(Path(info['root'])/'runtime/build/storage_thermal_launch.so')
    require(hashlib.sha256(binary.read_bytes()).hexdigest()==info['bootstrap_sha256'],'installed bootstrap mismatch')
    return result


def _preview(config):
    result = _inspect(config)
    binary=owned_path(Path(result['installed_runtime']['root'])/'runtime/build/storage_thermal_launch.so')
    from .lvs_storage_thermal_launch import prepare,ready,provenance
    if ready():
        observed=provenance()['binary'];identity=binary.stat()
        require((observed['file_device'],observed['file_inode'])==(identity.st_dev,identity.st_ino),'different bootstrap already loaded; restart LVS')
    prepare(binary.parent,allow_build=False)  # verified installed bytes; never rebuild from client source
    result['execution_ready'] = True
    return result


def read_terminal(session):return rpc('terminal',session=token(session))


def proxy(channel,admission_fd):
    """Owned unprivileged relay; root only receives existing descriptor authority."""
    read_fd,write_fd=map(int,channel.split(':'));parent=os.getppid()
    # TERM closes the authenticated connection rather than abandoning a root job.
    stopped=[False]
    for sig in (signal.SIGTERM,signal.SIGHUP,signal.SIGINT):signal.signal(sig,lambda *_:stopped.__setitem__(0,True))
    with connect() as conn:
        descriptors=array.array('i',[read_fd,write_fd,admission_fd])
        conn.sendmsg([b'F'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,descriptors)])
        conn.settimeout(None)
        while not stopped[0] and os.getppid()==parent:
            if select.select([conn],[],[],.1)[0]:
                result=receive(conn)
                return 0 if result.get('clean') is True else 1
    return 1




if __name__=='__main__':
    require(len(sys.argv)==4 and sys.argv[1]=='--proxy','internal owned proxy arguments required')
    raise SystemExit(proxy(sys.argv[2],int(sys.argv[3])))
