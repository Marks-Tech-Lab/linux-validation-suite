#define _GNU_SOURCE

#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

static volatile sig_atomic_t g_running = 1;
static volatile uint64_t g_sink = 0;
static volatile uint64_t g_error_count = 0;
static volatile uint64_t g_verify_passes = 0;
static const char *g_result_file = NULL;

enum pattern_kind {
    PATTERN_MIX64 = 0,
    PATTERN_INVERTED = 1,
    PATTERN_WALKING = 2,
    PATTERN_ADDRESS_XOR = 3,
    PATTERN_COUNT = 4
};

struct worker_stats {
    uint64_t verify_passes;
    uint64_t error_count;
    uint64_t pattern_passes[PATTERN_COUNT];
    uint64_t first_error_offset;
    uint64_t first_error_expected;
    uint64_t first_error_actual;
    uint64_t first_error_pass_index;
    int first_error_pattern;
    int first_error_recorded;
};

struct worker_args {
    uint8_t *start;
    size_t length;
    int thread_index;
    struct worker_stats *stats;
};

static void stop_handler(int signo) {
    (void)signo;
    g_running = 0;
}

static void bind_to_cpu(int thread_index) {
#ifdef __linux__
    cpu_set_t set;
    CPU_ZERO(&set);
    long cpu_total = sysconf(_SC_NPROCESSORS_ONLN);
    if (cpu_total <= 0) {
        return;
    }
    CPU_SET(thread_index % cpu_total, &set);
    (void)pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
#else
    (void)thread_index;
#endif
}

static uint64_t mix64(uint64_t value) {
    value ^= value >> 30;
    value *= 0xBF58476D1CE4E5B9ULL;
    value ^= value >> 27;
    value *= 0x94D049BB133111EBULL;
    value ^= value >> 31;
    return value;
}

static const char *pattern_name(int pattern) {
    switch (pattern) {
        case PATTERN_INVERTED:
            return "inverted_mix64";
        case PATTERN_WALKING:
            return "walking_bit";
        case PATTERN_ADDRESS_XOR:
            return "address_xor";
        case PATTERN_MIX64:
        default:
            return "mix64";
    }
}

static uint64_t expected_value_for_pattern(int pattern, uint64_t pass_index, int thread_index, size_t offset, int lane_index) {
    uint64_t basis = pass_index;
    basis ^= ((uint64_t)(thread_index + 1) << 48);
    basis ^= ((uint64_t)offset << 3);
    basis ^= (uint64_t)(lane_index + 1) * 0x9E3779B97F4A7C15ULL;
    switch (pattern) {
        case PATTERN_INVERTED:
            return ~mix64(basis ^ 0xA5A5A5A5A5A5A5A5ULL);
        case PATTERN_WALKING: {
            uint64_t bit = 1ULL << ((pass_index + (uint64_t)thread_index + (uint64_t)lane_index) % 63ULL);
            return bit ^ ((uint64_t)offset << 1) ^ ((uint64_t)(thread_index + 1) << 56);
        }
        case PATTERN_ADDRESS_XOR:
            return ((uint64_t)offset * 0x9E3779B97F4A7C15ULL) ^ ((uint64_t)(lane_index + 1) * 0xBF58476D1CE4E5B9ULL) ^ pass_index;
        case PATTERN_MIX64:
        default:
            return mix64(basis);
    }
}

