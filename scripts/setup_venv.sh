#!/usr/bin/env bash
set -euo pipefail

readonly TESTED_MAJOR=3
readonly TESTED_MINOR=14
readonly MINIMUM_MAJOR=3
readonly MINIMUM_MINOR=10

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"

if [[ -n "${PYTHON:-}" ]]; then
    PYTHON_BIN="${PYTHON}"
elif command -v python3.14 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3.14)"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    echo "Error: no Python interpreter found." >&2
    echo "Install Python ${MINIMUM_MAJOR}.${MINIMUM_MINOR} or newer, or set PYTHON=/path/to/python." >&2
    exit 1
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1 && [[ ! -x "${PYTHON_BIN}" ]]; then
    echo "Error: Python interpreter is not executable: ${PYTHON_BIN}" >&2
    exit 1
fi

if ! VERSION_FIELDS="$("${PYTHON_BIN}" -c 'import sys; print(sys.version_info.major, sys.version_info.minor, sys.version_info.micro)')"; then
    echo "Error: failed to run Python interpreter: ${PYTHON_BIN}" >&2
    exit 1
fi
read -r PYTHON_MAJOR PYTHON_MINOR PYTHON_MICRO <<<"${VERSION_FIELDS}"
PYTHON_VERSION="${PYTHON_MAJOR}.${PYTHON_MINOR}.${PYTHON_MICRO}"

if (( PYTHON_MAJOR < MINIMUM_MAJOR || (PYTHON_MAJOR == MINIMUM_MAJOR && PYTHON_MINOR < MINIMUM_MINOR) )); then
    echo "Error: Python ${PYTHON_VERSION} is too old." >&2
    echo "Linux Validation Suite requires Python ${MINIMUM_MAJOR}.${MINIMUM_MINOR} or newer." >&2
    echo "Python ${TESTED_MAJOR}.${TESTED_MINOR} is the currently tested version." >&2
    exit 1
fi

echo "Selected Python: ${PYTHON_BIN} (Python ${PYTHON_VERSION})"
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
