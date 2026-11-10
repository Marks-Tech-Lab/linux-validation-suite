"""Shared timed-stage adapter for the authoritative guarded thermal runner.

No block I/O is implemented here. Saved configuration contains no permissions or
consent. Only unmonitored execution needs an ephemeral run-local approval.
"""
from __future__ import annotations

from dataclasses import asdict, replace
from contextlib import contextmanager
import array
import ctypes
import errno
import fcntl
import hashlib
import json
import math
import select
import os
from pathlib import Path
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
from uuid import uuid4

from .lvs_storage_thermal import ThermalConfig, GROUPS, canonical_lease_identity
from .lvs_storage_thermal_runner import ThermalRunner, approve_unmonitored, group_gone
from .lvs_profile_report_artifacts import atomic_preflight_json
from .lvs_storage_thermal_results import normalize, not_run, error_result

ROOT = Path(__file__).resolve().parents[1]
RECOVERY_MARKER = ROOT/'build/storage_thermal_recovery_required.json'
_UNCONFIRMED = {}  # retain supervisor references; never silently release recovery state


def stage_config(stage):
    values = asdict(stage.modules.storage_thermal)
    if type(values["enabled"]) is not bool:
        raise ValueError("Thermal enabled must be a boolean")
    values.pop('enabled')
    # Saved profiles express intent only. The session must explicitly approve
    # the entire bounded scope before this placeholder can become executable.
    if values['monitoring'] == 'approved_unmonitored':
        values['unmonitored_approval'] = 'pending explicit run-local approval'
    duration = stage.duration_seconds if stage.modules.storage_thermal.enabled else 120
    return ThermalConfig(**values, duration_seconds=duration)


def default_runner():
    return ThermalRunner(shutil.which('fio') or '/nonexistent/fio', ROOT/'build/storage_thermal_guard')


def thermal_settings(stage, setting_type):
    StageSetting = setting_type
    obj = stage.modules.storage_thermal
    fields = [StageSetting('thermal_enabled', 'Storage Thermal Assist enabled', 'storage_thermal',
                           'enabled', obj.enabled, ('false', 'true'))]
    if not obj.enabled:
        return fields
    options = dict(selection=GROUPS, rate_mode=('percent', 'advanced'), monitoring=('required', 'approved_unmonitored'), scheduling=('normal',))
    labels = dict(device_ids='Individual stable IDs (JSON list)', per_device_percent='Per-drive intensity (JSON object)',
                  intensity_percent='Ordinary activity %', system_intensity_percent='System activity % (active drives blocked)',
                  block_size='Read size bytes', iops='Advanced IOPS (JSON integer/null)',
                  bandwidth_bytes_per_second='Advanced bytes/s (JSON integer/null)',
                  temperature_limit_c='Stop temperature C (JSON number/null)',
                  temperature_warning_c='Warning temperature C (JSON number/null)')
    for name, value in asdict(obj).items():
        if name in ('enabled','rate_mode','iops','bandwidth_bytes_per_second'):
            continue
        fields.append(StageSetting('thermal_'+name, 'Thermal: '+labels.get(name, name.replace('_',' ')),
                                   'storage_thermal', name, value, tuple(options.get(name, ()))))
    fields.append(StageSetting('thermal_rates', 'Thermal advanced rates (JSON object: rate_mode, iops, bandwidth_bytes_per_second)',
                  'storage_thermal', 'rate_mode', {k:getattr(obj,k) for k in ('rate_mode','iops','bandwidth_bytes_per_second')}))
    return fields


def set_thermal_setting(stage, key, raw):
    name = key.removeprefix('thermal_')
    if name == 'rates':
        values=json.loads(raw)
        if not isinstance(values,dict) or set(values)!={'rate_mode','iops','bandwidth_bytes_per_second'}:
            raise ValueError('Provide rate_mode, iops and bandwidth_bytes_per_second together')
        for key,value in values.items():setattr(stage.modules.storage_thermal,key,value)
        stage_config(stage)
        return values
    if name not in asdict(stage.modules.storage_thermal):
        raise ValueError('Unknown thermal setting')
    value = raw if name in ('selection','rate_mode','monitoring','scheduling') else json.loads(raw)
    setattr(stage.modules.storage_thermal, name, value)
    stage_config(stage)  # same validation as standalone; caller owns transaction
    if type(stage.modules.storage_thermal.enabled) is not bool:
        raise ValueError('enabled must be a boolean')
    return value


def inspect_stage(runner, config):
    result=runner.inspect(config)
    if result.get('backend',{}).get('status')=='available':
        probe_error=''
        try:
            from .lvs_storage_thermal_launch import prepare,provenance
            prepare()
            result['backend']=dict(result['backend'],owned_launcher=provenance())
        except (OSError,ValueError,subprocess.SubprocessError) as exc:
            result.update(status='BLOCKED',commands=[],runnable_devices=[])
            reason='Owned launcher unavailable: '+str(exc)
            result['reasons']=list(result.get('reasons') or [])+[reason]
            for row in result.get('devices',[])+result.get('targets',[]):
                if row.get('state')=='ready':row.update(state='blocked',reasons=list(row.get('reasons') or [])+[reason])
            return result
        try:
            proof=subprocess.run([str(runner.guard),'--stage-admission-version'],
                stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=2,check=False)
            available=proof.returncode==0 and proof.stdout.strip()=='lvs-storage-thermal-stage-admission-v2'
        except (OSError,subprocess.SubprocessError) as exc:
            available=False;probe_error=str(exc)
        result['backend']=dict(result['backend'])
        result['backend']['stage_admission_protocol']='v2' if available else 'unavailable'
        if not available:
            reason='Stage admission protocol unavailable; rebuild the target-local native guard'
            if probe_error:reason+='; probe failed: '+probe_error
            result.update(status='BLOCKED',commands=[],runnable_devices=[])
            result['reasons']=list(result.get('reasons') or [])+[reason]
            for row in result.get('devices',[])+result.get('targets',[]):
                if row.get('state')=='ready':row.update(state='blocked',reasons=list(row.get('reasons') or [])+[reason])
            result['blocked_devices']=[r['device_id'] for r in result.get('devices',[]) if r.get('selected') and r.get('state')=='blocked']
            result['eligibility_status']='BLOCKED'
    return result


def preview(stage, runner=None):
    if not getattr(getattr(stage.modules,'storage_thermal',None),'enabled',False):
        return None
    config = None
    try:
        config = stage_config(stage)
        runner = runner or default_runner()
        if config.monitoring == 'approved_unmonitored':
            # Preview only: no execution authorization is conferred. The stage
            # child needs the run-local bounded consent before recreating this.
            from .lvs_storage_thermal_targets import selected
            rows = runner.targets.discover()
            ids = [r['device_id'] for r in rows if selected(r,config)]
            config = approve_unmonitored(config, ids, 'preview only; explicit bounded session consent still required')
        result = inspect_stage(runner,config)
    except (OSError, ValueError, RuntimeError) as exc:
        requested=asdict(stage.modules.storage_thermal);requested.pop('enabled',None)
        requested.update(duration_seconds=stage.duration_seconds)
        result = dict(status='BLOCKED', configuration=config.to_dict() if config else requested, devices=[], targets=[],
                      selected_devices=[], runnable_devices=[], blocked_devices=[], commands=[],
                      backend=dict(status='unavailable',reasons=[str(exc)]), reasons=[str(exc)])
    result['requires_consent'] = bool(result['status']=='READY' and config is not None and config.monitoring=='approved_unmonitored')
    return result


