#!/usr/bin/env python3
"""Session-scoped privileged telemetry helper management."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from typing import Any, Optional


class PrivilegedTelemetryManager:
    """Manages sudo timestamp readiness for enhanced telemetry probes.

    The suite does not store passwords. It asks sudo to validate the current
    terminal session, then periodically refreshes the sudo timestamp.
    """

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self._keepalive_stop = threading.Event()
        self._keepalive_thread: Optional[threading.Thread] = None

    def enhanced_telemetry_label(self) -> str:
        return "enabled for this session" if self.settings.privileged_helper_enabled else "normal-user only"

    def enable_enhanced_telemetry(self) -> bool:
        if os.geteuid() == 0:
            self.settings.privileged_helper_enabled = True
            self.settings.privileged_helper_prompt_for_sudo = False
            return True
        if shutil.which("sudo") is None:
            return False
        if not self._prepare_session():
            self.settings.privileged_helper_enabled = False
            self.settings.privileged_helper_prompt_for_sudo = True
            return False
        self.settings.privileged_helper_enabled = True
        self.settings.privileged_helper_prompt_for_sudo = False
        self._start_keepalive()
        return True

    def ensure_ready(self) -> bool:
        if not self.settings.privileged_helper_enabled:
            return False
        if os.geteuid() == 0:
            return True
        if shutil.which("sudo") is None:
            self.settings.privileged_helper_enabled = False
            return False
        if self._sudo_noninteractive_ready():
            return True
        if self._prepare_session():
            self._start_keepalive()
            return True
        self.settings.privileged_helper_enabled = False
        self.settings.privileged_helper_prompt_for_sudo = True
        return False

    def stop_keepalive(self) -> None:
        self._keepalive_stop.set()
        thread = self._keepalive_thread
        if thread and thread.is_alive():
            thread.join(timeout=1)

    def prepare_session(self) -> bool:
        return self._prepare_session()

    def sudo_noninteractive_ready(self) -> bool:
        return self._sudo_noninteractive_ready()

    def start_keepalive(self) -> None:
        self._start_keepalive()

    def _prepare_session(self) -> bool:
        if os.geteuid() == 0:
            return True
        if shutil.which("sudo") is None:
            return False
        try:
            check = subprocess.run(["sudo", "-v"], check=False, timeout=60)
        except Exception:
            return False
        return check.returncode == 0

    def _sudo_noninteractive_ready(self) -> bool:
        if os.geteuid() == 0:
            return True
        if shutil.which("sudo") is None:
            return False
        try:
            check = subprocess.run(
                ["sudo", "-n", "true"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except Exception:
            return False
        return check.returncode == 0

    def _start_keepalive(self) -> None:
        if os.geteuid() == 0 or shutil.which("sudo") is None:
            return
        if self._keepalive_thread and self._keepalive_thread.is_alive():
            return
        self._keepalive_stop.clear()

        def keepalive() -> None:
            while not self._keepalive_stop.wait(60):
                try:
                    subprocess.run(
                        ["sudo", "-n", "-v"],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                except Exception:
                    return

        self._keepalive_thread = threading.Thread(
            target=keepalive,
            name="tui-privileged-helper-keepalive",
            daemon=True,
        )
        self._keepalive_thread.start()
