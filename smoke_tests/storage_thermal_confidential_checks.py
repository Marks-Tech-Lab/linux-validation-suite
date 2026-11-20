"""Final-exec policy on regular files only; crash/debugger tests are VM-only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from Modules.lvs_storage_thermal_backend import capability,guard_command
from Modules.lvs_storage_thermal_system import postexec_witness_valid

ROOT=Path(__file__).resolve().parents[1]
VERSION=r'''
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
int main(int argc,char **argv) {
 if(argc!=2)return 2;
 if(!strcmp(argv[1],"--version")) {void *p=0;if(posix_memalign(&p,4096,4096))return 3;long n=read(0,p,4096);fprintf(stderr,"fixture_read_bytes:%ld\n",n);puts("fio-3.42");return 0;}
 if(!strcmp(argv[1],"--cmdhelp=filetype")){puts("block");return 0;}
 if(!strcmp(argv[1],"--enghelp")){puts("psync");return 0;}
 return 2;
}
'''


def build(root):
    cc=shutil.which('cc')or shutil.which('gcc');assert cc,'existing compiler required'
    guard=root/'storage_thermal_guard';hook=root/'storage_thermal_confidential.so';fio=root/'fio'
    source=root/'version.c';source.write_text(VERSION)
    for c,out,flags in [(ROOT/'native/storage_thermal_guard.c',guard,[]),(ROOT/'native/storage_thermal_confidential.c',hook,['-shared','-fPIC']),(source,fio,[])]:
        subprocess.run([cc,'-O2',str(c),'-o',str(out),*flags],check=True,capture_output=True)
    return guard,hook,fio


def run_thermal_postexec_native_checks():
    with tempfile.TemporaryDirectory()as name:
        root=Path(name);guard,hook,fio=build(root)
        a=capability(str(fio),str(guard));b=capability(str(fio),str(guard))
        assert a==b,(a,b)  # transient probe PIDs must never change readiness.
        assert a['status']=='available'and a['postexec_confidentiality']['status']=='verified',a
        source=root/'readonly';source.write_bytes(bytes(4096));fd=os.open(source,os.O_RDONLY|os.O_DIRECT);exe=os.open(fio,os.O_RDONLY)
        try:
            cmd=[str(guard),'--confidential-probe-fd',str(exe),str(os.getuid()),str(os.getgid()),'0','0','4096','4096','1','1']
            p=subprocess.run(cmd,stdin=fd,pass_fds=(exe,),capture_output=True,text=True,timeout=10)
            assert p.returncode==0 and 'fixture_read_bytes:4096'in p.stderr,p
            event=next(json.loads(line)for line in p.stderr.splitlines()if '"contract_id":"lvs.storage_thermal.postexec"'in line)
            assert postexec_witness_valid(event,os.getuid(),os.getgid(),event['pid'],dict(major=0,minor=0,size_bytes=4096))
            # Absent or unexecuted hook cannot deliver target data to main.
            preserved=root/'preserved.so';hook.rename(preserved)
            p=subprocess.run(cmd,stdin=fd,pass_fds=(exe,),capture_output=True,text=True,timeout=10)
            assert p.returncode==125 and not p.stdout
            cc=shutil.which('cc')or shutil.which('gcc');empty=root/'empty.c';empty.write_text('int unqualified_library;')
            subprocess.run([cc,'-shared','-fPIC',str(empty),'-o',str(hook)],check=True,capture_output=True)
            p=subprocess.run(cmd,stdin=fd,pass_fds=(exe,),capture_output=True,text=True,timeout=10)
            assert p.returncode==0 and 'fixture_read_bytes:0'in p.stderr and '"contract_id":"lvs.storage_thermal.postexec"'not in p.stderr
            unqualified=capability(str(fio),str(guard));assert unqualified['postexec_confidentiality']['status']=='unavailable'
            try:guard_command(str(guard),exe,backend=unqualified,uid=os.getuid(),gid=os.getgid(),major=0,minor=0,size=4096,block_size=4096,iops=1,seconds=1,confidential=True)
            except ValueError:pass
            else:raise AssertionError('unqualified postexec fallback admitted')
            # Truncated stage-confidential protocol must reject before admission.
            malformed=cmd.copy();malformed[1]='--stage-confidential-fio-fd'
            p=subprocess.run(malformed,stdin=fd,pass_fds=(exe,),capture_output=True,text=True,timeout=10)
            assert p.returncode==125 and 'invalid fixed guard protocol'in p.stderr
        finally:os.close(fd);os.close(exe)


def run_thermal_postexec_witness_checks():
    from copy import deepcopy
    event=dict(contract_id='lvs.storage_thermal.postexec',version=1,pid=123,uid=999,gid=999,dumpable=0,state_locked=True,thread_sync=True,target_deferred=True,parent=101,major=259,minor=0,size=1048576)
    identity=dict(major=259,minor=0,size_bytes=1048576)
    assert postexec_witness_valid(event,999,999,123,identity)
    for key,value in [('version',True),('pid',124),('uid',1000),('dumpable',2),('dumpable',False),('thread_sync',False),('state_locked',False),('target_deferred',False),('parent',1),('minor',False),('size',4096)]:
        bad=deepcopy(event);bad[key]=value;assert not postexec_witness_valid(bad,999,999,123,identity),(key,value)
    for key in event:
        bad=deepcopy(event);bad.pop(key);assert not postexec_witness_valid(bad,999,999,123,identity),key

    # Fixed OS aliases are supported only through trusted owners/ancestors.
    import stat
    from types import SimpleNamespace
    from unittest.mock import patch
    from scripts import storage_thermal_install as installer
    d=lambda uid=0,mode=0o755:SimpleNamespace(st_uid=uid,st_mode=stat.S_IFDIR|mode)
    link=lambda uid=0:SimpleNamespace(st_uid=uid,st_mode=stat.S_IFLNK|0o777)
    tree={'/alias':link(),'/safe':d(),'/safe/base':d()}
    def info(path):
        if str(path)not in tree:raise FileNotFoundError(path)
        return tree[str(path)]
    with patch.object(installer,'trusted'),patch.object(installer.os,'lstat',side_effect=info),patch.object(installer.os,'readlink',return_value='/safe'):
        assert installer.canonical_directory('/alias/base')==Path('/safe/base')
        assert installer.canonical_directory('/alias/new',allow_missing=True)==Path('/safe/new')
        for key,bad in [('/alias',link(1000)),('/safe',d(mode=0o777)),('/safe',d(uid=1000))]:
            good=tree[key];tree[key]=bad
            try:installer.canonical_directory('/alias/base')
            except ValueError:pass
            else:raise AssertionError('unsafe OS alias accepted')
            tree[key]=good