def decision_key(plan):
    """Include safety/coverage, not volatile sensor readings or memory headroom.

    Every material identity, requested setting, blocker and backend change expires
    consent. A temperature becoming critical changes eligibility/reasons.
    """
    configuration = dict(plan['configuration'])
    configuration['unmonitored_approval'] = ''
    payload = dict(configuration=configuration, status=plan['status'], schedule_scope=plan.get('schedule_scope'),
                   devices=[{k:d.get(k) for k in ('device_id','identity','selected','state','system_drive','reasons','rate')}
                            for d in plan.get('devices',[]) if d.get('selected')],
                   backend=plan.get('backend'),source=(plan.get('source_provenance') or {}).get('source'), reasons=plan.get('reasons',[]),
                   monitoring=[dict(device_id=r['device_id'], sensors=r.get('sensors',[]),
                      policy={k:r.get('initial_temperature',{}).get(k) for k in
                              ('critical_c','warning_c','low_critical_c','complete')})
                      for r in plan.get('targets',[])])
    return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()


def schedule_scope(profile):
    stages = [dict(stage_id=s.id, enabled=s.enabled, duration_seconds=s.duration_seconds,
                   thermal=asdict(s.modules.storage_thermal)) for s in profile.stages]
    return hashlib.sha256(json.dumps(stages,sort_keys=True).encode()).hexdigest()


def consent_requests(report, profile):
    consents = getattr(profile, '_thermal_consents', {})
    return [p['storage_thermal'] for p in report.get('plan',[]) if p.get('enabled') and p.get('storage_thermal')
            and p['storage_thermal'].get('requires_consent')
            and not consent_decided(p['storage_thermal'], consents)]


def consent_valid(plan, consents):
    record = consents.get(decision_key(plan), {})
    return record.get('expires_unix',0) > time.time() and record.get('approved') is True


def consent_decided(plan, consents):
    record = consents.get(decision_key(plan), {})
    return record.get('expires_unix',0) > time.time() and type(record.get('approved')) is bool


def consent_text(plans):
    lines = ['Explicit approval is needed only for the requested unmonitored Thermal Assist activity.',
        f"Scope: {len(plans)} stage(s), {sum(p['configuration']['duration_seconds'] for p in plans)} seconds total."]
    for plan in {decision_key(p):p for p in plans}.values():
        c=plan['configuration']
        lines.append(f"{c['duration_seconds']}s per stage; {c['selection']}; {c['intensity_percent']}% ordinary / {c['system_intensity_percent']}% system; {c['monitoring']}")
        lines.append(f"Eligible: {plan.get('runnable_devices',[])}; excluded: {plan.get('blocked_devices',[])}")
    lines.append('No measured thermal safety is claimed. Approval covers this exact bounded schedule, not later or longer runs.')
    lines.append('You may continue primary validation without unmonitored Thermal Assist; it is non-gating.')
    return '\n'.join(lines)


def record_unmonitored_decision(profile, plans, approved):
    duration = sum(int(s.duration_seconds or 0) for s in profile.stages if s.enabled)
    records = getattr(profile, '_thermal_consents', {}).copy()
    for plan in plans:
        if plan['configuration']['monitoring']!='approved_unmonitored':
            continue
        plan['schedule_scope'] = schedule_scope(profile)
        records[decision_key(plan)] = dict(approved=bool(approved), expires_unix=time.time()+duration+600,
            scope='exact_stage_requested_unmonitored_duration', unmonitored=bool(approved))
    profile._thermal_consents = records


def approve_coverage(profile, plans):
    """Compatibility name for the uncommitted UI adapter; unmonitored scope only."""
    record_unmonitored_decision(profile, plans, True)


def apply_profile_decisions(profile, plans):
    for item in plans:
        thermal = item.get('storage_thermal')
        if not thermal:continue
        thermal['schedule_scope'] = schedule_scope(profile)
        thermal['coverage_consent'] = getattr(profile, '_thermal_consents', {}).get(decision_key(thermal))
        thermal['execution_permitted'] = thermal['status']=='READY' and (
            not thermal['requires_consent'] or consent_valid(thermal,getattr(profile,'_thermal_consents',{})))
        thermal['auxiliary_prediction'] = ('COMPLETED_WITH_WARNINGS' if thermal.get('partial_coverage') or thermal['requires_consent'] else 'COMPLETED') if thermal['execution_permitted'] else 'NOT_RUN'
        thermal['decision_key'] = decision_key(thermal)
        # No primary issues, warnings, runnable flags or hardware policies change.


def recovery_blocker(marker):
    try:
        if str(marker) in _UNCONFIRMED:
            return 'Previous storage cleanup is unconfirmed; further storage execution prohibited pending manual recovery'
        from .lvs_storage_thermal_recovery import blocker
        return blocker(marker)
    except FileNotFoundError:pass
    except OSError as exc:return 'Storage recovery state unavailable: '+str(exc)
    return ''


class StageChannel:
    """Two anonymous pipes: local control only, no socket/network dependency."""
    def __init__(self, read_fd, write_fd):
        self.read_fd, self.write_fd = read_fd, write_fd
        self.timeout = None
        self.peeked = b''

    @classmethod
    def pair(cls):
        child_read, parent_write = os.pipe()
        parent_read, child_write = os.pipe()
        return cls(parent_read,parent_write), cls(child_read,child_write)

    def setblocking(self, blocking):
        os.set_blocking(self.read_fd,False);os.set_blocking(self.write_fd,False)
        self.timeout = None if blocking else 0
    def settimeout(self, seconds):
        os.set_blocking(self.read_fd,False);os.set_blocking(self.write_fd,False)
        self.timeout = seconds
    def recv(self, size, peek=False):
        if self.peeked:
            value = self.peeked[:size]
            if not peek: self.peeked = self.peeked[size:]
            return value
        if not select.select([self.read_fd],[],[],self.timeout)[0]:
            if self.timeout == 0: raise BlockingIOError()
            raise TimeoutError('Stage control deadline expired')
        value = os.read(self.read_fd,size)
        if peek: self.peeked = value
        return value
    def send(self, data):
        if not select.select([],[self.write_fd],[],self.timeout)[1]:
            if self.timeout == 0: raise BlockingIOError()
            raise TimeoutError('Stage control deadline expired')
        # Nonblocking writes keep a large readiness payload off the timed path.
        return os.write(self.write_fd,data)
    def sendall(self, data):
        until=time.monotonic()+self.timeout if self.timeout is not None else None
        while data:
            if until is not None and time.monotonic()>=until:raise TimeoutError('Control send deadline expired')
            try:data=data[self.send(data):]
            except (BlockingIOError,InterruptedError):
                if self.timeout==0:raise

    def close(self):
        for fd in (self.read_fd,self.write_fd):
            try: os.close(fd)
            except OSError: pass


