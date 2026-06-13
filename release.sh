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

# Copy runtime files (what Decky actually loads)
cp dist/index.js "${OUT_DIR}/tmp/${PLUGIN_NAME}/dist/"
cp main.py "${OUT_DIR}/tmp/${PLUGIN_NAME}/"
cp plugin.json "${OUT_DIR}/tmp/${PLUGIN_NAME}/"
cp package.json "${OUT_DIR}/tmp/${PLUGIN_NAME}/"
cp -r registry "${OUT_DIR}/tmp/${PLUGIN_NAME}/"
cp LICENSE "${OUT_DIR}/tmp/${PLUGIN_NAME}/"
cp README.md "${OUT_DIR}/tmp/${PLUGIN_NAME}/"

# Copy backend (Python source — already the preferred form for modification)
cp backend/*.py "${OUT_DIR}/tmp/${PLUGIN_NAME}/backend/"

# --- Corresponding Source (GPL-3.0) ---
# The only compiled artifact we ship is dist/index.js, built from the frontend
# source below. Bundling it means the zip is GPL-complete on its own: the
# Corresponding Source travels with the binary. Decky ignores these extra files.
cp -r src "${OUT_DIR}/tmp/${PLUGIN_NAME}/"
cp rollup.config.js "${OUT_DIR}/tmp/${PLUGIN_NAME}/"
cp tsconfig.json "${OUT_DIR}/tmp/${PLUGIN_NAME}/"
cp pnpm-lock.yaml "${OUT_DIR}/tmp/${PLUGIN_NAME}/"
cp BUILDING.md "${OUT_DIR}/tmp/${PLUGIN_NAME}/"

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
echo "Releases are normally published automatically by the Nightly workflow."
echo "To publish this build manually to the public repo instead:"
echo "  cp ${OUT_DIR}/${ZIP_NAME} ${OUT_DIR}/moddy-nightly.zip"
echo "  gh release delete nightly --repo FunkyByte1/Moddy-releases --yes --cleanup-tag || true"
echo "  gh release create nightly \\"
echo "    ${OUT_DIR}/${ZIP_NAME} ${OUT_DIR}/moddy-nightly.zip \\"
echo "    --repo FunkyByte1/Moddy-releases --title \"Nightly\" --prerelease"
echo ""
echo "Decky install link (constant — always the latest nightly):"
echo "  https://github.com/FunkyByte1/Moddy-releases/releases/download/nightly/moddy-nightly.zip"