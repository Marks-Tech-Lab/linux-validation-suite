#!/bin/sh
# Stage 1: POSIX prerequisite discovery; all maintenance stays in Python.
set -u
for _lvs_arg do
    case $_lvs_arg in -h|--help)
        printf '%s\n' 'Usage: ./setup.sh [environment-manager options]' \
            'Requires only /bin/sh to start. Detects Python, then opens the LVS Environment Manager.' \
            'PYTHON=/path/to/python overrides discovery; --python PATH also selects it.' \
            'Options are forwarded, including --check and --wheelhouse PATH. No OS packages are installed.'
        exit 0 ;;
    esac
done
case $0 in */*) _lvs_here=${0%/*} ;; *) _lvs_here=. ;; esac
LVS_ROOT=$(CDPATH= cd -P "$_lvs_here" && pwd -P) || exit 1
. "$LVS_ROOT/scripts/lvs_python_bootstrap.sh" || exit 1
_lvs_override=${PYTHON-}
_lvs_need_python=no
for _lvs_arg do
    if [ "$_lvs_need_python" = yes ]; then _lvs_override=$_lvs_arg; _lvs_need_python=no
    else case $_lvs_arg in --python) _lvs_need_python=yes ;; --python=*) _lvs_override=${_lvs_arg#--python=} ;; esac
    fi
done
if [ "$_lvs_need_python" = yes ]; then printf '%s\n' '--python requires an interpreter path.' >&2; exit 2; fi
if ! lvs_find_python "$LVS_ROOT" "$_lvs_override"; then lvs_python_guidance; exit 1; fi
if ! lvs_python_prerequisites "$LVS_BOOTSTRAP_PYTHON"; then
    lvs_python_guidance
    printf '%s\n' 'Opening the manager for diagnostics; creation/rebuild requires the missing support to be resolved.' >&2
fi
if [ -n "$_lvs_override" ]; then
    exec "$LVS_BOOTSTRAP_PYTHON" -B "$LVS_ROOT/lvs_environment_manager.py" --python "$LVS_BOOTSTRAP_PYTHON" "$@"
fi
# Bootstrap interpreter selection must not override the manager's safe default
# reuse of an existing compatible environment with a different Python minor.
exec "$LVS_BOOTSTRAP_PYTHON" -B "$LVS_ROOT/lvs_environment_manager.py" "$@"