class _OFDLock(ctypes.Structure):
    # The guard supports Linux x86-64/AArch64: off_t is signed 64 bit.
    _fields_=[('type',ctypes.c_short),('whence',ctypes.c_short),
              ('start',ctypes.c_int64),('length',ctypes.c_int64),('pid',ctypes.c_int)]


def ofd_lock(fd, unlock=False):
    if ctypes.sizeof(ctypes.c_void_p)!=8:raise OSError('64-bit Linux admission required')
    request=_OFDLock(fcntl.F_UNLCK if unlock else fcntl.F_WRLCK,os.SEEK_SET,0,0,0)
    # Linux UAPI values are stable even when CPython omits the named constants.
    fcntl.fcntl(fd,getattr(fcntl,'F_OFD_SETLK',37),bytes(request))


class SharedAdmission:
    """Primary identity, independently opened OFD pin, monotonic closure only.

    The public fd is a transport handle, never the authority. Every operation
    opens a private independent OFD from the retained original pin. Closing
    another same-file alias cannot release that operation's OFD lock.
    """
    def __init__(self, fd, identity):
        try:identity=canonical_lease_identity(identity)
        except ValueError as exc:raise OSError('Primary-established lease identity required') from exc
        self.fd=fd;self._identity=tuple(identity);self._pid=os.getpid()
        self._validate(fd)
        # Reopen the memfd, not a device pathname. dup() would share OFD locks.
        self._pin=os.open(f'/proc/self/fd/{fd}',os.O_RDWR|os.O_CLOEXEC)
        try:self._validate(self._pin);self._validate(fd)
        except BaseException:os.close(self._pin);raise

    @property
    def identity(self):return self._identity

    def verified_identity(self):
        with self._operation() as pin:
            self._validate(pin);self._validate(self.fd)
            return canonical_lease_identity(self._identity)

    def _validate(self, fd):
        info=os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_size!=6 or
                (info.st_dev,info.st_ino)!=self._identity or
                fcntl.fcntl(fd,fcntl.F_GETFL)&os.O_ACCMODE!=os.O_RDWR):
            raise OSError('Authoritative lease identity/descriptor mismatch')

    @contextmanager
    def _operation(self):
        if self._pid!=os.getpid():raise OSError('Inherited admission object requires independent attachment')
        pin=os.open(f'/proc/self/fd/{self._pin}',os.O_RDWR|os.O_CLOEXEC)
        reference=None
        try:
            reference=os.dup(pin)  # lifetime alias only; never a competing owner
            self._validate(pin);self._validate(reference)
            yield pin  # private operation; never passed to a child or plugin
        finally:
            try:
                if reference is not None:os.close(reference)
            finally:os.close(pin)

    @classmethod
    def create(cls):
        create=getattr(os,'memfd_create',None)
        if create is not None:fd=create('lvs-stage-admission',getattr(os,'MFD_CLOEXEC',1))
        else:
            try:call=ctypes.CDLL(None,use_errno=True).memfd_create
            except AttributeError as exc:raise OSError('Linux memfd admission unavailable') from exc
            call.argtypes=[ctypes.c_char_p,ctypes.c_uint];call.restype=ctypes.c_int
            fd=call(b'lvs-stage-admission',1)
            if fd<0:raise OSError(ctypes.get_errno(),'Linux memfd admission unavailable')
        try:
            if os.write(fd,b'LVS1OO')!=6:raise OSError('Incomplete stage lease initialization')
            info=os.fstat(fd)
            return cls(fd,(info.st_dev,info.st_ino))
        except BaseException:os.close(fd);raise

    def _revoke_pin(self,pin):
        self._validate(pin)
        if os.pwrite(pin,b'R',5)!=1:raise OSError('Lease closure request incomplete')
        try:ofd_lock(pin)
        except OSError as exc:
            if exc.errno in (errno.EACCES,errno.EAGAIN):return False
            raise
        try:
            self._validate(pin)
            if os.pwrite(pin,b'C',4)!=1:raise OSError('Lease closure incomplete')
            self._validate(pin);self._validate(self._pin)
            if os.pread(self._pin,6,0)!=b'LVS1CR':raise OSError('Original lease closure unconfirmed')
        finally:ofd_lock(pin,unlock=True)
        return True

    def revoke(self):
        with self._operation() as pin:
            mismatch=None
            try:self._validate(self.fd)
            except OSError as exc:mismatch=exc
            closed=self._revoke_pin(pin)  # always closes the original authority
            if mismatch is not None:raise OSError('Lease transport changed; original closure requested') from mismatch
            self._validate(self.fd)
            return closed

    def closed(self):
        with self._operation() as pin:
            try:self._validate(self.fd)
            except OSError:
                self._revoke_pin(pin)
                raise
            return os.pread(pin,6,0)!=b'LVS1OO'

    def close(self):
        if self._pid!=os.getpid():raise OSError('Admission pin owned by another process')
        self._validate(self.fd);self._validate(self._pin)
        # No admission actor uses this pin after confirmed cleanup. Never close
        # a reused, unrelated fd; identity failures retain the original pin.
        os.close(self.fd);os.close(self._pin)


