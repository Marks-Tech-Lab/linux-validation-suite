#!/usr/bin/env python3
"""Google Drive upload/readiness helper."""

from __future__ import annotations

import importlib.util
import mimetypes
import shutil
import socket
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .lvs_core import APP_NAME, APP_VERSION, JsonStore, now_local_iso
from .lvs_settings import DEFAULT_GOOGLE_CREDENTIALS_PATH, GlobalSettings


class GoogleDriveUploader:
    AUTH_HOST = "oauth2.googleapis.com"
    DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
    SCOPES = (
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive",
    )

    def __init__(self, settings: GlobalSettings) -> None:
        self.settings = settings

    def credentials_path(self) -> Path:
        return Path(str(self.settings.google_drive_credentials_path or DEFAULT_GOOGLE_CREDENTIALS_PATH)).expanduser()

    def readiness(self) -> Dict[str, Any]:
        credential_path = self.credentials_path()

        def module_available(name: str) -> bool:
            try:
                return importlib.util.find_spec(name) is not None
            except Exception:
                return False

        modules = {
            "google.oauth2.service_account": module_available("google.oauth2.service_account"),
            "googleapiclient.discovery": module_available("googleapiclient.discovery"),
            "googleapiclient.http": module_available("googleapiclient.http"),
        }
        dns_ok = False
        dns_error = ""
        try:
            socket.gethostbyname(self.AUTH_HOST)
            dns_ok = True
        except Exception as exc:
            dns_error = str(exc)
        shared_drive_id = str(self.settings.google_drive_shared_drive_id or "").strip()
        missing = []
        if not credential_path.exists():
            missing.append("credential_file")
        if not shared_drive_id:
            missing.append("shared_drive_id")
        for module_name, available in modules.items():
            if not available:
                missing.append(module_name)
        if not dns_ok:
            missing.append("google_dns")
        return {
            "credential_path": str(credential_path),
            "credential_exists": credential_path.exists(),
            "shared_drive_id_configured": bool(shared_drive_id),
            "python_modules": modules,
            "dns_host": self.AUTH_HOST,
            "dns_ok": dns_ok,
            "dns_error": dns_error,
            "move_to_uploaded_on_success": bool(self.settings.google_drive_move_to_uploaded_on_success),
            "missing": missing,
            "ready": not missing,
        }

    def upload_result_folder(self, result_dir: Path) -> Dict[str, Any]:
        result_dir = result_dir.resolve()
        started = now_local_iso()
        payload: Dict[str, Any] = {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "kind": "google_drive_upload",
            "started": started,
            "source_folder": str(result_dir),
            "source_folder_name": result_dir.name,
            "destination": {},
            "files": [],
            "errors": [],
            "warnings": [],
            "uploaded_count": 0,
            "file_count": 0,
            "result": "started",
        }
        if not result_dir.exists() or not result_dir.is_dir():
            payload["errors"].append(f"result folder not found: {result_dir}")
            payload["result"] = "failed"
            payload["ended"] = now_local_iso()
            return payload

        readiness = self.readiness()
        payload["readiness"] = readiness
        if not readiness.get("ready"):
            payload["errors"].append("Google Drive upload is not ready: " + ", ".join(readiness.get("missing") or []))
            payload["result"] = "failed"
            payload["ended"] = now_local_iso()
            self._write_local_manifest(result_dir, payload)
            return payload

        try:
            service = self._drive_service()
            year = datetime.now().year
            month = datetime.now().strftime("%B")
            year_folder_id = self._find_or_create_folder(service, str(year), None)
            month_folder_id = self._find_or_create_folder(service, month, year_folder_id)
            test_folder_id, test_folder_name = self._create_unique_folder(service, result_dir.name, month_folder_id)
            payload["destination"] = {
                "shared_drive_id": str(self.settings.google_drive_shared_drive_id or "").strip(),
                "year": str(year),
                "month": month,
                "folder_id": test_folder_id,
                "folder_name": test_folder_name,
            }

            source_files = [
                path
                for path in sorted(result_dir.rglob("*"))
                if path.is_file() and path.name not in {"upload_manifest.json", "google_drive_upload.json"}
            ]
            payload["file_count"] = len(source_files)
            folder_cache: Dict[Path, str] = {Path("."): test_folder_id}
            for path in source_files:
                relative_path = path.relative_to(result_dir)
                parent_id = self._drive_parent_for_relative_path(service, relative_path.parent, folder_cache)
                file_payload = self._upload_file(service, path, relative_path, parent_id)
                payload["files"].append(file_payload)
                if file_payload.get("status") == "uploaded":
                    payload["uploaded_count"] += 1
                else:
                    payload["errors"].append(f"{relative_path}: {file_payload.get('error') or 'upload failed'}")

            payload["ended"] = now_local_iso()
            payload["result"] = "uploaded" if payload["uploaded_count"] == payload["file_count"] else "partial"
            self._write_local_manifest(result_dir, payload)

            manifest_payload = self._upload_file(
                service,
                result_dir / "upload_manifest.json",
                Path("upload_manifest.json"),
                test_folder_id,
            )
            payload["manifest_upload"] = manifest_payload
            if manifest_payload.get("status") != "uploaded":
                payload["result"] = "partial"
                payload["errors"].append("upload_manifest.json could not be uploaded")
                self._write_local_manifest(result_dir, payload)

            if payload["result"] == "uploaded" and self.settings.google_drive_move_to_uploaded_on_success:
                moved_to = self._move_to_uploaded(result_dir)
                payload["moved_to"] = str(moved_to)
                self._write_local_manifest(moved_to, payload)
        except Exception as exc:
            payload["result"] = "failed"
            payload["errors"].append(str(exc))
            payload["ended"] = now_local_iso()
            self._write_local_manifest(result_dir, payload)
        return payload

    def _drive_service(self) -> Any:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_file(
            str(self.credentials_path()),
            scopes=list(self.SCOPES),
        )
        return build("drive", "v3", credentials=credentials, cache_discovery=False)

    def _drive_parent_for_relative_path(
        self,
        service: Any,
        relative_parent: Path,
        folder_cache: Dict[Path, str],
    ) -> str:
        if str(relative_parent) in {"", "."}:
            return folder_cache[Path(".")]
        current = Path(".")
        parent_id = folder_cache[current]
        for part in relative_parent.parts:
            current = current / part
            if current not in folder_cache:
                folder_cache[current] = self._find_or_create_folder(service, part, parent_id)
            parent_id = folder_cache[current]
        return parent_id

    def _find_or_create_folder(self, service: Any, folder_name: str, parent_id: Optional[str]) -> str:
        parent = parent_id or str(self.settings.google_drive_shared_drive_id or "").strip()
        existing = self._find_folder(service, folder_name, parent)
        if existing:
            return existing
        body = {
            "name": folder_name,
            "mimeType": self.DRIVE_FOLDER_MIME,
            "parents": [parent],
        }
        created = service.files().create(
            body=body,
            supportsAllDrives=True,
            fields="id,name",
        ).execute()
        return str(created["id"])

    def _create_unique_folder(self, service: Any, base_name: str, parent_id: str) -> tuple[str, str]:
        folder_name = base_name
        counter = 1
        while True:
            if not self._find_folder(service, folder_name, parent_id):
                body = {
                    "name": folder_name,
                    "mimeType": self.DRIVE_FOLDER_MIME,
                    "parents": [parent_id],
                }
                created = service.files().create(
                    body=body,
                    supportsAllDrives=True,
                    fields="id,name",
                ).execute()
                return str(created["id"]), folder_name
            counter += 1
            folder_name = f"{base_name}({counter})"

    def _find_folder(self, service: Any, folder_name: str, parent_id: str) -> str:
        query = (
            f"name = {self._drive_literal(folder_name)} "
            + f"and mimeType = {self._drive_literal(self.DRIVE_FOLDER_MIME)} "
            + "and trashed = false "
            + f"and {self._drive_literal(parent_id)} in parents"
        )
        request = service.files().list(
            q=query,
            corpora="drive",
            driveId=str(self.settings.google_drive_shared_drive_id or "").strip(),
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            fields="files(id,name)",
            pageSize=10,
        )
        result = request.execute()
        files = result.get("files") or []
        return str(files[0]["id"]) if files else ""

    def _upload_file(self, service: Any, path: Path, relative_path: Path, parent_id: str) -> Dict[str, Any]:
        from googleapiclient.http import MediaFileUpload

        payload: Dict[str, Any] = {
            "relative_path": str(relative_path),
            "size_bytes": path.stat().st_size if path.exists() else 0,
            "status": "pending",
        }
        try:
            mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            media = MediaFileUpload(str(path), mimetype=mime_type, resumable=True)
            request = service.files().create(
                body={"name": path.name, "parents": [parent_id]},
                media_body=media,
                supportsAllDrives=True,
                fields="id,name,size,md5Checksum",
            )
            response = None
            while response is None:
                _, response = request.next_chunk()
            payload.update(
                {
                    "status": "uploaded",
                    "drive_file_id": response.get("id"),
                    "drive_name": response.get("name"),
                    "drive_size": response.get("size"),
                    "drive_md5": response.get("md5Checksum"),
                    "mime_type": mime_type,
                }
            )
        except Exception as exc:
            payload["status"] = "failed"
            payload["error"] = str(exc)
        return payload

    def _move_to_uploaded(self, result_dir: Path) -> Path:
        uploaded_root = Path(self.settings.results_dir) / "Uploaded"
        uploaded_root.mkdir(parents=True, exist_ok=True)
        destination = uploaded_root / result_dir.name
        counter = 1
        while destination.exists():
            counter += 1
            destination = uploaded_root / f"{result_dir.name}({counter})"
        shutil.move(str(result_dir), str(destination))
        return destination

    def _write_local_manifest(self, result_dir: Path, payload: Dict[str, Any]) -> None:
        try:
            JsonStore.write(result_dir / "upload_manifest.json", payload)
            JsonStore.write(result_dir / "google_drive_upload.json", payload)
        except Exception:
            pass

    def _drive_literal(self, value: str) -> str:
        return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"
