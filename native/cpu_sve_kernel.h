/* Included only inside the CPU helper: no separate worker or build system.
 * Baseline code never takes scalable-vector arguments or enables SVE globally. */
#if defined(LVS_CPU_HELPER_ENABLE_SVE) && defined(__aarch64__) && defined(__linux__)
#pragma GCC push_options
#pragma GCC target("+sve")
#include <arm_sve.h>

__attribute__((noinline))
static int execute_sve_fp32_block(const uint32_t *initial, const uint32_t *multiplier,
                                 const uint32_t *addend, uint32_t *output,
                                 int lanes, int final) {
    if ((int)svcntw() != lanes) return -1;
    svbool_t pg = svptrue_b32();
#define SVE_LOAD(N) \
    svfloat32_t x##N = svreinterpret_f32_u32(svld1_u32(pg, initial + lanes*N)); \
    svfloat32_t a##N = svreinterpret_f32_u32(svld1_u32(pg, multiplier + lanes*N)); \
    svfloat32_t b##N = svreinterpret_f32_u32(svld1_u32(pg, addend + lanes*N))
    SVE_LOAD(0); SVE_LOAD(1); SVE_LOAD(2); SVE_LOAD(3);
    SVE_LOAD(4); SVE_LOAD(5); SVE_LOAD(6); SVE_LOAD(7);
#undef SVE_LOAD
    for (int round = 0; round < FP32_FMA_ROUNDS; ++round) {
        if ((round & 31) == 0 && !final && !keep_running) return 0;
        x0 = svmla_f32_m(pg, b0, x0, a0); x1 = svmla_f32_m(pg, b1, x1, a1);
        x2 = svmla_f32_m(pg, b2, x2, a2); x3 = svmla_f32_m(pg, b3, x3, a3);
        x4 = svmla_f32_m(pg, b4, x4, a4); x5 = svmla_f32_m(pg, b5, x5, a5);
        x6 = svmla_f32_m(pg, b6, x6, a6); x7 = svmla_f32_m(pg, b7, x7, a7);
        __asm__ volatile("" : "+w"(x0), "+w"(x1), "+w"(x2), "+w"(x3),
                             "+w"(x4), "+w"(x5), "+w"(x6), "+w"(x7));
    }
#define SVE_STORE(N) svst1_u32(pg, output + lanes*N, svreinterpret_u32_f32(x##N))
    SVE_STORE(0); SVE_STORE(1); SVE_STORE(2); SVE_STORE(3);
    SVE_STORE(4); SVE_STORE(5); SVE_STORE(6); SVE_STORE(7);
#undef SVE_STORE
    return 1;
}

/* Four active fused witnesses; remaining lanes must retain the merge operand.
 * A masked store must leave all inactive destinations and both guards intact. */
__attribute__((noinline))
static void execute_sve_witness(const uint32_t *a, const uint32_t *b, const uint32_t *c,
                                uint32_t *all, uint32_t *masked) {
    svbool_t full = svptrue_b32(), pg = svwhilelt_b32((uint64_t)0, (uint64_t)4);
    svfloat32_t va = svreinterpret_f32_u32(svld1_u32(full, a));
    svfloat32_t vb = svreinterpret_f32_u32(svld1_u32(full, b));
    svfloat32_t vc = svreinterpret_f32_u32(svld1_u32(full, c));
    __asm__ volatile("" : "+w"(va), "+w"(vb), "+w"(vc));
    svfloat32_t value = svmla_f32_m(pg, vc, va, vb);
    svst1_u32(full, all, svreinterpret_u32_f32(value));
    svst1_u32(pg, masked + 1, svreinterpret_u32_f32(value));
}
#pragma GCC pop_options

#elif defined(LVS_CPU_HELPER_TEST_SVE)
/* Explicitly labelled integer emulation: lifecycle/reference tests, never ISA proof. */
static int execute_sve_fp32_block(const uint32_t *initial, const uint32_t *multiplier,
                                 const uint32_t *addend, uint32_t *output,
                                 int lanes, int final) {
#if defined(LVS_CPU_HELPER_TEST_INTERRUPT_FP32_BLOCK)
    static _Thread_local unsigned calls;
    if (!final && ++calls == 3) { keep_running = 0; return 0; }
#endif
    memcpy(output, initial, (size_t)lanes * 8 * sizeof(*output));
    for (int round = 0; round < FP32_FMA_ROUNDS; ++round) {
        if (!final && !keep_running) return 0;
        for (int lane = 0; lane < lanes * 8; ++lane)
            if (!fp32_fma_reference(output[lane], multiplier[lane], addend[lane], &output[lane])) return -1;
    }
    return 1;
}
static void execute_sve_witness(const uint32_t *a, const uint32_t *b, const uint32_t *c,
                                uint32_t *all, uint32_t *masked) {
    /* Caller fills inactive merge values; emulation does not claim predicates executed. */
    for (int lane = 0; lane < 4; ++lane) {
        fp32_fma_reference(a[lane], b[lane], c[lane], &all[lane]);
#if defined(LVS_CPU_HELPER_TEST_UNFUSED_FP32)
        uint32_t product;
        fp32_fma_reference(a[lane], b[lane], 0, &product);
        fp32_fma_reference(product, 0x3f800000U, c[lane], &all[lane]);
#endif
        masked[lane + 1] = all[lane];
    }
#if defined(LVS_CPU_HELPER_TEST_BAD_SVE_MASK)
    masked[0] = 0;
#endif
#if defined(LVS_CPU_HELPER_TEST_BAD_SVE_MERGE)
    all[4] = 0;
#endif
}
#endif
