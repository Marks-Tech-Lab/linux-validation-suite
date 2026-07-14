from __future__ import annotations

import os
import subprocess
from pathlib import Path
from shutil import which
from typing import Any, Callable, Dict, Optional

from .lvs_cpu_execution import (
    build_cpu_default_kernel_probe_command,
    build_cpu_kernel_support_probe_command,
    build_cpu_resolved_mode_probe_command,
    cpu_kernel_support_probe_matches,
    normalize_cpu_probe_mode,
    parse_cpu_default_kernel_probe,
    parse_cpu_resolved_mode_probe,
)


def find_c_compiler(which_func: Callable[[str], Optional[str]] = which) -> Optional[str]:
    for name in ("gcc", "cc"):
        path = which_func(name)
        if path:
            return path
    return None


def native_helper_status_base(source: Path, binary: Path, compiler: Optional[str]) -> Dict[str, Any]:
    return {
        "available": False,
        "built": False,
        "path": str(binary),
        "source": str(source),
        "compiler": compiler or "",
        "reason": "",
    }


def native_helper_build_command(compiler: str, source: Path, binary: Path) -> list[str]:
    return [compiler, "-O3", "-std=c11", "-pthread", str(source), "-o", str(binary)]


def native_helper_binary_ready(source: Path, binary: Path) -> bool:
    return binary.exists() and binary.stat().st_mtime >= source.stat().st_mtime and os.access(binary, os.X_OK)


def resolve_native_helper_status(
    *,
    source: Path,
    binary: Path,
    compiler: Optional[str],
    reason_label: str,
    build_runner: Callable[[list[str]], Any],
) -> Dict[str, Any]:
    status = native_helper_status_base(source, binary, compiler)

    if not source.exists():
        status["reason"] = f"native {reason_label} helper source missing"
        return status

    if native_helper_binary_ready(source, binary):
        status["available"] = True
        status["reason"] = ""
        return status

    if not compiler:
        status["reason"] = "no C compiler found; install gcc or build-essential"
        return status

    binary.parent.mkdir(parents=True, exist_ok=True)
    cmd = native_helper_build_command(compiler, source, binary)
    try:
        completed = build_runner(cmd)
    except Exception as exc:
        status["reason"] = f"native {reason_label} helper build failed: {exc}"
        return status

    if completed.returncode == 0 and binary.exists() and os.access(binary, os.X_OK):
        status["available"] = True
        status["built"] = True
        return status

    stderr = (completed.stderr or "").strip()
    stdout = (completed.stdout or "").strip()
    status["reason"] = stderr or stdout or f"native {reason_label} helper build failed with exit code {completed.returncode}"
    return status


class NativeHelperRuntimeService:
    """Cached native-helper build status and CPU capability probes."""

    def __init__(
        self,
        *,
        command_env: Callable[[], Dict[str, str]],
        run_command: Callable[..., Any] = subprocess.run,
    ) -> None:
        self._command_env = command_env
        self._run_command = run_command
        self._status_cache: Dict[str, Dict[str, Any]] = {}
        self._resolved_mode_cache: Dict[str, str] = {}
        self._kernel_flavor_cache: Dict[str, str] = {}
        self._supported_kernel_cache: Dict[str, bool] = {}

    def helper_status(
        self,
        *,
        cache_key: str,
        source: Path,
        binary: Path,
        compiler_path: Callable[[], Optional[str]],
        reason_label: str,
    ) -> Dict[str, Any]:
        cached = self._status_cache.get(cache_key)
        if cached is not None:
            return cached

        def run_build(command: list[str]) -> Any:
            return self._run_command(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
                env=self._command_env(),
            )

        status = resolve_native_helper_status(
            source=source,
            binary=binary,
            compiler=compiler_path(),
            reason_label=reason_label,
            build_runner=run_build,
        )
        self._status_cache[cache_key] = status
        return status

    def cpu_resolved_mode(
        self,
        requested_mode: str,
        *,
        helper_status: Callable[[], Dict[str, Any]],
    ) -> str:
        normalized = normalize_cpu_probe_mode(requested_mode)
        cached = self._resolved_mode_cache.get(normalized)
        if cached:
            return cached
        helper = helper_status()
        if not helper.get("available"):
            return ""
        command = build_cpu_resolved_mode_probe_command(str(helper.get("path") or ""), normalized)
        try:
            completed = self._run_command(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                env=self._command_env(),
            )
        except Exception:
            return ""
        resolved = parse_cpu_resolved_mode_probe(completed.returncode, completed.stdout or "")
        if resolved:
            self._resolved_mode_cache[normalized] = resolved
        return resolved

    def cpu_default_kernel_flavor(
        self,
        requested_mode: str,
        *,
        helper_status: Callable[[], Dict[str, Any]],
    ) -> str:
        normalized = normalize_cpu_probe_mode(requested_mode)
        cached = self._kernel_flavor_cache.get(normalized)
        if cached:
            return cached
        helper = helper_status()
        if not helper.get("available"):
            return ""
        command = build_cpu_default_kernel_probe_command(str(helper.get("path") or ""), normalized)
        try:
            completed = self._run_command(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                env=self._command_env(),
            )
        except Exception:
            return ""
        flavor = parse_cpu_default_kernel_probe(completed.returncode, completed.stdout or "")
        if flavor:
            self._kernel_flavor_cache[normalized] = flavor
        return flavor

    def cpu_supports_kernel_flavor(
        self,
        flavor: str,
        *,
        helper_status: Callable[[], Dict[str, Any]],
    ) -> bool:
        normalized = str(flavor or "").strip().lower()
        if not normalized:
            return False
        cached = self._supported_kernel_cache.get(normalized)
        if cached is not None:
            return cached
        helper = helper_status()
        if not helper.get("available"):
            self._supported_kernel_cache[normalized] = False
            return False
        command = build_cpu_kernel_support_probe_command(str(helper.get("path") or ""), normalized)
        try:
            completed = self._run_command(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                env=self._command_env(),
            )
        except Exception:
            self._supported_kernel_cache[normalized] = False
            return False
        supported = cpu_kernel_support_probe_matches(completed.returncode, completed.stdout or "", normalized)
        self._supported_kernel_cache[normalized] = supported
        return supported
