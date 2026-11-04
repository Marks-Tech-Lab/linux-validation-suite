# POSIX prerequisite discovery/guidance only. Never installs or creates a venv.

lvs_try_python() {
    _lvs_probe_path=$(command -v "$1" 2>/dev/null) || return 1
    [ -x "$_lvs_probe_path" ] || return 1
    _lvs_probe_version=$("$_lvs_probe_path" -B -I -c "import sys; print('.'.join(str(v) for v in sys.version_info[:3])); sys.exit(0 if sys.version_info >= ($MINIMUM_MAJOR, $MINIMUM_MINOR) else 1)" 2>/dev/null) || {
        printf 'Rejected Python %s (%s): unavailable or below %s.%s.\n' "$1" "${_lvs_probe_version:-unknown}" "$MINIMUM_MAJOR" "$MINIMUM_MINOR" >&2
        return 1
    }
    # An activated venv is not the base interpreter for a replacement venv.
    _lvs_base=$("$_lvs_probe_path" -B -I -c 'import sys; print(getattr(sys,"_base_executable",sys.executable))' 2>/dev/null) || return 1
    [ -x "$_lvs_base" ] || return 1
    _lvs_base_version=$("$_lvs_base" -B -I -c "import sys; print('.'.join(str(v) for v in sys.version_info[:3])); sys.exit(0 if sys.version_info >= ($MINIMUM_MAJOR, $MINIMUM_MINOR) and sys.prefix == getattr(sys,'base_prefix',sys.prefix) else 1)" 2>/dev/null) || return 1
    LVS_BOOTSTRAP_PYTHON=$_lvs_base
    LVS_BOOTSTRAP_VERSION=$_lvs_base_version
    return 0
}

lvs_find_python() {
    . "$1/scripts/lvs_python_policy.sh" || return 1
    LVS_BOOTSTRAP_PYTHON=
    LVS_BOOTSTRAP_VERSION=
    if [ -n "$2" ]; then
        if ! lvs_try_python "$2"; then
            printf 'Explicit Python override is unusable: %s\n' "$2" >&2
            return 1
        fi
    elif lvs_try_python "python$TESTED_MAJOR.$TESTED_MINOR" || lvs_try_python python3; then
        :
    else
        # Search versioned Python executables on PATH, bounded and never ranked
        # newest-first. The manager owns detailed discovery/manual selection.
        _lvs_remaining=${PATH-}:
        _lvs_count=0
        while [ -n "$_lvs_remaining" ]; do
            _lvs_directory=${_lvs_remaining%%:*}
            _lvs_remaining=${_lvs_remaining#*:}
            [ -n "$_lvs_directory" ] || _lvs_directory=.
            for _lvs_path_candidate in "$_lvs_directory"/python3.*; do
                _lvs_suffix=${_lvs_path_candidate##*/python3.}
                case $_lvs_suffix in ''|*[!0-9]*) continue ;; esac
                [ -x "$_lvs_path_candidate" ] || continue
                _lvs_count=$((_lvs_count + 1))
                [ "$_lvs_count" -le 32 ] || break 2
                if lvs_try_python "$_lvs_path_candidate"; then break 2; fi
            done
        done
        if [ -z "$LVS_BOOTSTRAP_PYTHON" ]; then
            printf 'No usable Python found. LVS requires Python %s.%s or newer; tested %s.%s.\n' "$MINIMUM_MAJOR" "$MINIMUM_MINOR" "$TESTED_MAJOR" "$TESTED_MINOR" >&2
            return 1
        fi
    fi
    printf 'Selected Python: %s (Python %s; LVS tested %s.%s).\n' "$LVS_BOOTSTRAP_PYTHON" "$LVS_BOOTSTRAP_VERSION" "$TESTED_MAJOR" "$TESTED_MINOR" >&2
}

lvs_python_prerequisites() {
    # Discovery/version only; never run system ensurepip bootstrap or require pip.
    "$1" -B -I -c 'import sys
try:
 import venv, ensurepip
 ensurepip.version()
except Exception as error:
 print("Python venv/ensurepip support is unavailable: " + str(error), file=sys.stderr)
 sys.exit(1)'
}

lvs_python_guidance() {
    # Optional file arguments permit isolated tests; production uses host files.
    _lvs_release=${1:-/etc/os-release}
    _lvs_ostree=${2:-/run/ostree-booted}
    _lvs_id=unknown
    _lvs_like=
    _lvs_variant=
    _lvs_image=
    if [ -r "$_lvs_release" ]; then
        while IFS='=' read -r _lvs_key _lvs_value; do
            case $_lvs_value in \"*\") _lvs_value=${_lvs_value#\"}; _lvs_value=${_lvs_value%\"} ;; esac
            case $_lvs_key in
                ID) _lvs_id=$_lvs_value ;;
                ID_LIKE) _lvs_like=$_lvs_value ;;
                VARIANT_ID) _lvs_variant=$_lvs_value ;;
                OSTREE_VERSION) _lvs_image=$_lvs_value ;;
            esac
        done < "$_lvs_release"
    fi
    printf 'Prerequisite guidance (%s). No package commands will be run; sudo is not assumed.\n' "$_lvs_id" >&2
    case "$_lvs_id $_lvs_variant $_lvs_image" in
        *bazzite*|*silverblue*|*kinoite*|*coreos*) _lvs_image=yes ;;
    esac
    if [ -e "$_lvs_ostree" ] || [ -n "$_lvs_image" ]; then
        printf '%s\n' 'Image-based system: consult the image documentation for host Python/venv support; do not apply mutable-host dnf/apt instructions blindly.' \
            'Bazzite guidance: https://docs.bazzite.gg/Installing_and_Managing_Software/rpm-ostree/' \
            'A container can provide Python tooling, but does not establish host hardware/device readiness.' >&2
    else
        case "$_lvs_id $_lvs_like" in
            *debian*|*ubuntu*)
                printf '%s\n' 'For the Debian/Ubuntu default Python, ask an administrator or use a root shell:' \
                    '  apt-get update' '  apt-get install python3 python3-venv' \
                    'python3-venv supplies the distro default Python; for another Python X.Y, check the matching provider (apt-cache policy pythonX.Y-venv) before installing.' \
                    'If the distro Python is below the LVS minimum, use a supported OS/Python provider; installing its default package alone may not upgrade it enough.' \
                    'Debian reference: https://packages.debian.org/stable/python3-venv' >&2 ;;
            *fedora*)
                printf '%s\n' 'On mutable Fedora, an administrator can install a supported Python (dnf install python3).' \
                    "For missing venv/ensurepip files, inspect the matching provider: dnf provides '*/ensurepip/__init__.py' '*/venv/__init__.py'" \
                    'Fedora reference: https://developer.fedoraproject.org/tech/languages/python/multiple-pythons.html' >&2 ;;
            *) printf '%s\n' 'Ask the distro/image administrator for a minimum-compatible Python with its matching venv and ensurepip support. Do not install packages meant for another distro or interpreter.' >&2 ;;
        esac
    fi
    printf '%s\n' 'No globally installed pip is required. After resolving prerequisites, rerun ./setup.sh (or set PYTHON=/path/to/a/compatible/base/python).' >&2
}
