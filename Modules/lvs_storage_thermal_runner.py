"""Standalone guarded duration supervisor; no profile or CPU/GPU stage integration."""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import time
from uuid import uuid4

from .lvs_storage_thermal import ThermalConfig, ThermalDevice, ThermalResult, pilot_rate, readiness, result_successful
from .lvs_storage_thermal_backend import capability, guard_command, guard_environment, executable_identity
from .lvs_storage_thermal_launch import OwnedProcess, group_gone
from .lvs_storage_thermal_targets import ThermalTargets, selected, temperature
from .lvs_profile_report_artifacts import atomic_preflight_json
from .lvs_source_provenance import collect_source_provenance
from .lvs_system_memory_budget import system_memory_budget_bytes


def approval_digest(config):
    data=config.to_dict();data['unmonitored_approval']=''
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()


def approve_unmonitored(config, device_ids, note, now=None):
    """Called only after explicit human approval of this exact bounded run."""
    if not note.strip():raise ValueError('approval requires a reason')
    window=config.duration_seconds+len(device_ids)*.2+10
    record=dict(note=note,config_digest=approval_digest(config),targets=sorted(device_ids),
                maximum_seconds=config.duration_seconds,expires_unix=(time.time() if now is None else now)+window)
    return replace(config,unmonitored_approval=json.dumps(record,sort_keys=True))


def approval_valid(config, device_ids, now=None):
    try:
        value=json.loads(config.unmonitored_approval)
        return (value['config_digest']==approval_digest(config) and value['targets']==sorted(device_ids)
                and type(value['maximum_seconds']) is int and value['maximum_seconds']==config.duration_seconds
                and 0<float(value['expires_unix'])-(time.time() if now is None else now)<=config.duration_seconds+len(device_ids)*.2+10)
    except (ValueError,KeyError,TypeError):return False


