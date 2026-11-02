/* Explicit, VL-agnostic SVE2 signed widening multiply-accumulate.
 * Four bottom/top pairs: SMLALB uses even halfwords, SMLALT odd halfwords.
 * Baseline functions never execute SVE; no global ISA compiler flag. */
#define SVE2_CHAINS 8
#define SVE2_ROUNDS 256
#define SVE2_CASES 4
#define SVE2_MAX_LANES 64

static int sve2_capability(uint64_t hwcap, uint64_t hwcap2) {
    return (hwcap & ((1ULL << 22) | 3)) == ((1ULL << 22) | 3)
        && (hwcap2 & (1ULL << 1)) != 0;
}

static int cpu_supports_sve2_smlal(void) {
#if defined(LVS_CPU_HELPER_TEST_SVE2)
# if defined(LVS_CPU_HELPER_TEST_DISABLE_SVE2)
    return 0;
# else
    return 1;
# endif
#elif defined(LVS_CPU_HELPER_ENABLE_SVE2) && defined(__aarch64__) && defined(__linux__)
    return sve2_capability(getauxval(AT_HWCAP), getauxval(AT_HWCAP2));
#else
    return 0;
#endif
}

static uint32_t sve2_reference(uint32_t initial, int16_t a, int16_t b) {
    /* 256 * (-32768)^2 + UINT32_MAX fits int64; unsigned cast defines wrap. */
    return (uint32_t)((int64_t)initial + (int64_t)a * b * SVE2_ROUNDS);
}

typedef struct {
    int16_t a[SVE2_CHAINS * SVE2_MAX_LANES];
    int16_t b[SVE2_CHAINS * SVE2_MAX_LANES];
    uint32_t initial[SVE2_CHAINS * SVE2_MAX_LANES];
    uint32_t expected[SVE2_CHAINS * SVE2_MAX_LANES];
} sve2_case_t;

static void prepare_sve2_case(sve2_case_t *input, uint32_t seed, int lanes) {
    static const int16_t extremes[] = {-32768, 32767, -1, 0, 1, -12345, 23456};
    for (int n = 0; n < SVE2_CHAINS * lanes; ++n) {
        input->a[n] = extremes[((uint32_t)n + seed) % 7];
        input->b[n] = extremes[((uint32_t)n * 3 + seed + 1) % 7];
        input->initial[n] = n % 2 ? 0x80000000U : UINT32_MAX - seed;
    }
    for (int chain = 0; chain < SVE2_CHAINS; ++chain)
        for (int lane = 0; lane < lanes; ++lane) {
            int n = chain * lanes + lane;
            int halfword = (chain / 2) * 2 * lanes + 2 * lane + chain % 2;
            input->expected[n] = sve2_reference(input->initial[n], input->a[halfword], input->b[halfword]);
        }
}

