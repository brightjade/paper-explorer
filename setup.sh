#!/usr/bin/env bash
set -euo pipefail

REPO="brightjade/paper-explorer"
TAG="${1:-latest}"

echo "Downloading data from release ${TAG}..."

if command -v gh &>/dev/null; then
    if [ "$TAG" = "latest" ]; then
        # gh treats "latest" as a literal tag; no tag means the release marked Latest
        gh release download -R "$REPO" -p "data.zip" --clobber
    else
        gh release download "$TAG" -R "$REPO" -p "data.zip" --clobber
    fi
else
    if [ "$TAG" = "latest" ]; then
        URL="https://github.com/${REPO}/releases/latest/download/data.zip"
    else
        URL="https://github.com/${REPO}/releases/download/${TAG}/data.zip"
    fi
    curl -fSL "$URL" -o data.zip
fi

echo "Extracting..."
unzip -o data.zip
rm data.zip
echo "Done. Run ./build.sh to build the web app."
