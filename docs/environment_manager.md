# LVS Environment Manager — first milestone

Run from a normal user account:

```bash
./setup.sh
# Direct Python access remains available:
python3 lvs_environment_manager.py
python3 lvs_environment_manager.py --check
python3 lvs_environment_manager.py --python /usr/bin/python3.14
python3 lvs_environment_manager.py --wheelhouse /path/to/local/packages
```

## Two-stage bootstrap and missing prerequisites

Root `setup.sh` is a minimal POSIX `/bin/sh` entrypoint. It can display help and
missing-Python guidance without Bash, Python, pip, compilers or third-party tools.
It uses a shared shell prerequisite helper to find a minimum-compatible interpreter,
prefer the tested version, honor `PYTHON=/path/to/python` and `--python PATH`, and
then exec the Python manager. Versioned PATH discovery is bounded; an explicit
invalid override fails rather than silently choosing something else. An activated
venv is resolved to its base interpreter for bootstrap. Without an explicit
override, the shell does not force a different Python minor on the manager's
existing compatible `.venv` default.

The only Python policy declarations live in `scripts/lvs_python_policy.sh`, shared
by the POSIX entrypoint, legacy shell setup and Python metadata. The shell does
not implement menus, requirement resolution, installation or repair. Diagnostic
messages go to stderr so delegated `--check` JSON remains usable on stdout.

No compatible Python: the shell reports the minimum and exits without changing
anything. Missing `venv`/`ensurepip`: it checks module/bundled-pip availability
without running system ensurepip or requiring global pip, gives guidance, then
opens the manager for diagnostics; creation/rebuild waits for the prerequisite.
Resolve missing support using the distro's supported mechanism, then rerun
`./setup.sh`. The direct Python manager remains available for repair and inspection.

Fresh Debian/Ubuntu defaults can require `python3-venv` even though `python3`
already runs. The displayed commands are for an administrator/root shell, not
commands this tool executes:

```sh
apt-get update
apt-get install python3 python3-venv
```

