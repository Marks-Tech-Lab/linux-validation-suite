from __future__ import annotations

import os
import shutil
import sys
from typing import Any

from Modules.lvs_privileged import PrivilegedTelemetryManager


class PrivilegedCliAdapter:
    """CLI prompt/messages for session-scoped privileged telemetry."""

    def __init__(self, launcher: Any) -> None:
        self.launcher = launcher
        manager = getattr(launcher, "privileged_telemetry", None)
        if manager is None:
            manager = PrivilegedTelemetryManager(launcher.settings_manager.settings)
            launcher.privileged_telemetry = manager
        self.manager: PrivilegedTelemetryManager = manager

    def __getattr__(self, name: str) -> Any:
        return getattr(self.launcher, name)

    def prompt_at_launch(self) -> None:
        settings = self.settings_manager.settings
        settings.privileged_helper_enabled = False
        settings.privileged_helper_prompt_for_sudo = True
        if os.geteuid() == 0:
            self.manager.enable_enhanced_telemetry()
            print("Privileged hardware telemetry is available because the suite is running as root.")
            return
        if shutil.which("sudo") is None:
            print("Privileged hardware telemetry unavailable: sudo was not found.")
            print("CPU package power and DIMM identity may be limited.")
            return
        if not sys.stdin.isatty():
            print("Privileged hardware telemetry skipped in non-interactive mode.")
            print("CPU package power and DIMM identity may be limited.")
            return
        print("\nEnhanced Hardware Telemetry")
        print("Some read-only hardware fields need sudo, such as RAPL CPU package power and dmidecode DIMM identity.")
        print("No password is stored by the suite; sudo handles the prompt and the suite keeps the sudo timestamp warm.")
        try:
            raw = self._input("Press Enter to skip, or type Y to enable enhanced telemetry for this session: ", allow_back=False)
        except (EOFError, KeyboardInterrupt):
            print("\nEnhanced telemetry skipped.")
            return
        if raw.strip().lower() not in {"y", "yes"}:
            print("Enhanced telemetry skipped. CPU package power and DIMM identity may be limited.")
            return
        if self.manager.enable_enhanced_telemetry():
            print("Enhanced telemetry enabled for this session.")
        else:
            print("Enhanced telemetry unavailable; continuing with normal-user telemetry.")

    def ensure_ready(self, context: str = "this operation") -> bool:
        settings = self.settings_manager.settings
        if not settings.privileged_helper_enabled:
            return False
        if os.geteuid() == 0:
            return True
        if shutil.which("sudo") is None:
            print("Privileged helper is enabled, but sudo is not available.")
            return False
        if self.manager.sudo_noninteractive_ready():
            return True
        print(f"Privileged telemetry session needs sudo refresh before {context}.")
        if self.manager.prepare_session():
            self.manager.start_keepalive()
            return True
        print("Privileged helper unavailable; continuing with normal-user telemetry.")
        settings.privileged_helper_enabled = False
        settings.privileged_helper_prompt_for_sudo = True
        return False

    def prepare_session(self) -> bool:
        return self.manager.prepare_session()

    def start_keepalive(self) -> None:
        self.manager.start_keepalive()

    def stop_keepalive(self) -> None:
        self.manager.stop_keepalive()

    def sudo_noninteractive_ready(self) -> bool:
        return self.manager.sudo_noninteractive_ready()


class PrivilegedCompatibilityMixin:
    """Compatibility delegates for legacy launcher privileged-helper methods."""

    def _privileged_cli_adapter(self) -> PrivilegedCliAdapter:
        adapter = getattr(self, "privileged_cli", None)
        if adapter is None:
            adapter = PrivilegedCliAdapter(self)
            self.privileged_cli = adapter
        return adapter

    def _prompt_privileged_helper_at_launch(self) -> None:
        self._privileged_cli_adapter().prompt_at_launch()

    def _ensure_privileged_helper_ready(self, context: str = "this operation") -> bool:
        return self._privileged_cli_adapter().ensure_ready(context)

    def _prepare_privileged_helper_session(self) -> bool:
        return self._privileged_cli_adapter().prepare_session()

    def _start_privileged_helper_keepalive(self) -> None:
        self._privileged_cli_adapter().start_keepalive()

    def _stop_privileged_helper_keepalive(self) -> None:
        self._privileged_cli_adapter().stop_keepalive()

    def _sudo_noninteractive_ready(self) -> bool:
        return self._privileged_cli_adapter().sudo_noninteractive_ready()
