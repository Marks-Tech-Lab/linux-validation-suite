/* Explicit NEON BF16: standard EBF=0 dot/matrix plus IEEE widening FMA.
 * Independent exact finite references, not host FP or a relaxed tolerance. */
#define BF16_ROUNDS 256
#define BF16_CASES 4
#define BF16_FPCR_MASK (HALF_FPCR_MASK | (1ULL<<13))
#define BF16_WORDS 10
#define BF16_UNIT (-300)

static int bf16_capability(uint64_t h,uint64_t h2) {
    return (h&3)==3 && (h2&(1ULL<<14))!=0;
}
static int bf16_environment_supported(uint64_t fpcr) { return !(fpcr&BF16_FPCR_MASK); }
static int cpu_supports_neon_bf16(void) {
#if defined(LVS_CPU_HELPER_TEST_BF16)
# if defined(LVS_CPU_HELPER_TEST_DISABLE_BF16)
    return 0;
# else
    return 1;
# endif
#elif defined(LVS_CPU_HELPER_ENABLE_BF16) && defined(__aarch64__) && defined(__linux__)
    return bf16_capability(getauxval(AT_HWCAP),getauxval(AT_HWCAP2));
#else
    return 0;
#endif
}

typedef struct { uint64_t words[BF16_WORDS]; int negative; } bf16_exact_t;
/* Fixed 640-bit dyadics in units 2^-300 cover every finite BF16 product
 * (lowest exponent -266, highest occupied bit 255) plus any finite FP32 addend.
 * This avoids rounding/sticky errors from restricting exponent alignment. */