class StageLaunches:
    """Owned, descriptor-free bootstraps; only the native gate admits I/O.

    The standalone ThermalRunner still owns normal execution and read evidence.
    This registry additionally owns every bootstrap before its OWN message.
    """
    def __init__(self, runner, lease, directory, *, owned_launch=None):
        if lease.admission is None: raise ValueError('Shared native admission gate required')
        from .lvs_storage_thermal_launch import OwnedProcess
        self._spawn = owned_launch or OwnedProcess
        self._processes = {}
        self.lease, self.directory = lease, directory
        self.owned = []
        self.publication_error = ''
        self.revocation_error = ''
        self.cleanup_confirmed = True

    def _rows(self):
        rows=list(self.owned)
        for row,p in self._processes.values():
            if not any(r is row for r in rows):
                row['ownership_error']='Owned worker omitted from public registry'
                rows.append(row)
        return rows

    def _register(self,row,p):
        from .lvs_storage_thermal_launch import OwnedProcess
        if not isinstance(p,OwnedProcess):raise OSError('Native bootstrap requires owned creation authority')
        old=self._processes.get(id(row))
        if old is not None and old[1] is not p:raise OSError('Native process ownership cannot be replaced')
        self._processes[id(row)]=(row,p)
        self.cleanup_confirmed=False
        row.update(process=p,pid=p.authority_pid)
        if not p._native_stage:raise OSError('Native bootstrap must remain in supervisor group until OWN')

    def authority(self,p):
        for row,actual in self._processes.values():
            if actual is p:
                if row.get('process') is not actual or row.get('pid')!=actual.authority_pid:
                    row['ownership_error']='Native process handle/registration substituted'
                    raise OSError(row['ownership_error'])
                return actual
        raise OSError('Process does not belong to this native registry')

    def identity(self,p):return self.authority(p).authority_pid

    def snapshot(self):
        return dict(protocol='lvs-storage-thermal-stage-admission-v2',
            lease_identity=list(self.lease.admission.identity),
            cleanup_confirmed=self.cleanup_confirmed, publication_error=self.publication_error,
            revocation_error=self.revocation_error,
            workers=[{k:v for k,v in row.items() if k!='process'} for row in self._rows()])

    def publish(self):
        try: atomic_preflight_json(self.directory/'launch_ownership.json', self.snapshot())
        except OSError as exc:
            self.publication_error = str(exc)
            raise

    def receive(self, channel):
        while True:
            self.lease.check()
            try:
                data = channel.recv(128)
                if not data: raise ValueError('Native admission bootstrap exited without acknowledgement')
                return data
            except socket.timeout: pass

    def stop(self, row, sig):
        entry=self._processes.get(id(row))
        if entry is None:
            row['cleanup_error']='Native creation authority missing';return
        p=entry[1]
        try:
            self.authority(p)
        except OSError as exc:
            row['ownership_error']=str(exc)
            # The independent private handle still owns the intended child.
            # Clean that child only, but never certify ambiguous public evidence.
        try:p.send_signal(sig)
        except OSError as exc:row['cleanup_error']=str(exc)

    def _reconcile(self,row):
        entry=self._processes.get(id(row))
        if entry is None:row['cleanup_confirmed']=False;return False
        p=entry[1]
        try:
            self.authority(p)
            code=p.poll();gone=p.group_cleanup_confirmed()
            row.update(exit_code=code,reaped=code is not None,
                       cleanup_confirmed=gone and not row.get('ownership_error'))
        except OSError as exc:
            row.update(cleanup_confirmed=False,cleanup_error=str(exc))
        return row['cleanup_confirmed']

    def finish(self):
        # One broadcast and bounded shared windows; never N per-drive waits.
        try:self.lease.admission.revoke()
        except OSError as exc:self.revocation_error=str(exc)
        rows=self._rows()
        for row in rows:self.stop(row,signal.SIGTERM)
        until=time.monotonic()+2
        while True:
            outstanding=[row for row in rows if not self._reconcile(row)]
            if not outstanding:break
            if time.monotonic()>=until:
                for row in outstanding:self.stop(row,signal.SIGKILL)
                break
            time.sleep(.02)
        until=time.monotonic()+1
        while any(not r['cleanup_confirmed'] for r in rows) and time.monotonic()<until:
            for row in rows:self._reconcile(row)
            time.sleep(.02)
        try:revoked=self.lease.admission.revoke()
        except OSError as exc:revoked=False;self.revocation_error=str(exc)
        self.cleanup_confirmed=all(r['cleanup_confirmed'] for r in rows) and revoked
        try:self.publish()
        except OSError:pass

    def launch(self, argv, **kwargs):
        # This check is only an optimization. The native shared gate, not this
        # Python sample, decides admission after process ownership is registered.
        self.lease.check(1)
        if len(argv)!=11 or argv[1]!='--fio-fd':raise ValueError('Unexpected standalone guard command')
        target = kwargs['stdin']
        if type(target) is not int or target==int(argv[2]) or tuple(kwargs.get('pass_fds',()))!=(int(argv[2]),):
            raise ValueError('Only the pinned executable may be inherited; target must remain in its owner')
        if kwargs.get('preexec_fn') is not None or kwargs.get('close_fds') is False:
            raise ValueError('Unapproved bootstrap descriptor/launch policy')
        parent,child=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        parent.settimeout(.02)
        row = None
        try:
            command=[argv[0],'--stage-fio-fd',argv[2],str(child.fileno()),
                str(self.lease.admission.fd),str(self.lease.deadline_ns),str(os.getpid()),
                *map(str,self.lease.admission.identity),*argv[3:]]
            options=dict(kwargs,stdin=subprocess.DEVNULL,
                pass_fds=tuple(kwargs.get('pass_fds',()))+(child.fileno(),self.lease.admission.fd),
                start_new_session=False)
            row=dict(process=None,pid=None,phase='bootstrap_launch_pending',group_ready=False,
                supervisor_pgid=os.getpgrp(),descriptor_offered=False,io_admission='not_requested',cleanup_confirmed=False)
            self.owned.append(row)
            self.cleanup_confirmed=False
            self.publish()
            registry=self
            class Registration:
                @property
                def process(self):return registry._processes.get(id(row),(None,None))[1]
                @process.setter
                def process(self,p):registry._register(row,p)
            process=self._spawn(command,**options,stage_bootstrap=True,owner=Registration(),deadline=self.lease.deadline)
            if self.authority(process) is not process:raise OSError('Native launch authority unavailable')
            # Register before any observation/publication/OWN permission. Until
            # OWN the child has no target and remains in the supervisor's group.
            row.update(phase='created')
            child.close()
            self.publish()
            self.lease.check(1)
            parent.sendall(b'OWN')
            if self.receive(parent)!=b'R':raise ValueError('Native ownership acknowledgement invalid')
            process.confirm_native_group()
            row.update(phase='owned',group_ready=True)
            self.publish()
            self.lease.check(1)
            # Offering is NOT admission. A queued fd cannot be received after
            # authoritative closure; the native lock/deadline decides the commit.
            row.update(phase='offering',descriptor_offered=True,io_admission='offered_unconfirmed')
            self.publish()
            parent.sendmsg([b'F'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[target]))])
            ack=self.receive(parent)
            if not ack.startswith(b'A:'):raise ValueError('Native admission acknowledgement invalid')
            committed=int(ack[2:])
            if committed>=self.lease.deadline_ns:raise ValueError('Native admission outside stage deadline')
            row.update(phase='committed',io_admission='committed',committed_monotonic_ns=committed)
            self.publish()
            self.lease.check()
            return process
        except BaseException as exc:
            if row is not None:
                orphan=getattr(exc,'owned_process',None)
                if id(row) not in self._processes and orphan is not None:
                    from .lvs_storage_thermal_launch import OwnedProcess
                    if isinstance(orphan,OwnedProcess):
                        self._processes[id(row)]=(row,orphan)
                        row.update(process=orphan,pid=orphan.authority_pid,ownership_error='Creation registration failed')
                row['launch_failed']=True
                self.stop(row,signal.SIGTERM)
                # Runner's job does not yet contain this process. Keep ownership
                # here and reconcile even when failure precedes return to Runner.
                self.finish()
            raise
        finally:
            parent.close();child.close()


class StageLeaseExpired(ValueError):
    pass


class StageLease:
    """Admission deadline, not a replacement storage safety/identity policy."""
    def __init__(self, deadline, parent_pid, cancelled=lambda:False, clock=time.monotonic, admission=None):
        if not isinstance(deadline,(int,float)) or not math.isfinite(deadline):
            raise ValueError('finite stage deadline required')
        self.deadline,self.parent_pid,self.cancelled,self.clock=deadline,parent_pid,cancelled,clock
        self.deadline_ns=int(deadline*1_000_000_000)
        self.admission=admission

    def check(self, minimum_seconds=0):
        if os.getppid()!=self.parent_pid or self.cancelled() or (self.admission is not None and self.admission.closed()) or self.deadline-self.clock()<=minimum_seconds:
            if self.admission is not None:self.admission.revoke()
            raise StageLeaseExpired('Stage lease expired/cancelled; no new storage admission')


