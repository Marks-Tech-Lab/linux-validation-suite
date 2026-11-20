"""Sealed-VM post-exec privacy positive/negative controls; no host entrypoint."""
from pathlib import Path
import ctypes
import errno
import json
import os
import signal
import subprocess
import time

HELPER=r'''
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
static void *thread(void *p) {*(int*)p=prctl(PR_GET_DUMPABLE);return 0;}
int main(void) {
 void *buffer=0;if(posix_memalign(&buffer,4096,4096))return 2;
 ssize_t n=read(0,buffer,4096);
 int dump=prctl(PR_GET_DUMPABLE),locked=0,tid=-1,child=-1;
#ifndef CONTROL
 errno=0;locked=(prctl(PR_SET_DUMPABLE,1L,0L,0L,0L)==-1 && errno==EPERM);
 errno=0;locked &= syscall(SYS_execve,"/nonexistent",NULL,NULL)==-1 && errno==EPERM;
 errno=0;locked &= syscall(SYS_setresuid,getuid(),getuid(),getuid())==-1 && errno==EPERM;
 pthread_t t;if(pthread_create(&t,NULL,thread,&tid))return 3;pthread_join(t,NULL);
 pid_t p=fork();if(p==0)_exit(prctl(PR_GET_DUMPABLE));int status=0;if(waitpid(p,&status,0)!=p)return 4;child=WEXITSTATUS(status);
#endif
 printf("{\"pid\":%ld,\"address\":%llu,\"read_bytes\":%ld,\"dumpable\":%d,\"locked\":%d,\"thread_dumpable\":%d,\"child_dumpable\":%d}\n",(long)getpid(),(unsigned long long)(uintptr_t)buffer,(long)n,dump,locked,tid,child);fflush(stdout);
 for(;;)pause();
}
'''


def build(root,tools,compiler):
    source=tools/'confidential-fixture.c';source.write_text(HELPER)
    result=[]
    for name,flags in [('confidential-fixture',[]),('confidential-control',['-DCONTROL'])]:
        binary=tools/name;subprocess.run([compiler,'-O2','-pthread',str(source),'-o',str(binary),*flags],check=True)
        result.append((binary,'/bin/'+name))
    return result


