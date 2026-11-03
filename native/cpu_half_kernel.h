/* Explicit-only fixed-width FP16/FHM. Exact finite IEEE reference uses integer
 * significands, one RN-even rounding, no host FP arithmetic or tolerances. */
#define HALF_CHAINS 8
#define HALF_ROUNDS 256
#define HALF_CASES 4
#define HALF_FPCR_MASK ((3ULL<<22)|(1ULL<<24)|(1ULL<<19)|(1ULL<<26)|(31ULL<<8)|(1ULL<<15)|3ULL)

static int half_capability(uint64_t h, int wide) {
    uint64_t required=3ULL | (1ULL << (wide ? 23 : 10));
    return (h & required)==required;
}
static int cpu_supports_neon_half(int wide) {
#if defined(LVS_CPU_HELPER_TEST_HALF)
# if defined(LVS_CPU_HELPER_TEST_DISABLE_HALF)
    (void)wide; return 0;
# else
    (void)wide; return 1;
# endif
#elif defined(__aarch64__) && defined(__linux__)
    if (wide) {
# if defined(LVS_CPU_HELPER_ENABLE_FHM)
        return half_capability(getauxval(AT_HWCAP),1);
# endif
    } else {
# if defined(LVS_CPU_HELPER_ENABLE_FP16)
        return half_capability(getauxval(AT_HWCAP),0);
# endif
    }
    return 0;
#else
    (void)wide; return 0;
#endif
}

static int half_bits(unsigned __int128 value) {
    int bits=0; while (value) { ++bits; value>>=1; } return bits;
}
static int half_decode(uint32_t bits,int precision,int *sign,int *exp,uint32_t *mant) {
    int fraction=precision-1,ebits=precision==11 ? 5:8,bias=precision==11 ? 15:127;
    uint32_t e=(bits>>fraction)&((1U<<ebits)-1),f=bits&((1U<<fraction)-1);
    if (e==((1U<<ebits)-1)) return 0; /* NaN/Inf outside finite workload domain. */
    *sign=(bits>>(fraction+ebits))&1; *mant=e ? (1U<<fraction)|f:f;
    *exp=(e ? (int)e-bias:1-bias)-fraction; return 1;
}
static int half_fma_reference(uint16_t a,uint16_t b,uint32_t c,int wide,uint32_t *out) {
    int sa,sb,sc,ea,eb,ec; uint32_t ma,mb,mc;
    int precision=wide ? 24:11,bias=wide ? 127:15,minexp=1-bias-(precision-1);
    if (!half_decode(a,11,&sa,&ea,&ma) || !half_decode(b,11,&sb,&eb,&mb)
        || !half_decode(c,precision,&sc,&ec,&mc)) return 0;
    unsigned __int128 product=(unsigned __int128)ma*mb;
    int ep=ea+eb,base=!product ? ec:!mc ? ep:ep<ec ? ep:ec;
    int ps=product ? ep-base:0,cs=mc ? ec-base:0;
    /* Explicit bounded exact domain; reject, never approximate a wide gap. */
    if (ps<0 || cs<0 || ps>124 || cs>124
        || half_bits(product)+ps>125 || half_bits(mc)+cs>125) return 0;
    __int128 left=(__int128)(product<<ps),right=(__int128)((unsigned __int128)mc<<cs);
    if (sa^sb) left=-left;
    if (sc) right=-right;
    __int128 sum=left+right;
    int sign=sum<0; unsigned __int128 mag=sign ? (unsigned __int128)(-sum):(unsigned __int128)sum;
    if (!mag) { *out=((sa^sb)&sc) << (wide ? 31:15); return 1; }
    int quantum=base+half_bits(mag)-precision;
    if (quantum<minexp) quantum=minexp;
    int shift=quantum-base; unsigned __int128 rounded;
    if (shift>0) {
        if (shift>=128) return 0;
        unsigned __int128 mask=(((unsigned __int128)1)<<shift)-1;
        unsigned __int128 remainder=mag&mask,mid=((unsigned __int128)1)<<(shift-1);
        rounded=mag>>shift;
        rounded+=(remainder>mid || (remainder==mid && (rounded&1)));
    } else {
        if (-shift>=128 || half_bits(mag)-shift>125) return 0;
        rounded=mag<<(-shift);
    }
    if (half_bits(rounded)>precision) { rounded>>=1; ++quantum; }
    if (quantum+precision-1>bias) return 0; /* No accidental overflow. */
    uint32_t e=rounded>=((unsigned __int128)1<<(precision-1)) ? (uint32_t)(quantum+precision-1+bias):0;
    *out=((uint32_t)sign<<(wide ? 31:15)) | (e<<(precision-1))
        | ((uint32_t)rounded&((1U<<(precision-1))-1));
    return 1;
}

