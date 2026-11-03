"""Shared, transactional workload editing for profiles and one-off run setups.

This layer only edits configuration. Hardware readiness, budgeting and runtime
safety remain the responsibility of the normal execution pipeline.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any

from .lvs_gpu_targets import physical_gpu_choices, physical_slot_targets

from .lvs_gpu_backend_catalog import OPENCL_COMPUTE_VARIANTS, VULKAN_COMPUTE_VARIANTS


@dataclass(frozen=True)
class StageSetting:
    key: str
    label: str
    module: str
    attribute: str
    value: Any
    options: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None
    option_labels: tuple[str, ...] = ()


def configuration_gpu_cards(host: Any) -> list[dict]:
    """Use the normal workload runner inventory in either frontend."""
    runner = getattr(getattr(host, "orchestrator", None), "workload_runner", None)
    if runner is None:
        runner = getattr(host, "workload_runner", None)
    discover = getattr(runner, "_discover_gpu_cards", None)
    return list(discover()) if callable(discover) else []


def stage_settings(stage: Any, editor: Any, gpu_cards=()) -> list[StageSetting]:
    """Only enabled modules expose settings; values come from shared catalogs."""
    settings = []

    def add(key, label, module, attribute, options=(), minimum=None, maximum=None):
        obj = getattr(stage.modules, module)
        if obj.enabled:
            settings.append(StageSetting(key, label, module, attribute, getattr(obj, attribute),
                                         tuple(options), minimum, maximum))

    add("cpu_power_auto", "CPU Power Auto", "cpu", "power_auto", ("false", "true"))
    add("cpu_backend", "CPU backend preference", "cpu", "backend_preference", editor.CPU_BACKEND_OPTIONS)
    add("cpu_instruction_intent", "CPU Instruction Intent", "cpu", "instruction_intent", editor.CPU_INSTRUCTION_INTENT_OPTIONS)
    add("cpu_instruction", "CPU instruction set", "cpu", "instruction_set", editor.cpu_instruction_options())
    add("cpu_mode", "CPU workload level", "cpu", "mode", editor.CPU_MODE_OPTIONS)
    add("cpu_load", "CPU load pattern", "cpu", "load", editor.CPU_LOAD_OPTIONS)
    add("cpu_threads", "CPU threads (all or positive count)", "cpu", "threads")
    add("memory_instruction", "Memory instruction set", "memory", "instruction_set", editor.MEMORY_INSTRUCTION_OPTIONS)
    add("memory_allocation", "Memory allocation percent", "memory", "allocation_percent", minimum=1, maximum=95)
    add("gpu_3d_target", "3D GPU target selection", "gpu_3d", "gpus", editor.GPU_TARGET_OPTIONS)
    add("vram_target", "VRAM GPU target selection", "vram", "gpus", editor.GPU_TARGET_OPTIONS)
    add("gpu_backend", "3D backend preference", "gpu_3d", "backend_preference", editor.gpu_backend_options())
    add("gpu_mode", "3D load mode", "gpu_3d", "mode", editor.GPU_3D_MODE_OPTIONS)
    add("gpu_intensity", "3D intensity", "gpu_3d", "intensity", editor.gpu_intensity_options())
    backend = stage.modules.gpu_3d.backend_preference
    variants = (tuple(VULKAN_COMPUTE_VARIANTS) if backend == "vulkan_compute" else
                tuple(OPENCL_COMPUTE_VARIANTS) if backend == "opencl" else
                tuple(editor.compute_variant_options()) if backend == "auto" else ())
    if variants:
        add("gpu_compute_variant", "3D compute variant", "gpu_3d", "compute_variant", variants)
    if backend in {"auto", "vulkan_compute", "opencl"} and stage.modules.gpu_3d.compute_variant == "stateful_memory":
        add("gpu_allocation", "3D stateful-memory allocation percent", "gpu_3d", "allocation_percent", minimum=0, maximum=95)
    add("vram_backend", "VRAM backend preference", "vram", "backend_preference", editor.VRAM_BACKEND_OPTIONS)
    add("vram_allocation", "VRAM allocation percent", "vram", "allocation_percent", minimum=1, maximum=95)
    choices = physical_gpu_choices(list(gpu_cards))
    return [replace(setting,
                    options=setting.options + tuple(value for value, _ in choices),
                    option_labels=setting.options + tuple(label for _, label in choices))
            if setting.key in {"gpu_3d_target", "vram_target"}
            else replace(setting, option_labels=tuple("Auto" if value.casefold() == "auto" else value
                                                     for value in setting.options))
            if setting.key == "cpu_instruction" else setting
            for setting in settings]


def apply_stage_setting(edit: Any, index: int, key: str, raw: str, controller: Any, validator: Any, gpu_cards=()) -> Any:
    """Reject invalid input without partially mutating the effective profile."""
    candidate = deepcopy(edit)
    stage = candidate.profile.stages[index]
    setting = next((item for item in stage_settings(stage, controller.profile_editor, gpu_cards) if item.key == key), None)
    if setting is None:
        raise ValueError("This setting is not applicable to the selected stage/backend.")
    value: Any = str(raw).strip()
    if key in {"gpu_3d_target", "vram_target"} and value.startswith("slots:"):
        cards = physical_slot_targets(value, list(gpu_cards))
        value = "slots:" + ",".join(str(card["slot"]).lower() for card in cards)
    elif setting.options:
        if value not in setting.options:
            raise ValueError(f"Choose a valid {setting.label}: {', '.join(setting.options)}")
    elif key == "cpu_threads":
        if value != "all" and (not value.isascii() or not value.isdecimal() or int(value) <= 0):
            raise ValueError("CPU threads must be 'all' or a positive integer.")
    elif setting.minimum is not None:
        try:
            value = int(value)
        except ValueError:
            raise ValueError(f"{setting.label} must be a whole number.") from None
        if not setting.minimum <= value <= setting.maximum:
            raise ValueError(f"{setting.label} must be between {setting.minimum} and {setting.maximum}.")
    if key == "gpu_backend":
        variants = VULKAN_COMPUTE_VARIANTS if value == "vulkan_compute" else OPENCL_COMPUTE_VARIANTS if value == "opencl" else None
        if variants is not None and stage.modules.gpu_3d.compute_variant not in variants:
            raise ValueError("Select a compute variant compatible with the requested backend first.")
    result = controller.apply_stage_action(candidate.profile, candidate.labels, index, key, value)
    errors = validator.validate(candidate.profile, result.labels)["errors"]
    if errors:
        raise ValueError("; ".join(errors))
    edit.profile, edit.labels, edit.dirty = candidate.profile, result.labels, True
    return result.value


def effective_stage_text(stage: Any) -> list[str]:
    """Show the actual effective workload, not just duration and a stage label."""
    from dataclasses import asdict
    return [f"  {name}: " + ", ".join(f"{key}={value}" for key, value in asdict(module).items() if key != "enabled")
            for name, module in vars(stage.modules).items() if module.enabled]
