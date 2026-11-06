#!/usr/bin/env bash
set -e

BIN_DIR="${HOME}/.local/bin"
APP_DIR="${HOME}/.local/share/applications"
ICON_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
TARGET_INSTALL_DIR="${HOME}/.local/share/nvidia-control-center"

echo "=== Uninstalling NVIDIA Control Center ==="

rm -f "$BIN_DIR/nvidia-control-center"
rm -f "$APP_DIR/nvidia-control-center.desktop"
rm -f "$ICON_DIR/nvidia-control-center.svg"
rm -rf "$TARGET_INSTALL_DIR"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APP_DIR" 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f "${HOME}/.local/share/icons/hicolor" 2>/dev/null || true
fi

echo "[✓] Uninstalled successfully."
