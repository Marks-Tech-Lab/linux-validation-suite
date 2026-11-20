/* Trusted final-exec hook. No engine, target pathname, raw payload logging or
 * host policy changes. The only target arrives after nondumpability is locked. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <linux/audit.h>
#include <linux/fs.h>
#include <sched.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <sys/ioctl.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/sysmacros.h>
#include <unistd.h>
#if defined(__x86_64__)
#define ARCH AUDIT_ARCH_X86_64
#elif defined(__aarch64__)
#define ARCH AUDIT_ARCH_AARCH64
#else
#error "Qualified hook supports native x86-64/AArch64"
#endif
#define LOAD(f) BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,f))
#define REJECT BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ERRNO|EPERM)
#define BLOCK(n) BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,n,0,1),REJECT
#define require(ok) do {if(!(ok)) {dprintf(2,"{\"postexec_failure_line\":%d}\n",__LINE__);_exit(125);}} while(0)
static void lock_state(void) {
    struct sock_filter f[]={
        LOAD(arch),BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,ARCH,1,0),BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS),
        LOAD(nr),
#if defined(__x86_64__)
        BPF_JUMP(BPF_JMP|BPF_JGE|BPF_K,0x40000000,0,1),BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS),
#endif
        BLOCK(__NR_execve),BLOCK(__NR_execveat),
        BLOCK(__NR_setuid),BLOCK(__NR_setgid),BLOCK(__NR_setreuid),BLOCK(__NR_setregid),
        BLOCK(__NR_setresuid),BLOCK(__NR_setresgid),BLOCK(__NR_setfsuid),BLOCK(__NR_setfsgid),
        BLOCK(__NR_setgroups),BLOCK(__NR_capset),BLOCK(__NR_unshare),BLOCK(__NR_setns),
        BLOCK(__NR_ptrace),BLOCK(__NR_process_vm_readv),BLOCK(__NR_process_vm_writev),
#ifdef __NR_clone3
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,__NR_clone3,0,1),BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ERRNO|ENOSYS),
#endif
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,__NR_clone,0,4),LOAD(args[0]),
        BPF_JUMP(BPF_JMP|BPF_JSET|BPF_K,CLONE_NEWUSER|CLONE_NEWNS|CLONE_NEWPID|CLONE_NEWNET|CLONE_NEWUTS|CLONE_NEWIPC|CLONE_NEWCGROUP,0,1),REJECT,
        BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW),
        LOAD(nr),BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,__NR_prctl,0,6),LOAD(args[0]),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,PR_SET_DUMPABLE,3,0),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,PR_SET_PDEATHSIG,2,0),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,PR_SET_MM,1,0),
        BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW),REJECT,
        BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW)
    };
    struct sock_fprog p={.len=sizeof(f)/sizeof(f[0]),.filter=f};
    require(prctl(PR_GET_NO_NEW_PRIVS,0L,0L,0L,0L)==1);
    require(syscall(SYS_seccomp,SECCOMP_SET_MODE_FILTER,SECCOMP_FILTER_FLAG_TSYNC,&p)==0);
}
__attribute__((constructor)) static void confidential_init(void) {
    /* Before receiving the target there are no sector bytes in userspace.
     * Preload failure/omission leaves stdin at /dev/null, not the target. */
    require(prctl(PR_SET_DUMPABLE,0L,0L,0L,0L)==0);
    const char *text=getenv("LVS_THERMAL_HANDOFF");
    require(text!=NULL);
    unsigned int channel,library,parent,maj,min;uint64_t size;char extra;
    require(sscanf(text,"%u:%u:%u:%u:%u:%"SCNu64"%c",&channel,&library,&parent,&maj,&min,&size,&extra)==6);
    require(channel>=3 && library>=3 && channel!=library && parent>1 && getppid()==(pid_t)parent);
    require(getuid()!=0 && getuid()==geteuid() && getgid()==getegid());
    require(prctl(PR_SET_PDEATHSIG,SIGKILL)==0 && getppid()==(pid_t)parent);
    lock_state();
    require(prctl(PR_GET_DUMPABLE)==0);
    errno=0;require(prctl(PR_SET_DUMPABLE,1L,0L,0L,0L)==-1 && errno==EPERM);
    errno=0;require(syscall(SYS_execve,"/nonexistent",NULL,NULL)==-1 && errno==EPERM);
    errno=0;require(syscall(SYS_setresuid,-1,-1,-1)==-1 && errno==EPERM);
    require(prctl(PR_GET_DUMPABLE)==0);
    union {struct cmsghdr align;char bytes[CMSG_SPACE(sizeof(int))];} control;
    char byte=0;struct iovec v={&byte,1};
    struct msghdr m={.msg_iov=&v,.msg_iovlen=1,.msg_control=control.bytes,.msg_controllen=sizeof(control.bytes)};
    require(recvmsg((int)channel,&m,MSG_DONTWAIT|MSG_CMSG_CLOEXEC)==1 && byte=='T' && !(m.msg_flags&(MSG_CTRUNC|MSG_TRUNC)));
    struct cmsghdr *c=CMSG_FIRSTHDR(&m);
    require(c && c->cmsg_level==SOL_SOCKET && c->cmsg_type==SCM_RIGHTS && c->cmsg_len==CMSG_LEN(sizeof(int)) && !CMSG_NXTHDR(&m,c));
    int target;memcpy(&target,CMSG_DATA(c),sizeof(target));
    struct stat s;require(fstat(target,&s)==0 && (S_ISBLK(s.st_mode)||S_ISREG(s.st_mode)) && major(s.st_rdev)==maj && minor(s.st_rdev)==min);
    int flags=fcntl(target,F_GETFL);require(flags>=0 && (flags&O_ACCMODE)==O_RDONLY && (flags&O_DIRECT));
    uint64_t actual=s.st_size;
    if(S_ISBLK(s.st_mode)) require(ioctl(target,BLKGETSIZE64,&actual)==0);
    require(actual==size && dup2(target,0)==0);close(target);close((int)channel);close((int)library);
    unsetenv("LVS_THERMAL_HANDOFF");unsetenv("LD_PRELOAD");
    require(prctl(PR_GET_DUMPABLE)==0 && getppid()==(pid_t)parent);
    dprintf(2,"{\"contract_id\":\"lvs.storage_thermal.postexec\",\"version\":1,\"pid\":%ld,\"uid\":%lu,\"gid\":%lu,\"dumpable\":0,\"state_locked\":true,\"thread_sync\":true,\"target_deferred\":true,\"parent\":%u,\"major\":%u,\"minor\":%u,\"size\":%"PRIu64"}\n",(long)getpid(),(unsigned long)getuid(),(unsigned long)getgid(),parent,maj,min,size);
}
