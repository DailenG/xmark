#!/usr/bin/env bash
set -euo pipefail

# Xmark install script for Omarchy

XMARK_DIR="$HOME/.config/omarchy/plugins/xmark"
LOCAL_BIN="$HOME/.local/bin"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing Xmark..."

# Create plugin directory
mkdir -p "$XMARK_DIR"

# Copy widget files
cp "$REPO_ROOT/manifest.json" "$XMARK_DIR/" 2>/dev/null || true
cp "$REPO_ROOT/Xmark.qml" "$XMARK_DIR/" 2>/dev/null || true

# If running from project root, also copy from there
if [[ -f "manifest.json" ]]; then
    cp manifest.json "$XMARK_DIR/"
fi
if [[ -f "Xmark.qml" ]]; then
    cp Xmark.qml "$XMARK_DIR/"
fi

# Enable plugin
echo "Enabling Omarchy plugin..."
omarchy plugin enable xmark

# Create symlink in ~/.local/bin
mkdir -p "$LOCAL_BIN"
ln -sf "$REPO_ROOT/.venv/bin/xmark" "$LOCAL_BIN/xmark"

echo "Xmark installed successfully!"
echo ""
echo "Next steps:"
echo "1. Add X_BEARER_TOKEN to your ~/.env file"
echo "2. Restart your bar: omarchy-bar restart"
echo "3. Click the bookmark icon in the bar to open Xmark"
echo ""
echo "Keybindings in Xmark:"
echo "  j/k or ↑/↓  - Navigate"
echo "  Enter       - Open tweet detail"
echo "  o           - Open author profile"
echo "  d           - Delete bookmark"
echo "  r           - Refresh"
echo "  q           - Quit"