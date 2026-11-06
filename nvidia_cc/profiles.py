"""
Game & Application Graphics Profile Manager for NVIDIA Control Center.
Provides Windows NVIDIA App–equivalent per-app and global driver overrides
for OpenGL, Vulkan, DXVK-NVAPI, DLSS Super Resolution Upscaling, DLAA,
Ray Reconstruction, Frame Generation, OptiScaler, VRR/G-SYNC, and MangoHud on Linux.
"""

from dataclasses import asdict, dataclass, fields
import json
import lzma
from pathlib import Path
import re
import shutil
import subprocess
import threading
from typing import Dict, List, Optional, Set, Tuple


SKIP_APP_IDS = {
    "228980",   # Steamworks Common Redistributables
    "1070560",  # Steam Linux Runtime
    "1391110",  # Steam Linux Runtime - Soldier
    "1628350",  # Steam Linux Runtime - Sniper
    "1493710",  # Proton Experimental
    "2805730",  # Proton 9.0
    "2348590",  # Proton 8.0
    "4183110",  # Steam Linux Runtime 4.0
    "4628710",  # Proton 11.0
    "1826330",  # Proton EasyAntiCheat Runtime
    "1161040",  # Proton BattlEye Runtime
}

KNOWN_STEAM_APP_NAMES = {
    "227300": "Euro Truck Simulator 2",
    "1245620": "ELDEN RING",
    "1501750": "Lords of the Fallen",
}

# All environment variable keys managed by NVIDIA Control Center (including legacy keys for cleanup)
MANAGED_ENV_KEYS: Tuple[str, ...] = (
    "__NV_PRIME_RENDER_OFFLOAD",
    "__GLX_VENDOR_LIBRARY_NAME",
    "__VK_LAYER_NV_optimus",
    "PROTON_ENABLE_NGX_UPDATER",
    "PROTON_DLSS_UPGRADE",
    "PROTON_FSR4_UPGRADE",
    "DXVK_NVAPI_DRS_SETTINGS",
    "DXVK_NVAPI_DRS_NGX_DLSS_SR_OVERRIDE",
    "DXVK_NVAPI_DRS_NGX_DLSS_SR_OVERRIDE_RENDER_PRESET_SELECTION",
    "DXVK_NVAPI_DRS_NGX_DLSS_SR_MODE",
    "DXVK_NVAPI_DRS_NGX_DLSS_SR_OVERRIDE_SCALING_RATIO",
    "DXVK_NVAPI_DRS_NGX_DLSS_RR_OVERRIDE",
    "DXVK_NVAPI_DRS_NGX_DLSS_RR_OVERRIDE_RENDER_PRESET_SELECTION",
    "DXVK_NVAPI_DRS_NGX_DLSS_FG_OVERRIDE",
    "DXVK_NVAPI_DRS_NGX_DLSSG_MULTI_FRAME_COUNT",
    "DXVK_NVAPI_DRS_NGX_DLAA_OVERRIDE",
    "PROTON_USE_OPTISCALER",
    "PROTON_OPTISCALER_CONFIG",
    "WINEDLLOVERRIDES",
    "ENABLE_VKBASALT",
    "VKBASALT_CONFIG",
    "PROTON_DLSS_INDICATOR",
    "NGX_DLSS_INDICATOR",
    "DXVK_NVAPI_SET_NGX_DEBUG_OPTIONS",
    "__GL_SYNC_TO_VBLANK",
    "__GL_VRR_ALLOWED",
    "__GL_MaxFramesAllowed",
    "__GL_ImageSettings",
    "__GL_THREADED_OPTIMIZATIONS",
    "__GL_SHADER_DISK_CACHE",
    "__GL_SHADER_DISK_CACHE_SKIP_CLEANUP",
    "PROTON_ENABLE_WAYLAND",
    "PROTON_ENABLE_HDR",
    "MANGOHUD",
    "MANGOHUD_CONFIG",
    "DXVK_FRAME_RATE",
    "VKD3D_FRAME_RATE",
)


@dataclass
class GameProfile:
    app_id: str
    name: str
    install_dir: str = ""
    custom_override: bool = False
    # DLSS Super Resolution (Upscaling) & NGX
    dlss_override: bool = False
    dlss_upgrade: bool = True
    dlss_sr_mode: str = "default"  # default, dlaa, ultra_quality, quality, balanced, performance, ultra_performance, custom
    dlss_scale_ratio: int = 67     # 33 to 100 (%)
    dlss_preset: str = "default"   # default, render_preset_latest, preset_k, preset_j, preset_f, preset_e
    dlss_rr_override: bool = False
    optiscaler_fg_enabled: bool = False
    optiscaler_fg_mode: str = "off"      # off, default, on, mfg_3x, mfg_4x
    smooth_frametimes: bool = False
    optiscaler_enable: bool = False
    nis_sharpening: int = 0        # 0 to 100 (%)
    dlss_indicator: bool = False
    # Frame Rate & Sync
    vsync_mode: str = "app"  # app, on, off
    vrr_gsync: bool = True
    low_latency_mode: bool = False
    fps_limit: int = 0  # 0 = Unlimited
    # Driver & Shader Optimizations
    image_quality: str = "quality"  # high_quality, quality, performance, high_performance
    threaded_optimization: bool = True
    unlimited_shader_cache: bool = True
    prime_offload: bool = True
    # Proton / Wayland / Overlay
    proton_wayland: bool = False
    proton_hdr: bool = False
    mangohud: bool = False

    @property
    def dlss_fg_enabled(self) -> bool:
        return self.optiscaler_fg_enabled

    @dlss_fg_enabled.setter
    def dlss_fg_enabled(self, val: bool):
        self.optiscaler_fg_enabled = bool(val)

    @property
    def dlss_fg_mode(self) -> str:
        return self.optiscaler_fg_mode

    @dlss_fg_mode.setter
    def dlss_fg_mode(self, val: str):
        self.optiscaler_fg_mode = str(val)


# DLSS Super Resolution Upscaling Modes -> (Label, DRS Mode Value, Default Scale %)
DLSS_SR_MODE_MAP: Dict[str, Tuple[str, str, int]] = {
    "default": ("Default (Use In-Game Quality Setting)", "default", 67),
    "dlaa": ("DLAA — 100% Native Resolution (Anti-Aliasing)", "dlaa", 100),
    "ultra_quality": ("Ultra Quality — 77% Render Scale (1.3x Upscale)", "custom", 77),
    "quality": ("Quality — 67% Render Scale (1.5x Upscale)", "quality", 67),
    "balanced": ("Balanced — 58% Render Scale (1.7x Upscale)", "balanced", 58),
    "performance": ("Performance — 50% Render Scale (2.0x Upscale)", "performance", 50),
    "ultra_performance": ("Ultra Performance — 33% Render Scale (3.0x Upscale)", "ultra_performance", 33),
    "custom": ("Custom Resolution Scale % (33% – 100%)", "custom", 67),
}

