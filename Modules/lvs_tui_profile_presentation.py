"""Textual-free profile list presentation helpers for the optional TUI."""

from __future__ import annotations


def profile_summary_presentation(
    *,
    environment_mode: str,
    enhanced_telemetry: str,
    profile_summary: str,
) -> str:
    return (
        "Mode: "
        + str(environment_mode)
        + "\nEnhanced telemetry: "
        + str(enhanced_telemetry)
        + "\n\n"
        + str(profile_summary)
        + "\n\nActions:\n"
        "- Enter opens Run Setup for this profile.\n"
        "- N creates a new profile in the Profile Edit screen.\n"
        "- M opens Profile Edit for persistent profile changes.\n"
        "- D runs Dry Run / Diagnostics.\n"
        "- U starts run confirmation.\n"
        "- A audits all profiles.\n"
        "- E ensures the example PL Validation profile exists."
    )
