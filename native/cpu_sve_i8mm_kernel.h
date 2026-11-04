/* Explicit-only SVE I8MM. Each scalable Z register contains independent
 * 128-bit A[2][8] row-major x B[8][2] column-packed matrix segments. */
#define SVE_I8MM_CHAINS 8
#define SVE_I8MM_ROUNDS 256
#define SVE_I8MM_CASES 4
#define SVE_I8MM_MAX_BYTES 256
#define SVE_I8MM_MAX_LANES 64

static int sve_i8mm_capability(uint64_t h,uint64_t h2) {
    return (h&((1ULL<<22)|3))==((1ULL<<22)|3) && (h2&(1ULL<<9))!=0;
}
static int cpu_supports_sve_i8mm(void) {
#if defined(LVS_CPU_HELPER_TEST_SVE_I8MM)
# if defined(LVS_CPU_HELPER_TEST_DISABLE_SVE_I8MM)
    return 0;
# else
    return 1;
# endif
#elif defined(LVS_CPU_HELPER_ENABLE_SVE_I8MM) && defined(__aarch64__) && defined(__linux__)
    return sve_i8mm_capability(getauxval(AT_HWCAP),getauxval(AT_HWCAP2));
#else
    return 0;
#endif
}
static int sve_i8mm_valid_state(int state) {
    if (state<0) return 0;
    int bytes=state&0xffff,flags=state&~0xffff;
    return bytes>=16 && bytes<=SVE_I8MM_MAX_BYTES && bytes%16==0
        && (flags&~(1<<17))==0; /* PR_SVE_VL_INHERIT; never change VL. */
}
static int sve_i8mm_read_state(worker_stats_t *stats) {
#if defined(LVS_CPU_HELPER_TEST_SVE_I8MM)
    const char *raw=getenv("LVS_TEST_SVE_I8MM_VL_BYTES"); char *end=NULL;
    long value=raw ? strtol(raw,&end,10):16;
    if ((raw && (!*raw || *end)) || value<0 || value>INT32_MAX) { stats->sve_vl_errno=EINVAL; return -1; }
# if defined(LVS_CPU_HELPER_TEST_SVE_I8MM_MIXED_VL)
    value=(stats->progress_index&1) ? 48:16;
# endif
# if defined(LVS_CPU_HELPER_TEST_SVE_I8MM_VL_CHANGED)
    if (stats->arithmetic_verified_blocks>=2) value=32;
# endif
    stats->sve_vl_errno=0; return (int)value;
#elif defined(__aarch64__) && defined(__linux__)
    errno=0; int state=prctl(PR_SVE_GET_VL,0UL,0UL,0UL,0UL);
    stats->sve_vl_errno=state<0 ? errno:0; return state;
#else
    stats->sve_vl_errno=ENOTSUP; return -1;
#endif
}

/* All buffers have architectural maximum capacity, including inactive padding.
 * An unexpected VL increase cannot write outside allocated storage before the
 * subsequent state check rejects it. Only the recorded active extent earns credit. */
typedef struct {
    uint8_t a[8*SVE_I8MM_MAX_BYTES],b[8*SVE_I8MM_MAX_BYTES];
    uint32_t initial[8*SVE_I8MM_MAX_LANES],expected[8*SVE_I8MM_MAX_LANES],witness[8*SVE_I8MM_MAX_LANES];
} sve_i8mm_case_t;
static uint32_t sve_i8mm_reference(uint32_t initial,const uint8_t *a,const uint8_t *b,int row,int col,int kind,int rounds) {
    int64_t product_sum=0;
    for (int k=0;k<8;++k)
        product_sum+=(int64_t)i8mm_value(a[row*8+k],kind!=0)*i8mm_value(b[col*8+k],kind==1);
    /* 8*255*255*256 + UINT32_MAX < 2^63. Conversion defines modulo 2^32. */
    return (uint32_t)((int64_t)initial+product_sum*rounds);
}
static void prepare_sve_i8mm_case(sve_i8mm_case_t *c,uint32_t seed,int lanes) {
    static const uint8_t values[]={128,127,255,0,1,63,193};
    int bytes=lanes*4;
    for (int n=0;n<8*bytes;++n) {
        c->a[n]=values[((uint32_t)n+seed)%7];
        c->b[n]=values[((uint32_t)n*3+seed+1)%7];
    }
    for (int chain=0;chain<8;++chain) for (int lane=0;lane<lanes;++lane) {
        int n=chain*lanes+lane,segment=lane/4,kind=chain<3 ? 0:chain<6 ? 1:2;
        c->initial[n]=n%2 ? 0x80000000U:UINT32_MAX-seed;
        const uint8_t *a=c->a+chain*bytes+16*segment,*b=c->b+chain*bytes+16*segment;
        c->expected[n]=sve_i8mm_reference(c->initial[n],a,b,(lane%4)/2,lane%2,kind,SVE_I8MM_ROUNDS);
        c->witness[n]=sve_i8mm_reference(c->initial[n],a,b,(lane%4)/2,lane%2,kind,1);
    }
}

