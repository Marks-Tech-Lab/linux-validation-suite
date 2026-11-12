"""Narrow, owned Linux process launch without a parent-side exec handshake.

The optional C bootstrap must be prepared before timed execution. clone returns
an owned PID while all exec/filesystem latency stays in the gated child. No
Python interpreter code executes after clone until a fresh exec. This is not a
general Popen replacement, privilege helper, or an I/O engine.
"""
from __future__ import annotations
import ctypes
from dataclasses import dataclass
import threading
from contextlib import contextmanager
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time

def group_gone(pgid):
    try:os.killpg(pgid,0);return False
    except ProcessLookupError:return True
    except PermissionError:return False


ROOT=Path(__file__).resolve().parents[1]
_LIBRARY=None
_PROVENANCE={}
_OWNED={}  # registered before child release; failures cannot abandon ownership


def prepare(directory=None):
    global _LIBRARY,_PROVENANCE
    if _LIBRARY is not None:return True
    from .lvs_native_helpers import find_c_compiler,native_helper_build_command
    source=ROOT/'native/storage_thermal_launch.c'
    binary=Path(directory or ROOT/'build')/'storage_thermal_launch.so'
    compiler=find_c_compiler()
    binary.parent.mkdir(parents=True,exist_ok=True)
    # Existing helper compiler policy; never called on primary timed path.
    if not binary.exists() or binary.stat().st_mtime_ns<source.stat().st_mtime_ns:
        if compiler is None:raise OSError('C compiler required to prepare optional owned launch bootstrap')
        import tempfile
        with tempfile.TemporaryDirectory(dir=binary.parent) as tmp:
            target=Path(tmp)/'launch.so'
            subprocess.run(native_helper_build_command(compiler,source,target)+['-shared','-fPIC','-Wall','-Wextra','-Werror'],check=True,capture_output=True,timeout=30)
            os.replace(target,binary)
    library=ctypes.CDLL(str(binary),use_errno=True)
    library.lvs_owned_launch.argtypes=[ctypes.POINTER(ctypes.c_char_p),ctypes.POINTER(ctypes.c_char_p),ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_int),ctypes.POINTER(ctypes.c_int),ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_uint,ctypes.c_uint64,ctypes.POINTER(ctypes.c_int)]
    library.lvs_owned_launch.restype=ctypes.c_int
    from .lvs_native_binary_provenance import executable_snapshot
    import hashlib
    observed=executable_snapshot(binary)
    stable={k:observed.get(k) for k in ('status','sha256','architecture','file_device','file_inode','modified_time_ns','changed_time_ns','size_bytes')}
    _PROVENANCE=dict(binary=stable,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        compiler=compiler or 'existing target-local bootstrap',protocol='owned-clone-exec-v2')
    if _PROVENANCE['binary'].get('status')!='observed':raise OSError('Owned launch provenance unavailable')
    _LIBRARY=library
    return True


def ready():return _LIBRARY is not None


def provenance():return dict(_PROVENANCE)


@dataclass(frozen=True)
class _CreationIdentity:
    pid: int
    pgid: int | None


