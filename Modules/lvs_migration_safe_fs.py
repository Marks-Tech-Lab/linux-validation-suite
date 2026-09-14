#!/usr/bin/env python3
"""Narrow Linux dir-fd filesystem operations for migration transactions."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
from typing import BinaryIO


def validate_relative_path(value: str | Path) -> tuple[str, ...]:
    text = str(value)
    if not text or "\x00" in text or "\\" in text:
        raise ValueError("migration path is invalid")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("migration path must be a normalized relative path")
    return tuple(path.parts)


def file_sha256(stream: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


@dataclass(frozen=True)
class FileIdentity:
    exists: bool
    device: int = 0
    inode: int = 0
    size: int = 0
    mtime_ns: int = 0
    sha256: str = ""

    def token(self) -> str:
        if not self.exists:
            return "missing"
        return f"{self.device}:{self.inode}:{self.size}:{self.mtime_ns}:{self.sha256}"


class PinnedRoot:
    """Pins one trusted root and never follows descendant symlinks."""

    def __init__(self, path: Path, *, create: bool = False) -> None:
        selected = path.absolute()
        self.path = selected
        if not selected.is_absolute():
            raise OSError("migration root must be absolute")
        current = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for part in selected.parts[1:]:
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=current)
                    except FileExistsError:
                        pass
                next_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                    dir_fd=current,
                )
                os.close(current)
                current = next_fd
            self.fd = current
        except BaseException:
            os.close(current)
            raise

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self) -> "PinnedRoot":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _parent_fd(self, relative: str | Path, *, create: bool = False) -> tuple[int, str]:
        parts = validate_relative_path(relative)
        current = os.dup(self.fd)
        try:
            for part in parts[:-1]:
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=current)
                    except FileExistsError:
                        pass
                next_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                    dir_fd=current,
                )
                os.close(current)
                current = next_fd
            return current, parts[-1]
        except BaseException:
            os.close(current)
            raise

    def ensure_private_dir(self, relative: str | Path) -> None:
        parts = validate_relative_path(relative)
        current = os.dup(self.fd)
        try:
            for part in parts:
                try:
                    os.mkdir(part, 0o700, dir_fd=current)
                except FileExistsError:
                    pass
                next_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                    dir_fd=current,
                )
                os.fchmod(next_fd, 0o700)
                os.close(current)
                current = next_fd
        finally:
            os.close(current)

    def open_read(self, relative: str | Path) -> int:
        parent, name = self._parent_fd(relative)
        try:
            return os.open(name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=parent)
        finally:
            os.close(parent)

    def open_exclusive(self, relative: str | Path, *, mode: int = 0o600) -> int:
        parent, name = self._parent_fd(relative, create=True)
        try:
            fd = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                mode,
                dir_fd=parent,
            )
            os.fchmod(fd, mode)
            return fd
        finally:
            os.close(parent)

    def open_lock(self, relative: str | Path) -> int:
        parent, name = self._parent_fd(relative, create=False)
        try:
            fd = os.open(
                name,
                os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            os.fchmod(fd, 0o600)
            return fd
        finally:
            os.close(parent)

    def identity(self, relative: str | Path, *, hash_content: bool = True) -> FileIdentity:
        parent, name = self._parent_fd(relative)
        try:
            try:
                fd = os.open(name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=parent)
            except FileNotFoundError:
                return FileIdentity(False)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode):
                    raise OSError("migration target is not a regular file")
                digest = ""
                if hash_content:
                    with os.fdopen(fd, "rb", closefd=False) as stream:
                        digest, _ = file_sha256(stream)
                after = os.fstat(fd)
                if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                ):
                    raise OSError("migration target changed during identity capture")
                return FileIdentity(True, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, digest)
            finally:
                os.close(fd)
        finally:
            os.close(parent)

    def link_exclusive(self, source_relative: str | Path, destination_relative: str | Path) -> None:
        source_parent, source_name = self._parent_fd(source_relative)
        destination_parent, destination_name = self._parent_fd(destination_relative)
        try:
            os.link(
                source_name,
                destination_name,
                src_dir_fd=source_parent,
                dst_dir_fd=destination_parent,
                follow_symlinks=False,
            )
        finally:
            os.close(source_parent)
            os.close(destination_parent)

    def rename(self, source_relative: str | Path, destination_relative: str | Path) -> None:
        source_parent, source_name = self._parent_fd(source_relative)
        destination_parent, destination_name = self._parent_fd(destination_relative)
        try:
            os.rename(source_name, destination_name, src_dir_fd=source_parent, dst_dir_fd=destination_parent)
        finally:
            os.close(source_parent)
            os.close(destination_parent)

    def remove_verified(self, relative: str | Path, expected: FileIdentity) -> None:
        current = self.identity(relative)
        if current.token() != expected.token():
            raise OSError("migration-owned destination changed before removal")
        parent, name = self._parent_fd(relative)
        try:
            os.unlink(name, dir_fd=parent)
        finally:
            os.close(parent)

    def remove_empty_dir(self, relative: str | Path) -> None:
        parent, name = self._parent_fd(relative)
        try:
            os.rmdir(name, dir_fd=parent)
        finally:
            os.close(parent)
