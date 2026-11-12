"""Isolated file-research contracts. No VM or host storage workloads in smoke."""
from copy import deepcopy
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

from scripts import storage_thermal_file_probe as probe


def rejected(call):
    try:call()
    except (RuntimeError,ValueError,OSError):return
    raise AssertionError('unsafe/unqualified research input accepted')


def run_file_research_fixture_checks():
    required={'io','cpu','memory','pids'}
    probe.validate_resources(1024**3,1,required)
    probe.validate_resources(1024**4,256,required)
    rejected(lambda:probe.validate_resources(128*1024**2,1,required))
    rejected(lambda:probe.validate_resources(1024**3,0,required))
    rejected(lambda:probe.validate_resources(1024**3,True,required))
    for missing in required:rejected(lambda:probe.validate_resources(1024**3,1,required-{missing}))
    for state in ('cold','warm','dirty','concurrent'):
        jobs=probe.campaign_jobs('access-'+state)
        assert len(jobs)==9
        assert sorted(job['mode'] for _,job in jobs if type(job['mode']) is int)==[0,0,0,1,1,1]
        assert sum(job['mode']=='control' for _,job in jobs)==3
        assert len({job['opaque'] for _,job in jobs})==9
    assert len(probe.campaign_jobs('lifetime-a'))==11
    assert len(probe.campaign_jobs('lifetime-b'))==14
    with patch.object(probe,'validate',side_effect=RuntimeError('outside fixture')),patch.object(probe.os,'open',side_effect=AssertionError('host target access')):
        rejected(lambda:probe.authorize('f00'))
    with tempfile.TemporaryDirectory() as directory:
        rejected(lambda:probe.regular(directory))
        path=Path(directory)/'ordinary';path.write_bytes(b'fixture')
        assert probe.regular(path)==path
    assert probe.BUDGET['read_bps']==2097152 and probe.BUDGET['workers']==1


def run_file_research_attribution_checks():
    from scripts import storage_thermal_causal_probe as causal
    with tempfile.TemporaryDirectory() as directory:
        folder=Path(directory)
        (folder/'kernel.trace').write_text('\n'.join([
            ' fio-9 [000] ..... 1.000001: block_bio_queue: 259,0 R 2056 + 128 [fio]',
            ' fio-9 [000] ..... 1.000002: block_bio_queue: 259,0 R 8000 + 8 [fio]',
            ' jbd2-4 [000] ..... 1.000003: block_bio_queue: 259,0 W 2056 + 8 [jbd2]',
            ' fio-9 [000] ..... 1.000004: block_bio_queue: 8,0 R 2056 + 128 [fio]',
        ]))
        record=dict(extents=[dict(physical=4096,length=65536)],preadv2_calls=['preadv2(...) = 65536 <0.001>'])
        result=probe.observe_case(folder,record,causal)
        assert result['read_bytes']==65536 and result['write_bytes']==4096
        assert result['logical_reads']==1 and len(result['corpus_bios'])==2
        record['extents']=[]
        assert probe.observe_case(folder,record,causal)['read_bytes']==0
    stats={'io.stat':'8:0 rbytes=7 wbytes=1 rios=2 wios=1\n259:0 rbytes=65536 wbytes=0 rios=1 wios=0\n'}
    assert probe.io_values(stats,'259:0')['rbytes']==65536
    assert probe.io_values(stats,'7:1')['rbytes']==0


def run_file_research_evidence_checks():
    jobs=probe.campaign_jobs('access-cold')
    result=dict(contract='lvs.storage_thermal.file_research.v1',production_eligibility=False,decision='INCONCLUSIVE',campaign='access-cold',
                capability=[dict(task=job,worker=dict(cleanup_confirmed=True),journal='CLEAN') for _,job in jobs])
    probe.verify(result)
    for field,value in (('decision','GO'),('production_eligibility',True),('contract','foreign')):
        bad=deepcopy(result);bad[field]=value;rejected(lambda:probe.verify(bad))
    bad=deepcopy(result);bad['capability'].pop();rejected(lambda:probe.verify(bad))
    bad=deepcopy(result);bad['capability'][0]['worker']['cleanup_confirmed']=False;rejected(lambda:probe.verify(bad))
    bad=deepcopy(result);bad['capability'][1]['task']=bad['capability'][0]['task'];rejected(lambda:probe.verify(bad))


def run_file_research_native_checks():
    from Modules.lvs_native_helpers import find_c_compiler,native_helper_build_command
    compiler=find_c_compiler()
    assert compiler is not None,'existing compiler required for research wrapper verification'
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        output=Path(directory)/'file-guard'
        command=native_helper_build_command(compiler,root/'scripts/storage_thermal_file_guard.c',output)
        subprocess.run(command+['-Wall','-Wextra','-Werror'],check=True,capture_output=True,timeout=30)
        for args in ([],['--fio-fd'],['--policy-test'],['--research-file','3','0','0','65536','0','1','1','aabbccddeeff']):
            child=subprocess.run([str(output),*args],stdin=subprocess.DEVNULL,capture_output=True,timeout=5)
            assert child.returncode==125,(args,child.stderr)
    # Assert the research/production API boundary, not whether a contributor
    # happens to have an authorized backend edit in their working tree.
    assert '--research-file' not in (root/'native/storage_thermal_guard.c').read_text()
    assert 'storage_thermal_file_probe' not in (root/'Modules/lvs_storage_thermal_runner.py').read_text()
