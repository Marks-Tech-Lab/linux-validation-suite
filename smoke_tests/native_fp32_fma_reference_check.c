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

int lane_check(int lane, uint32_t corrupt) {
    worker_stats_t stats = {0};
    uint32_t actual[FP32_FMA_LANES], expected[FP32_FMA_LANES];
    for (int i = 0; i < FP32_FMA_LANES; ++i) actual[i] = expected[i] = 0x3f000000U + (uint32_t)i;
    if (lane >= 0) actual[lane] = corrupt;
    int success = verify_fp32_fma_lanes(&stats, actual, expected, FP32_FMA_LANES, 7);
    return success ? -1 : stats.first_error_lane;
}