class LeaseTargets:
    """Delegate every identity/open decision; check lifetime around blocking work."""
    def __init__(self, targets, lease):self.targets,self.lease=targets,lease
    def __getattr__(self,key):return getattr(self.targets,key)
    def discover(self):
        self.lease.check();result=self.targets.discover();self.lease.check();return result
    def revalidate(self,row):
        self.lease.check();result=self.targets.revalidate(row);self.lease.check();return result
    def output_safe(self,*args):
        self.lease.check();result=self.targets.output_safe(*args);self.lease.check();return result
    def open(self,row):
        self.lease.check();fd=self.targets.open(row)
        try:self.lease.check();return fd
        except BaseException:os.close(fd);raise


class ThermalStageSession:
    """Non-gating stage adapter. Only the authoritative ThermalRunner performs I/O."""
    def __init__(self, stage, plan, run_dir, popen=None, *, recovery_marker=None,
                 launch_args=None, launch_delay_ms=0,
                 stage_deadline=None, clock=time.monotonic, signal_group=None, group_reaped=None):
        self.stage, self.plan = stage, plan
        self.directory = Path(run_dir)/'storage_thermal'/uuid4().hex
        self.process = None
        self.popen = popen  # obsolete synchronous factories fail closed
        self.launch_args=launch_args;self.launch_delay_ms=launch_delay_ms
        self.handles = []
        self.last_live = None
        self.clock=clock
        self.started = clock()
        self.deadline=stage_deadline if stage_deadline is not None else self.started+stage.duration_seconds
        # Legacy injectable numeric-group hooks confer no process authority.
        # Every sensitive operation belongs to the OwnedProcess instance.
        self.channel=None;self.pending=b'';self.incoming=b''
        self.closed_ns=None;self.primary_end_ns=None
        self.ready_seen=False
        self.admitted=False;self.stopping=False;self.expired_before_admission=False
        self.lease_id=uuid4().hex
        from .lvs_storage_thermal_results import run_identity
        self.terminal_observation={}
        self.context=dict(version=1,run_id=run_identity(run_dir),session_id=self.lease_id,stage_id=stage.id,run_directory=os.path.abspath(run_dir),
            started_ns=int((self.deadline-stage.duration_seconds if stage_deadline is not None else self.started)*1e9),deadline_ns=int(self.deadline*1e9),lease_identity=None)
        self.admission=None;self.admission_identity=None;self.revocation_confirmed=False;self.revocation_error=''
        self.supervisor_forced_kill=False
        self.marker = Path(recovery_marker) if recovery_marker is not None else RECOVERY_MARKER
        self.fault = ''
        self.terminal_read = False
        self.recovery_observation = ''
        self.evidence = not_run('Storage execution has not started', readiness=plan)

    def _latch_cleanup(self, reason):
        _UNCONFIRMED[str(self.marker)] = self
        self.evidence['cleanup_confirmed'] = False
        self.recovery_observation='Storage ownership recovery required: '+str(reason)
        try:
            from .lvs_storage_thermal_recovery import evidence_operation
            evidence_operation('--retain',self.marker,reason[:2000])
            self.evidence['recovery_marker'] = str(self.marker)
        except (OSError,ValueError,subprocess.SubprocessError) as exc:
            self.evidence['recovery_publication_error'] = str(exc)

    def request_stop(self, reason):
        self.fault = self.fault or reason
        self.end_stage()

    def start(self):
        # No discovery, capability subprocess, target opening or filesystem
        # preparation on the primary timed path. The child owns initialization.
        if self.clock()>=self.deadline:
            self.evidence=not_run('Stage ended before auxiliary startup',readiness=self.plan);return
        if self.plan.get('status')!='READY':
            self.evidence=not_run('No eligible runnable storage; see readiness reasons',readiness=self.plan);return
        if self.plan.get('requires_consent') and not consent_valid(self.plan,{decision_key(self.plan):self.plan.get('coverage_consent') or {}}):
            self.evidence=not_run('Bounded unmonitored consent missing/declined/expired',readiness=self.plan);return
        if str(self.marker) in _UNCONFIRMED:
            self.evidence=not_run('Previous auxiliary cleanup remains unconfirmed',readiness=self.plan);return
        # Recovery filesystem inspection/locking belongs to the supervisor.
        if self.popen is not None:
            self.evidence=not_run('Synchronous auxiliary process factories are unsupported',readiness=self.plan);return
        self.admission=SharedAdmission.create()
        self.admission_identity=self.admission.identity
        self.context['lease_identity']=list(self.admission.identity)
        parent,child=StageChannel.pair()
        os.set_blocking(parent.write_fd,False)
        parent.setblocking(False)
        self.channel=parent
        payload=dict(plan=self.plan,execution_context=self.context,directory=os.path.abspath(self.directory),supervisor_parent_pid=os.getpid(),
                     recovery_marker=str(self.marker),stage_deadline=self.deadline,stage_lease_id=self.lease_id,
                     admission_fd=self.admission.fd,admission_identity=self.admission.identity)
        try:
            self.pending=(json.dumps(payload)+'\n').encode()
            if len(self.pending)>8*1024**2:raise ValueError('Auxiliary bootstrap exceeds bounded IPC evidence budget')
            from .lvs_storage_thermal_launch import OwnedProcess
            argv=self.launch_args or [sys.executable,'-m','Modules.lvs_storage_thermal_stage','--channel','{channel}']
            argv=[str(v).replace('{channel}',f'{child.read_fd}:{child.write_fd}') for v in argv]
            self.process=OwnedProcess(argv,delay_ms=self.launch_delay_ms,owner=self,deadline=self.deadline,
                cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                pass_fds=(child.read_fd,child.write_fd,self.admission.fd),start_new_session=True)
            self.evidence=not_run('Auxiliary initialization pending; no I/O admission yet',readiness=self.plan)
            self._channel_poll()
        except BaseException as exc:
            if getattr(exc,'owned_process',None) is not None:self.process=exc.owned_process
            parent.close();self.channel=None
            raise
        finally:child.close()

    def _channel_poll(self):
        if self.channel is None:return
        if self.clock()>=self.deadline:
            self.end_stage();return
        try:
            if self.pending:
                try:
                    sent=self.channel.send(self.pending);self.pending=self.pending[sent:]
                except BlockingIOError:pass
            # One bounded read per primary poll; never drain an unbounded producer.
            for _ in range(1):
                try:data=self.channel.recv(65536)
                except BlockingIOError:break
                if not data:break
                self.incoming+=data
                if len(self.incoming)>65536:raise ValueError('Auxiliary control evidence exceeded bound')
                packets=0
                while b'\n' in self.incoming:
                    packets+=1
                    if packets>32:raise ValueError('Control packet rate exceeds per-poll budget')
                    line,self.incoming=self.incoming.split(b'\n',1);message=json.loads(line)
                    if not isinstance(message,dict):raise ValueError('Control packet must be an object')
                    if message.get('snapshot') and message.get('lease')==self.lease_id:
                        snapshot=message['snapshot']
                        if not isinstance(snapshot,dict) or not isinstance(snapshot.get('devices'),list):
                            raise ValueError('Malformed auxiliary snapshot')
                        self.last_live=snapshot
                    if message.get('ready') and message.get('lease')==self.lease_id:
                        if self.ready_seen:raise ValueError('Duplicate READY after single-shot authorization')
                        self.ready_seen=True
                        if self.stopping or self.deadline-self.clock()<1:
                            self.end_stage();return
                        # Mark conservative ownership BEFORE sending permission.
                        self.admitted=True
                        self.pending+=(json.dumps(dict(run=True,lease=self.lease_id))+'\n').encode()
            if self.pending:
                try:
                    sent=self.channel.send(self.pending);self.pending=self.pending[sent:]
                except BlockingIOError:pass
        except (OSError,ValueError) as exc:self.request_stop('Auxiliary startup IPC failed: '+str(exc))

    def revoke_admission(self):
        """Fast admission barrier only: no process polling, signaling or persistence."""
        if self.closed_ns is None:self.closed_ns=int(self.clock()*1e9)
        if self.admission is not None:
            try:self.revocation_confirmed=self.admission.revoke()
            except OSError as exc:
                self.revocation_confirmed=False;self.revocation_error=str(exc)
                self.fault=self.fault or 'Native admission revocation failed: '+str(exc)

    def end_stage(self):
        """Post-window shutdown; revoke before touching process lifecycle."""
        self.revoke_admission()
        if self.stopping:return
        self.stopping=True
        self.expired_before_admission=not self.admitted
        if self.channel is not None:self.channel.close();self.channel=None
        if self.process is not None:
            try:
                if self.process.poll() is None:self.process.send_signal(signal.SIGTERM)
            except ProcessLookupError:pass
            except OSError as exc:self.fault=self.fault or str(exc)

    def poll(self):
        """Contain storage faults. A drive-level stop is never a primary event."""
        if self.process is None:return None
        self._channel_poll()
        # Live status arrives through the bounded nonblocking control pipe.
        # No stat/open/read/parse-publication retry on the primary timed path.
        return None

    def live_summary(self):
        if self.process is None:return ' | storage='+self.evidence['auxiliary_outcome']
        if (self.last_live or {}).get('auxiliary_outcome'):
            return (' | storage='+self.last_live['auxiliary_outcome']+' '+str(self.last_live.get('reason','')))[:512]
        devices=(self.last_live or {}).get('devices',[])
        if not devices:return ' | storage='+('stopping' if self.stopping else 'status unavailable; no activity inferred')
        age=self.clock()-(self.last_live or {}).get('monotonic',0)
        prefix=' | storage='+('STALE observation; ' if age>3 else '')
        text='; '.join(
            f"{d['device_id'][:80]} {d.get('state','unknown')} temp={(d.get('observation') or {}).get('temperature',{}).get('value_c')}C reads={(d.get('observation') or {}).get('device_read_ios_since_launch','unavailable')}"
            for d in devices[:3])
        return (prefix+text+f"; {len(devices)} shown in snapshot; {(self.last_live or {}).get('omitted_devices',0)} omitted")[:512]

    def _read_terminal(self):
        """Post-primary reconciliation, with filesystem latency in a killable child."""
        result=None
        try:
            from .lvs_storage_thermal_recovery import evidence_operation
            observed=evidence_operation('--read-terminal',self.directory,self.marker)
            if observed.get('recovery_blocker'):
                self.recovery_observation=observed['recovery_blocker']
            result=observed['result']
            if result is None and observed.get('ownership') is not None:
                result=error_result('Terminal record missing despite independent launch registry',readiness=self.plan,cleanup_confirmed=False)
                result['execution_context']=dict(self.context)
            if result is None:
                if self.process.poll() is not None and not (self.stopping and not self.admitted):
                    self.request_stop('Storage supervisor exited without completion evidence')
                return
            if (not isinstance(result,dict) or result.get('contract_id') not in
                    ('lvs.storage_thermal.manifest','lvs.storage_thermal.auxiliary_stage') or result.get('contract_version')!=1):
                raise ValueError('Unrecognized storage completion contract')
            if result.get('contract_id')=='lvs.storage_thermal.manifest' and not result.get('parent_finalization_complete'):
                raise ValueError('Storage supervisor finalization is incomplete')
            from .lvs_storage_thermal_results import session_errors
            self.terminal_observation=dict(ownership=observed.get('ownership'),observed_ns=int(self.clock()*1e9),closed_ns=self.closed_ns,primary_end_ns=self.primary_end_ns)
            errors=session_errors(result,self.plan,self.context,self.terminal_observation)
            if errors:
                ownership=observed.get('ownership') or {}
                context_ok=result.get('execution_context')==self.context
                owned_cleanup=(ownership.get('lease_identity')==self.context.get('lease_identity') and
                    ownership.get('cleanup_confirmed') is True and
                    all(w.get('cleanup_confirmed') is True and w.get('reaped') is True for w in ownership.get('workers',[])))
                from .lvs_storage_thermal_results import execution_facts
                cleanup=context_ok and owned_cleanup and ownership==result.get('stage_launch_ownership') and result.get('cleanup_confirmed') is not False and not observed.get('recovery_blocker')
                result=dict(result,session_errors=errors,cleanup_confirmed=cleanup,independent_launch_ownership=ownership,rejected_terminal_evidence=result)
            self.evidence=normalize(result,readiness=self.plan)
            self.terminal_read=True
            if self.evidence['auxiliary_outcome']=='ERROR':self.request_stop('Storage execution or evidence failure')
        except (OSError,ValueError,TypeError,AttributeError,subprocess.SubprocessError) as exc:
            self.evidence=error_result('Rejected terminal evidence: '+str(exc),readiness=self.plan,cleanup_confirmed=False)
            if result is not None:self.evidence['rejected_terminal_evidence']=result
            self.terminal_read=result is not None
            self.request_stop('Storage terminal observation failed: '+str(exc))

    def finish(self, cancelled=False):
        if self.process is not None:
            try:
                self.end_stage()
                try:self.process.wait(timeout=6 if self.admitted else 1)
                except subprocess.TimeoutExpired:
                    if self.admitted:
                        self.request_stop('Storage supervisor completion deadline expired')
                        self.supervisor_forced_kill=True
                        self._latch_cleanup('Forced supervisor shutdown; descendant cleanup unconfirmed')
                    # Unowned bootstraps remain in this group. Committed native
                    # leaders have registered PIDs/groups and parent-death KILL.
                    # Forced owner death still requires recovery verification.
                    self.process.kill()
                    self.process.wait(timeout=2)
                self._read_terminal()
                if self.supervisor_forced_kill:self._latch_cleanup('Forced supervisor shutdown; descendant cleanup unconfirmed')
                if not self.admitted and self.process.group_cleanup_confirmed():
                    if self.expired_before_admission and not self.fault and not self.terminal_read:
                        self.evidence=not_run('Stage ended/cancelled during auxiliary initialization; no I/O admission',readiness=self.plan)
                        self.evidence['execution_context']=dict(self.context)
                        self.terminal_read=True
                    elif not self.terminal_read:
                        self.evidence=error_result(self.fault or 'Auxiliary initializer exited without completion',readiness=self.plan)
                        self.terminal_read=True
                elif not self.admitted:
                    self._latch_cleanup('Auxiliary initializer group cleanup unconfirmed')
                if self.process.returncode!=0 and self.evidence.get('verdict') in ('PASS','WARN'):
                    self.fault='Storage supervisor exit inconsistent with completion evidence'
                if not self.terminal_read:
                    self.fault=self.fault or 'Storage completion record missing or unreadable'
                    self._latch_cleanup(self.fault)
            except (OSError,subprocess.SubprocessError) as exc:
                self.request_stop('Storage cleanup unconfirmed: '+str(exc))
                self._latch_cleanup(self.fault)
            finally:
                for h in self.handles:h.close()
            if self.fault:
                self.evidence['adapter_error'] = self.fault
                if not self.evidence.get('failure'):self.evidence['failure'] = self.fault
            if self.evidence.get('cleanup_confirmed') is False or any(not d.get('cleanup_confirmed') for d in self.evidence.get('devices',[])):
                self._latch_cleanup('Native storage process cleanup unconfirmed')
        if self.admission is not None:
            try:self.revocation_confirmed=self.admission.revoke()
            except OSError as exc:self.revocation_confirmed=False;self.revocation_error=str(exc)
            if not self.revocation_confirmed:self._latch_cleanup('Native admission revocation lock unconfirmed')
            if self.evidence.get('cleanup_confirmed') is not False:
                self.admission.close();self.admission=None
        if not self.terminal_read and not self.evidence.get('rejected_terminal_evidence'):
            self.evidence.setdefault('execution_context',dict(self.context))
        self.evidence=normalize(self.evidence,readiness=self.plan)
        self.evidence['admission_lease_identity']=self.admission_identity
        self.evidence['supervisor_forced_kill']=self.supervisor_forced_kill
        self.evidence['admission_revocation_confirmed']=self.revocation_confirmed
        if self.revocation_error:self.evidence['admission_revocation_error']=self.revocation_error
        self.evidence['persistent_recovery_required']=bool(self.recovery_observation)
        if self.recovery_observation:self.evidence['recovery_reason']=self.recovery_observation
        self.evidence['live_snapshot_received']=self.last_live is not None
        self.evidence['last_live_snapshot_monotonic']=(self.last_live or {}).get('monotonic')
        self.evidence['stage_session_seconds']=self.clock()-self.started
        self.evidence['parent_session_start_monotonic']=self.started
        self.evidence['stage_deadline_monotonic']=self.deadline
        self.evidence['initializer_permission_granted']=self.admitted
        ownership=self.evidence.get('stage_launch_ownership') or {}
        workers=ownership.get('workers') or []
        trusted=not self.evidence.get('session_errors') and not self.evidence.get('rejected_terminal_evidence')
        committed=trusted and any(r.get('io_admission')=='committed' for r in workers)
        uncertain=any(r.get('descriptor_offered') for r in workers) or (self.admitted and not self.terminal_read) or (bool(self.evidence.get('executed_devices')) and not workers)
        self.evidence['io_admission_granted']=committed
        self.evidence['io_admission_state']='committed' if committed else 'unconfirmed' if uncertain or not trusted else 'not_admitted'
        starts=[d.get('started_monotonic') for d in self.evidence.get('devices',[]) if d.get('started_monotonic') is not None]
        self.evidence['startup_seconds_to_first_worker']=max(0,min(starts)-self.started) if starts else None
        self.evidence['evidence_directory']=str(self.directory)
        try:
            from .lvs_storage_thermal_recovery import evidence_operation
            evidence_operation('--publish-json',self.directory/'adapter_result.json',payload=self.evidence)
        except (OSError,ValueError,subprocess.SubprocessError) as exc:
            self.evidence.update(failure='Storage adapter publication failed: '+str(exc),terminal_published=False)
            self.evidence=normalize(self.evidence,readiness=self.plan)
        return self.evidence


