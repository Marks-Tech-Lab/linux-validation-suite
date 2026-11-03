from __future__ import annotations

from .lvs_profile_editor import ProfileEditor


class ProfileCliStagePromptMixin:
    """CLI prompt helpers for CPU, memory, and allocation stage options."""

    def _choose_cpu_instruction_set(self, current: str = "auto") -> str:
        options = ProfileEditor.cpu_instruction_options()
        print("CPU instruction set:")
        for idx, name in enumerate(options, start=1):
            label = "Auto" if name == "auto" else name.upper()
            if name in {"sve_fp32_fma", "avx_vnni", "avx512_vnni", "sve2_smlal", "neon_dotprod", "neon_i8mm", "neon_fp16", "neon_fhm", "neon_bf16"}:
                label += " (experimental; runtime capability/verification checks required)"
            print(f"{idx}. {label}")
        raw = self._input(f"Choose CPU instruction set [{current}]: ").strip().lower()
        if not raw:
            return current or "auto"
        if raw in options:
            return raw
        try:
            index = int(raw) - 1
            if not 0 <= index < len(options):
                raise ValueError("selection out of range")
            return options[index]
        except Exception:
            print("Invalid CPU instruction set, keeping current.")
            return current or "auto"

    def _choose_memory_instruction_set(self, current: str = "auto") -> str:
        options = list(ProfileEditor.MEMORY_INSTRUCTION_OPTIONS)
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
            index = int(raw) - 1
            if not 0 <= index < len(options):
                raise ValueError("selection out of range")
            return options[index]
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