static void *worker_main(void *opaque) {
    struct worker_args *args = (struct worker_args *)opaque;
    uint8_t *ptr = args->start;
    size_t length = args->length;
    const size_t stride = 64;
    uint64_t pass_index = 0;
    struct worker_stats *stats = args->stats;
    bind_to_cpu(args->thread_index);

    while (g_running) {
        int verify_pattern = (int)((pass_index + (uint64_t)PATTERN_COUNT - 1ULL) % (uint64_t)PATTERN_COUNT);
        int write_pattern = (int)(pass_index % (uint64_t)PATTERN_COUNT);
        for (size_t offset = 0; g_running && offset + stride <= length; offset += stride) {
            uint64_t *lane = (uint64_t *)(ptr + offset);
            if (pass_index > 0) {
                for (int lane_index = 0; lane_index < 8; ++lane_index) {
                    uint64_t expected = expected_value_for_pattern(verify_pattern, pass_index - 1, args->thread_index, offset, lane_index);
                    if (lane[lane_index] != expected) {
                        __atomic_fetch_add(&g_error_count, 1, __ATOMIC_RELAXED);
                        if (stats != NULL) {
                            stats->error_count += 1;
                            if (!stats->first_error_recorded) {
                                stats->first_error_recorded = 1;
                                stats->first_error_pattern = verify_pattern;
                                stats->first_error_pass_index = pass_index - 1;
                                stats->first_error_offset = (uint64_t)offset + (uint64_t)(lane_index * (int)sizeof(uint64_t));
                                stats->first_error_expected = expected;
                                stats->first_error_actual = lane[lane_index];
                            }
                        }
                    }
                }
            }
            for (int lane_index = 0; lane_index < 8; ++lane_index) {
                lane[lane_index] = expected_value_for_pattern(write_pattern, pass_index, args->thread_index, offset, lane_index);
            }
        }
        __atomic_fetch_add(&g_verify_passes, 1, __ATOMIC_RELAXED);
        if (stats != NULL) {
            stats->verify_passes += 1;
            stats->pattern_passes[write_pattern] += 1;
        }
        __atomic_fetch_add(
            &g_sink,
            expected_value_for_pattern(write_pattern, pass_index, args->thread_index, pass_index & 0xFFFFU, 0),
            __ATOMIC_RELAXED
        );
        pass_index += 1;
    }
    return NULL;
}

static uint64_t parse_u64(const char *text, const char *flag_name) {
    char *end = NULL;
    errno = 0;
    unsigned long long value = strtoull(text, &end, 10);
    if (errno != 0 || end == text || (end && *end != '\0')) {
        fprintf(stderr, "invalid value for %s: %s\n", flag_name, text);
        exit(2);
    }
    return (uint64_t)value;
}

