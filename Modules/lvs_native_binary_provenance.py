"""Automatic, bounded native executable observations, separate from source identity.

No executable paths, argv, binaries, environment, or raw exception text are exported.
Observations are evidence, not signatures, instruction inspection, or worker verdicts.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import time
from typing import Any

CONTRACT = "linux_validation_suite.native_executable_provenance"
MAX_BYTES = 32 * 1024 * 1024
MAX_HASH_SECONDS = 1.0
_UNSPECIFIED_PID = object()


def executable_snapshot(path: str | Path) -> dict[str, Any]:
    """Read an opened regular-file image once, not its subsequently replaced path."""
    started = time.monotonic()
    result: dict[str, Any] = {"status": "unavailable", "observed_at": datetime.now(timezone.utc).isoformat(),
                              "started_monotonic_seconds": started}
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            result["reason"] = "not_regular_file"
            return result
        if before.st_size > MAX_BYTES:
            result["reason"] = "size_budget_exceeded"
            return result
        digest, size, header = hashlib.sha256(), 0, b""
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BYTES or time.monotonic() - started > MAX_HASH_SECONDS:
                result["reason"] = "collection_budget_exceeded"
                return result
            if not header:
                header = chunk[:64]
            digest.update(chunk)
        after = os.fstat(descriptor)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if identity(before) != identity(after) or size != before.st_size:
            result.update(status="unstable", reason="file_changed_during_read")
            return result
        architecture = "unknown"
        elf_class = None
        if len(header) >= 20 and header[:4] == b"\x7fELF" and header[5] in (1, 2):
            machine = struct.unpack_from("<H" if header[5] == 1 else ">H", header, 18)[0]
            architecture = {62: "x86_64", 183: "aarch64", 3: "x86"}.get(machine, "unknown")
            elf_class = {1: 32, 2: 64}.get(header[4])
        result.update(status="observed", algorithm="sha256", sha256=digest.hexdigest(), size_bytes=size,
                      architecture=architecture, elf_class_bits=elf_class,
                      file_device=before.st_dev, file_inode=before.st_ino,
                      modified_time_ns=before.st_mtime_ns, changed_time_ns=before.st_ctime_ns)
    except OSError as error:
        result.update(reason="file_unavailable", errno=error.errno)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        result["elapsed_seconds"] = max(0.0, time.monotonic() - started)
    return result


def begin_native_executable(command: list[str], family: str, env: dict | None) -> tuple[str, dict]:
    requested = command[0] if command else ""
    # Keep the selected pathname internally (including symlinks) for end-state comparison.
    selected = (os.path.abspath(requested) if os.path.dirname(requested) else
                shutil.which(requested, path=env.get("PATH", os.defpath) if env is not None else None) or "")
    selected = os.path.abspath(selected) if selected else ""
    return selected, {"contract_id": CONTRACT, "contract_version": 1, "kind": "native_executable_provenance",
                      "helper_family": family, "prelaunch": executable_snapshot(selected),
                      "process_executable": {"status": "not_observed"},
                      "post_execution": {"status": "not_observed"}}


def observe_process_executable(evidence: dict, process: Any) -> None:
    # Bind the observation to the Popen child independently of procfs contents.
    pid = getattr(process, "pid", None)
    evidence["worker_pid"] = pid if type(pid) is int and pid > 0 else None
    try:
        _observe_process_executable(evidence, process)
    except Exception:
        # Optional evidence must not orphan an already-launched child or replace
        # existing lifecycle/error handling. Never export exception paths.
        evidence["process_executable"] = {"status": "unavailable", "reason": "process_observation_failed"}


def _observe_process_executable(evidence: dict, process: Any) -> None:
    pid = getattr(process, "pid", None)
    if type(pid) is not int or pid <= 0 or process.poll() is not None:
        evidence["process_executable"] = {"status": "unavailable", "reason": "process_not_running"}
        return
    path = f"/proc/{pid}/exe"
    observed = executable_snapshot(path)
    observed.update(pid=pid, source="linux_proc_pid_exe")
    # Never expose the link's potentially private target path.
    try:
        observed["path_deleted"] = os.readlink(path).endswith(" (deleted)")
    except OSError:
        observed["path_deleted"] = None
    observed["running_after_observation"] = process.poll() is None
    evidence["process_executable"] = observed


def _valid_snapshot(snapshot: Any) -> bool:
    return (isinstance(snapshot, dict) and snapshot.get("status") == "observed"
            and snapshot.get("algorithm") == "sha256"
            and isinstance(snapshot.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", snapshot["sha256"]) is not None
            and type(snapshot.get("size_bytes")) is int and 0 <= snapshot["size_bytes"] <= MAX_BYTES
            and all(type(snapshot.get(k)) is int and snapshot[k] >= 0 for k in ("file_device", "file_inode")))


def _validated_process_association(evidence: dict, expected_worker_pid: Any) -> tuple[dict | None, str]:
    """One trust decision for identity AND every comparison using process bytes."""
    proc = evidence.get("process_executable")
    if not isinstance(proc, dict) or proc.get("status") != "observed":
        return None, "process_evidence_unavailable"
    if not _valid_snapshot(proc):
        return None, "invalid_process_snapshot"
    if proc.get("source") != "linux_proc_pid_exe":
        return None, "unrecognized_process_provider"
    owner, pid = evidence.get("worker_pid"), proc.get("pid")
    if any(type(value) is not int or value <= 0 for value in (owner, pid)):
        return None, "invalid_process_pid"
    if pid != owner:
        return None, "worker_pid_mismatch"
    if expected_worker_pid is not _UNSPECIFIED_PID:
        if type(expected_worker_pid) is not int or expected_worker_pid <= 0:
            return None, "invalid_worker_context_pid"
        if pid != expected_worker_pid:
            return None, "worker_pid_mismatch"
    if (type(proc.get("running_after_observation")) is not bool or "path_deleted" not in proc
            or (proc["path_deleted"] is not None and type(proc["path_deleted"]) is not bool)):
        return None, "invalid_process_state"
    return proc, ""


def native_executable_identity(evidence: Any, *, expected_worker_pid: Any = _UNSPECIFIED_PID) -> dict:
    """Validate recorded observations without accessing the reviewing filesystem."""
    result: dict[str, Any] = {"status": "not_recorded", "sha256": "", "post_execution_state": "unknown"}
    if not evidence:
        return result
    if (not isinstance(evidence, dict) or evidence.get("contract_id") != CONTRACT
            or type(evidence.get("contract_version")) is not int or evidence["contract_version"] != 1
            or evidence.get("kind") != "native_executable_provenance"
            or evidence.get("helper_family") not in {"cpu", "memory"}):
        return dict(result, status="invalid_evidence")
    result["helper_family"] = evidence["helper_family"]
    pre, post = (evidence.get(k) for k in ("prelaunch", "post_execution"))
    proc, rejection = _validated_process_association(evidence, expected_worker_pid)
    result["process_association"] = ("accepted" if proc is not None else
                                     "unavailable" if rejection == "process_evidence_unavailable" else "rejected")
    if rejection:
        result["process_rejection_reason"] = rejection
    same = lambda a, b: (a["sha256"], a["size_bytes"]) == (b["sha256"], b["size_bytes"])
    if proc is not None:
        result.update(status="process_observed", sha256=proc["sha256"], architecture=proc.get("architecture", "unknown"))
        result["prelaunch_comparison"] = ("matching_bytes" if same(pre, proc) else "different_bytes") if _valid_snapshot(pre) else "unavailable"
        result["running_after_observation"] = proc.get("running_after_observation")
        # Equal bytes do not conceal replacement with an identical-content inode.
        if _valid_snapshot(pre):
            result["same_prelaunch_file_object"] = (pre.get("file_device"), pre.get("file_inode")) == (proc.get("file_device"), proc.get("file_inode"))
    elif _valid_snapshot(pre):
        result.update(status="prelaunch_only", sha256=pre["sha256"], architecture=pre.get("architecture", "unknown"))
    else:
        result["status"] = "unavailable"
    reference = proc if proc is not None else pre if _valid_snapshot(pre) else None
    result["post_execution_reference"] = "process_executable" if proc is not None else "prelaunch" if reference is not None else "unavailable"
    if _valid_snapshot(post) and reference is not None:
        result["post_execution_state"] = "matching_bytes" if same(reference, post) else "different_bytes"
        result["same_post_execution_file_object"] = (reference.get("file_device"), reference.get("file_inode")) == (post.get("file_device"), post.get("file_inode"))
    elif isinstance(post, dict) and post.get("status") != "not_observed":
        result["post_execution_state"] = "unavailable"
    return result


def native_binary_reviews(payload: Any) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    stages = payload.get("stage_windows") or payload.get("Segments") or []
    reviews = []
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        for worker in stage.get("worker_results") or stage.get("WorkerResults") or []:
            if isinstance(worker, dict) and "native_executable_provenance" in worker:
                evidence = worker["native_executable_provenance"]
                identity = native_executable_identity(evidence, expected_worker_pid=worker.get("process_pid"))
                reviews.append({"stage_id": str(stage.get("stage_id") or stage.get("StageId") or ""),
                                "worker_pid": worker.get("process_pid"),
                                **identity})
    return reviews


def native_binary_text(reviews: list[dict]) -> str:
    if not reviews:
        return "Native executable identity: not recorded (no historical hash inferred)"
    return "\n".join("Native " + str(item.get("helper_family", "helper")) + " executable: " + str(item.get("status")) + "; SHA-256 " +
                     str(item.get("sha256") or "unavailable") + "; prelaunch " +
                     str(item.get("prelaunch_comparison", "unknown")) + "; post-execution " +
                     str(item.get("post_execution_state", "unknown")) +
                     "; reference " + str(item.get("post_execution_reference", "unavailable")) +
                     ("; process association " + str(item.get("process_association", "unavailable")) + ": " +
                      str(item["process_rejection_reason"]) if item.get("process_rejection_reason") else "") +
                     ("; executable file object replaced" if item.get("same_post_execution_file_object") is False or item.get("same_prelaunch_file_object") is False else "") +
                     " (not instruction or source attestation)"
                     for item in reviews)


def load_native_binary_reviews(result_dir: Path, parsed: Any = None) -> list[dict]:
    from .lvs_core import JsonStore
    for name in ("run_manifest.json", "parsed_results_extended.json"):
        payload = JsonStore.read(Path(result_dir) / name, {})
        found = native_binary_reviews(payload)
        if found:
            return found
    return native_binary_reviews(parsed if parsed is not None else
                                 JsonStore.read(Path(result_dir) / "parsed_results_custom.json", {}))