static int bf16_decode(uint32_t bits,int wide,int flush,int *negative,int *exponent,uint32_t *mantissa) {
    int fraction=wide ? 23:7;
    uint32_t e=(bits>>fraction)&255,f=bits&((1U<<fraction)-1);
    if (e==255) return 0;
    *negative=(bits>>(fraction+8))&1;
    *mantissa=e ? (1U<<fraction)|f:flush ? 0:f;
    *exponent=(e ? (int)e-127:-126)-fraction;
    return 1;
}
static int bf16_term(bf16_exact_t *v,uint64_t m,int exponent,int negative) {
    memset(v,0,sizeof(*v)); v->negative=negative;
    if (!m) return 1;
    int shift=exponent-BF16_UNIT;
    if (shift<0 || shift+64>BF16_WORDS*64) return 0;
    int word=shift/64,bit=shift%64;
    v->words[word]=m<<bit;
    if (bit) v->words[word+1]=m>>(64-bit);
    return 1;
}
static int bf16_exact_sum(const bf16_exact_t *a,const bf16_exact_t *b,bf16_exact_t *out) {
    memset(out,0,sizeof(*out));
    if (a->negative==b->negative) {
        uint64_t carry=0;
        for (int i=0;i<BF16_WORDS;++i) {
            unsigned __int128 sum=(unsigned __int128)a->words[i]+b->words[i]+carry;
            out->words[i]=(uint64_t)sum; carry=(uint64_t)(sum>>64);
        }
        out->negative=a->negative; return carry==0;
    }
    int cmp=0;
    for (int i=BF16_WORDS-1;i>=0;--i)
        if (a->words[i]!=b->words[i]) { cmp=a->words[i]>b->words[i] ? 1:-1; break; }
    if (!cmp) return 1; /* Exact cancellation is +0 under RN or round-to-odd. */
    const bf16_exact_t *large=cmp>0 ? a:b,*small=cmp>0 ? b:a;
    uint64_t borrow=0;
    for (int i=0;i<BF16_WORDS;++i) {
        uint64_t x=large->words[i],y=small->words[i];
        out->words[i]=x-y-borrow;
        borrow=(x<y)||(x==y && borrow);
    }
    out->negative=large->negative; return borrow==0;
}
static int bf16_bit(const bf16_exact_t *v,int index) {
    return (int)((v->words[index/64]>>(index%64))&1);
}
static int bf16_any_below(const bf16_exact_t *v,int cut) {
    for (int i=0;i<cut/64;++i) if (v->words[i]) return 1;
    int bits=cut%64;
    return bits && (v->words[cut/64]&((1ULL<<bits)-1));
}
static int bf16_round32(const bf16_exact_t *v,int odd,int flush,uint32_t *out) {
    int top=-1;
    for (int i=BF16_WORDS-1;i>=0;--i) if (v->words[i]) {
        top=i*64+63-__builtin_clzll(v->words[i]); break;
    }
    uint32_t sign=(uint32_t)v->negative<<31;
    if (top<0 || (flush && top+BF16_UNIT<-126)) { *out=sign; return 1; }
    int quantum=top+BF16_UNIT-23;
    if (quantum<-149) quantum=-149;
    int cut=quantum-BF16_UNIT,word=cut/64,bit=cut%64;
    uint64_t rounded=v->words[word]>>bit;
    if (bit && word+1<BF16_WORDS) rounded|=v->words[word+1]<<(64-bit);
    if (odd) rounded|=bf16_any_below(v,cut)!=0;
    else if (bf16_bit(v,cut-1) && (bf16_any_below(v,cut-1)||(rounded&1))) ++rounded;
    if (rounded>=(1ULL<<24)) { rounded>>=1; ++quantum; }
    if (quantum+23>127) return 0; /* Finite workload: explicit overflow rejection. */
    uint32_t e=rounded>=(1U<<23) ? (uint32_t)(quantum+150):0;
    *out=sign|(e<<23)|((uint32_t)rounded&0x7fffffU); return 1;
}
static int bf16_product(uint16_t a,uint16_t b,int flush,bf16_exact_t *out) {
    int sa,sb,ea,eb; uint32_t ma,mb;
    if (!bf16_decode(a,0,flush,&sa,&ea,&ma)||!bf16_decode(b,0,flush,&sb,&eb,&mb)) return 0;
    return bf16_term(out,(uint64_t)ma*mb,ea+eb,sa^sb);
}
static int bf16_add32(uint32_t a,uint32_t b,int odd,int flush,uint32_t *out) {
    int sa,sb,ea,eb; uint32_t ma,mb; bf16_exact_t left,right,sum;
    return bf16_decode(a,1,flush,&sa,&ea,&ma) && bf16_decode(b,1,flush,&sb,&eb,&mb)
        && bf16_term(&left,ma,ea,sa) && bf16_term(&right,mb,eb,sb)
        && bf16_exact_sum(&left,&right,&sum) && bf16_round32(&sum,odd,flush,out);
}
static int bf16_fma(uint16_t a,uint16_t b,uint32_t c,uint32_t *out) {
    int sign,exp; uint32_t mant; bf16_exact_t product,addend,sum;
    return bf16_product(a,b,0,&product) && bf16_decode(c,1,0,&sign,&exp,&mant)
        && bf16_term(&addend,mant,exp,sign) && bf16_exact_sum(&product,&addend,&sum)
        && bf16_round32(&sum,0,0,out);
}
static int bf16_dot2(const uint16_t *a,const uint16_t *b,uint32_t c,uint32_t *out) {
    bf16_exact_t product; uint32_t p[2],pair;
    for (int i=0;i<2;++i)
        if (!bf16_product(a[i],b[i],1,&product)||!bf16_round32(&product,1,1,&p[i])) return 0;
    return bf16_add32(p[0],p[1],1,1,&pair) && bf16_add32(c,pair,1,1,out);
}
static int bf16_lane_reference(const uint16_t *a,const uint16_t *b,uint32_t c,int chain,int lane,uint32_t *out) {
    if (chain<2) return bf16_dot2(a+2*lane,b+2*lane,c,out);
    if (chain<4) {
        /* A[2][4] row-major, B[4][2] packed by columns, C[2][2] row-major.
         * Each output sequentially accumulates two standard 2-way dot products. */
        int row=lane/2,col=lane%2; uint32_t first;
        return bf16_dot2(a+4*row,b+4*col,c,&first)
            && bf16_dot2(a+4*row+2,b+4*col+2,first,out);
    }
    return bf16_fma(a[2*lane+(chain&1)],b[2*lane+(chain&1)],c,out);
}

