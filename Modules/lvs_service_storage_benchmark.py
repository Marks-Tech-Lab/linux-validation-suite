"""Frontend-neutral Storage Benchmark service delegates."""

from pathlib import Path
from typing import Any


class SuiteStorageBenchmarkServiceMixin:
    def storage_benchmark_profile(self) -> Any:
        from .lvs_storage_benchmark_profile import STORAGE_BENCHMARK_V1
        return STORAGE_BENCHMARK_V1

    def storage_benchmark_preflight(self, target_path: Path, *, test_size_gib: int, root_confirmation: str | None = None) -> Any:
        return self.storage_benchmark_service.preflight(
            target_path, test_size_gib=test_size_gib, root_confirmation=root_confirmation
        )

    def run_storage_benchmark(self, target_path: Path, **kwargs: Any) -> Path:
        return self.storage_benchmark_service.run(target_path, **kwargs)

    def discover_all_storage_benchmark_targets(self, **kwargs: Any) -> Any:
        return self.storage_benchmark_service.discover_all_eligible(**kwargs)

    def run_all_internal_storage_benchmarks(self, plan: Any, **kwargs: Any) -> Path:
        return self.storage_benchmark_service.run_all_internal(plan, **kwargs)
