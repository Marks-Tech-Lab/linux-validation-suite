"""Automatic offline source identity; optional legacy stamps, not attestation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Any

from .lvs_core import APP_VERSION


STAMP_NAME = "lvs_source_build.json"
CONTRACT_ID = "linux_validation_suite.source_provenance"
SCOPE = "lvs_execution_source_v1"
ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {"linux_validation_suite.py", "Modules/lvs_core.py",
            "native/cpu_stress_helper.c", "native/memory_stress_helper.c"}
MAX_SOURCE_BYTES = 32 * 1024 * 1024


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def source_scope_digest(records: list[list[str]]) -> str:
    """The v1 byte/path protocol, shared by deployed and committed sources."""
    return hashlib.sha256(_canonical([SCOPE, sorted(records)])).hexdigest()


def read_local_git(root: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    """Read local Git only: no index refresh, object replacement or lazy fetch."""
    return subprocess.run(["git", "-C", str(root), "-c", "protocol.allow=never", *args],
                          input=input_bytes, check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=5,
                          env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1",
                               "GIT_NO_LAZY_FETCH": "1"}).stdout


def _in_scope(name: str) -> bool:
    path = Path(name)
    if any(part.startswith(".") or part == "__pycache__" for part in path.parts):
        return False
    if len(path.parts) == 1:
        return path.suffix in {".py", ".sh"} or (path.name.startswith("requirements") and path.suffix == ".txt")
    prefix = path.parts[0]
    return ((prefix == "Modules" and path.suffix == ".py")
            or (prefix == "native" and path.suffix in {".py", ".c", ".h", ".comp", ".glsl"})
            or (prefix == "scripts" and path.suffix == ".sh")
            or (prefix == "profiles" and len(path.parts) == 2 and path.suffix == ".json"))


def _source_snapshot(root: Path) -> tuple[dict[str, Any], dict[str, tuple[str, str, str]]]:
    """Hash only declared source paths. Never traverse result/build/archive trees."""
    candidates = list(root.iterdir())
    files: list[Path] = []
    errors = 0
    for directory in ("Modules", "native", "scripts"):
        start = root / directory
        if start.is_symlink():
            errors += 1
            continue
        if start.is_dir():
            def walk_error(_error):
                nonlocal errors
                errors += 1
            for current, dirs, names in os.walk(start, onerror=walk_error, followlinks=False):
                visible = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
                errors += sum((Path(current) / d).is_symlink() for d in visible)
                dirs[:] = [d for d in visible if not (Path(current) / d).is_symlink()]
                candidates.extend(Path(current) / name for name in names)
    profiles = root / "profiles"
    if profiles.is_symlink():
        errors += 1
    elif profiles.is_dir():
        candidates.extend(profiles.iterdir())
    for path in candidates:
        name = path.relative_to(root).as_posix()
        if _in_scope(name):
            if path.is_symlink():
                errors += 1
            elif path.is_file():
                files.append(path)
            else:
                errors += 1
    content: dict[str, tuple[str, str, str]] = {}
    for path in sorted(set(files)):
        try:
            before = path.stat()
            if before.st_size > MAX_SOURCE_BYTES:
                errors += 1
                continue
            header = b"blob " + str(before.st_size).encode("ascii") + b"\0"
            digest, sha1, sha256 = hashlib.sha256(), hashlib.sha1(header, usedforsecurity=False), hashlib.sha256(header)
            size = 0
            with path.open("rb") as handle:
                while chunk := handle.read(65536):
                    size += len(chunk)
                    if size > MAX_SOURCE_BYTES:
                        break
                    digest.update(chunk)
                    sha1.update(chunk)
                    sha256.update(chunk)
            after = path.stat()
            if size != before.st_size or (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                errors += 1
                continue
            content[path.relative_to(root).as_posix()] = (digest.hexdigest(), sha1.hexdigest(), sha256.hexdigest())
        except OSError:
            errors += 1
    errors += len(REQUIRED - content.keys())
    records = [[name, hashes[0]] for name, hashes in sorted(content.items())]
    return {"scope": SCOPE, "algorithm": "sha256", "file_count": len(records),
            "digest": source_scope_digest(records),
            "status": "complete" if not errors else "incomplete", "error_count": errors}, content


def _git_identity(root: Path, content: dict[str, tuple[str, str, str]]) -> dict[str, Any]:
    # Never accidentally attribute a copied subtree to an enclosing repository.
    if not (root / ".git").exists():
        return {"status": "absent", "commit": "", "scoped_source_state": "unknown"}
    def git(*args: str) -> bytes:
        return read_local_git(root, *args)
    try:
        if Path(os.fsdecode(git("rev-parse", "--show-toplevel")).strip()).resolve() != root.resolve():
            return {"status": "unavailable", "commit": "", "scoped_source_state": "unknown"}
        commit = git("rev-parse", "--verify", "HEAD").decode("ascii").strip()
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
            raise ValueError("invalid Git identity")
        tree = {}
        for entry in git("ls-tree", "-rz", commit).split(b"\0"):
            if not entry:
                continue
            description, raw_name = entry.split(b"\t", 1)
            mode, kind, oid = description.decode("ascii").split()
            name = raw_name.decode("utf-8")
            if _in_scope(name):
                tree[name] = (mode, kind, oid)
        # Compare actual bytes against HEAD blobs, not Git stat caches, index
        # state, timestamps, model labels, or an optimistic 'git status' alone.
        matches = tree.keys() == content.keys()
        for name, hashes in content.items():
            oid = hashes[1] if len(commit) == 40 else hashes[2]
            item = tree.get(name)
            matches = matches and bool(item and item[0] in {"100644", "100755"} and item[1:] == ("blob", oid))
        try:
            tracked_state = "modified" if git("status", "--porcelain=v1", "--untracked-files=no") else "clean"
        except (OSError, subprocess.SubprocessError):
            tracked_state = "unknown"
        return {"status": "available", "commit": commit,
                "tracked_worktree_state": tracked_state,
                "scoped_source_state": "clean" if matches else "modified",
                "scoped_commit_match": matches,
                "association": "verified_scoped_content" if matches else "not_associated_modified_source"}
    except (OSError, subprocess.SubprocessError, ValueError, UnicodeError):
        return {"status": "unavailable", "commit": "", "scoped_source_state": "unknown"}


def _valid_stamp(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    unsigned = {k: v for k, v in value.items() if k != "record_sha256"}
    source = value.get("source")
    git = value.get("git")
    if not isinstance(source, dict) or not isinstance(git, dict):
        return False
    try:
        captured = datetime.fromisoformat(value.get("captured_at", ""))
        if captured.tzinfo is None:
            return False
    except (TypeError, ValueError):
        return False
    if git.get("status") == "available":
        if (not isinstance(git.get("commit"), str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", git["commit"])
                or git.get("scoped_source_state") not in {"clean", "modified"}
                or type(git.get("scoped_commit_match")) is not bool
                or git["scoped_commit_match"] != (git["scoped_source_state"] == "clean")):
            return False
    elif git.get("status") not in {"absent", "unavailable"} or git.get("commit") != "" or git.get("scoped_source_state") != "unknown":
        return False
    return (value.get("contract_id") == CONTRACT_ID and type(value.get("contract_version")) is int and value["contract_version"] == 1
            and value.get("kind") == "source_build_stamp"
            and isinstance(value.get("runtime_version"), str) and bool(value["runtime_version"])
            and value.get("record_sha256") == hashlib.sha256(_canonical(unsigned)).hexdigest()
            and source.get("status") == "complete" and source.get("scope") == SCOPE
            and source.get("algorithm") == "sha256"
            and type(source.get("file_count")) is int and source["file_count"] >= len(REQUIRED)
            and type(source.get("error_count")) is int and source["error_count"] == 0
            and isinstance(source.get("digest"), str) and bool(re.fullmatch(r"[0-9a-f]{64}", source["digest"]))
            and isinstance(value.get("operator_label"), str))


def collect_source_provenance(root: Path | None = None) -> dict[str, Any]:
    root = Path(root) if root is not None else ROOT
    result: dict[str, Any] = {
        "contract_id": CONTRACT_ID, "contract_version": 1, "kind": "source_provenance",
        "runtime_version": APP_VERSION, "observed_at": datetime.now(timezone.utc).isoformat(),
        "identity_scope": "scoped_source_only", "native_binary_identity": "not_assessed",
        "external_dependencies": "not_assessed",
        "collection_mode": "automatic",
    }
    try:
        source, content = _source_snapshot(root)
    except OSError:
        source, content = {"scope": SCOPE, "status": "unavailable", "digest": ""}, {}
    result["source"] = source
    result["collection_confidence"] = "observed_scoped_bytes" if source.get("status") == "complete" else "insufficient"
    result["git"] = _git_identity(root, content)
    if source.get("status") != "complete" and result["git"]["status"] == "available":
        result["git"].update(scoped_source_state="unknown", scoped_commit_match=False, association="unknown")
    result["stamp_status"] = "missing"
    path = root / STAMP_NAME
    if path.exists() or path.is_symlink():
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
                raise ValueError("invalid stamp")
            with path.open("rb") as handle:
                raw_stamp = handle.read(65537)
            if len(raw_stamp) > 65536:
                raise ValueError("oversized stamp")
            stamp = json.loads(raw_stamp.decode("utf-8"))
            if not _valid_stamp(stamp):
                raise ValueError("invalid stamp")
            matches = source.get("status") == "complete" and stamp["source"] == source
            if matches and stamp["runtime_version"] != APP_VERSION:
                raise ValueError("stamp version contradicts current runtime version")
            result["stamp_status"] = "content_match" if matches else "stale"
            # Whitelist fields; never re-export arbitrary stamp contents/paths.
            result["capture"] = {
                "captured_at": datetime.fromisoformat(stamp["captured_at"]).astimezone(timezone.utc).isoformat(),
                "commit": str(stamp["git"].get("commit") or "") if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", str(stamp["git"].get("commit") or "")) else "",
                "scoped_source_state": stamp["git"].get("scoped_source_state") if stamp["git"].get("scoped_source_state") in {"clean", "modified"} else "unknown",
                "operator_label": stamp["operator_label"] if re.fullmatch(r"[A-Za-z0-9 ._-]{0,80}", stamp["operator_label"]) else "",
                "association": "capture_claim_content_matches" if matches else "unverified_stale_capture_claim",
            }
        except (OSError, ValueError, TypeError, AttributeError, RecursionError):
            result["stamp_status"] = "invalid"
    return result


def write_build_stamp(root: Path | None = None, operator_label: str = "") -> dict[str, Any]:
    root = Path(root) if root is not None else ROOT
    if not re.fullmatch(r"[A-Za-z0-9 ._-]{0,80}", operator_label):
        raise ValueError("label must be at most 80 ASCII letters/digits, spaces, dots, underscores or hyphens")
    observed = collect_source_provenance(root)
    if observed["source"].get("status") != "complete":
        raise ValueError("cannot stamp an incomplete source snapshot")
    stamp = {k: observed[k] for k in ("contract_id", "contract_version", "runtime_version", "source", "git")}
    stamp.update(kind="source_build_stamp", captured_at=observed["observed_at"], operator_label=operator_label)
    stamp["record_sha256"] = hashlib.sha256(_canonical(stamp)).hexdigest()
    temporary = ""
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, prefix="." + STAMP_NAME + ".", delete=False) as handle:
            temporary = handle.name
            json.dump(stamp, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, root / STAMP_NAME)
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()
    return stamp


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("show", "stamp"))
    parser.add_argument("--label", default="", help="advanced legacy stamp label; never needed for ordinary provenance")
    args = parser.parse_args()
    try:
        result = write_build_stamp(operator_label=args.label) if args.action == "stamp" else collect_source_provenance()
    except (OSError, ValueError):
        parser.exit(1, "Source stamp failed; check source completeness and label format.\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