#if defined(LVS_CPU_HELPER_ENABLE_SVE2) && defined(__aarch64__) && defined(__linux__)
#if !defined(__clang__)
#pragma GCC push_options
#pragma GCC target("+sve2")
#endif
#include <arm_sve.h>
#if defined(__clang__)
__attribute__((noinline, target("sve2")))
#else
__attribute__((noinline))
#endif
static int execute_sve2_smlal_block(const sve2_case_t *input, uint32_t *output, int lanes, int final) {
    if ((int)svcntw() != lanes) return -1;
    svbool_t words = svptrue_b32(), halves = svptrue_b16();
#define SVE2_LOAD(P,B,T) \
    svint16_t a##P = svld1_s16(halves, input->a + P*2*lanes); \
    svint16_t b##P = svld1_s16(halves, input->b + P*2*lanes); \
    svint32_t x##B = svreinterpret_s32_u32(svld1_u32(words, input->initial + B*lanes)); \
    svint32_t x##T = svreinterpret_s32_u32(svld1_u32(words, input->initial + T*lanes))
    SVE2_LOAD(0,0,1); SVE2_LOAD(1,2,3); SVE2_LOAD(2,4,5); SVE2_LOAD(3,6,7);
#undef SVE2_LOAD
    for (int r = 0; r < SVE2_ROUNDS; ++r) {
        if ((r & 31) == 0 && !final && !keep_running) return 0;
        x0=svmlalb_s32(x0,a0,b0); x1=svmlalt_s32(x1,a0,b0);
        x2=svmlalb_s32(x2,a1,b1); x3=svmlalt_s32(x3,a1,b1);
        x4=svmlalb_s32(x4,a2,b2); x5=svmlalt_s32(x5,a2,b2);
        x6=svmlalb_s32(x6,a3,b3); x7=svmlalt_s32(x7,a3,b3);
        __asm__ volatile("" : "+w"(x0), "+w"(x1), "+w"(x2), "+w"(x3),
                             "+w"(x4), "+w"(x5), "+w"(x6), "+w"(x7));
    }
#define SVE2_STORE(N) svst1_u32(words, output + N*lanes, svreinterpret_u32_s32(x##N))
    SVE2_STORE(0); SVE2_STORE(1); SVE2_STORE(2); SVE2_STORE(3);
    SVE2_STORE(4); SVE2_STORE(5); SVE2_STORE(6); SVE2_STORE(7);
#undef SVE2_STORE
    return 1;
}
#if !defined(__clang__)
#pragma GCC pop_options
#endif
#elif defined(LVS_CPU_HELPER_TEST_SVE2)
/* Deliberately separate, stepwise integer emulation; never ISA execution proof. */
static int execute_sve2_smlal_block(const sve2_case_t *input, uint32_t *output, int lanes, int final) {
    memcpy(output, input->initial, (size_t)lanes * SVE2_CHAINS * sizeof(*output));
    for (int r = 0; r < SVE2_ROUNDS; ++r) {
        if (!final && !keep_running) return 0;
        for (int pair = 0; pair < 4; ++pair)
            for (int half = 0; half < 2 * lanes; ++half) {
                int source = pair * 2 * lanes + half;
                int dest = (pair * 2 + (half & 1)) * lanes + half / 2;
                output[dest] += (uint32_t)((int32_t)input->a[source] * input->b[source]);
            }
    }
    return 1;
}
#endif

