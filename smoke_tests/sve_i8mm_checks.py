"""Scalable SVE I8MM software evidence; never physical acceptance."""
from __future__ import annotations
from copy import deepcopy
import ctypes
import ctypes.util
import importlib.util
import json
import os
from pathlib import Path
import random
import re
import shutil
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
from smoke_tests.sve2_smlal_checks import _build
from smoke_tests.neon_dotprod_checks import _frontend_checks
from Modules.lvs_worker_integrity import worker_result_successful,worker_verification_satisfied
ROOT=Path(__file__).resolve().parents[1]
KERNEL='sve_i8mm'
OPERATION='sve_segmented_s8_s8_u8_u8_u8_s8_matrix_2x8_8x2'


def _valid(vl=16):
    from smoke_tests.sve2_smlal_checks import _valid as sve_valid
    w=sve_valid(vl)
    for k in ['mode','kernel_flavor']:w[k]=KERNEL
    w.pop('bottom_top_mapping');w.pop('multiply_accumulate_rounds_per_block')
    w.update(verification_contract=KERNEL+'_v1',verification_method='wide_integer_segmented_matrix_reference_modulo_2_32',
             operation_family=OPERATION,execution_implementation='aarch64_sve_i8mm_asm',actual_isa='svei8mm',
             matrix_rounds_per_block=256,witness_rounds_per_block=1,signed_chains=3,unsigned_chains=3,mixed_chains=2,
             products_per_lane=8,matrix_segment_bits=128,matrix_layout='a_row_major_b_column_major_c_row_major')
    w['threads_detail'][0].update(matrix_segments_per_chain=vl//16,isa_hwcap2=1<<9)
    return w


def _run(binary,directory,vl=16,*,fail=False,workers=1):
    path=Path(directory)/(str(time.monotonic_ns())+'.json');cpus=sorted(os.sched_getaffinity(0))[:workers]
    proc=subprocess.Popen([str(binary),'--mode',KERNEL,'--kernel-flavor',KERNEL,'--threads',str(len(cpus)),
        '--cpu-ids',','.join(map(str,cpus)),'--result-file',str(path)],env={**os.environ,'LVS_TEST_SVE_I8MM_VL_BYTES':str(vl)},stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        if not fail:
            deadline=time.monotonic()+10;sidecar=Path(str(path)+'.progress.jsonl')
            while time.monotonic()<deadline and proc.poll() is None:
                if sidecar.exists() and '"state":"initial"' in sidecar.read_text():break
                time.sleep(.02)
            assert proc.poll() is None,proc.communicate();proc.terminate()
        out,err=proc.communicate(timeout=10)
    finally:
        if proc.poll() is None:proc.kill();proc.communicate(timeout=5)
    w=json.loads(path.read_text());w.update(observed_exit_code=proc.returncode,result_path=str(path));return w


class Case(ctypes.Structure):
    _fields_=[('a',ctypes.c_uint8*2048),('b',ctypes.c_uint8*2048),('initial',ctypes.c_uint32*512),('expected',ctypes.c_uint32*512),('witness',ctypes.c_uint32*512)]


def _matrix(initial,a,b,row,col,kind,rounds):
    def value(x,unsigned):return x if unsigned or x<128 else x-256
    left=[a[:8],a[8:]];right=list(zip(b[:8],b[8:]))
    dot=sum(value(left[row][k],kind!=0)*value(right[k][col],kind==1) for k in range(8))
    return (initial+rounds*dot)&0xffffffff


def run_sve_i8mm_reference_checks():
    with TemporaryDirectory(prefix='lvs-svei8mm-reference-') as tmp:
        src=Path(tmp)/'ref.c'
        src.write_text('#define main fixture_main\n#include "'+str(ROOT/'native/cpu_stress_helper.c')+'"\n'
            'int cap(uint64_t h,uint64_t h2){return sve_i8mm_capability(h,h2);}\n'
            'int state(int s){return sve_i8mm_valid_state(s);}\n'
            'uint32_t ref(uint32_t c,uint8_t*a,uint8_t*b,int r,int col,int kind,int rounds){return sve_i8mm_reference(c,a,b,r,col,kind,rounds);}\n'
            'void cases(sve_i8mm_case_t*c,uint32_t seed,int lanes){prepare_sve_i8mm_case(c,seed,lanes);}\n')
        lib=Path(tmp)/'r.so';subprocess.run(['gcc','-O2','-std=c11','-pthread','-shared','-fPIC',str(src),'-o',str(lib)],check=True,capture_output=True)
        dll=ctypes.CDLL(str(lib));dll.cap.argtypes=[ctypes.c_uint64]*2;dll.ref.restype=ctypes.c_uint32
        dll.ref.argtypes=[ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint8),ctypes.POINTER(ctypes.c_uint8),ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int]
        assert dll.cap((1<<22)|3,1<<9) # Neither SVE2 nor NEON I8MM is inferred.
        for h,h2 in [(3,1<<9),(1<<22,1<<9),((1<<22)|1,1<<9),((1<<22)|2,1<<9),((1<<22)|3,1<<13),((1<<22)|3,2)]:assert not dll.cap(h,h2)
        for vl in range(16,257,16):assert dll.state(vl) and dll.state(vl|(1<<17))
        for state in [-1,0,15,17,31,260,512,16|(1<<18)]:assert not dll.state(state)
        byte=ctypes.c_uint8*16
        for kind in range(3):
            for ai in range(16):
                for bi in range(16):
                    a=[0]*16;b=[0]*16;a[ai]=255;b[bi]=128
                    for lane in range(4):
                        for rounds in [1,256]:assert dll.ref(0xffffffff,byte(*a),byte(*b),lane//2,lane%2,kind,rounds)==_matrix(0xffffffff,a,b,lane//2,lane%2,kind,rounds)
        rng=random.Random(67812)
        for _ in range(1000):
            a=[rng.randrange(256) for _ in range(16)];b=[rng.randrange(256) for _ in range(16)];c=rng.choice([0,0x7fffffff,0x80000000,0xffffffff])
            for kind in range(3):
                for lane in range(4):assert dll.ref(c,byte(*a),byte(*b),lane//2,lane%2,kind,256)==_matrix(c,a,b,lane//2,lane%2,kind,256)
        dll.cases.argtypes=[ctypes.POINTER(Case),ctypes.c_uint32,ctypes.c_int]
        for vl in range(16,257,16):
            for seed in [1,17,0xffffffff]:
                c=Case();lanes=vl//4;dll.cases(ctypes.byref(c),seed,lanes)
                for n in range(8*lanes):
                    chain,lane=divmod(n,lanes);base=chain*vl+16*(lane//4);kind=0 if chain<3 else 1 if chain<6 else 2
                    a=list(c.a[base:base+16]);b=list(c.b[base:base+16]);initial=c.initial[n]
                    assert c.expected[n]==_matrix(initial,a,b,(lane%4)//2,lane%2,kind,256)
                    assert c.witness[n]==_matrix(initial,a,b,(lane%4)//2,lane%2,kind,1)
        assert ctypes.sizeof(Case)==10240


def _trace(body,vl,rounds=256,final=0,stop=None,actual=None,change_after=False):
    """Bounded interpreter for emitted scalar control and full-predicate SVE data.
    Track each loaded coefficient/accumulator, every effective matrix update and
    full VL store. Unknown operations, inactive predicates or wrong strides reject.
    """
    code=[];labels={}
    for line in body.splitlines():
        line=line.split('//',1)[0].strip()
        if not line or line.startswith('#'):continue
        match=re.match(r'^([\w.$]+):\s*(.*)',line)
        if match:labels.setdefault(match[1],[]).append(len(code));line=match[2]
        if line and not line.startswith('.'):
            parts=line.split(None,1);op={'bne':'b.ne','beq':'b.eq','blo':'b.lo','bcc':'b.lo','b.cc':'b.lo','bhs':'b.hs','bcs':'b.hs','b.cs':'b.hs','bhi':'b.hi','bls':'b.ls'}.get(parts[0],parts[0]);code.append((op,re.split(r',\s*(?![^\[]*\])',parts[1]) if len(parts)>1 else []))
    hardware=vl if actual is None else actual;cnts=0
    regs={'x0':0x10000,'x1':0x30000,'x2':vl//4,'x3':rounds,'x4':final,'sp':0x50000};pred={};vec={};stores={};counts=[0]*8;pc=0;zero=False;carry=False
    def scalar(x):
        x=x.strip()
        if x in ['xzr','wzr']:return 0
        if ':lo12:' in x:return 0
        if x.startswith('#'):return int(x[1:],0)
        return regs['x'+x[1:] if x.startswith('w') else x]
    def assign(x,v):regs['x'+x[1:] if x.startswith('w') else x]=v&((1<<32)-1 if x.startswith('w') else (1<<64)-1)
    def jump(x):
        m=re.fullmatch(r'(\d+)([bf])',x)
        if m:return max(p for p in labels[m[1]] if p<pc) if m[2]=='b' else min(p for p in labels[m[1]] if p>=pc)
        assert len(labels[x])==1;return labels[x][0]
    def vector(x):return int(re.fullmatch(r'z(\d+)\.[bs]',x)[1])
    for step in range(30000):
        assert 0<=pc<len(code);op,args=code[pc];pc+=1;args=[a.strip() for a in args]
        if op in ['stp','ldp','str']:
            assert any('[sp' in x for x in args) and all(re.fullmatch(r'd\d+',a) for a in args[:2 if op!='str' else 1]),(op,args)
        elif op in ['mov','sxtw','uxtw']:
            value=scalar(args[1]);value=value-(1<<32) if op=='sxtw' and value&(1<<31) else value
            assign(args[0],value)
        elif op=='adrp':assign(args[0],0x40000)
        elif op in ['add','sub','and','orr']:
            a,b=scalar(args[1]),scalar(args[2]);b<<=int(args[3].split('#')[1]) if len(args)>3 else 0
            assign(args[0],a+b if op=='add' else a-b if op=='sub' else a&b if op=='and' else a|b)
        elif op in ['cmp','cmn','tst']:
            a,b=map(scalar,args);width=32 if args[0].startswith('w') else 64;value=a+b if op=='cmn' else a&b if op=='tst' else a-b
            zero=(value&((1<<width)-1))==0;carry=value>=(1<<width) if op=='cmn' else a>=b
        elif op=='b':pc=jump(args[0])
        elif op in ['b.eq','b.ne','b.lo','b.hs','b.hi','b.ls']:
            take={'b.eq':zero,'b.ne':not zero,'b.lo':not carry,'b.hs':carry,'b.hi':carry and not zero,'b.ls':not carry or zero}[op]
            if take:pc=jump(args[0])
        elif op in ['cbz','cbnz']:
            if (scalar(args[0])==0)==(op=='cbz'):pc=jump(args[1])
        elif op=='cntw':
            assign(args[0],(hardware+16 if change_after and cnts else hardware)//4);cnts+=1
        elif op=='ptrue':
            assert (len(args)==1 or (len(args)==2 and args[1]=='all')) and re.fullmatch(r'p\d+\.[bs]',args[0]);p,t=args[0].split('.');pred[p]=(t,hardware)
        elif op in ['ld1b','ld1w','st1w']:
            v=re.fullmatch(r'\{\s*(z\d+\.[bs])\s*\}',args[0]);assert v;v=v[1]
            p=args[1].split('/')[0];assert pred[p]==('b' if op=='ld1b' else 's',hardware)
            assert args[1]==p+('/z' if op.startswith('ld') else '')
            m=re.fullmatch(r'\[(x\d+)(?:,\s*#(-?\d+),\s*mul vl)?\]',args[2]);assert m,args
            address=scalar(m[1])+(int(m[2])*hardware if m[2] else 0)
            if op=='ld1b':
                base,kind=(0x10000,'a') if address<0x10800 else (0x10800,'b')
                offset=address-base;assert 0<=offset<8*hardware and offset%hardware==0
                vec[vector(v)]=(kind,offset//hardware)
            elif op=='ld1w':
                offset=address-0x11000;assert 0<=offset<8*hardware and offset%hardware==0
                vec[vector(v)]=(offset//hardware,0)
            else:
                offset=address-0x30000;assert 0<=offset<8*hardware and offset%hardware==0 and offset not in stores
                stores[offset]=vec[vector(v)]
        elif op in ['smmla','ummla','usmmla']:
            assert re.fullmatch(r'z\d+\.s',args[0]) and all(re.fullmatch(r'z\d+\.b',a) for a in args[1:])
            dest,left,right=map(vector,args);chain,updates=vec[dest]
            assert type(chain) is int and op==('smmla' if chain<3 else 'ummla' if chain<6 else 'usmmla')
            assert vec[left]==('a',chain) and vec[right]==('b',chain) and updates<rounds
            vec[dest]=(chain,updates+1);counts[chain]+=1
        elif op=='ldr':
            assert scalar(args[1].strip('[]'))>=0x40000
            assign(args[0],int(stop is None or max(counts)<stop))
        elif op=='ret':
            result=scalar('w0')
            if actual is not None and hardware!=vl or change_after:
                assert result==0xffffffff and not stores
            elif final or stop is None:
                assert result==1 and counts==[rounds]*8 and stores=={i*hardware:(i,rounds) for i in range(8)},(result,counts,stores)
            else:assert result==0 and not stores and max(counts)<=stop
            return
        elif op!='nop':raise AssertionError(('unknown emitted operation',op,args))
    raise AssertionError('unbounded emitted control flow')


def _object_body(path):
    data=path.read_bytes();assert data[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<H',data,18)[0]==183
    offset=struct.unpack_from('<Q',data,40)[0];size,count=struct.unpack_from('<HH',data,58);sections=[struct.unpack_from('<IIQQQQIIQQ',data,offset+i*size) for i in range(count)];body=None
    for sec in sections:
        if sec[1]!=2:continue
        names=sections[sec[6]];strings=data[names[4]:names[4]+names[5]]
        for pos in range(sec[4],sec[4]+sec[5],sec[9]):
            name,info,other,index,value,length=struct.unpack_from('<IBBHQQ',data,pos)
            if strings[name:].split(b'\0',1)[0]==b'execute_sve_i8mm_block':
                section=sections[index];start=section[4]+value-section[3];body=data[start:start+length]
    assert body
    library=ctypes.util.find_library('LLVM') or ctypes.util.find_library('LLVM-22')
    if not library:
        tool=shutil.which('aarch64-linux-gnu-objdump') or shutil.which('llvm-objdump') or (shutil.which('objdump') if os.uname().machine=='aarch64' else None)
        assert tool,'AArch64 disassembler required for emitted object evidence'
        text=subprocess.check_output([tool,'-d','--disassemble=execute_sve_i8mm_block',str(path)],text=True);lines=[]
        for line in text.splitlines():
            m=re.match(r'^\s*([0-9a-f]+):\s+(?:[0-9a-f]{8}|(?:[0-9a-f]{2}\s+){3}[0-9a-f]{2})\s+(.+)$',line)
            if not m:continue
            pc=int(m[1],16);instruction=m[2].split('//',1)[0].strip();op=instruction.split()[0]
            if re.fullmatch(r'b(?:\.(?:ne|eq|lo|hs|hi|ls|cc|cs))?|cbnz|cbz',op):
                target=re.search(r'([0-9a-f]+)\s*(?:<[^>]+>)?$',instruction);assert target,instruction
                instruction=instruction[:target.start()]+'.L'+str(int(target[1],16))
            lines.append('.L'+str(pc)+':\n'+instruction)
        assert lines;return '\n'.join(lines)
    lib=ctypes.CDLL(library)
    for part in ['TargetInfo','Target','TargetMC','Disassembler']:getattr(lib,'LLVMInitializeAArch64'+part)()
    lib.LLVMCreateDisasmCPUFeatures.restype=ctypes.c_void_p;lib.LLVMCreateDisasmCPUFeatures.argtypes=[ctypes.c_char_p]*3+[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p]
    ctx=lib.LLVMCreateDisasmCPUFeatures(b'aarch64-linux-gnu',b'generic',b'+sve,+i8mm',None,0,None,None);assert ctx
    lib.LLVMDisasmInstruction.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint64,ctypes.c_uint64,ctypes.c_char_p,ctypes.c_size_t];lib.LLVMDisasmInstruction.restype=ctypes.c_size_t;lib.LLVMDisasmDispose.argtypes=[ctypes.c_void_p]
    lines=[]
    try:
        for i in range(0,len(body),4):
            out=ctypes.create_string_buffer(256);raw=ctypes.create_string_buffer(body[i:i+4]);assert lib.LLVMDisasmInstruction(ctx,raw,4,i,out,256)==4
            line=out.value.decode();op=line.strip().split()[0]
            if op in ['b','b.ne','b.eq','b.lo','b.hs','b.hi','b.ls','cbz','cbnz']:
                m=re.search(r'#(-?(?:0x[0-9a-f]+|\d+))\s*$',line);assert m,line;line=line[:m.start()]+'.L'+str(i+int(m[1],0))
            lines.append('.L'+str(i)+':\n'+line)
    finally:lib.LLVMDisasmDispose(ctx)
    return '\n'.join(lines)


def run_sve_i8mm_emission_checks():
    with TemporaryDirectory(prefix='lvs-svei8mm-emission-') as tmp:
        cross=shutil.which('aarch64-linux-gnu-gcc');compiler=[cross] if cross else ['gcc'] if os.uname().machine=='aarch64' else [sys.executable,'-m','ziglang','cc','-target','aarch64-linux-gnu']
        assert cross or os.uname().machine=='aarch64' or importlib.util.find_spec('ziglang')
        for flags in [[],['SVE_I8MM'],['SVE_I8MM','SVE2','I8MM','DOTPROD','FP16','FHM','BF16']]:
            asm=Path(tmp)/'w.s';obj=Path(tmp)/'w.o';cmd=[*compiler,'-O3','-std=c11','-pthread',*['-DLVS_CPU_HELPER_ENABLE_'+f for f in flags],str(ROOT/'native/cpu_stress_helper.c')];env={**os.environ,'ZIG_GLOBAL_CACHE_DIR':tmp+'/cache'}
            for option,path in [('-S',asm),('-c',obj)]:subprocess.run([*cmd,option,'-o',str(path)],env=env,check=True,capture_output=True,timeout=120)
            text=asm.read_text();match=re.search(r'execute_sve_i8mm_block[^:\n]*:',text)
            if not flags:assert not match;continue
            assert match;body=text[match.end():].split('.size',1)[0];decoded=_object_body(obj)
            for code in [body,decoded]:
                for vl in [16,32,48,64,128,256]:
                    for rounds,final,stop in [(256,0,None),(256,1,0),(256,0,0),(256,0,64),(1,1,0)]:_trace(code,vl,rounds,final,stop)
                    _trace(code,vl,actual=vl+16);_trace(code,vl,change_after=True)
            # Register renaming and unreachable extra sites cannot replace
            # effective recurrence/data flow; static opcode counts are not used.
            renamed=body.replace('z0.','TEMP.').replace('z7.','z0.').replace('TEMP.','z7.')
            _trace(renamed,32)
            _trace(body+'\nsmmla z0.s, z8.b, z16.b\n',32)
            for bad in [body.replace('usmmla','ummla'),body.replace('smmla','ummla'),re.sub(r'\bptrue\s+p1\.s','ptrue p1.b',body),body.replace('#7, mul vl','#6, mul vl'),re.sub(r'\badd\s+(w\d+),\s*\1,\s*#1',r'add \1, \1, #2',body),re.sub(r'\bst1w[^\n]+','',body)]:
                assert bad!=body
                try:_trace(bad,48)
                except (AssertionError,KeyError,TypeError):pass
                else:raise AssertionError('incorrect emitted SVE matrix workload accepted')


def run_sve_i8mm_lifecycle_checks():
    with TemporaryDirectory(prefix='lvs-svei8mm-lifecycle-') as tmp:
        baseline=_build(tmp,'baseline');caps=json.loads(subprocess.check_output([str(baseline),'--print-isa-capabilities'],text=True));assert caps['sve_i8mm_available'] is False
        for flag in ['--mode','--kernel-flavor']:assert subprocess.run([str(baseline),flag,KERNEL,'--print-kernel-flavor'],capture_output=True).returncode==3
        assert KERNEL not in subprocess.check_output([str(baseline),'--print-supported-kernels'],text=True)
        b=_build(tmp,'emulated','-DLVS_CPU_HELPER_TEST_SVE_I8MM')
        for vl in range(16,257,16):
            w=_run(b,tmp,vl,workers=2);assert worker_result_successful(w),w
            assert w['execution_implementation']==w['actual_isa']=='test_integer_emulation'
            assert all(t['vector_length_bytes']==vl and t['matrix_segments_per_chain']==vl//16 for t in w['threads_detail'])
        source=Path(tmp)/'io.c'
        source.write_text('#define _GNU_SOURCE\n#include <stdio.h>\n#include <errno.h>\nint fixture_flush(FILE*);\n'
            '#define fflush fixture_flush\n#define main fixture_main\n#include "'+str(ROOT/'native/cpu_stress_helper.c')+'"\n'
            '#undef main\n#undef fflush\n'
            'int fixture_flush(FILE*f){int r=fflush(f);if(f==progress_file && progress_sequence>=3){errno=ENOSPC;return EOF;}return r;}\n'
            'int main(int argc,char**argv){return fixture_main(argc,argv); }\n')
        io=Path(tmp)/'io';subprocess.run(['gcc','-O3','-std=c11','-pthread','-DLVS_CPU_HELPER_TEST_SVE_I8MM',str(source),'-o',str(io)],check=True,capture_output=True)
        record=_run(io,tmp);assert record['observed_exit_code']==4 and record['verified_progress']['persistence_error'] and not worker_result_successful(record)
        assert record['initial_verification_completed'] and record['final_verification_completed']
        for vl in [-1,'oops',0,15,17,512,16|(1<<18)]:assert not worker_result_successful(_run(b,tmp,vl,fail=True))
        assert worker_result_successful(_run(b,tmp,16|(1<<17)))
        for flag in ['CORRUPT_PERIODIC','CORRUPT_FINAL','CORRUPT_WITNESS','CORRUPT_GUARD','CAPABILITY_LOST','MIGRATION','INTERRUPT','VL_CHANGED','CNT_MISMATCH','ALLOCATION','THREAD_START_FAILURE']+['CORRUPT_LANE='+str(i*16+15) for i in range(8)]:
            macro='LVS_CPU_HELPER_TEST_THREAD_START_FAILURE' if flag=='THREAD_START_FAILURE' else 'LVS_CPU_HELPER_TEST_SVE_I8MM_'+flag
            if flag=='THREAD_START_FAILURE' and len(os.sched_getaffinity(0))<2:continue
            b=_build(tmp,'failure','-DLVS_CPU_HELPER_TEST_SVE_I8MM','-D'+macro)
            w=_run(b,tmp,64 if 'CORRUPT_LANE' in flag else 16,fail=flag!='CORRUPT_FINAL',workers=2 if flag=='THREAD_START_FAILURE' else 1)
            if flag=='INTERRUPT':assert worker_result_successful(w) and w['threads_detail'][0]['interrupted_arithmetic_blocks']>0,w
            else:
                assert w['observed_exit_code']==4 and not worker_result_successful(w),w
                if flag=='CORRUPT_FINAL':assert w['initial_verification_completed'] and not w['final_verification_completed']
                if flag=='VL_CHANGED':assert w['threads_detail'][0]['first_error']['actual']==32
        b=_build(tmp,'mixed','-DLVS_CPU_HELPER_TEST_SVE_I8MM','-DLVS_CPU_HELPER_TEST_SVE_I8MM_MIXED_VL')
        w=_run(b,tmp,workers=2);assert worker_result_successful(w),w
        b=_build(tmp,'disabled','-DLVS_CPU_HELPER_TEST_SVE_I8MM','-DLVS_CPU_HELPER_TEST_DISABLE_SVE_I8MM');assert subprocess.run([str(b),'--mode',KERNEL,'--print-kernel-flavor'],capture_output=True).returncode==3


def run_sve_i8mm_selection_build_checks():
    from Modules.lvs_cpu_architecture import cpu_instruction_set_policy,python_cpu_fallback_policy,resolve_cpu_instruction_intent
    from Modules.lvs_cpu_targeting import common_kernel_capabilities,select_common_kernel
    from Modules.lvs_cpu_execution import cpu_candidate_kernel_flavors
    from Modules.lvs_native_helpers import resolve_native_helper_status,native_helper_binary_ready
    assert cpu_instruction_set_policy('arm64',KERNEL)['allowed'] and not python_cpu_fallback_policy('arm64',KERNEL)['allowed']
    assert not cpu_instruction_set_policy('x86_64',KERNEL)['allowed']
    for targets in [[1],[1,17],list(range(256))]:
        caps={c:['scalar','neon',KERNEL] for c in targets};common=lambda:common_kernel_capabilities(targets,caps)['common_kernel_flavors']
        assert select_common_kernel(architecture='arm64',requested_mode=KERNEL,common_flavors=common())==KERNEL
        caps[targets[-1]]=['scalar','neon','neon_i8mm','sve_fp32_fma','sve2_smlal']
        assert not select_common_kernel(architecture='arm64',requested_mode=KERNEL,common_flavors=common())
    for intent in ['baseline_vector','high_throughput_vector','highest_verified_vector']:assert resolve_cpu_instruction_intent('arm64',intent,['scalar','neon','neon_fp32_fma','sve_fp32_fma',KERNEL])['resolved_kernel_flavor']!=KERNEL
    assert KERNEL not in cpu_candidate_kernel_flavors(helper_available=True,policy='max_power',resolved_mode='neon',supports_kernel_flavor=lambda _:True,architecture='arm64')
    regions=['DOTPROD','I8MM','FP16','FHM','BF16','SVE_I8MM']
    with TemporaryDirectory(prefix='lvs-svei8mm-build-') as tmp:
        source=Path(tmp)/'cpu_stress_helper.c';source.write_text('fixture');binary=source.with_name('cpu_stress_helper_arm64')
        for mask in range(64):
            binary.unlink(missing_ok=True);calls=[];supported={r for i,r in enumerate(regions) if mask&(1<<i)}
            def build(cmd):
                calls.append(cmd);enabled={r for r in regions if '-DLVS_CPU_HELPER_ENABLE_'+r in cmd}
                ok=enabled<=supported and '-DLVS_CPU_HELPER_ENABLE_SVE' not in cmd
                if ok:binary.write_text('fixture');binary.chmod(0o700)
                return SimpleNamespace(returncode=0 if ok else 1,stderr='' if ok else 'unsupported optional region')
            status=resolve_native_helper_status(source=source,binary=binary,compiler='gcc',reason_label='CPU',build_runner=build)
            assert status['available'] and len(calls)<=27,status
            for r in regions:assert status[r.lower()+'_build']['status']==('compiled' if r in supported else 'unavailable'),status
            assert not any('-march=' in a for cmd in calls for a in cmd)
        header=source.with_name('cpu_sve_i8mm_kernel.h');header.write_text('fixture');os.utime(header,(binary.stat().st_mtime+1,)*2);assert not native_helper_binary_ready(source,binary)


def run_sve_i8mm_reporting_progress_checks():
    from Modules.lvs_report_data import _reported_software_verification,_stage_shell
    from Modules.lvs_report_html import _stage_card
    from Modules.lvs_compat_export_helpers import preserve_legacy_worker_evidence_contract
    from Modules.lvs_cpu_verified_progress import analyze_verified_progress
    good=_valid(64);assert worker_result_successful(good)
    assert _reported_software_verification(good,KERNEL)['software_verification_satisfied']
    for key,value in [('actual_isa','i8mm'),('execution_implementation','aarch64_neon_i8mm_intrinsics'),('matrix_rounds_per_block',255),('witness_rounds_per_block',0),('signed_chains',0),('unsigned_chains',2),('mixed_chains',0),('matrix_layout','row_major_b'),('matrix_segment_bits',256),('observed_exit_code',-9),('threads_detail',[]),('arithmetic_verified_blocks',31),('verification_complete',False),('verified_progress',{'persistence_error':True})]:
        bad=deepcopy(good);bad[key]=value;assert not worker_result_successful(bad),(key,value)
        assert not _reported_software_verification(bad,KERNEL)['software_verification_satisfied'];assert preserve_legacy_worker_evidence_contract(bad)==bad
    for key,value in [('isa_hwcap',3),('isa_hwcap2',1<<13),('isa_hwcap2',2),('isa_hwcap2',True),('vector_length_bytes',512),('vector_length_bytes',64.0),('vector_length_bits',128),('vector_length_flags',1<<18),('vector_length_errno',1),('active_int32_lanes',4),('matrix_segments_per_chain',1),('observed_cpu',9),('affinity_applied',False),('final_verification_completed',False),('error_count',1)]:
        bad=deepcopy(good);bad['threads_detail'][0][key]=value;assert not worker_result_successful(bad),(key,value)
    with TemporaryDirectory(prefix='lvs-svei8mm-progress-') as tmp:
        for vl in [16,32,64,256]:
            w=_valid(vl);path=Path(tmp)/'p.jsonl';w['verified_progress']=dict(contract=KERNEL+'_progress_v1',path=str(path))
            rows=[]
            for i,count in enumerate([0,3,12,21,30]):
                rows.append(dict(contract=KERNEL+'_progress_v1',kernel_flavor=KERNEL,operation_family=OPERATION,sequence=i,pid=42,state=['startup','initial','ongoing','ongoing','final_complete'][i],monotonic_seconds=10.+i*2,realtime_seconds=1000.+i*2,clock_pair_uncertainty_seconds=0.,aggregate_verified_blocks=count,threads=[dict(thread_index=0,cpu_id=2,published_monotonic_seconds=10.+i*2,verified_blocks=count,error_count=0,initial_verified=i>0,periodic_verified=i>1,final_verified=i==4,affinity_applied=True,observed_cpu=2,vector_length_bytes=vl,active_int32_lanes=vl//4)]))
            def write():path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            write();window=SimpleNamespace(started_monotonic=10.,ended_monotonic=18.,trim_start_seconds=0,trim_end_seconds=0,analysis_intent='sustained',analysis_minimum_usable_seconds=8,analysis_evidence={'quality':'sufficient'})
            a=analyze_verified_progress(w,window);assert a['quality']=='sufficient',a
            assert a['derived_stress_byte_products_per_second']==30/8*8*(vl//4)*8*256
            assert 'derived_stress_lane_fma_count' not in a['threads'][0]
            w['verified_progress_analysis']=a;stage=_stage_shell(0,dict(stage_id='s',started_monotonic=10,ended_monotonic=18,cpu_kernel_flavor=KERNEL,cpu_selection_evidence={'selection_reason':'explicit SVE I8MM'},worker_results=[w]));assert KERNEL in _stage_card(stage,{})
            rows[3]['threads'][0]['vector_length_bytes']=16 if vl!=16 else 32;write();assert analyze_verified_progress(w,window)['quality']=='insufficient'


def run_sve_i8mm_frontend_checks():
    _frontend_checks(KERNEL)
