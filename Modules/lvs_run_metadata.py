#!/usr/bin/env python3
"""Run metadata model shared by CLI, service, TUI, and future GUI layers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RunMetadata:
    serial: str = ""
    order: str = ""
    dept: str = "Production"
    notes: str = ""
    wall_wattage: str = ""
    operator: str = ""
    case_sku: str = ""
    description: str = ""
    psu_wattage: str = ""
    psu_rating: str = ""
    power_limit_data: str = ""
    cpu_cooler: str = ""
    fan_type: str = ""
    fan_details: str = ""
    advanced_debug_logging: bool = False
