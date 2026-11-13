"""Overlay syntax and narrowly bound OSTree detached-image ancestry, metadata only."""
from __future__ import annotations
import ctypes
import os
from pathlib import Path
import re
import stat


def _split(value: str, delimiter: str) -> list[str]:
    """Split before decoding escaped delimiters, including mountinfo octal escapes."""
    fields=[];part='';i=0
    while i<len(value):
        if value[i]=='\\':
            if i+1==len(value):raise ValueError('truncated overlay escape')
            n=4 if re.match(r'\\[0-7]{3}',value[i:]) else 2
            part+=value[i:i+n];i+=n
        elif value[i]==delimiter:fields.append(part);part='';i+=1
        else:part+=value[i];i+=1
    fields.append(part);return fields


def _decode(value: str) -> str:
    return re.sub(r'\\([0-7]{3}|.)',lambda m:chr(int(m[1],8)) if len(m[1])==3 else m[1],value)


def overlay_layers(line: str) -> tuple[list[tuple[str,Path]],set[str]]:
    fields=line.split(' - ',1)[1].split()
    if len(fields)!=3:raise ValueError('malformed overlay mount record')
    layers=[];flags=set();singles=set()
    for option in _split(fields[2],','):
        key,sep,value=option.partition('=')
        if key not in ('lowerdir','lowerdir+','datadir+','upperdir','workdir'):
            if key.startswith(('lowerdir','datadir','upperdir','workdir')):raise ValueError('unsupported overlay layer option '+key)
            flags.add(option);continue
        if not sep:raise ValueError('missing overlay layer value')
        if key in ('lowerdir','upperdir','workdir'):
            if key in singles:raise ValueError('duplicate overlay layer declaration')
            singles.add(key)
        if key=='lowerdir':
            # :: starts data-only layers; separators are parsed before unescaping.
            parts=_split(value,':');kind='lower';previous_empty=False
            for part in parts:
                if not part:
                    if not layers or previous_empty:raise ValueError('invalid lower/data layer separator')
                    kind='data';previous_empty=True;continue
                layers.append((kind,Path(_decode(part))));previous_empty=False
            if previous_empty:raise ValueError('empty trailing overlay layer')
        else:layers.append(('lower' if key=='lowerdir+' else 'data' if key=='datadir+' else key,Path(_decode(value))))
    if not any(k=='lower' for k,p in layers):raise ValueError('no metadata lower layer declared')
    if 'lowerdir' in singles and any(x.startswith('lowerdir+=') for x in _split(fields[2],',')):
        raise ValueError('mixed legacy and appended lower layers')
    if ('upperdir' in singles)!=('workdir' in singles):raise ValueError('upper/work layer pair incomplete')
    if any(not p.is_absolute() or '..' in p.parts or '\x00' in str(p) for k,p in layers):
        raise ValueError('invalid or relative overlay layer path')
    return layers,flags


