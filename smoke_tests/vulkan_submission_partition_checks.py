"""Execute production cycle statements against a software Vulkan command model."""
import ast
from collections import defaultdict
import ctypes as C
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'native'))
import vulkan_compute_worker as w


def run_vulkan_submission_partition_checks():
    assert w.compute_submission_partitions(9,'stateful_memory') == [(i,) for i in range(9)]
    for kind in ('hash','stress_hash'):
        assert w.compute_submission_partitions(9,kind) == [tuple(range(9))]
    for invalid in (0,-1,True):
        try:w.compute_submission_partitions(invalid,'stateful_memory')
        except RuntimeError:pass
        else:raise AssertionError('invalid partition accepted')
    tree=ast.parse((ROOT/'native/vulkan_compute_worker.py').read_text())
    main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    cycle=next(n for n in ast.walk(main) if isinstance(n,ast.While) and 'final_cycle_completed' in ast.unparse(n.test))
    start=next(i for i,n in enumerate(cycle.body) if isinstance(n,ast.Assign)
               and any(isinstance(t,ast.Name) and t.id=='cycle_started' for t in n.targets))
    stop=next(i for i,n in enumerate(cycle.body) if isinstance(n,ast.AugAssign)
              and ast.unparse(n.target)=="state['cycle_count']")+1
    code=compile(ast.Module(body=cycle.body[start:stop],type_ignores=[]),'<actual-partitioned-cycle>','exec')

    class Stalls:
        def begin(self,*a):return None
        def finish(self,*a):pass
        def call(self,name,fn,*a,**kw):return fn(*a,**kw)

    class Vk:
        def __init__(self,variant,failure=None):
            self.variant,self.failure=variant,failure;self.commands=[];self.pending=[]
            self.data=[[0]*256 for _ in range(9)];self.sample=(C.c_ubyte*1024)()
            self.submissions=[];self.bound=0;self.events=[]
        def __getattr__(self,name):
            def call(*args):
                if name=='vkResetCommandBuffer':self.pending=[]
                elif name=='vkCmdBindDescriptorSets':self.bound=int(args[5][0])-1
                elif name=='vkCmdPipelineBarrier':
                    b=C.cast(args[7],C.POINTER(w.VkBufferMemoryBarrier)).contents
                    self.events.append(('barrier',int(b.buffer),b.srcAccessMask,b.dstAccessMask))
                elif name=='vkCmdDispatch':
                    self.pending.append(('dispatch',self.bound));self.events.append(('dispatch',self.bound+1))
                elif name=='vkCmdCopyBuffer':self.pending.append(('copy',int(args[1])-1))
                elif name=='vkQueueSubmit':
                    if self.failure==('submit',len(self.submissions)):return -4
                    self.submissions.append(list(self.pending))
                    for op,index in self.pending:
                        if op=='dispatch':
                            self.data[index]=[w.expected_word(i,5,v,self.variant) for i,v in enumerate(self.data[index])]
                        else:
                            values=list(self.data[index])
                            if self.failure==('corrupt',index):values[1]^=1
                            C.memmove(self.sample,struct.pack('<256I',*values),1024)
                elif name=='vkWaitForFences':
                    if self.failure==('wait',len(self.submissions)-1):return 2
                    if self.failure==('cancel',len(self.submissions)-1):raise InterruptedError('cancelled')
                elif name=='vkMapMemory':C.cast(args[-1],C.POINTER(C.c_void_p)).contents.value=C.addressof(self.sample)
                return 0
            return call

    def environment(variant='stateful_memory',failure=None,verify=0,final=False):
        vk=Vk(variant,failure);env=dict(vars(w));state=defaultdict(int)
        state.update(verification_interval_target_seconds=.75,verification_intervals_seconds=[],
                     initial_verification_completed=False,final_verification_completed=False,status='running')
        env.update(vk=vk,state=state,stalls=Stalls(),kernel_variant=variant,dispatch_diagnostic=None,
            submission_partitions=w.compute_submission_partitions(9,variant),
            active_infos=[({'buffer':i+1,'size':3*1024**3},3*1024**3,805306368,(3145728,1,1)) for i in range(9)],
            runtime_memory_stop_required=lambda:failure==('guard',len(vk.submissions)),
            prepare_token=None,cached_command_signature=None,dispatches_per_buffer=1,verify_buffer_index=verify,
            query_pool=0,queue=1,command_buffer=1,pipeline_layout=2,pipeline=3,device=4,fence=5,
            fence_array=(C.c_void_p*1)(5),command_array=(C.c_void_p*1)(1),
            descriptor_sets_by_buffer=[(C.c_void_p*1)(i+1) for i in range(9)],
            sample_words=256,staging_buffer=77,staging_memory=78,local_size_x=256,compute_rounds=5,
            first_submission_checkpoint_recorded=False,initial_command_checkpoint_recorded=False,
            record_startup_checkpoint=lambda *a,**k:None,buffer_dispatch_counts=[0]*9,
            expected_sample_dispatches=[0]*9,expected_samples=[[0]*256 for _ in range(9)],
            last_verification_monotonic=0.,verified_buffer_indexes=set(),final_cycle=final)
        return env,vk,state

    env,vk,state=environment()
    # Three cycles advance each independent buffer exactly once per cycle.
    for cycle_number in range(3):
        env['verify_buffer_index']=cycle_number
        env['final_cycle']=cycle_number==2
        exec(code,env)
        assert state['cycle_count']==cycle_number+1 and not state['incomplete_cycle']
        assert state['cycle_completed_submissions']==9
        assert env['buffer_dispatch_counts']==[cycle_number+1]*9
        expected=[]
        for index in range(256):
            value=0
            for _ in range(cycle_number+1):value=w.expected_word(index,5,value,'stateful_memory')
            expected.append(value)
        assert all(data==expected for data in vk.data)
    assert state['final_verification_completed'] and state['verification_passes']==3
    assert len(vk.submissions)==27 and all(sum(op=='dispatch' for op,_ in jobs)==1 for jobs in vk.submissions)
    # Every stateful dispatch has a write -> read/write dependency for its own buffer.
    for i,event in enumerate(vk.events):
        if event[0]=='dispatch':
            previous=vk.events[i-1]
            assert previous[:2]==('barrier',event[1])
            assert previous[2]==w.VK_ACCESS_SHADER_WRITE_BIT
            assert previous[3]==w.VK_ACCESS_SHADER_READ_BIT|w.VK_ACCESS_SHADER_WRITE_BIT
    for failure in (('submit',3),('wait',3),('guard',3),('corrupt',3),('cancel',3)):
        env,vk,state=environment(failure=failure,verify=3,final=True)
        try:exec(code,env)
        except (RuntimeError,InterruptedError):pass
        else:raise AssertionError('partial submission failure accepted')
        assert state['cycle_count']==0 and state['incomplete_cycle']
        assert not state['final_verification_completed']
        assert state['cycle_completed_submissions']==3
        assert env['buffer_dispatch_counts'][:3]==[1]*3 and env['buffer_dispatch_counts'][3:]==[0]*6
    # Stateless production batching remains one submission and nine dispatches.
    for kind in ('hash','stress_hash'):
        env,vk,state=environment(variant=kind)
        exec(code,env)
        assert len(vk.submissions)==1 and state['compute_dispatch_count']==9
        assert state['cycle_count']==1
