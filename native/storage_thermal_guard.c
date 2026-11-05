/* Stage 2B-1: narrow descriptor/privilege/ioctl guard, NOT an I/O engine or sandbox.
 * No device pathname is accepted. Only trusted fio ELF supplied on an open fd.
 * stdout/stderr must not be block devices. No setuid installation is supported.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <grp.h>
#include <inttypes.h>
#include <linux/audit.h>
#include <linux/capability.h>
#include <linux/filter.h>
#include <linux/fs.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/sysmacros.h>
#include <unistd.h>
#include <dirent.h>

#if __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "Thermal guard ABI proof currently requires little endian"
#endif

#if defined(__x86_64__)
#define GUARD_ARCH AUDIT_ARCH_X86_64
#elif defined(__aarch64__)
#define GUARD_ARCH AUDIT_ARCH_AARCH64
#else
#error "Optional thermal guard supports Linux x86-64 and AArch64 only"
#endif

static void fail(const char *what) { fprintf(stderr,"thermal guard: %s: %s\n",what,strerror(errno)); exit(125); }
static void need(int ok,const char *what) { if(!ok) { errno=EINVAL; fail(what); } }
static uint64_t number(const char *s) {
    need(s && *s && strspn(s,"0123456789")==strlen(s),"nonnegative decimal required");
    char *end; errno=0; unsigned long long n=strtoull(s,&end,10);
    if(errno || *end) fail("decimal overflow");
    return n;
}
static int close_extra(int keep) {
    DIR *dir=opendir("/proc/self/fd"); if(!dir) fail("enumerate inherited descriptors");
    struct dirent *entry; int count=0;
    while((entry=readdir(dir))) {
        char *end; long fd=strtol(entry->d_name,&end,10);
        if(*end==0 && fd>2 && fd!=keep && fd!=dirfd(dir)) {
            if(close((int)fd)) fail("close inherited descriptor");
            count++;
        }
    }
    closedir(dir);
    return count;
}

#define LOAD(field) BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,field))
#define ALLOW BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW)
#define DENY BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ERRNO|EPERM)
#define BLOCK(n) BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,(n),0,1), DENY

static void restrict_operations(void) {
    /* Global ioctl allowlist also covers dup'd or newly inherited aliases.
     * Deny alternate x86 ABIs and high ioctl request bits, not just usual calls.
     * Other syscalls are not generally sandboxed; trusted fio is required.
     */
    struct sock_filter filter[]={
        LOAD(arch), BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,GUARD_ARCH,1,0),
        BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS),
        LOAD(nr),
#if defined(__x86_64__)
        BPF_JUMP(BPF_JMP|BPF_JGE|BPF_K,0x40000000,0,1),
        BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS),
#endif
        BLOCK(__NR_fsync), BLOCK(__NR_fdatasync), BLOCK(__NR_sync), BLOCK(__NR_syncfs),
        BLOCK(__NR_fallocate),
#ifdef __NR_sync_file_range
        BLOCK(__NR_sync_file_range),
#endif
#ifdef __NR_io_uring_setup
        BLOCK(__NR_io_uring_setup),
        BLOCK(__NR_io_uring_enter), BLOCK(__NR_io_uring_register),
#endif
#ifdef __NR_io_setup
        BLOCK(__NR_io_setup), BLOCK(__NR_io_submit),
#endif
#ifdef __NR_fadvise64
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,__NR_fadvise64,0,4),
        LOAD(args[3]),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,POSIX_FADV_RANDOM,0,1), ALLOW, DENY,
#endif
        /* If not ioctl, return ALLOW. For ioctl inspect its request only. */
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,__NR_ioctl,1,0), ALLOW,
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,args[1])+4),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,0,1,0), DENY,
        LOAD(args[1]),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,BLKGETSIZE64,0,1), ALLOW,
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,BLKSSZGET,0,1), ALLOW,
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,BLKPBSZGET,0,1), ALLOW,
        DENY,
    };
    struct sock_fprog program={.len=sizeof(filter)/sizeof(filter[0]),.filter=filter};
    if(prctl(PR_SET_NO_NEW_PRIVS,1L,0L,0L,0L)) fail("no_new_privs");
    if(prctl(PR_SET_SECCOMP,SECCOMP_MODE_FILTER,&program,0L,0L)) fail("seccomp required");
}

