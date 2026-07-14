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
            print("2. Dry Run Selected Profile")
            print("3. Back")
            choice = self._input("Select: ").strip()
            if choice == "1":
                self.new_run()
            elif choice == "2":
                self._dry_run_diagnostics()
            elif choice == "3":
                return

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