typedef struct {
    uint16_t a[32],b[32],narrow[64];
    uint32_t wide[64],expected[64],witness[64];
} half_case_t;

static int prepare_half_cases(half_case_t *cases,uint32_t seed,int wide) {
    static const uint16_t av[]={0x2401,0xa001,0x7bff,0x0001,0x3555,0x3c01,0xbc01,0x0400};
    int lanes=wide ? 4:8;
    for (int k=0;k<HALF_CASES;++k) {
        half_case_t *c=&cases[k];
        for (int n=0;n<32;++n) {
            c->a[n]=av[((uint32_t)n+seed+k)%8];
            c->b[n]=(c->a[n]&0x7fff)==0x7bff ? 1:(c->a[n]&0x7fff)==1 ? 0x3c00:(n&1) ? 0x2c03:0x3c01;
        }
        /* A fused-rounding witness: (1+2^-10)^2 - (1+2^-9).
         * Binary16 unfused multiplication loses the 2^-20 residual. */
        c->a[0]=c->b[0]=0x3c01;
        for (int chain=0;chain<8;++chain) for (int lane=0;lane<lanes;++lane) {
            int n=chain*lanes+lane,src=(chain/2)*8+(wide ? 4*(chain%2):0)+lane;
            c->narrow[n]=(n&1) ? 0xb801:0x3801;
            c->wide[n]=(n&1) ? 0xbf000001:0x3f000001;
            if ((c->a[src]&0x7fff)==1) c->narrow[n]=c->wide[n]=0;
            if (src==0) { c->narrow[n]=0xbc02; c->wide[n]=0xbf804000; }
            uint32_t value=wide ? c->wide[n]:c->narrow[n];
            if (!half_fma_reference(c->a[src],c->b[src],value,wide,&c->witness[n])) return 0;
            for (int r=0;r<HALF_ROUNDS;++r)
                if (!half_fma_reference(c->a[src],c->b[src],value,wide,&value)) return 0;
            c->expected[n]=value;
        }
    }
    return 1;
}