static void drop_privileges(uid_t uid,gid_t gid) {
    need(uid!=0 && gid!=0,"non-root uid/gid required");
    need(getuid()==geteuid() && getgid()==getegid(),"setuid/setgid invocation forbidden");
    if(geteuid()==0) {
        if(setgroups(0,NULL) || setresgid(gid,gid,gid) || setresuid(uid,uid,uid)) fail("drop root/groups");
    } else need(getuid()==uid && getgid()==gid,"cannot change unprivileged identity");
    struct __user_cap_header_struct header={.version=_LINUX_CAPABILITY_VERSION_3,.pid=0};
    struct __user_cap_data_struct caps[2]={{0},{0}};
    if(syscall(SYS_capset,&header,caps)) fail("clear capabilities");
    if(prctl(PR_CAP_AMBIENT,PR_CAP_AMBIENT_CLEAR_ALL,0L,0L,0L) && errno!=EINVAL) fail("clear ambient capabilities");
    if(syscall(SYS_capget,&header,caps)) fail("read capabilities");
    need(!(caps[0].effective|caps[0].permitted|caps[0].inheritable|caps[1].effective|caps[1].permitted|caps[1].inheritable),"capabilities remain");
    need(getuid()==uid && geteuid()==uid && getgid()==gid && getegid()==gid,"identity mismatch");
}

static void denied_ioctl(int fd,unsigned long request,void *argument) {
    errno=0; need(ioctl(fd,request,argument)==-1 && errno==EPERM,"ioctl restriction ineffective");
}
static void policy_test(void) {
    int alias=dup(0); if(alias<0) fail("dup test");
    uint64_t range[2]={0,4096}; int value=0;
    const unsigned long requests[]={BLKFLSBUF,BLKDISCARD,BLKZEROOUT,BLKROSET,BLKRRPART,0x2285,0xC0484E41,BLKROGET};
    for(size_t i=0;i<sizeof(requests)/sizeof(requests[0]);i++) {
        denied_ioctl(0,requests[i],range); denied_ioctl(alias,requests[i],&value);
    }
    denied_ioctl(alias,((unsigned long)1<<32)|BLKGETSIZE64,&value);
    struct stat info; if(fstat(alias,&info)) fail("test descriptor");
    uint64_t bytes=0; errno=0; int rc=ioctl(alias,BLKGETSIZE64,&bytes);
    need(S_ISBLK(info.st_mode)?rc==0:(rc==-1 && errno==ENOTTY),"read ioctl allowlist ineffective");
    errno=0; need(fsync(alias)==-1 && errno==EPERM,"flush restriction ineffective");
    errno=0; need(fdatasync(alias)==-1 && errno==EPERM,"fdatasync restriction ineffective");
    errno=0; need(syncfs(alias)==-1 && errno==EPERM,"syncfs restriction ineffective");
    need(posix_fadvise(alias,0,4096,POSIX_FADV_DONTNEED)==EPERM,"cache discard restriction ineffective");
    need(posix_fadvise(alias,0,4096,POSIX_FADV_RANDOM)==0,"random hint restriction too broad");
    errno=0; need(pwrite(alias,range,sizeof(range),0)==-1 && errno==EBADF,"readonly write restriction ineffective");
#ifdef __NR_io_uring_setup
    errno=0; need(syscall(__NR_io_uring_setup,0,NULL)==-1 && errno==EPERM,"io_uring restriction ineffective");
#endif
#ifdef __NR_io_setup
    errno=0; need(syscall(__NR_io_setup,0,NULL)==-1 && errno==EPERM,"AIO restriction ineffective");
#endif
    close(alias);
    puts("{\"policy_test\":\"PASS\",\"ioctl_denials\":17,\"alias_tested\":true}");
}

