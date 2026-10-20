#define _GNU_SOURCE
#include <errno.h>
#if defined(__x86_64__) || defined(__i386__)
#include <cpuid.h>
#include <immintrin.h>
#endif
#if defined(__aarch64__) && defined(__linux__)
#include <arm_neon.h>
#include <asm/hwcap.h>
#include <sys/auxv.h>
#include <sys/prctl.h>
#ifndef HWCAP_SVE
#define HWCAP_SVE (1UL << 22)
#endif
#ifndef PR_SVE_GET_VL
#define PR_SVE_GET_VL 51
#define PR_SVE_VL_LEN_MASK 0xffff
#endif
#endif
#include <inttypes.h>
#include <math.h>
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>

typedef enum {
    MODE_AUTO = 0,
    MODE_SCALAR = 1,
    MODE_SSE = 2,
    MODE_AVX = 3,
    MODE_AVX2 = 4,
    MODE_AVX512 = 5,
    MODE_NEON = 6,
    MODE_SVE = 7
} stress_mode_t;

typedef enum {
    KERNEL_UNSPECIFIED = 0,
    KERNEL_SCALAR = 1,
    KERNEL_SSE2 = 2,
    KERNEL_SSE2_INT = 3,
    KERNEL_AVX = 4,
    KERNEL_AVX_FMA = 5,
    KERNEL_AVX2 = 6,
    KERNEL_AVX2_FMA = 7,
    KERNEL_AVX512_FMA = 8,
    KERNEL_AVX512_INT = 9,
    KERNEL_NEON = 10,
    KERNEL_NEON_FP32_FMA = 11,
    KERNEL_SVE_FP32_FMA = 12
} kernel_flavor_t;

typedef struct {
    uint64_t verify_passes;
    uint64_t error_count;
    uint64_t canary_passes;
    uint64_t first_error_iteration;
    uint64_t first_error_expected;
    uint64_t first_error_actual;
    int affinity_target_cpu;
    int affinity_attempted;
    int affinity_applied;
    int affinity_required;
    int affinity_error_code;
    int observed_cpu;
    int first_error_recorded;
    char first_error_kind[32];
    uint64_t arithmetic_verified_blocks;
    uint64_t interrupted_arithmetic_blocks;
    uint64_t fpcr;
    int initial_verification_completed;
    int periodic_verification_completed;
    int final_verification_completed;
    int first_error_lane;
    int progress_index;
    uint64_t progress_next_check;
    unsigned int progress_check_stride;
    double progress_check_time;
    int sve_vl_bytes;
    int sve_vl_flags;
    int sve_vl_errno;
    int sve_fp32_lanes;
} worker_stats_t;

typedef struct {
    int worker_index;
    int target_cpu;
    stress_mode_t mode;
    kernel_flavor_t kernel_flavor;
    worker_stats_t *stats;
} worker_args_t;

static volatile sig_atomic_t keep_running = 1;
static volatile uint64_t vector_sink_u64 = 0;
static const char *result_file_path = NULL;
static int sve_progress;

static int verified_fp32_kernel(kernel_flavor_t flavor) {
    return flavor == KERNEL_NEON_FP32_FMA || flavor == KERNEL_SVE_FP32_FMA;
}

/* One writer, O(threads) storage. Only verified block boundaries are published;
 * no I/O, mutex, or clock read occurs in the vector arithmetic hot loop. */
typedef struct {
    worker_stats_t stats;
    double monotonic;
} progress_slot_t;
static progress_slot_t *progress_slots;
static progress_slot_t *progress_snapshot;
static int progress_threads;
static pthread_mutex_t progress_lock = PTHREAD_MUTEX_INITIALIZER;
static FILE *progress_file;
static char *progress_path;
static unsigned long progress_sequence;
static int progress_io_error;
static double progress_write_seconds;

static double clock_seconds(clockid_t clock_id) {
    struct timespec value;
    if (clock_gettime(clock_id, &value) != 0) return 0.0;
    return (double)value.tv_sec + (double)value.tv_nsec / 1e9;
}

static void publish_verified_progress(worker_stats_t *stats, int force) {
    if (!progress_slots) return;
    int index = stats->progress_index;
    /* Adapt clock-check spacing to block latency, without changing arithmetic.
     * Fast cores avoid a clock read per block; slow cores publish promptly. */
    if (!force && stats->arithmetic_verified_blocks < stats->progress_next_check) return;
    double now = clock_seconds(CLOCK_MONOTONIC);
    unsigned int stride = stats->progress_check_stride ? stats->progress_check_stride : 1;
    double elapsed = now - stats->progress_check_time;
    if (stats->progress_check_time > 0) {
        if (elapsed > 0.1 && stride > 1) stride /= 2;
        else if (elapsed < 0.025 && stride <= UINT32_MAX / 2) stride *= 2;
    }
    stats->progress_check_stride = stride;
    stats->progress_check_time = now;
    stats->progress_next_check = UINT64_MAX - stats->arithmetic_verified_blocks < stride
        ? UINT64_MAX : stats->arithmetic_verified_blocks + stride;
    if (!force && now - progress_slots[index].monotonic < 0.25) return;
    pthread_mutex_lock(&progress_lock);
    progress_slots[index].stats = *stats;
    progress_slots[index].monotonic = now;
    pthread_mutex_unlock(&progress_lock);
}

static void write_progress_snapshot(const char *state, const int *cpu_ids) {
    if (!progress_file || progress_io_error) return;
    double before = clock_seconds(CLOCK_MONOTONIC);
    pthread_mutex_lock(&progress_lock);
    memcpy(progress_snapshot, progress_slots, (size_t)progress_threads * sizeof(*progress_slots));
    pthread_mutex_unlock(&progress_lock);
    double pair_before = clock_seconds(CLOCK_MONOTONIC);
    double realtime = clock_seconds(CLOCK_REALTIME);
    double now = clock_seconds(CLOCK_MONOTONIC);
    uint64_t total = 0;
    fprintf(progress_file, "{\"contract\":\"%s_progress_v1\","
        "\"sequence\":%lu,\"pid\":%ld,\"kernel_flavor\":\"%s\","
        "\"operation_family\":\"fp32_fused_multiply_add\",\"state\":\"%s\","
        "\"monotonic_seconds\":%.9f,\"realtime_seconds\":%.9f,"
        "\"clock_pair_uncertainty_seconds\":%.9f,\"snapshot_interval_seconds\":2.0,\"threads\":[",
        sve_progress ? "sve_fp32_fma" : "neon_fp32_fma", progress_sequence++, (long)getpid(),
        sve_progress ? "sve_fp32_fma" : "neon_fp32_fma", state, now, realtime, now - pair_before);
    for (int i = 0; i < progress_threads; ++i) {
        const progress_slot_t *slot = &progress_snapshot[i];
        const worker_stats_t *s = &slot->stats;
        /* Aggregate overflow is an evidence failure, never a wrapped count. */
        if (UINT64_MAX - total < s->arithmetic_verified_blocks) progress_io_error = 1;
        else total += s->arithmetic_verified_blocks;
        fprintf(progress_file, "%s{\"thread_index\":%d,\"cpu_id\":%d,"
            "\"published_monotonic_seconds\":%.9f,\"verified_blocks\":%" PRIu64 ","
            "\"initial_verified\":%s,\"periodic_verified\":%s,\"final_verified\":%s,"
            "\"error_count\":%" PRIu64 ",\"affinity_applied\":%s,\"observed_cpu\":%d,"
            "\"interrupted_arithmetic_blocks\":%" PRIu64 ",\"first_error_kind\":\"%s\","
            "\"first_error_lane\":%d,\"first_error_expected\":%" PRIu64 ",\"first_error_actual\":%" PRIu64,
            i ? "," : "", i, cpu_ids[i], slot->monotonic, s->arithmetic_verified_blocks,
            s->initial_verification_completed ? "true" : "false",
            s->periodic_verification_completed ? "true" : "false",
            s->final_verification_completed ? "true" : "false", s->error_count,
            s->affinity_applied ? "true" : "false", s->observed_cpu,
            s->interrupted_arithmetic_blocks, s->first_error_kind,
            s->first_error_lane, s->first_error_expected, s->first_error_actual);
        if (sve_progress) fprintf(progress_file, ",\"vector_length_bytes\":%d,\"active_fp32_lanes\":%d",
                                  s->sve_vl_bytes, s->sve_fp32_lanes);
        fputc('}', progress_file);
    }
    fprintf(progress_file, "],\"aggregate_verified_blocks\":%" PRIu64 "}\n", total);
    if (fflush(progress_file) != 0 || fsync(fileno(progress_file)) != 0 || ferror(progress_file)) {
        progress_io_error = 1;
        fprintf(stderr, "verified progress persistence failed: %s\n", strerror(errno));
    }
    progress_write_seconds += clock_seconds(CLOCK_MONOTONIC) - before;
}

static void handle_signal(int signum) {
    (void)signum;
    keep_running = 0;
}

static int bind_current_thread_to_cpu(int target_cpu) {
#ifdef __linux__
    if (target_cpu < 0) {
        return EINVAL;
    }
    size_t set_size = CPU_ALLOC_SIZE((size_t)target_cpu + 1U);
    cpu_set_t *set = CPU_ALLOC((size_t)target_cpu + 1U);
    if (set == NULL) {
        return ENOMEM;
    }
    CPU_ZERO_S(set_size, set);
    CPU_SET_S(target_cpu, set_size, set);
    int result = pthread_setaffinity_np(pthread_self(), set_size, set);
    CPU_FREE(set);
    return result;
#else
    (void)target_cpu;
    return ENOSYS;
#endif
}

static int bind_worker_to_cpu(int target_cpu, worker_stats_t *stats) {
    if (stats != NULL) {
        stats->affinity_target_cpu = -1;
        stats->observed_cpu = -1;
    }
#ifdef __linux__
    int affinity_result = bind_current_thread_to_cpu(target_cpu);
    if (stats != NULL) {
        stats->affinity_target_cpu = target_cpu;
        stats->affinity_attempted = 1;
        stats->affinity_applied = affinity_result == 0;
        stats->affinity_error_code = affinity_result;
        stats->observed_cpu = sched_getcpu();
    }
    return affinity_result;
#else
    (void)target_cpu;
    return ENOSYS;
#endif
}

static uint64_t checksum_u16(const uint16_t *values, int count) {
    uint64_t checksum = 0xCBF29CE484222325ULL;
    for (int i = 0; i < count; ++i) {
        checksum ^= (uint64_t)values[i] + ((uint64_t)(i + 1) << 8);
        checksum *= 0x100000001B3ULL;
    }
    return checksum;
}

static uint64_t checksum_u32(const uint32_t *values, int count) {
    uint64_t checksum = 0xCBF29CE484222325ULL;
    for (int i = 0; i < count; ++i) {
        checksum ^= (uint64_t)values[i] + ((uint64_t)(i + 1) << 16);
        checksum *= 0x100000001B3ULL;
    }
    return checksum;
}

static uint64_t checksum_f32(const float *values, int count) {
    uint64_t checksum = 0xCBF29CE484222325ULL;
    for (int i = 0; i < count; ++i) {
        union {
            float f;
            uint32_t u;
        } bits;
        bits.f = values[i];
        checksum ^= (uint64_t)bits.u + ((uint64_t)(i + 1) << 12);
        checksum *= 0x100000001B3ULL;
    }
    return checksum;
}

static void record_worker_error(worker_stats_t *stats, const char *kind, uint64_t iteration, uint64_t expected, uint64_t actual);

static void update_checksum_stats(worker_stats_t *stats, uint64_t checksum, uint64_t *last_checksum, unsigned int *repeat_count) {
    if (stats == NULL) {
        return;
    }
#ifdef __linux__
    if (stats->affinity_required && stats->affinity_applied) {
        int current_cpu = sched_getcpu();
        stats->observed_cpu = current_cpu;
        if (current_cpu < 0 || current_cpu != stats->affinity_target_cpu) {
            record_worker_error(
                stats,
                "affinity_lost",
                stats->verify_passes,
                (uint64_t)stats->affinity_target_cpu,
                current_cpu < 0 ? UINT64_MAX : (uint64_t)current_cpu
            );
            keep_running = 0;
            return;
        }
    }
#endif
    stats->verify_passes += 1;
    if (*last_checksum == checksum) {
        *repeat_count += 1U;
    } else {
    *repeat_count = 0U;
    }
    *last_checksum = checksum;
}

static void record_worker_error(worker_stats_t *stats, const char *kind, uint64_t iteration, uint64_t expected, uint64_t actual) {
    if (stats == NULL) {
        return;
    }
    stats->error_count += 1;
    if (!stats->first_error_recorded) {
        stats->first_error_recorded = 1;
        stats->first_error_iteration = iteration;
        stats->first_error_expected = expected;
        stats->first_error_actual = actual;
        snprintf(stats->first_error_kind, sizeof(stats->first_error_kind), "%s", kind != NULL ? kind : "unknown");
    }
    publish_verified_progress(stats, 1);
}

static uint64_t mul_add_mod_u64(uint64_t a, uint64_t b, uint64_t c) {
    __uint128_t wide = (__uint128_t)a * (__uint128_t)b;
    wide += (__uint128_t)c;
    return (uint64_t)wide;
}

typedef struct {
    uint64_t mul;
    uint64_t add;
} affine_lcg_t;

