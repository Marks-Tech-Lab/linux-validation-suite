"""Unprivileged, offline preparation of a reviewable non-target execution bundle.

Does not elevate, install packages, access devices or execute a workload. Promotion
is an explicit operator action with ordinary OS tools and an approved manifest hash.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]

LAUNCHER='''"""Execute only a separately reviewed, root-owned offline LVS bundle."""
import hashlib,json,os,pathlib,runpy,stat,sys
root=pathlib.Path(__file__).resolve().parent
if os.getuid()!=0:raise SystemExit('Use the separately approved sudo workflow; no automatic elevation')
if set(sys.argv[1:])-{'--check','--plan'} or len(sys.argv)>2:raise SystemExit('Only interactive, --check or --plan is supported')
for p in (root,*root.parents):
 s=p.lstat()
 if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise SystemExit('Unsafe deployment parent')
state=pathlib.Path('/var/lib/lvs-thermal')
for p in (state,*state.parents):
 s=p.lstat()
 if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise SystemExit('Unsafe canonical state directory')
manifest=root/'manifest.json'
for p in (manifest,root/'SHA256SUMS'):
 s=p.lstat()
 if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise SystemExit('Unsafe manifest')
m=json.loads(manifest.read_text())
actual=set()
for p in root.rglob('*'):
 s=p.lstat()
 if not (stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode)) or s.st_uid!=0 or s.st_mode&0o022:raise SystemExit('Unsafe bundle entry')
 if p.is_file():actual.add(str(p.relative_to(root)))
if actual!=set(m['files'])|{'manifest.json','SHA256SUMS'}:raise SystemExit('Unexpected bundle files (including bytecode)')
if m.get('contract')!='lvs.storage_thermal.offline_bundle.v1' or any(type(m[k]) is not int or not 1<=m[k]<=2**32-2 for k in ('uid','gid')):raise SystemExit('Invalid operator identity')
for rel,digest in m['files'].items():
 p=root/rel
 if pathlib.Path(rel).is_absolute() or '..' in pathlib.Path(rel).parts:raise SystemExit('Unsafe bundle path')
 for ancestor in p.parents:
  if ancestor==root:break
  s=ancestor.lstat()
  if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise SystemExit('Unsafe bundle directory')
 s=p.lstat()
 if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022 or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise SystemExit('Bundle changed: '+rel)
os.environ.clear();os.environ.update(PATH='/usr/bin:/bin',HOME='/root',LC_ALL='C',PYTHONDONTWRITEBYTECODE='1')
sys.dont_write_bytecode=True;sys.path.insert(0,str(root/'runtime'))
from Modules.lvs_source_provenance import _source_snapshot
if _source_snapshot(root/'runtime')[0]!=m['source']:raise SystemExit('Execution-source mismatch')
sys.argv=['lvs_storage_thermal_assist.py',*sys.argv[1:],'--fio',str(root/'runtime/build/fio'),'--guard',str(root/'runtime/build/storage_thermal_guard'),'--run-as',str(m['uid'])+':'+str(m['gid']),'--output-root','/var/lib/lvs-thermal/results','--access-mode','shared_readonly_opt_in','--aggregate-iops-limit','128','--aggregate-bps-limit','8388608']
import lvs_storage_thermal_assist as app
raise SystemExit(app.main(recovery_marker=pathlib.Path('/var/lib/lvs-thermal/storage_thermal_recovery_required.json')))
'''


def prepare(destination: Path, fio: Path, *, root=ROOT):
    from Modules.lvs_source_provenance import _source_snapshot
    from Modules.lvs_native_helpers import find_c_compiler,native_helper_build_command
    from Modules.lvs_storage_thermal_backend import capability
    if os.getuid()==0:raise ValueError('Prepare as the ordinary operator; promotion is separate')
    if fio.is_symlink() or not fio.is_file():raise ValueError('Explicit regular qualified fio executable required')
    from Modules.lvs_storage_thermal_recovery import blocker
    if blocker(root/'build/storage_thermal_recovery_required.json'):raise ValueError('Source recovery scope unresolved; do not bypass it through deployment')
    source,content=_source_snapshot(root)
    if source['status']!='complete':raise ValueError('Incomplete execution source')
    destination=Path(destination)
    destination.mkdir(mode=0o700,parents=False,exist_ok=False)
    runtime=destination/'runtime';runtime.mkdir()
    for name,hashes in content.items():
        src=root/name;dst=runtime/name;dst.parent.mkdir(parents=True,exist_ok=True)
        if src.is_symlink() or hashlib.sha256(src.read_bytes()).hexdigest()!=hashes[0]:raise ValueError('Source changed')
        shutil.copyfile(src,dst);dst.chmod(0o644)
    if _source_snapshot(runtime)[0]!=source:raise ValueError('Copied execution source mismatch')
    observer=runtime/'scripts/storage_thermal_acceptance.py'
    observer.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(root/'scripts/storage_thermal_acceptance.py',observer);observer.chmod(0o644)
    build=runtime/'build';build.mkdir();compiler=find_c_compiler()
    if not compiler:raise ValueError('Existing C compiler required; nothing is installed automatically')
    for name,output,flags in [('storage_thermal_guard.c','storage_thermal_guard',[]),('storage_thermal_launch.c','storage_thermal_launch.so',['-shared','-fPIC'])]:
        subprocess.run(native_helper_build_command(compiler,runtime/'native'/name,build/output)+flags,check=True,capture_output=True,timeout=60)
    shutil.copyfile(fio,build/'fio');(build/'fio').chmod(0o755)
    observed=capability(str(build/'fio'),str(build/'storage_thermal_guard'))
    if observed['status']!='available':raise ValueError('Qualified fio/guard required: '+str(observed['reasons']))
    (destination/'launch.py').write_text(LAUNCHER)
    files={str(p.relative_to(destination)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(destination.rglob('*')) if p.is_file()}
    manifest=dict(contract='lvs.storage_thermal.offline_bundle.v1',source=source,uid=os.getuid(),gid=os.getgid(),files=files,backend=observed)
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    files['manifest.json']=hashlib.sha256((destination/'manifest.json').read_bytes()).hexdigest()
    (destination/'SHA256SUMS').write_text(''.join(h+'  '+n+'\n' for n,h in sorted(files.items())))
    return dict(directory=str(destination),source=source,manifest_sha256=files['manifest.json'],checksums_sha256=hashlib.sha256((destination/'SHA256SUMS').read_bytes()).hexdigest())


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--destination',type=Path,required=True);parser.add_argument('--fio',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(prepare(args.destination,args.fio),indent=2))

if __name__=='__main__':main()