#if defined(LVS_CPU_HELPER_ENABLE_FP16) && defined(__aarch64__) && defined(__linux__)
#if !defined(__clang__)
#pragma GCC push_options
#pragma GCC target("+fp16")
__attribute__((noinline,noclone))
#else
__attribute__((noinline,target("fullfp16")))
#endif
static int execute_neon_fp16_block(const half_case_t *input,uint32_t *output,int rounds,int final) {
    uint16x8_t a0=vld1q_u16(input->a+0), b0=vld1q_u16(input->b+0);
    uint16x8_t a1=vld1q_u16(input->a+8), b1=vld1q_u16(input->b+8);
    uint16x8_t a2=vld1q_u16(input->a+16), b2=vld1q_u16(input->b+16);
    uint16x8_t a3=vld1q_u16(input->a+24), b3=vld1q_u16(input->b+24);
    uint16x8_t x0=vld1q_u16(input->narrow+0);
    uint16x8_t x1=vld1q_u16(input->narrow+8);
    uint16x8_t x2=vld1q_u16(input->narrow+16);
    uint16x8_t x3=vld1q_u16(input->narrow+24);
    uint16x8_t x4=vld1q_u16(input->narrow+32);
    uint16x8_t x5=vld1q_u16(input->narrow+40);
    uint16x8_t x6=vld1q_u16(input->narrow+48);
    uint16x8_t x7=vld1q_u16(input->narrow+56);
    unsigned count,alive;
    __asm__ volatile(
        ".arch_extension fp16\n"
        "// LVS_HALF_BEGIN\n"
        "mov %w[count], wzr\n"
        "1: tst %w[count], #31\n"
        "b.ne 2f\n"
        "cbnz %w[final], 2f\n"
        "ldr %w[alive], [%[running]]\n"
        "cbz %w[alive], 3f\n"
        "2:\n"
        "fmla %[x0].8h, %[a0].8h, %[b0].8h\n"
        "fmla %[x1].8h, %[a0].8h, %[b0].8h\n"
        "fmla %[x2].8h, %[a1].8h, %[b1].8h\n"
        "fmla %[x3].8h, %[a1].8h, %[b1].8h\n"
        "fmla %[x4].8h, %[a2].8h, %[b2].8h\n"
        "fmla %[x5].8h, %[a2].8h, %[b2].8h\n"
        "fmla %[x6].8h, %[a3].8h, %[b3].8h\n"
        "fmla %[x7].8h, %[a3].8h, %[b3].8h\n"
        "add %w[count], %w[count], #1\n"
        "cmp %w[count], %w[rounds]\n"
        "b.ne 1b\n"
        "3:\n"
        "// LVS_HALF_END\n"
        : [x0] "+&w"(x0), [x1] "+&w"(x1), [x2] "+&w"(x2), [x3] "+&w"(x3), [x4] "+&w"(x4), [x5] "+&w"(x5), [x6] "+&w"(x6), [x7] "+&w"(x7), [count] "=&r"(count), [alive] "=&r"(alive)
        : [a0] "w"(a0), [b0] "w"(b0), [a1] "w"(a1), [b1] "w"(b1), [a2] "w"(a2), [b2] "w"(b2), [a3] "w"(a3), [b3] "w"(b3),
          [rounds] "r"(rounds), [final] "r"(final), [running] "r"(&keep_running)
        : "cc", "memory");
    if (count!=(unsigned)rounds) return 0;
    vst1q_u32(output+0,vmovl_u16(vget_low_u16(x0)));
    vst1q_u32(output+4,vmovl_high_u16(x0));
    vst1q_u32(output+8,vmovl_u16(vget_low_u16(x1)));
    vst1q_u32(output+12,vmovl_high_u16(x1));
    vst1q_u32(output+16,vmovl_u16(vget_low_u16(x2)));
    vst1q_u32(output+20,vmovl_high_u16(x2));
    vst1q_u32(output+24,vmovl_u16(vget_low_u16(x3)));
    vst1q_u32(output+28,vmovl_high_u16(x3));
    vst1q_u32(output+32,vmovl_u16(vget_low_u16(x4)));
    vst1q_u32(output+36,vmovl_high_u16(x4));
    vst1q_u32(output+40,vmovl_u16(vget_low_u16(x5)));
    vst1q_u32(output+44,vmovl_high_u16(x5));
    vst1q_u32(output+48,vmovl_u16(vget_low_u16(x6)));
    vst1q_u32(output+52,vmovl_high_u16(x6));
    vst1q_u32(output+56,vmovl_u16(vget_low_u16(x7)));
    vst1q_u32(output+60,vmovl_high_u16(x7));
    return 1;
}
#if !defined(__clang__)
#pragma GCC pop_options
#endif
#endif

