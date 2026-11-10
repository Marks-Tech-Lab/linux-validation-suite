"""Stage 2B-1: isolated contract and kernel-policy tests, no block-device access."""
from copy import deepcopy
from dataclasses import replace
import json
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from Modules.lvs_native_helpers import find_c_compiler, native_helper_build_command
from Modules.lvs_storage_thermal import (ThermalConfig, ThermalDevice, ThermalResult,
                                        readiness, pilot_rate, result_successful)
from Modules.lvs_storage_thermal_backend import capability, guard_command, executable_identity, guard_environment

ROOT = Path(__file__).resolve().parents[1]


def rejects(call):
    try:
        call()
    except (ValueError, OSError):
        return
    raise AssertionError('invalid input accepted')


def run_storage_thermal_schema_checks():
    config = ThermalConfig()
    assert config.intensity_percent == 50 and config.system_intensity_percent == 25
    assert ThermalConfig(**json.loads(json.dumps(config.to_dict()))).to_dict()['policy'] == config.policy
    for change in ({'contract_version': True}, {'contract_version': 2}, {'duration_seconds': 0},
                   {'duration_seconds': 86401}, {'block_size': 65535}, {'queue_depth': True},
                   {'intensity_percent': -1}, {'system_intensity_percent': 101},
                   {'selection': 'usb'}, {'selection': 'individual'}, {'policy': 'unknown'},
                   {'rate_mode': 'advanced'}, {'iops': 30}, {'scheduling': 'realtime'},
                   {'monitoring': 'approved_unmonitored'}, {'temperature_limit_c': float('nan')}):
        rejects(lambda: replace(config, **change))
    approved = replace(config, monitoring='approved_unmonitored', unmonitored_approval='operator record')
    assert approved.temperature_limit_c is None
    dev = ThermalDevice('wwn:test', {'major': 1, 'minor': 2}, state='blocked', selected=True,
                        system_drive=True, reasons=['active system backend not proven'])
    report = readiness(config, [dev], {'status': 'available'})
    assert report['status'] == 'BLOCKED' and not report['commands'] and report['blocked_devices'] == ['wwn:test']
    dev.state = 'ready'
    rejects(lambda: readiness(config, [dev], {'status':'available'}))
    dev.system_drive = False
    report = readiness(config, [dev], {'status': 'available'})
    assert report['eligibility_status'] == 'ELIGIBLE' and report['status'] == 'BLOCKED'
    assert not report['launch_implemented'] and not report['runnable_devices']
    rejects(lambda: readiness(config, [dev, dev], {}))


def run_storage_thermal_pilot_policy_checks():
    config = ThermalConfig()
    assert pilot_rate(config, 'a', 'hdd')['effective_iops'] == 15
    system = pilot_rate(config, 'a', 'hdd', system=True)
    assert system['requested_iops'] == 7.5 and system['effective_iops'] == 7
    assert pilot_rate(config, 'a', 'ssd')['effective_iops'] == 64
    assert pilot_rate(config, 'a', 'nvme')['effective_iops'] == 128
    assert pilot_rate(replace(config, intensity_percent=0), 'a', 'hdd')['effective_iops'] == 0
    rejects(lambda: pilot_rate(replace(config, intensity_percent=1), 'a', 'hdd'))
    rejects(lambda: pilot_rate(config, 'a', 'unknown'))
    custom = replace(config, per_device_percent={'a': 100})
    assert pilot_rate(custom, 'a', 'hdd', system=True)['effective_iops'] == 30
    advanced = replace(config, rate_mode='advanced', iops=100000, bandwidth_bytes_per_second=655360)
    assert pilot_rate(advanced, 'a', 'hdd')['effective_iops'] == 10
    # Deterministic 6C/28-drive plan, no CPU or memory reservation implied.
    devices = ['hdd']*24 + ['nvme']*2 + ['ssd']*2
    rates = [pilot_rate(config, f'id:{i}', kind) for i, kind in enumerate(devices)]
    assert len(rates) == 28 and sum(r['effective_iops'] for r in rates) == 744
    assert all(r['provisional'] and not r['physical_thermal_acceptance'] for r in rates)
    large = pilot_rate(replace(config, block_size=1048576), 'a', 'hdd')
    assert large['effective_bps'] <= large['ceiling_bps'] * .5


