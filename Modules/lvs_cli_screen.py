from __future__ import annotations

import os
import sys
from typing import TextIO


def cli_screen_refresh_supported(stream: TextIO | None = None) -> bool:
    """Return true when menu redraws can safely use ANSI screen refresh."""

    target = stream or sys.stdout
    try:
        return bool(target.isatty()) and os.environ.get("TERM", "") not in {"", "dumb"}
    except Exception:
        return False


def clear_cli_screen(stream: TextIO | None = None) -> bool:
    """Clear/redraw helper for interactive CLI screens.

    Redirected output intentionally remains append-only so logs and scripted
    smoke runs keep the same plain transcript behavior.
    """

    target = stream or sys.stdout
    if not cli_screen_refresh_supported(target):
        return False
    target.write("\033[H\033[J")
    target.flush()
    return True
