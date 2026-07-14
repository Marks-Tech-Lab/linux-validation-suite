#!/usr/bin/env python3
"""CLI profile edit adapter.

This module owns terminal prompts and print flow for profile editing while
delegating actual profile mutations to the shared profile controllers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Tuple

from .lvs_profile_creation import ProfileCreationRequest, ProfileStageDraft
from .lvs_profile_edit_view import profile_detail_lines, profile_dry_run_preview_text
from .lvs_profile_models import StageConfig, StageModules, ValidationProfile


TEST_TYPE_CATALOG = {
    "CPU": {"description": "CPU-only stress."},
    "CPU+RAM": {"description": "CPU plus system memory stress."},
    "Linpack": {"description": "Reserved for later backend implementation."},
    "Memory": {"description": "System memory stress only."},
    "3D Adaptive": {"description": "GPU 3D stress."},
    "VRAM": {"description": "GPU VRAM stress."},
    "Combined": {"description": "Stack multiple test types in one segment."},
}


class ProfileCliEditor:
    """Terminal adapter for profile editing.

    The host is the CLI launcher. Keeping it as an object reference preserves
    current prompts and helper behavior while moving the edit loop out of the
    large CLI entrypoint file.
    """

    def __init__(self, host: Any) -> None:
        self.host = host

    def profiles_menu(self) -> None:
        host = self.host
        while True:
            print("\nProfiles / Test Definitions")
            print("1. Create Profile")
            print("2. Edit Profile")
            print("3. Ensure Example Profile")
            print("4. Back")
            choice = host._input("Select: ").strip()
            if choice == "1":
                self.create_profile()
            elif choice == "2":
                self.edit_profile()
            elif choice == "3":
                path = host.profile_loader.ensure_example_profile()
                print(f"Example profile ensured at: {path}")
            elif choice == "4":
                return

    def profile_choice_text(self, path: Path) -> str:
        metadata = self.host.profile_loader.profile_menu_metadata(path)
        group = str(metadata.get("menu_group") or "custom")
        group_label = self.host._profile_menu_group_label(group)
        return f"{path.name} ({group_label})" if group_label else path.name

    def create_profile(self) -> None:
        host = self.host
        print("\nCreate new profile")
        profile_name = host._input("Profile name: ").strip()
        if not profile_name:
            print("Profile name required.")
            return
        menu_group = host._choose_profile_menu_group(default="custom")
        try:
            stage_count = int(host._input("Number of segments/stages: ").strip())
        except Exception:
            print("Invalid stage count.")
            return

        stage_drafts: List[ProfileStageDraft] = []
        for index in range(stage_count):
            print(f"\n--- Segment {index + 1} ---")
            label = host._input("Segment label for parser/results: ").strip() or f"Segment {index + 1}"
            test_type = self.choose_test_type()
            try:
                duration_seconds = int(host._input("Duration seconds: ").strip())
            except Exception:
                print("Invalid duration. Using 300.")
                duration_seconds = 300
            stage_drafts.append(ProfileStageDraft(
                label=label,
                test_type=test_type,
                duration_seconds=duration_seconds,
                modules=self.build_stage_modules(test_type),
            ))

        result = host.profile_creation.build_profile(ProfileCreationRequest(
            profile_name=profile_name,
            menu_group=menu_group,
            telemetry_interval_seconds=host.settings_manager.settings.sample_interval_seconds,
            trim_start_seconds=host.settings_manager.settings.trim_start_seconds,
            trim_end_seconds=host.settings_manager.settings.trim_end_seconds,
            stages=stage_drafts,
        ))
        profile_path = host.profile_loader.profiles_dir / f"{profile_name}.json"
        host.profile_loader.save_profile(profile_path, result.profile, result.labels)
        print(f"Saved profile: {profile_path}")

    def choose_test_type(self) -> str:
        keys = list(TEST_TYPE_CATALOG.keys())
        print("Available test types:")
        for idx, name in enumerate(keys, start=1):
            print(f"{idx}. {name} - {TEST_TYPE_CATALOG[name]['description']}")
        raw = self.host._input("Choose test type: ").strip()
        try:
            return keys[int(raw) - 1]
        except Exception:
            return "Combined"

    def build_stage_modules(self, test_type: str) -> StageModules:
        host = self.host
        if test_type == "CPU":
            return host.profile_editor.build_stage_modules(test_type)
        if test_type == "CPU+RAM":
            return host.profile_editor.build_stage_modules(test_type)
        if test_type == "Memory":
            return host.profile_editor.build_stage_modules(test_type)
        if test_type == "3D Adaptive":
            gpu_target_mode = host._choose_gpu_target_mode()
            gpu_backend_preference = host._choose_gpu_3d_backend_preference("auto")
            gpu_mode = host._choose_gpu_3d_mode("steady")
            gpu_intensity = host._choose_gpu_3d_intensity("extreme")
            return host.profile_editor.build_stage_modules(
                test_type,
                gpu_target_mode=gpu_target_mode,
                gpu_backend_preference=gpu_backend_preference,
                gpu_mode=gpu_mode,
                gpu_intensity=gpu_intensity,
            )
        if test_type == "VRAM":
            gpu_target_mode = host._choose_gpu_target_mode()
            vram_backend_preference = host._choose_vram_backend_preference("auto")
            return host.profile_editor.build_stage_modules(
                test_type,
                gpu_target_mode=gpu_target_mode,
                vram_backend_preference=vram_backend_preference,
                vram_allocation_percent=80,
            )
        if test_type == "Linpack":
            return host.profile_editor.build_stage_modules(test_type)
        print("Combined builder")
        cpu_enabled = host._input("Include CPU? [y/N]: ").strip().lower() == "y"
        memory_enabled = host._input("Include Memory/RAM? [y/N]: ").strip().lower() == "y"
        gpu_enabled = host._input("Include 3D Adaptive? [y/N]: ").strip().lower() == "y"
        vram_enabled = host._input("Include VRAM? [y/N]: ").strip().lower() == "y"
        gpu_target_mode = host._choose_gpu_target_mode() if gpu_enabled or vram_enabled else "all"
        cpu_instruction_set = "auto"
        cpu_mode = "normal"
        cpu_load = "steady"
        cpu_priority = "normal"
        cpu_threads = "all"
        memory_allocation_percent = 90 if memory_enabled else 80
        memory_instruction_set = "auto"
        gpu_backend_preference = "auto"
        gpu_mode = "steady"
        gpu_intensity = "extreme"
        vram_allocation_percent = 90 if vram_enabled else 80
        vram_backend_preference = "auto"
        if cpu_enabled:
            cpu_instruction_set = host._choose_cpu_instruction_set(cpu_instruction_set)
            cpu_mode = host._input("CPU mode [normal/extreme]: ").strip().lower() or "normal"
            cpu_load = host._input("CPU load [steady/variable]: ").strip().lower() or "steady"
            cpu_priority = host._input("CPU priority [normal/high]: ").strip().lower() or "normal"
            cpu_threads = host._choose_cpu_threads(cpu_threads)
        if memory_enabled:
            try:
                memory_allocation_percent = int(host._input("RAM allocation percent [90]: ").strip() or "90")
            except Exception:
                memory_allocation_percent = 90
            memory_instruction_set = host._choose_memory_instruction_set(memory_instruction_set)
        if gpu_enabled:
            gpu_backend_preference = host._choose_gpu_3d_backend_preference(gpu_backend_preference)
            gpu_mode = host._choose_gpu_3d_mode(gpu_mode)
            gpu_intensity = host._choose_gpu_3d_intensity(gpu_intensity)
        if vram_enabled:
            try:
                vram_allocation_percent = int(host._input("VRAM allocation percent [90]: ").strip() or "90")
            except Exception:
                vram_allocation_percent = 90
            vram_backend_preference = host._choose_vram_backend_preference(vram_backend_preference)
        return host.profile_editor.build_stage_modules(
            "Combined",
            include_cpu=cpu_enabled,
            include_memory=memory_enabled,
            include_gpu_3d=gpu_enabled,
            include_vram=vram_enabled,
            gpu_target_mode=gpu_target_mode,
            cpu_instruction_set=cpu_instruction_set,
            cpu_mode=cpu_mode,
            cpu_load=cpu_load,
            cpu_priority=cpu_priority,
            cpu_threads=cpu_threads,
            memory_allocation_percent=memory_allocation_percent,
            memory_instruction_set=memory_instruction_set,
            gpu_backend_preference=gpu_backend_preference,
            gpu_mode=gpu_mode,
            gpu_intensity=gpu_intensity,
            vram_backend_preference=vram_backend_preference,
            vram_allocation_percent=vram_allocation_percent,
            clamp_allocations=False,
        )

    def edit_profile(self) -> None:
        host = self.host
        profiles = host.profile_loader.list_profiles()
        if not profiles:
            print("No profiles found.")
            return
        print("\nAvailable profiles:")
        for idx, path in enumerate(profiles, start=1):
            print(f"{idx}. {self.profile_choice_text(path)}")
        raw = host._input("Choose profile to edit: ").strip()
        try:
            profile_path = profiles[int(raw) - 1]
        except Exception:
            print("Invalid selection.")
            return

        profile = host.profile_loader.load_profile(profile_path)
        labels = host.profile_loader.load_segment_labels(profile_path, profile)

        while True:
            labels = self.normalize_profile_labels(profile, labels)
            print(f"\nEditing profile: {profile.profile_name}")
            print(f"Menu label: {profile_path.name} ({host._profile_menu_group_label(profile.menu_group)})")
            print(f"Menu group: {host._profile_menu_group_label(profile.menu_group)}")
            print(
                "Profile strict threshold warnings: "
                + host._strict_threshold_override_text(profile.defaults.strict_threshold_recommendation_warnings)
            )
            for idx, stage in enumerate(profile.stages, start=1):
                label = labels[idx - 1] if idx - 1 < len(labels) else stage.name
                gpu_mode = host._stage_gpu_target_mode_text(stage)
                gpu_backend = host._stage_gpu_backend_text(stage)
                gpu_profile = host._stage_gpu_profile_text(stage)
                cpu_threads = stage.modules.cpu.threads if stage.modules.cpu.enabled else "-"
                cpu_instruction = stage.modules.cpu.instruction_set if stage.modules.cpu.enabled else "-"
                strict_text = host._strict_threshold_override_text(stage.strict_threshold_recommendation_warnings)
                print(
                    f"{idx}. {label} | {stage.name} | {stage.duration_seconds}s | "
                    f"{'on' if stage.enabled else 'off'} | cpu={cpu_instruction}/{cpu_threads} | gpu={gpu_mode}/{gpu_backend}/{gpu_profile} | strict={strict_text}"
                )
            print("T. Cycle profile strict threshold warnings override")
            print("M. Edit profile menu metadata")
            print("A. Add stage")
            print("X. Remove stage")
            print("R. Review profile details")
            print("V. Validate current edits")
            print("D. Dry-run current edits")
            print("S. Save and exit")
            print("Q. Cancel")
            choice = host._input("Select stage to edit: ").strip().lower()
            if choice == "t":
                result = host.profile_edit_controller.cycle_profile_strict(profile, labels)
                labels = result.labels
                continue
            if choice == "m":
                self.edit_profile_menu_metadata(profile)
                continue
            if choice == "a":
                labels = self.add_profile_stage(profile, labels)
                continue
            if choice == "x":
                labels = self.remove_profile_stage(profile, labels)
                continue
            if choice == "r":
                self.print_profile_detail(profile, labels)
                continue
            if choice == "v":
                self.print_profile_edit_validation(profile, labels)
                continue
            if choice == "d":
                self.print_profile_edit_dry_run(profile_path, profile, labels)
                continue
            if choice == "s":
                preparation = host.profile_save.prepare(profile, labels)
                allow_errors = False
                if preparation.errors:
                    print("\nProfile still has blocking validation errors:")
                    for message in preparation.errors:
                        print(f"  [error] {message}")
                    raw = host._input("Save anyway? [y/N]: ").strip().lower()
                    if raw not in {"y", "yes"}:
                        print("Save cancelled.")
                        continue
                    allow_errors = True
                elif preparation.warnings:
                    print("\nProfile validation warnings:")
                    for message in preparation.warnings:
                        print(f"  [warn] {message}")
                host.profile_save.save(profile_path, preparation, allow_errors=allow_errors)
                print(f"Saved profile: {profile_path}")
                return
            if choice == "q":
                print("Edit cancelled.")
                return
            try:
                stage_index = int(choice) - 1
                stage = profile.stages[stage_index]
            except Exception:
                print("Invalid selection.")
                continue
            labels = self.edit_stage(profile, stage_index, stage, labels)

    def normalize_profile_labels(self, profile: ValidationProfile, labels: List[str]) -> List[str]:
        return self.host.profile_editor.normalize_labels(profile, labels)

    def add_profile_stage(self, profile: ValidationProfile, labels: List[str]) -> List[str]:
        host = self.host
        labels = self.normalize_profile_labels(profile, labels)
        default_position = len(profile.stages) + 1
        raw_position = host._input(f"Insert new stage at position [1-{default_position}, default end]: ").strip()
        if not raw_position:
            insert_index = len(profile.stages)
        else:
            try:
                insert_index = max(0, min(len(profile.stages), int(raw_position) - 1))
            except Exception:
                print("Invalid position. Adding at the end.")
                insert_index = len(profile.stages)
        display_index = insert_index + 1
        print(f"\n--- New Stage {display_index} ---")
        label = host._input("Segment label for parser/results: ").strip() or f"Segment {display_index}"
        test_type = host._choose_test_type()
        try:
            duration_seconds = int(host._input("Duration seconds [300]: ").strip() or "300")
        except Exception:
            print("Invalid duration. Using 300.")
            duration_seconds = 300
        result = host.profile_creation.insert_stage(
            profile,
            labels,
            ProfileStageDraft(
                label=label,
                test_type=test_type,
                duration_seconds=duration_seconds,
                modules=host._build_stage_modules(test_type),
            ),
            position=insert_index,
        )
        print(f"Added stage {display_index}: {label} [{test_type}]")
        return result.labels

    def remove_profile_stage(self, profile: ValidationProfile, labels: List[str]) -> List[str]:
        host = self.host
        labels = self.normalize_profile_labels(profile, labels)
        if len(profile.stages) <= 1:
            print("Profiles must keep at least one stage.")
            return labels
        print("\nRemove Stage")
        for index, stage in enumerate(profile.stages, start=1):
            label = labels[index - 1] if index - 1 < len(labels) else stage.name
            print(f"{index}. {label} [{stage.name}] ({stage.duration_seconds}s)")
        raw = host._input("Choose stage number to remove [Enter cancels]: ").strip()
        if not raw:
            print("Remove cancelled.")
            return labels
        try:
            remove_index = int(raw) - 1
        except Exception:
            print("Invalid stage number.")
            return labels
        if remove_index < 0 or remove_index >= len(profile.stages):
            print("Invalid stage number.")
            return labels
        stage = profile.stages[remove_index]
        label = labels[remove_index] if remove_index < len(labels) else stage.name
        confirm = host._input(f"Remove '{label}' [{stage.name}] from this profile? [y/N]: ").strip().lower()
        if confirm not in {"y", "yes"}:
            print("Remove cancelled.")
            return labels
        labels = host.profile_edit_controller.remove_stage(profile, labels, remove_index).labels
        print(f"Removed stage: {label}")
        return labels

    def edit_profile_menu_metadata(self, profile: ValidationProfile) -> None:
        host = self.host
        print("\nProfile Menu Group")
        print(f"Current group: {host._profile_menu_group_label(profile.menu_group)}")
        menu_group = host._choose_profile_menu_group(default=profile.menu_group)
        host.profile_edit_controller.set_profile_menu_group(profile, [], menu_group)
        print(f"Updated menu label: {profile.profile_name} ({host._profile_menu_group_label(profile.menu_group)})")

    def print_profile_edit_validation(self, profile: ValidationProfile, labels: List[str]) -> None:
        preparation = self.host.profile_save.prepare(profile, labels)
        errors = preparation.errors
        warnings = preparation.warnings
        print("\nProfile Validation")
        print(f"Errors: {len(errors)}")
        for message in errors:
            print(f"  [error] {message}")
        print(f"Warnings: {len(warnings)}")
        for message in warnings:
            print(f"  [warn] {message}")
        if not errors and not warnings:
            print("No profile validation issues found.")

    def print_profile_detail(self, profile: ValidationProfile, labels: List[str]) -> None:
        print("\n".join(self.profile_detail_lines(profile, labels)))

    def profile_detail_lines(self, profile: ValidationProfile, labels: List[str]) -> List[str]:
        host = self.host
        return profile_detail_lines(
            profile,
            labels,
            menu_group_label=host._profile_menu_group_label,
            stage_detail_lines=host._stage_detail_lines,
        )

    def profile_audit(self) -> None:
        host = self.host
        payload = self.profile_audit_body()
        text = host.profile_reports.profile_audit_summary_text(payload)
        print(text, end="")
        save = host._input("Save profile audit report? [Y/n]: ").strip().lower()
        if save not in {"n", "no"}:
            report_dir = self.write_profile_audit_report(text, payload)
            print(f"Profile audit report: {report_dir}")

    def profile_audit_body(self) -> dict[str, Any]:
        return self.host.profile_reports.profile_audit_payload(self.host.orchestrator.dry_run)

    def write_profile_audit_report(self, text: str, payload: dict[str, Any]) -> Path:
        return self.host.profile_reports.save_profile_audit_report(text, payload)

    def print_profile_edit_dry_run(
        self,
        profile_path: Path,
        profile: ValidationProfile,
        labels: List[str],
    ) -> None:
        host = self.host
        report = host.orchestrator.dry_run(profile_path, profile, labels)
        print(
            profile_dry_run_preview_text(report, host._profile_execution_summary_lines(report)),
            end="",
        )

    def edit_stage(
        self,
        profile: ValidationProfile,
        stage_index: int,
        stage: StageConfig,
        labels: List[str],
    ) -> List[str]:
        host = self.host
        labels = host.profile_edit_controller.normalize_labels(profile, labels)
        while True:
            current_label = labels[stage_index]
            print(f"\nStage {stage_index + 1}: {current_label}")
            for index, action in enumerate(host.profile_edit_controller.STAGE_ACTIONS, start=1):
                suffix = ""
                if action.key == "strict":
                    suffix = f" ({host._strict_threshold_override_text(stage.strict_threshold_recommendation_warnings)})"
                print(f"{index}. {action.label}{suffix}")
            action_spec = host.profile_edit_controller.stage_action(host._input("Select: ").strip())
            if action_spec is None:
                continue
            action = action_spec.key
            if action == "detail":
                host._print_stage_detail(stage, current_label)
                continue
            if action == "back":
                return labels
            error = host.profile_edit_controller.stage_action_error(stage, action)
            if error:
                print(error)
                continue
            should_apply, value = self.prompt_stage_edit_value(action, stage, current_label)
            if not should_apply:
                continue
            try:
                result = host.profile_edit_controller.apply_stage_action(
                    profile,
                    labels,
                    stage_index,
                    action,
                    value,
                )
                labels = result.labels
                if action == "toggle":
                    print(f"Stage enabled: {result.value}")
                elif action == "strict":
                    print(
                        "Stage strict threshold warnings override: "
                        + host._strict_threshold_override_text(result.value)
                    )
            except (TypeError, ValueError):
                if action == "duration":
                    print("Invalid duration.")
                else:
                    raise

    def prompt_stage_edit_value(self, action: str, stage: StageConfig, current_label: str) -> Tuple[bool, Any]:
        host = self.host
        if action == "label":
            value = host._input(f"Label [{current_label}]: ").strip()
            return bool(value), value
        if action == "duration":
            value = host._input(f"Duration seconds [{stage.duration_seconds}]: ").strip()
            return bool(value), value
        if action == "cpu_instruction":
            return True, host._choose_cpu_instruction_set(stage.modules.cpu.instruction_set)
        if action == "cpu_threads":
            return True, host._choose_cpu_threads(stage.modules.cpu.threads)
        if action == "memory_allocation":
            return True, host._choose_allocation_percent("Memory/RAM", stage.modules.memory.allocation_percent)
        if action == "gpu_target":
            current = stage.modules.vram.gpus if stage.modules.vram.enabled else stage.modules.gpu_3d.gpus
            return True, host._choose_gpu_target_mode(current)
        if action == "gpu_backend":
            return True, host._choose_gpu_3d_backend_preference(stage.modules.gpu_3d.backend_preference)
        if action == "gpu_mode":
            return True, host._choose_gpu_3d_mode(stage.modules.gpu_3d.mode)
        if action == "gpu_intensity":
            return True, host._choose_gpu_3d_intensity(stage.modules.gpu_3d.intensity)
        if action == "gpu_compute_variant":
            preference = host.workload_runner._normalize_gpu_3d_backend_preference(stage.modules.gpu_3d.backend_preference)
            chooser = host._choose_vulkan_compute_variant if preference == "vulkan_compute" else host._choose_opencl_compute_variant
            return True, chooser(stage.modules.gpu_3d.compute_variant)
        if action == "gpu_allocation":
            return True, host._choose_allocation_percent(
                "3D backend VRAM hint",
                stage.modules.gpu_3d.allocation_percent,
                minimum=0,
            )
        if action == "vram_backend":
            return True, host._choose_vram_backend_preference(stage.modules.vram.backend_preference)
        if action == "vram_allocation":
            return True, host._choose_allocation_percent("VRAM", stage.modules.vram.allocation_percent)
        return True, None
