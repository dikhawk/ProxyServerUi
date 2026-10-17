#!/usr/bin/env bash
set -euo pipefail

# Determine script root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check virtual environment
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "Error: Virtual environment not found at $VENV_PYTHON" >&2
    echo "Please create venv and install dependencies: python -m venv venv && ./venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

# Run the application
exec "$VENV_PYTHON" main.py "$@"
