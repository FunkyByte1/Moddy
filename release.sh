#!/bin/bash
# release.sh — Build and package Moddy for distribution
# Usage: ./release.sh [version]
# Example: ./release.sh v0.2.0
# If no version given, uses the version from package.json

set -e

VERSION=${1:-$(node -e "console.log(require('./package.json').version)")}
PLUGIN_NAME="moddy"
OUT_DIR="releases"
ZIP_NAME="${PLUGIN_NAME}-${VERSION}.zip"

echo "Building Moddy ${VERSION}..."

# Build frontend
pnpm run build

# Create release directory structure
rm -rf "${OUT_DIR}/tmp"
mkdir -p "${OUT_DIR}/tmp/${PLUGIN_NAME}/dist"
mkdir -p "${OUT_DIR}/tmp/${PLUGIN_NAME}/backend"

# Copy required files
cp dist/index.js "${OUT_DIR}/tmp/${PLUGIN_NAME}/dist/"
cp main.py "${OUT_DIR}/tmp/${PLUGIN_NAME}/"
cp plugin.json "${OUT_DIR}/tmp/${PLUGIN_NAME}/"
cp package.json "${OUT_DIR}/tmp/${PLUGIN_NAME}/"
cp -r registry "${OUT_DIR}/tmp/${PLUGIN_NAME}/"
cp LICENSE "${OUT_DIR}/tmp/${PLUGIN_NAME}/"
cp README.md "${OUT_DIR}/tmp/${PLUGIN_NAME}/"

# Copy backend
cp backend/*.py "${OUT_DIR}/tmp/${PLUGIN_NAME}/backend/"

# Create zip
mkdir -p "${OUT_DIR}"
cd "${OUT_DIR}/tmp"
zip -r "../${ZIP_NAME}" "${PLUGIN_NAME}/"
cd ../..

# Clean up tmp
rm -rf "${OUT_DIR}/tmp"

echo ""
echo "✓ Release built: ${OUT_DIR}/${ZIP_NAME}"
echo ""
echo "Next steps:"
echo "  1. Create a GitHub release tagged ${VERSION}"
echo "  2. Upload ${OUT_DIR}/${ZIP_NAME} as a release asset"
echo "  3. Share the zip URL with beta testers:"
echo "     https://github.com/FunkyByte1/Moddy/releases/download/${VERSION}/${ZIP_NAME}"