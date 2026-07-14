#!/usr/bin/env python3
"""Pure telemetry sample parsing helpers."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


def parse_optional_float(raw: Any, upper_bound: float) -> Optional[float]:
    text = str(raw or "").strip()
    if not text or text.lower() in {"n/a", "[not supported]", "[not available]"}:
        return None
    try:
        value = float(text)
    except Exception:
        return None
    if value < 0 or value > upper_bound:
        return None
    return round(value, 2)


def parse_temperature_text(raw: Any, *, upper_bound: float = 150.0) -> Optional[float]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        value = float(text)
    except Exception:
        return None
    if value > 1000:
        value /= 1000.0
    return round(value, 2) if 0 < value < upper_bound else None


def parse_power_text_w(raw: Any, *, max_watts: float) -> Optional[float]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        raw_value = float(text)
    except Exception:
        return None
    watts = raw_value / 1_000_000.0 if raw_value > 1000 else raw_value
    return round(watts, 2) if 0 < watts < max_watts else None


def parse_percent_text(raw: Any) -> Optional[float]:
    parsed = parse_optional_float(raw, upper_bound=100.0)
    return parsed if parsed is not None and 0 <= parsed <= 100 else None


def parse_vram_used_gb_from_bytes_text(raw: Any) -> Optional[float]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = int(text)
    except Exception:
        return None
    return round(parsed / (1024 ** 3), 2) if parsed >= 0 else None


def parse_mb_to_gb(raw: Any, *, upper_bound_mb: float = 10_000_000.0) -> Optional[float]:
    parsed = parse_optional_float(raw, upper_bound=upper_bound_mb)
    if parsed is None:
        return None
    return round(parsed / 1024.0, 2)


def parse_gpu_clock_text(raw: Any) -> Optional[float]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        value = float(text)
        if value > 10000:
            value /= 1000.0
        if 0 < value < 10000:
            return round(value, 2)
    except Exception:
        pass
    for line in text.splitlines():
        stripped = line.strip()
        if "*" not in stripped:
            continue
        token = stripped.split(":", 1)[1].replace("*", "").strip() if ":" in stripped else stripped.replace("*", "").strip()
        if token.lower().endswith("mhz"):
            token = token[:-3].strip()
        try:
            value = float(token)
        except Exception:
            continue
        if 0 < value < 10000:
            return round(value, 2)
    return None


def json_objects_from_text(text: str) -> List[Any]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
        return [parsed]
    except Exception:
        pass

    decoder = json.JSONDecoder()
    objects: List[Any] = []
    index = 0
    while index < len(cleaned):
        if cleaned[index] not in "[{":
            index += 1
            continue
        try:
            parsed, end_index = decoder.raw_decode(cleaned[index:])
        except Exception:
            index += 1
            continue
        if isinstance(parsed, list):
            objects.extend(parsed)
        else:
            objects.append(parsed)
        index += max(1, end_index)
    return objects


def metric_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("value", "busy", "current", "actual"):
            parsed = metric_number(value.get(key))
            if parsed is not None:
                return parsed
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if match:
            try:
                return float(match.group(0))
            except Exception:
                return None
    return None


def walk_json_numbers(value: Any, prefix: str = "") -> List[tuple[str, float]]:
    found: List[tuple[str, float]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            found.extend(walk_json_numbers(child, child_prefix))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(walk_json_numbers(child, f"{prefix}[{index}]"))
    elif isinstance(value, (int, float)):
        found.append((prefix, float(value)))
    return found


def parse_intel_gpu_top_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Optional[float]]:
    engines = snapshot.get("engines")
    busy_values: List[float] = []
    if isinstance(engines, dict):
        for engine_data in engines.values():
            if not isinstance(engine_data, dict):
                continue
            value = metric_number(engine_data.get("busy"))
            if value is not None and 0 <= value <= 100:
                busy_values.append(value)

    if not busy_values:
        for key, value in walk_json_numbers(snapshot):
            key_text = key.lower()
            if "busy" in key_text and "client" not in key_text and 0 <= value <= 100:
                busy_values.append(value)

    if not busy_values:
        return {}

    # Intel reports per-engine busy counters. The suite keeps the public metric
    # on the same 0-100 percent scale by summing active engines and capping.
    return {"busy_percent": round(min(100.0, sum(busy_values)), 2)}
