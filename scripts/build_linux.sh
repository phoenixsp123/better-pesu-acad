#!/usr/bin/env bash
set -euo pipefail

echo "=========================================="
echo " Building Better PESU Acad for Linux"
echo "=========================================="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

PYINSTALLER="${PYINSTALLER:-pyinstaller}"

rm -rf build dist
$PYINSTALLER --noconfirm --clean BetterPESU.spec

if [ -f "dist/BetterPESU/BetterPESU" ]; then
    echo "=========================================="
    echo "✓ Build Succeeded!"
    echo "Binary located at: dist/BetterPESU/BetterPESU"
    echo "=========================================="
else
    echo "Build failed: binary not found."
    exit 1
fi
