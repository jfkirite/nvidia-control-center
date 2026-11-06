#!/usr/bin/env bash
set -e

# NVIDIA Control Center Installer
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
APP_DIR="${HOME}/.local/share/applications"
ICON_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
TARGET_INSTALL_DIR="${HOME}/.local/share/nvidia-control-center"

echo "=== Installing NVIDIA Control Center ==="

# Check essential dependencies
MISSING_PKGS=()
for cmd in python3; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        MISSING_PKGS+=("$cmd")
    fi
done

if [ ${#MISSING_PKGS[@]} -ne 0 ]; then
    echo "[-] Missing required tools: ${MISSING_PKGS[*]}"
    exit 1
fi

# Verify Python GTK / Libadwaita / NVML bindings
echo "[*] Checking Python dependencies..."
python3 -c "import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1'); from gi.repository import Gtk, Adw" 2>/dev/null || {
    echo "[!] Warning: GTK4 and Libadwaita Python bindings not found."
    echo "    On Arch / CachyOS Linux, install them with:"
    echo "    sudo pacman -S gtk4 libadwaita python-gobject python-cairo"
}

mkdir -p "$BIN_DIR" "$APP_DIR" "$ICON_DIR" "$TARGET_INSTALL_DIR"

# Copy application files
echo "[*] Installing files to $TARGET_INSTALL_DIR..."
cp -r "$SCRIPT_DIR/nvidia_cc" "$TARGET_INSTALL_DIR/"
install -m 755 "$SCRIPT_DIR/nvidia-control-center" "$TARGET_INSTALL_DIR/nvidia-control-center"

# Create symlink in ~/.local/bin
echo "[*] Linking executable to $BIN_DIR/nvidia-control-center..."
ln -sf "$TARGET_INSTALL_DIR/nvidia-control-center" "$BIN_DIR/nvidia-control-center"

# Install desktop entry and icon
echo "[*] Installing desktop shortcut and icon..."
install -m 644 "$SCRIPT_DIR/data/nvidia-control-center.desktop" "$APP_DIR/nvidia-control-center.desktop"
install -m 644 "$SCRIPT_DIR/data/nvidia-control-center.svg" "$ICON_DIR/nvidia-control-center.svg"

# Update desktop and icon caches if tools exist
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APP_DIR" 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f "${HOME}/.local/share/icons/hicolor" 2>/dev/null || true
fi

echo ""
echo "[✓] Installation complete!"
echo "    - You can now launch NVIDIA Control Center from your App Menu / Application Launcher."
echo "    - Or run: ~/.local/bin/nvidia-control-center"
echo "    (Ensure ~/.local/bin is in your PATH if launching directly from terminal)"
