"""Explicit system access authority, established only inside the trusted service.

Configuration is intent, never privilege. Canonical recovery is unchanged. Limits
cover LVS logical output, not filesystem amplification or ordinary OS writes.
"""
from contextvars import ContextVar
import errno
import hashlib
import json
import os
from pathlib import Path
import resource
import stat
import re
import pwd

_BUDGET = ContextVar('thermal_control_budget', default=None)
FILE_LIMIT = 8 * 1024**2


def owned_path(path, directory=False):
    path=Path(path)
    if not path.is_absolute():raise ValueError('absolute installed path required')
    for item in (path,*path.parents):
        s=item.lstat()
        if s.st_uid!=0 or s.st_mode&0o022:raise ValueError('untrusted installed ownership: '+str(item))
        valid=stat.S_ISDIR(s.st_mode) if item!=path or directory else stat.S_ISREG(s.st_mode)
        if not valid:raise ValueError('untrusted installed type: '+str(item))
    return path



def valid_system_proof(proof, device):
    return (type(proof) is dict and proof.get('contract')=='shared_system_readonly_v1'
            and proof.get('physical_id')==device
            and type(proof.get('device_ids')) in (list,tuple)
            and all(type(item) is str for item in proof['device_ids'])
            and device in proof['device_ids']
            and type(proof.get('colocated')) is bool and proof['colocated']
            and type(proof.get('swap')) is bool
            and all(type(proof.get(k)) is int and 0<proof[k]<2**32-1 for k in ('worker_uid','worker_gid','operator_uid'))
            and proof['worker_uid']!=proof['operator_uid']
            and type(proof.get('topology_generation')) is str
            and re.fullmatch('[0-9a-f]{64}',proof['topology_generation']) is not None)


def postexec_witness_valid(value,uid,gid,pid,identity):
    if (type(value)is not dict or type(identity)is not dict or
            any(type(v)is not int or v<=0 for v in (uid,gid,pid)) or pid<=1 or
            any(type(identity.get(k))is not int or identity[k]<0 for k in ('major','minor')) or
            type(identity.get('size_bytes'))is not int or identity['size_bytes']<=0):return False
    expected=dict(contract_id='lvs.storage_thermal.postexec',version=1,pid=pid,uid=uid,gid=gid,dumpable=0,state_locked=True,thread_sync=True,target_deferred=True,
                  major=identity.get('major'),minor=identity.get('minor'),size=identity.get('size_bytes'))
    return (type(value)is dict and type(pid)is int and pid>1 and
            all(k in value and type(value[k])is type(v)and value[k]==v for k,v in expected.items())and
            type(value.get('parent'))is int and value['parent']>1)


def charge_output(value):
    budget = _BUDGET.get()
    if budget is not None:
        size = len(value.encode('utf-8')) if isinstance(value, str) else len(json.dumps(value, indent=2).encode('utf-8'))
        budget.charge(size)


def write_observation(stream, value):
    line = json.dumps(value) + '\n'
    charge_output(line)
    stream.write(line)


class ControlBudget:
    def __init__(self, devices):
        self.limit = 32 * 1024**2 + devices * 8 * 1024**2
        self.log_reserve = devices * 2 * FILE_LIMIT
        self.used = 8192  # reserve both canonical journal publications

    def charge(self, size):
        if size < 0 or self.used + size > self.limit:
            raise OSError(errno.ENOSPC, 'Thermal control-plane logical write budget exhausted')
        self.used += size  # failed publication also consumes its attempted budget

    def space(self, path):
        path = Path(path)
        while not path.exists():
            path = path.parent
        fs = os.statvfs(path)
        required = 2 * (self.limit + self.log_reserve)
        if fs.f_bavail * fs.f_frsize < required:
            raise OSError(errno.ENOSPC, 'Insufficient control-plane free-space reserve')
        return dict(logical_bytes=self.limit, worker_log_extent_bytes=self.log_reserve,
                    required_free_bytes=required, scope='LVS auxiliary output; not physical writes')


class SystemAuthority:
    """Private server policy. No caller can supply this object or its tool paths."""
    def __init__(self, root, manifest):
        self.root, self.manifest = Path(root), manifest

    def worker(self, confidential=True):
        m = self.manifest
        uid, gid = m.get('worker_uid'), m.get('worker_gid')
        if (os.geteuid() != 0 or type(uid) is not int or type(gid) is not int or
                not 0 < uid < 2**32-1 or not 0 < gid < 2**32-1 or uid == m['uid']):
            raise ValueError('System access requires a separately approved dedicated non-root worker identity')
        try:account=pwd.getpwuid(uid)
        except KeyError:raise ValueError('Dedicated lvs-thermal-worker account is not installed') from None
        if (account.pw_name!='lvs-thermal-worker' or account.pw_gid!=gid or
                account.pw_shell not in ('/sbin/nologin','/usr/sbin/nologin','/bin/false')):
            raise ValueError('System worker must be the dedicated non-login lvs-thermal-worker account')
        fio = owned_path(self.root/'runtime/build/fio')
        if fio.stat().st_mode & 0o044:
            raise ValueError('System worker requires unreadable trusted fio')
        if confidential:
            hook=owned_path(self.root/'runtime/build/storage_thermal_confidential.so')
            expected=m.get('files',{}).get('runtime/build/storage_thermal_confidential.so')
            proof=(m.get('backend')or{}).get('postexec_confidentiality')or{}
            if not expected or hashlib.sha256(hook.read_bytes()).hexdigest()!=expected or proof.get('status')!='verified':
                raise ValueError('Verified final-exec nondumpable worker protection required')
        return uid,gid

    def approve(self, config):
        if not config.system_device_ids:return None
        uid,gid=self.worker();m=self.manifest
        return dict(contract='shared_system_readonly_v1', device_ids=list(config.system_device_ids),
                    colocated=config.control_plane_colocation, swap=config.system_swap,
                    worker_uid=uid, worker_gid=gid, operator_uid=m['uid'],confidentiality='separate_uid_postexec_nondumpable_v1',postexec_required=True)

    def activate(self, config):
        proof = self.approve(config)
        if proof is None:
            return None
        budget = ControlBudget(len(config.device_ids))
        budget.space(self.root)
        budget.space('/var/lib/lvs-thermal')
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_LIMIT, FILE_LIMIT))
        _BUDGET.set(budget)  # request handler is a disposable owned process
        return budget


def configure_targets(targets, config, authority):
    targets.system_approval = None
    targets.system_config = config
    if config.system_device_ids:
        if authority is None:
            raise ValueError('System access is available only through the trusted installed service')
        targets.system_approval = authority.approve(config)
