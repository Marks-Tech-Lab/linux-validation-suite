#!/usr/bin/env python3
"""Manual standalone-report command for an existing LVS result directory."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Optional, Sequence, Tuple

from .lvs_chart_data import canonical_chart_json, compile_chart_data
from .lvs_report_data import compile_report_data
from .lvs_report_html import render_report_html


REPORT_DATA_NAME = "lvs_report_data.json"
CHART_DATA_NAME = "lvs_chart_data.json"
REPORT_HTML_NAME = "result_report.html"


def _atomic_write_text(path: Path, content: str) -> None:
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def generate_report(run_dir: Path | str, *, generated_at: Optional[str] = None) -> Tuple[Path, Path, Path]:
    """Compile and atomically replace only the three derived report artifacts."""
    root = Path(run_dir).expanduser().resolve()
    report = compile_report_data(root, generated_at=generated_at)
    chart_data = compile_chart_data(root, report)
    data_path = root / REPORT_DATA_NAME
    chart_path = root / CHART_DATA_NAME
    html_path = root / REPORT_HTML_NAME
    _atomic_write_text(data_path, json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    _atomic_write_text(chart_path, canonical_chart_json(chart_data) + "\n")
    _atomic_write_text(html_path, render_report_html(report, chart_data))
    return data_path, chart_path, html_path


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a standalone report for an existing LVS run directory.")
    parser.add_argument("run_directory", type=Path, help="completed LVS result directory")
    args = parser.parse_args(argv)
    try:
        data_path, chart_path, html_path = generate_report(args.run_directory)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(data_path)
    print(chart_path)
    print(html_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