#if defined(LVS_CPU_HELPER_ENABLE_FHM) && defined(__aarch64__) && defined(__linux__)
#if !defined(__clang__)
#pragma GCC push_options
#pragma GCC target("+fp16fml")
__attribute__((noinline,noclone))
#else
__attribute__((noinline,target("fp16fml")))
#endif
static int execute_neon_fhm_block(const half_case_t *input,uint32_t *output,int rounds,int final) {
    uint16x8_t a0=vld1q_u16(input->a+0), b0=vld1q_u16(input->b+0);
    uint16x8_t a1=vld1q_u16(input->a+8), b1=vld1q_u16(input->b+8);
    uint16x8_t a2=vld1q_u16(input->a+16), b2=vld1q_u16(input->b+16);
    uint16x8_t a3=vld1q_u16(input->a+24), b3=vld1q_u16(input->b+24);
    uint32x4_t x0=vld1q_u32(input->wide+0);
    uint32x4_t x1=vld1q_u32(input->wide+4);
    uint32x4_t x2=vld1q_u32(input->wide+8);
    uint32x4_t x3=vld1q_u32(input->wide+12);
    uint32x4_t x4=vld1q_u32(input->wide+16);
    uint32x4_t x5=vld1q_u32(input->wide+20);
    uint32x4_t x6=vld1q_u32(input->wide+24);
    uint32x4_t x7=vld1q_u32(input->wide+28);
    unsigned count,alive;
    __asm__ volatile(
        ".arch_extension fp16fml\n"
        "// LVS_HALF_BEGIN\n"
        "mov %w[count], wzr\n"
        "1: tst %w[count], #31\n"
        "b.ne 2f\n"
        "cbnz %w[final], 2f\n"
        "ldr %w[alive], [%[running]]\n"
        "cbz %w[alive], 3f\n"
        "2:\n"
        "fmlal %[x0].4s, %[a0].4h, %[b0].4h\n"
        "fmlal2 %[x1].4s, %[a0].4h, %[b0].4h\n"
        "fmlal %[x2].4s, %[a1].4h, %[b1].4h\n"
        "fmlal2 %[x3].4s, %[a1].4h, %[b1].4h\n"
        "fmlal %[x4].4s, %[a2].4h, %[b2].4h\n"
        "fmlal2 %[x5].4s, %[a2].4h, %[b2].4h\n"
        "fmlal %[x6].4s, %[a3].4h, %[b3].4h\n"
        "fmlal2 %[x7].4s, %[a3].4h, %[b3].4h\n"
        "add %w[count], %w[count], #1\n"
        "cmp %w[count], %w[rounds]\n"
        "b.ne 1b\n"
        "3:\n"
        "// LVS_HALF_END\n"
        : [x0] "+&w"(x0), [x1] "+&w"(x1), [x2] "+&w"(x2), [x3] "+&w"(x3), [x4] "+&w"(x4), [x5] "+&w"(x5), [x6] "+&w"(x6), [x7] "+&w"(x7), [count] "=&r"(count), [alive] "=&r"(alive)
        : [a0] "w"(a0), [b0] "w"(b0), [a1] "w"(a1), [b1] "w"(b1), [a2] "w"(a2), [b2] "w"(b2), [a3] "w"(a3), [b3] "w"(b3),
          [rounds] "r"(rounds), [final] "r"(final), [running] "r"(&keep_running)
        : "cc", "memory");
    if (count!=(unsigned)rounds) return 0;
    vst1q_u32(output+0,x0);
    vst1q_u32(output+4,x1);
    vst1q_u32(output+8,x2);
    vst1q_u32(output+12,x3);
    vst1q_u32(output+16,x4);
    vst1q_u32(output+20,x5);
    vst1q_u32(output+24,x6);
    vst1q_u32(output+28,x7);
    return 1;
}
#if !defined(__clang__)
#pragma GCC pop_options
#endif
#endif

