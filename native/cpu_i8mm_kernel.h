/* Explicit-only FEAT_I8MM Advanced SIMD: A[2][8] row-major,
 * B[8][2] packed by columns, C[2][2] row-major. No global ISA flags. */
#define I8MM_CHAINS 8
#define I8MM_LANES 4
#define I8MM_ROUNDS 256
#define I8MM_CASES 4

static int i8mm_capability(uint64_t hwcap, uint64_t hwcap2) {
    return (hwcap & 3) == 3 && (hwcap2 & (1ULL << 13)) != 0;
}
static int cpu_supports_neon_i8mm(void) {
#if defined(LVS_CPU_HELPER_TEST_I8MM)
# if defined(LVS_CPU_HELPER_TEST_DISABLE_I8MM)
    return 0;
# else
    return 1;
# endif
#elif defined(LVS_CPU_HELPER_ENABLE_I8MM) && defined(__aarch64__) && defined(__linux__)
    return i8mm_capability(getauxval(AT_HWCAP),getauxval(AT_HWCAP2));
#else
    return 0;
#endif
}

typedef struct {
    uint8_t a[128], b[128];
    uint32_t initial[32], expected[32];
} i8mm_case_t;

static int i8mm_value(uint8_t bits, int is_unsigned) {
    return is_unsigned || bits < 128 ? (int)bits : (int)bits - 256;
}
static uint32_t i8mm_reference(uint32_t initial, const uint8_t *a, const uint8_t *b,
                               int row, int col, int kind) {
    int64_t sum=0;
    for (int k=0;k<8;++k)
        sum += (int64_t)i8mm_value(a[row*8+k],kind!=0) * i8mm_value(b[col*8+k],kind==1);
    /* At most 8*255*255*256 + UINT32_MAX, safely representable in int64. */
    return (uint32_t)((int64_t)initial + sum*I8MM_ROUNDS);
}
static void prepare_i8mm_case(i8mm_case_t *input,uint32_t seed) {
    static const uint8_t values[]={128,127,255,0,1,63,193};
    for (int n=0;n<128;++n) {
        input->a[n]=values[((uint32_t)n+seed)%7];
        input->b[n]=values[((uint32_t)n*3+seed+1)%7];
    }
    for (int chain=0;chain<8;++chain)
        for (int lane=0;lane<4;++lane) {
            int n=chain*4+lane,kind=chain<3 ? 0 : chain<6 ? 1 : 2;
            input->initial[n]=n%2 ? 0x80000000U : UINT32_MAX-seed;
            input->expected[n]=i8mm_reference(input->initial[n],input->a+16*chain,
                                             input->b+16*chain,lane/2,lane%2,kind);
        }
}