def run_storage_thermal_terminal_checks():
    result = ThermalResult('wwn:test', {'major': 1, 'minor': 2}).to_dict()
    assert not result_successful(result)
    result.update(state='completed', exit_code=0, read_ios=30, read_bytes=1966080,
                  duration_completed=True, cleanup_confirmed=True, terminal_published=True,
                  identity_unchanged=True, guard_confirmed=True, provenance_confirmed=True,
                  fio_activity={'active_seconds':120}, configured_duration_seconds=120,
                  effective_rate={'block_size':65536}, started_monotonic=1, ended_monotonic=121,
                  source_provenance={'scope':'fixture'}, executable_provenance={'identity':'fixture'})
    assert result_successful(result)
    # Successful activity does not claim measured heating/temperature safety.
    assert result['temperature_status'] == 'unmeasured' and result['heating_status'] == 'unmeasured'
    for key in ('duration_completed', 'cleanup_confirmed', 'terminal_published', 'identity_unchanged', 'guard_confirmed', 'provenance_confirmed'):
        bad = dict(result); bad[key] = False; assert not result_successful(bad), key
    for key in ('errors', 'write_ios', 'discard_ios', 'flush_ios', 'outstanding_descriptors',
                'exit_code', 'forced_kill', 'shutdown_timed_out', 'safety_stop'):
        bad = dict(result); bad[key] = 1 if key not in ('forced_kill', 'shutdown_timed_out', 'safety_stop') else True
        assert not result_successful(bad), key
    for key in tuple(result):
        if key in ('exit_code', 'read_ios', 'contract_version', 'flush_ios'):
            bad = dict(result); bad[key] = True; assert not result_successful(bad)
    assert not result_successful(None)
    for key, value in [('read_bytes', 0), ('device_id', ''), ('identity', {}), ('effective_rate', {}),
                       ('source_provenance', {}), ('executable_provenance', {}), ('ended_monotonic', float('nan'))]:
        bad = dict(result); bad[key] = value; assert not result_successful(bad)


def run_storage_thermal_capability_checks():
    with patch.dict(os.environ, {'LD_PRELOAD':'untrusted', 'FIO_IOOPS':'untrusted'}):
        assert not any(k.startswith(('LD_', 'FIO_')) for k in guard_environment())
    with tempfile.TemporaryDirectory() as directory:
        fio = Path(directory)/'fio'; guard = Path(directory)/'guard'
        fio.write_text('fixture'); guard.write_text('fixture'); fio.chmod(0o700); guard.chmod(0o700)
        version = 'fio-3.42'; engine = 'Available IO engines:\n psync\n'; proof = 0
        filetype = 'filetype: block'
        calls = []
        def run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[-1] == '--version':
                return SimpleNamespace(returncode=0, stdout=version if cmd[0] == str(fio) else 'lvs-storage-thermal-guard-v1')
            if '--policy-test' in cmd:
                return SimpleNamespace(returncode=proof, stdout='{"policy_test":"PASS"}')
            return SimpleNamespace(returncode=0, stdout=filetype if '--cmdhelp=filetype' in cmd else engine)
        with patch('Modules.lvs_storage_thermal_backend.os.getuid', return_value=1000), patch('Modules.lvs_storage_thermal_backend.os.getgid', return_value=1000):
            assert capability(str(fio), str(guard), run=run)['status'] == 'available'
            version = 'fio-3.40'; filetype = 'No such command: filetype'
            assert capability(str(fio), str(guard), run=run)['status'] == 'unsupported'
            assert '--policy-test' not in calls[-1]
            version = 'fio-3.43'; filetype = 'filetype: block'
            assert capability(str(fio), str(guard), run=run)['status'] == 'untested'
            version = 'fio-3.42'; engine = 'sync'
            assert capability(str(fio), str(guard), run=run)['status'] == 'unsupported'
            engine = 'psync'; proof = 125
            assert capability(str(fio), str(guard), run=run)['status'] == 'unavailable'
        assert capability('/nonexistent', str(guard), run=run)['status'] == 'unavailable'