static int execute_half_block(const half_case_t *c,uint32_t *out,int wide,int rounds,int final) {
#if defined(LVS_CPU_HELPER_TEST_HALF)
    int lanes=wide ? 4:8;
    for (int i=0;i<8*lanes;++i) out[i]=wide ? c->wide[i]:c->narrow[i];
    for (int r=0;r<rounds;++r) {
        if (!final && !keep_running) return 0;
        for (int n=0;n<8*lanes;++n) {
            int chain=n/lanes,src=(chain/2)*8+(wide ? 4*(chain%2):0)+n%lanes;
            if (!half_fma_reference(c->a[src],c->b[src],out[n],wide,&out[n])) return -1;
        }
    }
    return 1;
#else
# if defined(LVS_CPU_HELPER_ENABLE_FHM) && defined(__aarch64__) && defined(__linux__)
    if (wide) return execute_neon_fhm_block(c,out,rounds,final);
# endif
# if defined(LVS_CPU_HELPER_ENABLE_FP16) && defined(__aarch64__) && defined(__linux__)
    if (!wide) return execute_neon_fp16_block(c,out,rounds,final);
# endif
    (void)c; (void)out; (void)wide; (void)rounds; (void)final; return -1;
#endif
}
static uint64_t half_read_fpcr(void) {
#if defined(LVS_CPU_HELPER_TEST_HALF)
    return 0;
#elif defined(__aarch64__) && defined(__linux__)
    uint64_t value; __asm__ volatile("mrs %0, fpcr":"=r"(value)); return value;
#else
    return UINT64_MAX;
#endif
}
static int half_check_affinity(worker_stats_t *stats) {
    stats->observed_cpu=sched_getcpu();
    if (stats->affinity_applied && stats->observed_cpu==stats->affinity_target_cpu) return 1;
    record_worker_error(stats,"affinity_lost",stats->arithmetic_verified_blocks,stats->affinity_target_cpu,stats->observed_cpu);
    keep_running=0; return 0;
}
static void run_neon_half_loop(uint32_t seed,worker_stats_t *stats,int wide) {
    stats->fpcr=half_read_fpcr();
#if defined(LVS_CPU_HELPER_TEST_HALF_BAD_FPCR)
    stats->fpcr=1ULL<<19;
#endif
#if defined(LVS_CPU_HELPER_TEST_HALF)
    stats->half_hwcap=3ULL|(1ULL<<(wide ? 23:10));
#else
# if defined(__aarch64__) && defined(__linux__)
    stats->half_hwcap=getauxval(AT_HWCAP);
# endif
#endif
#if defined(LVS_CPU_HELPER_TEST_HALF_CAPABILITY_LOST)
    stats->half_hwcap=3;
#endif
    if (!half_capability(stats->half_hwcap,wide)) {
        record_worker_error(stats,"half_capability_lost",0,3ULL|(1ULL<<(wide ? 23:10)),stats->half_hwcap); keep_running=0; return;
    }
    if (stats->fpcr&HALF_FPCR_MASK) {
        record_worker_error(stats,"half_fp_environment",0,0,stats->fpcr); keep_running=0; return;
    }
    half_case_t cases[HALF_CASES]; uint32_t output[66]; int lanes=wide ? 4:8;
    if (!prepare_half_cases(cases,seed,wide)) {
        record_worker_error(stats,"half_reference_domain",0,1,0); keep_running=0; return;
    }
    for (;;) {
        int final=!keep_running;
        if (stats->error_count || (final && !stats->initial_verification_completed)) break;
        if (!half_check_affinity(stats)) break;
#if defined(LVS_CPU_HELPER_TEST_HALF_MIGRATION)
        ++stats->observed_cpu;
        record_worker_error(stats,"affinity_lost",0,stats->affinity_target_cpu,stats->observed_cpu); keep_running=0; break;
#endif
        if (half_read_fpcr()!=stats->fpcr) {
            record_worker_error(stats,"half_fpcr_changed",0,stats->fpcr,half_read_fpcr()); keep_running=0; break;
        }
        const half_case_t *c=&cases[(stats->arithmetic_verified_blocks+seed)%HALF_CASES];
        int complete=1;
        for (int witness=0;witness<2 && complete>0;++witness) {
            output[0]=0x98765432U; output[8*lanes+1]=0x12345678U;
            complete=execute_half_block(c,output+1,wide,witness ? 1:HALF_ROUNDS,final);
#if defined(LVS_CPU_HELPER_TEST_HALF_INTERRUPT)
            if (!final && stats->arithmetic_verified_blocks==2) { keep_running=0; complete=0; }
#endif
            if (complete<=0) break;
            const uint32_t *expected=witness ? c->witness:c->expected;
#if defined(LVS_CPU_HELPER_TEST_HALF_CORRUPT)
            output[1]^=1;
#endif
#if defined(LVS_CPU_HELPER_TEST_HALF_CORRUPT_LANE)
            output[1+LVS_CPU_HELPER_TEST_HALF_CORRUPT_LANE]^=1;
#endif
#if defined(LVS_CPU_HELPER_TEST_HALF_CORRUPT_PERIODIC)
            if (!final && stats->arithmetic_verified_blocks==2) output[2]^=1;
#endif
#if defined(LVS_CPU_HELPER_TEST_HALF_CORRUPT_FINAL)
            if (final) output[3]^=1;
#endif
#if defined(LVS_CPU_HELPER_TEST_HALF_CORRUPT_WITNESS)
            if (witness) output[1]^=1;
#endif
#if defined(LVS_CPU_HELPER_TEST_HALF_CORRUPT_GUARD)
            output[0]^=1;
#endif
            if (output[0]!=0x98765432U || output[8*lanes+1]!=0x12345678U)
                record_worker_error(stats,"half_store_guard",0,1,0);
            for (int n=0;n<8*lanes && !stats->error_count;++n)
                if (output[n+1]!=expected[n]) {
                    stats->first_error_lane=n;
                    record_worker_error(stats,"half_fma_mismatch",stats->arithmetic_verified_blocks,expected[n],output[n+1]);
                }
        }
        if (complete<0) { record_worker_error(stats,"half_execution_state",0,1,0); keep_running=0; }
        if (!complete) { ++stats->interrupted_arithmetic_blocks; continue; }
        if (stats->error_count) { keep_running=0; break; }
        if (!half_check_affinity(stats)) break;
        if (half_read_fpcr()!=stats->fpcr) {
            record_worker_error(stats,"half_fpcr_changed",0,stats->fpcr,half_read_fpcr()); keep_running=0; break;
        }
        if (stats->arithmetic_verified_blocks==UINT64_MAX) {
            record_worker_error(stats,"half_counter_overflow",UINT64_MAX,0,0); keep_running=0; break;
        }
        ++stats->arithmetic_verified_blocks; ++stats->verify_passes;
        if (final) { stats->final_verification_completed=1; publish_verified_progress(stats,1); break; }
        int initial=!stats->initial_verification_completed;
        if (initial) stats->initial_verification_completed=1; else stats->periodic_verification_completed=1;
        publish_verified_progress(stats,initial);
    }
}

