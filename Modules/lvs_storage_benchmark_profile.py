"""Code-owned Storage Benchmark v1 profile.

The profile independently describes a KDiskMark/CDM-style fio workload.  It
does not contain or derive from KDiskMark source code.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class StorageBenchmarkRow:
    test_name: str
    display_name: str
    operation: str
    pattern: str
    block_size_bytes: int
    queue_depth: int
    threads: int = 1


@dataclass(frozen=True)
class StorageBenchmarkProfile:
    profile_id: str
    profile_name: str
    test_size_gib: int
    runs: int
    measure_time_seconds: int
    interval_seconds: int
    ioengine: str
    direct_io: bool
    test_data: str
    result_unit: str
    rows: tuple[StorageBenchmarkRow, ...]

    def with_overrides(self, *, test_size_gib: int, runs: int) -> "StorageBenchmarkProfile":
        if not 1 <= int(test_size_gib) <= 8:
            raise ValueError("test size must be between 1 and 8 GiB")
        if not 1 <= int(runs) <= 9:
            raise ValueError("run count must be between 1 and 9")
        return replace(self, test_size_gib=int(test_size_gib), runs=int(runs))


def _row(name: str, operation: str, block_size: int, depth: int) -> StorageBenchmarkRow:
    pattern = "random" if operation.startswith("rand") else "sequential"
    return StorageBenchmarkRow(
        test_name=name.lower().replace(" ", "_").replace("/", "_"),
        display_name=name,
        operation=operation,
        pattern=pattern,
        block_size_bytes=block_size,
        queue_depth=depth,
    )


STORAGE_BENCHMARK_V1 = StorageBenchmarkProfile(
    profile_id="storage_kdiskmark_cdm_style_v1",
    profile_name="KDiskMark/CDM-style fio benchmark",
    test_size_gib=1,
    runs=5,
    measure_time_seconds=5,
    interval_seconds=5,
    ioengine="libaio",
    direct_io=True,
    test_data="random",
    result_unit="decimal_mb_per_s",
    rows=(
        _row("SEQ 1M Q8T1 Read", "read", 1_048_576, 8),
        _row("SEQ 1M Q8T1 Write", "write", 1_048_576, 8),
        _row("SEQ 1M Q1T1 Read", "read", 1_048_576, 1),
        _row("SEQ 1M Q1T1 Write", "write", 1_048_576, 1),
        _row("RND 4K Q32T1 Read", "randread", 4_096, 32),
        _row("RND 4K Q32T1 Write", "randwrite", 4_096, 32),
        _row("RND 4K Q1T1 Read", "randread", 4_096, 1),
        _row("RND 4K Q1T1 Write", "randwrite", 4_096, 1),
    ),
)


def storage_benchmark_execution_rows(profile: StorageBenchmarkProfile) -> tuple[StorageBenchmarkRow, ...]:
    """Run every read row first while retaining the public CDM-style row order."""
    reads = tuple(row for row in profile.rows if row.operation in {"read", "randread"})
    writes = tuple(row for row in profile.rows if row.operation in {"write", "randwrite"})
    return reads + writes
