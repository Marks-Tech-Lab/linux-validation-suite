"""2B-4A research contracts only. No VM boot or host block access in smoke."""
from copy import deepcopy
import inspect
import json
from pathlib import Path
import struct
import tempfile
from unittest.mock import patch
from scripts import storage_thermal_active_probe as probe
from scripts import storage_thermal_fio_probe as original


def rejected(call):
    try:call()
    except (RuntimeError,ValueError,OSError):return
    raise AssertionError('unsafe research condition accepted')


def run_active_probe_fixture_checks():
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory)
        with patch.object(probe.subprocess,'run') as command:
            disk=probe.partition_image(root,'small-fixture',8192)
        assert disk.is_file() and disk.stat().st_size==probe.START_SECTOR*512+8192
        header=disk.read_bytes()[:512];assert header[510:]==b'\x55\xaa'
        status,_,kind,_,start,count=struct.unpack('<B3sB3sII',header[446:462])
        assert status==0x80 and kind==0x83 and start==2048 and count==16
        argv=command.call_args.args[0]
        assert argv[:3]==['mkfs.ext4','-q','-F'] and str(root/'small-fixture.ext4')==argv[-1]
        rejected(lambda:probe.partition_image(root,'small-fixture',8192))
        rejected(lambda:probe.partition_image(root,'../escape',8192))
        rejected(lambda:probe.partition_image(root,'invalid-size',True))
        rejected(lambda:probe.regular(root))
        assert probe.regular(disk)==disk
    # Matching root nonce is mandatory before examining or opening a target.
    token='aabbccddeeff'
    def fake_text(p,*a,**k):
        return json.dumps({'token':token}) if str(p)=='/fixture.json' else 'normal-host'
    with patch.object(probe.Path,'read_text',fake_text),patch.object(probe.os,'getuid',return_value=0),patch.object(probe,'serial',side_effect=AssertionError('identity examined before VM nonce')),patch.object(probe.os,'open',side_effect=AssertionError('host target open')):
        rejected(probe.validate_guest)


def valid_evidence():
    case=dict(name='idle-assist-A',cleanup_confirmed=True,journal='CLEAN',assist=True,cancelled=False,ordinary_writing=False,
        syscall=dict(aligned_bounded_reads=True,target_mutations=[],unknown_target_calls=[]),
        guard=dict(readonly_direct=True,capabilities=0,seccomp=2,no_new_privs=1),
        exit=0,fio=dict(read=dict(total_ios=21,io_bytes=21*65536,runtime=3000),write=dict(total_ios=0),trim=dict(total_ios=0),error=0))
    phases=[]
    for name in ('idle-control-A','idle-assist-A','idle-assist-B','idle-control-B','busy-control-A','busy-assist-A','busy-assist-B','busy-control-B','cancel'):
        row=deepcopy(case);row['name']=name;row['assist']='control' not in name
        row['ordinary_writing']=name.startswith('busy');row['ordinary_writes']=[{'bytes':4096}] if row['ordinary_writing'] else []
        if name=='cancel':row.update(cancelled=True,exit=128)
        phases.append(row)
    ownership=dict(cleanup_confirmed=True,workers=[dict(io_admission='committed')])
    rows=[]
    for name in probe.LIFECYCLE:
        row=dict(name=name,rejected=True,exit=125,ownership=deepcopy(ownership))
        if name in ('normal','cancel','clean-ENOSPC','clean-EIO'):row.update(exit=0,journal='ARMED' if name.startswith('clean-') else 'CLEAN')
        if name=='guard-policy':row['mutation_attempts_denied']=True
        if name.startswith('durable-'):row.update(target_opened=False,fresh_blocked=True)
        rows.append(row)
    return dict(contract='lvs.storage_thermal.active_access_research.v1',paired_cases=phases,lifecycle_cases=rows,
        supervisor_death={'fresh_blocked':True},uncertain_cleanup=dict(before='ARMED',after='CLEAN',victim_untouched=True),
        visibility_change=dict(new_open_rejected=True,original_lease_closed=True,owned_cleanup=True),
        misalignment=22,readonly_write=9,native_expiry=dict(native_deadline_rejected=True,target_descriptor_transferred=False),provider_decision='NO-GO')


def run_active_probe_evidence_checks():
    value=valid_evidence();probe.verify(value)
    for field,changed in (('aligned_bounded_reads',False),('target_mutations',['write']),('unknown_target_calls',['unknown'])):
        bad=deepcopy(value);bad['paired_cases'][1]['syscall'][field]=changed;rejected(lambda:probe.verify(bad))
    for changed in ('GO','PASS','COMPLETED'):
        bad=deepcopy(value);bad['provider_decision']=changed;rejected(lambda:probe.verify(bad))
    bad=deepcopy(value);bad['paired_cases'].pop();rejected(lambda:probe.verify(bad))
    bad=deepcopy(value);bad['supervisor_death']['fresh_blocked']=False;rejected(lambda:probe.verify(bad))
    bad=deepcopy(value);bad['paired_cases'][1]['fio']['read']['total_ios']=0;rejected(lambda:probe.verify(bad))


