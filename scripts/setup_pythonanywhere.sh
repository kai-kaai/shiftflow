#!/usr/bin/env bash
set -euo pipefail

USERNAME="chawakorn"
PROJECT_DIR="/home/${USERNAME}/shiftflow"
REPO_URL="https://github.com/kai-kaai/shiftflow.git"
VENV_NAME="shiftflow-env"
VENV_DIR="${HOME}/.virtualenvs/${VENV_NAME}"
PYTHON_BIN="$(command -v python3.10 || command -v python3.11 || command -v python3)"

load_virtualenvwrapper() {
  export WORKON_HOME="${HOME}/.virtualenvs"
  export PROJECT_HOME="${HOME}"

  if [ -z "${VIRTUALENVWRAPPER_PYTHON:-}" ]; then
    export VIRTUALENVWRAPPER_PYTHON="${PYTHON_BIN}"
  fi

  for wrapper in \
    /usr/local/bin/virtualenvwrapper.sh \
    /usr/share/virtualenvwrapper/virtualenvwrapper.sh \
    "${HOME}/.local/bin/virtualenvwrapper.sh"
  do
    if [ -f "${wrapper}" ]; then
      # shellcheck disable=SC1090
      source "${wrapper}"
      return 0
    fi
  done

  return 1
}

create_virtualenv() {
  mkdir -p "${HOME}/.virtualenvs"

  if [ -f "${VENV_DIR}/bin/activate" ]; then
    echo "==> Virtualenv already exists: ${VENV_NAME}"
    return 0
  fi

  echo "==> Creating virtualenv: ${VENV_NAME}"

  if load_virtualenvwrapper && command -v mkvirtualenv >/dev/null 2>&1; then
    mkvirtualenv --python="${PYTHON_BIN}" "${VENV_NAME}"
    return 0
  fi

  echo "==> mkvirtualenv not available, using python -m venv"
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
}

echo "==> ShiftFlow setup for PythonAnywhere (${USERNAME})"

cd ~

if [ -d "${PROJECT_DIR}/.git" ]; then
  echo "==> Updating existing repository..."
  cd "${PROJECT_DIR}"
  git pull origin main
else
  echo "==> Cloning repository..."
  rm -rf "${PROJECT_DIR}"
  git clone "${REPO_URL}" "${PROJECT_DIR}"
  cd "${PROJECT_DIR}"
fi

create_virtualenv

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
pip install --upgrade pip
pip install -r requirements.txt

cat <<EOF

✅ Code and dependencies are ready.

Project path:
  ${PROJECT_DIR}

Virtualenv:
  ${VENV_DIR}

Configure in Web tab (if this is a fresh setup):
  1. Add a new web app -> Manual configuration -> Python 3.10
  2. Source code: ${PROJECT_DIR}
  3. Virtualenv: ${VENV_DIR}
  4. Static files: URL /static/ -> Directory ${PROJECT_DIR}/static/
  5. WSGI file content:

import sys
import os

project_home = '${PROJECT_DIR}'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

os.chdir(project_home)

from app import app as application

  6. Click Reload

Site URL:
  https://${USERNAME}.pythonanywhere.com/
EOF