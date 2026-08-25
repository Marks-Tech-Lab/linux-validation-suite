#!/usr/bin/env python3
"""Profile edit presentation helpers shared by optional frontends."""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from .lvs_profile_metadata import derive_legacy_bucket_category

from .lvs_profile_editor import ProfileEditor, format_profile_duration
from .lvs_strict_threshold_policy import optional_bool
from .lvs_service_models import (
    FrontendActionSpec,
    ProfileEditItem,
    ProfileEditState,
    SetupInputSpec,
    SetupPickerSpec,
)


def strict_threshold_override_text(value: Any) -> str:
    parsed = optional_bool(value)
    if parsed is None:
        return "inherit"
    return "enabled" if parsed else "disabled"


def stage_enabled_module_names(stage: Any) -> List[str]:
    names: List[str] = []
    if stage.modules.cpu.enabled:
        names.append("cpu")
    if stage.modules.memory.enabled:
        names.append("memory")
    if stage.modules.gpu_3d.enabled:
        names.append("gpu_3d")
    if stage.modules.vram.enabled:
        names.append("vram")
    if stage.modules.storage_benchmark.enabled:
        names.append("storage_benchmark")
    return names


def profile_stage_summary_lines(stage: Any, label: str, index: int) -> List[str]:
    """Return the concise, frontend-neutral authoring summary for one stage."""
    duration = "Completion-based" if stage.modules.storage_benchmark.enabled else format_profile_duration(stage.duration_seconds)
    state = " (disabled)" if not stage.enabled else ""
    lines = [f"{index}. {label}{state}", f"   {duration}"]
    if stage.modules.cpu.enabled:
        cpu = stage.modules.cpu
        intent_names = {
            "baseline_vector": "architecture baseline SIMD",
            "high_throughput_vector": "high-throughput SIMD",
            "highest_verified_vector": "highest verified SIMD",
        }
        instruction_names = {
            "auto": "automatic instruction selection",
            "scalar": "scalar",
            "sse": "SSE",
            "avx": "AVX",
            "avx2": "AVX2",
            "avx512": "AVX-512",
            "neon": "NEON",
        }
        instruction = intent_names.get(
            cpu.instruction_intent,
            instruction_names.get(str(cpu.instruction_set).lower(), str(cpu.instruction_set)),
        )
        thread_value = str(cpu.threads or "all").strip().lower()
        threads = "all threads" if thread_value in {"", "0", "all", "auto"} else f"{cpu.threads} threads"
        lines.append(f"   CPU: {str(cpu.mode).title()}, {instruction}, {threads}")
    if stage.modules.memory.enabled:
        lines.append(f"   RAM: {stage.modules.memory.allocation_percent}%")
    if stage.modules.gpu_3d.enabled:
        gpu = stage.modules.gpu_3d
        target = {
            "all": "all GPUs",
            "discrete_all": "all discrete GPUs",
            "primary": "primary GPU",
            "first": "first GPU",
        }.get(str(gpu.gpus), str(gpu.gpus).replace("_", " "))
        intensity = "Maximum" if str(gpu.intensity) == "max" else str(gpu.intensity).title()
        lines.append(f"   GPU: {intensity}, {target}")
    if stage.modules.vram.enabled:
        lines.append(f"   VRAM: {stage.modules.vram.allocation_percent}%")
    legacy_bucket = derive_legacy_bucket_category(stage)
    lines.append("   Legacy compatibility: " + (f"{legacy_bucket} (derived)" if legacy_bucket else "none"))
    return lines


def profile_copy_selection_rows(
    profile: Any,
    labels: List[str],
    selected_stage_indices: List[int],
) -> List[str]:
    """Render the ordered stage choices shared by CLI and TUI copy flows."""
    selected = set(selected_stage_indices)
    rows: List[str] = []
    for index, stage in enumerate(profile.stages):
        label = labels[index] if index < len(labels) else stage.display_label
        mark = "x" if index in selected else " "
        rows.append(f"[{mark}] {index + 1}. {label} — {format_profile_duration(stage.duration_seconds)}")
    return rows