static affine_lcg_t compose_affine(affine_lcg_t outer, affine_lcg_t inner) {
    affine_lcg_t result;
    result.mul = mul_add_mod_u64(outer.mul, inner.mul, 0);
    result.add = mul_add_mod_u64(outer.mul, inner.add, outer.add);
    return result;
}

static affine_lcg_t pow_affine(uint64_t mul, uint64_t add, uint64_t steps) {
    affine_lcg_t result = {1ULL, 0ULL};
    affine_lcg_t base = {mul, add};
    uint64_t exponent = steps;
    while (exponent > 0) {
        if ((exponent & 1ULL) != 0ULL) {
            result = compose_affine(base, result);
        }
        exponent >>= 1U;
        if (exponent > 0) {
            base = compose_affine(base, base);
        }
    }
    return result;
}

static uint64_t cpu_canary_iterative(uint64_t state, uint64_t seed, uint64_t steps) {
    const uint64_t mul = 6364136223846793005ULL;
    const uint64_t add = 1442695040888963407ULL ^ (seed * 0x9E3779B97F4A7C15ULL);
    uint64_t value = state;
    for (uint64_t index = 0; index < steps; ++index) {
        value = mul_add_mod_u64(value, mul, add + index);
        value ^= value >> 29;
        value = mul_add_mod_u64(value, 0xBF58476D1CE4E5B9ULL, seed + index);
    }
    return value;
}

static uint64_t cpu_canary_expected(uint64_t state, uint64_t seed, uint64_t steps) {
    uint64_t value = state;
    for (uint64_t index = 0; index < steps; ++index) {
        affine_lcg_t affine = pow_affine(6364136223846793005ULL, (1442695040888963407ULL ^ (seed * 0x9E3779B97F4A7C15ULL)) + index, 1ULL);
        value = mul_add_mod_u64(affine.mul, value, affine.add);
        value ^= value >> 29;
        value = mul_add_mod_u64(value, 0xBF58476D1CE4E5B9ULL, seed + index);
    }
    return value;
}

static void run_cpu_canary(worker_stats_t *stats, uint64_t seed, uint64_t iteration, uint64_t *state) {
    if (stats == NULL || state == NULL) {
        return;
    }
    const uint64_t steps = 128ULL;
    uint64_t actual = cpu_canary_iterative(*state, seed, steps);
    uint64_t expected = cpu_canary_expected(*state, seed, steps);
    stats->canary_passes += 1;
    if (actual != expected) {
        record_worker_error(stats, "canary_mismatch", iteration, expected, actual);
    }
    *state = actual;
}

static int floats_all_finite(const float *values, int count) {
    for (int i = 0; i < count; ++i) {
        if (!isfinite(values[i])) {
            return 0;
        }
    }
    return 1;
}

static void update_float_stats(worker_stats_t *stats, const float *values, int count, uint64_t *last_checksum, unsigned int *repeat_count) {
    update_checksum_stats(stats, checksum_f32(values, count), last_checksum, repeat_count);
}

static void update_u16_stats(worker_stats_t *stats, const uint16_t *values, int count, uint64_t *last_checksum, unsigned int *repeat_count) {
    update_checksum_stats(stats, checksum_u16(values, count), last_checksum, repeat_count);
}

static void update_u32_stats(worker_stats_t *stats, const uint32_t *values, int count, uint64_t *last_checksum, unsigned int *repeat_count) {
    update_checksum_stats(stats, checksum_u32(values, count), last_checksum, repeat_count);
}

static double bound_scalar_value(double value) {
    const double limit = 8192.0;
    if (!isfinite(value)) {
        return 0.0;
    }
    if (value > limit) {
        return limit;
    }
    if (value < -limit) {
        return -limit;
    }
    return value;
}

static void run_scalar_loop(uint64_t seed, worker_stats_t *stats) {
    double a = 1.0000001192092896 + (double)(seed & 0xFFu);
    double b = 3.141592653589793 + (double)((seed >> 8) & 0xFFu);
    uint64_t last_checksum = 0;
    uint64_t canary_state = 0xC0DEC0DEC0DEC0DEULL ^ seed;
    uint64_t iteration = 0;
    unsigned int repeat_count = 0;
    while (keep_running) {
        for (int i = 0; i < 400000; ++i) {
            if ((i & 4095) == 0 && !keep_running) break;
            a = bound_scalar_value((a * 1.0000001192092896) + b);
            b = bound_scalar_value((b * 0.9999998807907104) + a);
            a = bound_scalar_value((a * b * 0.0001220703125) + 0.3333333333333333);
            b = bound_scalar_value((b * a * 0.0001220703125) + 0.6666666666666666);
        }
        if (stats != NULL) {
            float sink_values[2];
            sink_values[0] = (float)a;
            sink_values[1] = (float)b;
            update_checksum_stats(stats, checksum_f32(sink_values, 2), &last_checksum, &repeat_count);
            if (!isfinite(sink_values[0]) || !isfinite(sink_values[1])) {
                record_worker_error(stats, "non_finite", iteration, 0ULL, checksum_f32(sink_values, 2));
            }
            run_cpu_canary(stats, seed, iteration, &canary_state);
        }
        iteration += 1ULL;
    }
    volatile double sink = a + b;
    (void)sink;
}

static const char *mode_name(stress_mode_t mode) {
    switch (mode) {
        case MODE_SSE:
            return "sse";
        case MODE_AVX:
            return "avx";
        case MODE_AVX2:
            return "avx2";
        case MODE_AVX512:
            return "avx512";
        case MODE_NEON:
            return "neon";
        case MODE_SVE:
            return "sve";
        case MODE_AUTO:
            return "auto";
        case MODE_SCALAR:
        default:
            return "scalar";
    }
}

static const char *kernel_flavor_name(kernel_flavor_t flavor) {
    switch (flavor) {
        case KERNEL_SSE2:
            return "sse2";
        case KERNEL_SSE2_INT:
            return "sse2_int";
        case KERNEL_AVX:
            return "avx";
        case KERNEL_AVX_FMA:
            return "avx_fma";
        case KERNEL_AVX2:
            return "avx2";
        case KERNEL_AVX2_FMA:
            return "avx2_fma";
        case KERNEL_AVX512_FMA:
            return "avx512_fma";
        case KERNEL_AVX512_INT:
            return "avx512_int";
        case KERNEL_NEON:
            return "neon";
        case KERNEL_NEON_FP32_FMA:
            return "neon_fp32_fma";
        case KERNEL_SVE_FP32_FMA:
            return "sve_fp32_fma";
        case KERNEL_UNSPECIFIED:
            return "";
        case KERNEL_SCALAR:
        default:
            return "scalar";
    }
}

#if defined(__x86_64__) || defined(__i386__)
__attribute__((target("sse2")))
static void run_sse_loop(uint32_t seed, worker_stats_t *stats) {
    __m128 v0 = _mm_set_ps(1.0f + seed, 2.0f, 3.0f, 4.0f);
    __m128 v1 = _mm_set_ps(4.0f, 3.0f + seed, 2.0f, 1.0f);
    __m128 mul = _mm_set1_ps(1.000013f);
    __m128 add = _mm_set1_ps(0.000331f);
    __m128 hi = _mm_set1_ps(256.0f);
    __m128 lo = _mm_set1_ps(-256.0f);
    float sink[4] __attribute__((aligned(16)));
    uint64_t last_checksum = 0;
    uint64_t canary_state = 0x13579BDF2468ACE0ULL ^ seed;
    uint64_t iteration = 0;
    unsigned int repeat_count = 0;
    while (keep_running) {
        for (int i = 0; i < 200000; ++i) {
            if ((i & 4095) == 0 && !keep_running) break;
            v0 = _mm_add_ps(_mm_mul_ps(v0, mul), add);
            v1 = _mm_add_ps(_mm_mul_ps(v1, mul), v0);
            v0 = _mm_sub_ps(_mm_mul_ps(v0, v1), add);
            v1 = _mm_add_ps(_mm_mul_ps(v1, mul), v0);
            v0 = _mm_max_ps(lo, _mm_min_ps(hi, v0));
            v1 = _mm_max_ps(lo, _mm_min_ps(hi, v1));
        }
        _mm_storeu_ps(sink, _mm_add_ps(v0, v1));
        vector_sink_u64 ^= (uint64_t)sink[0];
        update_float_stats(stats, sink, 4, &last_checksum, &repeat_count);
        if (!floats_all_finite(sink, 4)) {
            record_worker_error(stats, "non_finite", iteration, 0ULL, checksum_f32(sink, 4));
        }
        run_cpu_canary(stats, seed, iteration, &canary_state);
        iteration += 1ULL;
    }
    _mm_storeu_ps(sink, _mm_add_ps(v0, v1));
    vector_sink_u64 ^= (uint64_t)sink[1];
}

__attribute__((target("sse2")))
static void run_sse2_int_loop(uint32_t seed, worker_stats_t *stats) {
    __m128i v0 = _mm_set_epi16(
        1 + (int16_t)(seed & 0x7FFFu), 2, 3, 4, 5, 6, 7, 8
    );
    __m128i v1 = _mm_set_epi16(
        8, 7 + (int16_t)((seed >> 1) & 0x7FFFu), 6, 5, 4, 3, 2, 1
    );
    __m128i mul = _mm_set1_epi16(257);
    __m128i add = _mm_set1_epi16(8191);
    uint16_t sink[8] __attribute__((aligned(16)));
    uint64_t last_checksum = 0;
    uint64_t canary_state = 0x0F1E2D3C4B5A6978ULL ^ seed;
    uint64_t iteration = 0;
    unsigned int repeat_count = 0;
    while (keep_running) {
        for (int i = 0; i < 260000; ++i) {
            if ((i & 4095) == 0 && !keep_running) break;
            v0 = _mm_add_epi16(_mm_mullo_epi16(v0, mul), add);
            v1 = _mm_xor_si128(_mm_add_epi16(_mm_mullo_epi16(v1, mul), add), v0);
            v0 = _mm_add_epi16(v0, _mm_slli_epi16(v1, 1));
            v1 = _mm_xor_si128(v1, _mm_srli_epi16(v0, 3));
        }
        _mm_storeu_si128((__m128i *)sink, _mm_add_epi16(v0, v1));
        vector_sink_u64 ^= (uint64_t)sink[0];
        update_u16_stats(stats, sink, 8, &last_checksum, &repeat_count);
        run_cpu_canary(stats, seed, iteration, &canary_state);
        iteration += 1ULL;
    }
    _mm_storeu_si128((__m128i *)sink, _mm_add_epi16(v0, v1));
    vector_sink_u64 ^= (uint64_t)sink[1];
}

__attribute__((target("avx")))
static void run_avx_loop(uint32_t seed, worker_stats_t *stats) {
    __m256 v0 = _mm256_set_ps(1.0f + seed, 2.0f, 3.0f, 4.0f, 5.0f, 6.0f, 7.0f, 8.0f);
    __m256 v1 = _mm256_set_ps(8.0f, 7.0f + seed, 6.0f, 5.0f, 4.0f, 3.0f, 2.0f, 1.0f);
    __m256 mul = _mm256_set1_ps(1.000021f);
    __m256 add = _mm256_set1_ps(0.000173f);
    __m256 hi = _mm256_set1_ps(256.0f);
    __m256 lo = _mm256_set1_ps(-256.0f);
    float sink[8] __attribute__((aligned(32)));
    uint64_t last_checksum = 0;
    uint64_t canary_state = 0x1122334455667788ULL ^ seed;
    uint64_t iteration = 0;
    unsigned int repeat_count = 0;
    while (keep_running) {
        for (int i = 0; i < 240000; ++i) {
            if ((i & 4095) == 0 && !keep_running) break;
            v0 = _mm256_add_ps(_mm256_mul_ps(v0, mul), add);
            v1 = _mm256_add_ps(_mm256_mul_ps(v1, mul), v0);
            v0 = _mm256_sub_ps(_mm256_mul_ps(v0, v1), add);
            v1 = _mm256_add_ps(_mm256_mul_ps(v1, mul), v0);
            v0 = _mm256_max_ps(lo, _mm256_min_ps(hi, v0));
            v1 = _mm256_max_ps(lo, _mm256_min_ps(hi, v1));
        }
        _mm256_storeu_ps(sink, _mm256_add_ps(v0, v1));
        vector_sink_u64 ^= (uint64_t)sink[0];
        update_float_stats(stats, sink, 8, &last_checksum, &repeat_count);
        if (!floats_all_finite(sink, 8)) {
            record_worker_error(stats, "non_finite", iteration, 0ULL, checksum_f32(sink, 8));
        }
        run_cpu_canary(stats, seed, iteration, &canary_state);
        iteration += 1ULL;
    }
    _mm256_storeu_ps(sink, _mm256_add_ps(v0, v1));
    vector_sink_u64 ^= (uint64_t)sink[1];
}