def run_active_probe_production_boundary_checks():
    from Modules.lvs_storage_thermal_targets import ThermalTargets
    opener=inspect.getsource(ThermalTargets.open)
    assert 'os.O_EXCL' in opener and 'self.revalidate' in opener
    research=inspect.getsource(probe.open_target)
    assert 'os.O_EXCL' not in research and 'os.O_RDONLY|os.O_DIRECT|os.O_CLOEXEC|os.O_NOFOLLOW' in research
    assert 'validate_guest(mounted=True)' in research
    assert inspect.signature(original.host).parameters['fixture_builder'].default is None
    host=inspect.getsource(original.host)
    assert 'if not layout:' in host and "manifest['image_before'] == manifest['image_after']" in host
    # Research refuses arbitrary device, QEMU and fio options at the CLI.
    source=Path(probe.__file__).read_text()
    assert "parser.add_argument('--device'" not in source and 'os.sync()' not in source
    guard=(Path(__file__).resolve().parents[1]/'native/storage_thermal_guard.c').read_text()
    assert 'BLKFLSBUF' in guard and '--invalidate=0' in guard and 'stage_target' in guard


def run_active_causal_trace_checks():
    from scripts import storage_thermal_causal_probe as causal

    trace = '\n'.join([
        ' fio-19 [000] ..... 5.000001: kiocb_wait: (kiocb_write_and_wait+0x0) mapping=0x1234 offset=65536 bytes=65536',
        ' fio-19 [000] ..... 5.000003: kiocb_done: (blkdev_read_iter+0xd6 <- kiocb_write_and_wait) rc=0',
        ' fio-19 [000] ..... 5.000005: block_rq_issue: 8,0 RS 65536 () 128 + 128',
        ' jbd2/sda1-7 [000] ..... 5.000006: block_rq_issue: 8,0 FF 0 () 0 + 0',
        ' fio-19 [000] ..... 5.000007: block_rq_issue: 8,16 W 4096 () 16 + 8',
    ])
    result = causal.correlate(trace, {19}, '8,0')
    assert result['target_requests'] == {'worker': {'RS': 1}, 'other': {'FF': 1}}
    assert result['unmatched_wait_entries'] == 0
    sample, = result['write_and_wait_samples']
    assert sample['pid'] == 19 and sample['end'] > sample['start']
    assert 'mapping=0x1234' in sample['mapping_and_range']
    assert causal.correlate(trace.splitlines()[0], {19}, '8,0')['unmatched_wait_entries'] == 1

    valid = '1794347971.040055 pread64(6</dev/sda<block 8:0>>, ""..., 65536, 65536) = 65536 <0.000741>'
    assert causal.target_reads(valid, 131072) == ([65536], [.000741])
    assert causal.target_reads(valid.replace('/dev/sda<', '/dev/sda1<'), 131072) == ([], [])
    rejected(lambda: causal.target_reads(valid, 65536))
    rejected(lambda: causal.target_reads(valid.replace(') = 65536', ') = 1024'), 131072))
    rejected(lambda: causal.target_reads(valid.replace(' <0.000741>', ''), 131072))
    with tempfile.TemporaryDirectory() as directory:
        other_kernel = Path(directory)/'other-image'
        other_kernel.write_bytes(b'wrong kernel image')
        rejected(lambda: causal.require_kernel_image(other_kernel))


def run_active_targeted_contract_checks():
    from scripts import storage_thermal_mapping_probe as targeted
    result = dict(contract='lvs.storage_thermal.targeted_research.v1', disposition='INCONCLUSIVE',
                  startup=dict(runs=[dict(exit=0),dict(exit=0)]), mapping=[
        dict(mode='clean', before=dict(tags=0,pages=0),worker=dict(exit=0),cleanup_confirmed=True),
        dict(mode='dirty', before=dict(tags=2,pages=16),worker=dict(exit=0),cleanup_confirmed=True),
        dict(mode='inflight-cancel', before=dict(tags=4,pages=16),worker=dict(exit=128,cancelled=True),cleanup_confirmed=True)])
    targeted.verify(result)
    for index, tags in ((0,2),(1,0),(2,2)):
        invalid=deepcopy(result);invalid['mapping'][index]['before']['tags']=tags
        rejected(lambda:targeted.verify(invalid))
    invalid=deepcopy(result);invalid['mapping'][1]['cleanup_confirmed']=False
    rejected(lambda:targeted.verify(invalid))
    with patch.object(probe,'validate_guest',side_effect=RuntimeError('outside disposable VM')), patch.object(targeted.os,'open',side_effect=AssertionError('host device access')):
        rejected(lambda:targeted.mapping_open(probe,write=True))
    # A root-drive identity can never authorize destructive mapping-fixture writes.
    with patch.object(probe,'validate_guest',return_value='aabbccddeeff'), patch.object(probe,'serial',return_value='LVS-aabbccddeeff'), patch.object(targeted.os,'open',side_effect=AssertionError('wrong device opened')):
        rejected(lambda:targeted.mapping_open(probe,write=True))
