#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

echo "=========================================="
echo " Installing Better PESU Acad to macOS"
echo "=========================================="

# Build if dist does not exist
if [ ! -d "dist/Better PESU Acad.app" ]; then
    echo "Bundle not found. Running build first..."
    ./scripts/build_macos.sh
fi

TARGET="/Applications/Better PESU Acad.app"
echo "Copying to $TARGET..."
rm -rf "$TARGET"
cp -R "dist/Better PESU Acad.app" /Applications/

# Clear macOS quarantine attribute
xattr -cr "$TARGET" || true

echo "=========================================="
echo "✓ Successfully installed Better PESU Acad!"
echo "You can now open it from:"
echo "  1. Spotlight (Cmd + Space -> 'Better PESU Acad')"
echo "  2. Launchpad"
echo "  3. Finder -> Applications -> Better PESU Acad"
echo "  4. Terminal: open '/Applications/Better PESU Acad.app'"
echo "=========================================="
