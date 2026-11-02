/* Explicit-only 128-bit NEON signed/unsigned byte dot products.
 * Optional target region; baseline compilation has no global DotProd flag. */
#define DOTPROD_CHAINS 8
#define DOTPROD_LANES 4
#define DOTPROD_ROUNDS 256
#define DOTPROD_CASES 4

static int dotprod_capability(uint64_t hwcap) {
    return (hwcap & ((1ULL << 20) | 3)) == ((1ULL << 20) | 3);
}
static int cpu_supports_neon_dotprod(void) {
#if defined(LVS_CPU_HELPER_TEST_DOTPROD)
# if defined(LVS_CPU_HELPER_TEST_DISABLE_DOTPROD)
    return 0;
# else
    return 1;
# endif
#elif defined(LVS_CPU_HELPER_ENABLE_DOTPROD) && defined(__aarch64__) && defined(__linux__)
    return dotprod_capability(getauxval(AT_HWCAP));
#else
    return 0;
#endif
}

typedef struct {
    int8_t sa[64], sb[64];
    uint8_t ua[64], ub[64];
    uint32_t initial[32], expected[32];
} dotprod_case_t;

static uint32_t dotprod_reference(uint32_t initial, const int8_t *sa, const int8_t *sb,
                                  const uint8_t *ua, const uint8_t *ub, int is_unsigned) {
    int64_t dot=0;
    for (int j=0;j<4;++j)
        dot += is_unsigned ? (int64_t)ua[j]*ub[j] : (int64_t)sa[j]*sb[j];
    /* All bounded products, repeats and any initial uint32 fit int64. */
    return (uint32_t)((int64_t)initial + dot*DOTPROD_ROUNDS);
}
static void prepare_dotprod_case(dotprod_case_t *input, uint32_t seed) {
    static const int8_t s[]={-128,127,-1,0,1,-63,97};
    static const uint8_t u[]={0,255,1,128,127,254,17};
    for (int k=0;k<64;++k) {
        input->sa[k]=s[((uint32_t)k+seed)%7];
        input->sb[k]=s[((uint32_t)k*3+seed+1)%7];
        input->ua[k]=u[((uint32_t)k+seed)%7];
        input->ub[k]=u[((uint32_t)k*5+seed+2)%7];
    }
    for (int n=0;n<32;++n) {
        input->initial[n]=n%2 ? 0x80000000U : UINT32_MAX-seed;
        int offset=(n%16)*4;
        input->expected[n]=dotprod_reference(input->initial[n],input->sa+offset,input->sb+offset,
                                            input->ua+offset,input->ub+offset,n>=16);
    }
}

#if defined(LVS_CPU_HELPER_ENABLE_DOTPROD) && defined(__aarch64__) && defined(__linux__)
#if !defined(__clang__)
#pragma GCC push_options
#pragma GCC target("+dotprod")
#endif
#if defined(__clang__)
__attribute__((noinline,target("dotprod")))
#else
__attribute__((noinline))
#endif
static int execute_neon_dotprod_block(const dotprod_case_t *input,uint32_t *output,int final) {
#define DOT_LOAD(N) \
    int8x16_t a##N=vld1q_s8(input->sa+16*N), b##N=vld1q_s8(input->sb+16*N); \
    uint8x16_t c##N=vld1q_u8(input->ua+16*N), d##N=vld1q_u8(input->ub+16*N); \
    int32x4_t s##N=vreinterpretq_s32_u32(vld1q_u32(input->initial+4*N)); \
    uint32x4_t u##N=vld1q_u32(input->initial+16+4*N)
    DOT_LOAD(0); DOT_LOAD(1); DOT_LOAD(2); DOT_LOAD(3);
#undef DOT_LOAD
    for (int r=0;r<DOTPROD_ROUNDS;++r) {
        if ((r&31)==0 && !final && !keep_running) return 0;
        s0=vdotq_s32(s0,a0,b0); s1=vdotq_s32(s1,a1,b1);
        s2=vdotq_s32(s2,a2,b2); s3=vdotq_s32(s3,a3,b3);
        u0=vdotq_u32(u0,c0,d0); u1=vdotq_u32(u1,c1,d1);
        u2=vdotq_u32(u2,c2,d2); u3=vdotq_u32(u3,c3,d3);
        __asm__ volatile("" : "+w"(s0),"+w"(s1),"+w"(s2),"+w"(s3),
                             "+w"(u0),"+w"(u1),"+w"(u2),"+w"(u3));
    }
#define DOT_STORE(N) vst1q_u32(output+4*N,vreinterpretq_u32_s32(s##N)); vst1q_u32(output+16+4*N,u##N)
    DOT_STORE(0); DOT_STORE(1); DOT_STORE(2); DOT_STORE(3);
#undef DOT_STORE
    return 1;
}
#if !defined(__clang__)
#pragma GCC pop_options
#endif
#elif defined(LVS_CPU_HELPER_TEST_DOTPROD)
/* Test-only stepwise emulation, never physical ISA execution evidence. */
static int execute_neon_dotprod_block(const dotprod_case_t *input,uint32_t *output,int final) {
    memcpy(output,input->initial,sizeof(input->initial));
    for (int r=0;r<DOTPROD_ROUNDS;++r) {
        if (!final && !keep_running) return 0;
        for (int n=0;n<32;++n)
            for (int j=0;j<4;++j) {
                int k=(n%16)*4+j;
                output[n]+=(uint32_t)(n<16 ? (int32_t)input->sa[k]*input->sb[k] : (int32_t)input->ua[k]*input->ub[k]);
            }
    }
    return 1;
}
#endif