__attribute__((target("avx,fma")))
static void run_avx_fma_loop(uint32_t seed, worker_stats_t *stats) {
    __m256 a = _mm256_set1_ps(0.001f * (float)(seed + 1));
    __m256 b = _mm256_set_ps(0.31f, 0.29f, 0.23f, 0.19f, 0.17f, 0.13f, 0.11f, 0.07f);
    __m256 c = _mm256_set_ps(0.53f, 0.47f, 0.43f, 0.41f, 0.37f, 0.31f, 0.29f, 0.23f);
    __m256 d = _mm256_set_ps(0.97f, 0.89f, 0.83f, 0.79f, 0.73f, 0.71f, 0.67f, 0.61f);
    __m256 mul0 = _mm256_set1_ps(1.000021f);
    __m256 mul1 = _mm256_set1_ps(0.999979f);
    __m256 bias0 = _mm256_set1_ps(0.000091f);
    __m256 bias1 = _mm256_set1_ps(-0.000067f);
    __m256 hi = _mm256_set1_ps(256.0f);
    __m256 lo = _mm256_set1_ps(-256.0f);
    float sink[8] __attribute__((aligned(32)));
    uint64_t last_checksum = 0;
    uint64_t canary_state = 0x8877665544332211ULL ^ seed;
    uint64_t iteration = 0;
    unsigned int repeat_count = 0;
    while (keep_running) {
        for (int i = 0; i < 220000; ++i) {
            if ((i & 4095) == 0 && !keep_running) break;
            a = _mm256_fmadd_ps(a, mul0, b);
            b = _mm256_fmadd_ps(b, mul1, c);
            c = _mm256_fmadd_ps(c, mul0, d);
            d = _mm256_fmadd_ps(d, mul1, a);
            a = _mm256_add_ps(a, bias0);
            b = _mm256_add_ps(b, bias1);
            c = _mm256_sub_ps(c, bias1);
            d = _mm256_sub_ps(d, bias0);
            a = _mm256_max_ps(lo, _mm256_min_ps(hi, a));
            b = _mm256_max_ps(lo, _mm256_min_ps(hi, b));
            c = _mm256_max_ps(lo, _mm256_min_ps(hi, c));
            d = _mm256_max_ps(lo, _mm256_min_ps(hi, d));
        }
        _mm256_storeu_ps(sink, _mm256_add_ps(_mm256_add_ps(a, b), _mm256_add_ps(c, d)));
        vector_sink_u64 ^= (uint64_t)sink[0];
        update_float_stats(stats, sink, 8, &last_checksum, &repeat_count);
        if (!floats_all_finite(sink, 8)) {
            record_worker_error(stats, "non_finite", iteration, 0ULL, checksum_f32(sink, 8));
        }
        run_cpu_canary(stats, seed, iteration, &canary_state);
        iteration += 1ULL;
    }
    _mm256_storeu_ps(sink, _mm256_add_ps(_mm256_add_ps(a, b), _mm256_add_ps(c, d)));
    vector_sink_u64 ^= (uint64_t)sink[1];
}

__attribute__((target("avx2")))
static void run_avx2_loop(uint32_t seed, worker_stats_t *stats) {
    __m256i v0 = _mm256_set_epi32(
        1 + (int)seed, 2, 3, 4, 5, 6, 7, 8
    );
    __m256i v1 = _mm256_set_epi32(
        8, 7 + (int)seed, 6, 5, 4, 3, 2, 1
    );
    __m256i mul = _mm256_set1_epi32(1664525);
    __m256i add = _mm256_set1_epi32(1013904223);
    uint32_t sink[8] __attribute__((aligned(32)));
    uint64_t last_checksum = 0;
    uint64_t canary_state = 0x55AA55AA33CC33CCULL ^ seed;
    uint64_t iteration = 0;
    unsigned int repeat_count = 0;
    while (keep_running) {
        for (int i = 0; i < 300000; ++i) {
            if ((i & 4095) == 0 && !keep_running) break;
            v0 = _mm256_add_epi32(_mm256_mullo_epi32(v0, mul), add);
            v1 = _mm256_xor_si256(_mm256_add_epi32(_mm256_mullo_epi32(v1, mul), add), v0);
            v0 = _mm256_add_epi32(v0, _mm256_slli_epi32(v1, 1));
            v1 = _mm256_xor_si256(v1, _mm256_srli_epi32(v0, 3));
        }
        _mm256_storeu_si256((__m256i *)sink, _mm256_add_epi32(v0, v1));
        vector_sink_u64 ^= (uint64_t)sink[0];
        update_u32_stats(stats, sink, 8, &last_checksum, &repeat_count);
        run_cpu_canary(stats, seed, iteration, &canary_state);
        iteration += 1ULL;
    }
    _mm256_storeu_si256((__m256i *)sink, _mm256_add_epi32(v0, v1));
    vector_sink_u64 ^= (uint64_t)sink[1];
}

__attribute__((target("avx2,fma")))
static void run_avx2_fma_loop(uint32_t seed, worker_stats_t *stats) {
    __m256 a = _mm256_set1_ps(0.001f * (float)(seed + 1));
    __m256 b = _mm256_set_ps(0.31f, 0.29f, 0.23f, 0.19f, 0.17f, 0.13f, 0.11f, 0.07f);
    __m256 c = _mm256_set_ps(0.53f, 0.47f, 0.43f, 0.41f, 0.37f, 0.31f, 0.29f, 0.23f);
    __m256 d = _mm256_set_ps(0.97f, 0.89f, 0.83f, 0.79f, 0.73f, 0.71f, 0.67f, 0.61f);
    __m256 mul0 = _mm256_set1_ps(1.000031f);
    __m256 mul1 = _mm256_set1_ps(0.999971f);
    __m256 bias0 = _mm256_set1_ps(0.000113f);
    __m256 bias1 = _mm256_set1_ps(-0.000087f);
    __m256 hi = _mm256_set1_ps(256.0f);
    __m256 lo = _mm256_set1_ps(-256.0f);
    float sink[8] __attribute__((aligned(32)));
    uint64_t last_checksum = 0;
    uint64_t canary_state = 0xCAFEBABE10203040ULL ^ seed;
    uint64_t iteration = 0;
    unsigned int repeat_count = 0;
    while (keep_running) {
        for (int i = 0; i < 220000; ++i) {
            if ((i & 4095) == 0 && !keep_running) break;
            a = _mm256_fmadd_ps(a, mul0, b);
            b = _mm256_fmadd_ps(b, mul1, c);
            c = _mm256_fmadd_ps(c, mul0, d);
            d = _mm256_fmadd_ps(d, mul1, a);
            a = _mm256_add_ps(a, bias0);
            b = _mm256_add_ps(b, bias1);
            c = _mm256_sub_ps(c, bias1);
            d = _mm256_sub_ps(d, bias0);
            a = _mm256_max_ps(lo, _mm256_min_ps(hi, a));
            b = _mm256_max_ps(lo, _mm256_min_ps(hi, b));
            c = _mm256_max_ps(lo, _mm256_min_ps(hi, c));
            d = _mm256_max_ps(lo, _mm256_min_ps(hi, d));
        }
        _mm256_storeu_ps(sink, _mm256_add_ps(_mm256_add_ps(a, b), _mm256_add_ps(c, d)));
        vector_sink_u64 ^= (uint64_t)sink[0];
        update_float_stats(stats, sink, 8, &last_checksum, &repeat_count);
        if (!floats_all_finite(sink, 8)) {
            record_worker_error(stats, "non_finite", iteration, 0ULL, checksum_f32(sink, 8));
        }
        run_cpu_canary(stats, seed, iteration, &canary_state);
        iteration += 1ULL;
    }
    _mm256_storeu_ps(sink, _mm256_add_ps(_mm256_add_ps(a, b), _mm256_add_ps(c, d)));
    vector_sink_u64 ^= (uint64_t)sink[1];
}

__attribute__((target("avx512f")))
static void run_avx512_loop(uint32_t seed, worker_stats_t *stats) {
    __m512 a = _mm512_set1_ps(0.001f * (float)(seed + 1));
    __m512 b = _mm512_set_ps(
        0.31f, 0.29f, 0.23f, 0.19f, 0.17f, 0.13f, 0.11f, 0.07f,
        0.61f, 0.59f, 0.53f, 0.47f, 0.43f, 0.41f, 0.37f, 0.31f
    );
    __m512 c = _mm512_set_ps(
        0.97f, 0.89f, 0.83f, 0.79f, 0.73f, 0.71f, 0.67f, 0.61f,
        0.57f, 0.53f, 0.47f, 0.43f, 0.41f, 0.37f, 0.31f, 0.29f
    );
    __m512 d = _mm512_set_ps(
        0.21f, 0.22f, 0.24f, 0.26f, 0.28f, 0.32f, 0.34f, 0.36f,
        0.38f, 0.42f, 0.44f, 0.46f, 0.48f, 0.52f, 0.54f, 0.56f
    );
    __m512 mul0 = _mm512_set1_ps(1.000041f);
    __m512 mul1 = _mm512_set1_ps(0.999959f);
    __m512 bias0 = _mm512_set1_ps(0.000091f);
    __m512 bias1 = _mm512_set1_ps(-0.000073f);
    __m512 hi = _mm512_set1_ps(256.0f);
    __m512 lo = _mm512_set1_ps(-256.0f);
    float sink[16] __attribute__((aligned(64)));
    uint64_t last_checksum = 0;
    uint64_t canary_state = 0x123456789ABCDEF0ULL ^ seed;
    uint64_t iteration = 0;
    unsigned int repeat_count = 0;
    while (keep_running) {
        for (int i = 0; i < 240000; ++i) {
            if ((i & 4095) == 0 && !keep_running) break;
            a = _mm512_fmadd_ps(a, mul0, b);
            b = _mm512_fmadd_ps(b, mul1, c);
            c = _mm512_fmadd_ps(c, mul0, d);
            d = _mm512_fmadd_ps(d, mul1, a);
            a = _mm512_add_ps(a, bias0);
            b = _mm512_add_ps(b, bias1);
            c = _mm512_sub_ps(c, bias1);
            d = _mm512_sub_ps(d, bias0);
            a = _mm512_max_ps(lo, _mm512_min_ps(hi, a));
            b = _mm512_max_ps(lo, _mm512_min_ps(hi, b));
            c = _mm512_max_ps(lo, _mm512_min_ps(hi, c));
            d = _mm512_max_ps(lo, _mm512_min_ps(hi, d));
        }
        _mm512_storeu_ps(sink, _mm512_add_ps(_mm512_add_ps(a, b), _mm512_add_ps(c, d)));
        vector_sink_u64 ^= (uint64_t)sink[0];
        update_float_stats(stats, sink, 16, &last_checksum, &repeat_count);
        if (!floats_all_finite(sink, 16)) {
            record_worker_error(stats, "non_finite", iteration, 0ULL, checksum_f32(sink, 16));
        }
        run_cpu_canary(stats, seed, iteration, &canary_state);
        iteration += 1ULL;
    }
    _mm512_storeu_ps(sink, _mm512_add_ps(_mm512_add_ps(a, b), _mm512_add_ps(c, d)));
    vector_sink_u64 ^= (uint64_t)sink[1];
}

__attribute__((target("avx512f")))
static void run_avx512_int_loop(uint32_t seed, worker_stats_t *stats) {
    __m512i v0 = _mm512_set_epi32(
        1 + (int)seed, 2, 3, 4, 5, 6, 7, 8,
        9, 10, 11, 12, 13, 14, 15, 16
    );
    __m512i v1 = _mm512_set_epi32(
        16, 15, 14, 13, 12, 11, 10, 9,
        8, 7 + (int)seed, 6, 5, 4, 3, 2, 1
    );
    __m512i add = _mm512_set1_epi32(0x9E3779B9u);
    __m512i mix = _mm512_set1_epi32(0x85EBCA6Bu);
    uint32_t sink[16] __attribute__((aligned(64)));
    uint64_t last_checksum = 0;
    uint64_t canary_state = 0x0BADF00DDEADBEEFULL ^ seed;
    uint64_t iteration = 0;
    unsigned int repeat_count = 0;
    while (keep_running) {
        for (int i = 0; i < 280000; ++i) {
            if ((i & 4095) == 0 && !keep_running) break;
            v0 = _mm512_add_epi32(v0, add);
            v1 = _mm512_xor_si512(_mm512_add_epi32(v1, mix), v0);
            v0 = _mm512_add_epi32(v0, _mm512_slli_epi32(v1, 1));
            v1 = _mm512_xor_si512(v1, _mm512_srli_epi32(v0, 3));
        }
        _mm512_storeu_si512((__m512i *)sink, _mm512_add_epi32(v0, v1));
        vector_sink_u64 ^= (uint64_t)sink[0];
        update_u32_stats(stats, sink, 16, &last_checksum, &repeat_count);
        run_cpu_canary(stats, seed, iteration, &canary_state);
        iteration += 1ULL;
    }
    _mm512_storeu_si512((__m512i *)sink, _mm512_add_epi32(v0, v1));
    vector_sink_u64 ^= (uint64_t)sink[1];
}
#endif

#if defined(__aarch64__) && defined(__linux__)
static void run_neon_loop(uint32_t seed, worker_stats_t *stats) {
    uint32x4_t v0 = {1U + seed, 2U, 3U, 4U};
    uint32x4_t v1 = {5U, 6U + seed, 7U, 8U};
    uint32x4_t v2 = {9U, 10U, 11U + seed, 12U};
    uint32x4_t v3 = {13U, 14U, 15U, 16U + seed};
    const uint32x4_t mul = vdupq_n_u32(1664525U);
    const uint32x4_t add = vdupq_n_u32(1013904223U);
    const uint32x4_t mix = vdupq_n_u32(0x9E3779B9U);
    uint32_t sink[16] __attribute__((aligned(16)));
    uint64_t last_checksum = 0;
    uint64_t canary_state = 0xA51DA51D5A1D5A1DULL ^ seed;
    uint64_t iteration = 0;
    unsigned int repeat_count = 0;
    while (keep_running) {
        for (int i = 0; i < 300000; ++i) {
            if ((i & 4095) == 0 && !keep_running) break;
            v0 = vaddq_u32(vmulq_u32(v0, mul), add);
            v1 = veorq_u32(vaddq_u32(vmulq_u32(v1, mul), mix), v0);
            v2 = vaddq_u32(vmulq_u32(v2, mul), vshlq_n_u32(v1, 1));
            v3 = veorq_u32(vaddq_u32(v3, mix), vshrq_n_u32(v2, 3));
            v0 = veorq_u32(v0, v3);
            v2 = vaddq_u32(v2, v1);
        }
        vst1q_u32(&sink[0], v0);
        vst1q_u32(&sink[4], v1);
        vst1q_u32(&sink[8], v2);
        vst1q_u32(&sink[12], v3);
        vector_sink_u64 ^= (uint64_t)sink[0];
        update_u32_stats(stats, sink, 16, &last_checksum, &repeat_count);
        run_cpu_canary(stats, seed, iteration, &canary_state);
        iteration += 1ULL;
    }
    vst1q_u32(&sink[0], vaddq_u32(v0, v2));
    vector_sink_u64 ^= (uint64_t)sink[1];
}
#endif