def worker(directory, *, gate=None, lease=None, snapshot=None, snapshot_stats=None):
    plan=json.loads((directory/'request.json').read_text())
    parent_pid=plan.get('supervisor_parent_pid')
    runner=default_runner()
    saved_runner=(runner.targets,runner.popen,runner.temperature,runner.native_processes)
    saved_check=lease.check if lease is not None else None
    config=ThermalConfig(**plan['configuration'])
    attempted=False
    launches=None
    recovery=None
    result=None
    code=1
    try:
        blocker=recovery_blocker(Path(plan.get('recovery_marker') or RECOVERY_MARKER))
        if blocker:raise ValueError(blocker)
        if gate is None or lease is None:
            raise ValueError('A live, deadline-bound stage lease is required')
        lease.check()
        if type(parent_pid) is not int or parent_pid < 1 or os.getppid()!=parent_pid:
            raise ValueError('Stage parent identity missing or already exited; no worker launch')
        if config.monitoring == 'approved_unmonitored':
            consent=plan.get('coverage_consent') or {}
            if not consent.get('unmonitored') or not consent_valid(plan,{decision_key(plan):consent}):
                raise ValueError('Bounded unmonitored session approval missing/expired')
            if time.time()+config.duration_seconds+10 > consent['expires_unix']:
                raise ValueError('Stage would exceed bounded unmonitored session deadline')
            config=approve_unmonitored(config,plan['selected_devices'],'explicit bounded profile session approval')
        fresh=inspect_stage(runner,config)
        fresh['schedule_scope'] = plan.get('schedule_scope')
        if decision_key(fresh)!=plan['decision_key']:
            raise ValueError('Storage readiness changed after confirmation; no fallback execution')
        # No native admission or target descriptor opening before durable intent.
        runner.targets.output_safe(Path(plan.get('recovery_marker') or RECOVERY_MARKER).parent,
                                   [r for r in fresh.get('targets',[]) if r.get('state')=='ready'])
        from .lvs_storage_thermal_recovery import RecoveryScope
        recovery=RecoveryScope(Path(plan.get('recovery_marker') or RECOVERY_MARKER))
        recovery.enter(evidence_directory=directory,lease_identity=lease.admission.identity if lease.admission else None,admission=lease.admission)
        if not gate():raise StageLeaseExpired('Stage permission absent/expired before execution')
        lease.check(1)
        requested_configuration=config.to_dict()
        available=min(config.duration_seconds, int(lease.deadline-lease.clock()))
        config=replace(config,duration_seconds=available)
        if config.monitoring=='approved_unmonitored':
            config=approve_unmonitored(config,plan['selected_devices'],'bounded to remaining approved stage window')
        original_check=lease.check
        def owned_check(*args):
            recovery._authority();return original_check(*args)
        lease.check=owned_check
        original_targets=runner.targets
        runner.targets=LeaseTargets(original_targets,lease)
        launches=StageLaunches(runner,lease,directory)
        runner.popen=launches.launch
        runner.native_processes=launches
        original_temperature=runner.temperature
        def bounded_temperature(row):
            lease.check()
            return original_temperature(row)
        runner.temperature=bounded_temperature
        fresh=inspect_stage(runner,config)
        lease.check(1)
        last_publish=[0.0];last_timeline=[0.0];timeline_count=[0];safety_recorded=[False]
        def observe(jobs):
            now=time.monotonic()
            safety=any(j['result'].safety_stop for j in jobs)
            if now-last_publish[0]>=1 or safety:
                observation=dict(monotonic=now,
                    safety_stop=safety,devices=[dict(device_id=j['row']['device_id'],
                    state=j['result'].state,observation=j.get('last_snapshot'),
                    stop_reason=j['result'].stop_reason) for j in jobs])
                if snapshot:snapshot(observation)
                atomic_preflight_json(directory/'live.json',observation)
                if (timeline_count[0]<1024 and now-last_timeline[0]>=max(1,config.duration_seconds/1024)) or (safety and not safety_recorded[0]):
                    with (directory/'stage_monitoring.jsonl').open('a') as stream:
                        stream.write(json.dumps(observation)+'\n')
                    last_timeline[0]=now;timeline_count[0]+=1;safety_recorded[0]=safety
                last_publish[0]=now
        attempted=True
        directory_used,result=runner.run(config,fresh,directory/'activity',allow_partial=True,observe=observe,
            control=lambda jobs: ['all'] if os.getppid()!=parent_pid or lease.cancelled() or lease.clock()>=lease.deadline else [])
        result['evidence_directory']=str(directory_used)
        result['requested_stage_configuration']=requested_configuration
        result['stage_window_shortened']=config.duration_seconds<requested_configuration['duration_seconds']
        result['stage_deadline_monotonic']=lease.deadline
        code=0 if result['verdict'] in ('PASS','WARN') else 1
    except BaseException as exc:
        result = (error_result(str(exc),readiness=plan,cleanup_confirmed=not runner.unconfirmed)
            if attempted and not hasattr(runner,'last_preflight') else
            not_run(str(exc),readiness=getattr(runner,'last_preflight',plan)))
    finally:
        if launches is not None:
            launches.finish()
            result['stage_launch_ownership']=launches.snapshot()
            if not launches.cleanup_confirmed:
                result.update(cleanup_confirmed=False,failure='Stage native launch cleanup unconfirmed')
                code=1
            elif launches.publication_error or any(r.get('launch_failed') for r in launches.owned):
                result.update(failure=launches.publication_error or 'Stage native admission/launch failed; see ownership evidence')
                code=1
        try:
            result['execution_context']=plan.get('execution_context')
            if snapshot_stats is not None:result['live_status_transport']=dict(snapshot_stats)
            atomic_preflight_json(directory/'completion.json',result)
            if recovery is not None and recovery.fd is not None and not runner.unconfirmed and (launches is None or launches.cleanup_confirmed):
                if all(d.get('cleanup_confirmed') is True and not d.get('outstanding_descriptors') for d in result.get('devices',[])):
                    recovery.resolve(cleanup_confirmed=True)
            if snapshot:
                terminal=normalize(result)
                snapshot(dict(monotonic=time.monotonic(),safety_stop=False,devices=[],
                    auxiliary_outcome=terminal['auxiliary_outcome'],
                    reason=str(terminal.get('failure') or '; '.join(terminal.get('reasons') or terminal.get('evidence_errors') or []))[:1000]))
        finally:
            try:
                if recovery is not None:recovery.close()
            finally:
                runner.targets,runner.popen,runner.temperature,runner.native_processes=saved_runner
                if lease is not None and saved_check is not None:lease.check=saved_check
    return code


