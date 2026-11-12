/* VM-only regular-file research wrapper. This is not a production guard mode.
 * Reuse the accepted restriction primitives without changing their source or
 * invoking the block-device entrypoint. A trusted pinned fio remains required.
 */
#define main lvs_unchanged_block_guard_entry
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wreturn-type"
#include "../native/storage_thermal_guard.c"
#pragma GCC diagnostic pop
#undef main
#include <sys/uio.h>

static void file_restrictions(void) {
    struct sock_filter filter[]={
        LOAD(nr), BLOCK(__NR_pwrite64), BLOCK(__NR_pwritev), BLOCK(__NR_pwritev2),
        BLOCK(__NR_truncate), BLOCK(__NR_ftruncate), BLOCK(__NR_unlink),
        BLOCK(__NR_unlinkat), BLOCK(__NR_rename), BLOCK(__NR_renameat),
        BLOCK(__NR_renameat2), BLOCK(__NR_fchmod), BLOCK(__NR_fchown),
        ALLOW,
    };
    struct sock_fprog program={.len=sizeof(filter)/sizeof(filter[0]),.filter=filter};
    if(prctl(PR_SET_SECCOMP,SECCOMP_MODE_FILTER,&program)) fail("file restrictions");
}

int main(int argc,char **argv) {
    need(argc==10 && !strcmp(argv[1],"--research-file"),"fixed VM file protocol required");
    int exe=(int)number(argv[2]);uint64_t dev=number(argv[3]),ino=number(argv[4]);
    uint64_t size=number(argv[5]),mode=number(argv[6]),deadline=number(argv[7]);
    pid_t owner=(pid_t)number(argv[8]);const char *session=argv[9];
    need(exe>=3 && size==65536 && mode<=4 && strlen(session)==12 &&
         strspn(session,"0123456789abcdef")==12 && owner>0,"invalid research authority");
    struct stat target,binary;
    need(fstat(0,&target)==0 && S_ISREG(target.st_mode) && (uint64_t)target.st_dev==dev &&
         (uint64_t)target.st_ino==ino && (uint64_t)target.st_size==size && target.st_nlink>0,"file identity mismatch");
    int flags=fcntl(0,F_GETFL);
    need(flags>=0 && (flags&O_ACCMODE)==O_RDONLY && (flags&O_NOATIME) && !(flags&O_DIRECT),"readonly noatime buffered descriptor required");
    need(fstat(exe,&binary)==0 && S_ISREG(binary.st_mode) && (binary.st_mode&0111) &&
         !(binary.st_mode&(S_ISUID|S_ISGID)),"ordinary fio executable required");
    char magic[4];need(pread(exe,magic,4,0)==4 && !memcmp(magic,"\177ELF",4),"fio ELF required");
    struct timespec now;need(clock_gettime(CLOCK_MONOTONIC,&now)==0,"monotonic clock");
    pid_t tracer=getppid();char procpath[64],line[256];long supervisor=-1;
    snprintf(procpath,sizeof(procpath),"/proc/%ld/status",(long)tracer);
    FILE *status=fopen(procpath,"r");need(status!=NULL,"tracer identity unavailable");
    while(fgets(line,sizeof(line),status)) if(sscanf(line,"PPid: %ld",&supervisor)==1) break;
    fclose(status);
    need((uint64_t)now.tv_sec*1000000000+(uint64_t)now.tv_nsec<deadline &&
         supervisor==owner && getpgid(0)==tracer,"research admission expired/owner chain lost");
    need(fcntl(exe,F_SETFD,FD_CLOEXEC)==0,"executable cloexec");
    close_extra(exe);drop_privileges(65534,65534);restrict_operations();file_restrictions();
    need(prctl(PR_SET_PDEATHSIG,SIGKILL)==0 && getppid()==tracer,"research tracer lost");
    fprintf(stderr,"{\"research_file\":true,\"session\":\"%s\",\"uid\":%lu,\"readonly\":true,\"noatime\":true,\"seccomp\":2,\"capabilities\":0,\"no_new_privs\":1}\n",session,(unsigned long)getuid());
    if(mode==2) {
        char buffer[4096];struct iovec vector={.iov_base=buffer,.iov_len=sizeof(buffer)};
        errno=0;ssize_t n=preadv2(0,&vector,1,0,0x40000000);
        printf("{\"unknown_flag_result\":%ld,\"errno\":%d}\n",(long)n,errno);return n<0?0:1;
    }
    if(mode==3) {
        char byte=0;errno=0;need(pwrite(0,&byte,1,0)==-1 && errno==EPERM,"pwrite denial");
        errno=0;need(ftruncate(0,0)==-1 && errno==EPERM,"truncate denial");
        errno=0;need(fsync(0)==-1 && errno==EPERM,"fsync denial");
        need(posix_fadvise(0,0,size,POSIX_FADV_DONTNEED)==EPERM,"cache discard denial");
        puts("{\"file_policy\":\"PASS\"}");return 0;
    }
    if(mode==4) {
        errno=0;int other=open("/proc/self/fd/0",O_RDONLY|O_NOATIME|O_CLOEXEC);
        need(other==-1 && errno==EPERM,"O_NOATIME permission negative missing");
        other=open("/proc/self/fd/0",O_RDONLY|O_CLOEXEC);
        need(other>=0,"ordinary read permission unexpectedly missing");close(other);
        puts("{\"noatime_permission_errno\":1,\"ordinary_open_succeeded\":true}");return 0;
    }
    char *args[]={"fio","--readonly","--name=authorized-file","--filetype=file","--filename=-",
        "--ioengine=pvsync2",mode?"--uncached=1":"--uncached=0","--direct=0","--rw=read",
        "--bs=65536","--size=65536","--iodepth=1","--numjobs=1","--thread=1","--rate_iops=7",
        "--runtime=2","--time_based=1","--allow_file_create=0","--create_on_open=0","--fallocate=none",
        "--invalidate=0","--create_fsync=0","--fsync=0","--fdatasync=0","--end_fsync=0",
        "--end_syncfs=0","--fsync_on_close=0","--output-format=json","--eta=never","--disk_util=0",NULL};
    char *environment[]={"PATH=/bin","LC_ALL=C","HOME=/","TMPDIR=/tmp",NULL};
    fexecve(exe,args,environment);fail("research fio exec");
}
