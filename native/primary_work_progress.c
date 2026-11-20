#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <pthread.h>
#include "primary_work_progress.h"
/* Supplementary completed-work evidence. Worker-private counters, bounded
 * publication; no extra workload reads/writes and no I/O in worker loops. */
#include <time.h>
#include <limits.h>

typedef struct {
    uint64_t units, processed, verified, errors;
    double monotonic;
    int final;
} lvs_work_slot;
static lvs_work_slot *lvs_work_slots, *lvs_work_copy, *lvs_work_accum;
static int lvs_work_threads, lvs_work_done, lvs_work_failed;
static unsigned long lvs_work_sequence;
static FILE *lvs_work_file;
static pthread_t lvs_work_writer;
static int lvs_work_started;
static const char *lvs_work_kind;
static pthread_mutex_t lvs_work_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t lvs_work_cond = PTHREAD_COND_INITIALIZER;
static double lvs_work_write_seconds;
static double lvs_work_clock(clockid_t id) {
    struct timespec ts;
    return clock_gettime(id,&ts)==0 ? ts.tv_sec+ts.tv_nsec/1e9 : 0;
}
void lvs_work_publish(int index,uint64_t units,uint64_t processed,uint64_t verified,uint64_t errors,int final) {
    if (!lvs_work_slots) return;
    double now=lvs_work_clock(CLOCK_MONOTONIC);
    if (!final && now-lvs_work_slots[index].monotonic<0.25) return;
    pthread_mutex_lock(&lvs_work_lock);
    lvs_work_slots[index]=(lvs_work_slot){units,processed,verified,errors,now,final};
    pthread_mutex_unlock(&lvs_work_lock);
}
static void lvs_work_snapshot(int final) {
    double before=lvs_work_clock(CLOCK_MONOTONIC);
    pthread_mutex_lock(&lvs_work_lock);
    memcpy(lvs_work_copy,lvs_work_slots,(size_t)lvs_work_threads*sizeof(*lvs_work_copy));
    pthread_mutex_unlock(&lvs_work_lock);
    double pair=lvs_work_clock(CLOCK_MONOTONIC),real=lvs_work_clock(CLOCK_REALTIME),now=lvs_work_clock(CLOCK_MONOTONIC);
    fprintf(lvs_work_file,"{\"contract\":\"lvs_primary_work_v1\",\"pid\":%ld,\"kind\":\"%s\",\"sequence\":%lu,\"final\":%s,\"monotonic_seconds\":%.9f,\"realtime_seconds\":%.9f,\"clock_pair_uncertainty_seconds\":%.9f,\"threads\":[",(long)getpid(),lvs_work_kind,lvs_work_sequence++,final?"true":"false",now,real,now-pair);
    for(int i=0;i<lvs_work_threads;i++) {
        lvs_work_slot *s=&lvs_work_copy[i];
        fprintf(lvs_work_file,"%s{\"thread_index\":%d,\"monotonic_seconds\":%.9f,\"completed_units\":%" PRIu64 ",\"processed_bytes\":%" PRIu64 ",\"verified_bytes\":%" PRIu64 ",\"error_count\":%" PRIu64 ",\"final\":%s}",i?",":"",i,s->monotonic,s->units,s->processed,s->verified,s->errors,s->final?"true":"false");
    }
    fprintf(lvs_work_file,"]}\n");
    if(fflush(lvs_work_file)||fsync(fileno(lvs_work_file))||ferror(lvs_work_file)) lvs_work_failed=1;
    lvs_work_write_seconds+=lvs_work_clock(CLOCK_MONOTONIC)-before;
}
static void *lvs_work_report(void *unused) {
    (void)unused;
    pthread_mutex_lock(&lvs_work_lock);
    while(!lvs_work_done) {
        struct timespec deadline;clock_gettime(CLOCK_MONOTONIC,&deadline);deadline.tv_sec+=2;
        int rc=0;
        while(!lvs_work_done && rc==0) rc=pthread_cond_timedwait(&lvs_work_cond,&lvs_work_lock,&deadline);
        if(lvs_work_done) break;
        pthread_mutex_unlock(&lvs_work_lock);lvs_work_snapshot(0);pthread_mutex_lock(&lvs_work_lock);
    }
    pthread_mutex_unlock(&lvs_work_lock);return NULL;
}
void lvs_work_init(const char *result,int threads,const char *kind) {
#ifdef LVS_TEST_DISABLE_WORK_PROGRESS
    (void)result;(void)threads;(void)kind;return;
#endif
    if(!result) return;
    lvs_work_kind=kind;lvs_work_threads=threads;
    lvs_work_accum=calloc((size_t)threads,sizeof(*lvs_work_accum));
    lvs_work_slots=calloc((size_t)threads,sizeof(*lvs_work_slots));lvs_work_copy=calloc((size_t)threads,sizeof(*lvs_work_copy));
    char *path=malloc(strlen(result)+sizeof(".work.jsonl"));
    if(!lvs_work_accum||!lvs_work_slots||!lvs_work_copy||!path) {lvs_work_failed=1;free(path);free(lvs_work_slots);lvs_work_slots=NULL;return;}
    sprintf(path,"%s.work.jsonl",result);lvs_work_file=fopen(path,"w");free(path);
    if(!lvs_work_file) {lvs_work_failed=1;free(lvs_work_slots);lvs_work_slots=NULL;return;}
    pthread_condattr_t attr;
    pthread_condattr_init(&attr);
    int clock_error=pthread_condattr_setclock(&attr,CLOCK_MONOTONIC);
    pthread_cond_destroy(&lvs_work_cond);
    int cond_error=pthread_cond_init(&lvs_work_cond,&attr);pthread_condattr_destroy(&attr);
    if(clock_error||cond_error) {lvs_work_failed=1;fclose(lvs_work_file);lvs_work_file=NULL;free(lvs_work_slots);lvs_work_slots=NULL;return;}
    if(pthread_create(&lvs_work_writer,NULL,lvs_work_report,NULL)) {lvs_work_failed=1;fclose(lvs_work_file);lvs_work_file=NULL;free(lvs_work_slots);lvs_work_slots=NULL;return;}
    lvs_work_started=1;
}
void lvs_work_finish(void) {
    if(!lvs_work_started) return;
    pthread_mutex_lock(&lvs_work_lock);lvs_work_done=1;pthread_cond_signal(&lvs_work_cond);pthread_mutex_unlock(&lvs_work_lock);
    pthread_join(lvs_work_writer,NULL);lvs_work_snapshot(1);
    if(fclose(lvs_work_file)) lvs_work_failed=1;
    lvs_work_file=NULL;
}
void lvs_work_dispose(void) {free(lvs_work_accum);free(lvs_work_slots);free(lvs_work_copy);lvs_work_slots=NULL;lvs_work_copy=NULL;}
void lvs_work_metadata(FILE *file) {
    if(!lvs_work_kind) return;
    fprintf(file,"  \"work_progress\":{\"contract\":\"lvs_primary_work_v1\",\"kind\":\"%s\",\"threads\":%d,\"sidecar_suffix\":\".work.jsonl\",\"persistence_error\":%s,\"snapshot_count\":%lu,\"snapshot_write_seconds\":%.9f,\"final_threads\":[",lvs_work_kind,lvs_work_threads,lvs_work_failed?"true":"false",lvs_work_sequence,lvs_work_write_seconds);
    for(int i=0;lvs_work_slots && i<lvs_work_threads;i++) {
        lvs_work_slot *s=&lvs_work_slots[i];
        fprintf(file,"%s{\"thread_index\":%d,\"monotonic_seconds\":%.9f,\"completed_units\":%" PRIu64 ",\"processed_bytes\":%" PRIu64 ",\"verified_bytes\":%" PRIu64 ",\"error_count\":%" PRIu64 ",\"final\":%s}",i?",":"",i,s->monotonic,s->units,s->processed,s->verified,s->errors,s->final?"true":"false");
    }
    fprintf(file,"]},\n");
}
void lvs_work_record_memory(int index,uint64_t actual,int compared,uint64_t errors,int final) {
    if(!lvs_work_slots) return;
    lvs_work_slot *s=&lvs_work_accum[index];
    s->units+=actual/64;s->processed+=actual*(compared ? 2U : 1U);
    if(compared) s->verified+=actual-(errors-s->errors)*sizeof(uint64_t);
    s->errors=errors;lvs_work_publish(index,s->units,s->processed,s->verified,errors,final);
}