#if defined(LVS_CPU_HELPER_ENABLE_I8MM) && defined(__aarch64__) && defined(__linux__)
#if !defined(__clang__)
#pragma GCC push_options
#pragma GCC target("+i8mm")
#endif
#if defined(__clang__)
__attribute__((noinline,target("i8mm")))
#else
__attribute__((noinline))
#endif
static int execute_neon_i8mm_block(const i8mm_case_t *input,uint32_t *output,int final) {
#define I8MM_SIGNED(N) \
    int8x16_t a##N=vld1q_s8((const int8_t*)input->a+16*N), b##N=vld1q_s8((const int8_t*)input->b+16*N); \
    int32x4_t x##N=vreinterpretq_s32_u32(vld1q_u32(input->initial+4*N))
#define I8MM_UNSIGNED(N) \
    uint8x16_t a##N=vld1q_u8(input->a+16*N), b##N=vld1q_u8(input->b+16*N); \
    uint32x4_t x##N=vld1q_u32(input->initial+4*N)
#define I8MM_MIXED(N) \
    uint8x16_t a##N=vld1q_u8(input->a+16*N); int8x16_t b##N=vld1q_s8((const int8_t*)input->b+16*N); \
    int32x4_t x##N=vreinterpretq_s32_u32(vld1q_u32(input->initial+4*N))
    I8MM_SIGNED(0); I8MM_SIGNED(1); I8MM_SIGNED(2);
    I8MM_UNSIGNED(3); I8MM_UNSIGNED(4); I8MM_UNSIGNED(5);
    I8MM_MIXED(6); I8MM_MIXED(7);
#undef I8MM_SIGNED
#undef I8MM_UNSIGNED
#undef I8MM_MIXED
    for (int r=0;r<I8MM_ROUNDS;++r) {
        if ((r&31)==0 && !final && !keep_running) return 0;
        x0=vmmlaq_s32(x0,a0,b0); x1=vmmlaq_s32(x1,a1,b1); x2=vmmlaq_s32(x2,a2,b2);
        x3=vmmlaq_u32(x3,a3,b3); x4=vmmlaq_u32(x4,a4,b4); x5=vmmlaq_u32(x5,a5,b5);
        x6=vusmmlaq_s32(x6,a6,b6); x7=vusmmlaq_s32(x7,a7,b7);
        __asm__ volatile("" : "+w"(x0),"+w"(x1),"+w"(x2),"+w"(x3),
                             "+w"(x4),"+w"(x5),"+w"(x6),"+w"(x7));
    }
#define I8MM_STORE_S(N) vst1q_u32(output+4*N,vreinterpretq_u32_s32(x##N))
    I8MM_STORE_S(0); I8MM_STORE_S(1); I8MM_STORE_S(2);
    vst1q_u32(output+12,x3); vst1q_u32(output+16,x4); vst1q_u32(output+20,x5);
    I8MM_STORE_S(6); I8MM_STORE_S(7);
#undef I8MM_STORE_S
    return 1;
}
#if !defined(__clang__)
#pragma GCC pop_options
#endif
#elif defined(LVS_CPU_HELPER_TEST_I8MM)
/* Deliberately stepwise emulator, not physical instruction evidence. */
static int execute_neon_i8mm_block(const i8mm_case_t *input,uint32_t *output,int final) {
    memcpy(output,input->initial,sizeof(input->initial));
    for (int r=0;r<I8MM_ROUNDS;++r) {
        if (!final && !keep_running) return 0;
        for (int chain=0;chain<8;++chain)
            for (int k=0;k<8;++k) {
                int base=chain*16;
                int a0=i8mm_value(input->a[base+k],chain>=3),a1=i8mm_value(input->a[base+8+k],chain>=3);
                int b0=i8mm_value(input->b[base+k],chain>=3 && chain<6),b1=i8mm_value(input->b[base+8+k],chain>=3 && chain<6);
                output[chain*4]+=(uint32_t)(a0*b0); output[chain*4+1]+=(uint32_t)(a0*b1);
                output[chain*4+2]+=(uint32_t)(a1*b0); output[chain*4+3]+=(uint32_t)(a1*b1);
            }
    }
    return 1;
}
#endif