def channel_worker(fd):
    """All potentially slow initialization lives in this supervised process."""
    channel=StageChannel(*map(int,fd.split(':')));buffer=b'';directory=None;worker_entered=False
    stopped=[False]
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):
        signal.signal(sig,lambda *_:stopped.__setitem__(0,True))
    try:
        while b'\n' not in buffer:
            data=channel.recv(65536)
            if not data:return 1
            buffer+=data
            if len(buffer)>8*1024**2:raise ValueError('Bootstrap exceeds IPC budget')
        line,buffer=buffer.split(b'\n',1);request=json.loads(line)
        directory=Path(request['directory'])
        deadline=request['stage_deadline'];parent=request['supervisor_parent_pid'];token=request['stage_lease_id']
        def cancelled():
            if stopped[0] or os.getppid()!=parent:return True
            channel.setblocking(False)
            try:
                value=channel.recv(1,peek=True)
                return not value
            except BlockingIOError:return False
            except OSError:return True
        lease=StageLease(deadline,parent,cancelled,admission=SharedAdmission(request['admission_fd'],request['admission_identity']))
        lease.check()
        directory.mkdir(parents=True,exist_ok=False)
        plan=dict(request['plan'],execution_context=request['execution_context'],supervisor_parent_pid=parent,recovery_marker=request['recovery_marker'],
                  admission_lease_identity=request['admission_identity'])
        atomic_preflight_json(directory/'request.json',plan)
        def grant():
            nonlocal buffer
            lease.check(1)
            channel.settimeout(max(.001,deadline-time.monotonic()))
            channel.sendall((json.dumps(dict(ready=True,lease=token))+'\n').encode())
            while b'\n' not in buffer:
                lease.check()
                channel.settimeout(max(.001,deadline-time.monotonic()))
                data=channel.recv(65536)
                if not data:return False
                buffer+=data
                if len(buffer)>65536:raise ValueError('Stage grant exceeds IPC budget')
            line,buffer=buffer.split(b'\n',1);permission=json.loads(line)
            lease.check(1)
            return permission.get('run') is True and permission.get('lease')==token
        worker_entered=True
        pending_snapshot=b''
        snapshot_stats=dict(dropped_updates=0,partial_writes=0,closed=False)
        def snapshot(value):
            nonlocal pending_snapshot
            channel.setblocking(False)
            if snapshot_stats['closed']:
                snapshot_stats['dropped_updates']+=1;return
            if pending_snapshot:snapshot_stats['dropped_updates']+=1
            if not pending_snapshot:
                # Summary-only IPC is bounded even on very large inventories.
                compact=dict(monotonic=value['monotonic'],safety_stop=value['safety_stop'],devices=[])
                for row in value['devices']:
                    compact['devices'].append(row)
                    if len(json.dumps(compact).encode())>30000:
                        compact['devices'].pop();break
                compact['omitted_devices']=len(value['devices'])-len(compact['devices'])
                if value.get('auxiliary_outcome'):
                    compact.update(auxiliary_outcome=value['auxiliary_outcome'],reason=value.get('reason',''))
                pending_snapshot=(json.dumps(dict(snapshot=compact,lease=token))+'\n').encode()
            try:
                written=channel.send(pending_snapshot)
                if written<len(pending_snapshot):snapshot_stats['partial_writes']+=1
                pending_snapshot=pending_snapshot[written:]
            except (BlockingIOError,InterruptedError):pass  # retain at most one packet; no producer wait
            except OSError:
                pending_snapshot=b'';snapshot_stats['closed']=True
        return worker(directory,gate=grant,lease=lease,snapshot=snapshot,snapshot_stats=snapshot_stats)
    except BaseException as exc:
        if directory is not None:
            try:atomic_preflight_json(directory/'completion.json',
                dict(error_result('Stage worker/finalization exception: '+str(exc),cleanup_confirmed=False)
                if worker_entered else not_run(str(exc)),execution_context=request.get('execution_context')))
            except OSError:pass
        return 1
    finally:channel.close()


if __name__ == '__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='--channel':
        raise SystemExit('Internal stage adapter requires an inherited stage lease channel')
    raise SystemExit(channel_worker(sys.argv[2]))
