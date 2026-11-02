/* Explicit-only unsigned-byte/signed-byte dot-product stress.
 * Baseline compilation has no global VNNI/AVX flags. Optional target regions
 * are excluded on compilers without the requisite intrinsic/target support. */
#define VNNI_CHAINS 8
#define VNNI_ROUNDS 256
#define VNNI_CASES 4
#define VNNI_MAX_LANES 16
#if defined(__x86_64__) && defined(__GNUC__) && !defined(__clang__) && !defined(LVS_CPU_HELPER_DISABLE_VNNI)
# if __GNUC__ >= 11
#  define LVS_COMPILED_AVX_VNNI 1
# endif
# if __GNUC__ >= 8
#  define LVS_COMPILED_AVX512_VNNI 1
# endif
#endif
#ifndef LVS_COMPILED_AVX_VNNI
#define LVS_COMPILED_AVX_VNNI 0
#endif
#ifndef LVS_COMPILED_AVX512_VNNI
#define LVS_COMPILED_AVX512_VNNI 0
#endif

static int vnni_kernel(kernel_flavor_t flavor) {
    return flavor == KERNEL_AVX_VNNI || flavor == KERNEL_AVX512_VNNI;
}

/* Pure capability decoding is shared by the actual pinned CPUID probe and
 * adversarial fixtures. AVX-VNNI is VEX, not AVX512VL emulation. */
static int vnni_capability(int wide, int os_avx, uint64_t xcr0,
                           uint32_t leaf7_ebx, uint32_t leaf7_ecx,
                           uint32_t max_subleaf, uint32_t leaf71_eax) {
    if (!os_avx || (xcr0 & 6) != 6 || !(leaf7_ebx & (1U << 5))) return 0;
    if (wide) return (leaf7_ebx & (1U << 16)) && (leaf7_ecx & (1U << 11)) && (xcr0 & 0xe6) == 0xe6;
    return max_subleaf >= 1 && (leaf71_eax & (1U << 4));
}

/* No signed-overflow UB, SIMD intrinsic, host saturation or SIMD checksum.
 * Four products and the bounded recurrence fit int64; conversion to uint32
 * implements the instruction's nonsaturating modulo-2^32 accumulator. */
static uint32_t vnni_reference(uint32_t initial, const uint8_t *a, const int8_t *b) {
    int64_t dot = 0;
    for (int j = 0; j < 4; ++j) dot += (int64_t)a[j] * (int64_t)b[j];
    return (uint32_t)((int64_t)initial + dot * VNNI_ROUNDS);
}

typedef struct {
    uint8_t a[VNNI_CHAINS * VNNI_MAX_LANES * 4];
    int8_t b[VNNI_CHAINS * VNNI_MAX_LANES * 4];
    uint32_t initial[VNNI_CHAINS * VNNI_MAX_LANES];
    uint32_t expected[VNNI_CHAINS * VNNI_MAX_LANES];
} vnni_case_t;

static void prepare_vnni_case(vnni_case_t *input, uint32_t seed, int lanes) {
    for (int n = 0; n < VNNI_CHAINS * lanes; ++n) {
        uint32_t mix = seed * 1664525U + (uint32_t)n * 1013904223U;
        input->initial[n] = n % 4 == 0 ? UINT32_MAX - 7U : n % 4 == 1 ? 0x80000000U : mix;
        for (int j = 0; j < 4; ++j) {
            input->a[4*n+j] = n % 4 < 2 ? 255U : (uint8_t)(mix >> (j*8));
            input->b[4*n+j] = n % 4 == 0 ? 127 : n % 4 == 1 ? -128 : (int8_t)((int)((mix >> (j*8)) & 255U) - 128);
        }
        input->expected[n] = vnni_reference(input->initial[n], input->a + 4*n, input->b + 4*n);
    }
}

/* Eight independent accumulator chains; compiler barriers retain each of the
 * 256 dependent dot-product instructions per chain rather than folding repeats. */
#define VNNI_LOAD(N) VECTOR x##N = LOAD(input->initial + N*LANES); \
    VECTOR a##N = LOAD(input->a + N*LANES*4); VECTOR b##N = LOAD(input->b + N*LANES*4)
#define VNNI_STORE(N) STORE(output + N*LANES, x##N)
#define VNNI_BODY \
    VNNI_LOAD(0); VNNI_LOAD(1); VNNI_LOAD(2); VNNI_LOAD(3); \
    VNNI_LOAD(4); VNNI_LOAD(5); VNNI_LOAD(6); VNNI_LOAD(7); \
    for (int r = 0; r < VNNI_ROUNDS; ++r) { \
        if ((r & 31) == 0 && !final && !keep_running) return 0; \
        x0=DOT(x0,a0,b0); x1=DOT(x1,a1,b1); x2=DOT(x2,a2,b2); x3=DOT(x3,a3,b3); \
        x4=DOT(x4,a4,b4); x5=DOT(x5,a5,b5); x6=DOT(x6,a6,b6); x7=DOT(x7,a7,b7); \
        __asm__ volatile("" : "+v"(x0), "+v"(x1), "+v"(x2), "+v"(x3), "+v"(x4), "+v"(x5), "+v"(x6), "+v"(x7)); \
    } \
    VNNI_STORE(0); VNNI_STORE(1); VNNI_STORE(2); VNNI_STORE(3); \
    VNNI_STORE(4); VNNI_STORE(5); VNNI_STORE(6); VNNI_STORE(7); return 1