static void run_neon_i8mm_loop(uint32_t seed, worker_stats_t *stats) {
#if (defined(LVS_CPU_HELPER_ENABLE_I8MM) && defined(__aarch64__) && defined(__linux__)) || defined(LVS_CPU_HELPER_TEST_I8MM)
#if defined(LVS_CPU_HELPER_TEST_I8MM)
    stats->i8mm_hwcap=3; stats->i8mm_hwcap2=1ULL<<13;
#else
    stats->i8mm_hwcap=getauxval(AT_HWCAP); stats->i8mm_hwcap2=getauxval(AT_HWCAP2);
#endif
#if defined(LVS_CPU_HELPER_TEST_I8MM_CAPABILITY_LOST)
    stats->i8mm_hwcap2=0;
#endif
    if (!i8mm_capability(stats->i8mm_hwcap,stats->i8mm_hwcap2)) {
        record_worker_error(stats,"i8mm_capability_lost",0,1ULL<<13,stats->i8mm_hwcap2); keep_running=0; return;
    }
    i8mm_case_t cases[I8MM_CASES];
    uint32_t output[I8MM_CHAINS*I8MM_LANES+2];
    for (int k=0;k<I8MM_CASES;++k) prepare_i8mm_case(&cases[k],seed+(uint32_t)k);
    for (;;) {
        int final = !keep_running;
        if (stats->error_count || (final && !stats->initial_verification_completed)) break;
        stats->observed_cpu = sched_getcpu();
#if defined(LVS_CPU_HELPER_TEST_I8MM_MIGRATION)
        ++stats->observed_cpu;
#endif
        if (stats->observed_cpu != stats->affinity_target_cpu) {
            record_worker_error(stats,"affinity_lost",stats->arithmetic_verified_blocks,stats->affinity_target_cpu,stats->observed_cpu); keep_running=0; break;
        }
        const i8mm_case_t *input=&cases[(stats->arithmetic_verified_blocks+seed)%I8MM_CASES];
        output[0]=0x98765432U; output[I8MM_LANES*I8MM_CHAINS+1]=0x12345678U;
        int complete=execute_neon_i8mm_block(input,output+1,final);
#if defined(LVS_CPU_HELPER_TEST_I8MM_INTERRUPT)
        if (!final && stats->arithmetic_verified_blocks==2) { keep_running=0; complete=0; }
#endif
        if (!complete) { ++stats->interrupted_arithmetic_blocks; continue; }
        if (complete < 0) { record_worker_error(stats,"i8mm_execution_state",0,4,0); keep_running=0; break; }
#if defined(LVS_CPU_HELPER_TEST_I8MM_CORRUPT)
        output[1] ^= 1U;
#endif
#if defined(LVS_CPU_HELPER_TEST_I8MM_CORRUPT_PERIODIC)
        if (!final && stats->arithmetic_verified_blocks==2) output[1]^=1U;
#endif
#if defined(LVS_CPU_HELPER_TEST_I8MM_CORRUPT_FINAL)
        if (final) output[13]^=1U;
#endif
#if defined(LVS_CPU_HELPER_TEST_I8MM_CORRUPT_GUARD)
        output[0]^=1U;
#endif
#if defined(LVS_CPU_HELPER_TEST_I8MM_CORRUPT_MIXED)
        output[25]^=1U;
#endif
#if defined(LVS_CPU_HELPER_TEST_I8MM_CORRUPT_LANE)
        output[1+LVS_CPU_HELPER_TEST_I8MM_CORRUPT_LANE]^=1U;
#endif
#if defined(LVS_CPU_HELPER_TEST_I8MM_CORRUPT_UNSIGNED)
        output[13] ^= 1U;
#endif
        if (output[0]!=0x98765432U || output[I8MM_LANES*I8MM_CHAINS+1]!=0x12345678U)
            record_worker_error(stats,"i8mm_store_guard",stats->arithmetic_verified_blocks,1,0);
        for (int n=0;n<I8MM_LANES*I8MM_CHAINS && !stats->error_count;++n)
            if (output[n+1]!=input->expected[n]) {
                stats->first_error_lane=n;
                record_worker_error(stats,"i8mm_mismatch",stats->arithmetic_verified_blocks,input->expected[n],output[n+1]);
            }
        stats->observed_cpu=sched_getcpu();
        if (stats->observed_cpu!=stats->affinity_target_cpu)
            record_worker_error(stats,"affinity_lost",stats->arithmetic_verified_blocks,stats->affinity_target_cpu,stats->observed_cpu);
        if (stats->error_count) { keep_running=0; break; }
        if (stats->arithmetic_verified_blocks==UINT64_MAX) {
            record_worker_error(stats,"i8mm_counter_overflow",UINT64_MAX,0,0); keep_running=0; break;
        }
        ++stats->arithmetic_verified_blocks; ++stats->verify_passes;
        if (final) { stats->final_verification_completed=1; publish_verified_progress(stats,1); break; }
        int initial=!stats->initial_verification_completed;
        if (initial) stats->initial_verification_completed=1; else stats->periodic_verification_completed=1;
        publish_verified_progress(stats,initial);
    }
#else
    (void)seed; record_worker_error(stats,"i8mm_not_compiled",0,1,0); keep_running=0;
#endif
}
