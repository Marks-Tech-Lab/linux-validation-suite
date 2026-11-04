"""No physical I/O. SMART fixtures and disposable research-probe safety checks."""
import json
from types import SimpleNamespace
from Modules.lvs_storage_health import StorageHealthEnricher
from scripts.storage_thermal_fio_probe import command, audit, validate_fixture, SIZE


def run_storage_smart_standby_checks():
    classification = {'is_internal': True, 'transport': 'sata'}
    cases = [
        ({'smartctl': {'messages': [{'string': 'Device is in STANDBY mode'}]}}, 2, 'unavailable'),
        ({'smartctl': {'messages': [{'string': 'INVALID ARGUMENT TO -n: standby,now'}]}}, 1, 'unavailable'),
        ({'smartctl': {'messages': [{'string': 'Permission denied'}]}}, 2, 'permission_denied'),
        ({'smartctl': {'messages': [{'string': 'Unable to detect device type'}]}}, 1, 'unsupported'),
        ({'smart_status': {'passed': False}}, 8, 'available'),
        ({'smart_status': {'passed': True}}, 64, 'available'),
    ]
    for payload, code, status in cases:
        calls = []

        def runner(argv, **kwargs):
            calls.append(argv)
            return SimpleNamespace(stdout=json.dumps(payload), stderr='', returncode=code)

        enricher = StorageHealthEnricher(read_sysfs=lambda p: None, run_command=runner,
                                       which_command=lambda n: '/smartctl' if n == 'smartctl' else None)
        result = enricher.query_health({'Name': 'fixture', 'DevicePath': '/not-a-device'}, classification)
        assert result['query_status'] == status
        assert calls == [['/smartctl', '--json', '--info', '--health', '--attributes',
                          '--nocheck', 'standby', '/not-a-device']]
        note = ' '.join(result['query_notes'])
        assert 'without waking' not in note
        if code == 1:
            assert note != 'drive reports standby; health query skipped (device autodetection may already have accessed it)'
        if code == 8:
            assert result['smart_health'] == 'failed'
        if code == 64:
            assert result['smart_health'] == 'passed' and '64' in note
    # NVMe is not sent ATA power-mode checks.
    calls.clear()
    enricher.query_health({'Name': 'fixture', 'DevicePath': '/not-a-device'},
                          dict(classification, transport='nvme'))
    assert '--nocheck' not in calls[0]


def run_storage_fio_probe_contract_checks():
    for rate in (10, 30):
        argv = command('/fixture/fio', rate)
        assert argv.index('--filetype=block') < argv.index('--filename=-')
        assert '--readonly' in argv and '--ioengine=psync' in argv
        for option in ('--invalidate=0', '--end_fsync=0', '--fsync_on_close=0',
                       '--allow_file_create=0', '--create_on_open=0', '--direct=1'):
            assert option in argv
        assert not any('/dev/' in option for option in argv)
        assert not any(option.startswith('--size=') for option in argv)  # kernel size discovery
    for rate, duration in [(0, 3), (100, 3), (10, 0), (10, 61)]:
        try:
            command('/fio', rate, duration)
        except ValueError:
            pass
        else:
            raise AssertionError('unbounded pilot accepted')
    args = ['aabbccddeeff', 'lvs_fixture=aabbccddeeff', 'QEMU', 'LVS-aabbccddeeff', SIZE, 0]
    validate_fixture(*args)
    for i, value in [(0, ''), (1, 'normal-host'), (2, 'real-hardware'),
                     (3, 'wrong-disk'), (4, SIZE*2), (5, 1000)]:
        bad = args.copy(); bad[i] = value
        try:
            validate_fixture(*bad)
        except RuntimeError:
            pass
        else:
            raise AssertionError('unsafe fixture accepted')


def run_storage_fio_trace_audit_checks():
    clean = '\n'.join([
        '1 dup(0</dev/vda>) = 4</dev/vda>',
        '1 ioctl(4</dev/vda>, BLKGETSIZE64, [33554432]) = 0',
        '1 fadvise64(4</dev/vda>, 0, 33554432, POSIX_FADV_RANDOM) = 0',
        '1 pread64(4</dev/vda>, ""..., 65536, 65536) = 65536',
        '1 pread64(4</dev/vda>, ""..., 65536, 196608) = 65536',
        '1 write(1</evidence/log>, ""..., 10) = 10'])
    result = audit(clean)
    assert result['aligned_bounded_reads'] and result['distinct_offsets'] == 2
    assert not result['target_mutations'] and not result['unknown_target_calls']
    for operation in ('pwrite64(4</dev/vda>, "", 65536, 0) = -1 EBADF',
                      'ioctl(4</dev/vda>, BLKFLSBUF) = 0',
                      'ioctl(4</dev/vda>, BLKDISCARD, []) = 0',
                      'fsync(4</dev/vda>) = 0',
                      'fcntl(4</dev/vda>, F_SETFL, O_RDWR) = 0',
                      'openat(AT_FDCWD, "/dev/vda", O_RDWR) = 4</dev/vda>',
                      'mmap(NULL, 4096, PROT_WRITE, MAP_SHARED, 4</dev/vda>, 0) = 1'):
        assert audit(clean + '\n' + operation)['target_mutations']
    assert audit('1 unknown(4</dev/vda>) = 0')['unknown_target_calls']
    for offset in (1, SIZE):
        assert not audit(f'1 pread64(4</dev/vda>, "", 65536, {offset}) = 65536')['aligned_bounded_reads']
    assert not audit('1 pread64(4</dev/vda>, "", 65536, 0) = 512')['aligned_bounded_reads']