typedef struct { uint16_t a[32],b[32]; uint32_t initial[32],expected[32],witness[32]; } bf16_case_t;
static int prepare_bf16_cases(bf16_case_t *cases,uint32_t seed) {
    static const uint16_t values[]={0x3d81,0xbd83,0x3e81,0xbe82,0x3f01,0xbf03,0x3b81,0xbb83};
    for (int k=0;k<BF16_CASES;++k) {
        bf16_case_t *c=&cases[k];
        for (int i=0;i<32;++i) {
            c->a[i]=values[((uint32_t)i+seed+k)%8];
            c->b[i]=values[((uint32_t)i*3+seed+k+1)%8];
        }
        /* Round-to-odd vs RN, forced flushing and finite BF16 boundary. */
        c->a[0]=0x3980; c->b[0]=0x3900; c->a[1]=c->b[1]=0;
        c->a[2]=c->a[3]=c->b[2]=c->b[3]=0x1a00;
        c->a[4]=1; c->b[4]=0x3f80; c->a[5]=c->b[5]=0;
        c->a[6]=0x7f7f; c->b[6]=0x0080; c->a[7]=c->b[7]=0;
        c->a[8]=0x3980; c->b[8]=0x3900;
        for (int i=9;i<12;++i) c->a[i]=c->b[i]=0;
        /* Fused underflow witness: 2^-150 + 2^-149 rounds to 2^-148;
         * prematurely rounded FP32 multiplication instead produces 2^-149. */
        c->a[16]=c->b[16]=c->b[17]=0x1a00; c->a[17]=0x9a00;
        c->a[24]=1; c->a[25]=0x8001; c->b[24]=c->b[25]=0x3f00;
        for (int chain=0;chain<8;++chain) for (int lane=0;lane<4;++lane) {
            int n=4*chain+lane;
            uint32_t initial=(n&1) ? 0xbf000001U:0x3f000001U;
            if (chain<4 && lane==0) initial=0x3f800000U;
            if (chain<2 && lane==1) initial=0;
            if (chain<2 && lane==2) initial=1; /* Standard dot flushes this too. */
            if (chain==4 && lane==0) initial=1;
            if (chain==5 && lane==0) initial=0x80000001U;
            if (chain>=6 && lane==0) initial=0;
            c->initial[n]=initial;
            const uint16_t *a=c->a+8*(chain/2),*b=c->b+8*(chain/2);
            if (!bf16_lane_reference(a,b,initial,chain,lane,&c->witness[n])) return 0;
            for (int r=0;r<BF16_ROUNDS;++r)
                if (!bf16_lane_reference(a,b,initial,chain,lane,&initial)) return 0;
            c->expected[n]=initial;
        }
    }
    return 1;
}