def resources():
    try:
        info={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemTotal:','MemAvailable:'))}
        budget=system_memory_budget_bytes(info['MemTotal'],info['MemAvailable'])
        return dict(memory_available=budget['system_memory_available_bytes'],memory_budget=budget['system_memory_budget_bytes'],
                    fd_limit=resource.getrlimit(resource.RLIMIT_NOFILE)[0])
    except (OSError,ValueError,KeyError):return dict(memory_available=0,memory_budget=0,fd_limit=0)


def limits(config, reading):
    stop=[v for v in (config.temperature_limit_c,reading.get('critical_c')) if v is not None]
    warning=[v for v in (config.temperature_warning_c,reading.get('warning_c')) if v is not None]
    effective=min(stop) if stop else None
    return effective,min(warning) if warning else effective-5 if effective is not None else None


def disk_activity(proc=Path('/proc')):
    result={}
    try:
        for row in (proc/'diskstats').read_text().splitlines():
            f=row.split()
            if len(f)>=14:
                values=list(map(int,f[3:]));result[(int(f[0]),int(f[1]))]=values
    except (OSError,ValueError):return {}
    return result


def process_observation(pid):
    try:
        fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
        return dict(cpu_seconds=(int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK'),
                    rss_bytes=int(fields[21])*os.sysconf('SC_PAGE_SIZE'),start_ticks=int(fields[19]))
    except (OSError,ValueError,IndexError):return dict(status='unavailable')


class ThermalRunner:
    def __init__(self, fio, guard, *, targets=None, uid=None, gid=None,
                 clock=time.monotonic, sleep=time.sleep, popen=subprocess.Popen,
                 publish=atomic_preflight_json, source=collect_source_provenance,
                 budget=resources, temperature_reader=temperature, activity=disk_activity):
        self.fio,self.guard=str(fio),str(guard)
        self.targets=targets or ThermalTargets()
        self.uid=os.getuid() if uid is None else uid;self.gid=os.getgid() if gid is None else gid
        self.clock,self.sleep,self.popen,self.publish,self.source=clock,sleep,popen,publish,source
        self.budget,self.temperature,self.activity=budget,temperature_reader,activity
        self.native_processes=None
        self.unconfirmed=[]  # retain exclusive descriptors if cleanup cannot be proven

    def discover(self,config):
        return self.targets.discover(access_mode=config.access_mode) if config.access_mode!='exclusive' else self.targets.discover()

    def _process(self,p):
        return self.native_processes.authority(p) if self.native_processes is not None else p

    def _process_pid(self,p):
        p=self._process(p)
        return p.authority_pid if self.native_processes is not None or isinstance(p,OwnedProcess) else p.pid

    def _signal_process(self,p,sig):
        p=self._process(p)
        if self.native_processes is not None or isinstance(p,OwnedProcess):p.send_signal(sig)
        else:os.killpg(p.pid,sig)  # established standalone process policy

    def _clean_process(self,p):
        p=self._process(p)
        if self.native_processes is not None or isinstance(p,OwnedProcess):return p.group_cleanup_confirmed()
        return p.poll() is not None and group_gone(p.pid)

    def inspect(self,config):
        rows=self.discover(config);backend=capability(self.fio,self.guard,uid=self.uid,gid=self.gid)
        return self.plan(config,rows,backend)

    def plan(self,config,rows,backend):
        ThermalConfig(**config.to_dict())
        if config.access_mode!='exclusive':
            backend=dict(backend,active_storage_supported=True,system_storage_supported=False,physical_acceptance=False,shared_access='experimental_opt_in')
        ids=list(config.device_ids) if config.selection=='individual' else [r['device_id'] for r in rows if selected(r,config)]
        approved=approval_valid(config,ids)
        devices=[];planned=[]
        for row in rows:
            chosen=selected(row,config);why=list(row['reasons']);rate={};reading={}
            if chosen:
                if backend.get('status')!='available':why+=backend.get('reasons') or ['backend unavailable']
                try:
                    rate=pilot_rate(config,row['device_id'],row['drive_class'],system=row['system_drive'])
                    if config.block_size % row['identity']['logical_sector']:why.append('read size not aligned to the device')
                except (ValueError,ZeroDivisionError):why.append('unknown class, alignment or unsupported rate')
                if row['eligible']:
                    reading=self.temperature(row);stop,_=limits(config,reading)
                    if reading.get('value_c') is not None and (stop is not None and reading['value_c']>=stop
                            or reading.get('low_critical_c') is not None and reading['value_c']<=reading['low_critical_c']):
                        why.append('temperature already at/above stop limit')
                    if config.monitoring=='required' and (not reading.get('complete') or stop is None):
                        why.append('reliable temperature and stop threshold required')
                    if config.monitoring=='approved_unmonitored' and not approved:
                        why.append('exact target/configuration/duration unmonitored approval required')
            state='discovered' if not chosen else 'blocked' if why else 'skipped' if rate.get('effective_iops')==0 else 'ready'
            d=ThermalDevice(row['device_id'],row['identity'],state,chosen,row['system_drive'],why,rate)
            devices.append(d)
            if chosen:planned.append(dict(row,rate=rate,state=state,reasons=why,initial_temperature=reading))
        for missing in set(config.device_ids)-{r['device_id'] for r in rows}:
            devices.append(ThermalDevice(missing,{},'blocked',True,False,['selected stable identity not present']))
        capacity=self.budget();running=sum(d.state=='ready' for d in devices)
        requested_memory=running*(16*1024**2+config.block_size)  # conservative provisional overhead reserve, recorded
        issues=[]
        rates=[d.rate for d in devices if d.state=='ready']
        if config.aggregate_iops_limit is not None and sum(r['effective_iops'] for r in rates)>config.aggregate_iops_limit:issues.append('aggregate IOPS budget exceeded; reduce selection/intensities or explicitly revise budget')
        if config.aggregate_bps_limit is not None and sum(r['effective_bps'] for r in rates)>config.aggregate_bps_limit:issues.append('aggregate bandwidth budget exceeded; reduce selection/intensities or explicitly revise budget')
        if requested_memory>capacity['memory_budget']:issues.append('insufficient available memory after existing LVS safety reserve')
        if running*4+32>capacity['fd_limit']:issues.append('insufficient file-descriptor budget')
        if issues:
            for d in devices:
                if d.state=='ready':d.state='blocked';d.reasons.extend(issues)
            for row in planned:
                if row['state']=='ready':row['state']='blocked';row['reasons'].extend(issues)
        # Other blocked members remain visible; start confirmation must explicitly
        # approve executing only this ready subset. No hidden continuation policy.
        commands=[dict(device_id=d.device_id,guard=self.guard,stdin_identity=d.identity,
                       fio_arguments=dict(rw='randread',readonly=True,direct=True,invalidate=0,
                                          block_size=config.block_size,iops=d.rate['effective_iops'],seconds=config.duration_seconds))
                  for d in devices if d.state=='ready']
        decision=readiness(config,devices,backend,source_provenance=self.source(),launch_implemented=True,commands=commands)
        if commands and not issues and backend.get('status')=='available':
            decision.update(status='READY',runnable_devices=[c['device_id'] for c in commands],
                            reasons=['blocked members require explicit eligible-subset confirmation'] if any(d.state=='blocked' and d.selected for d in devices) else [])
        decision.update(shared_access_experimental=config.access_mode!='exclusive',
                        access_contract=('shared_readonly_v1' if config.access_mode!='exclusive' else 'exclusive_inactive_v1'),
                        aggregate_scope='LVS requested workload limits, not kernel/background/initialization I/O or other applications',
                        selected_devices=ids,partial_coverage=any(d.state=='blocked' and d.selected for d in devices),
                        resources=dict(capacity,estimated_worker_memory=requested_memory,estimate_provisional=True),
                        targets=planned)
        return decision

    def _write(self,path,value):
        error=None
        for _ in range(2):
            try:self.publish(path,value);return
            except OSError as exc:error=exc
        raise error

    def run(self,config,plan,output_root,*,allow_partial=False,control=None,observe=None,control_diagnostics=None):
        if self.unconfirmed:raise RuntimeError('previous process cleanup unconfirmed; retained descriptors require recovery')
        if plan['configuration']!=config.to_dict():raise ValueError('effective configuration changed; preview again')
        if plan['partial_coverage'] and not allow_partial:raise ValueError('explicit eligible-subset confirmation required')
        # Re-evaluate the backend and all targets after confirmation, before any open.
        fresh=self.inspect(config)
        if fresh['status']!='READY' or fresh['runnable_devices']!=plan['runnable_devices']:
            raise ValueError('readiness changed; preview and confirm again')
        if (plan.get('source_provenance') or {}).get('source',{}).get('digest')!=(fresh.get('source_provenance') or {}).get('source',{}).get('digest'):
            raise ValueError('source identity changed after preview')
        for before,after in zip(plan['targets'],fresh['targets']):
            if before['identity']!=after['identity']:raise ValueError('target changed after preview')
        plan=fresh
        provenance=self.source()
        if provenance.get('source',{}).get('digest')!=(plan.get('source_provenance') or {}).get('source',{}).get('digest'):
            raise ValueError('source identity changed after readiness')
        if provenance.get('source',{}).get('status')!='complete':raise ValueError('complete source provenance required')
        candidates=[r for r in plan['targets'] if r['state']=='ready']
        self.targets.output_safe(Path(output_root),candidates)
        # Acquire every exclusive claim before any report writes or worker start.
        # Holding the claims prevents targets being mounted under a result path.
        claims={}
        try:
            for row in candidates:claims[row['device_id']]=self.targets.open(row)
        except BaseException as error:
            for fd in claims.values():os.close(fd)
            self.last_preflight={**plan,'status':'BLOCKED','commands':[],'runnable_devices':[],
                                 'reasons':[f'{config.access_mode} acquisition failed; no worker started: {error}']}
            try:
                self.targets.output_safe(Path(output_root),candidates)
                blocked=Path(output_root)/f'Storage_Thermal_Assist_Blocked_{uuid4().hex[:8]}'
                self._write(blocked/'effective_preflight.json',self.last_preflight);self.last_output=blocked
            except (OSError,ValueError):pass  # original failure remains visible; never write onto an unsafe target
            raise ValueError(self.last_preflight['reasons'][0]) from error
        directory=Path(output_root)/f'{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}_Storage_Thermal_Assist_{uuid4().hex[:8]}'
        try:
            directory.mkdir(parents=True,exist_ok=False,mode=0o700);self.last_output=directory
            (directory/'worker_results').mkdir();(directory/'worker_logs').mkdir()
            plan['source_provenance']=provenance;plan['exclusive_claims_acquired']=config.access_mode=='exclusive';plan['shared_claims_acquired']=config.access_mode!='exclusive'
            self._write(directory/'effective_preflight.json',plan)
            self._write(directory/'configuration.json',config.to_dict())
            manifest=dict(contract_id='lvs.storage_thermal.manifest',contract_version=1,status='running',verdict='INCOMPLETE',
                          started=datetime.now(timezone.utc).isoformat(),readiness=plan,source_provenance=provenance,
                          physical_thermal_acceptance=False)
            self._write(directory/'storage_thermal_manifest.json',manifest)
            progress=(directory/'progress.jsonl').open('w')
        except BaseException:
            for fd in claims.values():os.close(fd)
            raise
        jobs=[];pending=[r for r in plan['targets'] if r['state']=='ready'];failure=''
        started=self.clock();cpu_start=time.process_time();children_start=resource.getrusage(resource.RUSAGE_CHILDREN)
        next_launch=started;next_monitor=started;next_identity=started;next_progress=started
        handlers={};stop_all=False;emergency=False;request_time=None
        control_events=[];dropped_control_events=0
        def event(kind,**fields):
            nonlocal dropped_control_events
            if len(control_events)<256:control_events.append(dict(kind=kind,observed_monotonic=self.clock(),**fields))
            else:dropped_control_events+=1
        def interrupted(_signum,_frame):
            nonlocal stop_all,request_time
            stop_all=True;request_time=self.clock()
            event('signal_request',signal=_signum,recognized_monotonic=request_time)
        for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):
            try:handlers[sig]=signal.signal(sig,interrupted)
            except ValueError:pass  # injected worker-thread tests; main CLI is always signal-aware
        def stop(job,reason,safety=False,recognized=None):
            r=job['result']
            if job.get('done') or not job.get('process'):return
            if not job.get('stopping'):
                timing=job.setdefault('control_timing',{})
                if recognized is not None:timing['request_recognized_monotonic']=recognized
                try:
                    # A request is not proof of interruption. Reap/check through
                    # stable authority before tagging an operator cancellation.
                    if reason.startswith(('operator cancelled','group emergency')) and self._process(job['process']).poll() is not None:
                        timing['request_after_observed_exit']=True
                        event('late_stop_request',device_id=r.device_id,recognized_monotonic=recognized)
                        return
                    job['stopping']=self.clock();r.stop_reason=reason;r.safety_stop=safety
                    timing['signal_dispatch_monotonic']=self.clock()
                    self._signal_process(job['process'],signal.SIGTERM)
                    timing['signal_dispatched']=True
                except ProcessLookupError:
                    timing['signal_dispatched']=False
                    if reason.startswith('operator cancelled'):r.stop_reason=''
                except OSError as exc:r.state='incomplete';r.stop_reason='Owned process authority lost: '+str(exc)
        try:
            while pending or any(not j.get('done') for j in jobs):
                now=self.clock()
                if control:
                    commands=control(jobs) or []
                    for supplied in commands[:32]:
                        command=supplied.get('command') if isinstance(supplied,dict) else supplied
                        recognized=supplied.get('recognized_monotonic',now) if isinstance(supplied,dict) else now
                        event('control_request',command=command,recognized_monotonic=recognized)
                        if command in ('all','emergency'):
                            stop_all=True;request_time=recognized
                            if command=='emergency':emergency=True
                        else:
                            for j in jobs:
                                if j['row']['device_id']==command:stop(j,'operator cancelled drive',recognized=recognized)
                if config.monitoring=='approved_unmonitored' and not approval_valid(config,plan['selected_devices']):
                    emergency=True;stop_all=True
                    for j in jobs:
                        if not j.get('done'):stop(j,'bounded unmonitored approval expired',True)
                if stop_all:
                    pending.clear()
                    for j in jobs:
                        if not j.get('done'):stop(j,'group emergency stop' if emergency else 'operator cancelled run',emergency,request_time)
                if pending and now>=next_launch:
                    row=pending.pop(0);index=len(jobs)+1;fd=None;out=None;err=None;exe=None
                    result=ThermalResult(row['device_id'],row['identity'],state='running',activity_scope='physical_drive_reads',access_mode=config.access_mode,
                                         source_provenance=provenance,executable_provenance=plan['backend'],effective_rate=row['rate'])
                    job=dict(row=row,result=result,index=index,started=now,samples=[],peak=None,initial=None)
                    jobs.append(job)
                    try:
                        if config.monitoring=='approved_unmonitored' and not approval_valid(config,plan['selected_devices']):
                            raise ValueError('unmonitored approval expired')
                        before=self.temperature(row);bound,_=limits(config,before)
                        if (before.get('value_c') is not None and (bound is not None and before['value_c']>=bound
                                or before.get('low_critical_c') is not None and before['value_c']<=before['low_critical_c'])
                                or config.monitoring=='required' and (not before.get('complete') or bound is None)):
                            raise ValueError('temperature safety changed before launch')
                        fd=claims.pop(row['device_id']);job['fd']=fd
                        self.targets.revalidate(row)
                        exe=os.open(plan['backend']['fio']['path'],os.O_RDONLY|os.O_CLOEXEC)
                        argv=guard_command(self.guard,exe,backend=plan['backend'],uid=self.uid,gid=self.gid,
                                           major=row['identity']['major'],minor=row['identity']['minor'],size=row['identity']['size_bytes'],
                                           block_size=config.block_size,iops=row['rate']['effective_iops'],seconds=config.duration_seconds)
                        out=(directory/'worker_logs'/f'{index}.stdout').open('wb');err=(directory/'worker_logs'/f'{index}.stderr').open('wb')
                        job.update(stdout=out,stderr=err,command=argv)
                        result.launch_requested_monotonic=self.clock()
                        launcher=self.popen
                        if config.access_mode!='exclusive' and self.native_processes is None and launcher is subprocess.Popen:
                            launcher=OwnedProcess
                        p=launcher(argv,stdin=fd,pass_fds=(exe,),stdout=out,stderr=err,
                                     start_new_session=True,env=guard_environment())
                        job['process']=p  # register ownership before any further observation
                        result.started_monotonic=self.clock();job['started']=result.started_monotonic
                        job['baseline']=self.activity().get((row['identity']['major'],row['identity']['minor']))
                    except (OSError,ValueError) as error:
                        result.errors=1;result.stop_reason=str(error)
                        if job.get('process'):
                            stop(job,'launch observation failed: '+str(error),True)
                        else:
                            result.state='failed';result.cleanup_confirmed=True
                            result.started_monotonic=result.ended_monotonic=self.clock();job['done']=True
                            if fd is not None:os.close(fd);job.pop('fd',None)
                            for handle in (out,err):
                                if handle:handle.close()
                        emergency=True;stop_all=True
                    finally:
                        if exe is not None:os.close(exe)
                    next_launch=self.clock()+(1 if config.access_mode!='exclusive' else .1)
                if now>=next_monitor:
                    activity=self.activity()
                    # One shared snapshot for all identities, not N discovery processes.
                    current=None
                    if now>=next_identity:
                        current={r['device_id']:r for r in self.discover(config)};next_identity=now+5
                    capacity=self.budget()
                    if capacity['memory_budget']<=0:
                        emergency=True;stop_all=True
                    for job in jobs:
                        if job.get('done'):continue
                        row=job['row'];r=job['result'];p=job['process']
                        reading=self.temperature(row);value=reading.get('value_c');limit,warning=limits(config,reading)
                        if value is not None:
                            job['initial']=value if job['initial'] is None else job['initial']
                            job['peak']=value if job['peak'] is None else max(value,job['peak'])
                        if value is not None and (limit is not None and value>=limit or reading.get('low_critical_c') is not None and value<=reading['low_critical_c']):
                            stop(job,'temperature stop limit reached',True);emergency=True;stop_all=True
                        if config.monitoring=='required' and (not reading.get('complete') or limit is None):
                            stop(job,'temperature provider unavailable',True)
                        if current is not None and (row['device_id'] not in current or current[row['device_id']]['identity']!=row['identity'] or not current[row['device_id']]['eligible']):
                            stop(job,'device identity/topology changed',True);emergency=True;stop_all=True
                        counters=activity.get((row['identity']['major'],row['identity']['minor']))
                        baseline=job.get('baseline')
                        if counters is None or baseline is None or len(counters)!=len(baseline) or any(a<b for i,(a,b) in enumerate(zip(counters,baseline)) if i!=8):
                            stop(job,'device activity evidence missing/reset',True)
                        elif config.access_mode=='exclusive' and any(counters[k]>baseline[k] for k in (4,6,11,13,15) if k<len(counters)):
                            stop(job,'unexpected write/discard/flush activity on inactive target',True);emergency=True;stop_all=True
                        if any(h.tell()>2*1024**2 for h in (job['stdout'],job['stderr'])):
                            stop(job,'worker log exceeded bound',True)
                        snapshot=dict(monotonic=now,device_id=row['device_id'],temperature=reading,
                                      temperature_warning=value is not None and warning is not None and value>=warning,
                                      block_counters=counters,process=process_observation(self._process_pid(p)))
                        if counters is not None and baseline is not None:
                            snapshot['device_read_ios_since_launch']=max(0,counters[0]-baseline[0])
                            snapshot['device_read_bytes_since_launch']=max(0,counters[2]-baseline[2])*512
                            snapshot['device_iops_since_launch']=snapshot['device_read_ios_since_launch']/max(.001,now-job['started'])
                            snapshot['activity_attribution']='device counters, not exclusive fio attribution'
                            snapshot['access_mode']=config.access_mode
                            snapshot['background_write_ios_since_launch']=max(0,counters[4]-baseline[4])
                            snapshot['background_discards_since_launch']=max(0,counters[11]-baseline[11]) if len(counters)>11 else None
                            snapshot['background_flushes_since_launch']=max(0,counters[15]-baseline[15]) if len(counters)>15 else None
                        job['temperature_warning']=job.get('temperature_warning',False) or snapshot['temperature_warning']
                        job['last_snapshot']=snapshot
                        if now>=next_progress:progress.write(json.dumps(snapshot)+'\n')
                    if now>=next_progress:progress.flush();next_progress=now+max(1,config.duration_seconds/1024)
                    next_monitor=now+1
                for job in jobs:
                    if job.get('done'):continue
                    p=self._process(job['process']);r=job['result']
                    if p.poll() is None and now-job['started']>config.duration_seconds+5:
                        r.shutdown_timed_out=True;stop(job,'worker completion deadline expired')
                    if job.get('stopping') is not None and not self._clean_process(p) and now-job['stopping']>=2 and not job.get('kill_at'):
                        r.forced_kill=True;job['kill_at']=now
                        try:self._signal_process(p,signal.SIGKILL)
                        except ProcessLookupError:pass
                    if p.poll() is not None:
                        p.wait();r.exit_code=p.returncode;r.ended_monotonic=self.clock()
                        job.setdefault('control_timing',{})['worker_exit_observed_monotonic']=r.ended_monotonic
                        if not job.get('evidence_finished'):
                            self._finish(job,config);job['evidence_finished']=True
                            if r.state=='failed':emergency=True;stop_all=True
                        if self._clean_process(p):
                            os.close(job['fd']);job.pop('fd');r.cleanup_confirmed=True
                            job.setdefault('control_timing',{})['cleanup_confirmed_monotonic']=self.clock()
                        else:
                            stop(job,'descendant cleanup unconfirmed');
                            if now-job['stopping']<4:continue
                        job['done']=True
                    elif job.get('kill_at') is not None and now-job['kill_at']>=2:
                        r.state='incomplete';r.stop_reason='process cleanup unconfirmed after SIGKILL';r.ended_monotonic=now
                        job['done']=True
                if observe:observe(jobs)
                self.sleep(.1)
        except BaseException as error:
            failure=f'{type(error).__name__}: {error}'
            # One broadcast, then bounded group reaping, even after UI/persistence failure.
            for j in jobs:
                if j.get('process') and not j.get('done'):stop(j,'supervisor failure',True)
            for j in jobs:
                if j.get('process') and not j.get('done'):
                    try:self._process(j['process']).wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        j['result'].forced_kill=True
                        try:self._signal_process(j['process'],signal.SIGKILL)
                        except OSError:pass
                        try:self._process(j['process']).wait(timeout=2)
                        except (subprocess.TimeoutExpired,OSError):pass
                    except OSError:pass
                    j['result'].state='incomplete';j['result'].stop_reason=failure
        finally:
            progress.close()
            for fd in claims.values():os.close(fd)
            for sig,handler in handlers.items():signal.signal(sig,handler)
            for job in jobs:
                p=job.get('process');r=job['result']
                if 'fd' in job:
                    try:clean=bool(p) and self._clean_process(p)
                    except OSError:clean=False;job['authority_lost']=True
                    if clean:
                        os.close(job.pop('fd'));r.cleanup_confirmed=True
                        timing=job.setdefault('control_timing',{})
                        timing.setdefault('worker_exit_observed_monotonic',self.clock())
                        timing['cleanup_confirmed_monotonic']=self.clock()
                    else:self.unconfirmed.append(job);r.outstanding_descriptors=1;r.state='incomplete'
                for name in ('stdout','stderr'):
                    if name in job:job[name].close()
        source_end=self.source()
        source_unchanged=source_end.get('source',{}).get('status')=='complete' and source_end.get('source',{}).get('digest')==provenance['source'].get('digest')
        if not source_unchanged:failure=failure or 'source fingerprint changed or final source collection failed'
        records=[]
        for job in jobs:
            r=job['result'];r.provenance_confirmed=r.provenance_confirmed and source_unchanged;payload=r.to_dict()
            payload.update(configured_duration_seconds=config.duration_seconds,
                           pid=self._process_pid(job['process']) if job.get('process') and not job.get('authority_lost') else None,
                           temperature_start_c=job['initial'],temperature_peak_c=job['peak'],
                           temperature_end_c=job.get('temperature_end'),temperature_warning=job.get('temperature_warning',False),
                           last_observation=job.get('last_snapshot'),guard_evidence=job.get('guard'),command=job.get('command'),
                           fio_cpu=job.get('fio_cpu'),fio_activity=job.get('fio_activity'),control_timing=job.get('control_timing',{}))
            try:
                payload['terminal_published']=True;self._write(directory/'worker_results'/f'{job["index"]}.json',payload)
            except OSError as error:payload['terminal_published']=False;payload['state']='incomplete';failure=str(error)
            records.append(payload)
        executed={r['device_id'] for r in records if r['started_monotonic'] is not None and r.get('pid')}
        missing=set(plan['runnable_devices'])-executed
        verdict=('INCOMPLETE' if failure or any(not r['cleanup_confirmed'] or not r['terminal_published'] or r['state'] in ('incomplete','cancelled') for r in records)
                 else 'FAIL' if any(not result_successful(r) for r in records) else
                 'INCOMPLETE' if missing else
                 'WARN' if config.access_mode!='exclusive' or plan['partial_coverage'] or any(r['temperature_status']!='monitored' or r['temperature_warning'] for r in records) else 'PASS')
        ended=self.clock();children=resource.getrusage(resource.RUSAGE_CHILDREN)
        result=dict(contract_id='lvs.storage_thermal.manifest',contract_version=1,kind='storage_thermal',status='completed' if verdict in ('PASS','WARN') else verdict.lower(),
                    verdict=verdict,requested=True,execution_started=bool(executed),
                    cleanup_confirmed=all(r.get('cleanup_confirmed') is True for r in records),
                    terminal_published=True,configuration=config.to_dict(),requested_devices=plan['selected_devices'],
                    executed_devices=sorted(executed),unexecuted_devices=sorted(missing),devices=records,
                    blocked_devices=plan['blocked_devices'],source_provenance=provenance,
                    elapsed_seconds=ended-started,supervisor_cpu_seconds=time.process_time()-cpu_start,
                    children_cpu_seconds=(children.ru_utime+children.ru_stime)-(children_start.ru_utime+children_start.ru_stime),
                    heating_effectiveness='not_accepted',storage_integrity='not_tested',failure=failure,
                    physical_thermal_acceptance=False,control_events=control_events,dropped_control_events=dropped_control_events,
                    input_observation=control_diagnostics() if control_diagnostics else None,
                    source_provenance_end=source_end,readiness=plan,parent_finalization_complete=True,
                    ended=datetime.now(timezone.utc).isoformat(),started=manifest['started'])
        # One atomic completion authority, published LAST. No earlier successful
        # aggregate snapshot can conceal a report/finalization failure.
        observations=self.summary(result).splitlines()[1:]
        (directory/'storage_thermal_summary.txt').write_text('Storage Thermal Assist observations\nCompletion authority: storage_thermal_manifest.json\n'+'\n'.join(observations)+'\n')
        self._write(directory/'storage_thermal_manifest.json',result)
        return directory,result

    def _finish(self,job,config):
        r=job['result'];job['stdout'].flush();job['stderr'].flush()
        try:
            stderr=Path(job['stderr'].name).read_text()
            guard=next(json.loads(line) for line in stderr.splitlines() if line.startswith('{') and '"contract_id":"lvs.storage_thermal.guard"' in line)
            job['guard']=guard
            r.guard_confirmed=(guard['pid']==self._process_pid(job['process']) and guard['uid']==self.uid and guard['gid']==self.gid
                               and guard['capabilities']==0 and guard['seccomp']==2 and guard['no_new_privs']==1 and guard['readonly_direct'] is True)
            output=Path(job['stdout'].name).read_text();payload=json.loads(output[output.index('{'):]);fio=payload['jobs'][0]
            for value in (fio['read']['total_ios'],fio['read']['io_bytes'],fio['write']['total_ios'],fio['trim']['total_ios'],fio['error']):
                if type(value) is not int or value<0:raise ValueError('invalid fio counter')
            r.read_ios=fio['read']['total_ios'];r.read_bytes=fio['read']['io_bytes']
            r.write_ios=int(fio['write']['total_ios']);r.discard_ios=int(fio['trim']['total_ios'])
            r.flush_ios=int((fio.get('sync') or {}).get('total_ios',0));r.errors=int(fio['error'])
            milliseconds=fio['read']['runtime']
            if type(milliseconds) is not int or milliseconds<0:raise ValueError('invalid fio runtime')
            r.duration_completed=milliseconds>=config.duration_seconds*1000
            job['fio_activity']=dict(active_seconds=milliseconds/1000,achieved_iops=r.read_ios*1000/milliseconds if milliseconds else 0,
                                     achieved_bps=r.read_bytes*1000/milliseconds if milliseconds else 0)
            job['fio_cpu']=dict(user_percent=fio.get('usr_cpu'),system_percent=fio.get('sys_cpu'))
            self.targets.revalidate(job['row']);r.identity_unchanged=True
            final=self.temperature(job['row']);job['temperature_end']=final.get('value_c');bound,warning=limits(config,final)
            if final.get('value_c') is not None:
                job['peak']=final['value_c'] if job['peak'] is None else max(job['peak'],final['value_c'])
                job['temperature_warning']=job.get('temperature_warning',False) or warning is not None and final['value_c']>=warning
            if (config.monitoring=='required' and not final.get('complete')
                    or final.get('value_c') is not None and (bound is not None and final['value_c']>=bound
                        or final.get('low_critical_c') is not None and final['value_c']<=final['low_critical_c'])):
                r.safety_stop=True;r.stop_reason=r.stop_reason or 'final temperature evidence failed safety policy'
            r.provenance_confirmed=(executable_identity(self.fio)==r.executable_provenance['fio'] and executable_identity(self.guard)==r.executable_provenance['guard'])
            r.temperature_status='monitored' if config.monitoring=='required' and job['initial'] is not None else 'unmonitored'
            r.heating_status='observed_temperature_only' if job['initial'] is not None else 'unmeasured'
        except (OSError,ValueError,KeyError,StopIteration,IndexError,TypeError) as error:
            r.errors+=1;r.stop_reason=r.stop_reason or f'worker evidence invalid: {error}'
        if r.safety_stop:r.state='failed'
        elif r.shutdown_timed_out or r.forced_kill:r.state='incomplete'
        elif r.stop_reason.startswith(('operator cancelled','group emergency')):
            if r.duration_completed and r.exit_code==0 and not r.errors and not (r.write_ios or r.discard_ios or r.flush_ios) and r.guard_confirmed and r.provenance_confirmed:
                # Completion won the signal/exit race; retain the request timing
                # without retrospectively claiming interrupted execution.
                job.setdefault('control_timing',{})['completed_before_interruption']=True
                r.stop_reason='';r.state='completed'
            else:r.state='cancelled'
        elif r.exit_code!=0 or r.errors or r.write_ios or r.discard_ios or r.flush_ios or not r.duration_completed or not r.guard_confirmed or not r.provenance_confirmed:r.state='failed'
        elif r.stop_reason:r.state='incomplete'
        else:r.state='completed'

    @staticmethod
    def summary(result):
        lines=[f"Storage Thermal Assist: {result['verdict']}",
               f"Requested {len(result['requested_devices'])}; executed {len(result['executed_devices'])}; blocked {len(result['blocked_devices'])}"]
        for r in result['devices']:
            seconds=(r['ended_monotonic'] or 0)-(r['started_monotonic'] or 0)
            lines.append(f"{r['device_id']}: {r['state']}; {r['read_ios']} reads / {r['read_bytes']} bytes; "
                         f"{r['read_ios']/seconds if seconds>0 else 0:.2f} IOPS over observed process interval; "
                         f"peak {r.get('temperature_peak_c')} C; cleanup={r['cleanup_confirmed']}; {r['stop_reason']}")
        lines.append('Read activity is not storage-integrity verification or accepted heating effectiveness.')
        return '\n'.join(lines)
