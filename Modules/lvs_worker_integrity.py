from __future__ import annotations

from typing import Any, Dict, List


def worker_integrity_error_count(worker_results: List[Dict[str, Any]]) -> int:
    error_keys = (
        "error_count",
        "gl_error_count",
        "draw_mismatch_count",
        "vram_mismatch_count",
        "compute_mismatch_count",
        "transfer_mismatch_count",
        "child_failure_count",
    )
    total = 0
    for payload in worker_results:
        for key in error_keys:
            try:
                total += int(payload.get(key) or 0)
            except Exception:
                continue
        if str(payload.get("status") or "").lower() in {"error", "failed", "fail"}:
            total += 1
    return total
