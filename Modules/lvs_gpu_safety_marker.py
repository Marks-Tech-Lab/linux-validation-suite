#!/usr/bin/env python3
"""GPU safety marker persistence for interrupted GPU workload detection."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .lvs_core import now_local_iso


class GpuSafetyMarkerStore:
    def __init__(self, settings_dir: str | Path) -> None:
        self.settings_dir = Path(settings_dir)

    def marker_path(self) -> Path:
        return self.settings_dir / "gpu_safety_marker.json"

    def read(self) -> dict[str, Any] | None:
        path = self.marker_path()
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload.setdefault("path", str(path))
                return payload
        except Exception:
            pass
        return {"path": str(path), "warning": "marker unreadable"}

    def write(
        self,
        *,
        profile_name: str,
        stage_name: str,
        gpu_backends: list[str],
        gpu_targets: list[str],
        run_dir: Path,
    ) -> None:
        path = self.marker_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "started": now_local_iso(),
            "pid": os.getpid(),
            "profile_name": profile_name,
            "stage_name": stage_name,
            "gpu_backends": gpu_backends,
            "gpu_targets": gpu_targets,
            "run_dir": str(run_dir),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def clear(self) -> None:
        path = self.marker_path()
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except Exception:
            return
