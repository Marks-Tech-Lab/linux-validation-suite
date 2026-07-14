#!/usr/bin/env python3
"""Post-run metadata, wall-wattage, and upload helpers for UI frontends."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict

from .lvs_core import JsonStore
from .lvs_google_drive_uploader import GoogleDriveUploader


@dataclass
class PostRunOutcome:
    status: str
    text: str


@dataclass
class WallWattageInputResult:
    raw: str
    normalized: str
    message: str
    saved: bool = False
    skipped: bool = False


@dataclass
class GoogleDriveUploadAttempt:
    result_dir: Path
    readiness: Dict[str, Any]
    payload: Dict[str, Any]
    ready: bool = False


class PostRunManager:
    """Keeps post-run result mutations out of frontend service code."""

    def __init__(self, settings: Any, summary_exporter: Any) -> None:
        self.settings = settings
        self.summary_exporter = summary_exporter

    def normalize_wall_wattage(self, raw: str) -> str:
        text = str(raw or "").strip()
        if not text or text.lower() in {"skip", "none", "-"}:
            return ""
        cleaned = text.upper().rstrip("W").strip()
        try:
            value = float(cleaned)
            if value <= 0:
                return ""
            return f"{int(value) if value.is_integer() else value:g}W"
        except Exception:
            return ""

    def save_wall_wattage(self, result_dir: Path, metadata: Any, raw: str) -> str:
        return self.handle_wall_wattage_input(result_dir, metadata, raw).normalized

    def handle_wall_wattage_input(self, result_dir: Path, metadata: Any, raw: str) -> WallWattageInputResult:
        raw_text = str(raw or "")
        normalized = self.normalize_wall_wattage(raw)
        if normalized:
            metadata.wall_wattage = normalized
            self.apply_run_metadata_update(result_dir, metadata)
            return WallWattageInputResult(
                raw=raw_text,
                normalized=normalized,
                message=f"Wall wattage saved: {normalized}",
                saved=True,
            )
        if not raw_text.strip():
            return WallWattageInputResult(
                raw=raw_text,
                normalized="",
                message="Wall wattage skipped.",
                skipped=True,
            )
        return WallWattageInputResult(
            raw=raw_text,
            normalized="",
            message="Invalid wall wattage. Leaving result unchanged.",
        )

    def run_complete_outcome(self, result_dir: Path, summary_text: str) -> PostRunOutcome:
        text = (
            "Run complete\n"
            "============\n\n"
            f"Result folder: {result_dir}\n\n"
            "Post-run actions:\n"
            "- Press W to save max wall wattage.\n"
            "- Press G to upload this result folder to Google Drive.\n\n"
            "Run summary:\n"
            f"{summary_text}"
        )
        return PostRunOutcome(status="Run complete", text=text)

    def wall_wattage_prompt_outcome(self, result_dir: Path, completed_text: str = "") -> PostRunOutcome:
        text = (
            (completed_text.rstrip() + "\n\n" if completed_text else "")
            + "Post-Run Wall Wattage\n"
            "=====================\n\n"
            f"Result folder: {result_dir}\n\n"
            "Enter the maximum wall wattage observed during the run below and press Enter. "
            "Leave blank and press Enter to skip. Press Esc to cancel this prompt."
        )
        return PostRunOutcome(status="Run complete | Waiting for wall wattage", text=text)

    def wall_wattage_result_outcome(self, result_dir: Path, raw: str, normalized: str, base_text: str) -> PostRunOutcome:
        if normalized:
            message = f"Wall wattage saved: {normalized}"
        elif not str(raw or "").strip():
            message = "Wall wattage skipped."
        else:
            message = "Invalid wall wattage. Result was not changed."
        return PostRunOutcome(status="Run complete | Wall wattage handled", text=base_text.rstrip() + f"\n\n{message}")

    def upload_prompt_outcome(self, result_dir: Path, completed_text: str = "") -> PostRunOutcome:
        text = (
            (completed_text.rstrip() + "\n\n" if completed_text else "")
            + "Google Drive Upload\n"
            "===================\n\n"
            f"Result folder: {result_dir}\n\n"
            "Choose an option from the left. Upload will not start unless you select it. "
            "Press Esc to skip."
        )
        return PostRunOutcome(status="Run complete | Waiting for upload choice", text=text)

    def upload_skipped_outcome(self, base_text: str) -> PostRunOutcome:
        return PostRunOutcome(status="Run complete | Upload skipped", text=base_text.rstrip() + "\n\nGoogle Drive upload skipped.")

    def upload_result_outcome(self, payload: Dict[str, Any]) -> PostRunOutcome:
        result = str(payload.get("result") or "failed") if isinstance(payload, dict) else "failed"
        return PostRunOutcome(status=f"Google Drive upload {result}", text=self.upload_result_summary_text(payload))

    def apply_run_metadata_update(self, result_dir: Path, metadata: Any) -> None:
        result_dir = Path(result_dir)
        metadata_payload = asdict(metadata)
        JsonStore.write(result_dir / "run_metadata.json", metadata_payload)

        parsed_path = result_dir / "parsed_results_custom.json"
        if parsed_path.exists():
            parsed = self._read_json(parsed_path)
            parsed["wall_wattage"] = metadata.wall_wattage
            metadata_block = parsed.get("Metadata") if isinstance(parsed.get("Metadata"), dict) else {}
            self._apply_metadata_block(metadata_block, metadata, parsed)
            parsed["Metadata"] = metadata_block
            JsonStore.write(parsed_path, parsed)
            (result_dir / "run_summary.txt").write_text(
                self.summary_exporter.build(parsed),
                encoding="utf-8",
            )

        extended_path = result_dir / "parsed_results_extended.json"
        if extended_path.exists():
            extended = self._read_json(extended_path)
            extended["run_metadata"] = metadata_payload
            compat = extended.get("compatibility_export") if isinstance(extended.get("compatibility_export"), dict) else {}
            if compat:
                compat["wall_wattage"] = metadata.wall_wattage
                compat_metadata = compat.get("Metadata") if isinstance(compat.get("Metadata"), dict) else {}
                self._apply_metadata_block(compat_metadata, metadata, compat)
                compat["Metadata"] = compat_metadata
                extended["compatibility_export"] = compat
            JsonStore.write(extended_path, extended)

        manifest_path = result_dir / "run_manifest.json"
        if manifest_path.exists():
            manifest = self._read_json(manifest_path)
            manifest["metadata"] = metadata_payload
            JsonStore.write(manifest_path, manifest)

    def google_drive_readiness(self) -> Dict[str, Any]:
        return GoogleDriveUploader(self.settings).readiness()

    def google_drive_readiness_text(self) -> str:
        status = self.google_drive_readiness()
        modules = status.get("python_modules") if isinstance(status.get("python_modules"), dict) else {}
        missing = ", ".join(str(item) for item in status.get("missing") or []) or "none"
        lines = [
            "Google Drive Upload Readiness",
            "=============================",
            f"Credentials: {'OK' if status.get('credential_exists') else 'missing'}",
            f"Credential path: {status.get('credential_path') or '-'}",
            f"Shared Drive ID: {'configured' if status.get('shared_drive_id_configured') else 'missing'}",
            f"Google DNS: {'OK' if status.get('dns_ok') else 'missing'}",
        ]
        if status.get("dns_error"):
            lines.append(f"  {status.get('dns_error')}")
        lines.append("Python Google API modules:")
        for name, available in modules.items():
            lines.append(f"  - {name}: {'OK' if available else 'missing'}")
        lines.extend(
            [
                f"Ready: {'yes' if status.get('ready') else 'no'}",
                f"Missing: {missing}",
            ]
        )
        return "\n".join(lines)

    def upload_result_folder(self, result_dir: Path) -> Dict[str, Any]:
        return GoogleDriveUploader(self.settings).upload_result_folder(result_dir)

    def attempt_upload_result_folder(
        self,
        result_dir: Path,
        readiness: Dict[str, Any] | None = None,
    ) -> GoogleDriveUploadAttempt:
        result_dir = Path(result_dir)
        status = readiness if isinstance(readiness, dict) else self.google_drive_readiness()
        if not status.get("ready"):
            return GoogleDriveUploadAttempt(
                result_dir=result_dir,
                readiness=status,
                payload={},
                ready=False,
            )
        return GoogleDriveUploadAttempt(
            result_dir=result_dir,
            readiness=status,
            payload=self.upload_result_folder(result_dir),
            ready=True,
        )

    def upload_result_summary_text(self, payload: Dict[str, Any]) -> str:
        result = str(payload.get("result") or "unknown")
        lines = [
            "Google Drive Upload",
            "===================",
            "",
            f"Result: {result}",
            f"Uploaded files: {payload.get('uploaded_count', 0)}/{payload.get('file_count', 0)}",
        ]
        destination = payload.get("destination") if isinstance(payload.get("destination"), dict) else {}
        if destination.get("folder_name"):
            lines.append(
                "Drive folder: "
                + f"{destination.get('year')}/{destination.get('month')}/{destination.get('folder_name')}"
            )
        if payload.get("moved_to"):
            lines.append(f"Moved local folder to: {payload.get('moved_to')}")
        elif payload.get("source_folder"):
            lines.append(f"Local folder: {payload.get('source_folder')}")
        errors = list(payload.get("errors") or [])
        if errors:
            lines.append("")
            lines.append("Errors:")
            lines.extend(f"- {error}" for error in errors[:10])
        return "\n".join(lines)

    def _apply_metadata_block(self, metadata_block: Dict[str, Any], metadata: Any, root: Dict[str, Any]) -> None:
        metadata_block["MaxWallWattage"] = metadata.wall_wattage or "-"
        metadata_block["Case"] = metadata.case_sku or "-"
        metadata_block["Description"] = metadata.description or "-"
        metadata_block["CombinedDescription"] = (
            f"{metadata.case_sku}={metadata.description}"
            if metadata.case_sku or metadata.description
            else "-"
        )
        metadata_block["PsuWattage"] = metadata.psu_wattage or "-"
        metadata_block["PsuRating"] = metadata.psu_rating or "-"
        existing_power_limit_data = (
            metadata_block.get("PowerLimitData")
            or root.get("PowerLimitData")
            or root.get("power_limit_data")
            or ""
        )
        updated_power_limit_data = metadata.power_limit_data or existing_power_limit_data
        metadata_block["PowerLimitData"] = updated_power_limit_data or "-"
        root["PowerLimitData"] = updated_power_limit_data
        root["power_limit_data"] = updated_power_limit_data
        metadata_block["CpuCooler"] = metadata.cpu_cooler or "-"
        metadata_block["FanType"] = metadata.fan_type or "-"
        metadata_block["FanDetails"] = metadata.fan_details or "-"
        metadata_block["AdvancedDebugLogging"] = bool(getattr(metadata, "advanced_debug_logging", False))

    def _read_json(self, path: Path) -> Dict[str, Any]:
        payload = JsonStore.read(path, {})
        return payload if isinstance(payload, dict) else {}