static void write_half_result(FILE *handle,kernel_flavor_t kernel,const worker_stats_t *stats,
                              int threads,int requested,uint64_t errors) {
    int wide=kernel==KERNEL_NEON_FHM;
    uint64_t blocks=0; int initial=threads==requested && threads>0,periodic=initial,final=initial;
    for (int i=0;i<threads;++i) {
        blocks+=stats[i].arithmetic_verified_blocks;
        initial&=stats[i].initial_verification_completed;
        periodic&=stats[i].periodic_verification_completed;
        final&=stats[i].final_verification_completed;
    }
    fprintf(handle,"  \"verification_required\":true,\"verification_version\":1,\n"
        "  \"verification_contract\":\"%s_v1\",\n"
        "  \"verification_method\":\"integer_significand_rne_fused_reference\",\n"
        "  \"operation_family\":\"%s\",\n"
        "  \"execution_implementation\":\"%s\",\"actual_isa\":\"%s\",\n"
        "  \"isa_capability_source\":\"%s\",\n"
        "  \"arithmetic_verified_blocks\":%" PRIu64 ",\n"
        "  \"accumulator_chains\":8,\"fma_rounds_per_block\":256,\"witness_rounds_per_block\":1,\n"
        "  \"active_lanes\":%d,\"input_bits\":16,\"accumulator_bits\":%d,\n"
        "  \"fhm_mapping\":\"%s\",\"comparison\":\"bit_exact\",\n"
        "  \"initial_verification_completed\":%s,\"periodic_verification_completed\":%s,\n"
        "  \"final_verification_completed\":%s,\"verification_complete\":%s,\n"
        "  \"verified_progress\":{\"contract\":\"%s_progress_v1\",\"sidecar_suffix\":\".progress.jsonl\","
        "\"snapshot_interval_seconds\":2.0,\"persistence_error\":%s,\"snapshot_count\":%lu,\"snapshot_write_seconds\":%.9f},\n",
        kernel_flavor_name(kernel),wide ? "fp16_product_fp32_fused_accumulate_low_high":"fp16_fused_multiply_add",
#if defined(LVS_CPU_HELPER_TEST_HALF)
        "test_half_emulation","test_half_emulation","test_override",
#else
        wide ? "aarch64_neon_fhm_asm":"aarch64_neon_fp16_asm",wide ? "asimdfhm":"asimdhp","linux_aarch64_hwcap_common_set",
#endif
        blocks,wide ? 4:8,wide ? 32:16,wide ? "paired_low_high_halfwords":"all_eight_halfwords",
        initial ? "true":"false",periodic ? "true":"false",final ? "true":"false",
        initial && periodic && final && !errors ? "true":"false",kernel_flavor_name(kernel),
        progress_io_error ? "true":"false",progress_sequence,progress_write_seconds);
}