def vram_backend_candidates_for_preference(
    preference: str,
    *,
    normalize_preference: Callable[[str], str],
) -> List[str]:
    normalized = normalize_preference(preference)
    candidate_map = {
        "auto": ["python_opencl", "python_vulkan_compute", "python_egl_gles2"],
        "vulkan": ["python_vulkan_compute", "python_opencl", "python_egl_gles2"],
        "opencl": ["python_opencl", "python_egl_gles2"],
        "egl": ["python_egl_gles2", "python_opencl"],
    }
    return list(candidate_map.get(normalized, candidate_map["auto"]))


def vram_backend_display_name(backend: str) -> str:
    names = {
        "python_vulkan_compute": "Built-in Vulkan stateful-memory",
        "python_opencl": "Built-in OpenCL verification",
        "python_egl_gles2": "Built-in EGL/GLES fallback",
    }
    return names.get(backend, backend)


def vram_backend_description(backend: str) -> str:
    descriptions = {
        "python_vulkan_compute": "suite-controlled Vulkan stateful-memory allocation and readback verification",
        "python_opencl": "suite-controlled OpenCL buffer allocation, write, and readback verification",
        "python_egl_gles2": "EGL/GLES texture allocation fallback for systems without usable OpenCL",
    }
    return descriptions.get(backend, "unknown VRAM backend")


def profile_stage_detail_lines(
    stage: Any,
    label: str,
    *,
    normalize_gpu_preference: Callable[[str], str],
    gpu_target_summary: Callable[[str], str],
    normalize_gpu_intensity: Callable[[str], str],
    gpu_preference_catalog: Callable[[str], List[Dict[str, Any]]],
    normalize_vram_preference: Callable[[str], str],
) -> List[str]:
    legacy_bucket = derive_legacy_bucket_category(stage)
    lines = [
        "",
        "Stage Details",
        f"Label: {label}",
        f"Stage ID: {stage.id}",
        f"Type: {stage.name}",
        f"Enabled: {stage.enabled}",
        "Legacy result compatibility: "
        + (f"{legacy_bucket} (derived)" if legacy_bucket else "none"),
    ]
    if stage.modules.storage_benchmark.enabled:
        lines.extend(["Execution: completion-based", "Duration: not applicable", "Trim: not applicable"])
    else:
        lines.extend([
            f"Duration: {stage.duration_seconds}s",
            f"Trim: start={stage.normalization.trim_start_seconds}s, end={stage.normalization.trim_end_seconds}s",
        ])
    lines.append(f"Strict threshold warnings: {strict_threshold_override_text(stage.strict_threshold_recommendation_warnings)}")
    module_names = stage_enabled_module_names(stage)
    lines.append(f"Enabled workloads: {', '.join(module_names) if module_names else 'none'}")
    if stage.modules.cpu.enabled:
        cpu = stage.modules.cpu
        backend_text = f"backend={cpu.backend_preference}, " if cpu.backend_preference != "auto" else ""
        intent_text = f", instruction_intent={cpu.instruction_intent}" if cpu.instruction_intent else ""
        lines.append(
            "CPU: "
            + backend_text
            + f"instruction={cpu.instruction_set}{intent_text}, threads={cpu.threads}, "
            + f"mode={cpu.mode}, load={cpu.load}, priority={cpu.priority}"
        )
    else:
        lines.append("CPU: disabled")
    if stage.modules.memory.enabled:
        memory = stage.modules.memory
        backend_text = f"backend={memory.backend_preference}, " if memory.backend_preference != "auto" else ""
        lines.append(
            "Memory/RAM: "
            + backend_text
            + f"allocation={memory.allocation_percent}%, instruction={memory.instruction_set}, "
            + f"threads={memory.threads}, priority={memory.priority}"
        )
    else:
        lines.append("Memory/RAM: disabled")
    if stage.modules.storage_benchmark.enabled:
        storage = stage.modules.storage_benchmark
        lines.append(
            "Storage Benchmark: "
            f"profile={storage.profile_id}, target_mode={storage.target_mode}, "
            f"drive_execution={storage.drive_execution}, size={storage.test_size_gib} GiB, runs={storage.runs}, "
            f"allow_system_drive={storage.allow_system_drive}"
        )
        if storage.target_path:
            lines.append(f"Storage target path: {storage.target_path}")
        if storage.target_mode == "all_internal_non_root_low_occupancy":
            lines.extend([
                f"Storage maximum selected-filesystem usage: {storage.max_used_percent:.2f}%",
                "Storage occupancy is measured from the selected writable filesystem/workspace, not raw disk contents.",
                "Root/system drives are always excluded; unmounted filesystems on the same drive are not measured.",
            ])
    if stage.modules.gpu_3d.enabled:
        gpu = stage.modules.gpu_3d
        preference = normalize_gpu_preference(gpu.backend_preference)
        lines.append(
            "3D: "
            + f"target={gpu_target_summary(gpu.gpus)}, preference={preference}, "
            + f"mode={gpu.mode}, intensity={normalize_gpu_intensity(gpu.intensity)}, "
            + f"compute_variant={gpu.compute_variant}, vram_hint={gpu.allocation_percent}%"
        )
        if gpu.allocation_percent:
            lines.append("3D allocation note: used by Vulkan/stateful or memory-aware suite-native backends.")
        lines.append("3D backend candidates:")
        for entry in gpu_preference_catalog(preference):
            recommended = "yes" if entry.get("recommended_for_saturation") else "no"
            lines.append(
                f"  - {entry.get('backend')}: {entry.get('api_family')} / {entry.get('suite_scaling_mode')} / "
                + f"{entry.get('suite_verification')} / saturation={recommended}"
            )
            if entry.get("notes"):
                lines.append(f"    {entry.get('notes')}")
    else:
        lines.append("3D: disabled")
    if stage.modules.vram.enabled:
        vram = stage.modules.vram
        preference = normalize_vram_preference(vram.backend_preference)
        lines.append(
            "VRAM: "
            + f"target={gpu_target_summary(vram.gpus)}, "
            + f"preference={preference}, "
            + f"allocation={vram.allocation_percent}%"
        )
        lines.append("VRAM backend candidates:")
        for candidate in vram_backend_candidates_for_preference(
            preference,
            normalize_preference=normalize_vram_preference,
        ):
            lines.append(f"  - {candidate}: {vram_backend_description(candidate)}")
    else:
        lines.append("VRAM: disabled")
    return lines