int main(int argc,char **argv) {
    if(argc==2 && !strcmp(argv[1],"--version")) { puts("lvs-storage-thermal-guard-v1"); return 0; }
    int test=argc>1 && !strcmp(argv[1],"--policy-test");
    need((test && argc==10) || (argc==11 && !strcmp(argv[1],"--fio-fd")),"invalid fixed guard protocol");
    int start=test?2:3;
    uint64_t values[8]; for(int i=0;i<8;i++) values[i]=number(argv[start+i]);
    need(values[0]<UINT32_MAX && values[1]<UINT32_MAX && values[2]<=UINT32_MAX && values[3]<=UINT32_MAX,"identity overflow");
    uid_t uid=values[0]; gid_t gid=values[1]; uint64_t size=values[4], bs=values[5],rate=values[6],seconds=values[7];
    need(bs>=4096 && bs<=1048576 && !(bs&(bs-1)) && size>=bs && size<=INT64_MAX,"invalid geometry");
    need(rate>=1 && rate<=1000000 && seconds>=1 && seconds<=86400,"invalid finite pilot limits");
    struct stat info;
    if(fstat(0,&info)) fail("stdin identity");
    int flags=fcntl(0,F_GETFL); if(flags<0) fail("stdin flags");
    need((flags&O_ACCMODE)==O_RDONLY && (flags&O_DIRECT),"stdin must be readonly and direct");
    need((S_ISBLK(info.st_mode) || (test && S_ISREG(info.st_mode))) && major(info.st_rdev)==values[2] && minor(info.st_rdev)==values[3],"descriptor identity mismatch");
    uint64_t actual=info.st_size; int sector=512;
    if(S_ISBLK(info.st_mode)) {
        if(ioctl(0,BLKGETSIZE64,&actual) || ioctl(0,BLKSSZGET,&sector)) fail("block geometry");
    }
    need(actual==size && sector>0 && bs%(uint64_t)sector==0,"descriptor geometry changed");
    for(int fd=1;fd<=2;fd++) { if(fstat(fd,&info)) fail("output fd"); need(!S_ISBLK(info.st_mode),"block output forbidden"); }
    int executable=-1;
    if(!test) {
        uint64_t n=number(argv[2]); need(n>=3 && n<=INT32_MAX,"invalid executable fd");
        executable=(int)n;
        if(fstat(executable,&info)) fail("executable fd");
        need(S_ISREG(info.st_mode) && (info.st_mode&0111) && !(info.st_mode&(S_ISUID|S_ISGID)),"trusted ordinary ELF required");
        char magic[4]; need(pread(executable,magic,4,0)==4 && !memcmp(magic,"\177ELF",4),"fio must be an ELF executable");
        if(fcntl(executable,F_SETFD,FD_CLOEXEC)) fail("executable cloexec");
    }
    int closed=close_extra(executable);
    drop_privileges(uid,gid);
    restrict_operations();
    fprintf(stderr,"{\"contract_id\":\"lvs.storage_thermal.guard\",\"contract_version\":1,\"pid\":%ld,\"uid\":%lu,\"gid\":%lu,\"supplementary_groups\":%d,\"extra_fds_closed\":%d,\"no_new_privs\":1,\"seccomp\":2,\"capabilities\":0,\"readonly_direct\":true}\n",(long)getpid(),(unsigned long)getuid(),(unsigned long)getgid(),getgroups(0,NULL),closed);
    if(test) { policy_test(); return 0; }
    char block_arg[64],rate_arg[64],time_arg[64];
    snprintf(block_arg,sizeof(block_arg),"--bs=%"PRIu64,bs);
    snprintf(rate_arg,sizeof(rate_arg),"--rate_iops=%"PRIu64,rate);
    snprintf(time_arg,sizeof(time_arg),"--runtime=%"PRIu64,seconds);
    char *args[]={"fio","--readonly","--name=lvs-storage-thermal","--filetype=block","--filename=-",
        "--ioengine=psync","--rw=randread","--direct=1","--iodepth=1","--numjobs=1","--thread=1",
        block_arg,rate_arg,time_arg,"--time_based=1","--allow_file_create=0","--create_on_open=0",
        "--fallocate=none","--invalidate=0","--create_fsync=0","--fsync=0","--fdatasync=0",
        "--end_fsync=0","--end_syncfs=0","--fsync_on_close=0","--norandommap=1","--randrepeat=1",
        "--randseed=719","--output-format=json","--eta=never","--disk_util=0",NULL};
    char *environment[]={"PATH=/usr/bin:/bin","LC_ALL=C","HOME=/","TMPDIR=/tmp",NULL};
    fexecve(executable,args,environment);
    fail("fio exec");
}
