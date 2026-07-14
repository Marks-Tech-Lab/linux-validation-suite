#!/usr/bin/env python3
"""Shared run verdict helpers."""

from __future__ import annotations

from typing import Iterable


_VERDICT_RANK = {
    "pass": 0,
    "warning": 1,
    "fail": 2,
    "aborted": 3,
    "manually_aborted": 4,
}


def combine_run_verdict(
    stage_verdicts: Iterable[str],
    *,
    run_aborted: bool = False,
    manual_abort: bool = False,
) -> str:
    """Return the highest-severity run verdict from stage verdicts.

    This intentionally makes failure precedence order-independent. A later
    failing stage must override an earlier warning, and an abort must override
    both.
    """
    if manual_abort:
        return "manually_aborted"

    verdict = "aborted" if run_aborted else "pass"
    for raw in stage_verdicts:
        stage_verdict = str(raw or "").strip().lower()
        if stage_verdict not in _VERDICT_RANK:
            continue
        if _VERDICT_RANK[stage_verdict] > _VERDICT_RANK[verdict]:
            verdict = stage_verdict
    return verdict