def attacker(directory,guard,helper,uid,protected,deny_init=False):
    """Same-UID PARENT tracer: positive control avoids Yama ancestry ambiguity."""
    import resource,select
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    fd=os.open('/privacy-fixture',os.O_RDONLY|os.O_DIRECT);exe=os.open(helper,os.O_RDONLY)
    command=[str(guard),'--confidential-probe-fd',str(exe),str(uid),str(uid),'0','0','4096','4096','1','1']if protected else[helper]
    def block_init():
        # Private VM child filter: deny only PR_SET_DUMPABLE, proving failure
        # before dequeue/main. No host/core configuration is involved.
        class Filter(ctypes.Structure):_fields_=[('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),('jf',ctypes.c_ubyte),('k',ctypes.c_uint)]
        class Program(ctypes.Structure):_fields_=[('len',ctypes.c_ushort),('filter',ctypes.POINTER(Filter))]
        # VM x86-64 prctl=157. This fixture is never an installed worker.
        filters=(Filter*6)(Filter(0x20,0,0,0),Filter(0x15,0,3,317 if deny_init=='sync' else 157),Filter(0x20,0,0,16),Filter(0x15,0,1,1 if deny_init=='sync' else 4),Filter(0x06,0,0,0x50000|errno.EPERM),Filter(0x06,0,0,0x7fff0000))
        libc=ctypes.CDLL(None);assert libc.prctl(38,1,0,0,0)==0;assert libc.prctl(22,2,ctypes.byref(Program(6,filters)))==0
    p=subprocess.Popen(command,stdin=fd,pass_fds=(exe,)if protected else(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=dict(PATH='/bin:/usr/bin',LC_ALL='C'),preexec_fn=block_init if deny_init else None)
    os.close(fd);os.close(exe)
    try:
        if deny_init:
            out,err=p.communicate(timeout=10);assert p.returncode==125 and not out and b'postexec_failure_line'in err
            return dict(initialization_failure_closed=True)
        assert select.select([p.stdout],[],[],10)[0],'fixture did not reach main'
        row=json.loads(p.stdout.readline());assert row['pid']==p.pid and row['read_bytes']==4096,row
        libc=ctypes.CDLL(None,use_errno=True)
        class Iovec(ctypes.Structure):_fields_=[('base',ctypes.c_void_p),('length',ctypes.c_size_t)]
        value=ctypes.c_char();local=Iovec(ctypes.addressof(value),1);remote=Iovec(row['address'],1)
        result=libc.process_vm_readv(p.pid,ctypes.byref(local),1,ctypes.byref(remote),1,0);read_error=ctypes.get_errno()
        trace=libc.ptrace(16,p.pid,None,None);trace_error=ctypes.get_errno()
        if protected:
            assert row['dumpable']==0 and row['locked']==1 and row['thread_dumpable']==0 and row['child_dumpable']==0,row
            assert trace==-1 and trace_error==errno.EPERM and result==-1 and read_error==errno.EPERM
            for path in (f'/proc/{p.pid}/mem',f'/proc/{p.pid}/fd/0'):
                try:f=os.open(path,os.O_RDONLY)
                except PermissionError:pass
                else:os.close(f);raise AssertionError('confidential memory/descriptor exposed')
        else:
            assert row['dumpable']==1 and result==1 and trace==0,row
            os.waitpid(p.pid,os.WUNTRACED);assert libc.ptrace(17,p.pid,None,None)==0
        p.send_signal(signal.SIGABRT);p.wait(timeout=12);assert p.returncode==-signal.SIGABRT
        # Addresses and contents are not retained in exported evidence.
        return dict(pid=p.pid,read_bytes=row['read_bytes'],dumpable=row['dumpable'],same_uid_parent_debugger_denied=protected,same_uid_parent_memory_denied=protected,thread_and_fork_locked=protected,core_limit_zero=True)
    finally:
        if p.poll()is None:p.kill();p.wait(timeout=5)
        p.stdout.close();p.stderr.close()


def run(deployment):
    assert os.getuid()==0 and 'QEMU'in Path('/sys/class/dmi/id/sys_vendor').read_text()and'lvs_fixture='in Path('/proc/cmdline').read_text()
    assert Path('/proc/sys/fs/suid_dumpable').read_text().strip()=='2'
    fixture=Path('/privacy-fixture');fixture.write_bytes(b'private disposable fixture marker'.ljust(4096,b'X'));fixture.chmod(0o644)
    directory=Path('/var/tmp/privacy-fixture');directory.mkdir();os.chown(directory,65533,65533);directory.chmod(0o700)
    guard=deployment/'runtime/build/storage_thermal_guard';result={}
    for name,protected,deny in [('positive',False,False),('protected',True,False),('initialization-failure',True,True),('synchronization-failure',True,'sync')]:
        marker=Path('/control/core-invoked');marker.unlink(missing_ok=True)
        child=os.fork()
        if child==0:
            try:
                os.setgroups([]);os.setgid(65533);os.setuid(65533)
                value=attacker(directory,guard,'/bin/confidential-fixture'if protected else'/bin/confidential-control',65533,protected,deny)
                (directory/(name+'.json')).write_text(json.dumps(value));os._exit(0)
            except BaseException:
                import traceback;traceback.print_exc();os._exit(1)
        _,status=os.waitpid(child,0);assert os.waitstatus_to_exitcode(status)==0,name
        value=json.loads((directory/(name+'.json')).read_text());end=time.monotonic()+3
        if name=='positive':
            while not marker.exists()and time.monotonic()<end:time.sleep(.05)
            assert marker.exists(),'piped core positive control not observed'
        else:
            time.sleep(.5);assert not marker.exists(),'protected process generated core'
        result[name]=value
    result['piped_core_positive_observed']=True;result['protected_core_absent']=True
    return result
