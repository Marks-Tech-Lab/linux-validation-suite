#!/usr/bin/env python3
"""Shared stage event-to-verdict state helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List

from Modules.lvs_stability_events import new_unique_events


@dataclass(frozen=True)
class StageEventState:
    verdict: str
    aborted: bool
    abort_reason: str
    new_events: List[Dict[str, Any]]


def first_event_message(events: Iterable[Dict[str, Any]], severity: str = "error") -> str:
    target = str(severity or "").strip().lower()
    for event in events:
        if str(event.get("severity") or "").strip().lower() == target:
            return str(event.get("message") or "")
    return ""


def apply_stage_events(
    candidate_events: Iterable[Dict[str, Any]],
    existing_events: List[Dict[str, Any]],
    failure_reasons: List[str],
    verdict: str,
    *,
    aborted: bool = False,
    abort_reason: str = "",
    abort_on_error: bool = False,
    abort_only_from_pass: bool = False,
    abort_reason_from_first_event: bool = False,
    fail_only_from_pass: bool = False,
    failure_reasons_error_only: bool = True,
) -> StageEventState:
    new_events = new_unique_events(candidate_events, existing_events)
    if not new_events:
        return StageEventState(verdict, aborted, abort_reason, [])

    existing_events.extend(new_events)
    for event in new_events:
        severity = str(event.get("severity") or "").strip().lower()
        if failure_reasons_error_only and severity != "error":
            continue
        message = str(event.get("message") or "")
        if message:
            failure_reasons.append(message)

    has_error = any(str(event.get("severity") or "").strip().lower() == "error" for event in new_events)
    has_warning = any(str(event.get("severity") or "").strip().lower() == "warning" for event in new_events)

    if has_error:
        if abort_on_error and (not abort_only_from_pass or verdict == "pass"):
            verdict = "aborted"
            aborted = True
            if abort_reason_from_first_event:
                abort_reason = str(new_events[0].get("message") or "") or abort_reason
            else:
                abort_reason = first_event_message(new_events, "error") or abort_reason
        elif not fail_only_from_pass or verdict == "pass":
            verdict = "fail"
    elif has_warning and verdict == "pass":
        verdict = "warning"

    return StageEventState(verdict, aborted, abort_reason, new_events)