#if defined(LVS_CPU_HELPER_ENABLE_BF16) && defined(__aarch64__) && defined(__linux__)
#if !defined(__clang__)
#pragma GCC push_options
#pragma GCC target("+bf16")
__attribute__((noinline,noclone))
#else
__attribute__((noinline,target("bf16")))
#endif
static int execute_neon_bf16_block(const bf16_case_t *input,uint32_t *output,int rounds,int final) {
    uint16x8_t a0=vld1q_u16(input->a+0), b0=vld1q_u16(input->b+0);
    uint16x8_t a1=vld1q_u16(input->a+8), b1=vld1q_u16(input->b+8);
    uint16x8_t a2=vld1q_u16(input->a+16), b2=vld1q_u16(input->b+16);
    uint16x8_t a3=vld1q_u16(input->a+24), b3=vld1q_u16(input->b+24);
    uint32x4_t x0=vld1q_u32(input->initial+0);
    uint32x4_t x1=vld1q_u32(input->initial+4);
    uint32x4_t x2=vld1q_u32(input->initial+8);
    uint32x4_t x3=vld1q_u32(input->initial+12);
    uint32x4_t x4=vld1q_u32(input->initial+16);
    uint32x4_t x5=vld1q_u32(input->initial+20);
    uint32x4_t x6=vld1q_u32(input->initial+24);
    uint32x4_t x7=vld1q_u32(input->initial+28);
    unsigned count,alive;
    __asm__ volatile(
        ".arch_extension bf16\n"
        "// LVS_BF16_BEGIN\n"
        "mov %w[count], wzr\n"
        "1: tst %w[count], #31\n"
        "b.ne 2f\n"
        "cbnz %w[final], 2f\n"
        "ldr %w[alive], [%[running]]\n"
        "cbz %w[alive], 3f\n"
        "2:\n"
        "bfdot %[x0].4s, %[a0].8h, %[b0].8h\n"
        "bfdot %[x1].4s, %[a0].8h, %[b0].8h\n"
        "bfmmla %[x2].4s, %[a1].8h, %[b1].8h\n"
        "bfmmla %[x3].4s, %[a1].8h, %[b1].8h\n"
        "bfmlalb %[x4].4s, %[a2].8h, %[b2].8h\n"
        "bfmlalt %[x5].4s, %[a2].8h, %[b2].8h\n"
        "bfmlalb %[x6].4s, %[a3].8h, %[b3].8h\n"
        "bfmlalt %[x7].4s, %[a3].8h, %[b3].8h\n"
        "add %w[count], %w[count], #1\n"
        "cmp %w[count], %w[rounds]\n"
        "b.ne 1b\n"
        "3:\n"
        "// LVS_BF16_END\n"
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

static int execute_bf16_block(const bf16_case_t *c,uint32_t *out,int rounds,int final) {
    if (rounds!=1 && rounds!=BF16_ROUNDS) return -1;
#if defined(LVS_CPU_HELPER_TEST_BF16)
    memcpy(out,c->initial,128);
    for (int r=0;r<rounds;++r) {
        if (!final && !keep_running) return 0;
        for (int n=0;n<32;++n) {
            int chain=n/4;
            if (!bf16_lane_reference(c->a+8*(chain/2),c->b+8*(chain/2),out[n],chain,n%4,&out[n])) return -1;
        }
    }
    return 1;
#elif defined(LVS_CPU_HELPER_ENABLE_BF16) && defined(__aarch64__) && defined(__linux__)
    return execute_neon_bf16_block(c,out,rounds,final);
#else
    (void)c; (void)out; (void)rounds; (void)final; return -1;
#endif
}
static uint64_t bf16_read_fpcr(void) {
#if defined(LVS_CPU_HELPER_TEST_BF16)
    return 0;
#elif defined(__aarch64__) && defined(__linux__)
    uint64_t value; __asm__ volatile("mrs %0, fpcr":"=r"(value)); return value;
#else
    return UINT64_MAX;
#endif
}

static void run_neon_bf16_loop(uint32_t seed,worker_stats_t *stats) {
    stats->fpcr=bf16_read_fpcr();
#if defined(LVS_CPU_HELPER_TEST_BF16_BAD_FPCR)
    stats->fpcr=1ULL<<13;
#endif
#if defined(LVS_CPU_HELPER_TEST_BF16)
    stats->bf16_hwcap=3; stats->bf16_hwcap2=1ULL<<14;
#else
# if defined(__aarch64__) && defined(__linux__)
    stats->bf16_hwcap=getauxval(AT_HWCAP); stats->bf16_hwcap2=getauxval(AT_HWCAP2);
# endif
#endif
#if defined(LVS_CPU_HELPER_TEST_BF16_CAPABILITY_LOST)
    stats->bf16_hwcap2=0;
#endif
    if (!bf16_capability(stats->bf16_hwcap,stats->bf16_hwcap2)) {
        record_worker_error(stats,"bf16_capability_lost",0,1ULL<<14,stats->bf16_hwcap2); keep_running=0; return;
    }
    if (!bf16_environment_supported(stats->fpcr)) {
        record_worker_error(stats,"bf16_fp_environment",0,0,stats->fpcr); keep_running=0; return;
    }
    bf16_case_t cases[BF16_CASES]; uint32_t output[34]; int lanes=4;
    if (!prepare_bf16_cases(cases,seed)) {
        record_worker_error(stats,"bf16_reference_domain",0,1,0); keep_running=0; return;
    }
    for (;;) {
        int final=!keep_running;
        if (stats->error_count || (final && !stats->initial_verification_completed)) break;
        if (!half_check_affinity(stats)) break;
#if defined(LVS_CPU_HELPER_TEST_BF16_MIGRATION)
        ++stats->observed_cpu;
        record_worker_error(stats,"affinity_lost",0,stats->affinity_target_cpu,stats->observed_cpu); keep_running=0; break;
#endif
        if (bf16_read_fpcr()!=stats->fpcr) {
            record_worker_error(stats,"bf16_fpcr_changed",0,stats->fpcr,bf16_read_fpcr()); keep_running=0; break;
        }
        const bf16_case_t *c=&cases[(stats->arithmetic_verified_blocks+seed)%BF16_CASES];
        int complete=1;
        for (int witness=0;witness<2 && complete>0;++witness) {
            output[0]=0x98765432U; output[8*lanes+1]=0x12345678U;
            complete=execute_bf16_block(c,output+1,witness ? 1:BF16_ROUNDS,final);
#if defined(LVS_CPU_HELPER_TEST_BF16_INTERRUPT)
            if (!final && stats->arithmetic_verified_blocks==2) { keep_running=0; complete=0; }
#endif
            if (complete<=0) break;
            const uint32_t *expected=witness ? c->witness:c->expected;
#if defined(LVS_CPU_HELPER_TEST_BF16_CORRUPT)
            output[1]^=1;
#endif
#if defined(LVS_CPU_HELPER_TEST_BF16_CORRUPT_LANE)
            output[1+LVS_CPU_HELPER_TEST_BF16_CORRUPT_LANE]^=1;
#endif
#if defined(LVS_CPU_HELPER_TEST_BF16_CORRUPT_PERIODIC)
            if (!final && stats->arithmetic_verified_blocks==2) output[2]^=1;
#endif
#if defined(LVS_CPU_HELPER_TEST_BF16_CORRUPT_FINAL)
            if (final) output[3]^=1;
#endif
#if defined(LVS_CPU_HELPER_TEST_BF16_CORRUPT_WITNESS)
            if (witness) output[1]^=1;
#endif
#if defined(LVS_CPU_HELPER_TEST_BF16_CORRUPT_GUARD)
            output[0]^=1;
#endif
            if (output[0]!=0x98765432U || output[8*lanes+1]!=0x12345678U)
                record_worker_error(stats,"bf16_store_guard",0,1,0);
            for (int n=0;n<8*lanes && !stats->error_count;++n)
                if (output[n+1]!=expected[n]) {
                    stats->first_error_lane=n;
                    record_worker_error(stats,"bf16_fma_mismatch",stats->arithmetic_verified_blocks,expected[n],output[n+1]);
                }
        }
        if (complete<0) { record_worker_error(stats,"bf16_execution_state",0,1,0); keep_running=0; }
        if (!complete) { ++stats->interrupted_arithmetic_blocks; continue; }
        if (stats->error_count) { keep_running=0; break; }
        if (!half_check_affinity(stats)) break;
        if (bf16_read_fpcr()!=stats->fpcr) {
            record_worker_error(stats,"bf16_fpcr_changed",0,stats->fpcr,bf16_read_fpcr()); keep_running=0; break;
        }
        if (stats->arithmetic_verified_blocks==UINT64_MAX) {
            record_worker_error(stats,"bf16_counter_overflow",UINT64_MAX,0,0); keep_running=0; break;
        }
        ++stats->arithmetic_verified_blocks; ++stats->verify_passes;
        if (final) { stats->final_verification_completed=1; publish_verified_progress(stats,1); break; }
        int initial=!stats->initial_verification_completed;
        if (initial) stats->initial_verification_completed=1; else stats->periodic_verification_completed=1;
        publish_verified_progress(stats,initial);
    }
}

static void write_bf16_result(FILE *handle,const worker_stats_t *stats,
                              int threads,int requested,uint64_t errors) {
    uint64_t blocks=0; int initial=threads==requested && threads>0,periodic=initial,final=initial;
    for (int i=0;i<threads;++i) {
        blocks+=stats[i].arithmetic_verified_blocks;
        initial&=stats[i].initial_verification_completed;
        periodic&=stats[i].periodic_verification_completed;
        final&=stats[i].final_verification_completed;
    }
    fprintf(handle,"  \"verification_required\":true,\"verification_version\":1,\n"
        "  \"verification_contract\":\"neon_bf16_v1\",\n"
        "  \"verification_method\":\"integer_dyadic_rto_ftz_and_rne_fused_reference\",\n"
        "  \"operation_family\":\"bf16_standard_dot_matrix_and_fused_widening\",\n"
        "  \"execution_implementation\":\"%s\",\"actual_isa\":\"%s\",\n"
        "  \"isa_capability_source\":\"%s\",\n"
        "  \"arithmetic_verified_blocks\":%" PRIu64 ",\n"
        "  \"accumulator_chains\":8,\"bf16_rounds_per_block\":256,\"witness_rounds_per_block\":1,\n"
        "  \"dot_chains\":2,\"matrix_chains\":2,\"bottom_chains\":2,\"top_chains\":2,\n"
        "  \"active_lanes\":4,\"input_bits\":16,\"accumulator_bits\":32,\n"
        "  \"bf16_mode\":\"standard_ebf0\",\"comparison\":\"bit_exact\",\n"
        "  \"initial_verification_completed\":%s,\"periodic_verification_completed\":%s,\n"
        "  \"final_verification_completed\":%s,\"verification_complete\":%s,\n"
        "  \"verified_progress\":{\"contract\":\"neon_bf16_progress_v1\",\"sidecar_suffix\":\".progress.jsonl\","
        "\"snapshot_interval_seconds\":2.0,\"persistence_error\":%s,\"snapshot_count\":%lu,\"snapshot_write_seconds\":%.9f},\n",
#if defined(LVS_CPU_HELPER_TEST_BF16)
        "test_bf16_emulation","test_bf16_emulation","test_override",
#else
        "aarch64_neon_bf16_asm","asimdbf16","linux_aarch64_hwcap_common_set",
#endif
        blocks,initial ? "true":"false",periodic ? "true":"false",final ? "true":"false",
        initial && periodic && final && !errors ? "true":"false",
        progress_io_error ? "true":"false",progress_sequence,progress_write_seconds);
}
