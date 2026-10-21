"""Shared, read-only source identity review for results, reports and QA."""

from __future__ import annotations

from functools import lru_cache
import hashlib
from pathlib import Path
import re
import subprocess
from typing import Any

from .lvs_core import JsonStore
from .lvs_source_provenance import (
    CONTRACT_ID, REQUIRED, ROOT, SCOPE, MAX_SOURCE_BYTES, _in_scope,
    read_local_git, source_scope_digest,
)


_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
MAX_CORRELATION_BYTES = 16 * 1024 * 1024


def provenance_from_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    for key in ("source_provenance", "SourceProvenance"):
        if key in payload:
            value = payload[key]
            return value if isinstance(value, dict) else {"status": "invalid_evidence"}
    for key in ("SystemInfo", "system_info"):
        if isinstance(payload.get(key), dict):
            found = provenance_from_payload(payload[key])
            if found:
                return found
    return {}


def source_identity(record: Any, *, end: Any = None, changed: Any = None) -> dict[str, Any]:
    """Validate recorded observations, never substitute the reviewing checkout."""
    result: dict[str, Any] = {"status": "not_recorded", "fingerprint": "", "scope": "",
                             "git_association": "unknown", "change_status": "unknown"}
    if not record or record == {"status": "not_recorded"}:
        return result
    if not isinstance(record, dict) or record.get("contract_id") != CONTRACT_ID or type(record.get("contract_version")) is not int or record["contract_version"] != 1 or record.get("kind") != "source_provenance":
        result["status"] = "invalid_evidence"
        return result
    source = record.get("source")
    if not isinstance(source, dict):
        result["status"] = "invalid_evidence"
        return result
    result["runtime_version"] = str(record.get("runtime_version") or "unknown")
    result["scope"] = str(source.get("scope") or "")
    if source.get("status") in ("incomplete", "unavailable"):
        result["status"] = source["status"]
        return result
    if source.get("scope") != SCOPE:
        result["status"] = "unsupported_scope"
        return result
    if (source.get("status") != "complete" or source.get("algorithm") != "sha256"
            or record.get("collection_confidence", "observed_scoped_bytes") != "observed_scoped_bytes"
            or type(source.get("file_count")) is not int or source["file_count"] < len(REQUIRED)
            or type(source.get("error_count")) is not int or source["error_count"] != 0
            or not isinstance(source.get("digest"), str) or not _DIGEST.fullmatch(source["digest"])):
        result["status"] = "invalid_evidence"
        return result
    result.update(status="available", fingerprint=source["digest"], collection_confidence="observed_scoped_bytes")
    git = record.get("git") if isinstance(record.get("git"), dict) else {}
    commit = git.get("commit")
    if isinstance(commit, str) and _COMMIT.fullmatch(commit):
        result["recorded_head"] = commit
        if git.get("status") == "available" and git.get("scoped_commit_match") is True and git.get("scoped_source_state") == "clean" and git.get("association", "verified_scoped_content") == "verified_scoped_content":
            result["git_association"] = "recorded_content_match"
        elif git.get("scoped_commit_match") is False and git.get("scoped_source_state") == "modified" and git.get("association", "not_associated_modified_source") == "not_associated_modified_source":
            result["git_association"] = "working_source_differs_from_head"
    final = source_identity(end) if end else {}
    if final.get("status") == "available":
        differs = result["fingerprint"] != final["fingerprint"]
        result["change_status"] = "changed" if differs else "unchanged_endpoints"
        if type(changed) is bool and changed != differs:
            result["change_status"] = "conflicting_evidence"
        elif changed is not None and type(changed) is not bool:
            result["change_status"] = "conflicting_evidence"
    # Neither boolean alone establishes an endpoint comparison.
    return result


