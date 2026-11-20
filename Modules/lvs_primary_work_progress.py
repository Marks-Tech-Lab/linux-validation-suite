"""Supplementary native completed work, sharing stage/raw-telemetry time base.

No interpolation across warmup/trims, missing records or counter resets. These
measure logical workload work, not retired instructions or physical DRAM traffic.
Missing/failed evidence never changes the primary hardware verdict.
"""
from __future__ import annotations
import json
import math
from pathlib import Path

CONTRACT = 'lvs_primary_work_v1'
COUNTERS = ('completed_units', 'processed_bytes', 'verified_bytes')


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('invalid monotonic timestamp')
    return float(value)


def counter(value):
    if type(value) is not int or not 0 <= value < 2**64:
        raise ValueError('invalid uint64 counter')
    return value


def analyze_primary_work(worker, window):
    meta = worker.get('work_progress')
    result = dict(contract=CONTRACT, quality='unavailable', reasons=[], threads=[],
                  clock='linux_CLOCK_MONOTONIC', rates=None,
                  boundary_policy='both_worker_publications_inside_trimmed_window_no_interpolation',
                  physical_dram_bandwidth_measured=False,
                  telemetry_analysis_quality=(getattr(window,'analysis_evidence',{}) or {}).get('quality','not_assessed'),
                  analysis_intent=getattr(window,'analysis_intent','legacy_unspecified'),
                  arithmetic_correctness='existing worker verification; no new arithmetic oracle')
    if not isinstance(meta, dict) or meta.get('contract') != CONTRACT:
        result['reasons'].append('no recognized completed-work contract');return result
    kind = meta.get('kind');result['kind'] = kind
    try:
        if kind not in ('sse2', 'sse2_int', 'memory'):raise ValueError('unsupported completed-work kind')
        n = meta.get('threads')
        if type(n) is not int or n <= 0:raise ValueError('invalid thread count')
        if type(worker.get('threads')) is not int or worker.get('threads') != n:raise ValueError('terminal thread count mismatch')
        if type(worker.get('verify_passes')) is not int or worker.get('verify_passes',0)<=0 or (kind=='memory' and worker.get('verification_complete') is not True):raise ValueError('verification coverage unavailable')
        if worker.get('kind') != ('memory' if kind == 'memory' else 'cpu'):raise ValueError('worker kind mismatch')
        if kind != 'memory' and worker.get('kernel_flavor') != kind:raise ValueError('kernel mismatch')
        if meta.get('persistence_error') is not False:raise ValueError('progress persistence unconfirmed')
        if worker.get('error_count') != 0 or type(worker.get('error_count')) is not int:raise ValueError('worker verification error or unavailable verification')
        if type(worker.get('observed_exit_code')) is not int or worker['observed_exit_code'] != 0:raise ValueError('clean worker exit not established')
        start = number(window.started_monotonic) + number(window.trim_start_seconds)
        end = number(window.ended_monotonic) - number(window.trim_end_seconds)
        if end <= start:raise ValueError('invalid actual trimmed interval')
        minimum=getattr(window,'analysis_minimum_usable_seconds',None)
        if minimum is not None and end-start<number(minimum):raise ValueError('actual trimmed interval below authored duration requirement')
        result.update(window_start_monotonic_seconds=start, window_end_monotonic_seconds=end)
        path = Path(str(worker['result_path']) + '.work.jsonl');result['path'] = str(path)
        previous = {};rows = [];last_sequence = -1;last_snapshot = -1.;last_final = False;pid = None
        totals = {i:dict(thread_index=i,intervals=0,observed_seconds=0.,**{c:0 for c in COUNTERS})for i in range(n)}
        with path.open() as f:
            while True:
                line = f.readline(16*1024**2+1)
                if not line:break
                if len(line)>16*1024**2 or not line.endswith('\n'):raise ValueError('oversized or incomplete progress record')
                row = json.loads(line)
                if row.get('contract') != CONTRACT or row.get('kind') != kind:raise ValueError('foreign progress record')
                identity = counter(row.get('pid'))
                if pid is None:pid = identity
                if not identity or identity != pid or (worker.get('process_pid') is not None and identity != worker['process_pid']):raise ValueError('process identity mismatch')
                sequence = counter(row.get('sequence'));stamp = number(row.get('monotonic_seconds'))
                if sequence != last_sequence+1 or stamp <= last_snapshot or last_final:raise ValueError('missing, stale or reordered snapshot')
                last_sequence,last_snapshot,last_final=sequence,stamp,row.get('final')
                if type(last_final) is not bool:raise ValueError('invalid final marker')
                number(row.get('realtime_seconds'));number(row.get('clock_pair_uncertainty_seconds'))
                rows = row.get('threads')
                if type(rows) is not list or len(rows) != n:raise ValueError('incomplete thread observation')
                seen=set()
                for thread in rows:
                    i=thread.get('thread_index')
                    if type(i) is not int or i not in totals or i in seen:raise ValueError('duplicate or foreign thread')
                    seen.add(i);t=number(thread.get('monotonic_seconds'))
                    values={c:counter(thread.get(c))for c in COUNTERS}
                    if counter(thread.get('error_count')):raise ValueError('thread verification failed')
                    if type(thread.get('final')) is not bool or t>stamp:raise ValueError('invalid thread publication')
                    if kind=='memory' and values['verified_bytes']>values['processed_bytes']:raise ValueError('contradictory RAM work')
                    if kind!='memory' and (values['processed_bytes'] or values['verified_bytes']):raise ValueError('contradictory CPU work')
                    if not t:
                        if any(values.values()) or thread['final']:raise ValueError('unstarted thread claims work')
                        continue
                    old=previous.get(i)
                    if old:
                        ot,ov,of=old
                        if t<ot or any(values[c]<ov[c]for c in COUNTERS):raise ValueError('counter or clock reset')
                        if t==ot:
                            if values!=ov or thread['final']!=of:raise ValueError('changed frozen publication')
                            continue
                        if of:raise ValueError('work after final thread publication')
                        if start<=ot<t<=end:
                            total=totals[i];total['intervals']+=1;total['observed_seconds']+=t-ot
                            for c in COUNTERS:total[c]+=values[c]-ov[c]
                    previous[i]=(t,values,thread['final'])
        if json.dumps(meta.get('final_threads'),sort_keys=True,allow_nan=False) != json.dumps(rows,sort_keys=True,allow_nan=False):raise ValueError('terminal/sidecar final work disagreement')
        if not last_final or len(previous)!=n or not all(v[2]for v in previous.values()):raise ValueError('final worker observations unavailable')
        if meta.get('snapshot_count') != last_sequence+1:raise ValueError('terminal/sidecar snapshot disagreement')
        if not all(v['intervals'] and v['observed_seconds']>0 for v in totals.values()):raise ValueError('insufficient in-window observations for every thread')
        for v in totals.values():
            v['coverage_fraction']=v['observed_seconds']/(end-start)
            v['rates']={c:v[c]/v['observed_seconds']for c in COUNTERS}
        result['threads']=list(totals.values());result['quality']='observed'
        result['rates']={c:sum(v['rates'][c]for v in totals.values())for c in COUNTERS}
        result['aggregation']='sum of per-thread observed-interval mean rates; per-thread coverage retained'
        result['units']='completed_sse2_loop_iterations' if kind!='memory' else 'actual_64_byte_write_regions'
        # SSE2 body: four packed multiplies, three adds, one subtract, four
        # FP32 lanes. Min/max/checkpoint instructions are explicitly excluded.
        if kind=='sse2':
            result['algorithmic_fp32_operations_per_iteration']=32
            result['algorithmic_fp32_operations_per_second']=result['rates']['completed_units']*32
            result['operation_scope']='source/disassembly-qualified algorithmic FP32 add/sub/mul work; not hardware retired instructions or a new numerical proof'
        return result
    except (OSError,ValueError,TypeError,KeyError,OverflowError) as exc:
        result['reasons'].append(str(exc));result['quality']='unavailable';result['rates']=None
        return result


def attach_primary_work(window):
    for worker in window.worker_results or []:
        if 'work_progress' in worker:
            worker['primary_work_analysis']=analyze_primary_work(worker,window)
