# NVIDIA Control Center for Linux

A native **GTK4 + Libadwaita + NVML (`libnvidia-ml.so.1`)** graphics control panel modeled after the modern Windows **NVIDIA App**, built for **Linux (GNOME, KDE Plasma, X11, Wayland + NVIDIA RTX / GTX)**.

![NVIDIA Control Center Icon](data/nvidia-control-center.svg)

---

## Features

1. **Ultra-Smooth Frametime Optimization (All-in-One)**
   - 1-Click toggle optimizing your entire graphics pipeline and Linux kernel for jitter-free, buttery smooth frame pacing:
     - Automatically locks frame rate limit to your monitor's exact refresh cadence (e.g. 100 FPS).
     - Enables Ultra Low Latency queue (`__GL_MaxFramesAllowed=1`) and Multi-Threaded driver optimizations.
     - Loads kernel `/dev/ntsync` driver and sets `kernel.split_lock_mitigate=0` to eliminate wine lock delays and CPU bus freeze stutters.
     - Forces PCIe runtime power management to full performance (`power/control=on`) to prevent bus downclocking spikes.
     - Enables Resizable BAR, Stream Memory Ops, VRAM frequency locks, and CPU `performance` frequency governor.

2. **Clean, Clutter-Free UI with Interactive Hover Tooltips**
   - Simplified, beginner-friendly setting names.
   - Rich interactive hover tooltips over all options, sliders, and toggles explaining in plain English what each setting does, why to use it, and its system internals.

3. **Graphics, DLSS & Game Profiles (Zero-Config Steam Proton Integration)**
   - Automatically discovers installed Steam games from `steamapps/appmanifest_*.acf`.
   - Applies global and per-game overrides **directly and automatically** to Steam Proton prefixes (`compatdata/<appid>/user_settings.py`) and the user environment (`~/.config/environment.d/90-nvidia-control-center.conf` + `systemctl --user`) — **no Steam Launch Options or wrapper commands needed**.
   - Unified per-game and global controls for:
     - **OptiScaler Universal Frame Generation Switch & Mode Multiplier**: Replaces hardware-restricted DLSS Frame Generation with OptiScaler universal Frame Generation (FSR 3.1 & XeFG compute pipeline) built directly into the app and Linux kernel level. Seamlessly generates interpolated AI frames on RTX 3050 and non-Ada GPUs via Streamline & DXGI interception without requiring Ada Lovelace Optical Flow hardware.
     - **DLSS Super Resolution, DLAA & Ray Reconstruction Override** (`PROTON_ENABLE_NGX_UPDATER=1`, `PROTON_DLSS_UPGRADE=1`, `DXVK_NVAPI_DRS_SETTINGS`)
     - **Quick 1-Click DLSS Upscaling Mode Presets** (DLAA 100%, Ultra Quality 77%, Quality 67%, Balanced 58%, Performance 50%, Ultra Performance 33%, or Custom 33%–100%)
     - **DLSS AI Render Preset Selection** (Default, Preset E, Preset F, Preset J/K Transformer) & On-Screen HUD Indicator (`PROTON_DLSS_INDICATOR=1`)
     - **OptiScaler Universal Upscaler Injection** (`PROTON_USE_OPTISCALER=1`) & **Vulkan CAS Image Sharpening**
     - **VSync, G-SYNC / VRR Allowed (`__GL_VRR_ALLOWED`), Ultra Low Latency (`__GL_MaxFramesAllowed=1`)**
     - **Texture Quality (`__GL_ImageSettings`), Threaded Optimization, Unlimited Shader Disk Cache**
     - **PRIME Render Offload, Proton Wayland (`PROTON_ENABLE_WAYLAND=1`), Proton HDR (`PROTON_ENABLE_HDR=1`), MangoHud & FPS Limiter**

4. **Performance & Hardware Tuning (Wayland Native via NVML)**
   - Quick presets: **Silent / Eco**, **Balanced (Default)**, **Max Performance (OC)**, and **Smooth Frametimes**.
   - Direct NVML hardware controls applied in a single PolicyKit (`pkexec`) batch:
     - Power Limit (`nvmlDeviceSetPowerManagementLimit`)
     - GPU Core Clock Offset (`nvmlDeviceSetGpcClkVfOffset`)
     - VRAM Memory Clock Offset (`nvmlDeviceSetMemClkVfOffset`)
     - Persistence Mode (`nvmlDeviceSetPersistenceMode`)
     - Fan Policy (Automatic VBIOS, Manual Fixed %, or **Interactive 5-Point Software Fan Curve**)
     - Linux kernel PCIe power management, Resizable BAR, and CPU governor tuning.

5. **Display & Color Management**
   - Integrates with KDE Plasma Wayland (`kscreen-doctor`), DRM EDID detection, and `nvidia-settings` (Digital Vibrance, RGB Range, HDR10, VRR policy, Refresh Rate, and Scale).

6. **System & Driver Inspector**
   - Complete hardware, VBIOS, UUID, CUDA, Vulkan, `nvidia-drm` kernel module parameters, and system kernel overview with one-click clipboard export.

---

## Desktop Environment & Distro Support

- **GNOME (Wayland / X11)**:
  - Native **Libadwaita** design that matches GNOME's aesthetic, dark/light themes, and window decorations out of the box.
  - Full GPU overclocking, power limit, fan curves, OptiScaler/DLSS frame generation, and Steam Proton game profiles work 100%.
  - Display resolution, scaling, and refresh rates are managed natively via GNOME Settings (`gnome-control-center display`).
- **KDE Plasma (Wayland / X11)**:
  - Full support including native Wayland color management (`kscreen-doctor`) for refresh rates, VRR, HDR, and ICC-based Digital Vibrance.
- **Other Desktop Environments (XFCE, Cinnamon, Hyprland, Sway)**:
  - Fully compatible with all GPU tuning, fan curves, and game profiles.

---

## Requirements

Ensure you have the official **NVIDIA proprietary driver** (535, 550, 560, or newer) installed.

### Install Required Dependencies

#### **Ubuntu / Debian / Linux Mint / Pop!_OS**
```bash
sudo apt update
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libadwaita-1-0 policykit-1
```

#### **Fedora / Nobara Linux**
```bash
sudo dnf install python3-gobject gtk4 libadwaita polkit
```

#### **Arch Linux / CachyOS**
```bash
sudo pacman -S gtk4 libadwaita python-gobject python-cairo polkit
```
*(Optional on KDE: `kscreen` for Wayland display controls)*

#### **openSUSE (Tumbleweed / Leap)**
```bash
sudo zypper install python3-gobject typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 libadwaita-1-0 polkit
```

---

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/jfkirite/nvidia-control-center.git
   cd nvidia-control-center
   ```

2. **Run the installer:**
   ```bash
   ./install.sh
   ```
   This will install the desktop entry, high-resolution SVG icon, and executable into `~/.local/bin`.

---

## Launching

- **From App Menu**: Launch **NVIDIA Control Center** from your Application Launcher / Start Menu.
- **From Terminal**:
  ```bash
  nvidia-control-center
  ```
  *(Make sure `~/.local/bin` is in your `$PATH`)*

---

## Uninstallation

To remove NVIDIA Control Center and its desktop entries:
```bash
./uninstall.sh
```

---

## License

[MIT](LICENSE)
