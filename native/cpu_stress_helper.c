#define _GNU_SOURCE
#include <errno.h>
#include <immintrin.h>
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

typedef enum {
    MODE_AUTO = 0,
    MODE_SCALAR = 1,
    MODE_SSE = 2,
    MODE_AVX = 3,
    MODE_AVX2 = 4,
    MODE_AVX512 = 5
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
    KERNEL_AVX512_INT = 9
} kernel_flavor_t;

typedef struct {
    uint64_t verify_passes;
    uint64_t error_count;
    uint64_t canary_passes;
    uint64_t first_error_iteration;
    uint64_t first_error_expected;
    uint64_t first_error_actual;
    int first_error_recorded;
    char first_error_kind[32];
} worker_stats_t;

typedef struct {
    int worker_index;
    int cpu_count;
    stress_mode_t mode;
    kernel_flavor_t kernel_flavor;
    worker_stats_t *stats;
} worker_args_t;

static volatile sig_atomic_t keep_running = 1;
static volatile uint64_t vector_sink_u64 = 0;
static const char *result_file_path = NULL;

static void handle_signal(int signum) {
    (void)signum;
    keep_running = 0;
}

static void bind_worker_to_cpu(int worker_index, int cpu_count) {
#ifdef __linux__
    if (cpu_count <= 0) {
        return;
    }
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(worker_index % cpu_count, &set);
    (void)pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
#else
    (void)worker_index;
    (void)cpu_count;
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

static void update_checksum_stats(worker_stats_t *stats, uint64_t checksum, uint64_t *last_checksum, unsigned int *repeat_count) {
    if (stats == NULL) {
        return;
    }
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

static int cpu_supports_fma(void) {
#if defined(__x86_64__) || defined(__i386__)
    return __builtin_cpu_supports("fma");
#else
    return 0;
#endif
}

static stress_mode_t resolve_mode(stress_mode_t requested) {
#if defined(__x86_64__) || defined(__i386__)
    if (requested == MODE_AUTO) {
        if (__builtin_cpu_supports("avx512f")) {
            return MODE_AVX512;
        }
        if (__builtin_cpu_supports("avx2")) {
            return MODE_AVX2;
        }
        if (__builtin_cpu_supports("avx")) {
            return MODE_AVX;
        }
        if (__builtin_cpu_supports("sse2")) {
            return MODE_SSE;
        }
        return MODE_SCALAR;
    }
    if (
        requested == MODE_AVX512 &&
        !__builtin_cpu_supports("avx512f")
    ) {
        return MODE_AVX2;
    }
    if (requested == MODE_AVX2 && !__builtin_cpu_supports("avx2")) {
        return MODE_AVX;
    }
    if (requested == MODE_AVX && !__builtin_cpu_supports("avx")) {
        return MODE_SSE;
    }
    if (requested == MODE_SSE && !__builtin_cpu_supports("sse2")) {
        return MODE_SCALAR;
    }
    return requested;
#else
    (void)requested;
    return MODE_SCALAR;
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
    return KERNEL_UNSPECIFIED;
}

static int kernel_flavor_supported(kernel_flavor_t flavor) {
    switch (flavor) {
        case KERNEL_SCALAR:
            return 1;
        case KERNEL_SSE2:
        case KERNEL_SSE2_INT:
#if defined(__x86_64__) || defined(__i386__)
            return __builtin_cpu_supports("sse2");
#else
            return 0;
#endif
        case KERNEL_AVX:
#if defined(__x86_64__) || defined(__i386__)
            return __builtin_cpu_supports("avx");
#else
            return 0;
#endif
        case KERNEL_AVX_FMA:
#if defined(__x86_64__) || defined(__i386__)
            return __builtin_cpu_supports("avx") && cpu_supports_fma();
#else
            return 0;
#endif
        case KERNEL_AVX2:
#if defined(__x86_64__) || defined(__i386__)
            return __builtin_cpu_supports("avx2");
#else
            return 0;
#endif
        case KERNEL_AVX2_FMA:
#if defined(__x86_64__) || defined(__i386__)
            return __builtin_cpu_supports("avx2") && cpu_supports_fma();
#else
            return 0;
#endif
        case KERNEL_AVX512_FMA:
        case KERNEL_AVX512_INT:
#if defined(__x86_64__) || defined(__i386__)
            return __builtin_cpu_supports("avx512f");
#else
            return 0;
#endif
        case KERNEL_UNSPECIFIED:
        default:
            return 0;
    }
}

static stress_mode_t mode_for_kernel_flavor(kernel_flavor_t flavor) {
    switch (flavor) {
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
        case MODE_AUTO:
        case MODE_SCALAR:
        default:
            return KERNEL_SCALAR;
    }
}

static void *worker_main(void *opaque) {
    worker_args_t *args = (worker_args_t *)opaque;
    bind_worker_to_cpu(args->worker_index, args->cpu_count);
    kernel_flavor_t flavor = args->kernel_flavor;
    if (flavor == KERNEL_UNSPECIFIED) {
        flavor = default_kernel_flavor(args->mode);
    }
    uint32_t seed = (uint32_t)(args->worker_index + 1);

    switch (flavor) {
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
    return MODE_AUTO;
}

static void print_usage(const char *argv0) {
    fprintf(
        stderr,
        "Usage: %s [--mode auto|scalar|sse|avx|avx2|avx512] [--kernel-flavor scalar|sse2|sse2_int|avx|avx_fma|avx2|avx2_fma|avx512_fma|avx512_int] [--threads N] [--print-resolved-mode] [--print-kernel-flavor] [--result-file <path>]\n",
        argv0
    );
}

static void write_result_file(
    const char *path,
    stress_mode_t mode,
    kernel_flavor_t kernel_flavor,
    int threads,
    uint64_t verify_passes,
    uint64_t canary_passes,
    uint64_t error_count,
    const worker_stats_t *worker_stats
) {
    if (path == NULL || *path == '\0') {
        return;
    }
    FILE *handle = fopen(path, "w");
    if (handle == NULL) {
        return;
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
        "  \"threads_detail\": [\n",
        error_count == 0 ? "ok" : "error",
        mode_name(mode),
        kernel_flavor_name(kernel_flavor),
        threads,
        verify_passes,
        canary_passes,
        error_count
    );
    for (int index = 0; index < threads; ++index) {
        fprintf(
            handle,
            "    {\n"
            "      \"thread_index\": %d,\n"
            "      \"verify_passes\": %" PRIu64 ",\n"
            "      \"canary_passes\": %" PRIu64 ",\n"
            "      \"error_count\": %" PRIu64,
            index,
            worker_stats[index].verify_passes,
            worker_stats[index].canary_passes,
            worker_stats[index].error_count
        );
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
        if (strcmp(argv[i], "--result-file") == 0 && i + 1 < argc) {
            result_file_path = argv[++i];
            continue;
        }
        print_usage(argv[0]);
        return 2;
    }

    if (print_resolved_mode) {
        if (kernel_flavor != KERNEL_UNSPECIFIED) {
            if (!kernel_flavor_supported(kernel_flavor)) {
                fprintf(stderr, "kernel flavor not supported on this CPU\n");
                return 3;
            }
            puts(mode_name(mode_for_kernel_flavor(kernel_flavor)));
            return 0;
        }
        puts(mode_name(resolve_mode(mode)));
        return 0;
    }

    if (print_kernel_flavor) {
        kernel_flavor_t resolved_flavor = kernel_flavor;
        if (resolved_flavor == KERNEL_UNSPECIFIED) {
            resolved_flavor = default_kernel_flavor(mode);
        }
        if (!kernel_flavor_supported(resolved_flavor)) {
            fprintf(stderr, "kernel flavor not supported on this CPU\n");
            return 3;
        }
        puts(kernel_flavor_name(resolved_flavor));
        return 0;
    }

    if (kernel_flavor != KERNEL_UNSPECIFIED && !kernel_flavor_supported(kernel_flavor)) {
        fprintf(stderr, "kernel flavor not supported on this CPU\n");
        return 3;
    }

    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);

    pthread_t *workers = calloc((size_t)threads, sizeof(*workers));
    worker_args_t *worker_args = calloc((size_t)threads, sizeof(*worker_args));
    worker_stats_t *worker_stats = calloc((size_t)threads, sizeof(*worker_stats));
    if (workers == NULL || worker_args == NULL || worker_stats == NULL) {
        fprintf(stderr, "allocation failure\n");
        free(workers);
        free(worker_args);
        free(worker_stats);
        return 1;
    }

    for (int i = 0; i < threads; ++i) {
        worker_args[i].worker_index = i;
        worker_args[i].cpu_count = threads;
        worker_args[i].mode = mode;
        worker_args[i].kernel_flavor = kernel_flavor;
        worker_args[i].stats = &worker_stats[i];
        if (pthread_create(&workers[i], NULL, worker_main, &worker_args[i]) != 0) {
            fprintf(stderr, "pthread_create failed: %s\n", strerror(errno));
            keep_running = 0;
            threads = i;
            break;
        }
    }

    while (keep_running) {
        sleep(1);
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
        total_verify_passes += worker_stats[i].verify_passes;
        total_canary_passes += worker_stats[i].canary_passes;
        total_error_count += worker_stats[i].error_count;
    }
    write_result_file(result_file_path, resolve_mode(mode), resolved_flavor, threads, total_verify_passes, total_canary_passes, total_error_count, worker_stats);
    free(workers);
    free(worker_args);
    free(worker_stats);
    return total_error_count == 0 ? 0 : 4;
}
