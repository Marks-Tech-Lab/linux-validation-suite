#!/usr/bin/env python3
"""Standalone Storage Thermal Assist. No CPU/GPU stage or saved-profile changes."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import time

from Modules.lvs_environment_ui import EnvironmentScreens
from Modules.lvs_native_helpers import find_c_compiler, native_helper_build_command
from Modules.lvs_storage_thermal import ThermalConfig, GROUPS
from Modules.lvs_storage_thermal_runner import ThermalRunner, approve_unmonitored
from Modules.lvs_storage_thermal_targets import selected

ROOT=Path(__file__).resolve().parent


def drive_lines(rows):
    return [f"{i}. {r['model']} | {r['device_id']} | {r['transport']} / {r['drive_class']}"
            f"{' [SYSTEM: blocked]' if r['system_drive'] else ' [TOPOLOGY INCOMPLETE: blocked]' if r.get('classification_status')=='incomplete' else ''}\n   "
            + ('Eligible candidate under selected access contract' if r['eligible'] else 'Blocked: '+'; '.join(r['reasons']))
            for i,r in enumerate(rows,1)]


def plan_lines(plan):
    lines=[f"Readiness: {plan['status']}; backend: {plan['backend']['status']}",
           '50%/25% refers to provisional activity limits, not rated performance or guaranteed heating.']
    if plan['configuration'].get('access_mode','exclusive')!='exclusive':
        lines.insert(1,'EXPERIMENTAL shared read-only: physical acceptance pending; kernel/background/initialization I/O is outside fio limits.')
    if plan['configuration'].get('access_mode','exclusive')!='exclusive':
        rates=[d['rate'] for d in plan['devices'] if d['state']=='ready']
        lines.append(f"Aggregate fio plan: {sum(r['effective_iops'] for r in rates)}/{plan['configuration']['aggregate_iops_limit']} IOPS; {sum(r['effective_bps'] for r in rates)}/{plan['configuration']['aggregate_bps_limit']} B/s.")
    for d in plan['devices']:
        if not d['selected']:continue
        rate=d['rate'];lines.append(f"{d['device_id']}: {d['state']}; "
            f"{rate.get('requested_percent')}% -> {rate.get('effective_iops')} IOPS / {rate.get('effective_bps')} B/s; "
            + '; '.join(d['reasons']))
    lines.extend(plan['backend'].get('reasons',[]))
    lines.append(f"Duration per started drive: {plan['configuration']['duration_seconds']} s; staggered startup, ordinary scheduling, no reserved cores.")
    return lines


def build_guard():
    compiler=find_c_compiler()
    if not compiler:raise ValueError('No C compiler found; install/provide one separately. No system packages are installed here.')
    directory=ROOT/'build';directory.mkdir(exist_ok=True)
    if directory.is_symlink():raise ValueError('build directory must not be a symlink')
    destination=directory/'storage_thermal_guard'
    if destination.is_symlink():raise ValueError('guard destination must not be a symlink')
    temporary=directory/f'.storage_thermal_guard.{os.getpid()}'
    try:
        subprocess.run(native_helper_build_command(compiler,ROOT/'native/storage_thermal_guard.c',temporary),
                       check=True,capture_output=True,text=True,timeout=60)
        os.replace(temporary,destination)
    finally:temporary.unlink(missing_ok=True)
    return destination


class ThermalMenu:
    def __init__(self,runner,config,output_root,screens=None,*,recovery_marker=None):
        self.runner,self.config,self.output_root=runner,config,Path(output_root)
        self.ui=screens or EnvironmentScreens();self.last_print=0;self.cancel_input=''
        self.closed=False
        self.recovery_marker=Path(recovery_marker) if recovery_marker is not None else ROOT/'build/storage_thermal_recovery_required.json'

    def results(self,*args):
        self.closed=self.ui.results(*args)=='exit'

    def number(self,prompt,low,high,default):
        raw=self.ui.ask(f'{prompt} [{default}]: ').strip()
        value=default if not raw else int(raw)
        if not low<=value<=high:raise ValueError(f'Choose {low}–{high}')
        return value

    def advanced(self):
        self.ui.write('1. Read size\n2. Advanced IOPS/bandwidth\n3. Temperature policy\n4. Per-drive intensity\n5. Build native guard\n6. Access contract and aggregate budgets\n0. Back')
        choice=self.ui.ask('Choose [0]: ').strip() or '0'
        if choice=='1':self.config=replace(self.config,block_size=self.number('Read size in bytes (power of two)',4096,1048576,self.config.block_size))
        elif choice=='2':
            self.ui.write('1. Percentage mode\n2. Advanced rates\n0. Back')
            mode=self.ui.ask('Choose [0]: ').strip()
            if mode=='1':self.config=replace(self.config,rate_mode='percent',iops=None,bandwidth_bytes_per_second=None)
            elif mode=='2':
                rate=self.number('Requested IOPS (still limited by pilot ceiling)',1,1000000,15)
                bandwidth=self.number('Bandwidth cap in bytes/s',1,2**40,2*1024**2)
                self.config=replace(self.config,rate_mode='advanced',iops=rate,bandwidth_bytes_per_second=bandwidth)
        elif choice=='3':
            self.ui.write('1. Require reliable temperature monitoring\n2. Bounded unmonitored approval at start\n0. Back')
            mode=self.ui.ask('Choose [0]: ').strip()
            if mode in ('1','2'):
                raw=self.ui.ask('Stop temperature C (Enter: use hardware critical limit if available): ').strip()
                stop=float(raw) if raw else None
                self.config=replace(self.config,monitoring='required' if mode=='1' else 'approved_unmonitored',
                                    unmonitored_approval='' if mode=='1' else 'pending explicit run confirmation',temperature_limit_c=stop)
        elif choice=='4':
            rows=self.runner.discover(self.config);self.ui.write('\n'.join(drive_lines(rows)))
            index=self.number('Drive number (0 returns)',0,len(rows),0)
            if index:
                value=self.number('Override activity percent',0,100,50)
                self.config=replace(self.config,per_device_percent={**self.config.per_device_percent,rows[index-1]['device_id']:value})
        elif choice=='6':
            self.ui.write('1. Exclusive inactive-HDD contract (default)\n2. Experimental shared read-only internal data drives\nShared permits kernel/background writes and delayed kernel completion; fio budgets do not cap OS/startup I/O. Required monitoring; system/complex/external paths remain blocked.')
            mode=self.ui.ask('Access contract [0 returns]: ').strip()
            if mode=='1':self.config=replace(self.config,access_mode='exclusive')
            elif mode=='2':
                iops=self.number('Aggregate fio IOPS budget (one-drive starting example: 128)',1,2**40,self.config.aggregate_iops_limit or 128)
                bps=self.number('Aggregate fio bytes/s budget (8 MiB/s = 8388608)',1,2**40,self.config.aggregate_bps_limit or 8388608)
                self.config=replace(self.config,access_mode='shared_readonly_opt_in',aggregate_iops_limit=iops,
                                    aggregate_bps_limit=bps,monitoring='required',unmonitored_approval='')
        elif choice=='5':
            if self.ui.confirm('Build the optional guard from local source; existing CPU/memory helpers are preserved.','Build native guard'):
                path=build_guard();self.runner.guard=str(path)
                self.results('Guard built',[str(path)])

    def controls(self,jobs):
        try:
            if not self.ui.stdin.isatty() or not select.select([self.ui.stdin],[],[],0)[0]:return []
            value=self.ui.stdin.readline()
            if not value:return ['all']
            value=value.strip().lower()
            if value in ('0','q','stop'):return ['all']
            if value in ('e','emergency'):return ['emergency']
            if value.startswith('s '):
                index=int(value[2:]);return [jobs[index-1]['row']['device_id']] if 1<=index<=len(jobs) else []
        except (ValueError,OSError):pass
        return []

    def observe(self,jobs):
        if time.monotonic()-self.last_print<5:return
        self.last_print=time.monotonic()
        for j in jobs:
            r=j['result'];reading=j.get('last_snapshot',{}).get('temperature',{})
            sample=j.get('last_snapshot',{})
            self.ui.write(f"Drive {j['index']}: {r.device_id} | {'finished' if j.get('done') else 'active'} | "
                          f"temperature {reading.get('value_c','unavailable')} C | requested {r.effective_rate.get('effective_iops')} IOPS | "
                          f"observed device reads {sample.get('device_read_ios_since_launch','unavailable')}")

    def start(self):
        config=self.config
        if config.monitoring=='approved_unmonitored':
            ids=[r['device_id'] for r in self.runner.discover(self.config) if selected(r,config)]
            config=approve_unmonitored(config,ids,'pending operator confirmation')
        plan=self.runner.inspect(config);self.ui.write('\n'.join(plan_lines(plan)))
        if plan['status']!='READY':
            # Persist blocked attempts, with no worker or false execution PASS.
            from Modules.lvs_profile_report_artifacts import atomic_preflight_json
            from uuid import uuid4
            path=self.output_root/f'Storage_Thermal_Assist_Blocked_{uuid4().hex[:8]}'/'effective_preflight.json'
            atomic_preflight_json(path,plan)
            self.results('No workload started',['Resolve the listed blockers, then preview again.',f'Readiness saved: {path}'],json.dumps(plan,indent=2));return
        note=('Unmonitored operation: no verified thermal margins; approval is for this exact duration/selection only.\n'
              if config.monitoring=='approved_unmonitored' else '')
        if not self.ui.confirm(note+'Run only the listed eligible HDDs; blocked devices will not execute. No workload write requests or permission changes. Shared opt-in permits background/induced kernel writes and delayed read completion; fio limits do not bound initialization or OS traffic.',
                               'Start the displayed read-only workload'):
            return
        if config.monitoring=='approved_unmonitored':
            config=approve_unmonitored(config,plan['selected_devices'],'operator explicitly approved this standalone run')
            updated=self.runner.inspect(config)
            if (updated['runnable_devices']!=plan['runnable_devices']
                    or [r['identity'] for r in updated['targets']] != [r['identity'] for r in plan['targets']]):
                raise ValueError('drive selection/identity changed during confirmation; preview again')
            plan=updated
        self.ui.write('During activity: 0 + Enter stops all; s NUMBER + Enter stops one drive; e + Enter is emergency stop. Ctrl-C also stops the run.')
        from Modules.lvs_storage_thermal_launch import prepare
        prepare()  # standalone setup, before any target claim or activity
        # Standalone and profile entrypoints share one durable ownership scope.
        from Modules.lvs_storage_thermal_recovery import RecoveryScope
        self.runner.targets.output_safe(self.recovery_marker.parent,[r for r in plan['targets'] if r['state']=='ready'])
        scope=RecoveryScope(self.recovery_marker).enter(evidence_directory=self.output_root)
        try:
            directory,result=self.runner.run(config,plan,self.output_root,allow_partial=True,control=self.controls,observe=self.observe)
            if (not self.runner.unconfirmed and result.get('parent_finalization_complete') is True
                    and all(d.get('cleanup_confirmed') and d.get('terminal_published') for d in result.get('devices',[]))):
                scope.resolve(cleanup_confirmed=True)
        finally:scope.close()
        self.results('Run finished',self.runner.summary(result).splitlines()+[f'Results: {directory}'],json.dumps(result,indent=2))

    def run(self):
        while not self.closed:
            try:
                self.ui.open('LVS Storage Thermal Assist')
                self.ui.write('Guarded provisional read activity; access contract is selected in configuration. System/array paths remain blocked.\n'
                              '1. Check drives and eligibility\n2. Choose drive group or individual drives\n'
                              '3. Set ordinary/system activity\n4. Set duration\n5. Advanced options\n'
                              '6. Preview execution plan\n7. Confirm and start\n8. Exit')
                choice=self.ui.ask('Choose [8]: ').strip() or '8'
                if choice=='8':return
                if choice=='1':
                    rows=self.runner.discover(self.config);self.results('Available drives',drive_lines(rows) or ['No devices discovered.'],json.dumps(rows,indent=2))
                elif choice=='2':
                    labels=['All Eligible Internal Drives','SATA/SAS','NVMe','HDD','SSD','Individual drives']
                    self.ui.write('\n'.join(f'{i}. {label}' for i,label in enumerate(labels,1))+'\n0. Back')
                    index=self.number('Group',0,6,0)
                    if index:
                        ids=()
                        if index==6:
                            rows=self.runner.discover(self.config);self.ui.write('\n'.join(drive_lines(rows)))
                            raw=self.ui.ask('Drive numbers separated by commas (Enter cancels): ').strip()
                            if not raw:continue
                            indices=[int(v.strip()) for v in raw.split(',')]
                            if not all(1<=i<=len(rows) for i in indices):raise ValueError('Invalid drive number')
                            ids=tuple(rows[i-1]['device_id'] for i in indices)
                        self.config=replace(self.config,selection=GROUPS[index-1],device_ids=ids)
                elif choice=='3':
                    ordinary=self.number('Ordinary drive activity percent',0,100,self.config.intensity_percent)
                    system=self.number('System drive intent percent (execution remains blocked)',0,100,self.config.system_intensity_percent)
                    self.config=replace(self.config,intensity_percent=ordinary,system_intensity_percent=system)
                elif choice=='4':self.config=replace(self.config,duration_seconds=self.number('Seconds per started drive',1,86400,self.config.duration_seconds))
                elif choice=='5':self.advanced()
                elif choice=='6':
                    self.ui.write('Temperature readiness reads may access or wake selected drives; --check is passive inventory only.')
                    p=self.runner.inspect(self.config);self.results('Execution plan',plan_lines(p),json.dumps(p,indent=2))
                elif choice=='7':self.start()
                else:self.ui.write('Choose a listed number.')
            except (EOFError,KeyboardInterrupt):self.ui.write('\nCancelled; no new workload started.');return
            except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
                self.results('Operation did not complete',[str(error),f"Evidence location: {getattr(self.runner,'last_output','no execution folder created')}"])


def main(argv=None, *, recovery_marker=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true',help='passive inventory JSON only; no drive reads/workload')
    parser.add_argument('--plan',action='store_true',help='JSON readiness, including temperature reads which may access/wake drives; no workload')
    parser.add_argument('--access-mode',choices=('exclusive','shared_readonly_opt_in'),help='explicit access contract; shared requires both aggregate budgets and reliable monitoring')
    parser.add_argument('--aggregate-iops-limit',type=int,help='aggregate fio-request IOPS budget, not OS/initialization I/O')
    parser.add_argument('--aggregate-bps-limit',type=int,help='aggregate fio-request bytes/s budget')
    parser.add_argument('--config',type=Path,help='version-1 standalone configuration JSON; no saved profile is changed')
    parser.add_argument('--fio',default=shutil.which('fio') or '/nonexistent/fio')
    parser.add_argument('--guard',default=str(ROOT/'build/storage_thermal_guard'))
    parser.add_argument('--run-as',help='explicit non-root UID:GID when manually invoked as root; never elevates privileges')
    parser.add_argument('--output-root',type=Path,default=ROOT/'results')
    parser.add_argument('--build-guard',action='store_true',help='explicitly compile the optional local guard and exit')
    args=parser.parse_args(argv)
    if args.build_guard:print(build_guard());return 0
    uid=gid=None
    if args.run_as:
        try:uid,gid=map(int,args.run_as.split(':'))
        except ValueError:parser.error('--run-as requires UID:GID')
    runner=ThermalRunner(args.fio,args.guard,uid=uid,gid=gid)
    config=ThermalConfig(**json.loads(args.config.read_text())) if args.config else ThermalConfig()
    updates={name:getattr(args,name) for name in ('access_mode','aggregate_iops_limit','aggregate_bps_limit') if getattr(args,name) is not None}
    if updates:config=replace(config,**updates)
    if args.check:print(json.dumps(runner.discover(config),indent=2));return 0
    if args.plan:print(json.dumps(runner.inspect(config),indent=2));return 0
    if not sys.stdin.isatty():parser.error('interactive terminal required; use --check or --plan for plain JSON diagnostics')
    ThermalMenu(runner,config,args.output_root,recovery_marker=recovery_marker).run();return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        print(f'Storage Thermal Assist: {error}',file=sys.stderr);raise SystemExit(1)
