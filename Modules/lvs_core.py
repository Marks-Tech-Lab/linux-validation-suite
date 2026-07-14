#!/usr/bin/env python3
"""Small shared core primitives for Linux Validation Suite frontends."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


APP_NAME = "Linux Validation Suite"
APP_VERSION = "0.1.0-alpha"


def now_local_iso() -> str:
    return datetime.now().astimezone().isoformat()


def format_duration_hms(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


class JsonStore:
    @staticmethod
    def read(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    @staticmethod
    def write(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