def profile_detail_lines(
    profile: Any,
    labels: List[str],
    *,
    menu_group_label: Callable[[str], str],
    stage_detail_lines: Callable[[Any, str], List[str]],
) -> List[str]:
    lines = [
        "",
        "Profile Details",
        f"Name: {profile.profile_name}",
        f"Type: {profile.profile_type}",
        f"Menu group: {menu_group_label(profile.menu_group)}",
        f"Stages: {len(profile.stages)}",
        "Defaults: "
        + f"telemetry_interval={profile.defaults.telemetry_interval_seconds}s, "
        + f"trim_start={profile.defaults.trim_start_seconds}s, "
        + f"trim_end={profile.defaults.trim_end_seconds}s, "
        + "strict_threshold_warnings="
        + strict_threshold_override_text(profile.defaults.strict_threshold_recommendation_warnings),
    ]
    for index, stage in enumerate(profile.stages):
        label = labels[index] if index < len(labels) else stage.name
        lines.extend(stage_detail_lines(stage, label))
    return lines


def profile_dry_run_preview_text(
    report: Dict[str, Any],
    execution_summary_lines: List[str],
    *,
    error_limit: int = 12,
    warning_limit: int = 16,
) -> str:
    validation = report.get("validation") or {}
    errors = list(validation.get("errors") or [])
    warnings = list(validation.get("warnings") or [])
    lines = [
        "",
        "Profile Dry Run Preview",
        f"Runnable: {bool(report.get('runnable'))}",
        f"Validation errors: {len(errors)}",
    ]
    lines.extend(f"  [error] {message}" for message in errors[:error_limit])
    if len(errors) > error_limit:
        lines.append(f"  ... {len(errors) - error_limit} more error(s)")
    lines.append(f"Validation warnings: {len(warnings)}")
    lines.extend(f"  [warn] {message}" for message in warnings[:warning_limit])
    if len(warnings) > warning_limit:
        lines.append(f"  ... {len(warnings) - warning_limit} more warning(s)")
    lines.append("")
    lines.extend(execution_summary_lines)
    lines.append("")
    return "\n".join(lines) + "\n"


