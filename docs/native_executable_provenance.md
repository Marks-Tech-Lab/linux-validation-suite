# Automatic native executable provenance

Native executable identity is separate from the unchanged
`lvs_execution_source_v1` source fingerprint. Normal LVS execution collects it
automatically for native CPU and RAM helpers on x86_64 and AArch64. There is no
stamp, configuration, capture command, Git/network dependency, external ELF
utility, or deployment change. Full executables are never attached automatically.

## Observation boundary

Each worker's `native_executable_provenance` uses
`linux_validation_suite.native_executable_provenance`, contract version 1,
kind `native_executable_provenance`. It contains three separate observations:

1. `prelaunch`: hash the actual selected command pathname after normal helper
   readiness/building and immediately before launching it. PATH resolution uses
   the launch environment; the helper need not have the default filename.
2. `process_executable`: after successful `Popen`, open Linux `/proc/<pid>/exe`
   and hash that opened file image, not the pathname's possibly replaced target.
   Record the child PID, whether the pathname was deleted, and whether the child
   remained running after observation. A short-lived process, permission failure,
   missing procfs, or other unavailable evidence is explicit, never a process match.
3. `post_execution`: after process completion/reaping, observe the selected
   pathname once more. Missing/unreadable/unstable files and changed bytes remain
   distinct. Equal bytes do not conceal replacement with a different file object.

Each successful observation records SHA-256, byte size, ELF-header architecture
and class where recognizable, file device/inode and modification/change times,
UTC correlation, monotonic start and elapsed seconds. Paths, argv, environment,
and raw exceptions are not included. Original process commands remain subject to
the existing private result/public-safe export boundaries.

Hashing uses an open regular-file descriptor, 64-KiB chunks, a 32-MiB size cap,
and a one-second elapsed budget checked between reads. Size/stat changes invalidate
an observation. This does not guarantee a deadline for an individual blocked OS
filesystem call. Ordinary helpers are small; collection occurs at process
boundaries, never in arithmetic loops, and retains three bounded records per
worker, not per thread or sample. Failures in optional process observation do not
orphan launched children, change verification, or excuse nonzero exits/SIGKILL.

Run finalization adds sanitized existing readiness evidence (available/built,
compiler basename, optional SVE build status). Those fields are not a claim that
the executable was built from a particular source, compiler version, or flags.
Readiness and native building are otherwise unchanged; launch hashing does not
reuse a fingerprint captured before rebuilding.

## Results and review

The orchestrator attaches evidence to worker records, including failed/incomplete
worker records, in the manifest/executed plan, extended results and compatibility
WorkerResults. It is not written retroactively into native-authored worker JSON.
The versioned record survives compatibility serialization intact. Standalone
reports and normal QA/CLI/TUI review show `native_executable_review` and human text.
Text summaries show available native identities. Historical absence is not
recorded; review never hashes the reviewing machine's helper to fill a gap.

`process_observed` identifies bytes obtained through the running child's procfs
executable. It separately reports matching/different/unavailable prelaunch and
post-execution comparisons. `prelaunch_only` is weaker evidence, not executed-byte
confirmation. Changed/deleted pathnames, mismatches, malformed metadata and PID
conflicts must remain visible. Binary provenance is supplementary evidence and
does not create or override arithmetic, lifecycle, safety or performance verdicts.

The launch collector records `worker_pid` from the actual Popen child independently
of the process observation. One shared association validator checks the provider,
snapshot, strictly typed positive PID, agreement with this owner and the worker
record's PID, and explicit process-state fields. The same validated result selects
the post-execution comparison reference. Rejected process observations stay in
raw artifacts but cannot establish identity or a match. Reviews expose
`process_association`, a safe `process_rejection_reason` when applicable, and
`post_execution_reference`. When process evidence is rejected, a valid prelaunch
observation is the reference; without either, comparison is unavailable. A match
against prelaunch is never presented as a process-executable match. A valid
process/prelaunch mismatch remains visible even if post-execution matches the
process. Explicit unknown deleted-link state is allowed because the opened proc
image still supplies bytes; missing or malformed required state is rejected.

## What it does not prove

This is not a signed attestation, instruction disassembly, source-to-binary
reproducibility proof, memory-image integrity guarantee, shared-library/kernel
attestation, or compiler/dependency audit. It cannot exclude changes and reversions
between observations. On systems restricting procfs, pathname observations alone
cannot close the launch race. A historical run without a launch hash cannot be
given cryptographically exact executable identity by hashing a later supplied file.

## Source-change summaries

New compatibility results retain the manifest's final source observation and
change flag. Summary rendering compares complete initial/final observations;
matching bytes yield unchanged endpoints, differing bytes yield changed, and
missing endpoints yield unknown. Flags contradicting endpoints or conflicting
artifact endpoints are reported as conflicting evidence, never unchanged.
Summary refresh/validation uses recorded manifest/extended context only, without
fingerprinting the current checkout or rewriting historical evidence implicitly.
