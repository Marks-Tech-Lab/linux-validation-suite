from __future__ import annotations

from typing import Any, List

from Modules.lvs_cli_compat import BackRequested
from Modules.lvs_cli_screen import clear_cli_screen
from Modules.lvs_core import APP_NAME, APP_VERSION


class ShellCliAdapter:
    """Top-level CLI shell loop and main menu dispatch."""

    def __init__(self, launcher: Any) -> None:
        self.launcher = launcher

    def __getattr__(self, name: str) -> Any:
        return getattr(self.launcher, name)

    def start(self) -> None:
        try:
            while True:
                clear_cli_screen()
                print(f"\n=== {APP_NAME} v{APP_VERSION} ===")
                print(f"Mode: {self._environment_mode_label()}")
                if self._feature_enabled("department"):
                    print(f"Department: {self.settings_manager.settings.suite_department}")
                print(
                    "Enhanced telemetry: "
                    + ("enabled for this session" if self.settings_manager.settings.privileged_helper_enabled else "normal-user only")
                )
                print("Tip: press Esc, or type Escape/Back, to return.")
                actions: List[tuple[str, Any]] = [
                    ("Run Tests", self._run_tests_menu),
                    ("Profiles / Test Definitions", self._profiles_menu),
                    ("Diagnostics / Dependencies", self._diagnostics_menu),
                    ("Results / Reports", self._results_menu),
                ]
                if self._feature_enabled("google_upload"):
                    actions.append(("Upload / Sync", self.upload_cli.upload_menu))
                actions.extend(
                    [
                        ("Settings", self._settings_menu),
                        ("Exit", None),
                    ]
                )
                for index, (label, _) in enumerate(actions, start=1):
                    print(f"{index}. {label}")
                try:
                    choice = self._input("Select: ").strip()
                    try:
                        _label, action = actions[int(choice) - 1]
                    except Exception:
                        continue
                    if action is None:
                        return
                    action()
                except BackRequested:
                    print("Back.")
                except EOFError:
                    print()
                    return
        finally:
            self._stop_privileged_helper_keepalive()


class ShellCompatibilityMixin:
    """Compatibility delegates for legacy launcher shell helper methods."""

    def _shell_cli_adapter(self) -> ShellCliAdapter:
        adapter = getattr(self, "shell_cli", None)
        if adapter is None:
            adapter = ShellCliAdapter(self)
            self.shell_cli = adapter
        return adapter

    def start(self) -> None:
        self._shell_cli_adapter().start()