#define FP32_FMA_CASES 4
#define FP32_FMA_LANES 32
#define FP32_FMA_ROUNDS 256

#if (defined(__aarch64__) && defined(__linux__)) || defined(LVS_CPU_HELPER_TEST_FP32_FMA) || defined(LVS_CPU_HELPER_TEST_FP32_REFERENCE) || defined(LVS_CPU_HELPER_TEST_SVE)
/* Exact integer binary32 fused reference for the bounded finite operand domain
 * below. No host floating-point arithmetic, tolerance, or duplicated SIMD.
 * Unsupported exponent alignments are rejected rather than approximated. */
static int fp32_fma_reference(uint32_t a, uint32_t b, uint32_t c, uint32_t *output) {
#if defined(__SIZEOF_INT128__)
    unsigned ae = (a >> 23) & 255U, be = (b >> 23) & 255U, ce = (c >> 23) & 255U;
    if (ae == 255U || be == 255U || ce == 255U) return 0;
    uint64_t am = (a & 0x7fffffU) | (ae ? 0x800000U : 0U);
    uint64_t bm = (b & 0x7fffffU) | (be ? 0x800000U : 0U);
    uint64_t cm = (c & 0x7fffffU) | (ce ? 0x800000U : 0U);
    uint64_t pm = am * bm;
    int pe = (ae ? (int)ae - 150 : -149) + (be ? (int)be - 150 : -149);
    int add_e = ce ? (int)ce - 150 : -149;
    if (!pm) pe = add_e;
    if (!cm) add_e = pe;
    int common = pe < add_e ? pe : add_e;
    int ps = pe - common, cs = add_e - common;
    if (ps > 72 || cs > 96) return 0; /* <= 120 significant bits */
    __uint128_t product = (__uint128_t)pm << ps, addend = (__uint128_t)cm << cs;
    unsigned product_sign = (a ^ b) >> 31, add_sign = c >> 31;
    unsigned sign = product_sign;
    __uint128_t magnitude;
    if (product_sign == add_sign) magnitude = product + addend;
    else if (product >= addend) magnitude = product - addend;
    else { magnitude = addend - product; sign = add_sign; }
    if (!magnitude) { *output = product_sign == add_sign ? sign << 31 : 0U; return 1; }
    int bits = 0;
    for (__uint128_t v = magnitude; v; v >>= 1) ++bits;
    int exponent = common + bits - 1;
    int shift = bits - 24;
    if (exponent < -126) shift = -149 - common;
    __uint128_t rounded;
    if (shift > 0) {
        if (shift >= 128) return 0;
        rounded = magnitude >> shift;
        __uint128_t remainder = magnitude & (((__uint128_t)1 << shift) - 1);
        __uint128_t half = (__uint128_t)1 << (shift - 1);
        if (remainder > half || (remainder == half && (rounded & 1))) ++rounded;
    } else rounded = magnitude << -shift;
    if (exponent < -126) {
        *output = (sign << 31) | (uint32_t)rounded;
        return 1;
    }
    if (rounded >= 0x1000000U) { rounded >>= 1; ++exponent; }
    *output = (sign << 31) | (exponent > 127 ? 0x7f800000U :
        ((uint32_t)(exponent + 127) << 23) | ((uint32_t)rounded & 0x7fffffU));
    return 1;
#else
    /* Unrelated legacy helpers still build on targets without uint128. The
     * new kernel is only advertised on Linux AArch64, which supplies uint128. */
    (void)a; (void)b; (void)c; (void)output;
    return 0;
#endif
}

typedef struct {
    uint32_t initial[FP32_FMA_LANES];
    uint32_t multiplier[FP32_FMA_LANES];
    uint32_t addend[FP32_FMA_LANES];
    uint32_t expected[FP32_FMA_LANES];
} fp32_fma_case_t;

static const uint32_t fp32_witness_a[4] = {0x3f800001U, 0x3f800800U, 0x3f800001U, 0xbf800001U};
static const uint32_t fp32_witness_b[4] = {0x3f7ffffeU, 0x3f7ff000U, 0x3f000000U, 0x3f7ffffeU};
static const uint32_t fp32_witness_c[4] = {0xbf800000U, 0xbf800000U, 0x3f800000U, 0x3f800000U};
/* -2^-46, -2^-24, ties-to-even 1.5, +2^-46. */
static const uint32_t fp32_witness_expected[4] = {0xa8800000U, 0xb3800000U, 0x3fc00000U, 0x28800000U};

static int prepare_fp32_fma_cases(fp32_fma_case_t *cases, uint32_t seed) {
    for (int k = 0; k < FP32_FMA_CASES; ++k) {
        for (int lane = 0; lane < FP32_FMA_LANES; ++lane) {
            uint32_t mix = (seed * 1664525U + (uint32_t)(lane * 1013904223U) + (uint32_t)k * 69069U);
            cases[k].initial[lane] = 0x3f000000U | (mix & 0x3fffffU);
            cases[k].multiplier[lane] = 0x3f7f0000U | ((mix >> 5) & 0xffffU);
            cases[k].addend[lane] = 0x3a800000U | ((mix >> 9) & 0x3fffffU) | ((lane & 1) ? 0x80000000U : 0U);
            uint32_t value = cases[k].initial[lane];
            for (int i = 0; i < FP32_FMA_ROUNDS; ++i) {
                if (!fp32_fma_reference(value, cases[k].multiplier[lane], cases[k].addend[lane], &value)) return 0;
            }
            cases[k].expected[lane] = value;
        }
    }
    return 1;
}

static int verify_fp32_fma_lanes(worker_stats_t *stats, const uint32_t *actual,
                                 const uint32_t *expected, int count, uint64_t block) {
    for (int lane = 0; lane < count; ++lane) {
        if (((actual[lane] >> 23) & 255U) == 255U || actual[lane] != expected[lane]) {
            if (!stats->first_error_recorded) stats->first_error_lane = lane;
            record_worker_error(stats, "fp32_fma_mismatch", block, expected[lane], actual[lane]);
            keep_running = 0;
            return 0;
        }
    }
    return 1;
}

static int fp32_environment_supported(uint64_t fpcr) {
    /* RN ties-even, no FP32 flush-to-zero, and no enabled exception traps.
     * Sticky exception flags (FPSR), including ordinary inexact, are allowed. */
    return (fpcr & ((3ULL << 22) | (1ULL << 24) | (31ULL << 8) | (1ULL << 15))) == 0;
}

static int fp32_check_affinity(worker_stats_t *stats) {
    int observed = sched_getcpu();
    stats->observed_cpu = observed;
    if (observed == stats->affinity_target_cpu && stats->affinity_applied) return 1;
    record_worker_error(stats, "affinity_lost", stats->arithmetic_verified_blocks,
                        stats->affinity_target_cpu, observed < 0 ? UINT64_MAX : (uint64_t)observed);
    keep_running = 0;
    return 0;
}

#if (defined(__aarch64__) && defined(__linux__)) || defined(LVS_CPU_HELPER_TEST_FP32_FMA)
/* Test builds exercise lifecycle/verifier logic with an explicitly labelled
 * integer emulation. They never establish ARM instruction execution. */
__attribute__((noinline))
static int execute_fp32_fma_block(const fp32_fma_case_t *input, uint32_t *output, int final) {
#if defined(LVS_CPU_HELPER_TEST_FP32_FMA)
#if defined(LVS_CPU_HELPER_TEST_INTERRUPT_FP32_BLOCK)
    static _Thread_local unsigned int test_calls;
    if (!final && ++test_calls == 3) { keep_running = 0; return 0; }
#endif
    memcpy(output, input->initial, sizeof(input->initial));
    for (int i = 0; i < FP32_FMA_ROUNDS; ++i) {
        if (!final && !keep_running) return 0;
        for (int lane = 0; lane < FP32_FMA_LANES; ++lane) {
            if (!fp32_fma_reference(output[lane], input->multiplier[lane], input->addend[lane], &output[lane])) return -1;
        }
    }
#else
    float initial[32], multiplier[32], addend[32], result[32];
    memcpy(initial, input->initial, sizeof(initial));
    memcpy(multiplier, input->multiplier, sizeof(multiplier));
    memcpy(addend, input->addend, sizeof(addend));
#define LOAD_CHAIN(N) float32x4_t x##N = vld1q_f32(initial + 4*N); \
    float32x4_t a##N = vld1q_f32(multiplier + 4*N); \
    float32x4_t b##N = vld1q_f32(addend + 4*N)
    LOAD_CHAIN(0); LOAD_CHAIN(1); LOAD_CHAIN(2); LOAD_CHAIN(3);
    LOAD_CHAIN(4); LOAD_CHAIN(5); LOAD_CHAIN(6); LOAD_CHAIN(7);
#undef LOAD_CHAIN
    for (int i = 0; i < FP32_FMA_ROUNDS; ++i) {
        if ((i & 31) == 0 && !final && !keep_running) return 0;
        x0 = vfmaq_f32(b0, x0, a0); x1 = vfmaq_f32(b1, x1, a1);
        x2 = vfmaq_f32(b2, x2, a2); x3 = vfmaq_f32(b3, x3, a3);
        x4 = vfmaq_f32(b4, x4, a4); x5 = vfmaq_f32(b5, x5, a5);
        x6 = vfmaq_f32(b6, x6, a6); x7 = vfmaq_f32(b7, x7, a7);
        /* Compiler barrier only: retain every dependent arithmetic step. */
        __asm__ volatile("" : "+w"(x0), "+w"(x1), "+w"(x2), "+w"(x3),
                             "+w"(x4), "+w"(x5), "+w"(x6), "+w"(x7));
    }
#define STORE_CHAIN(N) vst1q_f32(result + 4*N, x##N)
    STORE_CHAIN(0); STORE_CHAIN(1); STORE_CHAIN(2); STORE_CHAIN(3);
    STORE_CHAIN(4); STORE_CHAIN(5); STORE_CHAIN(6); STORE_CHAIN(7);
#undef STORE_CHAIN
    memcpy(output, result, sizeof(result));
#endif
#if defined(LVS_CPU_HELPER_TEST_CORRUPT_FP32_LANE)
    output[17] ^= 1U;
#elif defined(LVS_CPU_HELPER_TEST_NONFINITE_FP32_LANE)
    output[31] = 0x7f800000U;
#endif
    return 1;
}

static void run_neon_fp32_fma_loop(uint32_t seed, worker_stats_t *stats) {
    fp32_fma_case_t cases[FP32_FMA_CASES];
    uint32_t actual[FP32_FMA_LANES], witness[4];
#if defined(__aarch64__) && !defined(LVS_CPU_HELPER_TEST_FP32_FMA)
    __asm__ volatile("mrs %0, fpcr" : "=r"(stats->fpcr));
    if (!fp32_environment_supported(stats->fpcr)) {
        record_worker_error(stats, "fp_environment", 0, 0, stats->fpcr);
        keep_running = 0;
        return;
    }
#endif
    if (!prepare_fp32_fma_cases(cases, seed)) {
        record_worker_error(stats, "fp32_reference_domain", 0, 0, 0);
        keep_running = 0;
        return;
    }
    int final = 0;
    for (;;) {
        if (!keep_running) {
            if (stats->error_count || !stats->initial_verification_completed) break;
            final = 1;
        }
        if (!fp32_check_affinity(stats)) break;
        unsigned k = (unsigned)((stats->arithmetic_verified_blocks + seed) % FP32_FMA_CASES);
        int completed = execute_fp32_fma_block(&cases[k], actual, final);
        if (completed == 0) { ++stats->interrupted_arithmetic_blocks; continue; }
        if (completed < 0) {
            record_worker_error(stats, "fp32_reference_failed", stats->arithmetic_verified_blocks, 1, 0);
            keep_running = 0;
            break;
        }
        if (!verify_fp32_fma_lanes(stats, actual, cases[k].expected, FP32_FMA_LANES, stats->arithmetic_verified_blocks)) break;
#if defined(LVS_CPU_HELPER_TEST_FP32_FMA)
        for (int lane = 0; lane < 4; ++lane) {
            fp32_fma_reference(fp32_witness_a[lane], fp32_witness_b[lane], fp32_witness_c[lane], &witness[lane]);
        }
#if defined(LVS_CPU_HELPER_TEST_UNFUSED_FP32)
        uint32_t product;
        fp32_fma_reference(fp32_witness_a[0], fp32_witness_b[0], 0, &product);
        fp32_fma_reference(product, 0x3f800000U, fp32_witness_c[0], &witness[0]);
#endif
#else
        float wa[4], wb[4], wc[4], wr[4];
        memcpy(wa, fp32_witness_a, sizeof(wa)); memcpy(wb, fp32_witness_b, sizeof(wb)); memcpy(wc, fp32_witness_c, sizeof(wc));
        float32x4_t va = vld1q_f32(wa), vb = vld1q_f32(wb), vc = vld1q_f32(wc);
        __asm__ volatile("" : "+w"(va), "+w"(vb), "+w"(vc));
        vst1q_f32(wr, vfmaq_f32(vc, va, vb)); memcpy(witness, wr, sizeof(witness));
#endif
        if (!verify_fp32_fma_lanes(stats, witness, fp32_witness_expected, 4, stats->arithmetic_verified_blocks)) break;
        if (!fp32_check_affinity(stats)) break;
        if (stats->arithmetic_verified_blocks == UINT64_MAX) {
            record_worker_error(stats, "fp32_counter_overflow", UINT64_MAX, 0, 0);
            keep_running = 0;
            break;
        }
        ++stats->arithmetic_verified_blocks;
        ++stats->verify_passes;
        if (final) {
            stats->final_verification_completed = 1;
            publish_verified_progress(stats, 1);
            break;
        }
        int initial = !stats->initial_verification_completed;
        if (initial) stats->initial_verification_completed = 1;
        else stats->periodic_verification_completed = 1;
        publish_verified_progress(stats, initial);
    }
}
#endif
#endif