# DLSS Render Presets -> (Label, DXVK-NVAPI DRS Preset String)
DLSS_PRESET_MAP: Dict[str, Tuple[str, str]] = {
    "default": ("Default (App Controlled)", "default"),
    "render_preset_latest": ("Latest Preset (Auto Transformer)", "render_preset_latest"),
    "preset_k": ("Preset K (Latest Transformer — Best Quality)", "render_preset_k"),
    "preset_j": ("Preset J (Transformer Gen 2 — Fast Motion)", "render_preset_j"),
    "preset_f": ("Preset F (CNN — Ultra Quality / DLAA)", "render_preset_f"),
    "preset_e": ("Preset E (CNN — Balanced Motion)", "render_preset_e"),
}

# OptiScaler numeric preset mapping for [DLSS] RenderPreset*
OPTISCALER_PRESET_INT_MAP: Dict[str, str] = {
    "default": "auto",
    "render_preset_latest": "11",  # Preset K (Latest Transformer)
    "preset_k": "11",
    "preset_j": "10",
    "preset_f": "6",
    "preset_e": "5",
}

# OptiScaler Frame Generation Modes -> (Label, FG Override, Multi-Frame Count)
OPTISCALER_FG_MODE_MAP: Dict[str, Tuple[str, str, int]] = {
    "off": ("Disabled — Force Off", "off", 0),
    "default": ("Default (In-Game / App Controlled)", "default", 1),
    "on": ("OptiScaler Frame Gen — Standard 2x", "on", 1),
    "mfg_3x": ("OptiScaler Multi-Frame Gen — 3x Mode", "on", 2),
    "mfg_4x": ("OptiScaler Multi-Frame Gen — 4x Mode", "on", 3),
}
DLSS_FG_MODE_MAP = OPTISCALER_FG_MODE_MAP

IMAGE_QUALITY_MAP = {
    "high_quality": ("High Quality", "0"),
    "quality": ("Quality (Default)", "1"),
    "performance": ("Performance", "2"),
    "high_performance": ("High Performance", "3"),
}