@lru_cache(maxsize=8)
def _commit_source(root_text: str, commit: str) -> str:
    """Fingerprint one local commit, with bounded source-only object reads."""
    root = Path(root_text)
    if read_local_git(root, "cat-file", "-t", commit).strip() != b"commit":
        raise ValueError("not a commit")
    entries: dict[str, tuple[str, int]] = {}
    for row in read_local_git(root, "ls-tree", "-rlz", commit).split(b"\0"):
        if not row:
            continue
        description, raw_name = row.split(b"\t", 1)
        mode, kind, oid, size = description.decode("ascii").split()
        name = raw_name.decode("utf-8")
        if not _in_scope(name):
            continue
        if name in entries or not _COMMIT.fullmatch(oid) or mode not in ("100644", "100755") or kind != "blob" or not size.isdecimal() or int(size) > MAX_SOURCE_BYTES:
            raise ValueError("unsupported source object")
        entries[name] = (oid, int(size))
    if not REQUIRED.issubset(entries):
        raise ValueError("incomplete committed source")
    sizes = {oid: size for oid, size in entries.values()}
    if sum(sizes.values()) > MAX_CORRELATION_BYTES:
        raise ValueError("local correlation byte budget exceeded")
    identifiers = sorted(sizes)
    data = read_local_git(root, "cat-file", "--batch", input_bytes=("\n".join(identifiers) + "\n").encode("ascii"))
    position, digests = 0, {}
    for identifier in identifiers:
        line_end = data.index(b"\n", position)
        actual_id, kind, size = data[position:line_end].decode("ascii").split()
        expected_size = sizes[identifier]
        if actual_id != identifier or kind != "blob" or size != str(expected_size):
            raise ValueError("inconsistent local object")
        position = line_end + 1
        raw = data[position:position + expected_size]
        position += expected_size
        if len(raw) != expected_size or data[position:position + 1] != b"\n":
            raise ValueError("truncated local object")
        position += 1
        header = b"blob " + size.encode("ascii") + b"\0"
        hasher = hashlib.sha1(header + raw, usedforsecurity=False) if len(identifier) == 40 else hashlib.sha256(header + raw)
        if hasher.hexdigest() != identifier:
            raise ValueError("corrupt local object")
        digests[identifier] = hashlib.sha256(raw).hexdigest()
    if position != len(data):
        raise ValueError("unexpected local object output")
    return source_scope_digest([[name, digests[oid]] for name, (oid, _) in entries.items()])


