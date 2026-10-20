# Source and manual-build provenance

LVS keeps the public runtime version (currently `0.5.1-alpha`) separate from
source identity. A version string or operator label does not identify the exact
development source. Git HEAD alone does not identify modified deployed files.

## Normal manual capture

There is no automatic hook for a manual filesystem copy. After the final source
edits and any intended commit, immediately before capturing the complete build,
run this from the current LVS project directory:

```bash
.venv/bin/python -B -m Modules.lvs_source_provenance stamp --label development-checkpoint
```

The label is optional. Use only a generic build label, never personal or secret
information. This atomically writes the **visible**, ignored root file
`lvs_source_build.json`. Include that file in the normal complete build copy.
Do not commit it, package physical evidence, or copy `.git` merely for provenance.
No new deployment system, release package, GitHub download, or target-side Git
installation is required. Normal native-helper compilation is unchanged.

This command is an explicit additional pre-copy action; LVS does **not** claim
that manual copies are stamped automatically. It also supports modified source:
the stamp retains the commit, marks its scoped source `modified`, and fingerprints
the actual content. Repeat stamping after subsequent source changes or commits.
To inspect the current deployment without writing anything:

```bash
python -B -m Modules.lvs_source_provenance show
```

Without a stamp, LVS still measures a deployed-source fingerprint. A no-Git,
unstamped copy has **unknown Git/capture provenance**, not an inferred release
commit. A stale stamp is retained as an explicitly unverified capture claim; its
claimed source/commit is never substituted for the observed source identity.

## Deterministic scope: `lvs_execution_source_v1`

The fingerprint covers bytes and relative POSIX paths of:

- Root `*.py`, `*.sh`, and `requirements*.txt` files.
- Recursive `Modules/**/*.py`.
- Recursive native `.py`, `.c`, `.h`, `.comp`, and `.glsl` source.
- Recursive `scripts/**/*.sh`.
- Active `profiles/*.json`, without traversing archived profiles.

Hidden paths and `__pycache__` are excluded. The collector never traverses
`results/`, archives, `build/`, supplied binaries, `.git/`, virtual environments,
vendor/reference assets, credentials, or runtime settings. Documentation and
smoke tests are outside execution-source scope. Effective profile, configuration,
and worker evidence remain governed by their existing result contracts; this
fingerprint is not a replacement for them or an identity of every copied file.

For each included file, compute SHA-256 of its exact bytes. Sort records
`[relative_path, file_sha256]` lexically by relative path, then SHA-256 the UTF-8
encoding of `[scope_name, records]` serialized with Python JSON
`sort_keys=True, separators=(",", ":"), ensure_ascii=True`. Timestamps,
permissions, machine architecture, usernames, and absolute paths are not inputs.
No text/newline normalization is performed. File hashes are streamed with a
64-KiB buffer; file contents/history are not retained in memory or exported.

Unreadable, changing, symlinked, or over-32-MiB source files produce incomplete
evidence, not silent exclusions from a purportedly complete identity. Four
minimum source anchors are required: the CLI entrypoint, `Modules/lvs_core.py`,
and the CPU and memory helper C sources. Full matching with a capture stamp also
detects lost/added included files. No completeness claim is made for an unknown
unstamped source-only subset beyond this declared scope and these anchors.

## Interpretation and trust boundaries

`source.status=complete` means the declared scope was read successfully;
`source.digest` identifies those bytes. It does **not** mean a release is approved,
hardware is validated, or an arbitrary deployment is a full distribution.

When the project itself contains Git metadata, LVS compares actual scoped file
bytes with HEAD's blob identifiers (including untracked/ignored relevant source),
not just index/mtime caches or optimistic `git status`. It records:

- `git.commit`: observed HEAD, never a surrogate for modified contents.
- `git.scoped_source_state`: `clean`, `modified`, or `unknown`.
- `git.scoped_commit_match`: whether the complete observed scope matches HEAD.
- `git.tracked_worktree_state`: broader tracked-tree state, including files
  outside the fingerprint scope. Untracked runtime lock files do not imply
  modified executable source.

No repository means `git.status=absent`; a missing/failing Git executable means
`unavailable`. Neither prevents content fingerprinting or workload execution.
An enclosing unrelated repository is not used as the project's identity.

`stamp_status` is `missing`, `invalid`, `stale`, or `content_match`. Only the last
means the complete deployed scope equals the captured fingerprint. Its Git
identity remains a **capture claim**, especially without independent Git history:
`capture.association=capture_claim_content_matches`, not verified historical
executable identity. A SHA-256 record checksum detects accidental stamp edits;
it is **not** a signature or protection against intentional restamping/tampering.
Paths, Git authors/remotes, command stderr, file contents, and user identities
are not embedded. Operator labels are optional, limited generic ASCII text.

Generated native executables, external drivers/libraries/interpreters, and
Python bytecode/resident process state are **not attested** by the source hash
(`native_binary_identity` and `external_dependencies` are `not_assessed`). A
prebuilt stale helper must not be called source-verified based on this record.
Existing helper build/probe and verification evidence remains authoritative;
exact instruction/binary association still requires its own matching binary
hash/provenance capture. Frozen/binary-only distributions without source anchors
report incomplete/unavailable source evidence rather than fabricate an identity.

Keep deployed source quiescent during execution. LVS snapshots at run start and
finalization and records `source_changed_during_run` (`null` if comparison is
unavailable). Equal endpoint digests cannot exclude transient edits that were
reverted or prove which already-imported machine instructions executed. An early
crash may retain only the initial snapshot; it does not imply an unchanged run.
Provenance never changes safety, performance thresholds, or workload verdicts.

## Persisted locations

- `run_manifest.json`: `source_provenance`, with final
  `source_provenance_end` and `source_changed_during_run` when available.
- `system_info.json`: additive `SourceProvenance` initial snapshot.
- Compatibility `parsed_results_custom.json`: the same initial evidence under
  `SystemInfo.SourceProvenance`, preserving established legacy fields.
- `parsed_results_extended.json`: initial/final evidence and change observation.
- Dry-run, CLI diagnostics, and blocked-preflight JSON: `source_provenance`.
- Report data: `run.source_provenance` and `run.source_changed_during_run`;
  normal standalone HTML exposes the recorded evidence in Run details.

Workers are associated with their run through the existing manifest lifecycle;
individual native worker JSON contracts are unchanged. Reports consume persisted
evidence only: rendering an old result never stamps it with the renderer's build.
Historical results without provenance remain readable as `not_recorded`.
