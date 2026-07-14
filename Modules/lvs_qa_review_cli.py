#!/usr/bin/env python3
"""Non-interactive QA review payload command helpers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, TextIO

from .linux_validation_suite_service import SuiteAppService


ServiceFactory = Callable[[Optional[Path]], Any]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linux_validation_suite_qa.py",
        description="Emit versioned Linux Validation Suite QA review JSON payloads.",
    )
    parser.add_argument(
        "--settings",
        type=Path,
        default=None,
        help="Optional settings JSON path for locating suite results/profiles.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    review = subparsers.add_parser("review", help="Emit one qa_result_review payload.")
    review.add_argument("result_dir", type=Path, help="Result folder to review.")
    review.add_argument(
        "--comparison",
        "--comparison-dir",
        dest="comparison_dir",
        type=Path,
        default=None,
        help="Optional baseline/comparison result folder.",
    )
    review.add_argument(
        "--refresh-summary",
        action="store_true",
        help="Refresh run_summary.txt while building import-readiness data.",
    )

    batch = subparsers.add_parser("batch", help="Emit one qa_result_review_batch payload.")
    batch.add_argument(
        "result_dirs",
        nargs="*",
        type=Path,
        help="Optional result folders. If omitted, completed results from configured results_dir are used.",
    )
    batch.add_argument(
        "--refresh-summary",
        action="store_true",
        help="Refresh run_summary.txt for each result while building import-readiness data.",
    )
    return parser


def _default_service_factory(settings_path: Optional[Path]) -> SuiteAppService:
    return SuiteAppService(settings_path=settings_path)


def build_payload(args: argparse.Namespace, service: Any) -> dict[str, Any]:
    if args.command == "review":
        return service.qa_result_review_payload(
            args.result_dir,
            comparison_dir=args.comparison_dir,
            refresh_summary=bool(args.refresh_summary),
        )
    if args.command == "batch":
        candidates = list(args.result_dirs) if args.result_dirs else None
        return service.qa_batch_review_payload(
            candidates,
            refresh_summary=bool(args.refresh_summary),
        )
    raise ValueError(f"unsupported QA command: {args.command}")


def main(
    argv: Optional[Iterable[str]] = None,
    *,
    service_factory: ServiceFactory = _default_service_factory,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
        service = service_factory(args.settings)
        payload = build_payload(args, service)
        json.dump(payload, output, indent=2, sort_keys=True)
        output.write("\n")
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        errors.write(f"QA payload command failed: {exc}\n")
        return 1
