"""
Direct NVML (libnvidia-ml.so.1) & Linux Kernel sysfs backend for real-time telemetry,
GPU process inspection, system diagnostics, and hardware/kernel-level tuning.
"""

from collections import deque
import ctypes
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import platform
import subprocess
from typing import Dict, List, Optional, Tuple


NVML_VALUE_NOT_AVAILABLE_ULL = 0xFFFFFFFFFFFFFFFF


class _NvmlUtilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _NvmlMemory(ctypes.Structure):
    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


class _NvmlBAR1Memory(ctypes.Structure):
    _fields_ = [
        ("bar1Total", ctypes.c_ulonglong),
        ("bar1Free", ctypes.c_ulonglong),
        ("bar1Used", ctypes.c_ulonglong),
    ]


class _NvmlPciInfo(ctypes.Structure):
    _fields_ = [
        ("busIdLegacy", ctypes.c_char * 16),
        ("domain", ctypes.c_uint),
        ("bus", ctypes.c_uint),
        ("device", ctypes.c_uint),
        ("pciDeviceId", ctypes.c_uint),
        ("pciSubSystemId", ctypes.c_uint),
        ("busId", ctypes.c_char * 32),
    ]


class _NvmlProcessInfoV2(ctypes.Structure):
    _fields_ = [
        ("pid", ctypes.c_uint),
        ("usedGpuMemory", ctypes.c_ulonglong),
        ("gpuInstanceId", ctypes.c_uint),
        ("computeInstanceId", ctypes.c_uint),
    ]


class _NvmlClockOffsetV1(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_uint),
        ("type", ctypes.c_uint),
        ("pstate", ctypes.c_uint),
        ("clockOffsetMHz", ctypes.c_int),
        ("minClockOffsetMHz", ctypes.c_int),
        ("maxClockOffsetMHz", ctypes.c_int),
    ]


NVML_CLOCK_OFFSET_V1 = ctypes.sizeof(_NvmlClockOffsetV1) | (1 << 24)


@dataclass
class GpuProcess:
    pid: int
    name: str
    cmdline: str
    engine: str  # "Graphics", "Compute", or "Graphics+Compute"
    vram_mib: Optional[int]


@dataclass
class GpuSnapshot:
    index: int = 0
    name: str = "NVIDIA GPU"
    uuid: str = ""
    vbios: str = ""
    driver_version: str = ""
    cuda_version: str = ""
    pci_bus_id: str = ""
    pcie_gen_cur: int = 0
    pcie_gen_max: int = 0
    pcie_width_cur: int = 0
    pcie_width_max: int = 0
    pcie_tx_kbps: int = 0
    pcie_rx_kbps: int = 0
    pstate: int = 0
    gpu_util: int = 0
    mem_util: int = 0
    enc_util: int = 0
    dec_util: int = 0
    vram_used_mib: int = 0
    vram_free_mib: int = 0
    vram_total_mib: int = 1
    bar1_used_mib: int = 0
    bar1_total_mib: int = 1
    temp_c: int = 0
    temp_slowdown_c: int = 90
    temp_shutdown_c: int = 95
    fan_count: int = 1
    fan_speeds: List[int] = field(default_factory=lambda: [0])
    fan_policy: int = 0  # 0 = Auto, 1 = Manual
    power_draw_w: float = 0.0
    power_limit_w: float = 70.0
    power_default_w: float = 70.0
    power_min_w: float = 20.0
    power_max_w: float = 70.0
    clock_graphics_mhz: int = 0
    clock_graphics_max_mhz: int = 2100
    clock_sm_mhz: int = 0
    clock_mem_mhz: int = 0
    clock_mem_max_mhz: int = 7000
    clock_video_mhz: int = 0
    core_offset_mhz: int = 0
    mem_offset_mhz: int = 0
    persistence_mode: bool = False
    pcie_pm_control: str = "auto"
    kernel_rebar: bool = False
    kernel_stream_memops: bool = False
    kernel_vrr_memclk: bool = False
    kernel_ntsync: bool = False
    throttle_reasons: List[str] = field(default_factory=list)
    processes: List[GpuProcess] = field(default_factory=list)


