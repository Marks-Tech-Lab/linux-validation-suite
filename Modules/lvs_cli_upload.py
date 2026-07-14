from __future__ import annotations

"""CLI adapter for Google Drive upload/readiness workflows."""

from pathlib import Path
from typing import Any, Dict

from .lvs_cli_compat import BackRequested, GoogleDriveUploader


class UploadCliAdapter:
    def __init__(self, launcher: Any) -> None:
        self.launcher = launcher

    def __getattr__(self, name: str) -> Any:
        return getattr(self.launcher, name)

    def upload_menu(self) -> None:
        while True:
            print("\nUpload / Sync")
            print("1. Upload Result Folder to Google Drive")
            print("2. Check Google Drive Upload Readiness")
            print("3. Configure Google Drive Settings")
            print("4. Back")
            choice = self._input("Select: ").strip()
            if choice == "1":
                self.google_drive_upload_result_folder()
            elif choice == "2":
                self.google_drive_readiness()
            elif choice == "3":
                self.google_drive_settings()
            elif choice == "4":
                return

    def google_drive_uploader(self) -> GoogleDriveUploader:
        return GoogleDriveUploader(self.settings_manager.settings)

    def google_drive_readiness(self) -> Dict[str, Any]:
        status = self.post_run_manager.google_drive_readiness()
        print()
        print(self.post_run_manager.google_drive_readiness_text())
        return status

    def google_drive_upload_result_folder(self) -> None:
        candidates = self.results_cli.result_artifact_candidates()
        if not candidates:
            print("No active result folders were found.")
            return
        self.results_cli.print_result_choices(candidates, heading="Available result folders to upload")
        choice = self._input("Choose result folder: ").strip()
        try:
            result_dir = candidates[int(choice) - 1]
        except Exception:
            print("Invalid selection.")
            return
        print(f"Selected: {result_dir}")
        status = self.google_drive_readiness()
        if not status.get("ready"):
            print("Upload cancelled because Google Drive readiness checks did not pass.")
            return
        confirm = self._input("Upload this folder now? [y/N]: ").strip().lower()
        if confirm not in {"y", "yes"}:
            print("Upload cancelled.")
            return
        attempt = self.post_run_manager.attempt_upload_result_folder(result_dir, status)
        payload = attempt.payload
        print()
        print(self.post_run_manager.upload_result_summary_text(payload))
        if not payload.get("moved_to") and (result_dir / "upload_manifest.json").exists():
            print(f"Upload manifest: {result_dir / 'upload_manifest.json'}")

    def google_drive_settings(self) -> None:
        settings = self.settings_manager.settings
        while True:
            print("\nGoogle Drive Settings")
            print(f"1. Credential path: {settings.google_drive_credentials_path}")
            print(f"2. Shared Drive ID: {'configured' if settings.google_drive_shared_drive_id else 'missing'}")
            print(f"3. Move to Uploaded after successful upload: {settings.google_drive_move_to_uploaded_on_success}")
            print(f"4. Prompt to upload after each run: {settings.google_drive_prompt_after_run}")
            print("5. Back")
            choice = self._input("Select: ").strip()
            if choice == "1":
                raw = self._input(f"Credential path [{settings.google_drive_credentials_path}]: ").strip()
                if raw:
                    settings.google_drive_credentials_path = raw
            elif choice == "2":
                raw = self._input("Shared Drive ID: ").strip()
                if raw:
                    settings.google_drive_shared_drive_id = raw
            elif choice == "3":
                settings.google_drive_move_to_uploaded_on_success = not settings.google_drive_move_to_uploaded_on_success
                print(f"Move to Uploaded: {settings.google_drive_move_to_uploaded_on_success}")
            elif choice == "4":
                settings.google_drive_prompt_after_run = not settings.google_drive_prompt_after_run
                print(f"Prompt after run: {settings.google_drive_prompt_after_run}")
            elif choice == "5":
                self.settings_manager.save()
                self._reload_runtime_state()
                return
            self.settings_manager.save()

    def post_run_google_drive_prompt(self, run_dir: Path) -> None:
        if not self._feature_enabled("google_upload"):
            return
        if not self.settings_manager.settings.google_drive_prompt_after_run:
            return
        try:
            raw = self._input("Upload this result folder to Google Drive now? [y/N]: ").strip().lower()
        except BackRequested:
            print("Upload skipped.")
            return
        if raw not in {"y", "yes"}:
            print("Upload skipped.")
            return
        status = self.google_drive_readiness()
        attempt = self.post_run_manager.attempt_upload_result_folder(run_dir, status)
        if not attempt.ready:
            print("Upload cancelled because Google Drive readiness checks did not pass.")
            return
        payload = attempt.payload
        print()
        print(self.post_run_manager.upload_result_summary_text(payload))
        manifest_path = run_dir / "upload_manifest.json"
        if not payload.get("moved_to") and manifest_path.exists():
            print(f"Upload manifest: {manifest_path}")
