# Automatic source provenance

LVS keeps the public runtime version (currently `0.5.1-alpha`) separate from
source identity. A version string or operator label does not identify the exact
development source. Git HEAD alone does not identify modified deployed files.

## Ordinary copying and execution: no setup

Copy/transfer the complete LVS project and run it normally. **No manual command,
stamp, packaging, Git operation, metadata file, or special copying procedure is
needed.** Normal execution, dry-run diagnostics, and blocked-preflight collection
automatically record the deployed source fingerprint. Source files are never
rewritten or packaged in the background. Native-helper compilation is unchanged.

A copy without Git has a usable source-content identity and **unknown Git
association**, not an inferred release commit. Absence of a legacy stamp is
normal and does not reduce the confidence of a complete source collection.
The runtime version, observed fingerprint, source-collection status/confidence,
Git evidence, and source changes during execution remain separate observations.

## Ordinary review and comparison

Run summary text, Results Overview, CLI/TUI QA Review, QA JSON, and standalone
HTML expose source identity without inspecting raw JSON. Comparison reports show
`matching`, `different`, `insufficient_evidence`, or `unavailable` (including
unsupported/conflicting source evidence). Matching means the same initial
observed **scope and bytes**, not the same hardware, binaries, whole execution,
or unique Git commit. Source changes and conflicting endpoint evidence remain
visible independently. Missing legacy evidence is `not_recorded`.

Review never fingerprints the current checkout and substitutes it for an old
result. It can automatically correlate a complete recorded fingerprint with
**local HEAD and at most one recorded HEAD candidate**. This reads the identical
v1 source scope from committed Git objects, verifies object content, and computes
the same SHA-256 protocol. It does not use working-tree contents for correlation,
search history, fetch objects, contact GitHub, or infer a unique commit. Multiple
commits may legitimately match the same source scope.

Reads are offline (lazy fetching/transports and replacement objects disabled),
time-bounded, and limited to 16 MiB of scoped blob contents per candidate, with
an eight-entry successful-result cache. Missing Git/objects or a byte-budget
limit leaves correlation unavailable, not the observed fingerprint invalid.
A no-match result applies only to checked candidates, not all Git history.
An independently checked local commit match is distinct from runtime Git evidence
and never retroactively proves historical executable identity. Conflicting
recorded commit claims are explicitly reported rather than accepted.

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
and the CPU and memory helper C sources. Comparisons with other results or local
committed contents detect lost/added included files. No completeness claim is made for an unknown
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
An enclosing unrelated repository is not used as the project's identity. HEAD
is associated with the observed source only on a complete byte match; otherwise
it is only an observed, nonmatching HEAD and the exact Git association is unknown.

## Legacy stamps: optional advanced diagnostics only

The `stamp`/`show` module commands remain for advanced diagnostics and backward
compatibility, **not** as a deployment/validation procedure. Normal users never
need to invoke this module. No stamp is generated automatically. Existing valid,
stale, and malformed stamps remain readable; their absence is not a deficiency.

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
