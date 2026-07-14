#!/usr/bin/env python3
"""Non-interactive QA JSON entrypoint for Linux Validation Suite."""

from __future__ import annotations

from Modules.lvs_qa_review_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