class OwnedProcess:
    @property
    def _creation_pid(self):
        return self._creation.pid

    @property
    def authority_pid(self):return self._creation.pid

    @property
    def returncode(self):return self._returncode

    def __init__(self, args, *, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, pass_fds=(), cwd=None, env=None,
                 start_new_session=True, close_fds=True, text=False, delay_ms=0, owner=None, deadline=None, stage_bootstrap=False):
        if _LIBRARY is None:raise OSError('Owned launch bootstrap was not prepared; no synchronous fallback')
        if not close_fds or bool(stage_bootstrap)==bool(start_new_session):raise ValueError('Owned isolated or native-stage bootstrap launch required')
        if type(delay_ms) is not int or not 0<=delay_ms<=30000:raise ValueError('invalid bootstrap delay')
        self.args=args;self.pid=None;self._returncode=None;self.text=text;self.stdin=self.stdout=self.stderr=None
        self.pidfd=None;self._pidfd_identity=None;self._lifecycle=threading.Lock();self._native_stage=bool(stage_bootstrap);self._native_group=None
        self._offset=0;self._out=bytearray();self._err=bytearray();self._gate=None
        parent=[];child=[];io=[];pid_slot=ctypes.c_int(0)
        try:
            for name,value in (('stdin',stdin),('stdout',stdout),('stderr',stderr)):
                if value==subprocess.PIPE:
                    r,w=os.pipe2(os.O_CLOEXEC)
                    own,other=(w,r) if name=='stdin' else (r,w)
                    os.set_blocking(own,False);parent.append(own);child.append(other)
                    setattr(self,name,os.fdopen(own,'wb' if name=='stdin' else 'rb',buffering=0));io.append(other)
                elif value==subprocess.DEVNULL:io.append(-2)
                else:io.append(value if type(value) is int else value.fileno())
            gate_r,gate_w=os.pipe2(os.O_CLOEXEC|os.O_NONBLOCK);child.append(gate_r);self._gate=gate_w
            # Child gate must block until ownership is registered.
            os.set_blocking(gate_r,True)
            argv=(ctypes.c_char_p*(len(args)+1))(*[os.fsencode(v) for v in args],None)
            items=[os.fsencode(k)+'='.encode()+os.fsencode(v) for k,v in (env or os.environ).items()]
            environment=(ctypes.c_char_p*(len(items)+1))(*items,None)
            keep=(ctypes.c_int*len(pass_fds))(*pass_fds);stdio=(ctypes.c_int*3)(*io)
            result=_LIBRARY.lvs_owned_launch(argv,environment,os.fsencode(cwd) if cwd is not None else None,
                stdio,keep,len(pass_fds),gate_r,int(start_new_session),delay_ms,int(deadline*1e9) if deadline is not None else 0,ctypes.byref(pid_slot))
            if result<0:raise OSError(ctypes.get_errno(),'Owned clone failed')
            self._creation=_CreationIdentity(pid_slot.value,pid_slot.value if start_new_session else None);self.pid=self._creation_pid;_OWNED[self._creation_pid]=self
            if owner is not None:owner.process=self
            if hasattr(os,'pidfd_open'):
                try:
                    self.pidfd=os.pidfd_open(self._creation_pid,0)
                    same=os.pidfd_open(self._creation_pid,0);other=None
                    try:
                        other=os.pidfd_open(os.getpid(),0)
                        ident=lambda fd:(os.fstat(fd).st_dev,os.fstat(fd).st_ino)
                        observed=ident(self.pidfd)
                        if observed!=ident(same) or observed==ident(other):
                            os.close(self.pidfd);self.pidfd=None
                        else:self._pidfd_identity=observed
                    finally:
                        os.close(same)
                        if other is not None:os.close(other)
                except OSError:
                    if self.pidfd is not None:os.close(self.pidfd);self.pidfd=None
                    pass  # unreaped-child identity remains mandatory below
            os.write(gate_w,b'G')
        except BaseException as exc:
            if pid_slot.value:
                self._creation=_CreationIdentity(pid_slot.value,pid_slot.value if start_new_session else None);self.pid=self._creation_pid;_OWNED[self._creation_pid]=self
                setattr(exc,'owned_process',self)
                if owner is not None:
                    try:owner.process=self
                    except Exception:pass  # preserve owned_process on the original exception
                try:self.kill()
                except OSError:pass
            for stream in (self.stdin,self.stdout,self.stderr):
                if stream is not None:stream.close()
            raise
        finally:
            for fd in child:
                try:os.close(fd)
                except OSError:pass
            if self._gate is not None:os.close(self._gate);self._gate=None

    @contextmanager
    def _exclusive(self):
        if not self._lifecycle.acquire(blocking=False):raise OSError('Owned process lifecycle busy; no ambiguous signal/reap')
        try:yield
        finally:self._lifecycle.release()

    @contextmanager
    def _pid_reference(self):
        pin=None
        try:
            if self._pidfd_identity is not None and self.pidfd is None and self.returncode is None:
                raise OSError('Owned pidfd reference lost; no numeric authority downgrade')
            if self.pidfd is not None:
                pin=os.dup(self.pidfd)
                info=os.fstat(pin)
                if (info.st_dev,info.st_ino)!=self._pidfd_identity:
                    raise OSError('Owned pidfd identity changed; signal/reap refused')
            yield pin
        finally:
            if pin is not None:os.close(pin)

    def poll(self):
        with self._exclusive(),self._pid_reference() as pin:
            if self.returncode is None:
                try:
                    if pin is not None and hasattr(os,'P_PIDFD'):
                        event=os.waitid(os.P_PIDFD,pin,os.WEXITED|os.WNOHANG)
                        pid=event.si_pid if event is not None else 0
                        status=None
                        if pid:self._returncode=event.si_status if event.si_code==os.CLD_EXITED else -event.si_status
                    else:pid,status=os.waitpid(self._creation_pid,os.WNOHANG)
                except ChildProcessError:raise OSError('Owned child reaping authority lost')
                if pid:
                    if status is not None:self._returncode=os.waitstatus_to_exitcode(status)
                    _OWNED.pop(self._creation_pid,None)
                    if self.pidfd is not None:os.close(self.pidfd);self.pidfd=None
            return self.returncode

    def confirm_native_group(self):
        """Bind the native guard's post-OWN setsid acknowledgement to the child."""
        with self._exclusive(),self._pid_reference() as pin:
            if not self._native_stage or self._returncode is not None:raise OSError('No live native bootstrap group')
            try:
                kind,ident=(os.P_PIDFD,pin) if pin is not None and hasattr(os,'P_PIDFD') else (os.P_PID,self._creation_pid)
                event=os.waitid(kind,ident,os.WEXITED|os.WNOHANG|os.WNOWAIT)
                if event is not None or os.getpgid(self._creation_pid)!=self._creation_pid:
                    raise OSError('Native group acknowledgement is not live or isolated')
            except ChildProcessError as exc:raise OSError('Native bootstrap ownership lost') from exc
            self._native_group=self._creation_pid

    def group_cleanup_confirmed(self):
        """Observation only, after primary timing. Never signal a reaped group.

        The creation group is retained independently of the diagnostic PID.
        A reused numeric group can cause conservative uncertainty, never a kill.
        """
        return self.poll() is not None and group_gone(self._creation.pid)

    def wait(self,timeout=None):
        end=time.monotonic()+timeout if timeout is not None else None
        while self.poll() is None:
            if end is not None and time.monotonic()>=end:raise subprocess.TimeoutExpired(self.args,timeout)
            time.sleep(.01)
        return self.returncode

    def send_signal(self,sig):
        with self._exclusive():
            if self.returncode is not None:return  # PID/PGID may now name someone else
            with self._pid_reference() as pin:
                # WNOWAIT proves parent ownership without releasing the child's PID.
                # All supported reaping goes through this same nonblocking exclusion.
                try:
                    kind,identity=(os.P_PIDFD,pin) if pin is not None and hasattr(os,'P_PIDFD') else (os.P_PID,self._creation_pid)
                    os.waitid(kind,identity,os.WEXITED|os.WNOHANG|os.WNOWAIT)
                except ChildProcessError:raise OSError('Owned process identity lost; signal refused')
                if pin is not None and hasattr(signal,'pidfd_send_signal'):
                    try:signal.pidfd_send_signal(pin,sig)
                    except ProcessLookupError:pass  # exited but not reaped; its group may remain
                # An unreaped child pins its numeric PID. The registered bootstrap
                # creates this PGID before release; no signal is sent after reap.
                group=self._creation.pgid if not self._native_stage else self._native_group
                if group is not None:
                    try:os.killpg(group,sig)
                    except ProcessLookupError:
                        if pin is None or not hasattr(signal,'pidfd_send_signal'):
                            try:os.kill(self._creation_pid,sig)
                            except ProcessLookupError:pass
                elif pin is None or not hasattr(signal,'pidfd_send_signal'):
                    try:os.kill(self._creation_pid,sig)
                    except ProcessLookupError:pass
    def kill(self):self.send_signal(signal.SIGKILL)
    def terminate(self):self.send_signal(signal.SIGTERM)

    def communicate(self,input=None,timeout=None):
        data=(input.encode() if isinstance(input,str) else input) or b''
        end=time.monotonic()+timeout if timeout is not None else None
        with selectors.DefaultSelector() as selector:
            for stream,events in ((self.stdin,selectors.EVENT_WRITE),(self.stdout,selectors.EVENT_READ),(self.stderr,selectors.EVENT_READ)):
                if stream is not None and not stream.closed:selector.register(stream,events)
            while selector.get_map() or self.poll() is None:
                if end is not None and time.monotonic()>=end:raise subprocess.TimeoutExpired(self.args,timeout)
                for key,events in selector.select(.02):
                    stream=key.fileobj
                    if events&selectors.EVENT_WRITE:
                        try:self._offset+=os.write(stream.fileno(),data[self._offset:self._offset+65536])
                        except BlockingIOError:continue
                        except BrokenPipeError:self._offset=len(data)
                        if self._offset>=len(data):selector.unregister(stream);stream.close()
                    else:
                        try:chunk=os.read(stream.fileno(),65536)
                        except BlockingIOError:continue
                        if not chunk:selector.unregister(stream);stream.close()
                        else:
                            target=self._out if stream is self.stdout else self._err;target.extend(chunk)
                            if len(target)>16*1024**2:raise ValueError('Owned evidence stream exceeds budget')
        output,error=bytes(self._out),bytes(self._err)
        return (output.decode(),error.decode()) if self.text else (output,error)
