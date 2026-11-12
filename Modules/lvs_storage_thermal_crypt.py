"""Key-free kernel status proof for a single conventional dm-crypt mapping.

Never request DM_STATUS_TABLE_FLAG: table parameters can contain encryption keys.
Only fixed INFO/NOFLUSH ioctls are permitted; raw response buffers are not evidence.
"""
from __future__ import annotations
import fcntl
import os
from pathlib import Path
import re
import stat
import struct


def crypt_status(node: Path, control=Path('/dev/mapper/control')) -> dict:
    """Query kernel target type, generation and geometry, without table parameters."""
    major,minor=map(int,(node/'dev').read_text().strip().split(':'))
    uuid=(node/'dm/uuid').read_text().strip()
    if not re.fullmatch(r'CRYPT-LUKS[12]-[0-9a-fA-F]{32}-.+',uuid):
        raise ValueError('only conventional LUKS mappings are qualified')
    fd=os.open(control,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
    try:
        s=os.fstat(fd)
        if not stat.S_ISCHR(s.st_mode):raise ValueError('device-mapper control is not a character device')
        result=[]
        for _ in range(2):
            data=bytearray(4096)
            struct.pack_into('=3I',data,0,4,0,0)
            struct.pack_into('=II',data,12,len(data),312)
            struct.pack_into('=I',data,28,1<<11)  # NOFLUSH, INFO (not TABLE)
            struct.pack_into('=Q',data,40,os.makedev(major,minor))
            fcntl.ioctl(fd,0xC138FD0C,data,True)  # DM_TABLE_STATUS, sizeof(dm_ioctl)=312
            size,start,count=struct.unpack_from('=III',data,12)
            flags,event=struct.unpack_from('=II',data,28)
            dev=struct.unpack_from('=Q',data,40)[0]
            actual_uuid=bytes(data[176:305]).split(b'\0',1)[0].decode('ascii')
            if (size>len(data) or start<312 or start+40>size or count!=1 or dev!=os.makedev(major,minor)
                    or actual_uuid!=uuid or flags&((1<<1)|(1<<6)|(1<<8)|(1<<4)) or not flags&(1<<5)):
                raise ValueError('ambiguous, suspended or changing device-mapper ownership')
            sector,length,status,next_offset,kind=struct.unpack_from('=QQiI16s',data,start)
            if sector!=0 or length<=0 or status or kind.split(b'\0',1)[0]!=b'crypt':
                raise ValueError('only one active crypt target is qualified')
            # INFO status for crypt carries no key parameters. Do not retain any payload.
            result.append(dict(device=f'{major}:{minor}',uuid=uuid,event=event,sectors=length))
        if result[0]!=result[1]:raise ValueError('device-mapper generation changed')
        if int((node/'size').read_text())!=result[0]['sectors']:raise ValueError('crypt geometry mismatch')
        return result[0]
    finally:os.close(fd)
