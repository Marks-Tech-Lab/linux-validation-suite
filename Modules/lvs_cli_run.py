from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from Modules.lvs_cli_compat import BackRequested
from Modules.lvs_cli_live_run import CliLiveRunPresenter, cli_live_run_supported
from Modules.lvs_cli_preflight_summary import compact_cli_preflight_summary
from Modules.lvs_cli_screen import clear_cli_screen
from Modules.lvs_run_executor import RunExecutionError
from Modules.lvs_run_metadata import RunMetadata
from Modules.lvs_service_models import RunSetupState


class RunCliAdapter:
    """CLI-only run selection and launch workflow."""

    def __init__(self, launcher: Any) -> None:
        self.launcher = launcher

    def __getattr__(self, name: str) -> Any:
        return getattr(self.launcher, name)

    def run_tests_menu(self) -> None:
        while True:
            clear_cli_screen()
            print("\nRun Tests")
            print("1. Start Validation Run")
            print("2. Run Storage Benchmark")
            print("3. Dry Run Selected Profile")
            print("4. Back")
            choice = self._input("Select: ").strip()
            if choice == "1":
                self.new_run()
            elif choice == "2":
                self.storage_benchmark()
            elif choice == "3":
                self._dry_run_diagnostics()
            elif choice == "4":
                return

    def storage_benchmark(self) -> None:
        clear_cli_screen()
        print("\nStorage Benchmark")
        print("KDiskMark/CDM-style fio benchmark (file-backed, non-destructive)")
        print("1. Benchmark one selected target")
        print("2. Benchmark all eligible internal drives")
        mode = self._input("Select mode [1]: ").strip() or "1"
        try:
            if mode not in {"1", "2"}:
                raise ValueError("invalid storage benchmark mode")
            profile_raw = self._input("Profile [1: KDiskMark/CDM-style fio benchmark]: ").strip()
            if profile_raw not in {"", "1"}:
                raise ValueError("only the built-in Storage Benchmark v1 profile is available")
            size_raw = self._input("Test size GiB [1, maximum 8]: ").strip()
            runs_raw = self._input("Run count [5, range 1-9]: ").strip()
            test_size = int(size_raw or "1")
            runs = int(runs_raw or "5")
            if mode == "1":
                self._storage_benchmark_one(test_size, runs)
            else:
                self._storage_benchmark_all(test_size, runs)
        except (OSError, ValueError) as exc:
            print(f"Storage benchmark unavailable: {exc}")

    def _storage_benchmark_one(self, test_size: int, runs: int) -> None:
        target_raw = self._input("Eligible internal-drive directory or mount: ").strip()
        if not target_raw:
            print("Benchmark cancelled.")
            return
        service = self.storage_benchmark_service
        root_confirmation = None
        try:
            target = service.preflight(Path(target_raw), test_size_gib=test_size)
        except ValueError as exc:
            if "BENCHMARK ROOT" not in str(exc):
                raise
            root_confirmation = self._input("System drive selected. Type BENCHMARK ROOT: ").strip()
            target = service.preflight(
                Path(target_raw), test_size_gib=test_size, root_confirmation=root_confirmation
            )
        estimate = service.estimated_maximum_written_gib(test_size, runs)
        print(f"Target: {target.target_path} ({target.physical_devices[0]})")
        print(f"Estimated maximum data written, including initialization: {estimate} GiB")
        confirmation = self._input("Type BENCHMARK to begin: ").strip()
        if confirmation != "BENCHMARK":
            print("Benchmark cancelled.")
            return
        result_dir = service.run(
            target.target_path,
            test_size_gib=test_size,
            runs=runs,
            root_confirmation=root_confirmation,
            confirmed=True,
            progress=lambda event: print(self._storage_benchmark_progress_text(event)),
        )
        print(f"Storage benchmark result: {result_dir}")

    def _storage_benchmark_all(self, test_size: int, runs: int) -> None:
        service = self.storage_benchmark_service
        root_confirmation = None
        plan = service.discover_all_eligible(test_size_gib=test_size)
        if plan.root_confirmation_required:
            print("\nA root/system drive is eligible but is excluded by default.")
            root_raw = self._input("Type BENCHMARK ROOT to include it, or Enter to skip: ").strip()
            if root_raw == "BENCHMARK ROOT":
                root_confirmation = root_raw
                plan = service.discover_all_eligible(
                    test_size_gib=test_size,
                    root_confirmation=root_confirmation,
                )
        per_drive_gib = service.estimated_maximum_written_gib(test_size, runs)
        total_gib = per_drive_gib * len(plan.targets)
        print("\nAll eligible internal drives preview")
        print(f"Drives to benchmark: {len(plan.targets)}")
        for target in plan.targets:
            model = plan.target_models.get(target.physical_devices[0], target.primary_block_name)
            suffix = " [ROOT/SYSTEM DRIVE]" if target.is_system_drive else ""
            print(f"- {target.physical_devices[0]} ({model}): {target.target_path}{suffix}")
        print(f"Test size: {test_size} GiB")
        print(f"Run count: {runs}")
        print(f"Estimated maximum writes per drive: {per_drive_gib} GiB")
        print(f"Estimated total maximum writes: {total_gib} GiB ({total_gib * 1024**3 / 1_000_000_000_000:.3f} TB)")
        if plan.skipped_targets:
            print("Skipped drives:")
            for skipped in plan.skipped_targets:
                print(f"- {skipped.device} ({skipped.model}): {skipped.reason}")
        confirmation = self._input("Type BENCHMARK ALL INTERNAL to begin: ").strip()
        if confirmation != "BENCHMARK ALL INTERNAL":
            print("Benchmark cancelled.")
            return
        result_dir = service.run_all_internal(
            plan,
            test_size_gib=test_size,
            runs=runs,
            confirmation=confirmation,
            root_confirmation=root_confirmation,
            progress=lambda event: print(self._storage_benchmark_progress_text(event)),
        )
        print(f"All-internal storage benchmark result: {result_dir}")

    @staticmethod
    def _storage_benchmark_progress_text(event: dict[str, Any]) -> str:
        if event.get("phase") == "batch_target":
            return f"Starting {event.get('device')}: target {event.get('target_index')}/{event.get('target_count')}"
        if event.get("phase") == "benchmark":
            prefix = f"{event.get('device')} " if event.get("device") else ""
            return f"{prefix}{event.get('row')}: run {event.get('run')}/{event.get('runs')}"
        return str(event.get("message") or event.get("phase") or "Storage benchmark")

    def new_run(self) -> None:
        self.launcher._pending_heatsoak_minutes = 0.0
        profiles = self.profile_loader.list_profiles()
        if not profiles:
            print("No profiles found.")
            return
        clear_cli_screen()
        print("\nAvailable profiles:")
        for idx, path in enumerate(profiles, start=1):
            print(f"{idx}. {self._profile_choice_text(path)}")
        print("A. Audit all profiles")
        raw = self._input("Choose profile: ").strip()
        if raw.strip().lower() == "a":
            self.profile_cli.profile_audit()
            return
        try:
            profile_path = profiles[int(raw) - 1]
        except Exception:
            print("Invalid selection.")
            return

        profile_decision = self.run_flow.inspect_profile(profile_path)
        readiness = profile_decision.readiness
        profile = readiness.profile
        labels = readiness.labels
        if profile_decision.errors or profile_decision.warnings:
            print("\nProfile diagnostics:")
            for message in profile_decision.errors:
                print(f"  [error] {message}")
            for message in profile_decision.warnings:
                print(f"  [warn] {message}")
            if profile_decision.blocked:
                print("Profile has blocking issues. Fix the profile or sidecar file before running.")
                return
        metadata = self._run_setup_review(profile_path, profile, labels)
        if metadata is None:
            print("Run cancelled.")
            return
        setup = RunSetupState(
            profile_path=profile_path,
            metadata=metadata,
            profile=profile,
            labels=labels,
            heatsoak_minutes=float(self.launcher._pending_heatsoak_minutes or 0.0),
        )
        prepared_run = self.run_flow.prepare_setup_run(readiness, setup, save_blocked_report=True)
        preflight = prepared_run.preflight_decision.report
        preflight_action = prepared_run.preflight_action
        print("")
        print(compact_cli_preflight_summary(preflight, report_dir=getattr(preflight_action, "report_dir", None)), end="")
        if preflight_action.blocked:
            report_dir = preflight_action.report_dir
            print("Run cancelled due to blocking preflight issues.")
            if report_dir is not None:
                print(f"Preflight report: {report_dir}")
                print(f"Preflight summary: {report_dir / 'preflight_summary.txt'}")
            return
        if preflight_action.skip_notice:
            print(preflight_action.skip_notice)
        if cli_live_run_supported(sys.stdout):
            live = CliLiveRunPresenter(stream=sys.stdout, enabled=True)
            try:
                result = self.run_launcher.run_prepared_capture(
                    prepared_run.launch_request,
                    output_callback=live.write_line,
                    operator_stop_source="cli",
                )
                run_dir = result.run_dir
            except RunExecutionError as exc:
                raise exc
            finally:
                live.finish()
        else:
            run_dir = self.run_launcher.run_prepared_direct(
                prepared_run.launch_request,
                heatsoak_debug_callback=lambda path: print(f"Heatsoak advanced debug logging: {path}"),
            )
        if run_dir is None:
            print("Run cancelled during heatsoak.")
            return
        self.post_run_wall_wattage_prompt(run_dir, metadata)
        self._save_run_setup_history(profile_path, profile, metadata, heatsoak_minutes=setup.heatsoak_minutes)
        self.upload_cli.post_run_google_drive_prompt(run_dir)

    def post_run_wall_wattage_prompt(self, run_dir: Path, metadata: RunMetadata) -> None:
        if not self.settings_manager.settings.prompt_for_wall_wattage:
            return
        try:
            raw = self._input("Max wall wattage observed during this run [Enter to skip]: ").strip()
        except BackRequested:
            print("Wall wattage skipped.")
            return
        result = self.post_run_manager.handle_wall_wattage_input(run_dir, metadata, raw)
        print(result.message)

    def normalize_wall_wattage(self, raw: str) -> str:
        return self.post_run_manager.normalize_wall_wattage(raw)

    def apply_run_metadata_update(self, run_dir: Path, metadata: RunMetadata) -> None:
        self.post_run_manager.apply_run_metadata_update(run_dir, metadata)


class RunCompatibilityMixin:
    """Compatibility delegates for legacy launcher run helper methods."""

    def _run_cli_adapter(self) -> RunCliAdapter:
        adapter = getattr(self, "run_cli", None)
        if adapter is None:
            adapter = RunCliAdapter(self)
            self.run_cli = adapter
        return adapter

    def _run_tests_menu(self) -> None:
        self._run_cli_adapter().run_tests_menu()

    def _new_run(self) -> None:
        self._run_cli_adapter().new_run()

    def _post_run_wall_wattage_prompt(self, run_dir: Path, metadata: RunMetadata) -> None:
        self._run_cli_adapter().post_run_wall_wattage_prompt(run_dir, metadata)

    def _normalize_wall_wattage(self, raw: str) -> str:
        return self._run_cli_adapter().normalize_wall_wattage(raw)

    def _apply_run_metadata_update(self, run_dir: Path, metadata: RunMetadata) -> None:
        self._run_cli_adapter().apply_run_metadata_update(run_dir, metadata)
