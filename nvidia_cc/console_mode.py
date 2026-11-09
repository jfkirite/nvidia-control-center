"""
Console 30 FPS Mode Manager for NVIDIA Control Center on Linux.
Provides frame pacing (33.3ms cadence) via global MangoHud / DXVK / VKD3D limits
and display refresh rate pulldown switching (60Hz 2:2 pulldown or 120Hz 4:1 pulldown)
across KDE Wayland (kscreen-doctor), GNOME Wayland (Mutter DisplayConfig D-Bus), and X11 (xrandr).
"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple


@dataclass
class DisplayModeInfo:
    mode_id: str
    width: int
    height: int
    refresh_rate: float
    is_current: bool = False


@dataclass
class PrimaryMonitorState:
    connector: str
    monitor_name: str
    current_mode_id: str
    current_refresh_rate: float
    native_refresh_rate: float
    available_modes: List[DisplayModeInfo] = field(default_factory=list)
    session_type: str = "wayland"
    backend: str = "gnome"  # "gnome", "kde", "x11", or "drm"


class ConsoleModeManager:
    """Manages Console 30 FPS mode: 33.3ms frame pacing and display refresh pulldown."""

    STATE_FILE = Path.home() / ".config" / "nvidia-control-center" / "console_mode_state.json"
    MANGOHUD_CONF = Path.home() / ".config" / "MangoHud" / "MangoHud.conf"
    ENV_SCRIPT = Path.home() / ".config" / "nvidia-control-center" / "console_30fps_env.sh"
    WRAPPER_SCRIPT = Path.home() / ".local" / "bin" / "console-30fps-run"
    SYSTEMD_ENV = Path.home() / ".config" / "environment.d" / "30-nvidia-console-mode.conf"

    def __init__(self):
        self.config_dir = Path.home() / ".config" / "nvidia-control-center"
        self.config_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # State Persistence & Caching
    # ------------------------------------------------------------------
    def load_state(self) -> dict:
        if self.STATE_FILE.exists():
            try:
                return json.loads(self.STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "enabled": False,
            "target_rate": 60,
            "cached_native_connector": None,
            "cached_native_mode_id": None,
            "cached_native_rate": None,
        }

    def save_state(self, state: dict) -> None:
        try:
            self.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Environment & Display Detection
    # ------------------------------------------------------------------
    @staticmethod
    def detect_session_type() -> str:
        return os.environ.get("XDG_SESSION_TYPE", "").strip().lower() or "wayland"

    @staticmethod
    def detect_desktop_environment() -> str:
        desk = os.environ.get("XDG_CURRENT_DESKTOP", "").strip().upper()
        if "KDE" in desk or "PLASMA" in desk:
            return "kde"
        if "GNOME" in desk:
            return "gnome"
        return "other"

    def get_primary_monitor_state(self) -> Optional[PrimaryMonitorState]:
        """Queries primary monitor, current mode, and available modes across all backends."""
        session_type = self.detect_session_type()
        desktop = self.detect_desktop_environment()

        # 1. On Wayland with KDE, prefer kscreen-doctor
        if session_type == "wayland" and desktop == "kde" and shutil.which("kscreen-doctor"):
            st = self._query_kscreen()
            if st is not None:
                return st

        # 2. On Wayland with GNOME (or Mutter DBus available)
        if session_type == "wayland":
            st = self._query_mutter()
            if st is not None:
                return st

        # 3. If kscreen-doctor is present even if desktop string differed
        if shutil.which("kscreen-doctor"):
            st = self._query_kscreen()
            if st is not None:
                return st

        # 4. Under X11 (or fallback)
        if shutil.which("xrandr"):
            st = self._query_xrandr()
            if st is not None:
                return st

        # 5. Last resort: DRM sysfs fallback
        return self._query_drm_fallback()

    def _query_mutter(self) -> Optional[PrimaryMonitorState]:
        """Queries org.gnome.Mutter.DisplayConfig over D-Bus."""
        try:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            proxy = Gio.DBusProxy.new_sync(
                bus,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.gnome.Mutter.DisplayConfig",
                "/org/gnome/Mutter/DisplayConfig",
                "org.gnome.Mutter.DisplayConfig",
                None,
            )
            state = proxy.GetCurrentState()
            _serial, monitors, logical_monitors, _props = state

            # Find primary logical monitor
            primary_conn = None
            for lm in logical_monitors:
                _x, _y, _scale, _transform, is_primary, outputs, _lm_props = lm
                if is_primary and outputs:
                    primary_conn = outputs[0][0]
                    break
            if not primary_conn and logical_monitors and logical_monitors[0][5]:
                primary_conn = logical_monitors[0][5][0][0]

            if not primary_conn and monitors:
                primary_conn = monitors[0][0][0]

            if not primary_conn:
                return None

            # Find monitor info
            for m in monitors:
                info, modes, _mprops = m
                connector, _vendor, product, _serial_no = info
                if connector != primary_conn:
                    continue

                modes_list: List[DisplayModeInfo] = []
                cur_mode_id = ""
                cur_rate = 60.0
                max_rate = 60.0

                for mode in modes:
                    m_id, w, h, rate, _scale, _supp_scales, m_props = mode
                    rate_f = float(rate)
                    is_cur = "is-current" in m_props
                    if is_cur:
                        cur_mode_id = m_id
                        cur_rate = rate_f
                    if rate_f > max_rate:
                        max_rate = rate_f
                    modes_list.append(
                        DisplayModeInfo(
                            mode_id=m_id,
                            width=int(w),
                            height=int(h),
                            refresh_rate=rate_f,
                            is_current=is_cur,
                        )
                    )

                if not cur_mode_id and modes_list:
                    cur_mode_id = modes_list[0].mode_id
                    cur_rate = modes_list[0].refresh_rate

                return PrimaryMonitorState(
                    connector=connector,
                    monitor_name=product or connector,
                    current_mode_id=cur_mode_id,
                    current_refresh_rate=cur_rate,
                    native_refresh_rate=max_rate,
                    available_modes=modes_list,
                    session_type="wayland",
                    backend="gnome",
                )
        except Exception:
            pass
        return None

    def _query_kscreen(self) -> Optional[PrimaryMonitorState]:
        """Queries kscreen-doctor -j."""
        try:
            raw = subprocess.check_output(
                ["kscreen-doctor", "-j"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3,
            )
            clean = re.sub(r"\x1b\[[0-9;]*m", "", raw)
            data = json.loads(clean)
            outputs = data.get("outputs", [])
            if not outputs:
                return None

            primary_out = None
            for out in outputs:
                if out.get("primary") and out.get("enabled", True):
                    primary_out = out
                    break
            if not primary_out:
                for out in outputs:
                    if out.get("enabled", True) and out.get("connected", True):
                        primary_out = out
                        break
            if not primary_out and outputs:
                primary_out = outputs[0]

            name = primary_out.get("name", "")
            cur_mode_id = primary_out.get("currentModeId", "")
            modes_raw = primary_out.get("modes", [])

            modes_list: List[DisplayModeInfo] = []
            cur_rate = 60.0
            max_rate = 60.0

            for m in modes_raw:
                m_id = str(m.get("id", ""))
                size = m.get("size", {})
                w = int(size.get("width", 1920))
                h = int(size.get("height", 1080))
                rate_f = float(m.get("refreshRate", 60.0))
                is_cur = m_id == str(cur_mode_id)
                if is_cur:
                    cur_rate = rate_f
                if rate_f > max_rate:
                    max_rate = rate_f
                modes_list.append(
                    DisplayModeInfo(
                        mode_id=m_id,
                        width=w,
                        height=h,
                        refresh_rate=rate_f,
                        is_current=is_cur,
                    )
                )

            return PrimaryMonitorState(
                connector=name,
                monitor_name=name,
                current_mode_id=str(cur_mode_id),
                current_refresh_rate=cur_rate,
                native_refresh_rate=max_rate,
                available_modes=modes_list,
                session_type="wayland",
                backend="kde",
            )
        except Exception:
            pass
        return None

    def _query_xrandr(self) -> Optional[PrimaryMonitorState]:
        """Queries xrandr --current under X11."""
        try:
            proc = subprocess.run(
                ["xrandr", "--current"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if proc.returncode != 0:
                return None

            primary_conn = None
            conns: Dict[str, dict] = {}
            cur_conn = None

            for line in proc.stdout.splitlines():
                m = re.match(r"^([A-Za-z0-9\-_]+)\s+(connected|disconnected)\s*(primary)?.*", line)
                if m:
                    cur_conn = m.group(1)
                    is_connected = m.group(2) == "connected"
                    is_primary = bool(m.group(3))
                    if is_connected:
                        conns[cur_conn] = {"primary": is_primary, "modes": []}
                        if is_primary:
                            primary_conn = cur_conn
                elif cur_conn and cur_conn in conns and line.startswith("   "):
                    parts = line.strip().split()
                    if parts:
                        res = parts[0]
                        for rate_str in parts[1:]:
                            is_cur = "*" in rate_str
                            clean_rate = rate_str.rstrip("*+ ")
                            try:
                                r_val = float(clean_rate)
                            except ValueError:
                                continue
                            conns[cur_conn]["modes"].append((res, r_val, is_cur))

            if not primary_conn and conns:
                primary_conn = next(iter(conns.keys()))

            if not primary_conn or primary_conn not in conns:
                return None

            c_info = conns[primary_conn]
            modes_list: List[DisplayModeInfo] = []
            cur_rate = 60.0
            max_rate = 60.0
            cur_mode_id = ""

            for res, r_val, is_cur in c_info["modes"]:
                w, h = (1920, 1080)
                if "x" in res:
                    try:
                        w_s, h_s = res.split("x", 1)
                        w, h = int(w_s), int(h_s)
                    except ValueError:
                        pass
                m_id = f"{res}@{r_val:.1f}"
                if is_cur:
                    cur_rate = r_val
                    cur_mode_id = m_id
                if r_val > max_rate:
                    max_rate = r_val
                modes_list.append(
                    DisplayModeInfo(
                        mode_id=m_id,
                        width=w,
                        height=h,
                        refresh_rate=r_val,
                        is_current=is_cur,
                    )
                )

            return PrimaryMonitorState(
                connector=primary_conn,
                monitor_name=primary_conn,
                current_mode_id=cur_mode_id or f"1920x1080@{cur_rate:.0f}",
                current_refresh_rate=cur_rate,
                native_refresh_rate=max_rate,
                available_modes=modes_list,
                session_type="x11",
                backend="x11",
            )
        except Exception:
            pass
        return None

    def _query_drm_fallback(self) -> PrimaryMonitorState:
        """Fallback querying sysfs DRM."""
        drm_root = Path("/sys/class/drm")
        connector = "DP-3"
        for conn_dir in sorted(drm_root.glob("card*-*")):
            st_file = conn_dir / "status"
            if st_file.exists():
                try:
                    if st_file.read_text(encoding="utf-8").strip() == "connected":
                        connector = conn_dir.name.split("-", 1)[1]
                        break
                except Exception:
                    pass

        return PrimaryMonitorState(
            connector=connector,
            monitor_name="Primary Display",
            current_mode_id="1920x1080@60",
            current_refresh_rate=60.0,
            native_refresh_rate=60.0,
            available_modes=[
                DisplayModeInfo("1920x1080@60", 1920, 1080, 60.0, is_current=True)
            ],
            session_type=self.detect_session_type(),
            backend="drm",
        )

    # ------------------------------------------------------------------
    # Display Refresh Switching Implementations
    # ------------------------------------------------------------------
    def switch_display_refresh(
        self,
        target_hz: int,
        target_mode_id: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Switches display refresh rate using the appropriate backend."""
        state = self.get_primary_monitor_state()
        if not state:
            return False, "Unable to query primary display output."

        connector = state.connector

        # Choose backend based on active state / environment
        if state.backend == "gnome":
            return self._switch_mutter(connector, target_hz, target_mode_id, state)
        elif state.backend == "kde":
            return self._switch_kscreen(connector, target_hz, target_mode_id, state)
        elif state.backend == "x11":
            return self._switch_xrandr(connector, target_hz)
        else:
            # Try Mutter then KScreen then Xrandr
            ok, msg = self._switch_mutter(connector, target_hz, target_mode_id, state)
            if ok:
                return ok, msg
            ok, msg = self._switch_kscreen(connector, target_hz, target_mode_id, state)
            if ok:
                return ok, msg
            return self._switch_xrandr(connector, target_hz)

    def _switch_mutter(
        self,
        connector: str,
        target_hz: int,
        target_mode_id: Optional[str],
        state: PrimaryMonitorState,
    ) -> Tuple[bool, str]:
        try:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio, GLib

            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            proxy = Gio.DBusProxy.new_sync(
                bus,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.gnome.Mutter.DisplayConfig",
                "/org/gnome/Mutter/DisplayConfig",
                "org.gnome.Mutter.DisplayConfig",
                None,
            )
            serial, monitors, logical_monitors, _props = proxy.GetCurrentState()

            # Find matching mode
            selected_mode_id = target_mode_id
            if not selected_mode_id:
                # Find available mode matching target_hz on connector
                for m in monitors:
                    if m[0][0] == connector:
                        # Find mode with closest rate
                        best_diff = 999.0
                        best_id = None
                        for mode in m[1]:
                            m_id, _w, _h, rate, _scale, _supp_scales, _m_props = mode
                            diff = abs(float(rate) - float(target_hz))
                            if diff < best_diff and diff <= 1.5:
                                best_diff = diff
                                best_id = m_id
                        if best_id:
                            selected_mode_id = best_id
                        break

            if not selected_mode_id:
                # If target was 120Hz and not available, attempt fallback to 60Hz
                if target_hz == 120:
                    for m in monitors:
                        if m[0][0] == connector:
                            for mode in m[1]:
                                m_id, _w, _h, rate, _scale, _supp_scales, _m_props = mode
                                if abs(float(rate) - 60.0) <= 1.5:
                                    selected_mode_id = m_id
                                    break
                    if selected_mode_id:
                        # Construct logical monitors with 60Hz fallback
                        new_logical_monitors = []
                        for lm in logical_monitors:
                            x, y, scale, transform, is_primary, outputs, _lm_props = lm
                            new_outputs = []
                            for out in outputs:
                                c_name = out[0]
                                if c_name == connector:
                                    new_outputs.append((c_name, selected_mode_id, {}))
                                else:
                                    cur_m = self._find_mutter_current_mode(monitors, c_name) or selected_mode_id
                                    new_outputs.append((c_name, cur_m, {}))
                            new_logical_monitors.append((x, y, scale, transform, is_primary, new_outputs))

                        proxy.call_sync(
                            "ApplyMonitorsConfig",
                            GLib.Variant("(uua(iiduba(ssa{sv}))a{sv})", (serial, 2, new_logical_monitors, {})),
                            Gio.DBusCallFlags.NONE,
                            -1,
                            None,
                        )
                        return True, f"Display '{connector}' does not support 120Hz. Fallen back to 60Hz ({selected_mode_id}) via GNOME Mutter."

                return False, f"Display '{connector}' does not support a ~{target_hz}Hz refresh rate mode in GNOME Mutter."

            # Construct new logical_monitors structure
            new_logical_monitors = []
            for lm in logical_monitors:
                x, y, scale, transform, is_primary, outputs, _lm_props = lm
                new_outputs = []
                for out in outputs:
                    c_name = out[0]
                    if c_name == connector:
                        new_outputs.append((c_name, selected_mode_id, {}))
                    else:
                        # Keep existing mode for other monitors
                        cur_m = self._find_mutter_current_mode(monitors, c_name) or selected_mode_id
                        new_outputs.append((c_name, cur_m, {}))
                new_logical_monitors.append((x, y, scale, transform, is_primary, new_outputs))

            # Apply persistent (method 2)
            proxy.call_sync(
                "ApplyMonitorsConfig",
                GLib.Variant("(uua(iiduba(ssa{sv}))a{sv})", (serial, 2, new_logical_monitors, {})),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            return True, f"Switched {connector} to {target_hz}Hz ({selected_mode_id}) via GNOME Mutter."
        except Exception as exc:
            return False, f"GNOME Mutter DisplayConfig error: {exc}"

    @staticmethod
    def _find_mutter_current_mode(monitors, connector: str) -> Optional[str]:
        for m in monitors:
            if m[0][0] == connector:
                for mode in m[1]:
                    if "is-current" in mode[6]:
                        return mode[0]
                if m[1]:
                    return m[1][0][0]
        return None

    def _switch_kscreen(
        self,
        connector: str,
        target_hz: int,
        target_mode_id: Optional[str],
        state: PrimaryMonitorState,
    ) -> Tuple[bool, str]:
        if not shutil.which("kscreen-doctor"):
            return False, "kscreen-doctor executable not found."

        mode_arg = target_mode_id
        fallback_note = ""
        if not mode_arg:
            # Find mode with closest refresh rate
            best_diff = 999.0
            best_id = None
            for m in state.available_modes:
                diff = abs(m.refresh_rate - float(target_hz))
                if diff < best_diff and diff <= 1.5:
                    best_diff = diff
                    best_id = m.mode_id
            if best_id:
                mode_arg = best_id
            elif target_hz == 120:
                # Try fallback to 60Hz
                for m in state.available_modes:
                    if abs(m.refresh_rate - 60.0) <= 1.5:
                        mode_arg = m.mode_id
                        fallback_note = f"Display '{connector}' does not support 120Hz. Fallen back to 60Hz via KDE KScreen."
                        break
            if not mode_arg:
                mode_arg = f"{target_hz}"

        cmd = ["kscreen-doctor", f"output.{connector}.mode.{mode_arg}"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if proc.returncode == 0:
                msg = fallback_note or f"Switched {connector} to {target_hz}Hz via KDE KScreen."
                return True, msg
            return False, (proc.stderr or proc.stdout or "kscreen-doctor returned an error").strip()
        except Exception as exc:
            return False, f"KScreen error: {exc}"

    def _switch_xrandr(self, connector: str, target_hz: int) -> Tuple[bool, str]:
        if not shutil.which("xrandr"):
            return False, "xrandr executable not found."

        cmd = ["xrandr", "--output", connector, "--rate", str(target_hz)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if proc.returncode == 0 and "error" not in (proc.stderr or "").lower():
                return True, f"Switched {connector} to {target_hz}Hz via xrandr."
            if target_hz == 120:
                # Fallback to 60Hz under xrandr
                proc60 = subprocess.run(["xrandr", "--output", connector, "--rate", "60"], capture_output=True, text=True, timeout=5)
                if proc60.returncode == 0 and "error" not in (proc60.stderr or "").lower():
                    return True, f"Display '{connector}' does not support 120Hz. Fallen back to 60Hz via xrandr."
            return False, (proc.stderr or "xrandr failed to set refresh rate").strip()
        except Exception as exc:
            return False, f"xrandr error: {exc}"

    # ------------------------------------------------------------------
    # Frame Pacing & Capper (MangoHud + DXVK / VKD3D)
    # ------------------------------------------------------------------
    def is_mangohud_installed(self) -> bool:
        return shutil.which("mangohud") is not None

    def configure_mangohud(self, fps_limit: int = 30, frametime: int = 1, vsync: int = 1) -> Tuple[bool, str]:
        """
        Updates ~/.config/MangoHud/MangoHud.conf with fps_limit, frametime, and vsync.
        Preserves other configuration options.
        """
        try:
            self.MANGOHUD_CONF.parent.mkdir(parents=True, exist_ok=True)
            lines: List[str] = []
            if self.MANGOHUD_CONF.exists():
                try:
                    lines = self.MANGOHUD_CONF.read_text(encoding="utf-8").splitlines()
                except Exception:
                    lines = []

            keys_to_set = {
                "fps_limit": str(fps_limit),
                "frametime": str(frametime),
                "vsync": str(vsync),
            }
            updated_keys = set()
            new_lines = []

            for line in lines:
                m = re.match(r"^\s*([a-zA-Z0-9_]+)\s*=\s*(.*)$", line)
                if m:
                    k = m.group(1).lower()
                    if k in keys_to_set:
                        new_lines.append(f"{k}={keys_to_set[k]}")
                        updated_keys.add(k)
                        continue
                new_lines.append(line)

            # Append any missing keys
            for k, val in keys_to_set.items():
                if k not in updated_keys:
                    new_lines.append(f"{k}={val}")

            self.MANGOHUD_CONF.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            return True, f"Configured MangoHud with fps_limit={fps_limit}"
        except Exception as exc:
            return False, f"Failed to configure MangoHud: {exc}"

    def update_environment_exports(self, enabled: bool) -> Tuple[bool, str]:
        """
        Exposes/unsets DXVK_FRAME_RATE=30 and VKD3D_FRAME_RATE=30 via:
        1. Helper environment source script (~/.config/nvidia-control-center/console_30fps_env.sh)
        2. Game launcher wrapper (~/.local/bin/console-30fps-run)
        3. Systemd environment generator (~/.config/environment.d/30-nvidia-console-mode.conf)
        4. Current python process environment
        """
        try:
            if enabled:
                # 1. Source script
                self.ENV_SCRIPT.parent.mkdir(parents=True, exist_ok=True)
                script_body = (
                    "# Auto-generated by NVIDIA Control Center - Console 30 FPS Mode\n"
                    "# Source this file in game launchers or shell profile\n"
                    "export DXVK_FRAME_RATE=30\n"
                    "export VKD3D_FRAME_RATE=30\n"
                    "export MANGOHUD=1\n"
                )
                self.ENV_SCRIPT.write_text(script_body, encoding="utf-8")

                # 2. Executable launcher wrapper
                self.WRAPPER_SCRIPT.parent.mkdir(parents=True, exist_ok=True)
                wrapper_body = (
                    "#!/bin/sh\n"
                    "# Auto-generated by NVIDIA Control Center - Console 30 FPS Game Wrapper\n"
                    "# Use as Steam Launch Option: console-30fps-run %command%\n"
                    "export DXVK_FRAME_RATE=30\n"
                    "export VKD3D_FRAME_RATE=30\n"
                    "export MANGOHUD=1\n"
                    'exec "$@"\n'
                )
                self.WRAPPER_SCRIPT.write_text(wrapper_body, encoding="utf-8")
                self.WRAPPER_SCRIPT.chmod(0o755)

                # 3. Systemd user session environment generator
                try:
                    self.SYSTEMD_ENV.parent.mkdir(parents=True, exist_ok=True)
                    self.SYSTEMD_ENV.write_text(
                        "DXVK_FRAME_RATE=30\nVKD3D_FRAME_RATE=30\n",
                        encoding="utf-8",
                    )
                except Exception:
                    pass

                # 4. In-process
                os.environ["DXVK_FRAME_RATE"] = "30"
                os.environ["VKD3D_FRAME_RATE"] = "30"
                return True, "Set DXVK_FRAME_RATE=30 & VKD3D_FRAME_RATE=30 environment exports."
            else:
                # 1. Source script
                self.ENV_SCRIPT.parent.mkdir(parents=True, exist_ok=True)
                script_body = (
                    "# Auto-generated by NVIDIA Control Center - Console 30 FPS Mode (Inactive)\n"
                    "unset DXVK_FRAME_RATE\n"
                    "unset VKD3D_FRAME_RATE\n"
                )
                self.ENV_SCRIPT.write_text(script_body, encoding="utf-8")

                # 2. Wrapper
                if self.WRAPPER_SCRIPT.exists():
                    try:
                        wrapper_body = (
                            "#!/bin/sh\n"
                            "# Auto-generated by NVIDIA Control Center (Console 30 FPS Inactive)\n"
                            'exec "$@"\n'
                        )
                        self.WRAPPER_SCRIPT.write_text(wrapper_body, encoding="utf-8")
                        self.WRAPPER_SCRIPT.chmod(0o755)
                    except Exception:
                        pass

                # 3. Systemd user session environment generator
                if self.SYSTEMD_ENV.exists():
                    try:
                        self.SYSTEMD_ENV.unlink()
                    except Exception:
                        pass

                # 4. In-process
                os.environ.pop("DXVK_FRAME_RATE", None)
                os.environ.pop("VKD3D_FRAME_RATE", None)
                return True, "Unset DXVK_FRAME_RATE & VKD3D_FRAME_RATE environment exports."
        except Exception as exc:
            return False, f"Failed to update environment exports: {exc}"

    # ------------------------------------------------------------------
    # High-Level Console Mode Controller
    # ------------------------------------------------------------------
    def enable_console_mode(self, target_rate: int = 60) -> Tuple[bool, str, List[str]]:
        """
        Enables Console 30 FPS Mode:
        1. Caches current native monitor refresh rate if not cached.
        2. Switches monitor refresh rate to target pulldown rate (60Hz or 120Hz).
        3. Configures MangoHud with fps_limit=30, frametime=1, vsync=1.
        4. Exposes DXVK_FRAME_RATE=30 and VKD3D_FRAME_RATE=30.
        5. Saves state.
        """
        warnings: List[str] = []
        state = self.load_state()

        # Query primary monitor state
        mon_state = self.get_primary_monitor_state()
        if not mon_state:
            warnings.append("Could not detect active primary display output.")
        else:
            # Cache native refresh rate and mode if not already cached
            if not state.get("cached_native_mode_id"):
                # Find maximum native refresh rate mode
                native_mode_id = mon_state.current_mode_id
                native_rate = mon_state.native_refresh_rate
                # Find highest mode matching current resolution
                for m in mon_state.available_modes:
                    if m.refresh_rate >= native_rate:
                        native_rate = m.refresh_rate
                        native_mode_id = m.mode_id

                state["cached_native_connector"] = mon_state.connector
                state["cached_native_mode_id"] = native_mode_id
                state["cached_native_rate"] = native_rate

        # 1. Switch Display Refresh
        disp_ok, disp_msg = self.switch_display_refresh(target_rate)
        if not disp_ok:
            warnings.append(disp_msg)
        elif "Fallen back to 60Hz" in disp_msg:
            target_rate = 60
            warnings.append(disp_msg)

        # 2. Check MangoHud installation
        if not self.is_mangohud_installed():
            warnings.append(
                "MangoHud is not installed in system PATH. Install 'mangohud' for complete Vulkan/DXVK flat frame pacing."
            )

        # 3. Configure MangoHud
        mh_ok, mh_msg = self.configure_mangohud(fps_limit=30, frametime=1, vsync=1)
        if not mh_ok:
            warnings.append(mh_msg)

        # 4. Update environment exports
        env_ok, env_msg = self.update_environment_exports(enabled=True)
        if not env_ok:
            warnings.append(env_msg)

        # 5. Save state
        state["enabled"] = True
        state["target_rate"] = target_rate
        self.save_state(state)

        pulldown_desc = "2:2 pulldown" if target_rate == 60 else "4:1 pulldown"
        success = disp_ok or mh_ok
        summary = (
            f"Console 30 FPS Mode engaged @ {target_rate}Hz ({pulldown_desc}) with 33.3ms pacing."
            if success
            else "Failed to engage Console 30 FPS Mode."
        )
        return success, summary, warnings

    def disable_console_mode(self) -> Tuple[bool, str, List[str]]:
        """
        Disables Console 30 FPS Mode:
        1. Restores monitor refresh rate to native cached rate.
        2. Restores fps_limit=0 in MangoHud.
        3. Unsets DXVK and VKD3D frame rate exports.
        4. Saves state.
        """
        warnings: List[str] = []
        state = self.load_state()

        cached_connector = state.get("cached_native_connector")
        cached_mode_id = state.get("cached_native_mode_id")
        cached_rate = state.get("cached_native_rate") or 100

        # 1. Revert display refresh
        disp_ok = True
        disp_msg = ""
        if cached_mode_id or cached_rate:
            disp_ok, disp_msg = self.switch_display_refresh(
                int(round(cached_rate)),
                target_mode_id=cached_mode_id,
            )
            if not disp_ok:
                warnings.append(disp_msg)

        # 2. Restore MangoHud fps_limit=0
        mh_ok, mh_msg = self.configure_mangohud(fps_limit=0, frametime=1, vsync=1)
        if not mh_ok:
            warnings.append(mh_msg)

        # 3. Unset environment exports
        env_ok, env_msg = self.update_environment_exports(enabled=False)
        if not env_ok:
            warnings.append(env_msg)

        # 4. Update state (clear cached mode so next enable captures fresh native state)
        state["enabled"] = False
        state["cached_native_mode_id"] = None
        state["cached_native_rate"] = None
        self.save_state(state)

        summary = f"Restored native high refresh rate ({cached_rate:.0f}Hz) and unlocked frame cap."
        return True, summary, warnings

    def set_target_pulldown_rate(self, new_rate: int) -> Tuple[bool, str, List[str]]:
        """Changes pulldown rate (60Hz or 120Hz) while active."""
        state = self.load_state()
        state["target_rate"] = new_rate
        self.save_state(state)

        if state.get("enabled", False):
            # Re-apply display refresh rate
            disp_ok, disp_msg = self.switch_display_refresh(new_rate)
            warnings = []
            if not disp_ok:
                warnings.append(disp_msg)
            elif "Fallen back to 60Hz" in disp_msg:
                state["target_rate"] = 60
                self.save_state(state)
                warnings.append(disp_msg)
            return disp_ok, f"Switched target pulldown rate to {state['target_rate']}Hz.", warnings
        return True, f"Target pulldown rate set to {new_rate}Hz.", []

    def get_status_info(self) -> dict:
        """Returns comprehensive status dictionary for UI rendering."""
        state = self.load_state()
        mon = self.get_primary_monitor_state()
        conn_name = mon.connector if mon else "Unknown"
        cur_rate = mon.current_refresh_rate if mon else 60.0
        native_rate = (
            state.get("cached_native_rate")
            or (mon.native_refresh_rate if mon else 60.0)
        )

        return {
            "enabled": bool(state.get("enabled", False)),
            "target_rate": int(state.get("target_rate", 60)),
            "primary_connector": conn_name,
            "monitor_name": mon.monitor_name if mon else conn_name,
            "current_rate": cur_rate,
            "native_rate": native_rate,
            "capper_active": bool(state.get("enabled", False)),
            "mangohud_installed": self.is_mangohud_installed(),
            "session_type": mon.session_type if mon else self.detect_session_type(),
        }