class ProfileEditPresenter:
    """Builds prompt-free profile edit summaries and action rows."""

    PROFILE_EDIT_ACTIONS = {
        "escape": FrontendActionSpec("escape", "cancel", label="return to profile list without saving"),
        "s": FrontendActionSpec("s", "save", label="save profile"),
        "a": FrontendActionSpec("a", "save_as", label="save as a new profile"),
        "delete": FrontendActionSpec("delete", "remove_stage", label="remove selected stage"),
        "u": FrontendActionSpec("u", "move_stage", target="up", label="move selected stage up"),
        "j": FrontendActionSpec("j", "move_stage", target="down", label="move selected stage down"),
        "y": FrontendActionSpec("y", "duplicate_stage", label="duplicate selected stage"),
        "t": FrontendActionSpec("t", "toggle_stage", label="toggle selected stage enabled state"),
        "d": FrontendActionSpec("d", "input", target="duration", label="edit selected stage duration"),
        "l": FrontendActionSpec("l", "input", target="label", label="edit selected stage display label"),
        "g": FrontendActionSpec("g", "picker", target="gpu_target", label="edit selected stage GPU target mode"),
        "b": FrontendActionSpec("b", "picker", target="backend", label="edit selected stage backend preference"),
        "h": FrontendActionSpec("h", "picker", target="cpu_backend", label="edit selected CPU backend preference"),
        "i": FrontendActionSpec("i", "picker", target="intensity", label="edit selected GPU stage intensity"),
        "c": FrontendActionSpec("c", "picker", target="compute_variant", label="edit selected GPU compute variant"),
        "p": FrontendActionSpec("p", "picker", target="cpu_instruction", label="edit selected CPU instruction set"),
        "o": FrontendActionSpec("o", "picker", target="cpu_instruction_intent", label="edit selected CPU instruction intent"),
        "r": FrontendActionSpec("r", "picker", target="memory_instruction", label="edit selected memory instruction set"),
        "e": FrontendActionSpec("e", "picker", target="cpu_mode", label="edit selected CPU mode"),
        "f": FrontendActionSpec("f", "picker", target="cpu_load", label="edit selected CPU load pattern"),
        "n": FrontendActionSpec("n", "input", target="trim_start", label="edit selected stage trim"),
        "v": FrontendActionSpec("v", "input", target="vram_allocation", label="edit selected stage VRAM allocation percent"),
        "m": FrontendActionSpec("m", "input", target="memory_allocation", label="edit selected stage memory allocation percent"),
    }
    STAGE_PICKER_TITLES = {
        "gpu_target": "GPU Target Mode",
        "backend": "Backend Preference",
        "intensity": "GPU Intensity",
        "compute_variant": "GPU Compute Variant",
        "cpu_instruction": "CPU Instruction Set",
        "cpu_instruction_intent": "CPU Instruction Intent",
        "memory_instruction": "Memory Instruction Set",
        "cpu_mode": "CPU Mode",
        "cpu_load": "CPU Load Pattern",
        "cpu_backend": "CPU Backend Preference",
    }

    def __init__(
        self,
        profile_editor: ProfileEditor,
        menu_group_label: Callable[[str], str],
    ) -> None:
        self.profile_editor = profile_editor
        self.menu_group_label = menu_group_label

    def profile_edit_action_for_key(self, key: str) -> FrontendActionSpec:
        normalized = str(key or "").lower()
        return self.PROFILE_EDIT_ACTIONS.get(normalized, FrontendActionSpec(normalized, ""))

    def option_values(self, key: str) -> List[str]:
        options = {
            "gpu_target": list(self.profile_editor.GPU_TARGET_OPTIONS),
            "cpu_instruction": list(self.profile_editor.CPU_INSTRUCTION_OPTIONS),
            "cpu_instruction_intent": list(self.profile_editor.CPU_INSTRUCTION_INTENT_OPTIONS),
            "memory_instruction": list(self.profile_editor.MEMORY_INSTRUCTION_OPTIONS),
            "gpu_backend": self.profile_editor.gpu_backend_options(),
            "vram_backend": list(self.profile_editor.VRAM_BACKEND_OPTIONS),
            "gpu_intensity": self.profile_editor.gpu_intensity_options(),
            "compute_variant": self.profile_editor.compute_variant_options(),
            "cpu_mode": list(self.profile_editor.CPU_MODE_OPTIONS),
            "cpu_load": list(self.profile_editor.CPU_LOAD_OPTIONS),
            "cpu_backend": list(self.profile_editor.CPU_BACKEND_OPTIONS),
        }
        return list(options.get(str(key or ""), []))

    def stage_picker_spec(self, edit: ProfileEditState, stage_index: int, key: str) -> SetupPickerSpec:
        if stage_index < 0 or stage_index >= len(edit.profile.stages):
            raise ValueError("Select a stage row first.")
        stage = edit.profile.stages[stage_index]
        normalized = str(key or "")
        option_key = normalized
        title = self.STAGE_PICKER_TITLES.get(normalized, normalized)
        if normalized == "backend":
            if stage.modules.gpu_3d.enabled:
                option_key = "gpu_backend"
                current = stage.modules.gpu_3d.backend_preference
            elif stage.modules.vram.enabled:
                option_key = "vram_backend"
                current = stage.modules.vram.backend_preference
            else:
                raise ValueError("Selected stage does not have a GPU or VRAM workload.")
        elif normalized == "gpu_target":
            if stage.modules.gpu_3d.enabled:
                current = stage.modules.gpu_3d.gpus
            elif stage.modules.vram.enabled:
                current = stage.modules.vram.gpus
            else:
                raise ValueError("Selected stage does not have a GPU or VRAM workload.")
        elif normalized == "intensity":
            if not stage.modules.gpu_3d.enabled:
                raise ValueError("Selected stage does not have a GPU 3D workload.")
            option_key = "gpu_intensity"
            current = stage.modules.gpu_3d.intensity
        elif normalized == "compute_variant":
            if not stage.modules.gpu_3d.enabled:
                raise ValueError("Selected stage does not have a GPU 3D workload.")
            current = stage.modules.gpu_3d.compute_variant
        elif normalized == "cpu_instruction":
            if not stage.modules.cpu.enabled:
                raise ValueError("Selected stage does not have a CPU workload.")
            current = stage.modules.cpu.instruction_set
        elif normalized == "cpu_instruction_intent":
            if not stage.modules.cpu.enabled:
                raise ValueError("Selected stage does not have a CPU workload.")
            current = stage.modules.cpu.instruction_intent
        elif normalized == "memory_instruction":
            if not stage.modules.memory.enabled:
                raise ValueError("Selected stage does not have a memory workload.")
            current = stage.modules.memory.instruction_set
        elif normalized == "cpu_mode":
            if not stage.modules.cpu.enabled:
                raise ValueError("Selected stage does not have a CPU workload.")
            current = stage.modules.cpu.mode
        elif normalized == "cpu_load":
            if not stage.modules.cpu.enabled:
                raise ValueError("Selected stage does not have a CPU workload.")
            current = stage.modules.cpu.load
        elif normalized == "cpu_backend":
            if not stage.modules.cpu.enabled:
                raise ValueError("Selected stage does not have a CPU workload.")
            current = stage.modules.cpu.backend_preference
        else:
            current = ""
        options = self.option_values(option_key)
        if not options:
            raise ValueError(f"No options available for {title}.")
        return SetupPickerSpec(key=normalized, title=title, options=options, current=str(current or ""))

    def stage_input_spec(self, edit: ProfileEditState, stage_index: int, field: str) -> SetupInputSpec:
        if stage_index < 0 or stage_index >= len(edit.profile.stages):
            raise ValueError("Select a stage row first.")
        stage = edit.profile.stages[stage_index]
        labels = self.profile_editor.normalize_labels(edit.profile, edit.labels)
        edit.labels = labels
        normalized = str(field or "")
        field_map = {
            "duration": (
                "__profile_stage_duration",
                f"Stage {stage_index + 1} duration (for example 90s, 5m, or 1h 30m)",
                f"{stage.duration_seconds}s",
            ),
            "label": (
                "__profile_stage_label",
                f"Stage {stage_index + 1} display label",
                labels[stage_index] if stage_index < len(labels) else stage.name,
            ),
            "vram_allocation": (
                "__profile_stage_vram_allocation",
                f"Stage {stage_index + 1} VRAM allocation percent",
                str(stage.modules.vram.allocation_percent),
            ),
            "memory_allocation": (
                "__profile_stage_memory_allocation",
                f"Stage {stage_index + 1} memory allocation percent",
                str(stage.modules.memory.allocation_percent),
            ),
            "trim_start": (
                "__profile_stage_trim_start",
                f"Stage {stage_index + 1} trim start seconds",
                str(stage.normalization.trim_start_seconds),
            ),
            "trim_end": (
                "__profile_stage_trim_end",
                f"Stage {stage_index + 1} trim end seconds",
                str(stage.normalization.trim_end_seconds),
            ),
            "storage_target_path": (
                "__profile_stage_storage_target_path",
                f"Stage {stage_index + 1} Storage Benchmark target directory",
                str(stage.modules.storage_benchmark.target_path),
            ),
            "storage_test_size": (
                "__profile_stage_storage_test_size",
                f"Stage {stage_index + 1} Storage Benchmark test size GiB (1-8)",
                str(stage.modules.storage_benchmark.test_size_gib),
            ),
            "storage_runs": (
                "__profile_stage_storage_runs",
                f"Stage {stage_index + 1} Storage Benchmark runs (1-9)",
                str(stage.modules.storage_benchmark.runs),
            ),
            "storage_max_used_percent": (
                "__profile_stage_storage_max_used_percent",
                f"Stage {stage_index + 1} Storage Benchmark maximum selected-filesystem usage percent (0-100)",
                str(stage.modules.storage_benchmark.max_used_percent),
            ),
        }
        if normalized not in field_map:
            raise ValueError("")
        if normalized == "duration" and stage.modules.storage_benchmark.enabled:
            raise ValueError("Storage Benchmark is completion-based and has no stage duration.")
        if normalized == "vram_allocation" and not stage.modules.vram.enabled:
            raise ValueError("Selected stage does not have a VRAM workload.")
        if normalized == "memory_allocation" and not stage.modules.memory.enabled:
            raise ValueError("Selected stage does not have a memory workload.")
        if normalized.startswith("storage_") and not stage.modules.storage_benchmark.enabled:
            raise ValueError("Selected stage does not have a Storage Benchmark module.")
        if (
            normalized == "storage_max_used_percent"
            and stage.modules.storage_benchmark.target_mode != "all_internal_non_root_low_occupancy"
        ):
            raise ValueError("Maximum used percent applies only to all_internal_non_root_low_occupancy.")
        pending, label, initial = field_map[normalized]
        return SetupInputSpec(field=pending, label=label, initial_value=initial)

    def items(self, edit: ProfileEditState) -> List[ProfileEditItem]:
        profile = edit.profile
        labels = self.profile_editor.normalize_labels(profile, edit.labels)
        edit.labels = labels
        rows: List[ProfileEditItem] = [
            ProfileEditItem("save", "Save profile"),
            ProfileEditItem("save_as", "Save As..."),
            ProfileEditItem("name", f"Name: {profile.profile_name}"),
            ProfileEditItem("group", f"Menu group: {self.menu_group_label(profile.menu_group)}"),
            ProfileEditItem("description", f"Description: {profile.menu_description or '-'}"),
            ProfileEditItem(
                "strict",
                f"Strict warnings: {profile.defaults.strict_threshold_recommendation_warnings}",
            ),
        ]
        templates = self.profile_editor.stage_templates()
        for template in templates:
            key = str(template.get("key") or "cpu")
            label = str(template.get("label") or key)
            action_label = (
                "Add Storage Benchmark Stage (completion-based)"
                if key == "storage_benchmark"
                else f"Add {label} stage"
            )
            rows.append(ProfileEditItem("add_template", action_label, template_key=key))
        for index, stage in enumerate(profile.stages):
            label = labels[index] if index < len(labels) else stage.name
            state = "enabled" if stage.enabled else "disabled"
            legacy_bucket = derive_legacy_bucket_category(stage)
            rows.append(
                ProfileEditItem(
                    "stage",
                    f"{index + 1}. {label} — "
                    f"{'Completion-based' if stage.modules.storage_benchmark.enabled else format_profile_duration(stage.duration_seconds)}, {state} | "
                    f"Legacy result compatibility: {f'{legacy_bucket} (derived)' if legacy_bucket else 'none'}",
                    index=index,
                )
            )
            if stage.modules.storage_benchmark.enabled:
                storage = stage.modules.storage_benchmark
                rows.extend([
                    ProfileEditItem(
                        "storage_target_mode",
                        f"  Storage target mode: {storage.target_mode}",
                        index=index,
                    ),
                    ProfileEditItem(
                        "storage_target_path",
                        f"  Storage target path: {storage.target_path or '(not used for all_internal)'}",
                        index=index,
                    ),
                    ProfileEditItem(
                        "storage_test_size",
                        f"  Storage test size: {storage.test_size_gib} GiB",
                        index=index,
                    ),
                    ProfileEditItem(
                        "storage_runs",
                        f"  Storage runs: {storage.runs}",
                        index=index,
                    ),
                ])
                if storage.target_mode == "all_internal_non_root_low_occupancy":
                    rows.append(ProfileEditItem(
                        "storage_max_used_percent",
                        f"  Maximum selected-filesystem usage: {storage.max_used_percent:.2f}%",
                        index=index,
                    ))
                else:
                    rows.append(ProfileEditItem(
                        "storage_allow_system",
                        f"  Allow system drive: {storage.allow_system_drive}",
                        index=index,
                    ))
        return rows

    def summary_text(self, edit: ProfileEditState) -> str:
        profile = edit.profile
        labels = self.profile_editor.normalize_labels(profile, edit.labels)
        lines: List[str] = [
            "Profile Edit",
            "============",
            f"Profile: {profile.profile_name}",
            f"File: {edit.profile_path.name}",
            f"Group: {self.menu_group_label(profile.menu_group)}",
            f"Description: {profile.menu_description or '-'}",
            f"Strict warnings: {profile.defaults.strict_threshold_recommendation_warnings}",
            f"Dirty: {'yes' if edit.dirty else 'no'}",
            "",
            "Stages:",
        ]
        if not profile.stages:
            lines.append("(No stages yet. Choose Add Stage to begin.)")
        for index, stage in enumerate(profile.stages, start=1):
            label = labels[index - 1] if index - 1 < len(labels) else stage.name
            lines.extend(profile_stage_summary_lines(stage, label, index))
        lines.extend(
            [
                "",
                "Actions:",
                "- Enter activates the highlighted edit action.",
                "- Choose an Add Stage row to review a guided workload before adding it.",
                "- Storage Benchmark configuration is edited through the indented rows beneath its stage.",
                "- S saves the profile after validation.",
                "- A starts Save As using the current in-memory edits.",
                "- Y duplicates the selected stage; U/J move it up/down.",
                "- D edits selected stage duration.",
                "- L edits selected stage display label.",
                "- T toggles selected stage enabled/disabled.",
                "- Delete removes selected stage.",
                "- G cycles selected stage GPU target mode.",
                "- B edits selected stage backend preference.",
                "- I edits selected GPU stage intensity.",
                "- C edits selected GPU compute variant.",
                "- P edits selected CPU instruction set.",
                "- R edits selected memory instruction set.",
                "- E edits selected CPU mode; F edits its steady/variable load pattern.",
                "- CPU mode is a backend-specific workload envelope; it does not change ISA selection.",
                "- H edits the CPU backend preference; O edits architecture-neutral instruction intent.",
                "- N edits selected stage trim start/end.",
                "- V edits selected stage VRAM allocation percent.",
                "- M edits selected stage memory allocation percent.",
                "- Esc returns to profile list without saving.",
            ]
        )
        return "\n".join(lines)