static int cpu_supports_sve_fp32_fma(void) {
#if defined(LVS_CPU_HELPER_TEST_DISABLE_FP) || defined(LVS_CPU_HELPER_TEST_DISABLE_SVE)
    return 0;
#elif defined(LVS_CPU_HELPER_TEST_SVE)
    return 1;
#elif defined(LVS_CPU_HELPER_ENABLE_SVE) && defined(__aarch64__) && defined(__linux__)
    unsigned long hwcap = getauxval(AT_HWCAP);
    return (hwcap & (HWCAP_FP | HWCAP_SVE)) == (HWCAP_FP | HWCAP_SVE);
#else
    return 0;
#endif
}

static void print_isa_capabilities(void) {
    printf("{\"source\":\"%s\",\"sve_compiled\":%s,",
#if defined(__aarch64__) && defined(__linux__)
           "linux_getauxval_common_set",
#else
           "unsupported_architecture",
#endif
#if defined(LVS_CPU_HELPER_ENABLE_SVE) && defined(__aarch64__) && defined(__linux__)
           "true"
#else
           "false"
#endif
    );
#if defined(__aarch64__) && defined(__linux__)
    printf("\"hwcap\":%lu,", getauxval(AT_HWCAP));
    errno = 0;
    unsigned long hwcap2 = getauxval(AT_HWCAP2);
    if (errno) printf("\"hwcap2\":null,\"hwcap2_errno\":%d,", errno);
    else printf("\"hwcap2\":%lu,\"hwcap2_errno\":0,", hwcap2);
    if ((getauxval(AT_HWCAP) & HWCAP_SVE) != 0) {
        errno = 0;
        int vl = prctl(PR_SVE_GET_VL, 0UL, 0UL, 0UL, 0UL);
        if (vl < 0) printf("\"current_vector_length_bytes\":null,\"vector_length_errno\":%d", errno);
        else printf("\"current_vector_length_bytes\":%d,\"vector_length_flags\":%d,\"vector_length_errno\":0", vl & PR_SVE_VL_LEN_MASK, vl & ~PR_SVE_VL_LEN_MASK);
    } else printf("\"current_vector_length_bytes\":null,\"vector_length_status\":\"unsupported\"");
#else
    printf("\"hwcap\":null,\"hwcap2\":null,\"current_vector_length_bytes\":null,\"status\":\"unsupported_architecture\"");
#endif
    printf("}\n");
}

#if defined(LVS_CPU_HELPER_ENABLE_SVE) || defined(LVS_CPU_HELPER_TEST_SVE)
#include "cpu_sve_kernel.h"

static int prepare_sve_fp32_cases(uint32_t *data, size_t count, uint32_t seed) {
    for (int k = 0; k < FP32_FMA_CASES; ++k) {
        uint32_t *input = data + k * count * 4;
        for (size_t lane = 0; lane < count; ++lane) {
            uint32_t mix = seed * 1664525U + (uint32_t)lane * 1013904223U + (uint32_t)k * 69069U;
            input[lane] = 0x3f000000U | (mix & 0x3fffffU);
            input[count + lane] = 0x3f7f0000U | ((mix >> 5) & 0xffffU);
            input[count * 2 + lane] = 0x3a800000U | ((mix >> 9) & 0x3fffffU) | ((lane & 1) ? 0x80000000U : 0U);
            uint32_t value = input[lane];
            for (int round = 0; round < FP32_FMA_ROUNDS; ++round) {
                if (!keep_running || !fp32_fma_reference(value, input[count + lane], input[count * 2 + lane], &value)) return 0;
            }
            input[count * 3 + lane] = value;
        }
    }
    return 1;
}

static void run_sve_fp32_fma_loop(uint32_t seed, worker_stats_t *stats) {
#if defined(LVS_CPU_HELPER_TEST_SVE)
    const char *configured = getenv("LVS_TEST_SVE_VL_BYTES");
    int state = configured ? atoi(configured) : 16;
#if defined(LVS_CPU_HELPER_TEST_SVE_DIFFERING_VL)
    state = stats->progress_index & 1 ? 48 : 32;
#endif
    stats->sve_vl_errno = state < 0 ? EINVAL : 0;
#if defined(LVS_CPU_HELPER_TEST_BAD_FPCR)
    stats->fpcr = 1ULL << 24;
#endif
#else
    errno = 0;
    int state = prctl(PR_SVE_GET_VL, 0UL, 0UL, 0UL, 0UL);
    stats->sve_vl_errno = state < 0 ? errno : 0;
    __asm__ volatile("mrs %0, fpcr" : "=r"(stats->fpcr));
#endif
    if (state < 0) {
        record_worker_error(stats, "sve_vl_query", 0, 0, stats->sve_vl_errno);
        keep_running = 0; return;
    }
    stats->sve_vl_bytes = state & 0xffff;
    stats->sve_vl_flags = state & ~0xffff;
    /* Architectural SVE VL is 16..256 bytes in 16-byte units, not powers of two. */
    if (stats->sve_vl_bytes < 16 || stats->sve_vl_bytes > 256 || stats->sve_vl_bytes % 16) {
        record_worker_error(stats, "sve_vl_invalid", 0, 16, stats->sve_vl_bytes);
        keep_running = 0; return;
    }
    if (!fp32_environment_supported(stats->fpcr)) {
        record_worker_error(stats, "fp_environment", 0, 0, stats->fpcr);
        keep_running = 0; return;
    }
    int lanes = stats->sve_fp32_lanes = stats->sve_vl_bytes / 4;
    size_t count = (size_t)lanes * 8;
    /* Four cases x four arrays; actual outputs and predication witnesses.
     * O(actual VL), allocated once; never proportional to system memory. */
    uint32_t *data = calloc(FP32_FMA_CASES * count * 4 + count + (size_t)lanes * 6 + 2, sizeof(*data));
    if (!data) {
        record_worker_error(stats, "sve_allocation", 0, 1, 0);
        keep_running = 0; return;
    }
    uint32_t *actual = data + FP32_FMA_CASES * count * 4;
    uint32_t *wa = actual + count, *wb = wa + lanes, *wc = wb + lanes;
    uint32_t *witness = wc + lanes, *expected_witness = witness + lanes, *masked = expected_witness + lanes;
    if (!prepare_sve_fp32_cases(data, count, seed)) {
        if (keep_running) record_worker_error(stats, "fp32_reference_domain", 0, 1, 0);
        keep_running = 0; goto cleanup;
    }
    for (int lane = 0; lane < lanes; ++lane) {
        wa[lane] = fp32_witness_a[lane % 4]; wb[lane] = fp32_witness_b[lane % 4];
        wc[lane] = lane < 4 ? fp32_witness_c[lane] : 0x3f123456U;
        expected_witness[lane] = lane < 4 ? fp32_witness_expected[lane] : wc[lane];
    }
    for (;;) {
        int final = !keep_running;
        if (final && (stats->error_count || !stats->initial_verification_completed)) break;
        if (!fp32_check_affinity(stats)) break;
#if defined(LVS_CPU_HELPER_TEST_MIGRATION)
        record_worker_error(stats, "affinity_lost", 0, stats->affinity_target_cpu, UINT64_MAX);
        keep_running = 0; break;
#endif
        uint32_t *input = data + ((stats->arithmetic_verified_blocks + seed) % FP32_FMA_CASES) * count * 4;
        int completed = execute_sve_fp32_block(input, input + count, input + count * 2, actual, lanes, final);
        if (!completed) { ++stats->interrupted_arithmetic_blocks; continue; }
        if (completed < 0) {
            record_worker_error(stats, "sve_execution_state", stats->arithmetic_verified_blocks, lanes, 0);
            keep_running = 0; break;
        }
#if defined(LVS_CPU_HELPER_TEST_CORRUPT_FP32_LANE)
        actual[count - 1] ^= 1U;
#elif defined(LVS_CPU_HELPER_TEST_NONFINITE_FP32_LANE)
        actual[count - 1] = 0x7f800000U;
#endif
        if (!verify_fp32_fma_lanes(stats, actual, input + count * 3, (int)count, stats->arithmetic_verified_blocks)) break;
        memcpy(witness, wc, (size_t)lanes * sizeof(*wc));
        for (int i = 0; i < lanes + 2; ++i) masked[i] = 0xdeadbeefU;
        execute_sve_witness(wa, wb, wc, witness, masked);
        if (!verify_fp32_fma_lanes(stats, witness, expected_witness, lanes, stats->arithmetic_verified_blocks)) break;
        for (int i = 0; i < lanes + 2; ++i) {
            uint32_t expected = i >= 1 && i <= 4 ? fp32_witness_expected[i - 1] : 0xdeadbeefU;
            if (masked[i] != expected) {
                stats->first_error_lane = i;
                record_worker_error(stats, "sve_masked_store", stats->arithmetic_verified_blocks, expected, masked[i]);
                keep_running = 0; goto cleanup;
            }
        }
        if (!fp32_check_affinity(stats)) break;
        if (stats->arithmetic_verified_blocks == UINT64_MAX) {
            record_worker_error(stats, "fp32_counter_overflow", UINT64_MAX, 0, 0);
            keep_running = 0; break;
        }
        ++stats->arithmetic_verified_blocks; ++stats->verify_passes;
        if (final) {
            stats->final_verification_completed = 1;
            publish_verified_progress(stats, 1); break;
        }
        int initial = !stats->initial_verification_completed;
        if (initial) stats->initial_verification_completed = 1;
        else stats->periodic_verification_completed = 1;
        publish_verified_progress(stats, initial);
    }
cleanup:
    free(data);
}
#endif

static int cpu_supports_neon_fp32_fma(void) {
#if defined(LVS_CPU_HELPER_TEST_DISABLE_FP) || defined(LVS_CPU_HELPER_TEST_DISABLE_ASIMD)
    return 0;
#elif defined(LVS_CPU_HELPER_TEST_FP32_FMA)
    return 1;
#elif defined(__aarch64__) && defined(__linux__)
    unsigned long hwcap = getauxval(AT_HWCAP);
    return (hwcap & (HWCAP_FP | HWCAP_ASIMD)) == (HWCAP_FP | HWCAP_ASIMD);
#else
    return 0;
#endif
}

static int cpu_supports_neon(void) {
#if defined(LVS_CPU_HELPER_TEST_DISABLE_ASIMD)
    return 0;
#elif defined(__aarch64__) && defined(__linux__)
    return (getauxval(AT_HWCAP) & HWCAP_ASIMD) != 0UL;
#else
    return 0;
#endif
}

#if defined(__x86_64__) || defined(__i386__)
static uint64_t read_xcr0(void) {
    uint32_t eax = 0;
    uint32_t edx = 0;
    __asm__ volatile("xgetbv" : "=a"(eax), "=d"(edx) : "c"(0));
    return ((uint64_t)edx << 32) | eax;
}

static int current_cpu_supports_sse2(void) {
    unsigned int eax = 0, ebx = 0, ecx = 0, edx = 0;
    return __get_cpuid(1, &eax, &ebx, &ecx, &edx) && (edx & bit_SSE2) != 0U;
}

static int current_cpu_supports_avx(void) {
    unsigned int eax = 0, ebx = 0, ecx = 0, edx = 0;
    if (!__get_cpuid(1, &eax, &ebx, &ecx, &edx)) {
        return 0;
    }
    if ((ecx & bit_AVX) == 0U || (ecx & bit_OSXSAVE) == 0U) {
        return 0;
    }
    return (read_xcr0() & 0x6U) == 0x6U;
}

static int current_cpu_supports_fma(void) {
    unsigned int eax = 0, ebx = 0, ecx = 0, edx = 0;
    return current_cpu_supports_avx() && __get_cpuid(1, &eax, &ebx, &ecx, &edx) && (ecx & bit_FMA) != 0U;
}

static int current_cpu_supports_avx2(void) {
    unsigned int eax = 0, ebx = 0, ecx = 0, edx = 0;
    if (!current_cpu_supports_avx() || __get_cpuid_max(0, NULL) < 7U) {
        return 0;
    }
    __cpuid_count(7, 0, eax, ebx, ecx, edx);
    return (ebx & bit_AVX2) != 0U;
}