static void run_sve2_smlal_loop(uint32_t seed, worker_stats_t *stats) {
#if (defined(LVS_CPU_HELPER_ENABLE_SVE2) && defined(__aarch64__) && defined(__linux__)) || defined(LVS_CPU_HELPER_TEST_SVE2)
#if defined(LVS_CPU_HELPER_TEST_SVE2)
    const char *raw = getenv("LVS_TEST_SVE2_VL_BYTES");
    int state = raw ? atoi(raw) : 16;
    stats->sve2_hwcap = (1ULL << 22) | 3; stats->sve2_hwcap2 = 2;
#if defined(LVS_CPU_HELPER_TEST_SVE2_MIXED_VL)
    state = stats->progress_index & 1 ? 48 : 32;
#endif
    stats->sve_vl_errno = state < 0 ? EINVAL : 0;
#else
    stats->sve2_hwcap = getauxval(AT_HWCAP); stats->sve2_hwcap2 = getauxval(AT_HWCAP2);
    errno = 0;
    int state = prctl(PR_SVE_GET_VL, 0UL, 0UL, 0UL, 0UL);
    stats->sve_vl_errno = state < 0 ? errno : 0;
#endif
    if (state < 0) { record_worker_error(stats,"sve2_vl_query",0,0,stats->sve_vl_errno); keep_running=0; return; }
    stats->sve_vl_bytes = state & 0xffff; stats->sve_vl_flags = state & ~0xffff;
    if (stats->sve_vl_bytes < 16 || stats->sve_vl_bytes > 256 || stats->sve_vl_bytes % 16) {
        record_worker_error(stats,"sve2_vl_invalid",0,16,stats->sve_vl_bytes); keep_running=0; return;
    }
    int lanes = stats->sve_int32_lanes = stats->sve_vl_bytes / 4;
    sve2_case_t *cases = calloc(SVE2_CASES, sizeof(*cases));
    uint32_t *output = calloc((size_t)lanes * SVE2_CHAINS + 2, sizeof(*output));
    if (!cases || !output) { record_worker_error(stats,"sve2_allocation",0,1,0); keep_running=0; goto cleanup; }
    for (int k=0;k<SVE2_CASES;++k) prepare_sve2_case(&cases[k],seed+(uint32_t)k,lanes);
    for (;;) {
        int final = !keep_running;
        if (stats->error_count || (final && !stats->initial_verification_completed)) break;
        stats->observed_cpu = sched_getcpu();
#if defined(LVS_CPU_HELPER_TEST_SVE2_MIGRATION)
        ++stats->observed_cpu;
#endif
        if (stats->observed_cpu != stats->affinity_target_cpu) {
            record_worker_error(stats,"affinity_lost",stats->arithmetic_verified_blocks,stats->affinity_target_cpu,stats->observed_cpu); keep_running=0; break;
        }
        const sve2_case_t *input=&cases[(stats->arithmetic_verified_blocks+seed)%SVE2_CASES];
        output[0]=0x98765432U; output[lanes*SVE2_CHAINS+1]=0x12345678U;
        int complete=execute_sve2_smlal_block(input,output+1,lanes,final);
#if defined(LVS_CPU_HELPER_TEST_SVE2_INTERRUPT)
        if (!final && stats->arithmetic_verified_blocks==2) { keep_running=0; complete=0; }
#endif
        if (!complete) { ++stats->interrupted_arithmetic_blocks; continue; }
        if (complete < 0) { record_worker_error(stats,"sve2_execution_state",0,lanes,0); keep_running=0; break; }
#if defined(LVS_CPU_HELPER_TEST_SVE2_CORRUPT)
        output[1 + (stats->progress_index & 1 ? lanes : 0)] ^= 1U;
#endif
#if defined(LVS_CPU_HELPER_TEST_SVE2_CORRUPT_TOP)
        output[1+lanes] ^= 1U;
#endif
        if (output[0]!=0x98765432U || output[lanes*SVE2_CHAINS+1]!=0x12345678U)
            record_worker_error(stats,"sve2_store_guard",stats->arithmetic_verified_blocks,1,0);
        for (int n=0;n<lanes*SVE2_CHAINS && !stats->error_count;++n)
            if (output[n+1]!=input->expected[n]) {
                stats->first_error_lane=n;
                record_worker_error(stats,"sve2_smlal_mismatch",stats->arithmetic_verified_blocks,input->expected[n],output[n+1]);
            }
        stats->observed_cpu=sched_getcpu();
        if (stats->observed_cpu!=stats->affinity_target_cpu)
            record_worker_error(stats,"affinity_lost",stats->arithmetic_verified_blocks,stats->affinity_target_cpu,stats->observed_cpu);
        if (stats->error_count) { keep_running=0; break; }
        if (stats->arithmetic_verified_blocks==UINT64_MAX) {
            record_worker_error(stats,"sve2_counter_overflow",UINT64_MAX,0,0); keep_running=0; break;
        }
        ++stats->arithmetic_verified_blocks; ++stats->verify_passes;
        if (final) { stats->final_verification_completed=1; publish_verified_progress(stats,1); break; }
        int initial=!stats->initial_verification_completed;
        if (initial) stats->initial_verification_completed=1; else stats->periodic_verification_completed=1;
        publish_verified_progress(stats,initial);
    }
cleanup:
    free(output); free(cases);
#else
    (void)seed; record_worker_error(stats,"sve2_not_compiled",0,1,0); keep_running=0;
#endif
}
