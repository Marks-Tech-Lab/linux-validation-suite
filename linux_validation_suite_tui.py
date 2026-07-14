#!/usr/bin/env python3
"""Optional Textual TUI launcher for Linux Validation Suite.

The CLI remains the stable entrypoint. The Textual app implementation lives in
``Modules/lvs_tui_app.py`` so this file stays a small optional-dependency
launcher.
"""

from __future__ import annotations

from Modules.linux_validation_suite_service import SuiteAppService


def _print_missing_textual_message() -> None:
    print("Textual is not installed.")
    print("Install it in the suite Python environment, then run this file again.")
    print("Examples:")
    print("  .venv/bin/python -m pip install textual")
    print("  uv pip install --python .venv/bin/python textual")
    print("Launch with:")
    print("  .venv/bin/python linux_validation_suite_tui.py")


def prompt_enhanced_telemetry(service: SuiteAppService) -> None:
    print("\nEnhanced telemetry setup")
    print("========================")
    print("Some hardware fields need sudo, such as RAPL CPU package power and dmidecode DIMM identity.")
    print("No password is stored by the suite; sudo handles the prompt and the suite keeps the sudo timestamp warm.")
    try:
        raw = input("Press Enter to skip, or type Y to enable enhanced telemetry for this TUI session: ")
    except (EOFError, KeyboardInterrupt):
        print("\nEnhanced telemetry skipped.")
        return
    if raw.strip().lower() not in {"y", "yes"}:
        print("Enhanced telemetry skipped. CPU package power and DIMM identity may be limited.")
        return
    if service.enable_enhanced_telemetry():
        print("Enhanced telemetry enabled for this session.")
    else:
        print("Enhanced telemetry unavailable; continuing with normal-user telemetry.")


def main() -> int:
    try:
        from Modules.lvs_tui_app import LinuxValidationSuiteTui
    except ModuleNotFoundError:
        _print_missing_textual_message()
        return 2

    service = SuiteAppService()
    prompt_enhanced_telemetry(service)
    try:
        LinuxValidationSuiteTui(service).run()
    finally:
        service.stop_enhanced_telemetry_keepalive()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