def correlate_local_source(identity: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    """Check HEAD and at most one recorded HEAD. Never search history or fetch."""
    result = dict(identity)
    result["local_git_correlation"] = {"status": "not_checked", "matching_commits": []}
    if (identity.get("status") != "available" or identity.get("scope") != SCOPE
            or not isinstance(identity.get("fingerprint"), str) or not _DIGEST.fullmatch(identity["fingerprint"])):
        return result
    root = Path(root) if root is not None else ROOT
    if not (root / ".git").exists():
        result["local_git_correlation"]["status"] = "unavailable"
        return result
    try:
        if Path(read_local_git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve() != root.resolve():
            raise ValueError("not the project repository")
        head = read_local_git(root, "rev-parse", "--verify", "HEAD").decode("ascii").strip()
        if not _COMMIT.fullmatch(head):
            raise ValueError("invalid HEAD")
        candidates = list(dict.fromkeys([head, identity.get("recorded_head")]))
        candidates = [value for value in candidates if isinstance(value, str) and _COMMIT.fullmatch(value)]
        matching, checked = [], []
        for commit in candidates:
            try:
                digest = _commit_source(str(root.resolve()), commit)
            except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
                continue
            checked.append(commit)
            if digest == identity["fingerprint"]:
                matching.append(commit)
        if identity.get("git_association") == "recorded_content_match" and identity.get("recorded_head") in checked and identity["recorded_head"] not in matching:
            result["git_association"] = "conflicting_recorded_git_evidence"
        result["local_git_correlation"] = {
            "status": "verified_match" if matching else "no_match_in_checked_candidates" if checked else "unavailable",
            "matching_commits": matching, "checked_commits": checked,
            "basis": "identical_v1_scoped_bytes", "unique_commit_identity": False,
        }
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        result["local_git_correlation"]["status"] = "unavailable"
    return result


def review_source_records(records: list[Any], *, end: Any = None, changed: Any = None, correlate: bool = True) -> dict[str, Any]:
    identities = [source_identity(record, end=end, changed=changed) for record in records if record]
    identity = identities[0] if identities else source_identity(None)
    # Do not hide a conflict by picking the most convenient artifact.
    if any((other["status"], other["scope"], other["fingerprint"]) !=
           (identity["status"], identity["scope"], identity["fingerprint"]) for other in identities):
        identity = dict(identity, status="conflicting_evidence", fingerprint="")
    return correlate_local_source(identity) if correlate else identity


def load_result_source_identity(result_dir: Path, *, parsed: Any = None, correlate: bool = True) -> dict[str, Any]:
    payloads = [JsonStore.read(Path(result_dir) / name, {}) for name in
                ("run_manifest.json", "system_info.json", "parsed_results_extended.json")]
    payloads.append(parsed if parsed is not None else JsonStore.read(Path(result_dir) / "parsed_results_custom.json", {}))
    return review_result_source_payloads(payloads, correlate=correlate)


def review_result_source_payloads(payloads: list[Any], *, correlate: bool = True) -> dict[str, Any]:
    records = [p for p in payloads if isinstance(p, dict)]
    ends = [p["source_provenance_end"] for p in records if p.get("source_provenance_end") is not None]
    flags = [p["source_changed_during_run"] for p in records if p.get("source_changed_during_run") is not None]
    result = review_source_records([provenance_from_payload(p) for p in records],
        end=ends[0] if ends else None, changed=flags[0] if flags else None, correlate=correlate)
    endpoint_ids = [source_identity(end) for end in ends]
    if (any(type(flag) is not bool for flag in flags) or any(flag != flags[0] for flag in flags)
            or any((other["status"], other["scope"], other["fingerprint"]) !=
                   (endpoint_ids[0]["status"], endpoint_ids[0]["scope"], endpoint_ids[0]["fingerprint"])
                   for other in endpoint_ids[1:])):
        result["change_status"] = "conflicting_evidence"
    return result


def compare_source_identities(baseline: dict[str, Any], comparison: dict[str, Any]) -> dict[str, Any]:
    valid = all(item.get("status") == "available" and item.get("scope") == SCOPE
                and isinstance(item.get("fingerprint"), str) and _DIGEST.fullmatch(item["fingerprint"])
                for item in (baseline, comparison))
    if valid:
        status = "matching" if baseline["fingerprint"] == comparison["fingerprint"] else "different"
    else:
        statuses = (baseline.get("status"), comparison.get("status"))
        status = "insufficient_evidence" if "incomplete" in statuses else "unavailable"
    return {"status": status, "basis": "initial_observed_scoped_source",
            "baseline_fingerprint": baseline.get("fingerprint", ""), "comparison_fingerprint": comparison.get("fingerprint", ""),
            "baseline_change_status": baseline.get("change_status", "unknown"),
            "comparison_change_status": comparison.get("change_status", "unknown")}


def source_identity_text(identity: dict[str, Any]) -> str:
    status = identity.get("status", "not_recorded")
    if status != "available":
        return f"Source fingerprint: {str(status).replace('_', ' ')} (no exact source comparison)\nRuntime version: {identity.get('runtime_version', 'unknown')}"
    lines = [f"Source fingerprint: SHA-256 {identity['fingerprint']}",
             f"Source scope: {identity['scope']} (observed scoped bytes)",
             f"Runtime version: {identity.get('runtime_version', 'unknown')}"]
    association = identity.get("git_association")
    if association == "recorded_content_match":
        lines.append(f"Git: recorded source/HEAD match {identity['recorded_head']} (not binary attestation)")
    elif association == "working_source_differs_from_head":
        lines.append(f"Git: working source differs from observed HEAD {identity['recorded_head']}; no exact commit association")
    elif association == "conflicting_recorded_git_evidence":
        lines.append("Git: recorded commit association conflicts with local committed source; do not treat it as verified")
    else:
        lines.append("Git: unknown association; source fingerprint remains usable")
    local = identity.get("local_git_correlation", {})
    if local.get("status") == "verified_match":
        lines.append("Local Git scope match: " + ", ".join(local["matching_commits"]) + " (not a unique historical build identity)")
    elif local.get("status") == "no_match_in_checked_candidates":
        lines.append("Local Git: no match among checked candidates (not a history search)")
    lines.append("Source changes during execution: " + str(identity.get("change_status", "unknown")).replace("_", " "))
    return "\n".join(lines)