static int current_cpu_supports_avx512f(void) {
    unsigned int eax = 0, ebx = 0, ecx = 0, edx = 0;
    if (!current_cpu_supports_avx() || __get_cpuid_max(0, NULL) < 7U) {
        return 0;
    }
    __cpuid_count(7, 0, eax, ebx, ecx, edx);
    return (ebx & bit_AVX512F) != 0U && (read_xcr0() & 0xE6U) == 0xE6U;
}
#endif

static int cpu_supports_fma(void) {
#if defined(__x86_64__) || defined(__i386__)
    return current_cpu_supports_fma();
#else
    return 0;
#endif
}

static stress_mode_t resolve_mode(stress_mode_t requested) {
#if defined(__x86_64__) || defined(__i386__)
    if (requested == MODE_AUTO) {
        if (current_cpu_supports_avx512f()) {
            return MODE_AVX512;
        }
        if (current_cpu_supports_avx2()) {
            return MODE_AVX2;
        }
        if (current_cpu_supports_avx()) {
            return MODE_AVX;
        }
        if (current_cpu_supports_sse2()) {
            return MODE_SSE;
        }
        return MODE_SCALAR;
    }
    if (
        requested == MODE_AVX512 &&
        !current_cpu_supports_avx512f()
    ) {
        return MODE_AVX2;
    }
    if (requested == MODE_AVX2 && !current_cpu_supports_avx2()) {
        return MODE_AVX;
    }
    if (requested == MODE_AVX && !current_cpu_supports_avx()) {
        return MODE_SSE;
    }
    if (requested == MODE_SSE && !current_cpu_supports_sse2()) {
        return MODE_SCALAR;
    }
    return requested;
#elif defined(__aarch64__) && defined(__linux__)
    if (requested == MODE_AUTO) {
        return cpu_supports_neon() ? MODE_NEON : MODE_SCALAR;
    }
    return requested;
#else
    (void)requested;
    return MODE_SCALAR;
#endif
}

static int requested_mode_supported(stress_mode_t requested) {
#if defined(__x86_64__) || defined(__i386__)
    return requested != MODE_NEON && requested != MODE_SVE;
#elif defined(__aarch64__) && defined(__linux__)
    return requested == MODE_AUTO || requested == MODE_SCALAR ||
        (requested == MODE_NEON && cpu_supports_neon()) ||
        (requested == MODE_SVE && cpu_supports_sve_fp32_fma());
#else
    return requested == MODE_AUTO || requested == MODE_SCALAR;
#endif
}

static kernel_flavor_t parse_kernel_flavor(const char *raw) {
    if (strcmp(raw, "scalar") == 0) {
        return KERNEL_SCALAR;
    }
    if (strcmp(raw, "sse2") == 0) {
        return KERNEL_SSE2;
    }
    if (strcmp(raw, "sse2_int") == 0) {
        return KERNEL_SSE2_INT;
    }
    if (strcmp(raw, "avx") == 0) {
        return KERNEL_AVX;
    }
    if (strcmp(raw, "avx_fma") == 0) {
        return KERNEL_AVX_FMA;
    }
    if (strcmp(raw, "avx2") == 0) {
        return KERNEL_AVX2;
    }
    if (strcmp(raw, "avx2_fma") == 0) {
        return KERNEL_AVX2_FMA;
    }
    if (strcmp(raw, "avx512_fma") == 0) {
        return KERNEL_AVX512_FMA;
    }
    if (strcmp(raw, "avx512_int") == 0) {
        return KERNEL_AVX512_INT;
    }
    if (strcmp(raw, "neon") == 0) {
        return KERNEL_NEON;
    }
    if (strcmp(raw, "neon_fp32_fma") == 0) {
        return KERNEL_NEON_FP32_FMA;
    }
    if (strcmp(raw, "sve_fp32_fma") == 0) return KERNEL_SVE_FP32_FMA;
    return KERNEL_UNSPECIFIED;
}

static int kernel_flavor_supported(kernel_flavor_t flavor) {
    switch (flavor) {
        case KERNEL_SVE_FP32_FMA:
            return cpu_supports_sve_fp32_fma();
        case KERNEL_NEON_FP32_FMA:
            return cpu_supports_neon_fp32_fma();
        case KERNEL_SCALAR:
            return 1;
        case KERNEL_SSE2:
        case KERNEL_SSE2_INT:
#if defined(__x86_64__) || defined(__i386__)
            return current_cpu_supports_sse2();
#else
            return 0;
#endif
        case KERNEL_AVX:
#if defined(__x86_64__) || defined(__i386__)
            return current_cpu_supports_avx();
#else
            return 0;
#endif
        case KERNEL_AVX_FMA:
#if defined(__x86_64__) || defined(__i386__)
            return current_cpu_supports_avx() && cpu_supports_fma();
#else
            return 0;
#endif
        case KERNEL_AVX2:
#if defined(__x86_64__) || defined(__i386__)
            return current_cpu_supports_avx2();
#else
            return 0;
#endif
        case KERNEL_AVX2_FMA:
#if defined(__x86_64__) || defined(__i386__)
            return current_cpu_supports_avx2() && cpu_supports_fma();
#else
            return 0;
#endif
        case KERNEL_AVX512_FMA:
        case KERNEL_AVX512_INT:
#if defined(__x86_64__) || defined(__i386__)
            return current_cpu_supports_avx512f();
#else
            return 0;
#endif
        case KERNEL_NEON:
#if defined(__aarch64__) && defined(__linux__)
            return cpu_supports_neon();
#else
            return 0;
#endif
        case KERNEL_UNSPECIFIED:
        default:
            return 0;
    }
}

static void report_unsupported_kernel(kernel_flavor_t flavor) {
    if (flavor == KERNEL_SVE_FP32_FMA)
        fprintf(stderr, "sve_fp32_fma requires optional compiled SVE support and Linux FP/SVE HWCAP; inspect --print-isa-capabilities\n");
    else fprintf(stderr, "kernel flavor not supported on this CPU\n");
}

static stress_mode_t mode_for_kernel_flavor(kernel_flavor_t flavor) {
    switch (flavor) {
        case KERNEL_SVE_FP32_FMA:
            return MODE_SVE;
        case KERNEL_SSE2:
        case KERNEL_SSE2_INT:
            return MODE_SSE;
        case KERNEL_AVX:
        case KERNEL_AVX_FMA:
            return MODE_AVX;
        case KERNEL_AVX2:
        case KERNEL_AVX2_FMA:
            return MODE_AVX2;
        case KERNEL_AVX512_FMA:
        case KERNEL_AVX512_INT:
            return MODE_AVX512;
        case KERNEL_NEON:
        case KERNEL_NEON_FP32_FMA:
            return MODE_NEON;
        case KERNEL_UNSPECIFIED:
        case KERNEL_SCALAR:
        default:
            return MODE_SCALAR;
    }
}

static kernel_flavor_t default_kernel_flavor(stress_mode_t requested) {
    stress_mode_t resolved = resolve_mode(requested);
    switch (resolved) {
        case MODE_SSE:
            return KERNEL_SSE2;
        case MODE_AVX:
            if (cpu_supports_fma()) {
                return KERNEL_AVX_FMA;
            }
            return KERNEL_AVX;
        case MODE_AVX2:
            if (cpu_supports_fma()) {
                return KERNEL_AVX2_FMA;
            }
            return KERNEL_AVX2;
        case MODE_AVX512:
            return KERNEL_AVX512_FMA;
        case MODE_NEON:
            return KERNEL_NEON;
        case MODE_SVE:
            return KERNEL_SVE_FP32_FMA;
        case MODE_AUTO:
        case MODE_SCALAR:
        default:
            return KERNEL_SCALAR;
    }
}

static void *worker_main(void *opaque) {
    worker_args_t *args = (worker_args_t *)opaque;
    int affinity_result = bind_worker_to_cpu(args->target_cpu, args->stats);
    kernel_flavor_t flavor = args->kernel_flavor;
    if (flavor == KERNEL_UNSPECIFIED) {
        flavor = default_kernel_flavor(args->mode);
    }
    if (verified_fp32_kernel(flavor)) {
        args->stats->affinity_required = 1;
        if (affinity_result != 0) {
            record_worker_error(args->stats, "affinity_required", 0, 0, (uint64_t)affinity_result);
            keep_running = 0;
            return NULL;
        }
    }
#if defined(__x86_64__) || defined(__i386__)
    args->stats->affinity_required = flavor != KERNEL_SCALAR;
    if (flavor != KERNEL_SCALAR && affinity_result != 0) {
        args->stats->error_count += 1ULL;
        args->stats->first_error_recorded = 1;
        snprintf(args->stats->first_error_kind, sizeof(args->stats->first_error_kind), "%s", "affinity_required");
        return NULL;
    }
#endif
    if (affinity_result == 0 && !kernel_flavor_supported(flavor)) {
        args->stats->error_count += 1ULL;
        args->stats->first_error_recorded = 1;
        snprintf(args->stats->first_error_kind, sizeof(args->stats->first_error_kind), "%s", "isa_not_supported");
        if (verified_fp32_kernel(flavor)) keep_running = 0;
        return NULL;
    }
    uint32_t seed = (uint32_t)(args->worker_index + 1);

    switch (flavor) {
        case KERNEL_SVE_FP32_FMA:
#if defined(LVS_CPU_HELPER_ENABLE_SVE) || defined(LVS_CPU_HELPER_TEST_SVE)
            run_sve_fp32_fma_loop(seed, args->stats);
#else
            record_worker_error(args->stats, "sve_not_compiled", 0, 1, 0);
            keep_running = 0;
#endif
            break;
        case KERNEL_NEON_FP32_FMA:
#if (defined(__aarch64__) && defined(__linux__)) || defined(LVS_CPU_HELPER_TEST_FP32_FMA)
            run_neon_fp32_fma_loop(seed, args->stats);
#else
            record_worker_error(args->stats, "isa_not_supported", 0, 1, 0);
            keep_running = 0;
#endif
            break;
        case KERNEL_SSE2:
#if defined(__x86_64__) || defined(__i386__)
            run_sse_loop(seed, args->stats);
            break;
#endif
        case KERNEL_SSE2_INT:
#if defined(__x86_64__) || defined(__i386__)
            run_sse2_int_loop(seed, args->stats);
            break;
#endif
        case KERNEL_AVX:
#if defined(__x86_64__) || defined(__i386__)
            run_avx_loop(seed, args->stats);
            break;
#endif
        case KERNEL_AVX_FMA:
#if defined(__x86_64__) || defined(__i386__)
            run_avx_fma_loop(seed, args->stats);
            break;
#endif
        case KERNEL_AVX2:
#if defined(__x86_64__) || defined(__i386__)
            run_avx2_loop(seed, args->stats);
            break;
#endif
        case KERNEL_AVX2_FMA:
#if defined(__x86_64__) || defined(__i386__)
            run_avx2_fma_loop(seed, args->stats);
            break;
#endif
        case KERNEL_AVX512_FMA:
#if defined(__x86_64__) || defined(__i386__)
            run_avx512_loop(seed, args->stats);
            break;
#endif
        case KERNEL_AVX512_INT:
#if defined(__x86_64__) || defined(__i386__)
            run_avx512_int_loop(seed, args->stats);
            break;
#endif
        case KERNEL_NEON:
#if defined(__aarch64__) && defined(__linux__)
            run_neon_loop(seed, args->stats);
            break;
#endif
        case KERNEL_UNSPECIFIED:
        case KERNEL_SCALAR:
        default:
            run_scalar_loop(seed, args->stats);
            break;
    }
    return NULL;
}

static stress_mode_t parse_mode(const char *raw) {
    if (strcmp(raw, "auto") == 0) {
        return MODE_AUTO;
    }
    if (strcmp(raw, "scalar") == 0) {
        return MODE_SCALAR;
    }
    if (strcmp(raw, "sse") == 0) {
        return MODE_SSE;
    }
    if (strcmp(raw, "avx") == 0) {
        return MODE_AVX;
    }
    if (strcmp(raw, "avx2") == 0) {
        return MODE_AVX2;
    }
    if (strcmp(raw, "avx512") == 0) {
        return MODE_AVX512;
    }
    if (strcmp(raw, "neon") == 0) {
        return MODE_NEON;
    }
    if (strcmp(raw, "sve") == 0 || strcmp(raw, "sve_fp32_fma") == 0) {
        return MODE_SVE;
    }
    return MODE_AUTO;
}

static void print_usage(const char *argv0) {
    fprintf(
        stderr,
        "Usage: %s [--mode auto|scalar|sse|avx|avx2|avx512|neon|sve] [--kernel-flavor scalar|sse2|sse2_int|avx|avx_fma|avx2|avx2_fma|avx512_fma|avx512_int|neon|neon_fp32_fma|sve_fp32_fma] [--threads N] [--cpu-ids LIST] [--probe-cpu ID] [--print-resolved-mode] [--print-kernel-flavor] [--print-supported-kernels] [--print-isa-capabilities] [--result-file <path>]\n",
        argv0
    );
}

