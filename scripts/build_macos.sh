#!/usr/bin/env bash
set -euo pipefail

echo "=========================================="
echo " Building Better PESU Acad for macOS"
echo "=========================================="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

# Check Python environment
if [ -d "pesu-notes/venv" ]; then
    PYTHON="pesu-notes/venv/bin/python3"
    PYINSTALLER="pesu-notes/venv/bin/pyinstaller"
elif [ -d "venv" ]; then
    PYTHON="venv/bin/python3"
    PYINSTALLER="venv/bin/pyinstaller"
else
    PYTHON="python3"
    PYINSTALLER="pyinstaller"
fi

echo "Using Python: $($PYTHON --version)"
echo "Using PyInstaller: $($PYINSTALLER --version)"

# Clean previous build artifacts
rm -rf build dist

# Run PyInstaller
$PYINSTALLER --noconfirm --clean BetterPESU.spec

if [ -d "dist/Better PESU Acad.app" ]; then
    echo "=========================================="
    echo "✓ Build Succeeded!"
    echo "Application Bundle: dist/Better PESU Acad.app"
    echo "To launch: open 'dist/Better PESU Acad.app'"
    echo "=========================================="
else
    echo "Build failed: dist/Better PESU Acad.app not created."
    exit 1
fi