def boot_record(path=Path('/run/ostree-booted'), *, owner=0) -> dict:
    """Decode bounded root-owned GVariant with OS GLib, not PyGObject or a tool."""
    fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_uid!=owner or before.st_mode&0o022 or not 1<=before.st_size<=65536:
            raise ValueError('untrusted OSTree boot record')
        raw=os.read(fd,65537);after=os.fstat(fd)
        attrs=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        if len(raw)!=before.st_size or attrs(before)!=attrs(after):raise ValueError('OSTree boot record changed')
    finally:os.close(fd)
    try:g=ctypes.CDLL('libglib-2.0.so.0')
    except OSError as e:raise ValueError('OSTree boot decoder unavailable (system GLib required)') from e
    ptr=ctypes.c_void_p
    for name,args,result in [('g_bytes_new',[ptr,ctypes.c_size_t],ptr),('g_bytes_unref',[ptr],None),
        ('g_variant_type_new',[ctypes.c_char_p],ptr),('g_variant_type_free',[ptr],None),
        ('g_variant_new_from_bytes',[ptr,ptr,ctypes.c_int],ptr),('g_variant_is_normal_form',[ptr],ctypes.c_int),
        ('g_variant_unref',[ptr],None),('g_variant_lookup_value',[ptr,ctypes.c_char_p,ptr],ptr),
        ('g_variant_get_boolean',[ptr],ctypes.c_int),('g_variant_get_uint64',[ptr],ctypes.c_uint64),
        ('g_variant_get_child_value',[ptr,ctypes.c_size_t],ptr),('g_variant_n_children',[ptr],ctypes.c_size_t),
        ('g_variant_get_string',[ptr,ptr],ctypes.c_char_p)]:
        f=getattr(g,name);f.argtypes=args;f.restype=result
    data=ctypes.create_string_buffer(raw);b=g.g_bytes_new(data,len(raw));typ=g.g_variant_type_new(b'a{sv}')
    variant=g.g_variant_new_from_bytes(typ,b,False)
    try:
        if not g.g_variant_is_normal_form(variant) or not 1<=g.g_variant_n_children(variant)<=128:raise ValueError('malformed OSTree boot record')
        keys=set()
        for i in range(g.g_variant_n_children(variant)):
            entry=g.g_variant_get_child_value(variant,i);key=g.g_variant_get_child_value(entry,0)
            try:
                value=g.g_variant_get_string(key,None)
                if value in keys:raise ValueError('duplicate OSTree boot record key')
                keys.add(value)
            finally:g.g_variant_unref(key);g.g_variant_unref(entry)
        def get(key,signature,read):
            t=g.g_variant_type_new(signature);v=g.g_variant_lookup_value(variant,key.encode(),t)
            try:
                if not v:raise ValueError('missing/invalid OSTree '+key)
                return read(v)
            finally:
                if v:g.g_variant_unref(v)
                g.g_variant_type_free(t)
        def pair(v):
            values=[]
            for i in range(2):
                child=g.g_variant_get_child_value(v,i)
                try:values.append(int(g.g_variant_get_uint64(child)))
                finally:g.g_variant_unref(child)
            return tuple(values)
        return {**{k:bool(get(k,b'b',g.g_variant_get_boolean)) for k in ('composefs','root.transient','root.transient-ro')},
                'backing-root-device-inode':get('backing-root-device-inode',b'(tt)',pair)}
    finally:g.g_variant_unref(variant);g.g_variant_type_free(typ);g.g_bytes_unref(b)


def composefs_image(mount,line,layers,flags,proc=Path('/proc')) -> Path | None:
    """Only OSTree's readonly boot root has an OS-published detached-image proof.

    The source label/path alone is NOT authority. Match the kernel boot argument
    to the root-owned OS boot record's device/inode before mapping the image.
    """
    if mount.mount_point!=Path('/') or mount.source!='composefs':return None
    lowers=[p for k,p in layers if k=='lower'];data=[p for k,p in layers if k=='data']
    if lowers!=[Path('/run/ostree/.private/cfsroot-lower')]:return None
    if not {'ro','metacopy=on','redirect_dir=on'}<=flags or any(k in ('upperdir','workdir') for k,p in layers):
        raise ValueError('OSTree composefs root contract mismatch')
    roots={p.parents[2] for p in data if p.parts[-3:]==('ostree','repo','objects')}
    if len(roots)!=1:raise ValueError('OSTree object-store/deployment relationship ambiguous')
    record=boot_record()
    if not record['composefs'] or record['root.transient'] or record['root.transient-ro']:
        raise ValueError('OSTree boot record does not attest this readonly composefs root')
    arguments=[v.split('=',1)[1] for v in (proc/'cmdline').read_text().split() if v.startswith('ostree=')]
    if len(arguments)!=1 or not arguments[0].startswith('/') or '..' in Path(arguments[0]).parts:
        raise ValueError('kernel OSTree deployment argument missing/ambiguous')
    deployment=(next(iter(roots))/arguments[0].lstrip('/')).resolve(strict=True)
    identity=deployment.stat()
    if (identity.st_dev,identity.st_ino)!=record['backing-root-device-inode']:
        raise ValueError('kernel deployment and OSTree boot identity differ')
    image=(deployment/'.ostree.cfs').resolve(strict=True);info=image.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
        raise ValueError('OSTree metadata image is not a trusted regular file')
    return image