static int parse_cpu_ids(const char *raw, int *cpu_ids, int capacity) {
    if (raw == NULL || *raw == '\0' || cpu_ids == NULL || capacity <= 0) {
        return 0;
    }
    char *copy = strdup(raw);
    if (copy == NULL) {
        return -1;
    }
    int count = 0;
    char *save = NULL;
    for (char *token = strtok_r(copy, ",", &save); token != NULL; token = strtok_r(NULL, ",", &save)) {
        char *end = NULL;
        long value = strtol(token, &end, 10);
        if (end == token || *end != '\0' || value < 0 || value > INT32_MAX || count >= capacity) {
            free(copy);
            return -1;
        }
        for (int index = 0; index < count; ++index) {
            if (cpu_ids[index] == (int)value) {
                free(copy);
                return -1;
            }
        }
        cpu_ids[count++] = (int)value;
    }
    free(copy);
    return count;
}

static int allowed_cpu_ids(int *cpu_ids, int capacity) {
#ifdef __linux__
    long configured = sysconf(_SC_NPROCESSORS_CONF);
    size_t cpu_capacity = (size_t)(configured > 0 ? configured : 1024);
    cpu_set_t *set = CPU_ALLOC(cpu_capacity);
    if (set == NULL) {
        return 0;
    }
    size_t set_size = CPU_ALLOC_SIZE(cpu_capacity);
    CPU_ZERO_S(set_size, set);
    if (sched_getaffinity(0, set_size, set) != 0) {
        CPU_FREE(set);
        return 0;
    }
    int count = 0;
    for (size_t cpu_id = 0; cpu_id < cpu_capacity && count < capacity; ++cpu_id) {
        if (CPU_ISSET_S(cpu_id, set_size, set)) {
            cpu_ids[count++] = (int)cpu_id;
        }
    }
    CPU_FREE(set);
    return count;
#else
    for (int index = 0; index < capacity; ++index) {
        cpu_ids[index] = index;
    }
    return capacity;
#endif
}

static void write_result_file(
    const char *path,
    stress_mode_t mode,
    kernel_flavor_t kernel_flavor,
    int requested_threads,
    int threads,
    uint64_t verify_passes,
    uint64_t canary_passes,
    uint64_t error_count,
    const worker_stats_t *worker_stats,
    const int *target_cpu_ids
) {
    if (path == NULL || *path == '\0') {
        return;
    }
    FILE *handle = fopen(path, "w");
    if (handle == NULL) {
        return;
    }
    int affinity_attempted_count = 0;
    int affinity_applied_count = 0;
    for (int index = 0; index < threads; ++index) {
        affinity_attempted_count += worker_stats[index].affinity_attempted ? 1 : 0;
        affinity_applied_count += worker_stats[index].affinity_applied ? 1 : 0;
    }
    fprintf(
        handle,
        "{\n"
        "  \"kind\": \"cpu\",\n"
        "  \"status\": \"%s\",\n"
        "  \"mode\": \"%s\",\n"
        "  \"kernel_flavor\": \"%s\",\n"
        "  \"threads\": %d,\n"
        "  \"verify_passes\": %" PRIu64 ",\n"
        "  \"canary_passes\": %" PRIu64 ",\n"
        "  \"error_count\": %" PRIu64 ",\n"
        "  \"requested_thread_count\": %d,\n"
        "  \"actual_worker_count\": %d,\n"
        "  \"capability_scope\": \"%s\",\n"
        "  \"target_cpu_ids\": [",
        error_count == 0 ? "ok" : "error",
        mode_name(mode),
        kernel_flavor_name(kernel_flavor),
        threads,
        verify_passes,
        canary_passes,
        error_count,
        requested_threads,
        threads,
#if defined(__x86_64__) || defined(__i386__)
        "per_cpu_affinity_pinned_cpuid"
#elif defined(__aarch64__)
        "linux_aarch64_hwcap_common_set"
#else
        "generic"
#endif
    );
    for (int index = 0; index < threads; ++index) {
        fprintf(handle, "%s%d", index == 0 ? "" : ", ", target_cpu_ids[index]);
    }
    fprintf(handle, "],\n");
    if (verified_fp32_kernel(kernel_flavor)) {
        const char *contract_kernel = kernel_flavor_name(kernel_flavor);
        fprintf(handle, "  \"verified_progress\": {\"contract\":\"%s_progress_v1\","
            "\"sidecar_suffix\":\".progress.jsonl\",\"snapshot_interval_seconds\":2.0,"
            "\"publication_checks\":\"adaptive_block_boundary_clock_checks\",\"publication_minimum_seconds\":0.25,"
            "\"persistence_error\":%s,\"snapshot_count\":%lu,\"snapshot_write_seconds\":%.9f},\n",
            contract_kernel, progress_io_error ? "true" : "false", progress_sequence, progress_write_seconds);
        uint64_t blocks = 0;
        int initial = threads == requested_threads && threads > 0;
        int periodic = initial, final = initial;
        for (int index = 0; index < threads; ++index) {
            blocks += worker_stats[index].arithmetic_verified_blocks;
            initial &= worker_stats[index].initial_verification_completed;
            periodic &= worker_stats[index].periodic_verification_completed;
            final &= worker_stats[index].final_verification_completed;
        }
#if defined(__aarch64__) && defined(__linux__) && !defined(LVS_CPU_HELPER_TEST_FP32_FMA) && !defined(LVS_CPU_HELPER_TEST_SVE)
        fprintf(handle, "  \"isa_capability_source\": \"linux_getauxval_at_hwcap_common_set\",\n"
                        "  \"isa_hwcap\": %lu,\n", getauxval(AT_HWCAP));
        errno = 0;
        unsigned long hwcap2 = getauxval(AT_HWCAP2);
        if (errno) fprintf(handle, "  \"isa_hwcap2\": null,\n  \"isa_hwcap2_status\": \"unavailable\",\n");
        else fprintf(handle, "  \"isa_hwcap2\": %lu,\n  \"isa_hwcap2_status\": \"measured\",\n", hwcap2);
#else
        fprintf(handle, "  \"isa_capability_source\": \"test_override\",\n"
                        "  \"isa_hwcap\": null,\n  \"isa_hwcap2\": null,\n  \"isa_hwcap2_status\": \"not_collected\",\n");
#endif
        fprintf(handle,
            "  \"operation_family\": \"fp32_fused_multiply_add\",\n"
            "  \"verification_required\": true,\n"
            "  \"verification_contract\": \"%s_v1\",\n"
            "  \"verification_method\": \"integer_binary32_fma_reference\",\n"
            "  \"verification_version\": 1,\n"
            "  \"rounding_environment\": \"nearest_ties_even_no_flush\",\n"
            "  \"execution_implementation\": \"%s\",\n"
            "  \"arithmetic_verified_blocks\": %" PRIu64 ",\n"
            "  \"fma_rounds_per_block\": %d,\n"
            "  \"initial_verification_completed\": %s,\n"
            "  \"periodic_verification_completed\": %s,\n"
            "  \"final_verification_completed\": %s,\n"
            "  \"verification_complete\": %s,\n",
            contract_kernel,
#if defined(LVS_CPU_HELPER_TEST_FP32_FMA) || defined(LVS_CPU_HELPER_TEST_SVE)
            "test_integer_emulation",
#else
            kernel_flavor == KERNEL_SVE_FP32_FMA ? "aarch64_sve_intrinsics" : "aarch64_neon_intrinsics",
#endif
            blocks, FP32_FMA_ROUNDS,
            initial ? "true" : "false", periodic ? "true" : "false", final ? "true" : "false",
            initial && periodic && final && error_count == 0 ? "true" : "false");
        if (kernel_flavor == KERNEL_SVE_FP32_FMA) {
            fprintf(handle, "  \"actual_isa\":\"%s\",\n  \"accumulator_chains\":8,\n"
                            "  \"vector_length_source\":\"%s\",\n"
                            "  \"predicate_verification\":\"four_active_witnesses_merge_and_guarded_masked_store\",\n",
#if defined(LVS_CPU_HELPER_TEST_SVE)
                            "test_integer_emulation", "test_override"
#else
                            "sve", "linux_prctl_pr_sve_get_vl_per_thread"
#endif
            );
        } else fprintf(handle, "  \"lanes_per_block\": %d,\n", FP32_FMA_LANES);
    }
    fprintf(
        handle,
        "  \"affinity_attempted_count\": %d,\n"
        "  \"affinity_applied_count\": %d,\n"
        "  \"affinity_failed_count\": %d,\n"
        "  \"threads_detail\": [\n",
        affinity_attempted_count,
        affinity_applied_count,
        affinity_attempted_count - affinity_applied_count
    );
    for (int index = 0; index < threads; ++index) {
        fprintf(
            handle,
            "    {\n"
            "      \"thread_index\": %d,\n"
            "      \"affinity_target_cpu\": %d,\n"
            "      \"affinity_attempted\": %s,\n"
            "      \"affinity_applied\": %s,\n"
            "      \"affinity_required\": %s,\n"
            "      \"affinity_error_code\": %d,\n"
            "      \"observed_cpu\": %d,\n"
            "      \"verify_passes\": %" PRIu64 ",\n"
            "      \"canary_passes\": %" PRIu64 ",\n"
            "      \"error_count\": %" PRIu64,
            index,
            worker_stats[index].affinity_target_cpu,
            worker_stats[index].affinity_attempted ? "true" : "false",
            worker_stats[index].affinity_applied ? "true" : "false",
            worker_stats[index].affinity_required ? "true" : "false",
            worker_stats[index].affinity_error_code,
            worker_stats[index].observed_cpu,
            worker_stats[index].verify_passes,
            worker_stats[index].canary_passes,
            worker_stats[index].error_count
        );
        if (verified_fp32_kernel(kernel_flavor)) {
            fprintf(handle,
                ",\n      \"arithmetic_verified_blocks\": %" PRIu64 ",\n"
                "      \"interrupted_arithmetic_blocks\": %" PRIu64 ",\n"
                "      \"fpcr\": %" PRIu64 ",\n"
                "      \"initial_verification_completed\": %s,\n"
                "      \"periodic_verification_completed\": %s,\n"
                "      \"final_verification_completed\": %s,\n"
                "      \"first_error_lane\": %d",
                worker_stats[index].arithmetic_verified_blocks,
                worker_stats[index].interrupted_arithmetic_blocks, worker_stats[index].fpcr,
                worker_stats[index].initial_verification_completed ? "true" : "false",
                worker_stats[index].periodic_verification_completed ? "true" : "false",
                worker_stats[index].final_verification_completed ? "true" : "false",
                (strcmp(worker_stats[index].first_error_kind, "fp32_fma_mismatch") == 0 ||
                 strcmp(worker_stats[index].first_error_kind, "sve_masked_store") == 0)
                    ? worker_stats[index].first_error_lane : -1);
            if (kernel_flavor == KERNEL_SVE_FP32_FMA) {
                const worker_stats_t *s = &worker_stats[index];
                fprintf(handle, ",\n      \"vector_length_bytes\":%d,\n      \"vector_length_flags\":%d,"
                    "\n      \"vector_length_errno\":%d,\n      \"active_fp32_lanes\":%d,"
                    "\n      \"lanes_per_block\":%d,\n      \"stress_lane_fmas_per_block\":%d,"
                    "\n      \"witness_lane_fmas_per_block\":4",
                    s->sve_vl_bytes, s->sve_vl_flags, s->sve_vl_errno, s->sve_fp32_lanes,
                    s->sve_fp32_lanes * 8, s->sve_fp32_lanes * 8 * FP32_FMA_ROUNDS);
            }
        }
        if (worker_stats[index].first_error_recorded) {
            fprintf(
                handle,
                ",\n"
                "      \"first_error\": {\n"
                "        \"kind\": \"%s\",\n"
                "        \"iteration\": %" PRIu64 ",\n"
                "        \"expected\": %" PRIu64 ",\n"
                "        \"actual\": %" PRIu64 "\n"
                "      }\n"
                "    }%s\n",
                worker_stats[index].first_error_kind,
                worker_stats[index].first_error_iteration,
                worker_stats[index].first_error_expected,
                worker_stats[index].first_error_actual,
                index + 1 < threads ? "," : ""
            );
        } else {
            fprintf(handle, "\n    }%s\n", index + 1 < threads ? "," : "");
        }
    }
    fprintf(handle, "  ]\n}\n");
    fclose(handle);
}

