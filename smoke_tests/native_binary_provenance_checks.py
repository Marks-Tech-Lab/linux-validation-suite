"""Normal launch/artifact regressions; no hardware acceptance or binary attestation."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from Modules import lvs_native_binary_provenance as binary
from Modules.lvs_stage_launch_plan import StageLaunchCommand
from Modules.lvs_stage_process_control import launch_stage_processes_from_plan, stop_stage_processes
from Modules.lvs_worker_evidence import apply_worker_entry_context
from Modules.lvs_worker_integrity import worker_verification_satisfied
from Modules.lvs_compat_export_helpers import preserve_legacy_worker_evidence_contract
from Modules.lvs_core import JsonStore
from Modules.lvs_source_review import source_identity, review_result_source_payloads
from Modules.lvs_summary_text import SummaryTextBuilder, summary_with_recorded_source
from smoke_tests.source_provenance_checks import _fixture
from Modules.lvs_source_provenance import collect_source_provenance


def run_native_binary_provenance_checks():
    with TemporaryDirectory(prefix="lvs_native_identity_") as tmp:
        root = Path(tmp)
        sleeper = shutil.which("sleep")
        assert sleeper
        image = root / "renamed-helper"
        shutil.copyfile(sleeper, image); image.chmod(0o700)
        snapshot = binary.executable_snapshot(image)
        assert snapshot["sha256"] == hashlib.sha256(image.read_bytes()).hexdigest()
        assert snapshot["size_bytes"] == image.stat().st_size
        assert snapshot["architecture"] in {"x86_64", "aarch64", "x86", "unknown"}
        assert str(root) not in json.dumps(snapshot)
        for machine, arch in ((62, "x86_64"), (183, "aarch64")):
            fake = bytearray(64); fake[:6] = b"\x7fELF\x02\x01"; struct.pack_into('<H', fake, 18, machine)
            fixture = root / arch; fixture.write_bytes(fake)
            assert binary.executable_snapshot(fixture)["architecture"] == arch
        assert binary.executable_snapshot(root / 'missing')["status"] == "unavailable"
        with patch.object(binary.os, "open", side_effect=PermissionError(13, "private path")):
            assert 'private path' not in json.dumps(binary.executable_snapshot(image))
        with patch.object(binary, "MAX_BYTES", 1):
            assert binary.executable_snapshot(image)["reason"] == "size_budget_exceeded"
        with patch.object(binary, "MAX_HASH_SECONDS", -1):
            assert binary.executable_snapshot(image)["status"] == "unavailable"
        real_read = binary.os.read
        modified = [False]
        def mutating(fd, count):
            raw = real_read(fd, count)
            if raw and not modified[0]:
                modified[0] = True
                with image.open('ab') as output: output.write(b'changed')
            return raw
        with patch.object(binary.os, 'read', side_effect=mutating):
            assert binary.executable_snapshot(image)["status"] == "unstable"
        shutil.copyfile(sleeper, image)
        # Both native families, arbitrary actual executable path, normal launch,
        # actual /proc image association, ordinary and abnormal termination.
        for family in ('cpu', 'memory'):
            entries = launch_stage_processes_from_plan([
                StageLaunchCommand(family, [str(image), '30'], native_helper_family=family)], stage_id='fixture')
            assert len(entries) == 1
            entry = entries[0]
            try:
                running_payload={}
                apply_worker_entry_context(running_payload,entry)
                assert running_payload['native_executable_provenance']['post_execution']['status']=='not_observed'
                assert binary.native_executable_identity(entry.native_executable_provenance)['status'] == 'process_observed'
                assert entry.native_executable_provenance['process_executable']['pid'] == entry.process.pid
                assert entry.native_executable_provenance['prelaunch']['sha256'] == snapshot['sha256']
                # Same bytes, new inode: not allowed to conceal pathname replacement.
                replacement = root / 'replacement'
                shutil.copyfile(sleeper, replacement); replacement.chmod(0o700)
                replacement.replace(image)
            finally:
                stop_stage_processes(entries)
            payload = {'status': 'error', 'error_count': 1, 'verification_required': True}
            apply_worker_entry_context(payload, entry, return_code=entry.process.returncode)
            evidence = payload['native_executable_provenance']
            identity = binary.native_executable_identity(evidence)
            assert identity['post_execution_state'] == 'matching_bytes'
            assert identity['same_post_execution_file_object'] is False
            assert not worker_verification_satisfied(payload)
            assert preserve_legacy_worker_evidence_contract(payload)['native_executable_provenance'] == evidence
            assert str(root) not in json.dumps(evidence)
            assert len(json.dumps(evidence)) < 5000  # Three fixed observations, no growing history.
            changed = deepcopy(evidence); changed['post_execution']['sha256'] = '0' * 64
            assert binary.native_executable_identity(changed)['post_execution_state'] == 'different_bytes'
            changed['prelaunch']['sha256'] = '1' * 64
            assert binary.native_executable_identity(changed)['prelaunch_comparison'] == 'different_bytes'
            changed['process_executable']['sha256'] = None
            assert binary.native_executable_identity(changed)['status'] == 'prelaunch_only'
            evidence_fixture = deepcopy(evidence)
        def replacing_launch(cmd, **kwargs):
            replacement = root/'between_hash_and_exec'
            replacement.write_bytes(Path(sleeper).read_bytes()+b'replacement')
            replacement.chmod(0o700);replacement.replace(image)
            return subprocess.Popen(cmd,**kwargs)
        entries=launch_stage_processes_from_plan([StageLaunchCommand('cpu',[str(image),'30'],native_helper_family='cpu')],
            stage_id='race',popen_factory=replacing_launch)
        try:
            identity=binary.native_executable_identity(entries[0].native_executable_provenance)
            assert identity['status']=='process_observed' and identity['prelaunch_comparison']=='different_bytes'
            assert identity['same_prelaunch_file_object'] is False
        finally: stop_stage_processes(entries)
        interrupted=[]
        def capture_launch(cmd,**kwargs):
            child=subprocess.Popen(cmd,**kwargs);interrupted.append(child);return child
        with patch('Modules.lvs_stage_process_control.observe_process_executable',side_effect=KeyboardInterrupt):
            try:
                launch_stage_processes_from_plan([StageLaunchCommand('cpu',[str(image),'30'],native_helper_family='cpu')],
                    stage_id='interrupt',popen_factory=capture_launch)
                raise AssertionError('interrupt swallowed')
            except KeyboardInterrupt: pass
        assert interrupted and interrupted[0].poll() is not None
        selected, evidence = binary.begin_native_executable([str(image)], 'cpu', None)
        with patch.object(binary, 'executable_snapshot', return_value={'status': 'unavailable'}):
            binary.observe_process_executable(evidence, SimpleNamespace(pid=123, poll=lambda: None))
        assert binary.native_executable_identity(evidence)['status'] == 'prelaunch_only'
        with patch.object(binary, 'executable_snapshot', side_effect=RuntimeError('private')):
            binary.observe_process_executable(evidence, SimpleNamespace(pid=123, poll=lambda: None))
        assert evidence['process_executable']['reason'] == 'process_observation_failed'
        binary.observe_process_executable(evidence, SimpleNamespace(pid=123, poll=lambda: 1))
        assert evidence['process_executable']['reason'] == 'process_not_running'
        assert binary.native_executable_identity({})['status'] == 'not_recorded'
        assert binary.native_executable_identity({'contract_version': 1})['status'] == 'invalid_evidence'
        assert binary.native_binary_reviews({'Segments': []}) == []
        # Persistence path: worker context -> stage manifest -> compatibility ->
        # normal report/QA readers. No Git, stamp, executable reads during review.
        worker = {'kind': 'cpu', 'process_pid': evidence_fixture['process_executable']['pid'],
                  'native_executable_provenance': evidence_fixture}
        manifest = {'stage_windows': [{'stage_id': 'fixture', 'worker_results': [worker]}]}
        custom = {'Segments': [{'StageId': 'fixture', 'WorkerResults': [worker]}]}
        JsonStore.write(root/'run_manifest.json', manifest)
        JsonStore.write(root/'parsed_results_extended.json', manifest)
        JsonStore.write(root/'parsed_results_custom.json', preserve_legacy_worker_evidence_contract(custom))
        with patch.object(binary, 'executable_snapshot', side_effect=AssertionError('no retrospective hashing')):
            reviews = binary.load_native_binary_reviews(root)
            assert reviews == binary.native_binary_reviews(custom)
            assert snapshot['sha256'] in binary.native_binary_text(reviews)
        worker['process_pid'] += 1
        rejected = binary.native_binary_reviews(custom)[0]
        assert rejected['status'] == 'prelaunch_only' and rejected['process_rejection_reason'] == 'worker_pid_mismatch'
        assert rejected['post_execution_reference'] == 'prelaunch'
        from smoke_tests.neon_fp32_fma_checks import _export_worker_fixture, _worker_export_round_trip
        from Modules.lvs_worker_evidence import worker_result_events_from_payload
        from Modules.lvs_report_data import compile_report_data
        from Modules.lvs_report_html import render_report_html
        from Modules.linux_validation_suite_service import SuiteAppService
        from Modules.lvs_result_validation import ResultValidationFacade
        from Modules.lvs_result_comparison import ResultComparisonFacade
        from Modules.lvs_pre_import_sanity import PreImportSanityFacade
        from Modules.lvs_result_artifacts import ResultArtifactFacade
        from Modules.lvs_tui_result_presentation import qa_result_review_presentation
        arithmetic = _export_worker_fixture()
        arithmetic.update(native_executable_provenance=deepcopy(evidence_fixture),
                          process_pid=evidence_fixture['process_executable']['pid'])
        run = root/'normal_artifacts'
        exported = _worker_export_round_trip(arithmetic, run)
        observed = binary.load_native_binary_reviews(run, parsed=exported)
        assert observed[0]['status'] == 'process_observed'
        report = compile_report_data(run)
        assert report['stages'][0]['native_executable_review'] == observed
        assert snapshot['sha256'] in render_report_html(report)
        assert snapshot['sha256'] in (run/'run_summary.txt').read_text()
        service = SuiteAppService.__new__(SuiteAppService)
        service.summary_exporter = SummaryTextBuilder()
        service.result_validation = ResultValidationFacade(root)
        service.result_comparison = ResultComparisonFacade()
        service.pre_import_sanity = PreImportSanityFacade(root, service.result_validation, service.summary_exporter)
        service.result_artifacts = ResultArtifactFacade(root)
        qa = service.qa_result_review_payload(run,refresh_summary=False)
        assert qa['native_executable_review'] == observed
        assert snapshot['sha256'] in qa_result_review_presentation(qa,'fixture')
        killed=deepcopy(arithmetic);killed.update(observed_exit_code=-9, forced_kill=True)
        events=worker_result_events_from_payload(killed,'fixture')
        assert any(event['category']=='worker_exit' and event['severity']=='error' for event in events)
        for missing in ({'status':'unavailable'},{'status':'unstable'}):
            unavailable=deepcopy(evidence_fixture);unavailable['post_execution']=missing
            assert binary.native_executable_identity(unavailable)['post_execution_state']=='unavailable'
        # Use the established native build function, not a new build workflow.
        from Modules.lvs_native_helpers import resolve_native_helper_status
        source, executable = root/'cpu_stress_helper.c', root/'rebuilt'
        source.write_text('int main(void) { return 0; }\n')
        compiler = shutil.which('gcc') or shutil.which('cc')
        assert compiler
        def build(cmd): return subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        status = resolve_native_helper_status(source=source, binary=executable, compiler=compiler, reason_label='CPU', build_runner=build)
        assert status['available'] and status['built']
        first_hash = binary.executable_snapshot(executable)['sha256']
        reused = resolve_native_helper_status(source=source, binary=executable, compiler=compiler, reason_label='CPU', build_runner=lambda _: (_ for _ in ()).throw(AssertionError('unexpected rebuild')))
        assert reused['available'] and not reused['built']
        source.write_text('int main(void) { return 7; }\n')
        os.utime(source, ns=(executable.stat().st_mtime_ns+10000000,)*2)
        rebuilt = resolve_native_helper_status(source=source, binary=executable, compiler=compiler, reason_label='CPU', build_runner=build)
        assert rebuilt['built']
        _, current = binary.begin_native_executable([str(executable)], 'cpu', None)
        assert current['prelaunch']['sha256'] != first_hash


def run_source_endpoint_summary_checks():
    with TemporaryDirectory(prefix='lvs_source_endpoints_') as tmp:
        root=Path(tmp); _fixture(root)
        initial=collect_source_provenance(root); final=deepcopy(initial)
        payload={'SystemInfo': {'SourceProvenance': initial}}
        builder=SummaryTextBuilder()
        for flag in (None, False, True):
            assert source_identity(initial, changed=flag)['change_status']=='unknown'
        for changed in (False, True):
            final['source']['digest'] = 'f'*64 if changed else initial['source']['digest']
            current={**payload, 'source_provenance_end':final, 'source_changed_during_run':changed}
            expected='changed' if changed else 'unchanged endpoints'
            assert 'Source changes during execution: '+expected in builder.build(current)
            manifest={'source_provenance':initial, 'source_provenance_end':final, 'source_changed_during_run':changed}
            JsonStore.write(root/'run_manifest.json',manifest)
            assert 'Source changes during execution: '+expected in builder.build(summary_with_recorded_source(payload,root))
            conflict={**current, 'source_changed_during_run':not changed}
            assert 'Source changes during execution: conflicting evidence' in builder.build(conflict)
        manifest['source_provenance_end']=deepcopy(initial);manifest['source_changed_during_run']=False
        extended={**manifest,'source_provenance_end':final,'source_changed_during_run':True}
        assert review_result_source_payloads([manifest,extended],correlate=False)['change_status']=='conflicting_evidence'
        extended['source_changed_during_run']=False
        assert review_result_source_payloads([manifest,extended],correlate=False)['change_status']=='conflicting_evidence'
        assert source_identity(initial,end=initial,changed='false')['change_status']=='conflicting_evidence'
        for missing in (None,{}, {'source': {'status':'incomplete'}}):
            assert source_identity(initial,end=missing,changed=False)['change_status']=='unknown'
        assert 'Source changes during execution: unknown' in builder.build(payload)


def run_native_binary_rejection_checks():
    """Adversarial observations through the actual artifact and review pipeline."""
    from smoke_tests.neon_fp32_fma_checks import _export_worker_fixture, _worker_export_round_trip
    from Modules.lvs_report_data import compile_report_data
    from Modules.lvs_report_html import render_report_html
    from Modules.linux_validation_suite_service import SuiteAppService
    from Modules.lvs_result_validation import ResultValidationFacade
    from Modules.lvs_result_comparison import ResultComparisonFacade
    from Modules.lvs_pre_import_sanity import PreImportSanityFacade
    from Modules.lvs_result_artifacts import ResultArtifactFacade
    from Modules.lvs_tui_result_presentation import qa_result_review_presentation
    from contextlib import redirect_stdout
    from io import StringIO

    def observation(digest, inode=42):
        return dict(status='observed', algorithm='sha256', sha256=digest*64, size_bytes=4096,
                    file_device=1, file_inode=inode, architecture='aarch64', elf_class_bits=64,
                    observed_at='2026-10-21T00:00:00+00:00', started_monotonic_seconds=1.0,
                    elapsed_seconds=0.001, modified_time_ns=1, changed_time_ns=1)

    original=dict(contract_id=binary.CONTRACT, contract_version=1, kind='native_executable_provenance',
                  helper_family='cpu', worker_pid=12345, prelaunch=observation('a'),
                  process_executable={**observation('b'), 'source':'linux_proc_pid_exe', 'pid':12345,
                                      'running_after_observation':True, 'path_deleted':False},
                  post_execution=observation('b'))
    mutations=[('unknown_provider',lambda e:e['process_executable'].update(source='unrecognized_provider')),
               ('missing_process_observation',lambda e:e.pop('process_executable')),
               ('missing_provider',lambda e:e['process_executable'].pop('source')),
               ('missing_pid',lambda e:e['process_executable'].pop('pid')),
               ('wrong_pid',lambda e:e['process_executable'].update(pid=23456)),
               ('missing_owner_pid',lambda e:e.pop('worker_pid')),
               ('wrong_owner_pid',lambda e:e.update(worker_pid=23456)),
               ('missing_running_state',lambda e:e['process_executable'].pop('running_after_observation')),
               ('missing_deleted_state',lambda e:e['process_executable'].pop('path_deleted')),
               ('missing_inode',lambda e:e['process_executable'].pop('file_inode')),
               ('malformed_digest',lambda e:e['process_executable'].update(sha256='not-a-digest')),
               ('inconsistent_status',lambda e:e['process_executable'].update(status='unstable'))]
    for bad in (None,False,True,0,-1,'12345',1.5,[],{}):
        mutations.append(('bad_pid_'+repr(bad),lambda e,bad=bad:e['process_executable'].update(pid=bad)))
        mutations.append(('bad_owner_'+repr(bad),lambda e,bad=bad:e.update(worker_pid=bad)))
    for bad in (None,0,1,'true',[],{}):
        mutations.append(('bad_running_'+repr(bad),lambda e,bad=bad:e['process_executable'].update(running_after_observation=bad)))
        if bad is not None:  # Explicit unknown link state does not invalidate an opened proc image.
            mutations.append(('bad_deleted_'+repr(bad),lambda e,bad=bad:e['process_executable'].update(path_deleted=bad)))
    cases=[]
    for label,mutate in mutations:
        # Rejected B cannot conceal B!=A, nor stop a legitimate A==A comparison.
        for post in ('a','b'):
            evidence=deepcopy(original);mutate(evidence);evidence['post_execution']=observation(post)
            cases.append((label+'_post_'+post,evidence,12345,'prelaunch_only','prelaunch',
                          'matching_bytes' if post=='a' else 'different_bytes'))
    for context in (None,False,True,0,-1,'12345',1.5,23456):
        cases.append(('bad_context_'+repr(context),deepcopy(original),context,'prelaunch_only','prelaunch','different_bytes'))
    for kind in ('unrecognized_provider','wrong_pid','bad_running', 'procfs_unavailable'):
        evidence=deepcopy(original);evidence['prelaunch']={'status':'unavailable'}
        if kind=='unrecognized_provider': evidence['process_executable']['source']='unknown'
        elif kind=='wrong_pid': evidence['process_executable']['pid']=23456
        elif kind=='bad_running': evidence['process_executable']['running_after_observation']=None
        else: evidence['process_executable']={'status':'unavailable','reason':'file_unavailable','errno':13}
        cases.append(('no_reference_'+kind,evidence,12345,'unavailable','unavailable','unavailable'))
    for label,pre,post in [('all_match','b','b'),('valid_process_differs','a','b'),('post_changed','a','a')]:
        evidence=deepcopy(original);evidence['prelaunch']=observation(pre);evidence['post_execution']=observation(post)
        cases.append((label,evidence,12345,'process_observed','process_executable',
                      'matching_bytes' if post=='b' else 'different_bytes'))
    for label,state in [('short_lived',{'status':'unavailable','reason':'process_not_running'}),
                        ('missing_procfs',{'status':'unavailable','reason':'file_unavailable','errno':2}),
                        ('inaccessible_procfs',{'status':'unavailable','reason':'file_unavailable','errno':13})]:
        evidence=deepcopy(original);evidence['process_executable']=state;evidence['post_execution']=observation('a')
        cases.append((label,evidence,12345,'prelaunch_only','prelaunch','matching_bytes'))
    evidence=deepcopy(original);evidence['process_executable']['running_after_observation']=False
    cases.append(('exited_after_valid_observation',evidence,12345,'process_observed','process_executable','matching_bytes'))
    evidence=deepcopy(original);evidence['process_executable']['path_deleted']=None
    cases.append(('unavailable_link_state',evidence,12345,'process_observed','process_executable','matching_bytes'))
    evidence=deepcopy(original);evidence['post_execution']=observation('b',inode=99)
    cases.append(('identical_bytes_replacement',evidence,12345,'process_observed','process_executable','matching_bytes'))
    evidence=deepcopy(original);evidence['prelaunch']={'status':'unavailable'}
    cases.append(('valid_process_without_prelaunch',evidence,12345,'process_observed','process_executable','matching_bytes'))
    evidence=deepcopy(original);evidence.update(worker_pid=None,process_executable={'status':'not_observed'},post_execution=observation('a'))
    cases.append(('failed_launch_metadata',evidence,None,'prelaunch_only','prelaunch','matching_bytes'))
    for label in ('cancelled_before_verification','unexpected_exit','forced_kill'):
        cases.append((label,deepcopy(original),12345,'process_observed','process_executable','matching_bytes'))

    with TemporaryDirectory(prefix='lvs_native_rejection_') as tmp:
        root=Path(tmp)
        service=SuiteAppService.__new__(SuiteAppService);service.summary_exporter=SummaryTextBuilder()
        service.result_validation=ResultValidationFacade(root);service.result_comparison=ResultComparisonFacade()
        service.pre_import_sanity=PreImportSanityFacade(root,service.result_validation,service.summary_exporter)
        service.result_artifacts=ResultArtifactFacade(root)
        for index,(label,evidence,pid,status,reference,post) in enumerate(cases):
            untouched=deepcopy(evidence)
            expected=binary.native_executable_identity(evidence,expected_worker_pid=pid)
            assert evidence==untouched,(label,'checker mutated evidence')
            assert (expected['status'],expected['post_execution_reference'],expected['post_execution_state'])==(status,reference,post),label
            assert (expected['process_association']=='accepted') is (status=='process_observed'),label
            if label.startswith('unknown_provider_'):
                assert expected['process_rejection_reason']=='unrecognized_process_provider',label
            if reference=='prelaunch': assert expected['sha256']=='a'*64,label
            if reference=='unavailable': assert not expected['sha256'],label
            if status=='process_observed' and evidence['prelaunch'].get('sha256')=='a'*64:
                assert expected['prelaunch_comparison']=='different_bytes',label
            if label=='identical_bytes_replacement': assert expected['same_post_execution_file_object'] is False
            worker=_export_worker_fixture();worker.update(process_pid=pid,native_executable_provenance=evidence)
            failed = label in {'failed_launch_metadata','cancelled_before_verification','unexpected_exit','forced_kill'}
            if failed:
                worker.update(status='error',error_count=1,verification_complete=False,
                    observed_exit_code=-9 if label=='forced_kill' else -15 if label=='cancelled_before_verification' else 1,
                    forced_kill=label=='forced_kill')
            run=root/str(index);custom=_worker_export_round_trip(worker,run)
            manifest=JsonStore.read(run/'run_manifest.json',{})
            stored=manifest['stage_windows'][0]['worker_results'][0]['native_executable_provenance']
            for key in ('prelaunch','process_executable','post_execution'):
                assert (key in stored)==(key in untouched),(label,key,'export invented or filtered observation')
                if key in untouched:
                    assert stored[key]==untouched[key],(label,key,'export filtered or repaired observation')
            assert binary.native_binary_reviews(manifest)[0] == {**expected,'stage_id':'fp32','worker_pid':pid},label
            # Legacy Segments can omit the canonical stage_id; do not invent one.
            assert {k:v for k,v in binary.native_binary_reviews(custom)[0].items() if k!='stage_id'} == {
                k:v for k,v in binary.native_binary_reviews(manifest)[0].items() if k!='stage_id'},label
            report=compile_report_data(run);review=report['stages'][0]['native_executable_review']
            assert review==binary.native_binary_reviews(manifest),label
            human=binary.native_binary_text(review)
            assert human in (run/'run_summary.txt').read_text(),label
            assert '; reference '+reference in human and '; post-execution '+post in human,label
            html=render_report_html(report)
            assert 'reference '+reference in html and 'post-execution '+post in html,label
            qa=service.qa_result_review_payload(run,refresh_summary=False)
            assert qa['native_executable_review']==review,label
            assert qa['native_executable_text']==human,label
            assert human in qa_result_review_presentation(qa,'fixture'),label
            assert custom['ReportSummary']['DepartmentUseSummary']['WorkerVerified'] is (not failed),label
            assert (manifest['verdict']=='fail') is failed,label
        with redirect_stdout(StringIO()):
            assert launch_stage_processes_from_plan([StageLaunchCommand('cpu',[str(root/'missing')],native_helper_family='cpu')],stage_id='failed')==[]
    print(f'PASS native binary trust: {len(cases)} adversarial/positive artifact-report-QA round trips')