#if defined(LVS_CPU_HELPER_ENABLE_SVE_I8MM) && defined(__aarch64__) && defined(__linux__)
#if defined(__clang__)
__attribute__((noinline,target("sve,i8mm")))
#else
#pragma GCC push_options
#pragma GCC target("+sve+i8mm")
__attribute__((noinline,noclone))
#endif
static int execute_sve_i8mm_block(const sve_i8mm_case_t *c,uint32_t *out,int lanes,int rounds,int final) {
    if (lanes<4 || lanes>SVE_I8MM_MAX_LANES || lanes%4 || (rounds!=1 && rounds!=SVE_I8MM_ROUNDS)) return -1;
    unsigned count,alive; uint64_t actual; int result;
    /* Explicit scalable assembly keeps eight distinct accumulators and bounded
     * cancellation independent of compiler peeling. All loads/stores use full
     * predicates and MUL VL addressing, never fixed-width Q/V substitutes. */
    __asm__ volatile(
        ".arch_extension sve\n.arch_extension i8mm\n"
        "mov %w[result], #-1\n"
        "cntw %[actual]\n"
        "cmp %[actual], %[lanes]\n"
        "b.ne 9f\n"
        "ptrue p0.b\nptrue p1.s\n"
        "ld1b {z8.b}, p0/z, [%[a], #0, mul vl]\n"
        "ld1b {z9.b}, p0/z, [%[a], #1, mul vl]\n"
        "ld1b {z10.b}, p0/z, [%[a], #2, mul vl]\n"
        "ld1b {z11.b}, p0/z, [%[a], #3, mul vl]\n"
        "ld1b {z12.b}, p0/z, [%[a], #4, mul vl]\n"
        "ld1b {z13.b}, p0/z, [%[a], #5, mul vl]\n"
        "ld1b {z14.b}, p0/z, [%[a], #6, mul vl]\n"
        "ld1b {z15.b}, p0/z, [%[a], #7, mul vl]\n"
        "ld1b {z16.b}, p0/z, [%[b], #0, mul vl]\n"
        "ld1b {z17.b}, p0/z, [%[b], #1, mul vl]\n"
        "ld1b {z18.b}, p0/z, [%[b], #2, mul vl]\n"
        "ld1b {z19.b}, p0/z, [%[b], #3, mul vl]\n"
        "ld1b {z20.b}, p0/z, [%[b], #4, mul vl]\n"
        "ld1b {z21.b}, p0/z, [%[b], #5, mul vl]\n"
        "ld1b {z22.b}, p0/z, [%[b], #6, mul vl]\n"
        "ld1b {z23.b}, p0/z, [%[b], #7, mul vl]\n"
        "ld1w {z0.s}, p1/z, [%[initial], #0, mul vl]\n"
        "ld1w {z1.s}, p1/z, [%[initial], #1, mul vl]\n"
        "ld1w {z2.s}, p1/z, [%[initial], #2, mul vl]\n"
        "ld1w {z3.s}, p1/z, [%[initial], #3, mul vl]\n"
        "ld1w {z4.s}, p1/z, [%[initial], #4, mul vl]\n"
        "ld1w {z5.s}, p1/z, [%[initial], #5, mul vl]\n"
        "ld1w {z6.s}, p1/z, [%[initial], #6, mul vl]\n"
        "ld1w {z7.s}, p1/z, [%[initial], #7, mul vl]\n"
        "mov %w[count], wzr\n"
        "1: tst %w[count], #31\n"
        "b.ne 2f\n"
        "cbnz %w[final], 2f\n"
        "ldr %w[alive], [%[running]]\n"
        "cbz %w[alive], 3f\n"
        "2:\n"
        "smmla z0.s, z8.b, z16.b\n"
        "smmla z1.s, z9.b, z17.b\n"
        "smmla z2.s, z10.b, z18.b\n"
        "ummla z3.s, z11.b, z19.b\n"
        "ummla z4.s, z12.b, z20.b\n"
        "ummla z5.s, z13.b, z21.b\n"
        "usmmla z6.s, z14.b, z22.b\n"
        "usmmla z7.s, z15.b, z23.b\n"
        "add %w[count], %w[count], #1\n"
        "cmp %w[count], %w[rounds]\n"
        "b.ne 1b\n"
        "3: cmp %w[count], %w[rounds]\n"
        "b.ne 8f\n"
        "cntw %[actual]\n"
        "cmp %[actual], %[lanes]\n"
        "b.ne 9f\n"
        "st1w {z0.s}, p1, [%[output], #0, mul vl]\n"
        "st1w {z1.s}, p1, [%[output], #1, mul vl]\n"
        "st1w {z2.s}, p1, [%[output], #2, mul vl]\n"
        "st1w {z3.s}, p1, [%[output], #3, mul vl]\n"
        "st1w {z4.s}, p1, [%[output], #4, mul vl]\n"
        "st1w {z5.s}, p1, [%[output], #5, mul vl]\n"
        "st1w {z6.s}, p1, [%[output], #6, mul vl]\n"
        "st1w {z7.s}, p1, [%[output], #7, mul vl]\n"
        "mov %w[result], #1\nb 9f\n"
        "8: mov %w[result], #0\n9:\n"
        : [count] "=&r"(count),[alive] "=&r"(alive),[actual] "=&r"(actual),[result] "=&r"(result)
        : [a] "r"(c->a),[b] "r"(c->b),[initial] "r"(c->initial),[output] "r"(out),
          [lanes] "r"((uint64_t)lanes),[rounds] "r"(rounds),[final] "r"(final),[running] "r"(&keep_running)
        : "cc","memory","p0","p1","z0","z1","z2","z3","z4","z5","z6","z7","z8","z9","z10","z11","z12","z13","z14","z15","z16","z17","z18","z19","z20","z21","z22","z23");
    return result;
}
#if !defined(__clang__)
#pragma GCC pop_options
#endif
#elif defined(LVS_CPU_HELPER_TEST_SVE_I8MM)
static int execute_sve_i8mm_block(const sve_i8mm_case_t *c,uint32_t *out,int lanes,int rounds,int final) {
    if (lanes<4 || lanes>SVE_I8MM_MAX_LANES || lanes%4 || (rounds!=1 && rounds!=SVE_I8MM_ROUNDS)) return -1;
# if defined(LVS_CPU_HELPER_TEST_SVE_I8MM_CNT_MISMATCH)
    return -1;
# endif
    memcpy(out,c->initial,(size_t)8*lanes*sizeof(*out));
    for (int r=0;r<rounds;++r) {
        if (!final && !keep_running) return 0;
        for (int chain=0;chain<8;++chain) for (int segment=0;segment<lanes/4;++segment)
            for (int k=0;k<8;++k) {
                int base=chain*lanes*4+segment*16,dest=chain*lanes+segment*4;
                int a0=i8mm_value(c->a[base+k],chain>=3),a1=i8mm_value(c->a[base+8+k],chain>=3);
                int b0=i8mm_value(c->b[base+k],chain>=3 && chain<6),b1=i8mm_value(c->b[base+8+k],chain>=3 && chain<6);
                out[dest]+=(uint32_t)(a0*b0);out[dest+1]+=(uint32_t)(a0*b1);
                out[dest+2]+=(uint32_t)(a1*b0);out[dest+3]+=(uint32_t)(a1*b1);
            }
    }
    return 1;
}
#endif

