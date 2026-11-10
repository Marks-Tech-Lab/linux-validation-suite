/* Linux fork/exec-only bootstrap. No Python runs between clone and exec.
 * Parent never waits for exec, loader, cwd, or child I/O. No target opener.
 * Caller owns pid before releasing the bootstrap gate. */
#define _GNU_SOURCE
#include <unistd.h>
#include <sys/syscall.h>
#include <sys/resource.h>
#include <sys/prctl.h>
#include <sys/wait.h>
#include <signal.h>
#include <fcntl.h>
#include <errno.h>
#include <time.h>
#include <limits.h>
#include <stdint.h>
#if !defined(__x86_64__) && !defined(__aarch64__)
#error "Owned thermal launch supports Linux x86-64/AArch64"
#endif
static void die(void) { _exit(125); }
int lvs_owned_launch(char *const argv[], char *const env[], const char *cwd,
                     const int io[3], const int keep[], int count, int gate,
                     int isolated, unsigned delay_ms, uint64_t deadline, int *owned_pid) {
    pid_t parent=getpid();
    long pid=syscall(SYS_clone,(unsigned long)SIGCHLD,0,0,0,0);
    if(pid<0)return -1;
    if(pid) {
        *owned_pid=(int)pid; /* survives a Python exception immediately on return */
        if(isolated)(void)setpgid((pid_t)pid,(pid_t)pid);
        return (int)pid;
    }
    /* Async-signal-safe C/syscalls only: inherited Python/libc locks unused. */
    struct sigaction action={0};action.sa_handler=SIG_DFL;sigemptyset(&action.sa_mask);
    sigaction(SIGTERM,&action,0);sigaction(SIGINT,&action,0);sigaction(SIGHUP,&action,0);
    sigset_t mask;sigemptyset(&mask);sigprocmask(SIG_SETMASK,&mask,0);
    if((isolated && setpgid(0,0)) || prctl(PR_SET_PDEATHSIG,SIGKILL) || getppid()!=parent)die();
    for(int n=0;n<3;n++) {
        int fd=io[n];
        if(fd==-2)fd=open("/dev/null",n?O_WRONLY:O_RDONLY);
        if(fd<0 || dup2(fd,n)<0)die();
    }
    struct rlimit limit;if(getrlimit(RLIMIT_NOFILE,&limit))die();
    /* Close, rather than merely CLOEXEC, every unapproved inherited fd before
     * the ownership gate, delay, cwd or exec can stall. */
    int done=1;unsigned first=3;
#ifdef SYS_close_range
    for(;;) {
        unsigned next=gate>=((int)first)?(unsigned)gate:UINT_MAX;
        for(int n=0;n<count;n++)if(keep[n]>=(int)first && (unsigned)keep[n]<next)next=(unsigned)keep[n];
        if(first<next && syscall(SYS_close_range,first,next==UINT_MAX?UINT_MAX:next-1,0U)) {done=0;break;}
        if(next==UINT_MAX)break;
        first=next+1;
    }
#else
    done=0;
#endif
    if(!done) {
        if(limit.rlim_cur==RLIM_INFINITY || limit.rlim_cur>10000000)die();
        for(int fd=3;(rlim_t)fd<limit.rlim_cur;fd++) {
            int retain=fd==gate;for(int n=0;n<count;n++)if(fd==keep[n])retain=1;
            if(!retain)close(fd);
        }
    }
    char permit=0;
    if(read(gate,&permit,1)!=1 || permit!='G')die();
    close(gate);
    if(delay_ms) {struct timespec pause={delay_ms/1000,(long)(delay_ms%1000)*1000000};
        while(nanosleep(&pause,&pause) && errno==EINTR){} }
    for(int n=0;n<count;n++)if(keep[n]<3 || fcntl(keep[n],F_SETFD,0))die();
    if(cwd && chdir(cwd))die();
    if(deadline) {struct timespec now;if(clock_gettime(CLOCK_MONOTONIC,&now))die();
        if((uint64_t)now.tv_sec*1000000000ULL+(uint64_t)now.tv_nsec>=deadline)die();}
    execve(argv[0],argv,env);die();return -1;
}
