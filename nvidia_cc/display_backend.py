"""
Display & Color Management Backend for CachyOS (KDE Plasma Wayland + X11/nvidia-settings + DRM EDID).
Supports KWin Wayland DRM hardware color pipeline (ICC profiles, WCG, HDR, Brightness, VRR)
and X11 nvidia-settings fallback.
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import struct
import subprocess
from typing import List, Tuple


@dataclass
class DisplayOutput:
    connector: str          # e.g., "DP-3"
    drm_card: str           # e.g., "card2"
    monitor_name: str       # e.g., "24B15H2"
    connected: bool = True
    enabled: bool = True
    current_mode: str = "1920x1080@60"
    available_modes: List[str] = field(default_factory=lambda: ["1920x1080@60"])
    vrr_policy: str = "automatic"   # never, always, automatic
    hdr_enabled: bool = False
    wcg_enabled: bool = False
    rgb_range: str = "automatic"    # automatic, full, limited
    scale: float = 1.0
    brightness: int = 100
    vibrance: int = 0


class DisplayBackend:
    """Queries DRM sysfs, KDE kscreen-doctor, and nvidia-settings."""

    def __init__(self):
        self.config_dir = Path.home() / ".config" / "nvidia-control-center"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.display_cfg_file = self.config_dir / "display_config.json"

    def load_saved_config(self) -> dict:
        if self.display_cfg_file.exists():
            try:
                return json.loads(self.display_cfg_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def save_config(self, cfg: dict):
        try:
            self.display_cfg_file.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _parse_edid_name(edid_path: Path) -> str:
        try:
            if not edid_path.exists():
                return ""
            edid = edid_path.read_bytes()
            if len(edid) < 128:
                return ""
            for i in range(54, 126, 18):
                desc = edid[i : i + 18]
                if desc[:3] == b"\x00\x00\x00" and desc[3] == 0xFC:
                    return desc[5:].decode("ascii", errors="ignore").strip()
        except Exception:
            pass
        return ""

    def get_displays(self) -> List[DisplayOutput]:
        outputs: List[DisplayOutput] = []
        saved_cfg = self.load_saved_config()

        # 1. Try kscreen-doctor -j first (works inside active KDE Wayland session)
        kscreen_map = {}
        try:
            raw = subprocess.check_output(
                ["kscreen-doctor", "-j"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2,
            )
            # Strip ANSI escape codes if any
            clean = re.sub(r"\x1b\[[0-9;]*m", "", raw)
            data = json.loads(clean)
            for out in data.get("outputs", []):
                name = out.get("name", "")
                if not name:
                    continue
                modes_list = []
                cur_mode_id = out.get("currentModeId")
                cur_mode_str = "1920x1080@60"
                for m in out.get("modes", []):
                    size = m.get("size", {})
                    w = size.get("width", 1920)
                    h = size.get("height", 1080)
                    rate = int(round(m.get("refreshRate", 60.0)))
                    m_str = f"{w}x{h}@{rate}"
                    if m_str not in modes_list:
                        modes_list.append(m_str)
                    if m.get("id") == cur_mode_id:
                        cur_mode_str = m_str
                vrr_val = out.get("vrrPolicy", 2)
                vrr_str = {0: "never", 1: "always", 2: "automatic"}.get(vrr_val, "automatic")
                rgb_val = out.get("rgbRange", 0)
                rgb_str = {0: "automatic", 1: "full", 2: "limited"}.get(rgb_val, "automatic")
                bright_f = float(out.get("brightness", 1.0))
                kscreen_map[name] = {
                    "connected": bool(out.get("connected", False)),
                    "enabled": bool(out.get("enabled", False)),
                    "current_mode": cur_mode_str,
                    "modes": modes_list or [cur_mode_str],
                    "vrr_policy": vrr_str,
                    "hdr": bool(out.get("hdr", False)),
                    "wcg": bool(out.get("wcg", False)),
                    "rgb_range": rgb_str,
                    "scale": float(out.get("scale", 1.0)),
                    "brightness": int(round(bright_f * 100)),
                }
        except Exception:
            pass

        # 2. Scan /sys/class/drm/card*-* for physical connectors and EDID names
        drm_root = Path("/sys/class/drm")
        for conn_dir in sorted(drm_root.glob("card*-*")):
            name_parts = conn_dir.name.split("-", 1)
            if len(name_parts) != 2:
                continue
            card_name, connector = name_parts
            status_file = conn_dir / "status"
            status = "disconnected"
            if status_file.exists():
                try:
                    status = status_file.read_text(encoding="utf-8").strip()
                except Exception:
                    pass
            is_connected = status == "connected"
            mon_name = self._parse_edid_name(conn_dir / "edid") or connector

            modes = []
            modes_file = conn_dir / "modes"
            if modes_file.exists():
                try:
                    for line in modes_file.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if line and line not in modes:
                            modes.append(line)
                except Exception:
                    pass

            ks = kscreen_map.get(connector, {})
            saved_disp = saved_cfg.get(connector, {})
            if is_connected or ks.get("connected"):
                avail_modes = ks.get("modes") or [f"{m}@60" for m in modes[:12]] or ["1920x1080@60"]
                cur_mode = ks.get("current_mode") or avail_modes[0]
                outputs.append(
                    DisplayOutput(
                        connector=connector,
                        drm_card=card_name,
                        monitor_name=mon_name,
                        connected=True,
                        enabled=ks.get("enabled", True),
                        current_mode=cur_mode,
                        available_modes=avail_modes,
                        vrr_policy=ks.get("vrr_policy", "automatic"),
                        hdr_enabled=ks.get("hdr", False),
                        wcg_enabled=ks.get("wcg", False),
                        rgb_range=ks.get("rgb_range", "automatic"),
                        scale=ks.get("scale", 1.0),
                        brightness=ks.get("brightness", saved_disp.get("brightness", 100)),
                        vibrance=int(saved_disp.get("vibrance", 0)),
                    )
                )

        if not outputs:
            outputs.append(
                DisplayOutput(
                    connector="DP-3",
                    drm_card="card2",
                    monitor_name="Primary Display",
                    connected=True,
                    enabled=True,
                )
            )

        return outputs

    @staticmethod
    def _s15fixed16(val: float) -> bytes:
        return struct.pack(">i", int(round(val * 65536.0)))

    @classmethod
    def _build_vibrance_icc(cls, vibrance: int, out_path: Path) -> Path:
        """Generates a valid ICC v2.4 Display Profile with saturation-adjusted XYZ primaries."""
        # vibrance is -1024 (grayscale) to +1023 (max vibrance).
        # In KWin Wayland's color management pipeline, source sRGB is transformed to display RGB
        # via M_display^-1 * M_srgb. Shrinking the profile's primaries toward D50 white point
        # causes M_display^-1 to boost chroma/saturation on hardware DRM planes; expanding them
        # reduces chroma/saturation.
        norm = max(-1.0, min(1.0, vibrance / 1024.0))
        # Factor < 1.0 boosts saturation; Factor > 1.0 desaturates
        sat_scale = 1.0 / (1.0 + 0.65 * norm) if norm >= 0 else 1.0 + abs(norm) * 3.0

        # Standard D50-adapted sRGB primaries
        wp_x, wp_y, wp_z = 0.9642029, 1.0000000, 0.8249054
        r0 = (0.4360747, 0.2225045, 0.0139322)
        g0 = (0.3850649, 0.7168786, 0.0971045)
        b0 = (0.1430804, 0.0606169, 0.7141733)

        def adjust_primary(p, lum_weight):
            # Neutral axis contribution for this primary has XYZ proportional to D50 white point * lum_weight
            nx, ny, nz = wp_x * lum_weight, wp_y * lum_weight, wp_z * lum_weight
            return (
                nx + (p[0] - nx) * sat_scale,
                nx * 0.0 + ny + (p[1] - ny) * sat_scale,
                nz + (p[2] - nz) * sat_scale,
            )

        rx, ry, rz = adjust_primary(r0, r0[1])
        gx, gy, gz = adjust_primary(g0, g0[1])
        bx, by, bz = adjust_primary(b0, b0[1])

        def make_xyz_tag(x: float, y: float, z: float) -> bytes:
            return b"XYZ \x00\x00\x00\x00" + cls._s15fixed16(x) + cls._s15fixed16(y) + cls._s15fixed16(z)

        def make_curv_tag(gamma: float = 2.2) -> bytes:
            g_u8fixed8 = int(round(gamma * 256.0))
            return b"curv\x00\x00\x00\x00" + struct.pack(">I", 1) + struct.pack(">H", g_u8fixed8) + b"\x00\x00"

        def make_desc_tag(text: str) -> bytes:
            ascii_bytes = text.encode("ascii", errors="ignore") + b"\x00"
            body = (
                b"desc\x00\x00\x00\x00"
                + struct.pack(">I", len(ascii_bytes))
                + ascii_bytes
                + struct.pack(">II", 0, 0)
                + struct.pack(">HB", 0, 0)
                + b"\x00" * 67
            )
            while len(body) % 4 != 0:
                body += b"\x00"
            return body

        def make_text_tag(text: str) -> bytes:
            b_txt = b"text\x00\x00\x00\x00" + text.encode("ascii", errors="ignore") + b"\x00"
            while len(b_txt) % 4 != 0:
                b_txt += b"\x00"
            return b_txt

        tags = [
            (b"desc", make_desc_tag(f"NVIDIA Control Center Vibrance ({vibrance:+d})")),
            (b"cprt", make_text_tag("NVIDIA Control Center CachyOS")),
            (b"wtpt", make_xyz_tag(wp_x, wp_y, wp_z)),
            (b"rXYZ", make_xyz_tag(rx, ry, rz)),
            (b"gXYZ", make_xyz_tag(gx, gy, gz)),
            (b"bXYZ", make_xyz_tag(bx, by, bz)),
            (b"rTRC", make_curv_tag(2.2)),
            (b"gTRC", make_curv_tag(2.2)),
            (b"bTRC", make_curv_tag(2.2)),
        ]

        tag_count = len(tags)
        offset = 128 + 4 + tag_count * 12
        tag_table = struct.pack(">I", tag_count)
        data_blob = b""
        for sig, payload in tags:
            size = len(payload)
            tag_table += sig + struct.pack(">II", offset, size)
            data_blob += payload
            offset += size

        total_size = offset
        header = bytearray(128)
        struct.pack_into(">I", header, 0, total_size)
        header[4:8] = b"lcm2"
        struct.pack_into(">I", header, 8, 0x02400000)  # ICC v2.4
        header[12:16] = b"mntr"
        header[16:20] = b"RGB "
        header[20:24] = b"XYZ "
        struct.pack_into(">HHHHHH", header, 24, 2026, 1, 1, 0, 0, 0)
        header[36:40] = b"acsp"
        header[40:44] = b"APPL"
        struct.pack_into(">i", header, 68, int(round(wp_x * 65536.0)))
        struct.pack_into(">i", header, 72, int(round(wp_y * 65536.0)))
        struct.pack_into(">i", header, 76, int(round(wp_z * 65536.0)))

        out_path.write_bytes(bytes(header) + tag_table + data_blob)
        return out_path

    def apply_kscreen_settings(
        self,
        connector: str,
        mode: str,
        vrr_policy: str,
        hdr_enabled: bool,
        rgb_range: str,
        scale: float,
        brightness: int = 100,
        wcg_enabled: bool = False,
    ) -> Tuple[bool, str]:
        cmds = [
            f"output.{connector}.mode.{mode}",
            f"output.{connector}.vrrpolicy.{vrr_policy}",
            f"output.{connector}.hdr.{'enable' if hdr_enabled else 'disable'}",
            f"output.{connector}.wcg.{'enable' if (wcg_enabled or hdr_enabled) else 'disable'}",
            f"output.{connector}.rgbrange.{rgb_range}",
            f"output.{connector}.scale.{scale:.2f}",
            f"output.{connector}.brightness.{max(10, min(100, int(brightness)))}",
        ]
        try:
            proc = subprocess.run(
                ["kscreen-doctor"] + cmds,
                capture_output=True,
                text=True,
                timeout=5,
            )
            cfg = self.load_saved_config()
            cfg.setdefault(connector, {})["brightness"] = int(brightness)
            self.save_config(cfg)
            if proc.returncode == 0:
                return True, f"Applied display settings to {connector} via KWin/KScreen."
            return False, (proc.stderr or proc.stdout or "kscreen-doctor returned an error").strip()
        except Exception as exc:
            return False, str(exc)

    def apply_vibrance(self, vibrance: int, connector: str = "DP-3") -> Tuple[bool, str]:
        """Applies Digital Vibrance via KWin Wayland DRM ICC Color Pipeline (or X11 nvidia-settings fallback)."""
        vib = int(vibrance)
        cfg = self.load_saved_config()
        cfg.setdefault(connector, {})["vibrance"] = vib
        self.save_config(cfg)

        # 1. Apply on KDE Wayland via kscreen-doctor ICC Color Pipeline
        try:
            if vib == 0:
                proc = subprocess.run(
                    [
                        "kscreen-doctor",
                        f"output.{connector}.iccprofile.",
                        f"output.{connector}.colorProfileSource.sRGB",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if proc.returncode == 0:
                    return True, f"Reset Digital Vibrance on {connector} to standard sRGB."
            else:
                # Clear stale ICC caches and write fresh profile with unique vibrance value
                for old_icc in self.config_dir.glob("vibrance_*.icc"):
                    try:
                        old_icc.unlink()
                    except Exception:
                        pass
                icc_path = self.config_dir / f"vibrance_{vib}.icc"
                self._build_vibrance_icc(vib, icc_path)
                proc = subprocess.run(
                    [
                        "kscreen-doctor",
                        f"output.{connector}.iccprofile.{icc_path}",
                        f"output.{connector}.colorProfileSource.ICC",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if proc.returncode == 0:
                    return True, f"Applied Digital Vibrance ({vib:+d}) on {connector} via DRM Color Pipeline."
        except Exception:
            pass

        # 2. Fallback to nvidia-settings for X11 sessions
        cmds = [
            "nvidia-settings",
            "-a",
            f"DigitalVibrance={vib}",
        ]
        try:
            proc = subprocess.run(cmds, capture_output=True, text=True, timeout=5)
            if proc.returncode == 0 and "ERROR" not in (proc.stderr or ""):
                return True, f"Applied Digital Vibrance ({vib:+d})."
            return (
                False,
                "Could not apply Digital Vibrance via KScreen or nvidia-settings.",
            )
        except Exception as exc:
            return False, str(exc)