int main(int argc, char **argv) {
    stress_mode_t mode = MODE_AUTO;
    kernel_flavor_t kernel_flavor = KERNEL_UNSPECIFIED;
    int threads = (int)sysconf(_SC_NPROCESSORS_ONLN);
    int print_resolved_mode = 0;
    int print_kernel_flavor = 0;
    int print_supported_kernels = 0;
    int print_core_type = 0;
    int print_isa = 0;
    int probe_cpu = -1;
    const char *cpu_ids_raw = NULL;
    if (threads <= 0) {
        threads = 1;
    }

    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--mode") == 0 && i + 1 < argc) {
            mode = parse_mode(argv[++i]);
            continue;
        }
        if (strcmp(argv[i], "--threads") == 0 && i + 1 < argc) {
            threads = atoi(argv[++i]);
            if (threads <= 0) {
                threads = 1;
            }
            continue;
        }
        if (strcmp(argv[i], "--cpu-ids") == 0 && i + 1 < argc) {
            cpu_ids_raw = argv[++i];
            continue;
        }
        if (strcmp(argv[i], "--probe-cpu") == 0 && i + 1 < argc) {
            probe_cpu = atoi(argv[++i]);
            continue;
        }
        if (strcmp(argv[i], "--kernel-flavor") == 0 && i + 1 < argc) {
            kernel_flavor = parse_kernel_flavor(argv[++i]);
            if (kernel_flavor == KERNEL_UNSPECIFIED) {
                fprintf(stderr, "unknown kernel flavor\n");
                return 2;
            }
            continue;
        }
        if (strcmp(argv[i], "--print-resolved-mode") == 0) {
            print_resolved_mode = 1;
            continue;
        }
        if (strcmp(argv[i], "--print-kernel-flavor") == 0) {
            print_kernel_flavor = 1;
            continue;
        }
        if (strcmp(argv[i], "--print-supported-kernels") == 0) {
            print_supported_kernels = 1;
            continue;
        }
        if (strcmp(argv[i], "--print-core-type") == 0) {
            print_core_type = 1;
            continue;
        }
        if (strcmp(argv[i], "--print-isa-capabilities") == 0) {
            print_isa = 1;
            continue;
        }
        if (strcmp(argv[i], "--result-file") == 0 && i + 1 < argc) {
            result_file_path = argv[++i];
            continue;
        }
        print_usage(argv[0]);
        return 2;
    }

    if (probe_cpu >= 0) {
        int probe_affinity_result = bind_current_thread_to_cpu(probe_cpu);
        if (probe_affinity_result != 0) {
            fprintf(stderr, "unable to pin capability probe to CPU %d: %s\n", probe_cpu, strerror(probe_affinity_result));
            return 5;
        }
    }

    if (print_isa) { print_isa_capabilities(); return 0; }
    if (print_core_type) {
#if defined(__x86_64__) || defined(__i386__)
        unsigned int eax = 0, ebx = 0, ecx = 0, edx = 0;
        unsigned int max_basic_leaf = __get_cpuid_max(0, NULL);
        char vendor[13] = {0};
        __cpuid_count(0, 0, eax, ebx, ecx, edx);
        memcpy(vendor + 0, &ebx, 4);
        memcpy(vendor + 4, &edx, 4);
        memcpy(vendor + 8, &ecx, 4);
        unsigned int leaf7_edx = 0;
        int leaf7_supported = max_basic_leaf >= 7;
        if (leaf7_supported) {
            __cpuid_count(7, 0, eax, ebx, ecx, edx);
            leaf7_edx = edx;
        }
        int hybrid_flag = leaf7_supported && ((leaf7_edx & (1U << 15)) != 0U);
        unsigned int leaf1a_eax = 0;
        int leaf1a_supported = max_basic_leaf >= 0x1aU;
        if (leaf1a_supported) {
            __cpuid_count(0x1aU, 0, eax, ebx, ecx, edx);
            leaf1a_eax = eax;
        }
        unsigned int raw_core_type = (leaf1a_eax >> 24) & 0xffU;
        const char *interpreted = "";
        if (strcmp(vendor, "GenuineIntel") == 0 && hybrid_flag) {
            if (raw_core_type == 0x20U) {
                interpreted = "E";
            } else if (raw_core_type == 0x40U) {
                interpreted = "P";
            }
        }
        printf(
            "{\"architecture\":\"x86\",\"cpu_id\":%d,\"affinity_applied\":%s,"
            "\"observed_cpu\":%d,\"vendor\":\"%s\",\"max_basic_leaf\":%u,"
            "\"leaf_7_supported\":%s,\"leaf_7_edx\":%u,\"hybrid_flag\":%s,"
            "\"leaf_1a_supported\":%s,\"leaf_1a_eax\":%u,\"raw_core_type\":%u,"
            "\"interpreted_core_type\":\"%s\",\"evidence_source\":\"pinned_cpuid\"}\n",
            probe_cpu,
            probe_cpu >= 0 ? "true" : "false",
            sched_getcpu(),
            vendor,
            max_basic_leaf,
            leaf7_supported ? "true" : "false",
            leaf7_edx,
            hybrid_flag ? "true" : "false",
            leaf1a_supported ? "true" : "false",
            leaf1a_eax,
            raw_core_type,
            interpreted
        );
        return 0;
#else
        printf(
            "{\"architecture\":\"non_x86\",\"cpu_id\":%d,\"affinity_applied\":%s,"
            "\"observed_cpu\":%d,\"interpreted_core_type\":\"\","
            "\"evidence_source\":\"unsupported_architecture\"}\n",
            probe_cpu,
            probe_cpu >= 0 ? "true" : "false",
            sched_getcpu()
        );
        return 0;
#endif
    }

    if (!requested_mode_supported(mode)) {
        if (mode == MODE_NEON) {
            fprintf(stderr, "requested CPU mode 'neon' requires Linux AArch64 ASIMD/NEON capability\n");
        } else if (mode == MODE_SVE) {
            fprintf(stderr, "requested CPU mode 'sve' requires Linux AArch64 FP/SVE and optional SVE compiler support\n");
        } else {
            fprintf(
                stderr,
                "requested CPU mode '%s' is an x86 ISA and is not available on this architecture\n",
                mode_name(mode)
            );
        }
        return 3;
    }

    if (print_resolved_mode) {
        if (kernel_flavor != KERNEL_UNSPECIFIED) {
            if (!kernel_flavor_supported(kernel_flavor)) {
                report_unsupported_kernel(kernel_flavor);
                return 3;
            }
            puts(mode_name(mode_for_kernel_flavor(kernel_flavor)));
            return 0;
        }
        puts(mode_name(resolve_mode(mode)));
        return 0;
    }

    if (print_supported_kernels) {
        const kernel_flavor_t flavors[] = {
            KERNEL_AVX512_FMA, KERNEL_AVX512_INT,
            KERNEL_AVX2_FMA, KERNEL_AVX2,
            KERNEL_AVX_FMA, KERNEL_AVX,
            KERNEL_SSE2, KERNEL_SSE2_INT,
            KERNEL_NEON, KERNEL_NEON_FP32_FMA, KERNEL_SVE_FP32_FMA, KERNEL_SCALAR
        };
        int printed = 0;
        size_t flavor_count = sizeof(flavors) / sizeof(flavors[0]);
        for (size_t index = 0; index < flavor_count; ++index) {
            if (!kernel_flavor_supported(flavors[index])) {
                continue;
            }
            printf("%s%s", printed ? "," : "", kernel_flavor_name(flavors[index]));
            printed = 1;
        }
        putchar('\n');
        return printed ? 0 : 3;
    }

    if (print_kernel_flavor) {
        kernel_flavor_t resolved_flavor = kernel_flavor;
        if (resolved_flavor == KERNEL_UNSPECIFIED) {
            resolved_flavor = default_kernel_flavor(mode);
        }
        if (!kernel_flavor_supported(resolved_flavor)) {
            report_unsupported_kernel(kernel_flavor);
            return 3;
        }
        puts(kernel_flavor_name(resolved_flavor));
        return 0;
    }

    if (kernel_flavor != KERNEL_UNSPECIFIED && cpu_ids_raw == NULL && !kernel_flavor_supported(kernel_flavor)) {
        report_unsupported_kernel(kernel_flavor);
        return 3;
    }

    if (kernel_flavor == KERNEL_UNSPECIFIED && mode == MODE_SVE)
        kernel_flavor = KERNEL_SVE_FP32_FMA;

    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);

    pthread_t *workers = calloc((size_t)threads, sizeof(*workers));
    worker_args_t *worker_args = calloc((size_t)threads, sizeof(*worker_args));
    worker_stats_t *worker_stats = calloc((size_t)threads, sizeof(*worker_stats));
    int *target_cpu_ids = calloc((size_t)threads, sizeof(*target_cpu_ids));
    if (workers == NULL || worker_args == NULL || worker_stats == NULL || target_cpu_ids == NULL) {
        fprintf(stderr, "allocation failure\n");
        free(workers);
        free(worker_args);
        free(worker_stats);
        free(target_cpu_ids);
        return 1;
    }

    int target_count = cpu_ids_raw != NULL
        ? parse_cpu_ids(cpu_ids_raw, target_cpu_ids, threads)
        : allowed_cpu_ids(target_cpu_ids, threads);
    if (target_count != threads) {
        fprintf(stderr, "CPU target list contains %d valid CPUs for %d requested workers\n", target_count, threads);
        free(workers);
        free(worker_args);
        free(worker_stats);
        free(target_cpu_ids);
        return 2;
    }

    const int requested_threads = threads;
    sve_progress = kernel_flavor == KERNEL_SVE_FP32_FMA;
    if (verified_fp32_kernel(kernel_flavor) && result_file_path) {
        progress_threads = threads;
        progress_slots = calloc((size_t)threads, sizeof(*progress_slots));
        progress_snapshot = calloc((size_t)threads, sizeof(*progress_snapshot));
        progress_path = malloc(strlen(result_file_path) + sizeof(".progress.jsonl"));
        if (!progress_slots || !progress_snapshot || !progress_path) {
            fprintf(stderr, "verified progress allocation failed\n");
            return 1;
        }
        sprintf(progress_path, "%s.progress.jsonl", result_file_path);
        /* Never append another process's records to an old sidecar. */
        progress_file = fopen(progress_path, "wx");
        if (!progress_file) {
            fprintf(stderr, "verified progress open failed: %s\n", strerror(errno));
            return 1;
        }
        write_progress_snapshot("startup", target_cpu_ids);
    }
    int worker_creation_failed = 0;
    for (int i = 0; i < threads; ++i) {
        worker_args[i].worker_index = i;
        worker_args[i].target_cpu = target_cpu_ids[i];
        worker_args[i].mode = mode;
        worker_args[i].kernel_flavor = kernel_flavor;
        worker_args[i].stats = &worker_stats[i];
        worker_stats[i].progress_index = i;
        int create_result;
#if (defined(LVS_CPU_HELPER_TEST_FP32_FMA) || defined(LVS_CPU_HELPER_TEST_SVE)) && defined(LVS_CPU_HELPER_TEST_THREAD_START_FAILURE)
        create_result = i == 1 ? EAGAIN : pthread_create(&workers[i], NULL, worker_main, &worker_args[i]);
#else
        create_result = pthread_create(&workers[i], NULL, worker_main, &worker_args[i]);
#endif
        if (create_result != 0) {
            fprintf(stderr, "pthread_create failed: %s\n", strerror(create_result));
            keep_running = 0;
            worker_creation_failed = 1;
            threads = i;
            break;
        }
    }

    if (progress_slots) {
        double last_snapshot = clock_seconds(CLOCK_MONOTONIC);
        int initial_snapshot = 0;
        while (keep_running) {
            struct timespec pause = {0, 100000000};
            nanosleep(&pause, NULL);
            int all_initial = initial_snapshot;
            if (!initial_snapshot) {
                all_initial = 1;
                pthread_mutex_lock(&progress_lock);
                for (int i = 0; i < requested_threads; ++i)
                    all_initial &= progress_slots[i].stats.initial_verification_completed;
                pthread_mutex_unlock(&progress_lock);
            }
            double now = clock_seconds(CLOCK_MONOTONIC);
            if ((!initial_snapshot && all_initial) || now - last_snapshot >= 2.0) {
                write_progress_snapshot(!initial_snapshot && all_initial ? "initial" : "ongoing", target_cpu_ids);
                initial_snapshot |= all_initial;
                last_snapshot = now;
            }
        }
        write_progress_snapshot("interrupted", target_cpu_ids);
    } else {
        while (keep_running) sleep(1);
    }

    for (int i = 0; i < threads; ++i) {
        pthread_join(workers[i], NULL);
    }

    uint64_t total_verify_passes = 0;
    uint64_t total_canary_passes = 0;
    uint64_t total_error_count = 0;
    kernel_flavor_t resolved_flavor = kernel_flavor;
    if (resolved_flavor == KERNEL_UNSPECIFIED) {
        resolved_flavor = default_kernel_flavor(mode);
    }
    for (int i = 0; i < threads; ++i) {
        if (verified_fp32_kernel(resolved_flavor) && worker_stats[i].error_count == 0 &&
            (!worker_stats[i].initial_verification_completed ||
             !worker_stats[i].periodic_verification_completed ||
             !worker_stats[i].final_verification_completed ||
             worker_stats[i].arithmetic_verified_blocks < 3 ||
             !worker_stats[i].affinity_applied)) {
            record_worker_error(&worker_stats[i], "fp32_verification_incomplete", 0, 3,
                                worker_stats[i].arithmetic_verified_blocks);
        }
        total_verify_passes += worker_stats[i].verify_passes;
        total_canary_passes += worker_stats[i].canary_passes;
        total_error_count += worker_stats[i].error_count;
    }
    if (worker_creation_failed) {
        total_error_count += 1ULL;
    }
    if (progress_slots) {
        /* Keep successful workers' actual final block-boundary timestamps.
         * Joining other threads must not move their counter observation time. */
        for (int i = 0; i < threads; ++i)
            if (!worker_stats[i].final_verification_completed || worker_stats[i].error_count)
                publish_verified_progress(&worker_stats[i], 1);
        write_progress_snapshot(total_error_count == 0 ? "final_complete" : "failed", target_cpu_ids);
        if (fclose(progress_file) != 0) progress_io_error = 1;
        progress_file = NULL;
    }
    write_result_file(result_file_path, mode_for_kernel_flavor(resolved_flavor), resolved_flavor, requested_threads, threads, total_verify_passes, total_canary_passes, total_error_count, worker_stats, target_cpu_ids);
    free(progress_slots);
    free(progress_snapshot);
    free(progress_path);
    free(workers);
    free(worker_args);
    free(worker_stats);
    free(target_cpu_ids);
    return total_error_count == 0 ? 0 : 4;
}
