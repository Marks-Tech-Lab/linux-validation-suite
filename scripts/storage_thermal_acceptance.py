"""External acceptance observer: proc/sysfs metadata only; never opens a drive.

Not a workload launcher, safety monitor, cleanup certifier or production provider.
Run from the repository root with python -m scripts.storage_thermal_acceptance.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from itertools import islice
import math
import os
from pathlib import Path
import resource
import re
import signal
import stat
import time
from uuid import uuid4

from Modules.lvs_profile_report_artifacts import atomic_preflight_json
from Modules.lvs_telemetry_cpu import parse_proc_stat_cpu_snapshot, cpu_utilization_percent
from Modules.lvs_storage_thermal_runner import disk_activity
from Modules.lvs_storage_thermal_targets import ThermalTargets, temperature

CONTRACT='lvs.storage_thermal.acceptance_observer.v1'
MAX_LINE=1024*1024
MAX_LOG=128*1024*1024
MAX_PROCESSES=128
MAX_EVENTS=256


def require(condition,message):
    if not condition:raise ValueError(message)


def json_file(path):
    path=Path(path);info=path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_size<=8*1024*1024,'regular bounded JSON file required')
    return json.loads(path.read_text())


def event_paths(directory):
    # Atomic publisher's temporary names are not committed event packets.
    committed=(p for p in (Path(directory)/'events').iterdir() if re.fullmatch(r'[0-9]{20}-[0-9a-f]{32}\.json',p.name))
    paths=list(islice(committed,MAX_EVENTS+1))
    require(len(paths)<=MAX_EVENTS,'event limit exceeded')
    return sorted(paths)


def boot_id(proc=Path('/proc')):
    return (proc/'sys/kernel/random/boot_id').read_text().strip()


def stamp():
    return dict(monotonic_ns=time.monotonic_ns(),realtime_ns=time.time_ns())


def process(pid,proc=Path('/proc')):
    """Read creation ticks before AND after the other observations; no signaling."""
    directory=proc/str(pid)
    first=(directory/'stat').read_text().rsplit(')',1)[1].split()
    unavailable=[]
    try:children=(directory/'task'/str(pid)/'children').read_text().split()
    except OSError:children=[];unavailable.append('children')
    try:fds=len(list((directory/'fd').iterdir()))
    except OSError:fds=None;unavailable.append('fds')
    final=(directory/'stat').read_text().rsplit(')',1)[1].split()
    require(first[19]==final[19],'process identity changed during observation')
    return dict(pid=pid,start_ticks=int(final[19]),cpu_ticks=int(final[11])+int(final[12]),
                waited_child_ticks=int(final[13])+int(final[14]),rss_bytes=max(0,int(final[21]))*os.sysconf('SC_PAGE_SIZE'),
                threads=int(final[17]),fds=fds,children=[int(p) for p in children],state=final[0],unavailable=unavailable)


class Processes:
    def __init__(self,reader=process):
        self.reader=reader;self.known={};self.retired=set()

    def register(self,pid,role,expected=None):
        require(role in ('auxiliary','primary','observer'),'unknown process role')
        row=self.reader(pid)
        require(expected is None or row['start_ticks']==expected,'registered process identity changed')
        require(len(self.known)<MAX_PROCESSES or pid in self.known,'process observation limit')
        self.retired.discard(pid)
        self.known[pid]=(row['start_ticks'],role)
        return row['start_ticks']

    def sample(self):
        rows={};errors=[];queue=list(self.known);visited=set()
        while queue:
            pid=queue.pop(0)
            if pid in visited:continue
            visited.add(pid)
            expected,role=self.known[pid]
            try:
                row=self.reader(pid)
                require(row['start_ticks']==expected,'PID reused; replacement not followed')
                rows[pid]=dict(row,role=role)
            except (OSError,ValueError) as error:
                errors.append(dict(pid=pid,start_ticks=expected,reason=str(error)));self.known.pop(pid,None)
                require(len(self.retired)<8192,'retired process history limit');self.retired.add(pid)
            if pid not in rows:continue
            for child in row['children']:
                if child in self.retired:continue
                try:
                    if child not in self.known:
                        self.register(child,role);queue.append(child)
                    elif role=='auxiliary' and self.known[child][1]=='primary':
                        self.known[child]=(self.known[child][0],'auxiliary')
                        if child in rows:rows[child]['role']='auxiliary'
                except (OSError,ValueError) as error:
                    errors.append(dict(pid=child,parent_pid=pid,start_ticks=None,
                                       observation='child registration incomplete',reason=str(error)))
        return list(rows.values()),errors


def host_sample(proc):
    aggregate,cores=parse_proc_stat_cpu_snapshot((proc/'stat').read_text())
    require(aggregate is not None,'host CPU counters unavailable')
    cpu=list(aggregate[:8])  # guest fields already included in user/nice
    memory={k:int(v.split()[0])*1024 for k,v in (line.split(':',1) for line in (proc/'meminfo').read_text().splitlines())
            if k in ('MemAvailable','MemTotal','SwapFree','SwapTotal')}
    vm={k:int(v) for k,v in (line.split() for line in (proc/'vmstat').read_text().splitlines())
        if k in ('pgmajfault','pswpin','pswpout')}
    pressure={}
    for name in ('cpu','memory','io'):
        try:pressure[name]=(proc/'pressure'/name).read_text().strip()
        except OSError:pressure[name]=None
    return dict(cpu_ticks=cpu,logical_cpus=len(cores),
                memory=memory,vm=vm,pressure=pressure)


def counter_delta(previous,current,seconds):
    """Linux whole-device stat ABI; no fabricated rate on reset/missing data."""
    if (not isinstance(previous,list) or not isinstance(current,list) or len(previous)!=len(current)
            or len(current)<11 or not math.isfinite(seconds) or seconds<=0
            or any(type(v) is not int or v<0 for v in previous+current)):
        return dict(status='unavailable')
    cumulative=[i for i in range(len(current)) if i!=8]
    if any(current[i]<previous[i] for i in cumulative):return dict(status='reset')
    d=[a-b for a,b in zip(current,previous)]
    return dict(status='observed',read_iops=d[0]/seconds,read_bps=d[2]*512/seconds,
                writes=d[4],write_bytes=d[6]*512,discards=d[11] if len(d)>11 else None,
                flushes=d[15] if len(d)>15 else None,read_await_ms=d[3]/d[0] if d[0] else None,
                average_queue=d[10]/(seconds*1000),busy_percent=d[9]/(seconds*10),
                in_flight=current[8],scope='whole-device counters; attribution and controller/NAND latency unproven')


def capture(args,*,targets=None,proc=Path('/proc'),clock=time.monotonic,sleep=time.sleep):
    targets=targets or ThermalTargets()
    inventory=json_file(args.inventory)
    require(isinstance(inventory,list),'inventory must be the passive --check list')
    rows=[r for r in inventory if r.get('device_id') in args.device_id]
    require(len(args.device_id)==len(set(args.device_id)) and len(rows)==len(args.device_id) and len(rows)<=28,'missing/duplicate target or target-count limit')
    modes={r.get('access_mode','exclusive') for r in rows}
    require(len(modes)==1 and modes<= {'exclusive','shared_readonly_opt_in'},'one approved access contract per capture required')
    mode=next(iter(modes))
    require(all(r.get('eligible') is True and not r.get('system_drive') and
                (r.get('drive_class')=='hdd' or mode!='exclusive' and r.get('drive_class') in ('ssd','nvme')) for r in rows),'supported eligible non-system physical data drives required')
    discover=lambda:targets.discover(access_mode=mode) if mode!='exclusive' else targets.discover()
    current={r['device_id']:r for r in discover()}
    for row in rows:
        now=current.get(row['device_id'])
        require(now and now['eligible'] and now['identity']==row['identity'] and now['sensors']==row['sensors'],'inventory stale: identity, sensors or eligibility changed')
    directory=Path(args.directory).absolute()
    targets.output_safe(directory,rows)
    directory.mkdir(mode=0o700)  # existing path refused; no append to another session
    (directory/'events').mkdir(mode=0o700)
    session=uuid4().hex;boot=boot_id(proc);start=clock();tracker=Processes(lambda p:process(p,proc))
    tracker.register(os.getpid(),'observer')
    meta=dict(contract=CONTRACT,session=session,boot_id=boot,started=stamp(),targets=rows,
              observer_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              interval_seconds=args.interval,duration_seconds=args.seconds,temperature_reads=args.temperatures,
              sensor_resolution_c=args.sensor_resolution_c,clock_ticks=os.sysconf('SC_CLK_TCK'),
              cleanup_authority=False,complete=False,access_mode=mode,observer_startup_cpu_seconds=time.process_time())
    atomic_preflight_json(directory/'session.json',meta)
    stop=False;handlers={};seen=set();phase='passive';ambient=None;next_identity=start;count=0;written=0;failure=None;max_sample=0
    def interrupt(_sig,_frame):
        nonlocal stop
        stop=True
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):handlers[sig]=signal.signal(sig,interrupt)
    try:
        with (directory/'samples.jsonl').open('x',buffering=1) as stream:
            deadline=start
            while not stop and clock()-start<args.seconds:
                begin=clock();errors=[]
                for path in event_paths(directory):
                    if path.name in seen:continue
                    require(len(seen)<MAX_EVENTS,'event limit reached')
                    event=json_file(path)
                    require(event['session']==session and event['boot_id']==boot,'foreign event')
                    require(type(event['monotonic_ns']) is int and meta['started']['monotonic_ns']<=event['monotonic_ns']<=time.monotonic_ns(),'invalid event time')
                    seen.add(path.name)
                    if event.get('phase'):phase=event['phase']
                    if event.get('ambient_c') is not None:ambient={k:event[k] for k in ('ambient_c','monotonic_ns')}
                    if event.get('process'):
                        p=event['process'];tracker.register(p['pid'],p['role'],p['start_ticks'])
                if begin>=next_identity:
                    current={r['device_id']:r for r in discover()}
                    for r in rows:
                        now=current.get(r['device_id'])
                        require(now and now['eligible'] and now['identity']==r['identity'] and now['sensors']==r['sensors'],'target eligibility/identity/sensor association changed: stop workload separately')
                    require(boot_id(proc)==boot,'boot changed')
                    next_identity=begin+5
                devices={};disk_started=clock();counters=disk_activity(proc);disk_read_seconds=clock()-disk_started
                for r in rows:
                    identity=r['identity'];key=(identity['major'],identity['minor'])
                    temp_started=clock();reading=temperature(r) if args.temperatures else None
                    devices[r['device_id']]=dict(counters=counters.get(key),temperature=reading,temperature_read_seconds=clock()-temp_started)
                processes,process_errors=tracker.sample()
                sample=dict(type='sample',session=session,boot_id=boot,**stamp(),phase=phase,ambient=ambient,devices=devices,
                            processes=processes,process_gaps=process_errors,host=host_sample(proc),
                            late_seconds=max(0,begin-deadline),read_seconds=clock()-begin,diskstats_read_seconds=disk_read_seconds)
                max_sample=max(max_sample,sample['read_seconds']);line=json.dumps(sample,allow_nan=False)+'\n'
                require(len(line.encode())<=MAX_LINE and written+len(line.encode())<=MAX_LOG,'capture size limit reached: stop workload separately')
                stream.write(line);written+=len(line.encode());count+=1
                if count%10==0:stream.flush();os.fsync(stream.fileno())
                deadline=max(deadline+args.interval,clock())
                sleep(max(0,min(deadline,start+args.seconds)-clock()))
            stream.flush();os.fsync(stream.fileno())
    except Exception as error:
        failure=repr(error)
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)
        meta.update(ended=stamp(),complete=failure is None,operator_stopped=stop,failure=failure,samples=count,
                    observed_seconds=clock()-start,max_sample_read_seconds=max_sample,bytes_written=written,
                    observer_cpu_seconds=time.process_time(),observer_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
        atomic_preflight_json(directory/'session.json',meta)
    require(failure is None,failure)
    return meta


def mark(args):
    directory=Path(args.directory);meta=json_file(directory/'session.json')
    require(meta['contract']==CONTRACT and meta['boot_id']==boot_id(),'wrong capture/boot')
    require(0<len(args.event)<=256 and len(event_paths(directory))<MAX_EVENTS,'event name/quantity limit')
    event=dict(session=meta['session'],boot_id=meta['boot_id'],**stamp(),event=args.event)
    if args.phase:event['phase']=args.phase
    if args.ambient_c is not None:
        require(math.isfinite(args.ambient_c),'ambient must be finite');event['ambient_c']=args.ambient_c
    if args.pid:
        row=process(args.pid);event['process']=dict(pid=args.pid,start_ticks=row['start_ticks'],role=args.role)
    name=f'{event["monotonic_ns"]:020d}-{uuid4().hex}.json'
    atomic_preflight_json(directory/'events'/name,event)
    return event


def analyze(directory):
    directory=Path(directory);meta=json_file(directory/'session.json');require(meta['contract']==CONTRACT,'foreign capture')
    previous=None;last_process={};cpu={};rates={};thermal={};issues=[];samples=0;max_gap=0;first=None;peaks={};host_usage=dict(weighted_percent_seconds=0,covered_seconds=0)
    def issue(message):
        if message not in issues:issues.append(message)
    path=directory/'samples.jsonl';require(path.stat().st_size<=MAX_LOG,'oversized capture')
    with path.open() as stream:
        for line in stream:
            require(len(line)<=MAX_LINE,'oversized sample')
            try:row=json.loads(line)
            except ValueError:issue('malformed/truncated sample');continue
            try:
                require(row['session']==meta['session'] and row['boot_id']==meta['boot_id'],'foreign sample/session')
                require(set(row['devices'])=={r['device_id'] for r in meta['targets']},'missing/foreign device observations')
                now=row['monotonic_ns'];require(type(now) is int,'invalid monotonic timestamp')
                first=now if first is None else first
                dt=(now-previous['monotonic_ns'])/1e9 if previous else None
                if dt is not None:require(dt>0,'non-increasing monotonic timestamps');max_gap=max(max_gap,dt)
                if previous and abs((row['realtime_ns']-previous['realtime_ns'])/1e9-dt)>1:issue('wall clock step; monotonic intervals retained')
                if previous:
                    host_before=previous.get('host',{});host_now=row.get('host',{})
                    if host_before.get('logical_cpus')!=host_now.get('logical_cpus'):issue('CPU capacity changed; host-normalized process budgets unqualified')
                    vectors=(host_before.get('cpu_ticks'),host_now.get('cpu_ticks'))
                    valid=all(isinstance(v,list) and len(v)>=4 and all(type(x) is int and x>=0 for x in v) for v in vectors)
                    if not valid:issue('host CPU counters missing/invalid')
                    busy=cpu_utilization_percent(*vectors) if valid else None
                    if busy is not None:host_usage['weighted_percent_seconds']+=busy*dt;host_usage['covered_seconds']+=dt
                for identity,device in row['devices'].items():
                    delta=counter_delta((previous or {}).get('devices',{}).get(identity,{}).get('counters'),device['counters'],dt or 0)
                    rate=rates.setdefault(identity,dict(intervals=0,covered_seconds=0,read_ios=0,read_bytes=0,last_interval=None))
                    if delta['status']=='observed':
                        rate['intervals']+=1;rate['covered_seconds']+=dt
                        rate['read_ios']+=delta['read_iops']*dt;rate['read_bytes']+=delta['read_bps']*dt
                        rate['last_interval']=delta
                        if any(delta.get(k,0) for k in ('writes','discards','flushes')):
                            if meta.get('access_mode','exclusive')=='exclusive':issue('exclusive target mutation counters observed: investigate; no automatic attribution')
                            rate['background_activity_observed']=True
                    elif previous:issue('missing/reset device counters')
                    reading=device.get('temperature')
                    if meta['temperature_reads']:
                        if not reading or not reading.get('complete') or reading.get('value_c') is None:issue('missing/incomplete temperature')
                        else:
                            ambient=row.get('ambient');age=(now-ambient['monotonic_ns'])/1e9 if ambient else None
                            require(type(reading['value_c']) in (int,float) and math.isfinite(reading['value_c']),'invalid sensor value')
                            if age is not None and 0<=age<=300:
                                require(type(ambient['ambient_c']) in (int,float) and math.isfinite(ambient['ambient_c']),'invalid ambient value')
                                key=(identity,row['phase']);value=reading['value_c']-ambient['ambient_c']
                                t=thermal.setdefault(key,dict(count=0,total=0,minimum=value,maximum=value,tail=[],first_ns=now,last_ns=now))
                                t['last_ns']=now;t['count']+=1;t['total']+=value;t['minimum']=min(t['minimum'],value);t['maximum']=max(t['maximum'],value)
                                t['tail']=[(ns,v) for ns,v in t['tail'] if now-ns<=300_000_000_000]+[(now,value)]
                            else:issue('ambient absent/stale; corrected heating unavailable for affected samples')
                totals={}
                for p in row['processes']:
                    group=totals.setdefault(p['role'],dict(processes=0,rss_bytes=0,threads=0,fds=0))
                    group['processes']+=1
                    for field in ('rss_bytes','threads','fds'):
                        if p.get(field) is not None:group[field]+=p[field]
                    if p.get('unavailable'):issue('process field permissions/availability incomplete')
                    key=(p['pid'],p['start_ticks']);old=last_process.get(key)
                    require(len(last_process)<8192 or key in last_process,'process history limit')
                    if old:
                        if p['cpu_ticks']<old['cpu_ticks']:issue('process CPU counter reset')
                        elif p['role']!=old['role']:issue('process role changed; crossing interval not attributed')
                        else:cpu[p['role']]=cpu.get(p['role'],0)+(p['cpu_ticks']-old['cpu_ticks'])/meta['clock_ticks']
                    last_process[key]=p
                for role,values in totals.items():
                    peak=peaks.setdefault(role,dict.fromkeys(values,0))
                    for field,value in values.items():peak[field]=max(peak[field],value)
                if row.get('process_gaps'):issue('process exit/permission/identity gaps; CPU observations are lower bounds')
                samples+=1;previous=row
            except (KeyError,TypeError,ValueError) as error:issue('invalid sample: '+str(error))
    if max_gap>meta['interval_seconds']*2:issue('sampling gap exceeds twice requested interval')
    if not meta.get('complete') or samples!=meta.get('samples') or samples<2:issue('capture incomplete or insufficient observations')
    if meta.get('observed_seconds',0)<meta.get('duration_seconds',0):issue('capture ended before requested duration')
    heating={}
    for target in (r['device_id'] for r in meta['targets']):
        idle=thermal.get((target,'idle'));heat=thermal.get((target,'heat'))
        resolution=meta.get('sensor_resolution_c')
        heating[target]=dict(idle_samples=idle['count'] if idle else 0,heating_samples=heat['count'] if heat else 0,
            idle_span_seconds=(idle['last_ns']-idle['first_ns'])/1e9 if idle else None,
            heating_span_seconds=(heat['last_ns']-heat['first_ns'])/1e9 if heat else None,
            final_minus_idle_c=sum(v for _,v in heat['tail'])/len(heat['tail'])-idle['total']/idle['count'] if idle and heat else None,
            idle_range_c=idle['maximum']-idle['minimum'] if idle else None,resolution_c=resolution,
            disposition='descriptive only; no automatic heating, safety, cleanup or primary verdict')
    span=(previous['monotonic_ns']-first)/1e9 if previous and first is not None else 0
    cores=previous.get('host',{}).get('logical_cpus',0) if previous else 0
    percent={role:100*seconds/span/cores for role,seconds in cpu.items()} if span>0 and cores>0 else {}
    return dict(contract=CONTRACT,session=meta['session'],samples=samples,issues=issues,max_gap_seconds=max_gap,
                sampled_cpu_percent_host_capacity_lower_bound=percent,process_group_sampled_peaks=peaks,
                host_cpu_busy_percent=host_usage['weighted_percent_seconds']/host_usage['covered_seconds'] if host_usage['covered_seconds'] else None,
                host_cpu_covered_seconds=host_usage['covered_seconds'],
                sampled_cpu_seconds_lower_bound=cpu,device_intervals=rates,ambient_corrected_heating=heating,
                cleanup_confirmed='not established by observer; inspect authoritative LVS artifacts and recovery',
                observer=meta,events=[json_file(p) for p in event_paths(directory)])


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);commands=p.add_subparsers(dest='command',required=True)
    c=commands.add_parser('capture');c.add_argument('--inventory',required=True);c.add_argument('--device-id',action='append',required=True)
    c.add_argument('--directory',required=True);c.add_argument('--seconds',type=int,required=True);c.add_argument('--interval',type=float,default=1)
    c.add_argument('--temperatures',action='store_true',help='explicit sensor reads may affect drive power management')
    c.add_argument('--sensor-resolution-c',type=float)
    m=commands.add_parser('mark');m.add_argument('--directory',required=True);m.add_argument('--event',required=True)
    m.add_argument('--phase',choices=('passive','idle','launch','cancel','low','heat','cooling'));m.add_argument('--ambient-c',type=float)
    m.add_argument('--pid',type=int);m.add_argument('--role',choices=('auxiliary','primary'),default='auxiliary')
    a=commands.add_parser('analyze');a.add_argument('--directory',required=True)
    args=p.parse_args(argv)
    if args.command=='capture':
        require(1<=args.seconds<=21600 and math.isfinite(args.interval) and 1<=args.interval<=60,'duration 1..21600 s, interval 1..60 s required')
        require(args.sensor_resolution_c is None or math.isfinite(args.sensor_resolution_c) and args.sensor_resolution_c>0,'invalid sensor resolution')
        result=capture(args)
    elif args.command=='mark':result=mark(args)
    else:result=analyze(args.directory)
    print(json.dumps(result,indent=2,allow_nan=False))


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError) as error:raise SystemExit(str(error))