THROTTLE_BITS = [
    (0x0000000000000001, "Idle (GPU Low Utilization)"),
    (0x0000000000000002, "Application Clocks Setting"),
    (0x0000000000000004, "SW Power Cap (Power Limit Reached)"),
    (0x0000000000000008, "HW Slowdown (Thermal / Power Protection)"),
    (0x0000000000000010, "Sync Boost"),
    (0x0000000000000020, "SW Thermal Slowdown"),
    (0x0000000000000040, "HW Thermal Slowdown"),
    (0x0000000000000080, "HW Power Brake Slowdown"),
    (0x0000000000000100, "Display Clock Setting"),
]


class NvmlBackend:
    """Manages NVML lifecycle, telemetry history buffers, and hardware/kernel control."""

    def __init__(self, history_len: int = 60):
        self.history_len = history_len
        self.nvml = None
        self.dev = ctypes.c_void_p()
        self.available = False

        # Ring buffers for 60s real-time graphs
        self.hist_gpu_util = deque([0] * history_len, maxlen=history_len)
        self.hist_temp = deque([0] * history_len, maxlen=history_len)
        self.hist_power = deque([0.0] * history_len, maxlen=history_len)
        self.hist_clock_gfx = deque([0] * history_len, maxlen=history_len)

        self.config_dir = Path.home() / ".config" / "nvidia-control-center"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.presets_file = self.config_dir / "tuning_config.json"

        self._init_nvml()

    def _init_nvml(self):
        try:
            self.nvml = ctypes.CDLL("libnvidia-ml.so.1")
            if hasattr(self.nvml, "nvmlErrorString"):
                self.nvml.nvmlErrorString.restype = ctypes.c_char_p
            if self.nvml.nvmlInit_v2() == 0:
                if self.nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(self.dev)) == 0:
                    self.available = True
        except Exception:
            self.available = False

    def shutdown(self):
        if self.available and self.nvml is not None:
            try:
                self.nvml.nvmlShutdown()
            except Exception:
                pass
            self.available = False

    def _get_str(self, fn, *args, buf_len: int = 96) -> str:
        buf = ctypes.create_string_buffer(buf_len)
        if fn(*args, buf, buf_len) == 0:
            return buf.value.decode("utf-8", errors="replace")
        return ""

    def _get_uint(self, fn, *args) -> int:
        val = ctypes.c_uint(0)
        if fn(*args, ctypes.byref(val)) == 0:
            return int(val.value)
        return 0

    def _get_int(self, fn, *args) -> int:
        val = ctypes.c_int(0)
        if fn(*args, ctypes.byref(val)) == 0:
            return int(val.value)
        return 0

    def _get_clock_offset(self, clock_type: int) -> int:
        nvml = self.nvml
        dev = self.dev
        if hasattr(nvml, "nvmlDeviceGetClockOffsets"):
            info = _NvmlClockOffsetV1()
            info.version = NVML_CLOCK_OFFSET_V1
            info.type = clock_type
            info.pstate = 0
            if nvml.nvmlDeviceGetClockOffsets(dev, ctypes.byref(info)) == 0:
                return int(info.clockOffsetMHz)
        if clock_type == 0 and hasattr(nvml, "nvmlDeviceGetGpcClkVfOffset"):
            return self._get_int(nvml.nvmlDeviceGetGpcClkVfOffset, dev)
        if clock_type == 2 and hasattr(nvml, "nvmlDeviceGetMemClkVfOffset"):
            return self._get_int(nvml.nvmlDeviceGetMemClkVfOffset, dev)
        return 0

    @staticmethod
    def _read_sysfs_str(path: Path, default: str = "") -> str:
        try:
            if path.exists():
                return path.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            pass
        return default

    def poll(self) -> GpuSnapshot:
        snap = GpuSnapshot()
        if not self.available:
            return snap

        nvml = self.nvml
        dev = self.dev

        snap.name = self._get_str(nvml.nvmlDeviceGetName, dev) or "NVIDIA GPU"
        snap.uuid = self._get_str(nvml.nvmlDeviceGetUUID, dev)
        snap.vbios = self._get_str(nvml.nvmlDeviceGetVbiosVersion, dev)
        snap.driver_version = self._get_str(nvml.nvmlSystemGetDriverVersion)

        cuda_v = ctypes.c_int(0)
        if nvml.nvmlSystemGetCudaDriverVersion_v2(ctypes.byref(cuda_v)) == 0:
            snap.cuda_version = f"{cuda_v.value // 1000}.{(cuda_v.value % 1000) // 10}"

        pci = _NvmlPciInfo()
        if nvml.nvmlDeviceGetPciInfo_v3(dev, ctypes.byref(pci)) == 0:
            snap.pci_bus_id = pci.busId.decode("utf-8", errors="replace")

        snap.pcie_gen_cur = self._get_uint(nvml.nvmlDeviceGetCurrPcieLinkGeneration, dev)
        snap.pcie_gen_max = self._get_uint(nvml.nvmlDeviceGetMaxPcieLinkGeneration, dev)
        snap.pcie_width_cur = self._get_uint(nvml.nvmlDeviceGetCurrPcieLinkWidth, dev)
        snap.pcie_width_max = self._get_uint(nvml.nvmlDeviceGetMaxPcieLinkWidth, dev)
        snap.pcie_tx_kbps = self._get_uint(nvml.nvmlDeviceGetPcieThroughput, dev, ctypes.c_uint(0))
        snap.pcie_rx_kbps = self._get_uint(nvml.nvmlDeviceGetPcieThroughput, dev, ctypes.c_uint(1))

        snap.pstate = self._get_uint(nvml.nvmlDeviceGetPerformanceState, dev)

        util = _NvmlUtilization()
        if nvml.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(util)) == 0:
            snap.gpu_util = int(util.gpu)
            snap.mem_util = int(util.memory)

        enc_u = ctypes.c_uint(0)
        enc_s = ctypes.c_uint(0)
        if hasattr(nvml, "nvmlDeviceGetEncoderUtilization"):
            if nvml.nvmlDeviceGetEncoderUtilization(dev, ctypes.byref(enc_u), ctypes.byref(enc_s)) == 0:
                snap.enc_util = int(enc_u.value)
        if hasattr(nvml, "nvmlDeviceGetDecoderUtilization"):
            if nvml.nvmlDeviceGetDecoderUtilization(dev, ctypes.byref(enc_u), ctypes.byref(enc_s)) == 0:
                snap.dec_util = int(enc_u.value)

        mem = _NvmlMemory()
        if nvml.nvmlDeviceGetMemoryInfo(dev, ctypes.byref(mem)) == 0:
            snap.vram_total_mib = max(1, int(mem.total // (1024 * 1024)))
            snap.vram_used_mib = int(mem.used // (1024 * 1024))
            snap.vram_free_mib = int(mem.free // (1024 * 1024))

        bar1 = _NvmlBAR1Memory()
        if hasattr(nvml, "nvmlDeviceGetBAR1MemoryInfo"):
            if nvml.nvmlDeviceGetBAR1MemoryInfo(dev, ctypes.byref(bar1)) == 0:
                snap.bar1_total_mib = max(1, int(bar1.bar1Total // (1024 * 1024)))
                snap.bar1_used_mib = int(bar1.bar1Used // (1024 * 1024))

        snap.temp_c = self._get_uint(nvml.nvmlDeviceGetTemperature, dev, ctypes.c_uint(0))
        snap.temp_shutdown_c = self._get_uint(nvml.nvmlDeviceGetTemperatureThreshold, dev, ctypes.c_uint(0)) or 95
        snap.temp_slowdown_c = self._get_uint(nvml.nvmlDeviceGetTemperatureThreshold, dev, ctypes.c_uint(1)) or 90

        num_fans = ctypes.c_uint(1)
        if hasattr(nvml, "nvmlDeviceGetNumFans") and nvml.nvmlDeviceGetNumFans(dev, ctypes.byref(num_fans)) == 0:
            snap.fan_count = max(1, int(num_fans.value))
        else:
            snap.fan_count = 1

        fan_speeds = []
        for idx in range(snap.fan_count):
            if hasattr(nvml, "nvmlDeviceGetFanSpeed_v2"):
                spd = self._get_uint(nvml.nvmlDeviceGetFanSpeed_v2, dev, ctypes.c_uint(idx))
            else:
                spd = self._get_uint(nvml.nvmlDeviceGetFanSpeed, dev)
            fan_speeds.append(spd)
        snap.fan_speeds = fan_speeds or [0]

        if hasattr(nvml, "nvmlDeviceGetFanControlPolicy_v2"):
            pol = ctypes.c_uint(0)
            if nvml.nvmlDeviceGetFanControlPolicy_v2(dev, ctypes.c_uint(0), ctypes.byref(pol)) == 0:
                snap.fan_policy = int(pol.value)

        pwr_mw = self._get_uint(nvml.nvmlDeviceGetPowerUsage, dev)
        snap.power_draw_w = round(pwr_mw / 1000.0, 2)

        lim_mw = self._get_uint(nvml.nvmlDeviceGetPowerManagementLimit, dev)
        if lim_mw > 0:
            snap.power_limit_w = round(lim_mw / 1000.0, 2)

        def_mw = self._get_uint(nvml.nvmlDeviceGetPowerManagementDefaultLimit, dev)
        if def_mw > 0:
            snap.power_default_w = round(def_mw / 1000.0, 2)

        min_mw = ctypes.c_uint(0)
        max_mw = ctypes.c_uint(0)
        if nvml.nvmlDeviceGetPowerManagementLimitConstraints(dev, ctypes.byref(min_mw), ctypes.byref(max_mw)) == 0:
            snap.power_min_w = round(min_mw.value / 1000.0, 2)
            snap.power_max_w = round(max_mw.value / 1000.0, 2)

        # Clocks: 0=Graphics, 1=SM, 2=Memory, 3=Video
        snap.clock_graphics_mhz = self._get_uint(nvml.nvmlDeviceGetClockInfo, dev, ctypes.c_uint(0))
        snap.clock_sm_mhz = self._get_uint(nvml.nvmlDeviceGetClockInfo, dev, ctypes.c_uint(1))
        snap.clock_mem_mhz = self._get_uint(nvml.nvmlDeviceGetClockInfo, dev, ctypes.c_uint(2))
        snap.clock_video_mhz = self._get_uint(nvml.nvmlDeviceGetClockInfo, dev, ctypes.c_uint(3))

        snap.clock_graphics_max_mhz = self._get_uint(nvml.nvmlDeviceGetMaxClockInfo, dev, ctypes.c_uint(0)) or 2115
        snap.clock_mem_max_mhz = self._get_uint(nvml.nvmlDeviceGetMaxClockInfo, dev, ctypes.c_uint(2)) or 7001

        snap.core_offset_mhz = self._get_clock_offset(0)
        snap.mem_offset_mhz = self._get_clock_offset(2)

        pm = ctypes.c_uint(0)
        if nvml.nvmlDeviceGetPersistenceMode(dev, ctypes.byref(pm)) == 0:
            snap.persistence_mode = bool(pm.value == 1)

        # Kernel sysfs telemetry
        bdf_norm = snap.pci_bus_id.lower()
        if bdf_norm.startswith("00000000:"):
            bdf_norm = bdf_norm[4:]
        if not bdf_norm:
            bdf_norm = "0000:01:00.0"
        snap.pcie_pm_control = self._read_sysfs_str(
            Path(f"/sys/bus/pci/devices/{bdf_norm}/power/control"), "auto"
        )
        rebar_sys = self._read_sysfs_str(
            Path("/sys/module/nvidia/parameters/NVreg_EnableResizableBar"), "0"
        )
        smem_sys = self._read_sysfs_str(
            Path("/sys/module/nvidia/parameters/NVreg_EnableStreamMemOPs"), "0"
        )
        vrr_sys = self._read_sysfs_str(
            Path("/sys/module/nvidia_modeset/parameters/disable_vrr_memclk_switch"), "N"
        )
        snap.kernel_rebar = rebar_sys in ("1", "Y", "y") or snap.bar1_total_mib >= 4096
        snap.kernel_stream_memops = smem_sys in ("1", "Y", "y")
        snap.kernel_vrr_memclk = vrr_sys in ("1", "Y", "y")
        snap.kernel_ntsync = Path("/dev/ntsync").exists()

        if hasattr(nvml, "nvmlDeviceGetCurrentClocksThrottleReasons"):
            mask = ctypes.c_ulonglong(0)
            if nvml.nvmlDeviceGetCurrentClocksThrottleReasons(dev, ctypes.byref(mask)) == 0:
                reasons = []
                for bit, label in THROTTLE_BITS:
                    if mask.value & bit:
                        reasons.append(label)
                snap.throttle_reasons = reasons

        snap.processes = self._query_processes()

        # Update history buffers
        self.hist_gpu_util.append(snap.gpu_util)
        self.hist_temp.append(snap.temp_c)
        self.hist_power.append(snap.power_draw_w)
        self.hist_clock_gfx.append(snap.clock_graphics_mhz)

        return snap

    def _query_processes(self) -> List[GpuProcess]:
        proc_map: Dict[int, GpuProcess] = {}
        nvml = self.nvml
        dev = self.dev

        for fn_name, engine_label in [
            ("nvmlDeviceGetGraphicsRunningProcesses_v3", "Graphics"),
            ("nvmlDeviceGetComputeRunningProcesses_v3", "Compute"),
        ]:
            if not hasattr(nvml, fn_name):
                continue
            fn = getattr(nvml, fn_name)
            count = ctypes.c_uint(64)
            arr = (_NvmlProcessInfoV2 * 64)()
            res = fn(dev, ctypes.byref(count), arr)
            if res == 0 and count.value > 0:
                for i in range(count.value):
                    pid = int(arr[i].pid)
                    raw_mem = int(arr[i].usedGpuMemory)
                    vram_mib = None if raw_mem == NVML_VALUE_NOT_AVAILABLE_ULL else int(raw_mem // (1024 * 1024))
                    name, cmdline = self._read_proc_meta(pid)
                    if pid in proc_map:
                        proc_map[pid].engine = "Graphics+Compute"
                        if vram_mib is not None:
                            proc_map[pid].vram_mib = vram_mib
                    else:
                        proc_map[pid] = GpuProcess(
                            pid=pid,
                            name=name,
                            cmdline=cmdline,
                            engine=engine_label,
                            vram_mib=vram_mib,
                        )

        return sorted(
            proc_map.values(),
            key=lambda p: (p.vram_mib or 0, p.pid),
            reverse=True,
        )

    @staticmethod
    def _read_proc_meta(pid: int) -> Tuple[str, str]:
        name = f"PID {pid}"
        cmdline = ""
        comm_path = Path(f"/proc/{pid}/comm")
        cmd_path = Path(f"/proc/{pid}/cmdline")
        try:
            if comm_path.exists():
                name = comm_path.read_text(encoding="utf-8", errors="replace").strip()
            if cmd_path.exists():
                raw = cmd_path.read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
                cmdline = raw[:120]
        except Exception:
            pass
        return name, cmdline

    def load_tuning_config(self) -> dict:
        default_cfg = {
            "active_preset": "Balanced (Default)",
            "custom_fan_curve_enabled": False,
            "persistence": True,
            "pcie_pm": "on",
            "kernel_rebar": True,
            "kernel_stream_memops": True,
            "kernel_vrr_memclk": False,
            "kernel_ntsync": True,
            "last_applied": {
                "power_limit": 70.0,
                "core_offset": 0,
                "mem_offset": 0,
                "fan_mode": "auto",
                "fan_speed": 50,
            },
            "fan_curve_points": [
                [35, 0],
                [50, 35],
                [65, 60],
                [75, 80],
                [85, 100],
            ],
            "presets": {
                "Silent / Eco": {
                    "power_limit": 45.0,
                    "core_offset": -50,
                    "mem_offset": 0,
                    "fan_mode": "auto",
                    "fan_speed": 40,
                },
                "Balanced (Default)": {
                    "power_limit": 70.0,
                    "core_offset": 0,
                    "mem_offset": 0,
                    "fan_mode": "auto",
                    "fan_speed": 50,
                },
                "Max Performance (OC)": {
                    "power_limit": 70.0,
                    "core_offset": 120,
                    "mem_offset": 400,
                    "fan_mode": "auto",
                    "fan_speed": 75,
                },
                "Smooth Frametimes": {
                    "power_limit": 70.0,
                    "core_offset": 50,
                    "mem_offset": 200,
                    "fan_mode": "auto",
                    "fan_speed": 50,
                },
            },
        }
        if self.presets_file.exists():
            try:
                data = json.loads(self.presets_file.read_text(encoding="utf-8"))
                default_cfg.update(data)
            except Exception:
                pass
        else:
            self.save_tuning_config(default_cfg)
        return default_cfg

    def save_tuning_config(self, cfg: dict):
        try:
            self.presets_file.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def evaluate_fan_curve(points: List[List[int]], temp_c: int) -> int:
        if not points:
            return 50
        pts = sorted(points, key=lambda p: p[0])
        if temp_c <= pts[0][0]:
            return int(pts[0][1])
        if temp_c >= pts[-1][0]:
            return int(pts[-1][1])
        for i in range(len(pts) - 1):
            t0, s0 = pts[i]
            t1, s1 = pts[i + 1]
            if t0 <= temp_c <= t1:
                if t1 == t0:
                    return int(s1)
                ratio = (temp_c - t0) / float(t1 - t0)
                return int(round(s0 + ratio * (s1 - s0)))
        return 50

    def apply_hardware_tuning(
        self,
        power_limit: Optional[float] = None,
        core_offset: Optional[int] = None,
        mem_offset: Optional[int] = None,
        fan_mode: Optional[str] = None,
        fan_speed: Optional[int] = None,
        persistence: Optional[str] = None,
        reset_locked_clocks: bool = False,
        pcie_pm: Optional[str] = None,
        kernel_rebar: Optional[str] = None,
        kernel_stream_memops: Optional[str] = None,
        kernel_vrr_memclk: Optional[str] = None,
        kernel_ntsync: Optional[str] = None,
        kernel_framegen: Optional[str] = None,
        cpu_governor: Optional[str] = None,
    ) -> Tuple[bool, str]:
        helper_path = Path(__file__).resolve().parent / "privileged_helper.py"
        cmd = ["pkexec", "python3", str(helper_path)]
        if power_limit is not None:
            cmd += ["--power-limit", f"{power_limit:.2f}"]
        if core_offset is not None:
            cmd += ["--core-offset", str(int(core_offset))]
        if mem_offset is not None:
            cmd += ["--mem-offset", str(int(mem_offset))]
        if fan_mode is not None:
            cmd += ["--fan-mode", fan_mode]
        if fan_speed is not None:
            cmd += ["--fan-speed", str(int(fan_speed))]
        if persistence is not None:
            cmd += ["--persistence", persistence]
        if reset_locked_clocks:
            cmd += ["--reset-locked-clocks"]
        if pcie_pm is not None:
            cmd += ["--pcie-pm", pcie_pm]
        if kernel_rebar is not None:
            cmd += ["--kernel-rebar", kernel_rebar]
        if kernel_stream_memops is not None:
            cmd += ["--kernel-stream-memops", kernel_stream_memops]
        if kernel_vrr_memclk is not None:
            cmd += ["--kernel-vrr-memclk", kernel_vrr_memclk]
        if kernel_ntsync is not None:
            cmd += ["--kernel-ntsync", kernel_ntsync]
        if kernel_framegen is not None:
            cmd += ["--kernel-framegen", kernel_framegen]
        if cpu_governor is not None:
            cmd += ["--cpu-governor", cpu_governor]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if proc.returncode == 0:
                return True, proc.stdout.strip() or "Settings applied successfully."
            err = (proc.stderr or proc.stdout or f"Exit code {proc.returncode}").strip()
            return False, err
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def get_system_details() -> Dict[str, str]:
        info: Dict[str, str] = {}
        info["OS / Distro"] = "Linux"
        os_rel = Path("/etc/os-release")
        if os_rel.exists():
            for line in os_rel.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("PRETTY_NAME="):
                    info["OS / Distro"] = line.split("=", 1)[1].strip().strip('"')
                    break

        info["Kernel"] = platform.release()
        info["Architecture"] = platform.machine()
        info["Session Type"] = os.environ.get("XDG_SESSION_TYPE", "wayland").upper()
        info["Desktop Environment"] = os.environ.get("XDG_CURRENT_DESKTOP", "GNOME / KDE / Wayland")

        # CPU Model
        cpu_model = "Unknown CPU"
        cpuinfo = Path("/proc/cpuinfo")
        if cpuinfo.exists():
            for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
                if "model name" in line:
                    cpu_model = line.split(":", 1)[1].strip()
                    break
        info["CPU"] = cpu_model

        # Vulkan API version
        try:
            out = subprocess.check_output(
                ["vulkaninfo", "--summary"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3,
            )
            for line in out.splitlines():
                if "apiVersion" in line:
                    info["Vulkan API"] = line.split("=", 1)[1].strip()
                    break
        except Exception:
            info["Vulkan API"] = "Available (NVIDIA ICD)"

        # Check NVIDIA kernel module parameters (modeset, fbdev, pat, dynamic power)
        params_dir = Path("/sys/module/nvidia_drm/parameters")
        drm_flags = []
        if params_dir.exists():
            for p_name in ["modeset", "fbdev", "color_pipeline"]:
                p_file = params_dir / p_name
                if p_file.exists():
                    val = p_file.read_text(encoding="utf-8", errors="replace").strip()
                    drm_flags.append(f"{p_name}={val}")
        info["nvidia-drm Parameters"] = ", ".join(drm_flags) if drm_flags else "Loaded"

        nv_params_dir = Path("/sys/module/nvidia/parameters")
        nv_flags = []
        if nv_params_dir.exists():
            for p_name, short_lbl in [
                ("NVreg_UsePageAttributeTable", "PAT"),
                ("NVreg_DynamicPowerManagement", "DynPM"),
                ("NVreg_PreserveVideoMemoryAllocations", "PreserveVRAM"),
                ("NVreg_EnableResizableBar", "ReBAR"),
                ("NVreg_EnableStreamMemOPs", "StreamMemOPs"),
            ]:
                p_file = nv_params_dir / p_name
                if p_file.exists():
                    val = p_file.read_text(encoding="utf-8", errors="replace").strip()
                    nv_flags.append(f"{short_lbl}={val}")
        info["nvidia.ko Kernel Module"] = ", ".join(nv_flags) if nv_flags else "Loaded"

        ntsync_active = "Active (/dev/ntsync)" if Path("/dev/ntsync").exists() else "Inactive"
        split_lock = "0"
        sl_file = Path("/proc/sys/kernel/split_lock_mitigate")
        if sl_file.exists():
            try:
                split_lock = sl_file.read_text(encoding="utf-8").strip()
            except Exception:
                pass
        info["Kernel Gaming Subsystem"] = f"NTSYNC: {ntsync_active}  •  split_lock_mitigate={split_lock}"

        return info
