from __future__ import annotations

from typing import Any, Dict, List

from .lvs_gpu_backend_catalog import (
    GPU_3D_BACKEND_PREFERENCE_OPTIONS,
    GPU_3D_INTENSITY_FACTORS,
    OPENCL_COMPUTE_VARIANTS,
    VRAM_BACKEND_PREFERENCE_OPTIONS,
    VULKAN_COMPUTE_VARIANTS,
)


class ProfileCliGpuPromptMixin:
    """CLI prompt helpers for GPU and VRAM profile stage options."""

    def _choose_gpu_target_mode(self, current: str = "all") -> str:
        cards = self.workload_runner._discover_gpu_cards()
        print("GPU target mode:")
        print("1. Validate all GPUs")
        print("2. Stress discrete GPUs only")
        print("3. Stress GPU with most VRAM")
        print("4. Custom explicit GPU selection")
        raw = self._input(f"Choose GPU target mode [{self.workload_runner._gpu_target_summary(current)}]: ").strip()
        if not raw:
            return current or "all"
        if raw == "1":
            return "all"
        if raw == "2":
            return "discrete_all"
        if raw == "3":
            return "discrete_max_vram"
        if raw == "4":
            if not cards:
                print("No GPUs discovered, keeping current target mode.")
                return current or "all"
            print("Available GPUs:")
            for idx, card in enumerate(cards, start=1):
                print(f"{idx}. {self.workload_runner._gpu_target_display_label(card)}")
            selection = self._input("Choose one or more GPUs by number, comma-separated: ").strip()
            selected_cards: List[Dict[str, Any]] = []
            for item in selection.split(","):
                token = item.strip()
                if not token:
                    continue
                try:
                    selected_cards.append(cards[int(token) - 1])
                except Exception:
                    print(f"Ignoring invalid GPU selection: {token}")
            if not selected_cards:
                print("No valid GPUs selected, keeping current target mode.")
                return current or "all"
            slots = [card["slot"] for card in selected_cards if card.get("slot")]
            if len(slots) == len(selected_cards):
                return "slots:" + ",".join(slots)
            return "cards:" + ",".join(card["card"] for card in selected_cards)
        print("Invalid GPU target mode, keeping current.")
        return current or "all"

    def _choose_gpu_3d_backend_preference(self, current: str = "auto") -> str:
        current = self.workload_runner._normalize_gpu_3d_backend_preference(current)
        options = list(GPU_3D_BACKEND_PREFERENCE_OPTIONS)
        labels = {
            "auto": "Auto (suite-curated)",
            "vulkan": "Vulkan transfer/readback",
            "vulkan_compute": "Vulkan compute/readback",
            "egl": "Built-in EGL/GLES",
            "opencl": "Built-in OpenCL compute",
        }
        print("GPU 3D backend preference:")
        for idx, name in enumerate(options, start=1):
            candidates = self.workload_runner._gpu_3d_backend_preference_catalog(name)
            chain = ", ".join(str(entry.get("display_name") or entry.get("backend")) for entry in candidates)
            recommended = "yes" if any(entry.get("recommended_for_saturation") for entry in candidates) else "no"
            print(f"{idx}. {labels[name]} -> {chain} (stress-capable={recommended})")
        raw = self._input(f"Choose GPU 3D backend preference [{current}]: ").strip().lower()
        if not raw:
            return current or "auto"
        normalized = self.workload_runner._normalize_gpu_3d_backend_preference(raw)
        if normalized != "auto" or raw == "auto":
            return normalized
        try:
            return options[int(raw) - 1]
        except Exception:
            print("Invalid GPU 3D backend preference, keeping current.")
            return current or "auto"

    def _choose_gpu_3d_mode(self, current: str = "steady") -> str:
        options = ["steady", "variable"]
        labels = {
            "steady": "Steady",
            "variable": "Variable",
        }
        normalized_current = str(current or "steady").strip().lower()
        if normalized_current not in options:
            normalized_current = "steady"
        print("GPU 3D mode:")
        for idx, name in enumerate(options, start=1):
            print(f"{idx}. {labels[name]}")
        raw = self._input(f"Choose GPU 3D mode [{normalized_current}]: ").strip().lower()
        if not raw:
            return normalized_current
        if raw in options:
            return raw
        try:
            return options[int(raw) - 1]
        except Exception:
            print("Invalid GPU 3D mode, keeping current.")
            return normalized_current

    def _choose_gpu_3d_intensity(self, current: str = "extreme") -> str:
        options = list(GPU_3D_INTENSITY_FACTORS.keys())
        normalized_current = self.workload_runner._normalize_gpu_3d_intensity(current)
        print("GPU 3D intensity:")
        for idx, name in enumerate(options, start=1):
            print(f"{idx}. {name}")
        raw = self._input(f"Choose GPU 3D intensity [{normalized_current}]: ").strip().lower()
        if not raw:
            return normalized_current
        if raw in options:
            return self.workload_runner._normalize_gpu_3d_intensity(raw)
        try:
            return options[int(raw) - 1]
        except Exception:
            print("Invalid GPU 3D intensity, keeping current.")
            return normalized_current

    def _choose_opencl_compute_variant(self, current: str = "baseline") -> str:
        options = list(OPENCL_COMPUTE_VARIANTS.keys())
        normalized_current = self.workload_runner._normalize_opencl_compute_variant(current)
        print("OpenCL compute variant:")
        for idx, name in enumerate(options, start=1):
            meta = OPENCL_COMPUTE_VARIANTS.get(name, {})
            status = str(meta.get("status", "") or "unknown")
            display_name = str(meta.get("display_name", name) or name)
            print(f"{idx}. {name} - {display_name} ({status})")
        raw = self._input(f"Choose OpenCL compute variant [{normalized_current}]: ").strip().lower()
        if not raw:
            return normalized_current
        normalized = self.workload_runner._normalize_opencl_compute_variant(raw)
        if normalized == raw.replace("-", "_").replace(" ", "_"):
            return normalized
        try:
            return options[int(raw) - 1]
        except Exception:
            print("Invalid OpenCL compute variant, keeping current.")
            return normalized_current

    def _choose_vulkan_compute_variant(self, current: str = "hash") -> str:
        options = list(VULKAN_COMPUTE_VARIANTS.keys())
        normalized_current = self.workload_runner._normalize_vulkan_compute_variant(current)
        print("Vulkan compute variant:")
        for idx, name in enumerate(options, start=1):
            meta = VULKAN_COMPUTE_VARIANTS.get(name, {})
            status = str(meta.get("status", "") or "unknown")
            display_name = str(meta.get("display_name", name) or name)
            print(f"{idx}. {name} - {display_name} ({status})")
        raw = self._input(f"Choose Vulkan compute variant [{normalized_current}]: ").strip().lower()
        if not raw:
            return normalized_current
        normalized = self.workload_runner._normalize_vulkan_compute_variant(raw)
        if normalized == raw.replace("-", "_").replace(" ", "_") or raw in {"baseline", "memory", "memory_mix", "stateful"}:
            return normalized
        try:
            return options[int(raw) - 1]
        except Exception:
            print("Invalid Vulkan compute variant, keeping current.")
            return normalized_current

    def _choose_vram_backend_preference(self, current: str = "auto") -> str:
        current = self.workload_runner._normalize_vram_backend_preference(current)
        options = list(VRAM_BACKEND_PREFERENCE_OPTIONS)
        labels = {
            "auto": "Auto",
            "vulkan": "Vulkan stateful-memory",
            "opencl": "OpenCL",
            "egl": "EGL/GLES",
        }
        print("VRAM backend preference:")
        for idx, name in enumerate(options, start=1):
            chain = ", ".join(self._vram_backend_display_name(candidate) for candidate in self._vram_backend_candidates_for_preference(name))
            print(f"{idx}. {labels[name]} -> {chain}")
        raw = self._input(f"Choose VRAM backend preference [{current}]: ").strip().lower()
        if not raw:
            return current or "auto"
        normalized = self.workload_runner._normalize_vram_backend_preference(raw)
        if normalized != "auto" or raw == "auto":
            return normalized
        try:
            return options[int(raw) - 1]
        except Exception:
            print("Invalid VRAM backend preference, keeping current.")
            return current or "auto"
