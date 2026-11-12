#!/usr/bin/env bash
# GLB2Print GUI Launcher for macOS and Linux
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

# Determine python command
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "Error: Python 3 is required but not found."
    exit 1
fi

"$PYTHON_CMD" app_gui.py
