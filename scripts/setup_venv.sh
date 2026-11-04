#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"

# Share prerequisite discovery/version policy with the POSIX entrypoint while
# retaining this script's existing noninteractive setup and PYTHON override.
. "${SCRIPT_DIR}/lvs_python_bootstrap.sh"
if ! lvs_find_python "${REPO_ROOT}" "${PYTHON:-}"; then
    lvs_python_guidance
    exit 1
fi
PYTHON_BIN="${LVS_BOOTSTRAP_PYTHON}"
PYTHON_VERSION="${LVS_BOOTSTRAP_VERSION}"
IFS=. read -r PYTHON_MAJOR PYTHON_MINOR PYTHON_MICRO <<<"${PYTHON_VERSION}"
if (( PYTHON_MAJOR != TESTED_MAJOR || PYTHON_MINOR != TESTED_MINOR )); then
    echo "Notice: Python ${TESTED_MAJOR}.${TESTED_MINOR} is the currently tested version."
    echo "Python ${PYTHON_VERSION} meets the minimum; run the smoke tests before relying on it."
fi

if [[ -e "${VENV_DIR}" && ! -x "${VENV_DIR}/bin/python" ]]; then
    echo "Error: ${VENV_DIR} exists but is not a usable virtual environment." >&2
    echo "Move it aside and rerun this script." >&2
    exit 1
fi

if [[ ! -d "${VENV_DIR}" ]]; then
    if ! lvs_python_prerequisites "${PYTHON_BIN}"; then
        lvs_python_guidance
        exit 1
    fi
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
    echo "Created virtual environment: ${VENV_DIR}"
else
    echo "Using existing virtual environment: ${VENV_DIR}"
fi

VENV_FIELDS="$("${VENV_DIR}/bin/python" -c 'import sys; print(sys.version_info.major, sys.version_info.minor, sys.version_info.micro)')"
read -r VENV_MAJOR VENV_MINOR VENV_MICRO <<<"${VENV_FIELDS}"
VENV_VERSION="${VENV_MAJOR}.${VENV_MINOR}.${VENV_MICRO}"
echo "Virtual environment Python: ${VENV_DIR}/bin/python (Python ${VENV_VERSION})"

if ! "${VENV_DIR}/bin/python" -c "import sys; raise SystemExit(0 if sys.version_info >= (${MINIMUM_MAJOR}, ${MINIMUM_MINOR}) else 1)"; then
    echo "Error: the existing virtual environment uses unsupported Python ${VENV_VERSION}." >&2
    echo "Move ${VENV_DIR} aside and rerun this script with Python ${MINIMUM_MAJOR}.${MINIMUM_MINOR} or newer." >&2
    exit 1
fi

if [[ -n "${PYTHON:-}" ]] && (( VENV_MAJOR != PYTHON_MAJOR || VENV_MINOR != PYTHON_MINOR )); then
    echo "Error: PYTHON selected Python ${PYTHON_MAJOR}.${PYTHON_MINOR}, but the existing .venv uses Python ${VENV_MAJOR}.${VENV_MINOR}." >&2
    echo "Move ${VENV_DIR} aside and rerun this script to create it with the selected interpreter." >&2
    exit 1
fi

"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/python" -m pip install -r "${REPO_ROOT}/requirements.txt"

echo
echo "Baseline setup complete."
echo "Optional Google Drive dependencies:"
echo "  .venv/bin/python -m pip install -r requirements-google.txt"
echo "Next commands:"
echo "  source .venv/bin/activate"
echo "  .venv/bin/python linux_validation_suite.py"
echo "  .venv/bin/python linux_validation_suite_tui.py"
echo "  .venv/bin/python smoke_tests/run_smoke_tests.py"
