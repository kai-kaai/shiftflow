#!/usr/bin/env bash
set -euo pipefail

USERNAME="chawakorn"
PROJECT_DIR="/home/${USERNAME}/shiftflow"
REPO_URL="https://github.com/kai-kaai/shiftflow.git"
VENV_NAME="shiftflow-env"
PYTHON_BIN="$(command -v python3.10 || command -v python3.11 || command -v python3)"

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

if [ ! -f "${HOME}/.virtualenvs/${VENV_NAME}/bin/activate" ]; then
  echo "==> Creating virtualenv: ${VENV_NAME}"
  mkvirtualenv --python="${PYTHON_BIN}" "${VENV_NAME}"
fi

# shellcheck disable=SC1091
source "${HOME}/.virtualenvs/${VENV_NAME}/bin/activate"
pip install --upgrade pip
pip install -r requirements.txt

cat <<EOF

✅ Code and dependencies are ready.

Project path:
  ${PROJECT_DIR}

Virtualenv:
  ${HOME}/.virtualenvs/${VENV_NAME}

Configure in Web tab (if this is a fresh setup):
  1. Add a new web app -> Manual configuration -> Python 3.10
  2. Source code: ${PROJECT_DIR}
  3. Virtualenv: ${HOME}/.virtualenvs/${VENV_NAME}
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