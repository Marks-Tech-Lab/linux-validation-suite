#!/usr/bin/env python3
"""Optional per-run hardware/debug log capture."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


GPU_LOG_FILTER_TERMS = (
    "nvrm",
    "xid",
    "fallen off",
    "gpu has fallen",
    "aer",
    "pcie",
    "pcieport",
    "nvlink",
    "nvidia",
    "amdgpu",
    "radeon",
    "i915",
    "xe ",
    "nouveau",
    "drm",
    "radv",
    "vulkan",
    "reset",
    "timeout",
    "fault",
    "hang",
    "thermal",
    "overheat",
    "hwmon",
)


class AdvancedDebugLogger:
    """Best-effort debug collector for GPU dropouts and driver resets.

    This class is intentionally non-fatal. Missing commands, permission errors,
    and unsupported devices are written into the log instead of raising.
    """

    def __init__(
        self,
        run_dir: Path,
        *,
        enabled: bool = False,
        runtime_environment: Optional[Dict[str, str]] = None,
        scope: str = "",
    ) -> None:
        self.run_dir = Path(run_dir)
        self.enabled = bool(enabled)
        self.runtime_environment = {str(k): str(v) for k, v in (runtime_environment or {}).items()}
        self.scope = self._safe_name(scope) if scope else ""
        self.debug_dir = self.run_dir / "advanced_debug" / self.scope if self.scope else self.run_dir / "advanced_debug"
        log_name = f"{self.scope}_debug_log.txt" if self.scope else "advanced_debug_log.txt"
        manifest_name = f"{self.scope}_debug_manifest.json" if self.scope else "advanced_debug_manifest.json"
        self.log_path = self.debug_dir / log_name
        self.manifest_path = self.debug_dir / manifest_name
        self.events: List[Dict[str, Any]] = []
        self._load_existing_events()

    def capture_run_start(self, *, started_iso: str, profile_name: str) -> None:
        if not self.enabled:
            return
        self._ensure_dirs()
        self._append_header("Advanced Debug Logging")
        self._append_line(f"Enabled: true")
        self._append_line(f"Started: {started_iso}")
        self._append_line(f"Profile: {profile_name}")
        self._capture_event("run_start", started_iso=started_iso, profile_name=profile_name)
        self._capture_baseline_commands("run_start")
        self._write_manifest()

    def capture_heatsoak_start(self, *, timestamp_iso: str, duration_seconds: int) -> None:
        if not self.enabled:
            return
        self._ensure_dirs()
        self._append_header("Advanced Debug Heatsoak Logging")
        self._append_line("Scope: heatsoak only; not part of the logged validation stage data.")
        self._append_line(f"Started: {timestamp_iso}")
        self._append_line(f"Planned duration seconds: {int(duration_seconds)}")
        self._capture_event(
            "heatsoak_start",
            timestamp_iso=timestamp_iso,
            duration_seconds=int(duration_seconds),
        )
        self._capture_baseline_commands("heatsoak_start")
        self._write_manifest()

    def capture_heatsoak_end(
        self,
        *,
        timestamp_iso: str,
        since_iso: str,
        verdict: str,
    ) -> None:
        if not self.enabled:
            return
        self._capture_event(
            "heatsoak_end",
            timestamp_iso=timestamp_iso,
            since_iso=since_iso,
            verdict=verdict,
        )
        self._capture_baseline_commands("heatsoak_end")
        self._capture_kernel_log("heatsoak", since_iso=since_iso)
        self._write_manifest()

    def capture_stage_start(self, *, stage_name: str, stage_id: str, timestamp_iso: str) -> None:
        if not self.enabled:
            return
        self._capture_event("stage_start", stage_name=stage_name, stage_id=stage_id, timestamp_iso=timestamp_iso)
        self._write_manifest()

    def capture_stage_end(
        self,
        *,
        stage_name: str,
        stage_id: str,
        timestamp_iso: str,
        since_iso: str,
        verdict: str,
    ) -> None:
        if not self.enabled:
            return
        self._capture_event(
            "stage_end",
            stage_name=stage_name,
            stage_id=stage_id,
            timestamp_iso=timestamp_iso,
            since_iso=since_iso,
            verdict=verdict,
        )
        self._capture_kernel_log(f"stage_{self._safe_name(stage_id or stage_name)}", since_iso=since_iso)
        self._write_manifest()

    def capture_run_end(self, *, ended_iso: str, since_iso: str, verdict: str) -> None:
        if not self.enabled:
            return
        self._capture_event("run_end", ended_iso=ended_iso, since_iso=since_iso, verdict=verdict)
        self._capture_baseline_commands("run_end")
        self._capture_kernel_log("run", since_iso=since_iso)
        self._write_manifest()

    def _capture_event(self, event: str, **payload: Any) -> None:
        timestamp = datetime.now().isoformat(timespec="seconds")
        self._append_header(f"Event: {event}")
        self._append_line(f"Captured: {timestamp}")
        for key, value in payload.items():
            self._append_line(f"{key}: {value}")
        snapshot = self._drm_snapshot()
        snapshot_file = self.debug_dir / f"{len(self.events) + 1:03d}_{event}_drm_snapshot.json"
        self._write_json(snapshot_file, snapshot)
        self._append_line(f"DRM snapshot: {snapshot_file.name}")
        self.events.append(
            {
                "event": event,
                "captured": timestamp,
                "payload": payload,
                "drm_snapshot": str(snapshot_file.relative_to(self.run_dir)),
            }
        )

    def _capture_baseline_commands(self, prefix: str) -> None:
        commands = [
            ("uname", ["uname", "-a"], 5),
            ("lspci", ["lspci", "-nn"], 10),
            ("lsmod", ["lsmod"], 10),
            ("nvidia_smi_list", ["nvidia-smi", "-L"], 10),
            (
                "nvidia_smi_query",
                [
                    "nvidia-smi",
                    "--query-gpu=timestamp,index,pci.bus_id,uuid,name,pstate,power.draw,power.limit,temperature.gpu,temperature.memory,utilization.gpu,utilization.memory,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                10,
            ),
            ("nvidia_smi_q", ["nvidia-smi", "-q", "-d", "TEMPERATURE,POWER,CLOCK,PERFORMANCE,PCIE,UTILIZATION,MEMORY"], 20),
            ("vulkaninfo_summary", ["vulkaninfo", "--summary"], 25),
            ("clinfo_list", ["clinfo", "-l"], 15),
            ("intel_gpu_top_list", ["intel_gpu_top", "-L"], 8),
        ]
        for name, command, timeout in commands:
            self._capture_command(f"{prefix}_{name}", command, timeout=timeout)

    def _capture_kernel_log(self, prefix: str, *, since_iso: str) -> None:
        if shutil.which("journalctl"):
            self._capture_command(
                f"{prefix}_journalctl_kernel_filtered",
                ["journalctl", "-k", "--since", since_iso, "--no-pager", "--output", "short-iso"],
                timeout=20,
                filter_terms=GPU_LOG_FILTER_TERMS,
                max_chars=250_000,
            )
        if shutil.which("dmesg"):
            self._capture_command(
                f"{prefix}_dmesg_filtered",
                ["dmesg", "--time-format", "iso"],
                timeout=12,
                filter_terms=GPU_LOG_FILTER_TERMS,
                max_chars=250_000,
            )

    def _capture_command(
        self,
        label: str,
        command: List[str],
        *,
        timeout: int,
        filter_terms: Iterable[str] = (),
        max_chars: int = 120_000,
    ) -> None:
        safe_label = self._safe_name(label)
        output_path = self.debug_dir / f"{safe_label}.txt"
        if not command or shutil.which(command[0]) is None:
            self._write_text(output_path, f"Command unavailable: {' '.join(command)}\n")
            self._append_line(f"{safe_label}: command unavailable")
            return
        env = os.environ.copy()
        env.update(self.runtime_environment)
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            output = (
                f"$ {' '.join(command)}\n"
                f"returncode: {completed.returncode}\n\n"
                "[stdout]\n"
                f"{completed.stdout or ''}\n"
                "[stderr]\n"
                f"{completed.stderr or ''}\n"
            )
        except Exception as exc:
            output = f"$ {' '.join(command)}\nerror: {exc}\n"
        if filter_terms:
            output = self._filter_lines(output, filter_terms)
        if len(output) > max_chars:
            output = output[-max_chars:]
            output = "[truncated to trailing output]\n" + output
        self._write_text(output_path, output)
        self._append_line(f"{safe_label}: {output_path.name}")

    def _drm_snapshot(self) -> Dict[str, Any]:
        cards: List[Dict[str, Any]] = []
        for card in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
            if "-" in card.name:
                continue
            device_dir = card / "device"
            entry: Dict[str, Any] = {
                "card": card.name,
                "device_path": str(device_dir),
                "exists": device_dir.exists(),
                "uevent": self._read_key_value_lines(device_dir / "uevent"),
                "vendor": self._safe_read(device_dir / "vendor"),
                "device": self._safe_read(device_dir / "device"),
                "subsystem_vendor": self._safe_read(device_dir / "subsystem_vendor"),
                "subsystem_device": self._safe_read(device_dir / "subsystem_device"),
                "gpu_busy_percent": self._safe_read(device_dir / "gpu_busy_percent"),
                "mem_busy_percent": self._safe_read(device_dir / "mem_busy_percent"),
                "mem_info_vram_total": self._safe_read(device_dir / "mem_info_vram_total"),
                "mem_info_vram_used": self._safe_read(device_dir / "mem_info_vram_used"),
                "driver": "",
                "hwmon": [],
            }
            try:
                entry["driver"] = str((device_dir / "driver").resolve())
            except Exception:
                entry["driver"] = ""
            for hwmon in sorted((device_dir / "hwmon").glob("hwmon*")):
                hwmon_entry: Dict[str, Any] = {
                    "name": self._safe_read(hwmon / "name"),
                    "path": str(hwmon),
                    "values": {},
                }
                for pattern in ("temp*_input", "power*_average", "power*_input", "energy*_input", "fan*_input"):
                    for path in sorted(hwmon.glob(pattern)):
                        hwmon_entry["values"][path.name] = {
                            "value": self._safe_read(path),
                            "label": self._safe_read(path.with_name(path.name.replace("_input", "_label").replace("_average", "_label"))),
                        }
                entry["hwmon"].append(hwmon_entry)
            cards.append(entry)
        return {"captured": datetime.now().isoformat(timespec="seconds"), "cards": cards}

    def _filter_lines(self, text: str, terms: Iterable[str]) -> str:
        lowered_terms = tuple(str(term or "").lower() for term in terms if str(term or "").strip())
        if not lowered_terms:
            return text
        lines = []
        for line in text.splitlines():
            lowered = line.lower()
            if any(term in lowered for term in lowered_terms):
                lines.append(line)
        return "\n".join(lines) + ("\n" if lines else "")

    def _read_key_value_lines(self, path: Path) -> Dict[str, str]:
        text = self._safe_read(path)
        values: Dict[str, str] = {}
        for line in text.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
        return values

    def _safe_read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            return ""

    def _ensure_dirs(self) -> None:
        self.debug_dir.mkdir(parents=True, exist_ok=True)

    def _append_header(self, text: str) -> None:
        self._ensure_dirs()
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write("\n" + str(text).strip() + "\n")
            handle.write("=" * len(str(text).strip()) + "\n")

    def _append_line(self, text: str) -> None:
        self._ensure_dirs()
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(str(text) + "\n")

    def _write_text(self, path: Path, text: str) -> None:
        self._ensure_dirs()
        path.write_text(text, encoding="utf-8", errors="ignore")

    def _write_json(self, path: Path, payload: Any) -> None:
        self._ensure_dirs()
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _write_manifest(self) -> None:
        self._write_json(
            self.manifest_path,
            {
                "enabled": self.enabled,
                "scope": self.scope or "run",
                "debug_dir": str(self.debug_dir.relative_to(self.run_dir)),
                "log_file": str(self.log_path.relative_to(self.run_dir)),
                "events": self.events,
                "filter_terms": list(GPU_LOG_FILTER_TERMS),
            },
        )

    def _load_existing_events(self) -> None:
        if not self.manifest_path.exists():
            return
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            events = payload.get("events")
            if isinstance(events, list):
                self.events = [event for event in events if isinstance(event, dict)]
        except Exception:
            self.events = []

    def _safe_name(self, value: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or "").strip())
        return safe.strip("_") or "debug"