static void write_result_file(uint64_t bytes, int threads, const struct worker_stats *worker_stats) {
    if (g_result_file == NULL || *g_result_file == '\0') {
        return;
    }
    FILE *handle = fopen(g_result_file, "w");
    if (handle == NULL) {
        return;
    }
    fprintf(
        handle,
        "{\n"
        "  \"kind\": \"memory\",\n"
        "  \"status\": \"%s\",\n"
        "  \"bytes\": %" PRIu64 ",\n"
        "  \"threads\": %d,\n"
        "  \"verify_passes\": %" PRIu64 ",\n"
        "  \"error_count\": %" PRIu64 ",\n"
        "  \"patterns\": [\"mix64\", \"inverted_mix64\", \"walking_bit\", \"address_xor\"],\n"
        "  \"threads_detail\": [\n",
        g_error_count == 0 ? "ok" : "error",
        bytes,
        threads,
        g_verify_passes,
        g_error_count
    );
    for (int index = 0; index < threads; ++index) {
        const struct worker_stats *stats = &worker_stats[index];
        fprintf(
            handle,
            "    {\n"
            "      \"thread_index\": %d,\n"
            "      \"verify_passes\": %" PRIu64 ",\n"
            "      \"error_count\": %" PRIu64 ",\n"
            "      \"pattern_passes\": {\n"
            "        \"mix64\": %" PRIu64 ",\n"
            "        \"inverted_mix64\": %" PRIu64 ",\n"
            "        \"walking_bit\": %" PRIu64 ",\n"
            "        \"address_xor\": %" PRIu64 "\n"
            "      }",
            index,
            stats->verify_passes,
            stats->error_count,
            stats->pattern_passes[PATTERN_MIX64],
            stats->pattern_passes[PATTERN_INVERTED],
            stats->pattern_passes[PATTERN_WALKING],
            stats->pattern_passes[PATTERN_ADDRESS_XOR]
        );
        if (stats->first_error_recorded) {
            fprintf(
                handle,
                ",\n"
                "      \"first_error\": {\n"
                "        \"pattern\": \"%s\",\n"
                "        \"pass_index\": %" PRIu64 ",\n"
                "        \"offset\": %" PRIu64 ",\n"
                "        \"expected\": %" PRIu64 ",\n"
                "        \"actual\": %" PRIu64 "\n"
                "      }\n"
                "    }%s\n",
                pattern_name(stats->first_error_pattern),
                stats->first_error_pass_index,
                stats->first_error_offset,
                stats->first_error_expected,
                stats->first_error_actual,
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
    uint64_t bytes = 512ULL * 1024ULL * 1024ULL;
    int threads = 1;

    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--bytes") == 0 && i + 1 < argc) {
            bytes = parse_u64(argv[++i], "--bytes");
        } else if (strcmp(argv[i], "--threads") == 0 && i + 1 < argc) {
            threads = (int)parse_u64(argv[++i], "--threads");
        } else if (strcmp(argv[i], "--result-file") == 0 && i + 1 < argc) {
            g_result_file = argv[++i];
        } else if (strcmp(argv[i], "--help") == 0) {
            printf("memory_stress_helper --bytes <n> --threads <n> [--result-file <path>]\n");
            return 0;
        } else {
            fprintf(stderr, "unknown argument: %s\n", argv[i]);
            return 2;
        }
    }

    if (threads < 1) {
        threads = 1;
    }
    if (bytes < (1ULL << 20)) {
        bytes = 1ULL << 20;
    }

    signal(SIGTERM, stop_handler);
    signal(SIGINT, stop_handler);

    long page_size = sysconf(_SC_PAGESIZE);
    if (page_size <= 0) {
        page_size = 4096;
    }
    uint64_t aligned_bytes = (bytes + (uint64_t)page_size - 1ULL) & ~((uint64_t)page_size - 1ULL);

    uint8_t *buffer = mmap(NULL, (size_t)aligned_bytes, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (buffer == MAP_FAILED) {
        fprintf(stderr, "mmap failed for %llu bytes\n", (unsigned long long)aligned_bytes);
        return 1;
    }

    pthread_t *thread_ids = calloc((size_t)threads, sizeof(*thread_ids));
    struct worker_args *worker_args = calloc((size_t)threads, sizeof(*worker_args));
    struct worker_stats *worker_stats = calloc((size_t)threads, sizeof(*worker_stats));
    if (!thread_ids || !worker_args || !worker_stats) {
        fprintf(stderr, "allocation failed for worker metadata\n");
        munmap(buffer, (size_t)aligned_bytes);
        free(thread_ids);
        free(worker_args);
        free(worker_stats);
        return 1;
    }

    size_t bytes_per_thread = (size_t)(aligned_bytes / (uint64_t)threads);
    size_t remainder = (size_t)(aligned_bytes % (uint64_t)threads);
    size_t cursor = 0;
    for (int index = 0; index < threads; ++index) {
        size_t span = bytes_per_thread + (index == threads - 1 ? remainder : 0U);
        worker_args[index].start = buffer + cursor;
        worker_args[index].length = span;
        worker_args[index].thread_index = index;
        worker_args[index].stats = &worker_stats[index];
        cursor += span;
        if (pthread_create(&thread_ids[index], NULL, worker_main, &worker_args[index]) != 0) {
            g_running = 0;
            for (int joined = 0; joined < index; ++joined) {
                pthread_join(thread_ids[joined], NULL);
            }
            munmap(buffer, (size_t)aligned_bytes);
            free(thread_ids);
            free(worker_args);
            free(worker_stats);
            fprintf(stderr, "pthread_create failed\n");
            return 1;
        }
    }

    for (int index = 0; index < threads; ++index) {
        pthread_join(thread_ids[index], NULL);
    }

    write_result_file(aligned_bytes, threads, worker_stats);
    munmap(buffer, (size_t)aligned_bytes);
    free(thread_ids);
    free(worker_args);
    free(worker_stats);
    return g_error_count == 0 ? 0 : 4;
}
