/* Deterministic unit entry points, not a physical workload harness.
 * Compile without ARM emulation: no local test claims NEON instruction use. */
#define main lvs_cpu_helper_main
#define LVS_CPU_HELPER_TEST_FP32_REFERENCE 1
#include "../native/cpu_stress_helper.c"
#undef main

int reference_fma(uint32_t a, uint32_t b, uint32_t c, uint32_t *result) {
    return fp32_fma_reference(a, b, c, result);
}

int environment_check(uint64_t fpcr) {
    return fp32_environment_supported(fpcr);
}

int lost_affinity_check(void) {
    worker_stats_t stats = {.affinity_target_cpu = -1, .affinity_applied = 1};
    return !fp32_check_affinity(&stats) && stats.error_count == 1 &&
        strcmp(stats.first_error_kind, "affinity_lost") == 0;
}

int reference_case(uint32_t seed, int which, uint32_t *output) {
    fp32_fma_case_t cases[FP32_FMA_CASES];
    if (!prepare_fp32_fma_cases(cases, seed)) return 0;
    memcpy(output, cases[which].expected, sizeof(cases[which].expected));
    return 1;
}

#ifdef LVS_CPU_HELPER_TEST_SVE
int sve_reference_case(uint32_t seed, int which, int lanes, uint32_t *output) {
    keep_running = 1;
    if (lanes < 4 || lanes > 64 || lanes % 4 || which < 0 || which >= 4) return 0;
    size_t count = (size_t)lanes * 8;
    uint32_t *data = calloc(4 * count * 4, sizeof(*data));
    if (!data) return 0;
    int success = prepare_sve_fp32_cases(data, count, seed);
    if (success) memcpy(output, data + which * count * 4 + count * 3, count * sizeof(*data));
    free(data);
    return success;
}

int scalable_lane_check(int lanes, int corrupt) {
    keep_running = 1;
    worker_stats_t stats = {0};
    uint32_t actual[512], expected[512];
    if (lanes < 4 || lanes > 64 || lanes % 4 || corrupt < 0 || corrupt >= lanes * 8) return -1;
    for (int i = 0; i < lanes * 8; ++i) actual[i] = expected[i] = 0x3f000000U + i;
    actual[corrupt] ^= 1U;
    return verify_fp32_fma_lanes(&stats, actual, expected, lanes * 8, 0) ? -1 : stats.first_error_lane;
}
#endif

int lane_check(int lane, uint32_t corrupt) {
    worker_stats_t stats = {0};
    uint32_t actual[FP32_FMA_LANES], expected[FP32_FMA_LANES];
    for (int i = 0; i < FP32_FMA_LANES; ++i) actual[i] = expected[i] = 0x3f000000U + (uint32_t)i;
    if (lane >= 0) actual[lane] = corrupt;
    int success = verify_fp32_fma_lanes(&stats, actual, expected, FP32_FMA_LANES, 7);
    return success ? -1 : stats.first_error_lane;
}