#if LVS_COMPILED_AVX_VNNI
#define VECTOR __m256i
#define LANES 8
#define LOAD(P) _mm256_loadu_si256((const __m256i *)(P))
#define STORE(P,V) _mm256_storeu_si256((__m256i *)(P),V)
#define DOT _mm256_dpbusd_avx_epi32
__attribute__((target("avx2,avxvnni"), noinline))
static int execute_avx_vnni_block(const vnni_case_t *input, uint32_t *output, int final) { VNNI_BODY; }
#undef VECTOR
#undef LANES
#undef LOAD
#undef STORE
#undef DOT
#endif
#if LVS_COMPILED_AVX512_VNNI
#define VECTOR __m512i
#define LANES 16
#define LOAD(P) _mm512_loadu_si512((const void *)(P))
#define STORE(P,V) _mm512_storeu_si512((void *)(P),V)
#define DOT _mm512_dpbusd_epi32
__attribute__((target("avx2,avx512f,avx512vnni"), noinline))
static int execute_avx512_vnni_block(const vnni_case_t *input, uint32_t *output, int final) { VNNI_BODY; }
#undef VECTOR
#undef LANES
#undef LOAD
#undef STORE
#undef DOT
#endif
#undef VNNI_BODY
#undef VNNI_LOAD
#undef VNNI_STORE

static int execute_vnni_block(kernel_flavor_t flavor, const vnni_case_t *input, uint32_t *output, int final) {
#if defined(LVS_CPU_HELPER_TEST_VNNI)
    /* Deliberately different step-by-step emulator; never hardware ISA proof. */
    int lanes = flavor == KERNEL_AVX_VNNI ? 8 : 16;
    memcpy(output, input->initial, (size_t)(VNNI_CHAINS * lanes) * sizeof(*output));
    for (int r = 0; r < VNNI_ROUNDS; ++r) {
        if (!final && !keep_running) return 0;
        for (int n = 0; n < VNNI_CHAINS * lanes; ++n)
            for (int j = 0; j < 4; ++j)
                output[n] += (uint32_t)((int32_t)input->a[n*4+j] * (int32_t)input->b[n*4+j]);
    }
    return 1;
#else
#if LVS_COMPILED_AVX_VNNI
    if (flavor == KERNEL_AVX_VNNI) return execute_avx_vnni_block(input, output, final);
#endif
#if LVS_COMPILED_AVX512_VNNI
    if (flavor == KERNEL_AVX512_VNNI) return execute_avx512_vnni_block(input, output, final);
#endif
    (void)flavor; (void)input; (void)output; (void)final;
    return -1;
#endif
}

static void run_vnni_loop(kernel_flavor_t flavor, uint32_t seed, worker_stats_t *stats) {
    int lanes = flavor == KERNEL_AVX_VNNI ? 8 : 16;
    vnni_case_t cases[VNNI_CASES];
    uint32_t output[VNNI_CHAINS * VNNI_MAX_LANES];
    for (int k = 0; k < VNNI_CASES; ++k) prepare_vnni_case(&cases[k], seed + (uint32_t)k, lanes);
    for (;;) {
        int final = !keep_running;
        if (stats->error_count || (final && !stats->initial_verification_completed)) break;
        stats->observed_cpu = sched_getcpu();
        if (stats->observed_cpu != stats->affinity_target_cpu) {
            record_worker_error(stats,"affinity_lost",stats->arithmetic_verified_blocks,stats->affinity_target_cpu,stats->observed_cpu);
            keep_running=0; break;
        }
        const vnni_case_t *input = &cases[(stats->arithmetic_verified_blocks + seed) % VNNI_CASES];
        int complete = execute_vnni_block(flavor, input, output, final);
#if defined(LVS_CPU_HELPER_TEST_VNNI_INTERRUPT)
        if (!final && stats->arithmetic_verified_blocks == 2) { keep_running=0; complete=0; }
#endif
        if (!complete) { ++stats->interrupted_arithmetic_blocks; continue; }
        if (complete < 0) { record_worker_error(stats,"vnni_not_compiled",0,1,0); keep_running=0; break; }
#if defined(LVS_CPU_HELPER_TEST_VNNI_CORRUPT)
        output[VNNI_CHAINS * lanes - 1] ^= 1U;
#endif
        for (int n = 0; n < VNNI_CHAINS * lanes; ++n) {
            if (output[n] != input->expected[n]) {
                stats->first_error_lane=n;
                record_worker_error(stats,"vnni_mismatch",stats->arithmetic_verified_blocks,input->expected[n],output[n]);
                keep_running=0; break;
            }
        }
        stats->observed_cpu = sched_getcpu();
        if (stats->observed_cpu != stats->affinity_target_cpu) {
            record_worker_error(stats,"affinity_lost",stats->arithmetic_verified_blocks,stats->affinity_target_cpu,stats->observed_cpu);
            keep_running=0;
        }
        if (stats->error_count) break;
        if (stats->arithmetic_verified_blocks == UINT64_MAX) {
            record_worker_error(stats,"vnni_counter_overflow",UINT64_MAX,0,0); keep_running=0; break;
        }
        ++stats->arithmetic_verified_blocks; ++stats->verify_passes;
        if (final) { stats->final_verification_completed=1; publish_verified_progress(stats,1); break; }
        int initial=!stats->initial_verification_completed;
        if (initial) stats->initial_verification_completed=1;
        else stats->periodic_verification_completed=1;
        publish_verified_progress(stats,initial);
    }
}