def compile_guard(directory):
    compiler = find_c_compiler(); assert compiler, 'C compiler required for guard regression'
    binary = Path(directory)/'guard'
    cmd = native_helper_build_command(compiler, ROOT/'native/storage_thermal_guard.c', binary)
    subprocess.run(cmd + ['-Wall', '-Wextra', '-Werror'], check=True, capture_output=True)
    return binary


def run_storage_thermal_native_guard_checks():
    with tempfile.TemporaryDirectory() as directory:
        guard = compile_guard(directory)
        path = Path(directory)/'readonly'; path.write_bytes(bytes(65536))
        uid, gid = os.getuid(), os.getgid()
        assert uid and gid, 'run software tests as the regular operator'
        fd = os.open(path, os.O_RDONLY | os.O_DIRECT)
        try:
            args = [str(guard), '--policy-test', *map(str,(uid,gid,0,0,65536,4096,1,1))]
            result = subprocess.run(args, stdin=fd, capture_output=True, text=True, timeout=10)
            assert result.returncode == 0, result.stderr
            assert json.loads(result.stdout)['ioctl_denials'] == 17
            evidence = json.loads(result.stderr)
            assert evidence['no_new_privs'] == 1 and evidence['seccomp'] == 2 and evidence['capabilities'] == 0
            # Readonly but buffered, writable, root UID and wrong identity fail closed.
            bad = args.copy(); bad[2] = '0'
            assert subprocess.run(bad, stdin=fd, capture_output=True).returncode == 125
            bad = args.copy(); bad[5] = '1'
            assert subprocess.run(bad, stdin=fd, capture_output=True).returncode == 125
        finally:
            os.close(fd)
        for flags in (os.O_RDONLY, os.O_RDWR | os.O_DIRECT):
            fd = os.open(path, flags)
            try:
                assert subprocess.run(args, stdin=fd, capture_output=True).returncode == 125
            finally:
                os.close(fd)


def run_storage_thermal_descriptor_binding_checks():
    with tempfile.TemporaryDirectory() as directory:
        guard = compile_guard(directory)
        # Pin an ordinary trusted ELF for specification tests only, never execute it.
        executable = Path('/bin/true').resolve()
        fd = os.open(executable, os.O_RDONLY)
        # Project minimum Python 3.10 has no hashlib.file_digest.
        with patch.object(hashlib, 'file_digest', side_effect=AssertionError('Python 3.11-only API'), create=True):
            backend = {'status':'available','fio':executable_identity(str(executable)),
                       'guard':executable_identity(str(guard))}
        kwargs = dict(backend=backend, uid=os.getuid(), gid=os.getgid(), major=1, minor=2,
                      size=65536, block_size=4096, iops=15, seconds=120)
        try:
            argv = guard_command(str(guard), fd, **kwargs)
            assert argv[1:3] == ['--fio-fd', str(fd)]
            assert not any('/dev/' in arg for arg in argv)
            bad = deepcopy(backend); bad['fio']['sha256'] = '0'*64
            rejects(lambda: guard_command(str(guard), fd, **dict(kwargs, backend=bad)))
            rejects(lambda: guard_command(str(guard), fd, **dict(kwargs, seconds=0)))
            # Production mode refuses regular-file targets before any exec.
            target = Path(directory)/'fixture'; target.write_bytes(bytes(65536))
            targetfd = os.open(target, os.O_RDONLY | os.O_DIRECT)
            try:
                r = subprocess.run(argv, stdin=targetfd, pass_fds=(fd,), capture_output=True)
                assert r.returncode == 125 and b'descriptor identity mismatch' in r.stderr
            finally:
                os.close(targetfd)
        finally:
            os.close(fd)