static void run_sve_i8mm_loop(uint32_t seed,worker_stats_t *stats) {
#if (defined(LVS_CPU_HELPER_ENABLE_SVE_I8MM) && defined(__aarch64__) && defined(__linux__)) || defined(LVS_CPU_HELPER_TEST_SVE_I8MM)
#if defined(LVS_CPU_HELPER_TEST_SVE_I8MM)
    stats->sve_i8mm_hwcap=(1ULL<<22)|3;stats->sve_i8mm_hwcap2=1ULL<<9;
#else
    stats->sve_i8mm_hwcap=getauxval(AT_HWCAP);stats->sve_i8mm_hwcap2=getauxval(AT_HWCAP2);
#endif
#if defined(LVS_CPU_HELPER_TEST_SVE_I8MM_CAPABILITY_LOST)
    stats->sve_i8mm_hwcap2=0;
#endif
    if (!sve_i8mm_capability(stats->sve_i8mm_hwcap,stats->sve_i8mm_hwcap2)) {
        record_worker_error(stats,"sve_i8mm_capability_lost",0,1ULL<<9,stats->sve_i8mm_hwcap2);keep_running=0;return;
    }
    int state=sve_i8mm_read_state(stats);
    if (!sve_i8mm_valid_state(state)) {
        record_worker_error(stats,"sve_i8mm_vl_invalid",0,16,state<0 ? (uint64_t)stats->sve_vl_errno:(uint64_t)state);keep_running=0;return;
    }
    stats->sve_vl_bytes=state&0xffff;stats->sve_vl_flags=state&~0xffff;
    int lanes=stats->sve_int32_lanes=stats->sve_vl_bytes/4,words=8*lanes;
    sve_i8mm_case_t *cases=calloc(SVE_I8MM_CASES,sizeof(*cases));
    uint32_t *output=calloc(8*SVE_I8MM_MAX_LANES+2,sizeof(*output));
#if defined(LVS_CPU_HELPER_TEST_SVE_I8MM_ALLOCATION)
    free(cases);cases=NULL;
#endif
    if (!cases || !output) {record_worker_error(stats,"sve_i8mm_allocation",0,1,0);keep_running=0;goto cleanup;}
    for (int i=0;i<SVE_I8MM_CASES;++i) prepare_sve_i8mm_case(&cases[i],seed+(uint32_t)i,lanes);
    for (;;) {
        int final=!keep_running;
        if (stats->error_count || (final && !stats->initial_verification_completed)) break;
        if (!half_check_affinity(stats)) break;
#if defined(LVS_CPU_HELPER_TEST_SVE_I8MM_MIGRATION)
        ++stats->observed_cpu;record_worker_error(stats,"affinity_lost",0,stats->affinity_target_cpu,stats->observed_cpu);keep_running=0;break;
#endif
        int observed_state=sve_i8mm_read_state(stats);
        if (observed_state!=state) {record_worker_error(stats,"sve_i8mm_vl_changed",0,state,(uint64_t)(int64_t)observed_state);keep_running=0;break;}
        const sve_i8mm_case_t *c=&cases[(stats->arithmetic_verified_blocks+seed)%SVE_I8MM_CASES];int complete=1;
        for (int witness=0;witness<2 && complete>0;++witness) {
            output[0]=0x98765432U;output[words+1]=output[8*SVE_I8MM_MAX_LANES+1]=0x12345678U;
            complete=execute_sve_i8mm_block(c,output+1,lanes,witness ? 1:SVE_I8MM_ROUNDS,final);
#if defined(LVS_CPU_HELPER_TEST_SVE_I8MM_INTERRUPT)
            if (!final && stats->arithmetic_verified_blocks==2) {keep_running=0;complete=0;}
#endif
            if (complete<=0) break;
#if defined(LVS_CPU_HELPER_TEST_SVE_I8MM_CORRUPT_LANE)
            output[1+LVS_CPU_HELPER_TEST_SVE_I8MM_CORRUPT_LANE%words]^=1;
#endif
#if defined(LVS_CPU_HELPER_TEST_SVE_I8MM_CORRUPT_PERIODIC)
            if (!final && stats->arithmetic_verified_blocks==2) output[1]^=1;
#endif
#if defined(LVS_CPU_HELPER_TEST_SVE_I8MM_CORRUPT_FINAL)
            if (final) output[words]^=1;
#endif
#if defined(LVS_CPU_HELPER_TEST_SVE_I8MM_CORRUPT_WITNESS)
            if (witness) output[words]^=1;
#endif
#if defined(LVS_CPU_HELPER_TEST_SVE_I8MM_CORRUPT_GUARD)
            output[words+1]^=1;
#endif
            if (output[0]!=0x98765432U || output[words+1]!=0x12345678U || output[8*SVE_I8MM_MAX_LANES+1]!=0x12345678U)
                record_worker_error(stats,"sve_i8mm_store_guard",0,1,0);
            const uint32_t *expected=witness ? c->witness:c->expected;
            for (int n=0;n<words && !stats->error_count;++n) if (output[n+1]!=expected[n]) {
                stats->first_error_lane=n;record_worker_error(stats,"sve_i8mm_mismatch",stats->arithmetic_verified_blocks,expected[n],output[n+1]);
            }
        }
        if (complete<0) {record_worker_error(stats,"sve_i8mm_execution_geometry",0,lanes,0);keep_running=0;break;}
        if (!complete) {++stats->interrupted_arithmetic_blocks;continue;}
        if (stats->error_count) {keep_running=0;break;}
        if (!half_check_affinity(stats)) break;
        observed_state=sve_i8mm_read_state(stats);
        if (observed_state!=state) {record_worker_error(stats,"sve_i8mm_vl_changed",0,state,(uint64_t)(int64_t)observed_state);keep_running=0;break;}
        if (stats->arithmetic_verified_blocks==UINT64_MAX) {record_worker_error(stats,"sve_i8mm_counter_overflow",0,0,0);keep_running=0;break;}
        ++stats->arithmetic_verified_blocks;++stats->verify_passes;
        if (final) {stats->final_verification_completed=1;publish_verified_progress(stats,1);break;}
        int initial=!stats->initial_verification_completed;
        if (initial) stats->initial_verification_completed=1;else stats->periodic_verification_completed=1;
        publish_verified_progress(stats,initial);
    }
cleanup:
    free(cases);free(output);
#else
    (void)seed;record_worker_error(stats,"sve_i8mm_not_compiled",0,1,0);keep_running=0;
#endif
}

