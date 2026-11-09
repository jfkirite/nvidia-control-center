"""
Unit and integration tests for Console 30 FPS Mode in NVIDIA Control Center.
Tests MangoHud config, environment exports, display refresh switching across backends,
graceful error handling, and UI component integration with Libadwaita.
"""

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from nvidia_cc.console_mode import (
    ConsoleModeManager,
    DisplayModeInfo,
    PrimaryMonitorState,
)
from nvidia_cc.app import NvidiaControlCenterWindow


class TestConsoleModeBackend(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.tmp_dir.name)

        # Patch paths to test directory
        self.cm = ConsoleModeManager()
        self.cm.config_dir = self.test_dir / ".config" / "nvidia-control-center"
        self.cm.STATE_FILE = self.cm.config_dir / "console_mode_state.json"
        self.cm.MANGOHUD_CONF = self.test_dir / ".config" / "MangoHud" / "MangoHud.conf"
        self.cm.ENV_SCRIPT = self.cm.config_dir / "console_30fps_env.sh"
        self.cm.WRAPPER_SCRIPT = self.test_dir / ".local" / "bin" / "console-30fps-run"
        self.cm.SYSTEMD_ENV = self.test_dir / ".config" / "environment.d" / "30-nvidia-console-mode.conf"

        self.cm.config_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_state_load_and_save(self):
        initial = self.cm.load_state()
        self.assertFalse(initial["enabled"])
        self.assertEqual(initial["target_rate"], 60)

        sample = {
            "enabled": True,
            "target_rate": 120,
            "cached_native_connector": "DP-3",
            "cached_native_mode_id": "1920x1080@144.000",
            "cached_native_rate": 144.0,
        }
        self.cm.save_state(sample)
        loaded = self.cm.load_state()
        self.assertEqual(loaded, sample)

    def test_mangohud_config_create_and_restore(self):
        # 1. Configure ON (fps_limit=30, frametime=1, vsync=1)
        ok, msg = self.cm.configure_mangohud(fps_limit=30, frametime=1, vsync=1)
        self.assertTrue(ok)
        self.assertTrue(self.cm.MANGOHUD_CONF.exists())
        content = self.cm.MANGOHUD_CONF.read_text(encoding="utf-8")
        self.assertIn("fps_limit=30", content)
        self.assertIn("frametime=1", content)
        self.assertIn("vsync=1", content)

        # 2. Configure OFF (fps_limit=0)
        ok2, msg2 = self.cm.configure_mangohud(fps_limit=0, frametime=1, vsync=1)
        self.assertTrue(ok2)
        content2 = self.cm.MANGOHUD_CONF.read_text(encoding="utf-8")
        self.assertIn("fps_limit=0", content2)
        self.assertIn("frametime=1", content2)

    def test_mangohud_config_preserves_existing_keys(self):
        self.cm.MANGOHUD_CONF.parent.mkdir(parents=True, exist_ok=True)
        self.cm.MANGOHUD_CONF.write_text(
            "# Custom settings\ngpu_stats=1\ncpu_stats=1\nfps_limit=144\n",
            encoding="utf-8",
        )

        self.cm.configure_mangohud(fps_limit=30, frametime=1, vsync=1)
        content = self.cm.MANGOHUD_CONF.read_text(encoding="utf-8")
        self.assertIn("gpu_stats=1", content)
        self.assertIn("cpu_stats=1", content)
        self.assertIn("fps_limit=30", content)

    def test_environment_exports_on_and_off(self):
        # Enable exports
        ok, msg = self.cm.update_environment_exports(enabled=True)
        self.assertTrue(ok)
        self.assertTrue(self.cm.ENV_SCRIPT.exists())
        self.assertTrue(self.cm.WRAPPER_SCRIPT.exists())
        self.assertTrue(self.cm.SYSTEMD_ENV.exists())

        script_content = self.cm.ENV_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("export DXVK_FRAME_RATE=30", script_content)
        self.assertIn("export VKD3D_FRAME_RATE=30", script_content)

        wrapper_content = self.cm.WRAPPER_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("export DXVK_FRAME_RATE=30", wrapper_content)
        self.assertTrue(os.access(self.cm.WRAPPER_SCRIPT, os.X_OK))

        self.assertEqual(os.environ.get("DXVK_FRAME_RATE"), "30")
        self.assertEqual(os.environ.get("VKD3D_FRAME_RATE"), "30")

        # Disable exports
        ok2, msg2 = self.cm.update_environment_exports(enabled=False)
        self.assertTrue(ok2)
        self.assertNotIn("DXVK_FRAME_RATE", os.environ)
        self.assertNotIn("VKD3D_FRAME_RATE", os.environ)
        self.assertFalse(self.cm.SYSTEMD_ENV.exists())

    def test_kscreen_display_switching_and_fallback(self):
        sample_state = PrimaryMonitorState(
            connector="DP-1",
            monitor_name="Gaming Monitor",
            current_mode_id="mode-144",
            current_refresh_rate=144.0,
            native_refresh_rate=144.0,
            available_modes=[
                DisplayModeInfo("mode-144", 1920, 1080, 144.0, is_current=True),
                DisplayModeInfo("mode-60", 1920, 1080, 60.0),
            ],
            session_type="wayland",
            backend="kde",
        )

        with patch("shutil.which", return_value="/usr/bin/kscreen-doctor"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

            # Switch to 60Hz
            ok, msg = self.cm._switch_kscreen("DP-1", 60, None, sample_state)
            self.assertTrue(ok)
            mock_run.assert_called_with(
                ["kscreen-doctor", "output.DP-1.mode.mode-60"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            # Switch to 120Hz (falls back to 60Hz since 120Hz is missing)
            ok2, msg2 = self.cm._switch_kscreen("DP-1", 120, None, sample_state)
            self.assertTrue(ok2)
            self.assertIn("Fallen back to 60Hz", msg2)

    def test_xrandr_display_switching_and_fallback(self):
        with patch("shutil.which", return_value="/usr/bin/xrandr"), \
             patch("subprocess.run") as mock_run:
            # First call succeeds
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

            ok, msg = self.cm._switch_xrandr("DP-1", 60)
            self.assertTrue(ok)
            mock_run.assert_called_with(
                ["xrandr", "--output", "DP-1", "--rate", "60"],
                capture_output=True,
                text=True,
                timeout=5,
            )

    def test_graceful_error_handling_when_tools_missing(self):
        with patch("shutil.which", return_value=None):
            ok, msg = self.cm._switch_kscreen(
                "DP-1", 60, "m60",
                PrimaryMonitorState("DP-1", "Mon", "m144", 144.0, 144.0)
            )
            self.assertFalse(ok)
            self.assertIn("not found", msg)

            ok_x, msg_x = self.cm._switch_xrandr("DP-1", 60)
            self.assertFalse(ok_x)
            self.assertIn("not found", msg_x)

    def test_enable_and_disable_console_mode_cycle(self):
        # Mock monitor state
        mock_mon = PrimaryMonitorState(
            connector="DP-3",
            monitor_name="AOC Monitor",
            current_mode_id="1920x1080@144.0",
            current_refresh_rate=144.0,
            native_refresh_rate=144.0,
            available_modes=[
                DisplayModeInfo("1920x1080@144.0", 1920, 1080, 144.0, is_current=True),
                DisplayModeInfo("1920x1080@60.0", 1920, 1080, 60.0),
            ],
            session_type="wayland",
            backend="gnome",
        )

        with patch.object(self.cm, "get_primary_monitor_state", return_value=mock_mon), \
             patch.object(self.cm, "switch_display_refresh", return_value=(True, "Switched to 60Hz")):

            # Enable 60Hz
            ok, summary, warnings = self.cm.enable_console_mode(60)
            self.assertTrue(ok)
            self.assertIn("Console 30 FPS Mode engaged", summary)

            state = self.cm.load_state()
            self.assertTrue(state["enabled"])
            self.assertEqual(state["target_rate"], 60)
            self.assertEqual(state["cached_native_rate"], 144.0)

            # Disable
            ok_d, summary_d, warnings_d = self.cm.disable_console_mode()
            self.assertTrue(ok_d)
            self.assertIn("Restored native high refresh rate", summary_d)

            state_d = self.cm.load_state()
            self.assertFalse(state_d["enabled"])


class TestUIConsoleModeIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Adw.Application(application_id="com.nvidia.test.suite")
        cls.app.register(None)

    def setUp(self):
        self.win = NvidiaControlCenterWindow(self.app)

    def tearDown(self):
        self.win.destroy()

    def test_ui_components_exist(self):
        self.assertIsNotNone(self.win.sw_console_mode)
        self.assertIsNotNone(self.win.dd_pulldown_rate)
        self.assertIsNotNone(self.win.badge_console_mode)
        self.assertIsNotNone(self.win.pill_display_status)
        self.assertIsNotNone(self.win.pill_capper_status)

    def test_ui_toggle_events(self):
        # 1. Initially disabled
        self.win.sw_console_mode.set_active(False)
        self.assertEqual(self.win.badge_console_mode.get_label(), "Native High Refresh")
        self.assertIn("Inactive", self.win.pill_capper_status.get_label())

        # 2. Toggle ON
        self.win.sw_console_mode.set_active(True)
        self.assertTrue(self.win.sw_console_mode.get_active())
        self.assertIn("30 FPS", self.win.badge_console_mode.get_label())
        self.assertIn("Active", self.win.pill_capper_status.get_label())

        # 3. Toggle OFF
        self.win.sw_console_mode.set_active(False)
        self.assertFalse(self.win.sw_console_mode.get_active())
        self.assertEqual(self.win.badge_console_mode.get_label(), "Native High Refresh")
        self.assertIn("Inactive", self.win.pill_capper_status.get_label())

    def test_toast_display_does_not_crash(self):
        # Calling show_toast should execute smoothly without throwing exceptions
        self.win.show_toast("Test warning notice")


if __name__ == "__main__":
    unittest.main()