static void run_neon_dotprod_loop(uint32_t seed, worker_stats_t *stats) {
#if (defined(LVS_CPU_HELPER_ENABLE_DOTPROD) && defined(__aarch64__) && defined(__linux__)) || defined(LVS_CPU_HELPER_TEST_DOTPROD)
#if defined(LVS_CPU_HELPER_TEST_DOTPROD)
    stats->dotprod_hwcap=(1ULL<<20)|3;
#else
    stats->dotprod_hwcap=getauxval(AT_HWCAP);
#endif
#if defined(LVS_CPU_HELPER_TEST_DOTPROD_CAPABILITY_LOST)
    stats->dotprod_hwcap=3;
#endif
    if (!dotprod_capability(stats->dotprod_hwcap)) {
        record_worker_error(stats,"dotprod_capability_lost",0,(1ULL<<20)|3,stats->dotprod_hwcap); keep_running=0; return;
    }
    dotprod_case_t cases[DOTPROD_CASES];
    uint32_t output[DOTPROD_CHAINS*DOTPROD_LANES+2];
    for (int k=0;k<DOTPROD_CASES;++k) prepare_dotprod_case(&cases[k],seed+(uint32_t)k);
    for (;;) {
        int final = !keep_running;
        if (stats->error_count || (final && !stats->initial_verification_completed)) break;
        stats->observed_cpu = sched_getcpu();
#if defined(LVS_CPU_HELPER_TEST_DOTPROD_MIGRATION)
        ++stats->observed_cpu;
#endif
        if (stats->observed_cpu != stats->affinity_target_cpu) {
            record_worker_error(stats,"affinity_lost",stats->arithmetic_verified_blocks,stats->affinity_target_cpu,stats->observed_cpu); keep_running=0; break;
        }
        const dotprod_case_t *input=&cases[(stats->arithmetic_verified_blocks+seed)%DOTPROD_CASES];
        output[0]=0x98765432U; output[DOTPROD_LANES*DOTPROD_CHAINS+1]=0x12345678U;
        int complete=execute_neon_dotprod_block(input,output+1,final);
#if defined(LVS_CPU_HELPER_TEST_DOTPROD_INTERRUPT)
        if (!final && stats->arithmetic_verified_blocks==2) { keep_running=0; complete=0; }
#endif
        if (!complete) { ++stats->interrupted_arithmetic_blocks; continue; }
        if (complete < 0) { record_worker_error(stats,"dotprod_execution_state",0,4,0); keep_running=0; break; }
#if defined(LVS_CPU_HELPER_TEST_DOTPROD_CORRUPT)
        output[1 + (stats->progress_index & 1 ? 16 : 0)] ^= 1U;
#endif
#if defined(LVS_CPU_HELPER_TEST_DOTPROD_CORRUPT_PERIODIC)
        if (!final && stats->arithmetic_verified_blocks==2) output[1]^=1U;
#endif
#if defined(LVS_CPU_HELPER_TEST_DOTPROD_CORRUPT_FINAL)
        if (final) output[17]^=1U;
#endif
#if defined(LVS_CPU_HELPER_TEST_DOTPROD_CORRUPT_GUARD)
        output[0]^=1U;
#endif
#if defined(LVS_CPU_HELPER_TEST_DOTPROD_CORRUPT_UNSIGNED)
        output[17] ^= 1U;
#endif
        if (output[0]!=0x98765432U || output[DOTPROD_LANES*DOTPROD_CHAINS+1]!=0x12345678U)
            record_worker_error(stats,"dotprod_store_guard",stats->arithmetic_verified_blocks,1,0);
        for (int n=0;n<DOTPROD_LANES*DOTPROD_CHAINS && !stats->error_count;++n)
            if (output[n+1]!=input->expected[n]) {
                stats->first_error_lane=n;
                record_worker_error(stats,"dotprod_mismatch",stats->arithmetic_verified_blocks,input->expected[n],output[n+1]);
            }
        stats->observed_cpu=sched_getcpu();
        if (stats->observed_cpu!=stats->affinity_target_cpu)
            record_worker_error(stats,"affinity_lost",stats->arithmetic_verified_blocks,stats->affinity_target_cpu,stats->observed_cpu);
        if (stats->error_count) { keep_running=0; break; }
        if (stats->arithmetic_verified_blocks==UINT64_MAX) {
            record_worker_error(stats,"dotprod_counter_overflow",UINT64_MAX,0,0); keep_running=0; break;
        }
        ++stats->arithmetic_verified_blocks; ++stats->verify_passes;
        if (final) { stats->final_verification_completed=1; publish_verified_progress(stats,1); break; }
        int initial=!stats->initial_verification_completed;
        if (initial) stats->initial_verification_completed=1; else stats->periodic_verification_completed=1;
        publish_verified_progress(stats,initial);
    }
#else
    (void)seed; record_worker_error(stats,"dotprod_not_compiled",0,1,0); keep_running=0;
#endif
}
