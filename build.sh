#!/usr/bin/env bash
set -e

echo "================================================"
echo " Claude Monitor - macOS Build Script"
echo "================================================"
echo

# Find a Homebrew Python that has tkinter (prefer 3.13, 3.12, 3.11 in order)
PYTHON=""
for ver in 3.13 3.12 3.11; do
    candidate="$(brew --prefix)/bin/python${ver}"
    if [ -x "$candidate" ] && "$candidate" -c "import tkinter" 2>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[ERROR] No Homebrew Python with tkinter found."
    echo "  Run:  brew install python@3.13 python-tk@3.13"
    exit 1
fi

echo "Using Python: $($PYTHON --version) at $PYTHON"

# Create / reuse a local venv
VENV=".build-venv"
if [ -d "$VENV" ]; then
    echo "[setup] Removing old virtual environment..."
    rm -rf "$VENV"
fi
echo "[setup] Creating virtual environment..."
"$PYTHON" -m venv "$VENV"
PIP="$VENV/bin/pip"

echo "[1/4] Installing dependencies..."
"$PIP" install pyinstaller pystray pillow --quiet

echo "[2/4] Building ClaudeMonitor.app..."
"$VENV/bin/python" -m PyInstaller \
    --windowed \
    --name ClaudeMonitor \
    --hidden-import pystray._darwin \
    --hidden-import PIL._tkinter_finder \
    --osx-bundle-identifier com.claudemonitor.app \
    --clean \
    claude_monitor.py

echo "[3/4] Signing app (ad-hoc)..."
codesign --force --deep --sign - dist/ClaudeMonitor.app

echo "[4/4] Removing quarantine attribute & cleaning up..."
xattr -cr dist/ClaudeMonitor.app
rm -rf build ClaudeMonitor.spec

echo
echo "================================================"
echo " Done!  dist/ClaudeMonitor.app is ready."
echo " Drag it to /Applications to install."
echo "================================================"
