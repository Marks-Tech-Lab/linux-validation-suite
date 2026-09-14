#!/usr/bin/env python3
"""Small advisory lock used by validation and migration state mutation."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
from typing import Iterator

from .lvs_migration_safe_fs import PinnedRoot


class MigrationLockUnavailable(RuntimeError):
    pass


@contextmanager
def state_lock(settings_root: Path, *, exclusive: bool) -> Iterator[None]:
    """Shared for validation, exclusive for migration apply; always nonblocking."""
    root = PinnedRoot(settings_root, create=True)
    fd = root.open_lock(".lvs_state.lock")
    try:
        mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(fd, mode | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MigrationLockUnavailable("LVS state is busy") from exc
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
            root.close()