That package follows the **distro default Python**, not arbitrary alternate
interpreters. Check the matching provider for another X.Y (for example,
`apt-cache policy pythonX.Y-venv`); do not assume that package exists. An old distro
whose default Python is below LVS's minimum needs an appropriate supported
OS/Python provider, not a claim that reinstalling its old default is sufficient.
See [Debian's venv package definition](https://packages.debian.org/stable/python3-venv)
and [Debian's Python environment guidance](https://sources.debian.org/src/python3.13/3.13.5-2%2Bdeb13u5/debian/README.venv).

Mutable Fedora guidance uses its supported Python packages and a read-only provider
query for missing venv/ensurepip files, not Debian package names; see
[Fedora's Python documentation](https://developer.fedoraproject.org/tech/languages/python/multiple-pythons.html).
Bazzite/Atomic/image signals select image-specific guidance, never automatic dnf
or apt instructions; see [Bazzite's host package guidance](https://docs.bazzite.gg/Installing_and_Managing_Software/rpm-ostree/).
No sudo assumption or automated system installation is introduced. Containers may
supply Python tooling but do not establish host hardware/device readiness.

## Python maintenance interface

The Python bootstrap process uses only Python's standard library and the lightweight
`Modules/lvs_python_environment.py` metadata module. Starting the menu needs no
Textual, Google libraries, pip, compiler, activation or existing `.venv`. Older
Python 3 interpreters can display diagnostics and select a newer installed base
Python; LVS itself still requires Python 3.10 or newer. The bootstrap syntax is
checked against Python 3.6 syntax; it is not a claim of LVS runtime support on 3.6.
There is no automatic Python download, system-package install, sudo or global pip.

`--check` emits `python_environment_inspection` JSON with bootstrap-only scope.
Exit zero means inspection completed, not that Python or hardware is ready:
inspect `python_baseline_ready`, environment issues and per-group import/pin results.
Missing policy/configuration or failed inspection is reported with exit one.
The full LVS checker remains authoritative for runtime/hardware readiness.

## Plan and implementation boundary

1. Keep bootstrap discovery independent of the LVS runtime.
2. Treat the shared shell policy's minimum/tested Python versions and the
   requirement files as authoritative, with shared lightweight group metadata.
3. Maintain only this project's final `.venv`, using its own Python and pip.
4. Make rebuilds recoverable, with creation at the final path and preserved backups.
5. Delegate optional runtime/hardware assessment to the existing LVS checker and
   native-helper machinery; environment installation is not hardware acceptance.

This is implemented development, pending operator use on target installations.
Software fixtures cover installation/repair failures and both x86-64/AArch64
identities; they do not demonstrate new hardware/backend capabilities. Native
workloads, CPU ISA eligibility, GPU targeting, allocation and safety policies are
unchanged. The published release/tag and historical acceptance evidence are unchanged.

## Numbered menu

| Choice | Operation |
|---|---|
| 1 | Inspect distro/kernel/architecture, installed interpreters, selected and active Python, venv/base paths, pip, direct pins, actual imports, consistency and free disk |
| 2 | Select base Python and online/local packages; create a fresh venv or repair pip and synchronize an existing compatible venv |
| 3 | Synchronize project pins, explicitly upgrade packaging tools, or select another Python |
| 4 | Install/synchronize Google dependencies or inspect Python/import/uploader readiness separately |
| 5 | Explicitly rebuild for this machine, retaining the previous environment |
| 6 | Explicitly compile/query native CPU/memory helpers through existing LVS machinery |
| 7 | Run the existing structured LVS dependency checker and save its normal report |
| 8 | Exit |

Actions repeat in one session. Significant changes require confirmation, default
No. EOF exits safely; Ctrl-C interrupts the current operation and returns to the
menu after rebuild recovery where applicable. Stop LVS and other installers before
maintenance; this milestone does not provide coordination between multiple manager
instances or concurrent pip operations and does not acquire LVS's runtime lock.

## Python selection and discovery

Python policy is read from `scripts/lvs_python_policy.sh`: currently minimum **3.10**,
tested **3.14**. Versions are not duplicated in the manager. Interpreter discovery
is bounded to 32 distinct executable paths, preferring the existing compatible
venv base when reusing an environment, otherwise the tested version and active
base/system Python. It never chooses the numerically newest interpreter merely
because it exists. Select a discovered number or enter another installed base
interpreter path. Other minimum-compatible versions remain untested until evaluated;
the manager reports the tested-version distinction. Installer resolution and actual
imports must succeed; a new Python version alone is not dependency compatibility.

Diagnostics inspect `pyvenv.cfg`, actual isolated interpreter prefixes/version,
base interpreter availability, creation path, pip shebangs and the manager marker.
Broken symlinks, stale base paths, relocated environments, minor-version changes,
system-site-package exposure and marker mismatches are reported. A healthy legacy
environment can be reused after explicit confirmation; unmarked historical
machine/OS origin remains unknown. A transfer at an identical path cannot always
be detected in an unmarked legacy venv: explicitly rebuild after transferring a
project. Copy source and requirements, not compiled environments between machines.

Successful synchronization writes `.venv/.lvs-environment.json` with project path,
architecture, OS-release identity, hashed machine identity, base/version and selected
optional groups. Root/architecture/OS/machine changes require rebuilding. Marker
data is local ignored state, not published provenance or physical acceptance.

## Pins, repair and offline packages

- Baseline packages come exclusively from `requirements.txt`.
- Google packages come exclusively from `requirements-google.txt`.
- `Modules/lvs_python_environment.py` shares requirement-file locations and import
  names with the uploader; it contains no pinned package versions.
- Missing pip is repaired using the selected venv's `python -m ensurepip --upgrade`.
  This uses Python's bundled bootstrap, not a global pip or an online get-pip script.
  Missing distro venv/ensurepip support is reported with system-provider guidance.
- Synchronization uses the venv's isolated Python, `pip --require-virtualenv`,
  `--no-user` and requirement files, followed by `pip check`, installed-version
  inspection and actual imports. pip/Python target-redirection environment variables
  are removed and pip configuration files are disabled for managed commands.
- Normal synchronization does not upgrade pip/setuptools/wheel or substitute
  newest versions for project pins. Packaging-tool upgrade is a separately
  confirmed online operation. No pruning/uninstallation is performed; unrelated
  installed packages are not removed automatically. Existing complete Google
  installations and manager-selected optional groups are retained during sync/rebuild.
- A local package directory selects `--no-index --find-links`; provide all pinned
  packages and transitive dependencies for the target Python/architecture/platform.
  A wheel built for x86-64 does not establish AArch64 compatibility. pip remains
  responsible for compatibility/resolution and may build an available source
  distribution; missing build tools/wheels are explicit failures, not readiness.

The current files use exact direct `name==version` pins. Independent version
inspection rejects unsupported requirement syntax rather than silently guessing;
future syntax needs a deliberate extension. Private-index/custom pip configuration
management is deferred; local packages are supported. Network/wheel availability
is established by the requested pip operation, not by a speculative DNS success.
No offline guarantee is made when required local dependencies are absent.

If pip is interrupted or a repository/wheel is unavailable, installation can be
partial. The operation reports failure; inspect/check and repeat synchronization
after resolving the cause. Normal in-place synchronization is not a package-level
transaction and does not claim rollback. It never reports success solely because
an interpreter exists or because unrelated hardware readiness is satisfied.

## Recoverable rebuild

Rebuild renames a recognized old `.venv` to `.venv.backup-<timestamp>`, then invokes
the selected base Python's `venv` module directly at the final `.venv` path.
Installed scripts consequently refer to that final path. A working environment is
never deleted automatically. Symlinked `.venv` roots, unrelated directories/files,
and unrecognized configuration paths are refused.

Managed subprocesses run in their own process group. Timeout/Ctrl-C terminates
the installer group before rebuild path recovery, so surviving build children do
not keep writing into a restored environment. If process termination cannot be
confirmed, automatic rollback is withheld: the replacement stays in place and
the old backup is retained for recovery after the processes are stopped. A hard
kill/power failure cannot execute recovery code; inspect the retained paths manually.

If creation, package installation or verification fails (including Ctrl-C), a
partial replacement is retained as `.venv.failed-<timestamp>` and the old backup
is restored to `.venv` when possible. Its actual validity is reported: restoring
a previously broken environment does not make it usable. Filesystem recovery
failure remains visible, with retained backup paths. On success the old backup
remains available; no backups are automatically deleted.

Backups/failed environments are ignored by Git and must not be executed as portable
venvs: their scripts may still refer to `.venv`. If manual rollback is necessary,
stop LVS/manager, move the current `.venv` aside without deleting it, then restore
the desired backup to the original `.venv` path. Check its current usability before
running LVS. Free disk is reported; no model-specific or arbitrary allocation
threshold is imposed on Python installation.

## Google Drive and the full checker

The optional-group check separately reports installed direct pins, actual imports,
credential-file presence, Shared Drive configuration, DNS and the existing uploader
readiness result. Installed Python packages do not imply credentials/network/upload
readiness. This invokes `GoogleDriveUploader.readiness()` unchanged; it does not
print credentials, authenticate or upload anything. DNS/readiness runs in a bounded
child process. Existing uploader readiness checks presence and DNS, not authenticated
API/TLS/permissions; those limitations remain visible.

Menu 7 invokes the existing `DependencyReportManager.run_dependency_check()` in the
validated venv and prints/saves its normal structured report. Settings are read
without constructing a writing SettingsManager, and privileged helpers/sudo are
disabled for this operation. The full checker can discover hardware, query/build
helpers and perform its ordinary DNS checks; it is explicitly separate from Python
installation. No backend policy is duplicated or weakened. Failure to import the
checker is reported while the bootstrap menu remains available.

## Native helpers

Menu 6 uses `NativeHelperRuntimeService`, existing architecture-specific filenames,
compiler discovery (`gcc`/`cc`), optional ISA compilation and scalar/help readiness
queries. It builds fresh candidates from current sources under `build/`, validates
ELF architecture and executable SHA-256 using the existing provenance machinery,
and verifies unchanged source identity before publication. Existing final binaries
are retained as backups. Stale/copied binaries are not used as proof of readiness;
non-ELF/unrelated final paths are refused. No stress workload is executed.

Missing compiler support is an optional native dependency failure, not a failed
Python installation. Native maintenance supports existing x86-64/AArch64 targets;
other architectures receive truthful unsupported guidance. Optional compilation
failure continues to use LVS's established salvage/fail-closed machinery. Successful
build/query evidence does not establish CPU ISA physical acceptance.

## System-package groundwork and existing shell setup

`/etc/os-release`, kernel architecture, installed package managers and image-based
signals are reported. Bazzite/rpm-ostree/bootc guidance explicitly refers to the
image's supported tooling; the manager does not blindly prescribe mutable-distro
installation commands or elevate privileges. Distro/provider mapping, package
installation, environment copying, credential management and cross-compilation
are deferred.

`scripts/setup_venv.sh` remains the existing noninteractive Bash setup path. It
now shares interpreter discovery/version policy and prerequisite guidance with
`setup.sh`, while preserving its existing venv reuse, pip upgrade and baseline
installation workflow. It accepts `PYTHON=/path/to/python`, installs
baseline requirements and performs its existing pip upgrade. The manager reuses
the shared version declarations and requirement files but adds interactive diagnostics,
explicit tool-upgrade control, optional groups and recoverable rebuilding. Do not
run both installers concurrently. No saved profiles or runtime settings are edited.

## Development validation and provenance

The pre-shell implementation passed **10/10 focused checks**, **368/368 smoke
checks**, **81/81 profiles** (25 active, 56 archived; five unchanged advisories),
**383 Python compilation checks** and **12 integration imports**. Markdown/local
links and `git diff --check` pass. Standard-library-only startup is checked with
isolated Python and site packages disabled. Installation/failure fixtures use
fake executables; real venv creation is confined to a temporary directory with
`--without-pip`, never the development environment. A real idle descendant-process
fixture verifies timeout cancellation before rollback. No online package install
or target-system deployment was performed during development validation.

The native bridge also compiled, queried, verified and backed up both helpers twice
in an isolated x86-64 project copy, without stress execution. ARM64 control paths
use architecture fixtures and unchanged existing AArch64 native compilation/
capability regressions; actual ARM64 manager deployment is not thereby established.
Environment results do not reopen or expand existing ISA/hardware acceptance.

The pre-shell development fingerprint was
`a5fcec9254c285cc53e4da68e21f71d815a995b26dacaac2366b0fb7e18eb81a`.
The POSIX entrypoint and shared policy/helper change the current source identity;
final combined validation and identity are recorded below. This development follows
commit `90b547d15e3bedc5087730c9959b6219a0d47c4d`. Markdown, tests and ignored
environment markers/backups are outside execution-source scope. Native arithmetic,
workload policies, profiles and runtime version remain unchanged. The new full
snapshot is not a previously physically executed source snapshot.

Final two-stage validation passed **14/14 focused checks**, **372/372 complete
smoke checks**, **81/81 profiles** (five unchanged advisories), **384 Python
compilation checks** and **13 integration imports**. POSIX shell/Bash syntax,
Markdown/local links and `git diff --check` passed. Fixtures cover no Python,
old Python, versioned discovery, interpreter overrides, missing venv/ensurepip,
Debian/Fedora/image guidance, diagnostic delegation and legacy noninteractive
setup. A fresh-Debian deployment and online package installation were not
performed; these bootstrap cases use isolated fixtures.

The final complete **375-file** `lvs_execution_source_v1` SHA-256 is
`a8b1a058a0824d3285898d572bec8536d4489fda6ef6e9562d1658f6656c4e52`.
Shared policy/helper shell files and `setup.sh` account for three additional
scoped files versus the pre-shell implementation. Documentation does not enter
this scope. Validation preserved the actual development `.venv`, settings,
profiles, runtime lock and historical results.

Commit-readiness review corrected a false relocation diagnosis: CPython can write
the absolute destination in `pyvenv.cfg` without shell quoting. Inspection now
recognizes the literal current destination before considering quoted records,
without executing the recorded command. Real temporary environments with spaces
and apostrophes, quoted records and stale destinations are covered by regression
checks. This correction changes the execution-source digest from the earlier
`0ea18e9ce51496430c6d6e06df96173b11a612c90efca5a96ba648b6bac85e89`;
the file count stays unchanged.

Dash 0.5.12 was built only in a temporary directory for compatibility review. All
four shell-bootstrap check groups passed under Dash (23 invocations), in addition
to the host `/bin/sh` and legacy Bash checks. No system package was installed.
