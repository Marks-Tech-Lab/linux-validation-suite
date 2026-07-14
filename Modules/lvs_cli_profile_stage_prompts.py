from __future__ import annotations


class ProfileCliStagePromptMixin:
    """CLI prompt helpers for CPU, memory, and allocation stage options."""

    def _choose_cpu_instruction_set(self, current: str = "auto") -> str:
        options = ["auto", "sse", "avx", "avx2", "avx512"]
        print("CPU instruction set:")
        for idx, name in enumerate(options, start=1):
            label = "Auto" if name == "auto" else name.upper()
            print(f"{idx}. {label}")
        raw = self._input(f"Choose CPU instruction set [{current}]: ").strip().lower()
        if not raw:
            return current or "auto"
        if raw in options:
            return raw
        try:
            return options[int(raw) - 1]
        except Exception:
            print("Invalid CPU instruction set, keeping current.")
            return current or "auto"

    def _choose_memory_instruction_set(self, current: str = "auto") -> str:
        options = ["auto", "sse", "avx", "avx2", "avx512"]
        print("Memory instruction set:")
        for idx, name in enumerate(options, start=1):
            label = "Auto" if name == "auto" else name.upper()
            print(f"{idx}. {label}")
        raw = self._input(f"Choose memory instruction set [{current}]: ").strip().lower()
        if not raw:
            return current or "auto"
        if raw in options:
            return raw
        try:
            return options[int(raw) - 1]
        except Exception:
            print("Invalid memory instruction set, keeping current.")
            return current or "auto"

    def _choose_allocation_percent(self, label: str, current: int, minimum: int = 1, maximum: int = 95) -> int:
        raw = self._input(f"{label} allocation percent [{current}]: ").strip()
        if not raw:
            return int(current)
        try:
            value = int(raw)
            return max(minimum, min(maximum, value))
        except Exception:
            print("Invalid allocation percent, keeping current.")
            return int(current)

    def _choose_cpu_threads(self, current: str = "all") -> str:
        raw = self._input(f"CPU threads [all or integer] [{current}]: ").strip().lower()
        if not raw:
            return current or "all"
        if raw == "all":
            return "all"
        try:
            value = int(raw)
            return str(max(1, value))
        except Exception:
            print("Invalid CPU thread count, keeping current.")
            return current or "all"