static void write_sve_i8mm_result(FILE *handle,const worker_stats_t *stats,int threads,int requested,uint64_t errors) {
    uint64_t blocks=0;int initial=threads==requested && threads>0,periodic=initial,final=initial;
    for (int i=0;i<threads;++i) {
        blocks+=stats[i].arithmetic_verified_blocks;initial&=stats[i].initial_verification_completed;
        periodic&=stats[i].periodic_verification_completed;final&=stats[i].final_verification_completed;
    }
    fprintf(handle,"  \"verification_required\":true,\"verification_version\":1,\n"
        "  \"verification_contract\":\"sve_i8mm_v1\",\n"
        "  \"verification_method\":\"wide_integer_segmented_matrix_reference_modulo_2_32\",\n"
        "  \"operation_family\":\"sve_segmented_s8_s8_u8_u8_u8_s8_matrix_2x8_8x2\",\n"
        "  \"execution_implementation\":\"%s\",\"actual_isa\":\"%s\",\n"
        "  \"isa_capability_source\":\"%s\",\"vector_length_source\":\"%s\",\n"
        "  \"arithmetic_verified_blocks\":%" PRIu64 ",\n"
        "  \"accumulator_chains\":8,\"matrix_rounds_per_block\":256,\"witness_rounds_per_block\":1,\n"
        "  \"signed_chains\":3,\"unsigned_chains\":3,\"mixed_chains\":2,\"products_per_lane\":8,\n"
        "  \"matrix_segment_bits\":128,\"matrix_layout\":\"a_row_major_b_column_major_c_row_major\",\n"
        "  \"initial_verification_completed\":%s,\"periodic_verification_completed\":%s,\n"
        "  \"final_verification_completed\":%s,\"verification_complete\":%s,\n"
        "  \"verified_progress\":{\"contract\":\"sve_i8mm_progress_v1\",\"sidecar_suffix\":\".progress.jsonl\","
        "\"snapshot_interval_seconds\":2.0,\"persistence_error\":%s,\"snapshot_count\":%lu,\"snapshot_write_seconds\":%.9f},\n",
#if defined(LVS_CPU_HELPER_TEST_SVE_I8MM)
        "test_integer_emulation","test_integer_emulation","test_override","test_override",
#else
        "aarch64_sve_i8mm_asm","svei8mm","linux_aarch64_hwcap_common_set","linux_prctl_pr_sve_get_vl_per_thread",
#endif
        blocks,initial ? "true":"false",periodic ? "true":"false",final ? "true":"false",
        initial && periodic && final && !errors ? "true":"false",progress_io_error ? "true":"false",progress_sequence,progress_write_seconds);
}
