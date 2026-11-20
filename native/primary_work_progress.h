/* Shared supplementary work publisher; no workload data is read here. */
#ifndef LVS_PRIMARY_WORK_PROGRESS_H
#define LVS_PRIMARY_WORK_PROGRESS_H
#include <stdint.h>
#include <stdio.h>
void lvs_work_init(const char *,int,const char *);
void lvs_work_publish(int,uint64_t,uint64_t,uint64_t,uint64_t,int);
void lvs_work_record_memory(int,uint64_t,int,uint64_t,int);
void lvs_work_finish(void);
void lvs_work_metadata(FILE *);
void lvs_work_dispose(void);
#endif
