#!/usr/bin/env python3
"""Default frontend/settings option lists for Linux Validation Suite."""

from __future__ import annotations


DEFAULT_PROFILE_MENU_GROUPS = [
    {"key": "standard", "label": "standard profile"},
    {"key": "quick", "label": "quick/smoke profile"},
    {"key": "gpu", "label": "GPU profile/lab"},
    {"key": "advanced", "label": "advanced/lab profile"},
    {"key": "diagnostic", "label": "diagnostic/smoke profile"},
    {"key": "custom", "label": "custom profile"},
]

DEFAULT_CASE_OPTIONS = [
    "Standard Tower",
    "Compact Tower",
    "Small Form Factor",
    "Rackmount 2U",
    "Rackmount 4U",
    "OEM",
    "Other (custom)",
]

DEFAULT_PSU_RATING_OPTIONS = [
    "Titanium",
    "Platinum",
    "Gold",
    "Bronze",
    "White",
    "Skip",
]

DEFAULT_CPU_COOLER_OPTIONS = [
    "Stock",
    "360mm AIO",
    "240mm AIO",
    "120mm AIO",
    "Dual Tower Cooler",
    "120mm Tower Cooler",
    "120mm Low Profile Cooler",
    "High Perf Low Profile Cooler",
    "Low Profile Cooler",
    "Box Cooler",
    "Other",
    "Skip",
]