class ProfileManager:
    def __init__(self):
        self.config_dir = Path.home() / ".config" / "nvidia-control-center"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.dlss_cache_dir = self.config_dir / "dlss_cache"
        self.profiles_file = self.config_dir / "game_profiles.json"
        self.env_d_file = Path.home() / ".config" / "environment.d" / "90-nvidia-control-center.conf"
        self.profiles: Dict[str, GameProfile] = {}
        self._steamapps_cache: Optional[List[Path]] = None
        self._systemd_sync_lock = threading.Lock()
        self._load()
        self.discover_steam_games()
        self.clean_legacy_steam_launch_options()
        # Ensure all Proton prefixes, game directories, and global environment are synced on startup
        self.apply_profile_to_proton(self.profiles["__global__"])

    def _load(self):
        valid_keys = {f.name for f in fields(GameProfile)}
        self.profiles["__global__"] = GameProfile(
            app_id="__global__",
            name="Global Driver Settings (All Games)",
            vrr_gsync=True,
            threaded_optimization=True,
            unlimited_shader_cache=True,
            prime_offload=True,
        )
        if self.profiles_file.exists():
            try:
                raw = json.loads(self.profiles_file.read_text(encoding="utf-8"))
                for app_id, pdata in raw.items():
                    if app_id in SKIP_APP_IDS:
                        continue
                    filtered = {k: v for k, v in pdata.items() if k in valid_keys}
                    prof_obj = GameProfile(**filtered)
                    if "optiscaler_fg_enabled" not in filtered:
                        if "dlss_fg_enabled" in pdata:
                            prof_obj.optiscaler_fg_enabled = bool(pdata["dlss_fg_enabled"])
                        elif "dlss_fg_mode" in pdata:
                            prof_obj.optiscaler_fg_enabled = pdata["dlss_fg_mode"] in ("on", "mfg_3x", "mfg_4x")
                    if "optiscaler_fg_mode" not in filtered:
                        if "dlss_fg_mode" in pdata:
                            prof_obj.optiscaler_fg_mode = pdata["dlss_fg_mode"]
                    self.profiles[app_id] = prof_obj
            except Exception:
                pass

    def save(self):
        out = {app_id: asdict(prof) for app_id, prof in self.profiles.items()}
        self.profiles_file.write_text(json.dumps(out, indent=2), encoding="utf-8")

    def _scan_steam_libraries(self) -> Tuple[List[Path], Dict[str, str]]:
        """Single unified scan of Steam library roots, steamapps folders, and VDF app mappings."""
        steam_roots = [
            Path.home() / ".local" / "share" / "Steam",
            Path.home() / ".steam" / "steam",
        ]
        steamapps_dirs: Set[Path] = set()
        vdf_app_ids: Dict[str, str] = {}

        for root in steam_roots:
            sa = root / "steamapps"
            if sa.exists():
                steamapps_dirs.add(sa.resolve())
                vdf = sa / "libraryfolders.vdf"
                if vdf.exists():
                    try:
                        text = vdf.read_text(encoding="utf-8", errors="replace")
                        cur_path = ""
                        for line in text.splitlines():
                            pm = re.search(r'"path"\s+"([^"]+)"', line)
                            if pm:
                                cur_path = pm.group(1)
                                ext_sa = Path(cur_path) / "steamapps"
                                if ext_sa.exists():
                                    steamapps_dirs.add(ext_sa.resolve())
                            am = re.search(r'^\s*"(\d+)"\s+"\d+"', line)
                            if am:
                                aid = am.group(1)
                                if aid not in SKIP_APP_IDS:
                                    vdf_app_ids[aid] = cur_path
                    except Exception:
                        pass
        return sorted(steamapps_dirs), vdf_app_ids

    def get_steamapps_dirs(self) -> List[Path]:
        if self._steamapps_cache is None:
            self._steamapps_cache, _ = self._scan_steam_libraries()
        return self._steamapps_cache

    def discover_steam_games(self) -> List[GameProfile]:
        steamapps_dirs, vdf_app_ids = self._scan_steam_libraries()
        self._steamapps_cache = steamapps_dirs

        changed = False
        for sa_dir in steamapps_dirs:
            for acf in sorted(sa_dir.glob("appmanifest_*.acf")):
                try:
                    content = acf.read_text(encoding="utf-8", errors="replace")
                    appid_m = re.search(r'"appid"\s+"(\d+)"', content)
                    name_m = re.search(r'"name"\s+"([^"]+)"', content)
                    dir_m = re.search(r'"installdir"\s+"([^"]+)"', content)
                    if not appid_m or not name_m:
                        continue
                    appid = appid_m.group(1)
                    name = name_m.group(1)
                    if appid in SKIP_APP_IDS or "Proton" in name or "Steam Linux Runtime" in name:
                        continue
                    install_dir = str(sa_dir / "common" / (dir_m.group(1) if dir_m else name))
                    if appid not in self.profiles:
                        self.profiles[appid] = self._new_game_from_global(appid, name, install_dir)
                        changed = True
                    else:
                        if self.profiles[appid].name.startswith("Steam App "):
                            self.profiles[appid].name = name
                            changed = True
                        if self.profiles[appid].install_dir != install_dir and Path(install_dir).exists():
                            self.profiles[appid].install_dir = install_dir
                            changed = True
                except Exception:
                    continue

        for aid, lib_path in vdf_app_ids.items():
            if aid in KNOWN_STEAM_APP_NAMES:
                game_name = KNOWN_STEAM_APP_NAMES[aid]
                candidate_dir = Path(lib_path) / "steamapps" / "common" / game_name
                install_dir_str = str(candidate_dir) if candidate_dir.exists() else f"{lib_path}/steamapps/common/{game_name}"
                if aid not in self.profiles:
                    self.profiles[aid] = self._new_game_from_global(aid, game_name, install_dir_str)
                    changed = True
                elif self.profiles[aid].install_dir.endswith("/steamapps/common") or not self.profiles[aid].install_dir:
                    self.profiles[aid].install_dir = install_dir_str
                    changed = True

        if changed:
            self.save()
        return self.list_profiles()

    def _new_game_from_global(self, app_id: str, name: str, install_dir: str) -> GameProfile:
        g = self.profiles.get("__global__")
        if g:
            data = asdict(g)
            data["app_id"] = app_id
            data["name"] = name
            data["install_dir"] = install_dir
            data["custom_override"] = False
            return GameProfile(**data)
        return GameProfile(app_id=app_id, name=name, install_dir=install_dir)

    def reset_profile_to_defaults(self, profile: GameProfile) -> GameProfile:
        """Resets __global__ to factory defaults, or resets a game profile to follow __global__."""
        if profile.app_id == "__global__":
            fresh = GameProfile(
                app_id="__global__",
                name="Global Driver Settings (All Games)",
                vrr_gsync=True,
                threaded_optimization=True,
                unlimited_shader_cache=True,
                prime_offload=True,
            )
            self.profiles["__global__"] = fresh
            return fresh
        else:
            fresh = self._new_game_from_global(profile.app_id, profile.name, profile.install_dir)
            self.profiles[profile.app_id] = fresh
            return fresh

    def list_profiles(self) -> List[GameProfile]:
        global_p = self.profiles.get("__global__")
        others = [p for k, p in self.profiles.items() if k != "__global__"]
        others.sort(key=lambda p: p.name.lower())
        return ([global_p] if global_p else []) + others

    def add_custom_profile(self, name: str, executable_path: str = "") -> GameProfile:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "custom-app"
        app_id = f"custom-{slug}"
        prof = self._new_game_from_global(app_id, name, executable_path)
        prof.custom_override = True
        self.profiles[app_id] = prof
        self.save()
        return prof

    def build_dlss_env_vars(self, profile: GameProfile) -> Dict[str, str]:
        """Builds non-redundant DLSS Upscaling, DLAA, Ray Reconstruction, Frame Gen & OptiScaler env vars."""
        env: Dict[str, str] = {}
        drs_parts: List[str] = []

        # Always prevent Proton-CachyOS from attempting AMD FSR4 DLL copies on NVIDIA GPUs
        env["PROTON_FSR4_UPGRADE"] = "0"

        if profile.dlss_override:
            env["PROTON_ENABLE_NGX_UPDATER"] = "1"
            if profile.dlss_upgrade:
                env["PROTON_DLSS_UPGRADE"] = "1"

            drs_parts.append("ngx_dlss_sr_override=on")

            # Render Preset Selection
            preset_val = DLSS_PRESET_MAP.get(profile.dlss_preset, ("", "render_preset_latest"))[1]
            if preset_val == "default":
                preset_val = "render_preset_latest"
            drs_parts.append(f"ngx_dlss_sr_override_render_preset_selection={preset_val}")

            # Upscaling Quality Mode & Scaling Ratio
            sr_mode = profile.dlss_sr_mode
            ratio = max(33, min(100, int(profile.dlss_scale_ratio)))

            if sr_mode != "default":
                drs_parts.append("ngx_dlss_override_optimal_settings=perf_to_9x")

            if sr_mode == "dlaa":
                drs_parts.append("ngx_dlaa_override=dlaa_on")
                drs_parts.append("ngx_dlss_sr_mode=dlaa")
                drs_parts.append("ngx_dlss_sr_override_scaling_ratio=100")
            elif sr_mode == "ultra_quality":
                drs_parts.append("ngx_dlss_sr_mode=custom")
                drs_parts.append("ngx_dlss_sr_override_scaling_ratio=77")
            elif sr_mode in ("quality", "balanced", "performance", "ultra_performance"):
                mode_info = DLSS_SR_MODE_MAP[sr_mode]
                drs_parts.append(f"ngx_dlss_sr_mode={mode_info[1]}")
                drs_parts.append(f"ngx_dlss_sr_override_scaling_ratio={mode_info[2]}")
            elif sr_mode == "custom":
                drs_parts.append("ngx_dlss_sr_mode=custom")
                drs_parts.append(f"ngx_dlss_sr_override_scaling_ratio={ratio}")

        # Ray Reconstruction Override
        if profile.dlss_rr_override:
            preset_val = DLSS_PRESET_MAP.get(profile.dlss_preset, ("", "render_preset_latest"))[1]
            if preset_val == "default":
                preset_val = "render_preset_latest"
            drs_parts.append("ngx_dlss_rr_override=on")
            drs_parts.append(f"ngx_dlss_rr_override_render_preset_selection={preset_val}")

        if drs_parts:
            env["DXVK_NVAPI_DRS_SETTINGS"] = ",".join(drs_parts)

        # OptiScaler Universal Frame Generation & Upscaler Injection
        fg_active = bool(profile.optiscaler_fg_enabled and profile.optiscaler_fg_mode != "off")
        use_optiscaler = profile.optiscaler_enable or fg_active
        if use_optiscaler:
            env["PROTON_USE_OPTISCALER"] = "1"
            env["WINEDLLOVERRIDES"] = "dxgi=n,b"

            interp_count = "2" if profile.optiscaler_fg_mode == "mfg_3x" else ("3" if profile.optiscaler_fg_mode == "mfg_4x" else "1")
            fg_enabled_str = "true" if fg_active else "false"
            fg_input_str = "dlssg" if fg_active else "nofg"
            fg_output_str = "fsrfg" if fg_active else "nofg"

            cfg_parts = [
                f"FrameGen.Enabled={fg_enabled_str}",
                f"FrameGen.FGInput={fg_input_str}",
                f"FrameGen.FGOutput={fg_output_str}",
                "FSRFG.AllowAsync=true",
                f"XeFG.InterpolationCount={interp_count}",
                "Spoofing.StreamlineSpoofing=true",
                "Spoofing.Dxgi=true",
                "Spoofing.SpoofHAGS=true",
                "Spoofing.SpoofedGPUName=NVIDIA GeForce RTX 4090",
                "Spoofing.SpoofedDeviceId=0x2684",
                "Spoofing.SpoofedVendorId=0x10de",
                "Upscalers.Dx11Upscaler=dlss",
                "Upscalers.Dx12Upscaler=dlss",
                "Upscalers.VulkanUpscaler=dlss",
                "DLSS.Enabled=true",
            ]
            env["PROTON_OPTISCALER_CONFIG"] = ";".join(cfg_parts)

        # Image Sharpening (VKBasalt CAS)
        if profile.nis_sharpening > 0:
            sharp_float = round(profile.nis_sharpening / 100.0, 2)
            env["ENABLE_VKBASALT"] = "1"
            env["VKBASALT_CONFIG"] = f"effects=cas;casSharpness={sharp_float}"

        # On-screen DLSS HUD indicator (explicitly set 0 when off so Wine registry doesn't stay stuck on)
        if profile.dlss_indicator:
            env["DXVK_NVAPI_SET_NGX_DEBUG_OPTIONS"] = "DLSSIndicator=1024,DLSSGIndicator=2"
        else:
            env["DXVK_NVAPI_SET_NGX_DEBUG_OPTIONS"] = "DLSSIndicator=0,DLSSGIndicator=0"

        return env

    def build_env_vars(self, profile: GameProfile) -> Dict[str, str]:
        env: Dict[str, str] = {}

        if profile.prime_offload:
            env["__NV_PRIME_RENDER_OFFLOAD"] = "1"
            env["__GLX_VENDOR_LIBRARY_NAME"] = "nvidia"
            env["__VK_LAYER_NV_optimus"] = "NVIDIA_only"

        # Merge DLSS & Upscaling environment variables
        env.update(self.build_dlss_env_vars(profile))

        if profile.vsync_mode == "on":
            env["__GL_SYNC_TO_VBLANK"] = "1"
        elif profile.vsync_mode == "off":
            env["__GL_SYNC_TO_VBLANK"] = "0"

        env["__GL_VRR_ALLOWED"] = "1" if profile.vrr_gsync else "0"

        if profile.low_latency_mode:
            env["__GL_MaxFramesAllowed"] = "1"

        if profile.image_quality in IMAGE_QUALITY_MAP:
            env["__GL_ImageSettings"] = IMAGE_QUALITY_MAP[profile.image_quality][1]

        env["__GL_THREADED_OPTIMIZATIONS"] = "1" if profile.threaded_optimization else "0"

        if profile.unlimited_shader_cache:
            env["__GL_SHADER_DISK_CACHE"] = "1"
            env["__GL_SHADER_DISK_CACHE_SKIP_CLEANUP"] = "1"
        else:
            env["__GL_SHADER_DISK_CACHE"] = "0"

        if profile.proton_wayland:
            env["PROTON_ENABLE_WAYLAND"] = "1"
        if profile.proton_hdr:
            env["PROTON_ENABLE_HDR"] = "1"

        mh_parts = []
        if profile.mangohud:
            env["MANGOHUD"] = "1"
        if profile.fps_limit > 0:
            fps_str = str(profile.fps_limit)
            env["DXVK_FRAME_RATE"] = fps_str
            env["VKD3D_FRAME_RATE"] = fps_str
            env["MANGOHUD"] = "1"
            mh_parts.append(f"fps_limit={fps_str}")
            if not profile.mangohud:
                mh_parts.append("no_display")
        if mh_parts:
            env["MANGOHUD_CONFIG"] = ",".join(mh_parts)

        return env

    def _write_proton_user_settings(self, compat_app_dir: Path, env: Dict[str, str]) -> bool:
        """Writes user_settings.py inside a Steam Proton compatdata/<appid> folder."""
        try:
            compat_app_dir.mkdir(parents=True, exist_ok=True)
            us_file = compat_app_dir / "user_settings.py"
            lines = [
                "# Auto-generated by NVIDIA Control Center (CachyOS)",
                "import os",
                "import sys",
                "",
                "user_settings = {",
            ]
            for k, v in env.items():
                lines.append(f"    {json.dumps(k)}: {json.dumps(str(v))},")
            lines.extend(
                [
                    "}",
                    "",
                    "# Ensure per-game profile settings take precedence over global session environment",
                    f"for _k in {repr(MANAGED_ENV_KEYS)}:",
                    "    os.environ.pop(_k, None)",
                    "os.environ.update(user_settings)",
                    "_main = sys.modules.get('__main__')",
                    "_session = getattr(_main, 'g_session', None)",
                    "if _session is not None and hasattr(_session, 'env'):",
                    f"    for _k in {repr(MANAGED_ENV_KEYS)}:",
                    "        _session.env.pop(_k, None)",
                    "    _session.env.update(user_settings)",
                ]
            )
            us_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return True
        except Exception:
            return False

    def _sync_proton_install_shims(self):
        """Ensures official Valve Proton installations also load per-prefix compatdata user_settings.py."""
        shim_code = (
            "# Auto-generated by NVIDIA Control Center (CachyOS)\n"
            "import os\n"
            "import runpy\n"
            "import sys\n\n"
            "user_settings = {}\n"
            "_compat = os.environ.get('STEAM_COMPAT_DATA_PATH', '')\n"
            "_pfx_us = os.path.join(_compat, 'user_settings.py') if _compat else ''\n"
            "if _pfx_us and os.path.isfile(_pfx_us):\n"
            "    try:\n"
            "        user_settings.update(runpy.run_path(_pfx_us).get('user_settings', {}))\n"
            "    except Exception:\n"
            "        pass\n"
            f"for _k in {repr(MANAGED_ENV_KEYS)}:\n"
            "    if _k not in user_settings:\n"
            "        os.environ.pop(_k, None)\n"
            "os.environ.update(user_settings)\n"
            "_main = sys.modules.get('__main__')\n"
            "_session = getattr(_main, 'g_session', None)\n"
            "if _session is not None and hasattr(_session, 'env'):\n"
            f"    for _k in {repr(MANAGED_ENV_KEYS)}:\n"
            "        _session.env.pop(_k, None)\n"
            "    _session.env.update(user_settings)\n"
        )
        for sa_dir in self.get_steamapps_dirs():
            common_dir = sa_dir / "common"
            if not common_dir.exists():
                continue
            for pdir in common_dir.glob("Proton*"):
                if pdir.is_dir() and (pdir / "proton").exists():
                    us_path = pdir / "user_settings.py"
                    try:
                        if not us_path.exists() or "NVIDIA Control Center" in us_path.read_text(encoding="utf-8", errors="ignore"):
                            us_path.write_text(shim_code, encoding="utf-8")
                    except Exception:
                        pass

    def _prepare_cached_dlss_dlls(self) -> Dict[str, Path]:
        """Extracts latest DLSS 310.9.x DLLs from ~/.cache/protonfixes/upscalers into dlss_cache_dir."""
        upscalers_dir = Path.home() / ".cache" / "protonfixes" / "upscalers"
        result: Dict[str, Path] = {}
        if not upscalers_dir.exists():
            return result

        self.dlss_cache_dir.mkdir(parents=True, exist_ok=True)
        mapping = [
            ("dlss_v*.xz", "nvngx_dlss.dll"),
            ("dlss_d_v*.xz", "nvngx_dlssd.dll"),
            ("dlss_g_v*.xz", "nvngx_dlssg.dll"),
        ]
        for pattern, dll_name in mapping:
            archives = sorted(upscalers_dir.glob(pattern))
            if not archives:
                continue
            latest_xz = archives[-1]
            target_dll = self.dlss_cache_dir / dll_name
            stamp_file = self.dlss_cache_dir / f"{dll_name}.source"
            try:
                if not target_dll.exists() or not stamp_file.exists() or stamp_file.read_text(encoding="utf-8").strip() != latest_xz.name:
                    with lzma.open(latest_xz, "rb") as f_in:
                        target_dll.write_bytes(f_in.read())
                    stamp_file.write_text(latest_xz.name, encoding="utf-8")
                if target_dll.exists():
                    result[dll_name] = target_dll
            except Exception:
                pass
        return result

    def _sync_game_dlss_and_prefix(
        self,
        profile: GameProfile,
        compat_dirs: List[Path],
        cached_dlss_dlls: Optional[Dict[str, Path]] = None,
    ):
        """Syncs DLSS DLL upgrades, Wine NGX registry keys, OptiScaler.ini, and MangoHud.conf for a game."""
        if profile.dlss_upgrade:
            dlss_dlls = cached_dlss_dlls if cached_dlss_dlls is not None else self._prepare_cached_dlss_dlls()
        else:
            dlss_dlls = {}

        # 1. Sync Proton prefix registry, tracked_files cleanup, and prefix DLLs
        for cd_dir in compat_dirs:
            # Clean broken amdxcffx64.dll from tracked_files / upscaler_files
            for tf_name in ("tracked_files", "upscaler_files"):
                tf = cd_dir / tf_name
                if tf.exists():
                    try:
                        lines = tf.read_text(encoding="utf-8", errors="ignore").splitlines()
                        cleaned = [ln for ln in lines if "amdxcffx64.dll" not in ln]
                        if len(cleaned) != len(lines):
                            tf.write_text("\n".join(cleaned) + ("\n" if cleaned else ""), encoding="utf-8")
                    except Exception:
                        pass

            # Update Wine system.reg NGXCore indicator keys so they don't stay stuck on
            sys_reg = cd_dir / "pfx" / "system.reg"
            if sys_reg.exists():
                try:
                    reg_txt = sys_reg.read_text(encoding="utf-8", errors="ignore")
                    fg_active = bool(profile.optiscaler_fg_enabled and profile.optiscaler_fg_mode != "off")
                    ind_dword = "dword:00000400" if profile.dlss_indicator else "dword:00000000"
                    fg_dword = "dword:00000002" if (profile.dlss_indicator and fg_active) else "dword:00000000"
                    new_txt = re.sub(
                        r'"ShowDlssIndicator"=dword:[0-9a-fA-F]{8}',
                        f'"ShowDlssIndicator"={ind_dword}',
                        reg_txt,
                    )
                    new_txt = re.sub(
                        r'"DLSSG_IndicatorText"=dword:[0-9a-fA-F]{8}',
                        f'"DLSSG_IndicatorText"={fg_dword}',
                        new_txt,
                    )
                    if new_txt != reg_txt:
                        sys_reg.write_text(new_txt, encoding="utf-8")
                except Exception:
                    pass

            # Copy upgraded DLSS DLLs into prefix system32 & system32/umu
            if profile.dlss_upgrade and dlss_dlls:
                sys32 = cd_dir / "pfx" / "drive_c" / "windows" / "system32"
                for dest_dir in (sys32, sys32 / "umu"):
                    if dest_dir.exists():
                        for dll_name, src_path in dlss_dlls.items():
                            if dll_name == "nvngx_dlssg.dll":
                                # Never copy Ada nvngx_dlssg.dll into prefix when Frame Gen uses OptiScaler
                                continue
                            dst_dll = dest_dir / dll_name
                            try:
                                if not dst_dll.exists() or dst_dll.stat().st_size != src_path.stat().st_size:
                                    shutil.copy2(src_path, dst_dll)
                            except Exception:
                                pass

            # Also sync prefix umu OptiScaler.ini if present
            umu_ini = cd_dir / "pfx" / "drive_c" / "windows" / "system32" / "umu" / "OptiScaler.ini"
            if umu_ini.exists():
                self._update_optiscaler_ini(umu_ini, profile)

        # 2. Sync game installation directory (OptiScaler.ini, in-game nvngx_dlss*.dll, local MangoHud.conf)
        if not profile.install_dir:
            return
        game_dir = Path(profile.install_dir)
        if not game_dir.exists() or not game_dir.is_dir():
            return

        # Restore original nvngx_dlssg.dll if it was previously overwritten by Ada DLL
        try:
            for found_dll in game_dir.rglob("nvngx_dlssg.dll"):
                if not found_dll.is_file():
                    continue
                bak_dll = found_dll.with_name(found_dll.name + ".bak_nvcc")
                if bak_dll.exists() and found_dll.stat().st_size != bak_dll.stat().st_size:
                    shutil.copy2(bak_dll, found_dll)
        except Exception:
            pass

        # Upgrade in-game nvngx_dlss*.dll (excluding nvngx_dlssg.dll so OptiScaler Frame Gen isn't broken)
        if profile.dlss_upgrade and dlss_dlls:
            for dll_name, src_path in dlss_dlls.items():
                if dll_name == "nvngx_dlssg.dll":
                    continue

                try:
                    for found_dll in game_dir.rglob(dll_name):
                        if not found_dll.is_file():
                            continue
                        bak_dll = found_dll.with_name(found_dll.name + ".bak_nvcc")
                        if not bak_dll.exists() and found_dll.stat().st_size != src_path.stat().st_size:
                            try:
                                shutil.copy2(found_dll, bak_dll)
                            except Exception:
                                pass
                        if found_dll.stat().st_size != src_path.stat().st_size:
                            shutil.copy2(src_path, found_dll)
                except Exception:
                    pass

        # Deploy OptiScaler directly underneath the app in game binary directories
        fg_active = bool(profile.optiscaler_fg_enabled and profile.optiscaler_fg_mode != "off")
        if profile.optiscaler_enable or fg_active:
            try:
                self._deploy_optiscaler_to_game(game_dir, profile)
            except Exception:
                pass

        # Sync any OptiScaler.ini in the game directory so it uses NVIDIA DLSS instead of fsr31
        try:
            for opti_ini in game_dir.rglob("OptiScaler.ini"):
                if opti_ini.is_file():
                    self._update_optiscaler_ini(opti_ini, profile)
        except Exception:
            pass

        # Sync any local MangoHud.conf in the game directory so fps_limit matches profile
        try:
            for mh_conf in game_dir.rglob("MangoHud.conf"):
                if mh_conf.is_file():
                    self._update_local_mangohud_conf(mh_conf, profile)
        except Exception:
            pass

    def _find_optiscaler_source_dir(self) -> Optional[Path]:
        """Finds the local repository of OptiScaler and Frame Gen DLLs."""
        for candidate in (
            Path.home() / ".local" / "share" / "goverlay" / "optiscaler-stable",
            Path.home() / ".local" / "share" / "goverlay" / "dlssenabler-stable",
            Path.home() / ".local" / "share" / "goverlay" / "gameconfig" / "global",
            Path.home() / ".local" / "share" / "Steam" / "steamapps" / "compatdata" / "0" / "pfx" / "drive_c" / "windows" / "system32" / "umu",
        ):
            if candidate.exists() and (candidate / "OptiScaler.dll").is_file():
                return candidate
        return None

    def _find_game_binary_dirs(self, game_dir: Path) -> List[Path]:
        """Finds directories directly underneath the game where the main game executables reside."""
        if not game_dir.exists() or not game_dir.is_dir():
            return []
        target_dirs: Set[Path] = set()
        for f in game_dir.rglob("OptiScaler.ini"):
            target_dirs.add(f.parent)
        for f in game_dir.rglob("dxgi.dll"):
            target_dirs.add(f.parent)
        for marker in ("sl.interposer.dll", "sl.dlss_g.dll", "nvngx_dlss.dll", "nvngx_dlssg.dll"):
            for f in game_dir.rglob(marker):
                target_dirs.add(f.parent)

        skip_terms = {
            "crash", "report", "setup", "install", "__installer", "unins", "redist",
            "eac", "easyanticheat", "battleye", "vcredist", "directx", "dotnet",
            "support", "prereq", "steamworks", "benchmark", "tools", "webclient",
            "overlay", "battleserver", "plugins", "sentry"
        }
        for exe in game_dir.rglob("*.exe"):
            lower = exe.name.lower()
            if any(term in lower for term in skip_terms):
                continue
            parts_lower = [p.lower() for p in exe.parts]
            if any(term in parts_lower for term in skip_terms):
                continue
            target_dirs.add(exe.parent)

        return sorted(list(target_dirs))

    def _deploy_optiscaler_to_game(self, game_dir: Path, profile: GameProfile):
        """Ensures OptiScaler and Frame Gen DLLs/INIs are deployed directly underneath the game application."""
        opti_src = self._find_optiscaler_source_dir()
        if not opti_src:
            return

        target_dirs = self._find_game_binary_dirs(game_dir)
        for b_dir in target_dirs:
            # 1. Deploy OptiScaler.dll as dxgi.dll
            dxgi_dst = b_dir / "dxgi.dll"
            src_opti_dll = opti_src / "OptiScaler.dll"
            if src_opti_dll.exists():
                if not dxgi_dst.exists():
                    try:
                        shutil.copy2(src_opti_dll, dxgi_dst)
                    except Exception:
                        pass
                opti_dst = b_dir / "OptiScaler.dll"
                if not opti_dst.exists():
                    try:
                        shutil.copy2(src_opti_dll, opti_dst)
                    except Exception:
                        pass

            # 2. Deploy OptiScaler.ini if missing
            ini_dst = b_dir / "OptiScaler.ini"
            src_ini = opti_src / "OptiScaler.ini"
            if not ini_dst.exists() and src_ini.exists():
                try:
                    shutil.copy2(src_ini, ini_dst)
                except Exception:
                    pass

            # 3. Deploy Frame Gen translation & hooking DLLs
            fg_files = [
                "fakenvapi.dll",
                "fakenvapi.ini",
                "dlssg_to_fsr3_amd_is_better.dll",
                "amd_fidelityfx_dx12.dll",
                "amd_fidelityfx_framegeneration_dx12.dll",
                "amd_fidelityfx_upscaler_dx12.dll",
                "amd_fidelityfx_vk.dll",
                "libxess_fg.dll",
                "libxell.dll",
                "libxess.dll",
                "libxess_dx11.dll",
            ]
            for fname in fg_files:
                fsrc = opti_src / fname
                fdst = b_dir / fname
                if fsrc.exists() and not fdst.exists():
                    try:
                        shutil.copy2(fsrc, fdst)
                    except Exception:
                        pass

            # 4. Deploy D3D12_Optiscaler directory if present
            src_d3d12 = opti_src / "D3D12_Optiscaler"
            dst_d3d12 = b_dir / "D3D12_Optiscaler"
            if src_d3d12.exists() and not dst_d3d12.exists():
                try:
                    shutil.copytree(src_d3d12, dst_d3d12)
                except Exception:
                    pass

            # 5. Update the OptiScaler.ini in this binary directory
            if ini_dst.exists():
                self._update_optiscaler_ini(ini_dst, profile)

    @staticmethod
    def _update_ini_section_key(text: str, section: str, key: str, value: str) -> str:
        """Updates key=value inside [section] of an INI file, adding section/key if missing."""
        sec_pattern = re.compile(rf"(\[{re.escape(section)}\][^\[]*?^\s*{re.escape(key)}\s*=\s*)([^\r\n;]+)", re.MULTILINE | re.DOTALL)
        if sec_pattern.search(text):
            return sec_pattern.sub(rf"\g<1>{value}", text, count=1)
        sec_head = re.compile(rf"^(\[{re.escape(section)}\]\s*\r?\n)", re.MULTILINE)
        if sec_head.search(text):
            return sec_head.sub(rf"\g<1>{key}={value}\n", text, count=1)
        return f"{text.rstrip()}\n\n[{section}]\n{key}={value}\n"

    def _update_optiscaler_ini(self, ini_path: Path, profile: GameProfile):
        """Updates an existing OptiScaler.ini in a game folder to honor NVIDIA Control Center DLSS settings."""
        try:
            text = ini_path.read_text(encoding="utf-8", errors="replace")
            orig = text

            # Always route upscaling to NVIDIA DLSS on an RTX GPU instead of fsr31
            text = self._update_ini_section_key(text, "Upscalers", "Dx11Upscaler", "dlss")
            text = self._update_ini_section_key(text, "Upscalers", "Dx12Upscaler", "dlss")
            text = self._update_ini_section_key(text, "Upscalers", "VulkanUpscaler", "dlss")
            text = self._update_ini_section_key(text, "DLSS", "Enabled", "true")

            # Frame Generation (OptiScaler Universal Frame Gen: FSR 3.1 & XeFG)
            fg_active = bool(profile.optiscaler_fg_enabled and profile.optiscaler_fg_mode != "off")
            if fg_active:
                text = self._update_ini_section_key(text, "FrameGen", "Enabled", "true")
                text = self._update_ini_section_key(text, "FrameGen", "FGInput", "dlssg")
                text = self._update_ini_section_key(text, "FrameGen", "FGOutput", "fsrfg")
                text = self._update_ini_section_key(text, "FSRFG", "AllowAsync", "true")
                interp_count = "2" if profile.optiscaler_fg_mode == "mfg_3x" else ("3" if profile.optiscaler_fg_mode == "mfg_4x" else "1")
                text = self._update_ini_section_key(text, "XeFG", "InterpolationCount", interp_count)
                text = self._update_ini_section_key(text, "Spoofing", "StreamlineSpoofing", "true")
                text = self._update_ini_section_key(text, "Spoofing", "Dxgi", "true")
                text = self._update_ini_section_key(text, "Spoofing", "SpoofHAGS", "true")
                text = self._update_ini_section_key(text, "Spoofing", "SpoofedGPUName", "NVIDIA GeForce RTX 4090")
                text = self._update_ini_section_key(text, "Spoofing", "SpoofedDeviceId", "0x2684")
                text = self._update_ini_section_key(text, "Spoofing", "SpoofedVendorId", "0x10de")
            else:
                text = self._update_ini_section_key(text, "FrameGen", "Enabled", "false")
                text = self._update_ini_section_key(text, "FrameGen", "FGInput", "nofg")
                text = self._update_ini_section_key(text, "FrameGen", "FGOutput", "nofg")

            preset_int = OPTISCALER_PRESET_INT_MAP.get(profile.dlss_preset, "11")
            if profile.dlss_override:
                p_val = "11" if preset_int == "auto" else preset_int
                text = self._update_ini_section_key(text, "DLSS", "RenderPresetOverride", "true")
                text = self._update_ini_section_key(text, "DLSS", "RenderPresetForAll", p_val)
                text = self._update_ini_section_key(text, "DLSS", "RenderPresetDLAA", p_val)
                text = self._update_ini_section_key(text, "DLSS", "RenderPresetUltraQuality", p_val)
                text = self._update_ini_section_key(text, "DLSS", "RenderPresetQuality", p_val)
                text = self._update_ini_section_key(text, "DLSS", "RenderPresetBalanced", p_val)
                text = self._update_ini_section_key(text, "DLSS", "RenderPresetPerformance", p_val)
                text = self._update_ini_section_key(text, "DLSS", "RenderPresetUltraPerformance", p_val)
            else:
                text = self._update_ini_section_key(text, "DLSS", "RenderPresetOverride", "auto")
                text = self._update_ini_section_key(text, "DLSS", "RenderPresetForAll", "auto")

            # Upscale Ratio override
            if profile.dlss_override and profile.dlss_sr_mode != "default":
                eff_ratio = (
                    DLSS_SR_MODE_MAP.get(profile.dlss_sr_mode, ("", "", profile.dlss_scale_ratio))[2]
                    if profile.dlss_sr_mode != "custom"
                    else max(33, min(100, int(profile.dlss_scale_ratio)))
                )
                upscale_mult = round(100.0 / float(max(1, eff_ratio)), 4)
                text = self._update_ini_section_key(text, "UpscaleRatio", "UpscaleRatioOverrideEnabled", "true")
                text = self._update_ini_section_key(text, "UpscaleRatio", "UpscaleRatioOverrideValue", str(upscale_mult))
            else:
                text = self._update_ini_section_key(text, "UpscaleRatio", "UpscaleRatioOverrideEnabled", "false")

            # Sharpness / CAS
            if profile.nis_sharpening > 0:
                sharp_f = round(profile.nis_sharpening / 100.0, 2)
                text = self._update_ini_section_key(text, "Sharpness", "OverrideSharpness", "true")
                text = self._update_ini_section_key(text, "Sharpness", "Sharpness", str(sharp_f))
                text = self._update_ini_section_key(text, "CAS", "Enabled", "true")
            else:
                text = self._update_ini_section_key(text, "Sharpness", "OverrideSharpness", "auto")
                text = self._update_ini_section_key(text, "CAS", "Enabled", "auto")

            # Framerate & VSync
            fps_val = f"{float(profile.fps_limit):.1f}" if profile.fps_limit > 0 else "0.0"
            text = self._update_ini_section_key(text, "Framerate", "FramerateLimit", fps_val)

            if profile.vsync_mode == "on":
                text = self._update_ini_section_key(text, "V-Sync", "OverrideVsync", "true")
                text = self._update_ini_section_key(text, "V-Sync", "ForceVsync", "true")
            elif profile.vsync_mode == "off":
                text = self._update_ini_section_key(text, "V-Sync", "OverrideVsync", "true")
                text = self._update_ini_section_key(text, "V-Sync", "ForceVsync", "false")
            else:
                text = self._update_ini_section_key(text, "V-Sync", "OverrideVsync", "auto")

            if text != orig:
                ini_path.write_text(text, encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _update_local_mangohud_conf(mh_path: Path, profile: GameProfile):
        """Updates fps_limit inside a game directory's MangoHud.conf so it matches the game profile."""
        try:
            text = mh_path.read_text(encoding="utf-8", errors="replace")
            new_text = re.sub(
                r"^(\s*fps_limit\s*=\s*).*$",
                rf"\g<1>{int(profile.fps_limit)}",
                text,
                flags=re.MULTILINE,
            )
            if new_text != text:
                mh_path.write_text(new_text, encoding="utf-8")
        except Exception:
            pass

    def clean_legacy_steam_launch_options(self):
        """Removes redundant pasted NVIDIA Control Center LaunchOptions from Steam localconfig.vdf."""
        userdata_dir = Path.home() / ".local" / "share" / "Steam" / "userdata"
        if not userdata_dir.exists():
            return
        for vdf_path in userdata_dir.glob("*/config/localconfig.vdf"):
            try:
                text = vdf_path.read_text(encoding="utf-8", errors="replace")
                # Match LaunchOptions lines that were generated by NVIDIA Control Center
                pattern = re.compile(
                    r'^(\s*"LaunchOptions"\s+)"__NV_PRIME_RENDER_OFFLOAD=1[^"\n]*%command%"',
                    re.MULTILINE,
                )
                if pattern.search(text):
                    cleaned = pattern.sub(r'\1""', text)
                    vdf_path.write_text(cleaned, encoding="utf-8")
            except Exception:
                pass

    def _find_compat_dirs_for_app(self, app_id: str, install_dir: str = "") -> List[Path]:
        target_dirs: List[Path] = []
        for sa_dir in self.get_steamapps_dirs():
            cd = sa_dir / "compatdata" / app_id
            if cd.exists():
                target_dirs.append(cd)
        if not target_dirs and install_dir:
            p = Path(install_dir)
            # If install_dir is .../steamapps/common/<Game>, parent.parent is .../steamapps
            for ancestor in [p.parent, p.parent.parent]:
                if ancestor.name == "steamapps" and ancestor.exists():
                    target_dirs.append(ancestor / "compatdata" / app_id)
                    break
        return target_dirs

    def _sync_systemd_env_async(self, env: Dict[str, str]):
        def worker():
            if not self._systemd_sync_lock.acquire(blocking=False):
                return
            try:
                subprocess.run(
                    ["systemctl", "--user", "daemon-reload"],
                    timeout=3,
                    check=False,
                )
                to_unset = [k for k in MANAGED_ENV_KEYS if k not in env]
                if to_unset:
                    subprocess.run(
                        ["systemctl", "--user", "unset-environment"] + to_unset,
                        timeout=3,
                        check=False,
                    )
                if env:
                    subprocess.run(
                        ["systemctl", "--user", "import-environment"] + list(env.keys()),
                        env={**dict(subprocess.os.environ), **env},
                        timeout=3,
                        check=False,
                    )
            except Exception:
                pass
            finally:
                self._systemd_sync_lock.release()

        threading.Thread(target=worker, daemon=True).start()

    def apply_profile_to_proton(self, profile: GameProfile) -> Tuple[bool, str]:
        """Applies a profile automatically to Steam Proton prefixes, game directories, and/or Global user environment."""
        self.save()
        global_prof = self.profiles.get("__global__", profile)
        global_env = self.build_env_vars(global_prof)
        self._sync_proton_install_shims()
        cached_dlss = self._prepare_cached_dlss_dlls()

        if profile.app_id == "__global__":
            try:
                self.env_d_file.parent.mkdir(parents=True, exist_ok=True)
                lines = ["# Auto-generated by NVIDIA Control Center (CachyOS)"]
                for k, v in global_env.items():
                    lines.append(f'{k}="{v}"')
                self.env_d_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

                self._sync_systemd_env_async(global_env)

                # Sync all discovered games and existing compatdata prefixes
                synced_app_ids: Set[str] = set()

                for app_id, game_prof in self.profiles.items():
                    if app_id == "__global__" or not app_id.isdigit():
                        continue
                    if not game_prof.custom_override:
                        # Keep non-overridden games synced with Global Profile values
                        refreshed = self._new_game_from_global(app_id, game_prof.name, game_prof.install_dir)
                        self.profiles[app_id] = refreshed
                        game_prof = refreshed
                        target_env = global_env
                    else:
                        target_env = self.build_env_vars(game_prof)

                    compat_dirs = self._find_compat_dirs_for_app(app_id, game_prof.install_dir)
                    for cd_dir in compat_dirs:
                        if self._write_proton_user_settings(cd_dir, target_env):
                            synced_app_ids.add(app_id)
                    self._sync_game_dlss_and_prefix(game_prof, compat_dirs, cached_dlss)

                for sa_dir in self.get_steamapps_dirs():
                    cd_root = sa_dir / "compatdata"
                    if not cd_root.exists():
                        continue
                    for sub in cd_root.iterdir():
                        if (
                            sub.is_dir()
                            and sub.name.isdigit()
                            and sub.name not in SKIP_APP_IDS
                            and sub.name not in synced_app_ids
                        ):
                            if self._write_proton_user_settings(sub, global_env):
                                synced_app_ids.add(sub.name)

                updated_count = len(synced_app_ids)
                self.save()
                return (
                    True,
                    f"Auto-applied Global settings to system environment and {updated_count} Steam game prefix(es).",
                )
            except Exception as e:
                return False, f"Failed to write global environment: {e}"
        else:
            env = self.build_env_vars(profile)
            updated = 0
            compat_dirs = self._find_compat_dirs_for_app(profile.app_id, profile.install_dir)
            for cd_dir in compat_dirs:
                if self._write_proton_user_settings(cd_dir, env):
                    updated += 1
            self._sync_game_dlss_and_prefix(profile, compat_dirs, cached_dlss)
            if updated > 0:
                return (
                    True,
                    f"Auto-applied '{profile.name}' directly to Steam Proton, DLSS & OptiScaler (compatdata/{profile.app_id}).",
                )
            return (
                True,
                f"Saved & synced profile for '{profile.name}'. Settings will apply automatically.",
            )
