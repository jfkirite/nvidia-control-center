"""
Main GTK4 + Libadwaita Application for NVIDIA Control Center on CachyOS Linux.
Styled with a translucent Liquid Glass dark aesthetic and #76b900 emerald accents.
"""

import sys
import threading
from pathlib import Path
from typing import Callable, List, Optional
import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango  # noqa: E402

from .display_backend import DisplayBackend, DisplayOutput  # noqa: E402
from .nvml_backend import GpuSnapshot, NvmlBackend  # noqa: E402
from .profiles import (  # noqa: E402
    DLSS_FG_MODE_MAP,
    OPTISCALER_FG_MODE_MAP,
    DLSS_PRESET_MAP,
    DLSS_SR_MODE_MAP,
    IMAGE_QUALITY_MAP,
    GameProfile,
    ProfileManager,
)
from .widgets import FanCurveEditor, MetricCard, TelemetryGraph  # noqa: E402


NVIDIA_CSS = """
window, .nv-root {
    background-image:
        radial-gradient(circle at 85% 6%, rgba(118, 185, 0, 0.13) 0%, rgba(118, 185, 0, 0.0) 42%),
        radial-gradient(circle at 12% 92%, rgba(28, 168, 235, 0.09) 0%, rgba(28, 168, 235, 0.0) 46%),
        linear-gradient(160deg, #080b10 0%, #0d121a 52%, #070a0e 100%);
    color: #ecf1f8;
}

headerbar.nv-header {
    background-image: linear-gradient(180deg, rgba(26, 33, 46, 0.82) 0%, rgba(15, 20, 29, 0.78) 100%);
    border-bottom: 1px solid rgba(255, 255, 255, 0.10);
    box-shadow: 0 2px 14px rgba(0, 0, 0, 0.35);
    min-height: 44px;
}

.nv-header-title {
    font-size: 13.5px;
    font-weight: 800;
    letter-spacing: 0.4px;
    color: #f4f8fc;
}

.nv-header-sub {
    font-size: 11px;
    font-weight: 600;
    color: #8ee000;
}

.nv-sidebar {
    background-image: linear-gradient(180deg, rgba(22, 28, 39, 0.72) 0%, rgba(13, 17, 25, 0.84) 100%);
    border-right: 1px solid rgba(255, 255, 255, 0.10);
    box-shadow: inset -1px 0 0 rgba(255, 255, 255, 0.04);
    padding: 14px 10px 12px 10px;
}

.nv-brand-box {
    background-image: linear-gradient(135deg, rgba(118, 185, 0, 0.16) 0%, rgba(255, 255, 255, 0.03) 100%);
    border-top: 1px solid rgba(158, 235, 20, 0.32);
    border-left: 1px solid rgba(255, 255, 255, 0.14);
    border-right: 1px solid rgba(255, 255, 255, 0.07);
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 12px;
    padding: 11px 13px;
    margin-bottom: 10px;
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.16);
}

.nv-brand-title {
    font-size: 14.5px;
    font-weight: 800;
    letter-spacing: 0.7px;
    color: #ffffff;
}

.nv-brand-sub {
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.5px;
    color: #8ee000;
}

.nv-nav-btn {
    padding: 9px 12px;
    border-radius: 10px;
    font-weight: 600;
    font-size: 13px;
    color: #b8c3d4;
    background-color: transparent;
    background-image: none;
    border: 1px solid transparent;
    margin-bottom: 3px;
    transition: all 160ms ease;
}

.nv-nav-btn:hover {
    background-image: linear-gradient(135deg, rgba(255, 255, 255, 0.09) 0%, rgba(255, 255, 255, 0.03) 100%);
    border-top: 1px solid rgba(255, 255, 255, 0.16);
    border-left: 1px solid rgba(255, 255, 255, 0.10);
    border-right: 1px solid rgba(255, 255, 255, 0.05);
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    color: #ffffff;
}

.nv-nav-btn-active {
    background-image: linear-gradient(135deg, rgba(118, 185, 0, 0.25) 0%, rgba(118, 185, 0, 0.08) 100%);
    border-top: 1px solid rgba(154, 235, 16, 0.45);
    border-left: 3px solid #88d600;
    border-right: 1px solid rgba(118, 185, 0, 0.22);
    border-bottom: 1px solid rgba(118, 185, 0, 0.16);
    color: #98ee00;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.26), inset 0 1px 0 rgba(255, 255, 255, 0.16);
}

.nv-sidebar-footer {
    background-image: linear-gradient(155deg, rgba(255, 255, 255, 0.07) 0%, rgba(15, 20, 29, 0.65) 100%);
    border-top: 1px solid rgba(255, 255, 255, 0.15);
    border-left: 1px solid rgba(255, 255, 255, 0.10);
    border-right: 1px solid rgba(255, 255, 255, 0.05);
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 11px;
    padding: 9px 11px;
    margin-top: 6px;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.10);
}

.nv-banner {
    background-image: linear-gradient(135deg, rgba(118, 185, 0, 0.16) 0%, rgba(24, 32, 45, 0.78) 46%, rgba(14, 19, 28, 0.88) 100%);
    border-top: 1px solid rgba(156, 236, 22, 0.42);
    border-left: 1px solid rgba(156, 236, 22, 0.28);
    border-right: 1px solid rgba(255, 255, 255, 0.10);
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 15px;
    padding: 15px 18px;
    box-shadow: 0 10px 26px rgba(0, 0, 0, 0.36), inset 0 1px 0 rgba(255, 255, 255, 0.22);
}

.nv-gpu-title {
    font-size: 18.5px;
    font-weight: 800;
    color: #ffffff;
}

.nv-badge {
    background-image: linear-gradient(180deg, rgba(136, 214, 0, 0.26) 0%, rgba(118, 185, 0, 0.14) 100%);
    color: #9bf00a;
    border-top: 1px solid rgba(164, 244, 32, 0.50);
    border-left: 1px solid rgba(140, 220, 12, 0.36);
    border-right: 1px solid rgba(118, 185, 0, 0.28);
    border-bottom: 1px solid rgba(118, 185, 0, 0.22);
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 11.5px;
    font-weight: 700;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.18);
}

.nv-badge-muted {
    background-image: linear-gradient(180deg, rgba(255, 255, 255, 0.10) 0%, rgba(255, 255, 255, 0.04) 100%);
    color: #d0d8e4;
    border-top: 1px solid rgba(255, 255, 255, 0.18);
    border-left: 1px solid rgba(255, 255, 255, 0.12);
    border-right: 1px solid rgba(255, 255, 255, 0.07);
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 11.5px;
    font-weight: 600;
}

.nv-card {
    background-image: linear-gradient(155deg, rgba(32, 41, 56, 0.66) 0%, rgba(20, 26, 37, 0.74) 48%, rgba(13, 18, 26, 0.84) 100%);
    border-top: 1px solid rgba(255, 255, 255, 0.18);
    border-left: 1px solid rgba(255, 255, 255, 0.12);
    border-right: 1px solid rgba(255, 255, 255, 0.07);
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 14px;
    padding: 14px 16px;
    box-shadow: 0 8px 22px rgba(0, 0, 0, 0.32), inset 0 1px 0 rgba(255, 255, 255, 0.14);
    transition: all 160ms ease;
}

.nv-metric-card:hover {
    background-image: linear-gradient(155deg, rgba(38, 49, 66, 0.74) 0%, rgba(23, 30, 42, 0.80) 48%, rgba(15, 21, 30, 0.88) 100%);
    border-top: 1px solid rgba(156, 236, 22, 0.36);
}

.nv-card-dot {
    background-color: #84cf00;
    border-radius: 4px;
    box-shadow: 0 0 6px rgba(132, 207, 0, 0.65);
}

.nv-card-title {
    font-size: 11.5px;
    font-weight: 800;
    color: #9facbf;
    letter-spacing: 0.5px;
}

.nv-card-value {
    font-size: 21px;
    font-weight: 800;
    color: #ffffff;
}

.nv-card-sub {
    font-size: 11.5px;
    color: #93a0b4;
}

.nv-section-title {
    font-size: 14px;
    font-weight: 700;
    color: #f2f6fb;
}

.nv-primary-btn {
    background-image: linear-gradient(180deg, #8ee000 0%, #76b900 55%, #5f9600 100%);
    color: #070a0d;
    font-weight: 800;
    border-radius: 10px;
    padding: 8px 16px;
    border-top: 1px solid rgba(215, 255, 128, 0.65);
    border-left: 1px solid rgba(180, 245, 70, 0.45);
    border-right: 1px solid rgba(90, 145, 0, 0.6);
    border-bottom: 1px solid rgba(70, 115, 0, 0.8);
    box-shadow: 0 4px 14px rgba(118, 185, 0, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.35);
    transition: all 150ms ease;
}

.nv-primary-btn:hover {
    background-image: linear-gradient(180deg, #9cf00a 0%, #82cc00 55%, #6ba800 100%);
    box-shadow: 0 6px 18px rgba(132, 207, 0, 0.38), inset 0 1px 0 rgba(255, 255, 255, 0.45);
}

.nv-secondary-btn {
    background-image: linear-gradient(180deg, rgba(255, 255, 255, 0.11) 0%, rgba(255, 255, 255, 0.04) 100%);
    color: #e6ecf5;
    font-weight: 600;
    border-radius: 10px;
    padding: 7px 13px;
    border-top: 1px solid rgba(255, 255, 255, 0.20);
    border-left: 1px solid rgba(255, 255, 255, 0.14);
    border-right: 1px solid rgba(255, 255, 255, 0.08);
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    box-shadow: 0 3px 10px rgba(0, 0, 0, 0.22), inset 0 1px 0 rgba(255, 255, 255, 0.12);
    transition: all 150ms ease;
}

.nv-secondary-btn:hover {
    background-image: linear-gradient(180deg, rgba(255, 255, 255, 0.17) 0%, rgba(255, 255, 255, 0.07) 100%);
    border-top: 1px solid rgba(255, 255, 255, 0.28);
    color: #ffffff;
}

.nv-preset-btn-active {
    background-image: linear-gradient(180deg, rgba(136, 214, 0, 0.28) 0%, rgba(118, 185, 0, 0.14) 100%);
    border-top: 1px solid rgba(164, 244, 32, 0.55);
    border-left: 1px solid rgba(140, 220, 12, 0.40);
    border-right: 1px solid rgba(118, 185, 0, 0.30);
    border-bottom: 1px solid rgba(118, 185, 0, 0.24);
    color: #9bf00a;
}

.nv-progress trough {
    min-height: 7px;
    border-radius: 5px;
    background-color: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.06);
}

.nv-progress progress {
    min-height: 7px;
    border-radius: 5px;
    background-image: linear-gradient(90deg, #68a800 0%, #8ee000 100%);
    box-shadow: 0 0 8px rgba(132, 207, 0, 0.45);
}

scale trough {
    min-height: 6px;
    border-radius: 4px;
    background-color: rgba(255, 255, 255, 0.09);
}

scale highlight {
    min-height: 6px;
    border-radius: 4px;
    background-image: linear-gradient(90deg, #66a300 0%, #8ee000 100%);
}

scale slider {
    min-width: 16px;
    min-height: 16px;
    border-radius: 8px;
    background-image: linear-gradient(180deg, #ffffff 0%, #d9e2ec 100%);
    border: 2px solid #76b900;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.45);
}

dropdown > button {
    background-image: linear-gradient(180deg, rgba(255, 255, 255, 0.10) 0%, rgba(255, 255, 255, 0.04) 100%);
    border-top: 1px solid rgba(255, 255, 255, 0.18);
    border-left: 1px solid rgba(255, 255, 255, 0.12);
    border-right: 1px solid rgba(255, 255, 255, 0.08);
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 9px;
    padding: 5px 10px;
}

entry {
    background-color: rgba(10, 14, 20, 0.65);
    border-top: 1px solid rgba(255, 255, 255, 0.16);
    border-left: 1px solid rgba(255, 255, 255, 0.10);
    border-right: 1px solid rgba(255, 255, 255, 0.08);
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 9px;
    color: #f0f4f8;
}

.nv-row-divider {
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    padding-bottom: 8px;
}

.nv-status-ok {
    color: #96ec00;
    font-weight: 700;
}

.nv-paned > separator {
    background-color: rgba(255, 255, 255, 0.08);
    min-width: 1px;
}

.nv-setting-row {
    padding: 6px 8px;
    border-radius: 9px;
    transition: background-color 150ms ease;
}

.nv-setting-row:hover {
    background-color: rgba(255, 255, 255, 0.04);
}

.nv-setting-title {
    font-size: 13px;
    font-weight: 600;
    color: #e2e8f0;
}

.nv-info-icon {
    opacity: 0.38;
    color: #9facbf;
    transition: opacity 150ms ease, color 150ms ease;
}

.nv-info-icon:hover {
    opacity: 0.95;
    color: #9bf00a;
}

.nv-card-value-small {
    font-size: 12.5px;
    font-weight: 700;
    color: #9bf00a;
}

.nv-smooth-card {
    background-image:
        radial-gradient(circle at 92% 10%, rgba(118, 185, 0, 0.16) 0%, rgba(118, 185, 0, 0.0) 50%),
        linear-gradient(155deg, rgba(32, 48, 56, 0.72) 0%, rgba(20, 30, 38, 0.82) 48%, rgba(13, 20, 26, 0.92) 100%);
    border-top: 1px solid rgba(156, 236, 22, 0.45);
    border-left: 1px solid rgba(156, 236, 22, 0.32);
    border-right: 1px solid rgba(118, 185, 0, 0.18);
    border-bottom: 1px solid rgba(118, 185, 0, 0.15);
    border-radius: 14px;
    padding: 14px 16px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.38), inset 0 1px 0 rgba(255, 255, 255, 0.20);
    transition: all 160ms ease;
}
"""


def _disable_scale_scroll(scale: Gtk.Scale):
    """Prevents Gtk.Scale from hijacking mouse-wheel page scrolling inside ScrolledWindow."""
    ctrl_list = scale.observe_controllers()
    for i in range(ctrl_list.get_n_items()):
        ctrl = ctrl_list.get_item(i)
        if isinstance(ctrl, Gtk.EventControllerScroll):
            ctrl.set_propagation_phase(Gtk.PropagationPhase.NONE)


def _make_ellipsizing_dropdown(items: List[str], max_chars: int = 28) -> Gtk.DropDown:
    """Creates a Gtk.DropDown whose button label ellipsizes cleanly when resized narrow."""
    dd = Gtk.DropDown.new_from_strings(items)
    list_factory = dd.get_factory()
    if list_factory is not None:
        dd.set_list_factory(list_factory)

    btn_factory = Gtk.SignalListItemFactory()

    def _on_setup(_f, list_item):
        lbl = Gtk.Label(xalign=0.0)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        lbl.set_width_chars(10)
        lbl.set_max_width_chars(max_chars)
        list_item.set_child(lbl)

    def _on_bind(_f, list_item):
        lbl = list_item.get_child()
        obj = list_item.get_item()
        if lbl is not None and obj is not None:
            lbl.set_label(obj.get_string())

    btn_factory.connect("setup", _on_setup)
    btn_factory.connect("bind", _on_bind)
    dd.set_factory(btn_factory)
    return dd


class NvidiaControlCenterWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="NVIDIA Control Center")
        self.set_default_size(1140, 740)
        self.set_size_request(680, 480)

        self.nvml = NvmlBackend(history_len=60)
        self.profiles_mgr = ProfileManager()
        self.display_mgr = DisplayBackend()
        self.tuning_cfg = self.nvml.load_tuning_config()
        self.last_snap: GpuSnapshot = self.nvml.poll()
        self.selected_profile: GameProfile = self.profiles_mgr.list_profiles()[0]

        self._updating_profile_ui = False
        self._last_curve_fan_speed: Optional[int] = None
        self._fan_apply_in_flight: bool = False
        self._last_proc_signature: Optional[list] = None
        self._profile_sync_timer_id: Optional[int] = None
        self._telemetry_timer_id: Optional[int] = None
        self._is_compact_layout: bool = False

        self._apply_css()
        self._build_ui()
        self._setup_responsive_breakpoints()
        self._refresh_telemetry()

        self._telemetry_timer_id = GLib.timeout_add(1000, self._on_timer_tick)
        self.connect("close-request", self._on_close_request)

    def _on_close_request(self, _win) -> bool:
        if self._telemetry_timer_id is not None:
            GLib.source_remove(self._telemetry_timer_id)
            self._telemetry_timer_id = None
        if self._profile_sync_timer_id is not None:
            GLib.source_remove(self._profile_sync_timer_id)
            self._profile_sync_timer_id = None
        self.nvml.shutdown()
        return False

    def _apply_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(NVIDIA_CSS.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _build_ui(self):
        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root_box.add_css_class("nv-root")

        header = Adw.HeaderBar()
        header.add_css_class("nv-header")

        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title_box.set_valign(Gtk.Align.CENTER)
        hdr_title = Gtk.Label(label="NVIDIA Control Center")
        hdr_title.add_css_class("nv-header-title")
        hdr_sep = Gtk.Label(label="•")
        hdr_sep.add_css_class("nv-card-sub")
        hdr_sub = Gtk.Label(label="Liquid Glass Linux Edition")
        hdr_sub.add_css_class("nv-header-sub")
        title_box.append(hdr_title)
        title_box.append(hdr_sep)
        title_box.append(hdr_sub)
        header.set_title_widget(title_box)

        root_box.append(header)

        body_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        body_box.set_vexpand(True)
        body_box.set_hexpand(True)
        root_box.append(body_box)

        # Left Liquid Glass Navigation Sidebar
        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.sidebar.set_size_request(218, -1)
        self.sidebar.add_css_class("nv-sidebar")

        brand_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        brand_box.add_css_class("nv-brand-box")
        lbl_t = Gtk.Label(label="GEFORCE RTX", xalign=0)
        lbl_t.add_css_class("nv-brand-title")
        lbl_t.set_ellipsize(Pango.EllipsizeMode.END)
        self.lbl_brand_sub = Gtk.Label(label=f"DRIVER {self.last_snap.driver_version or 'NVML'}", xalign=0)
        self.lbl_brand_sub.add_css_class("nv-brand-sub")
        self.lbl_brand_sub.set_ellipsize(Pango.EllipsizeMode.END)
        brand_box.append(lbl_t)
        brand_box.append(self.lbl_brand_sub)
        self.sidebar.append(brand_box)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(140)
        self.stack.set_hhomogeneous(False)
        self.stack.set_vhomogeneous(False)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)

        self.nav_buttons = {}
        nav_items = [
            ("dashboard", "Dashboard", "speedometer-symbolic"),
            ("profiles", "Game Profiles & DLSS", "applications-games-symbolic"),
            ("tuning", "Performance & Tuning", "preferences-system-symbolic"),
            ("display", "Display & Color", "display-brightness-symbolic"),
            ("system", "System & Driver", "computer-symbolic"),
        ]

        for page_id, title, icon_name in nav_items:
            btn = Gtk.Button()
            btn.set_halign(Gtk.Align.FILL)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.set_pixel_size(16)
            lbl = Gtk.Label(label=title, xalign=0.0)
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            lbl.set_hexpand(True)
            row.append(icon)
            row.append(lbl)
            btn.set_child(row)
            btn.add_css_class("nv-nav-btn")
            btn.connect("clicked", self._on_nav_clicked, page_id)
            self.sidebar.append(btn)
            self.nav_buttons[page_id] = btn

        sidebar_spacer = Gtk.Box()
        sidebar_spacer.set_vexpand(True)
        self.sidebar.append(sidebar_spacer)

        # Liquid Glass mini live telemetry footer in sidebar
        footer_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        footer_card.add_css_class("nv-sidebar-footer")
        footer_hdr = Gtk.Label(label="LIVE GPU STATUS", xalign=0)
        footer_hdr.add_css_class("nv-card-title")
        self.sidebar_mini_lbl = Gtk.Label(label="", xalign=0)
        self.sidebar_mini_lbl.add_css_class("nv-card-sub")
        self.sidebar_mini_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.sidebar_mini_bar = Gtk.ProgressBar()
        self.sidebar_mini_bar.add_css_class("nv-progress")
        footer_card.append(footer_hdr)
        footer_card.append(self.sidebar_mini_lbl)
        footer_card.append(self.sidebar_mini_bar)
        self.sidebar.append(footer_card)

        body_box.append(self.sidebar)
        body_box.append(self.stack)

        # Build the 5 unified stack pages
        self.stack.add_named(self._build_dashboard_page(), "dashboard")
        self.stack.add_named(self._build_profiles_page(), "profiles")
        self.stack.add_named(self._build_tuning_page(), "tuning")
        self.stack.add_named(self._build_display_page(), "display")
        self.stack.add_named(self._build_system_page(), "system")

        self._set_active_nav("dashboard")
        self.set_content(root_box)

    def _setup_responsive_breakpoints(self):
        """Configures Libadwaita responsive breakpoint so narrow/tiled windows reflow smoothly."""
        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 920sp"))
        bp.connect("apply", self._on_compact_breakpoint_apply)
        bp.connect("unapply", self._on_compact_breakpoint_unapply)
        self.add_breakpoint(bp)

    def _on_compact_breakpoint_apply(self, _bp):
        if self._is_compact_layout:
            return
        self._is_compact_layout = True
        self.sidebar.set_size_request(176, -1)

        # Reflow 4 metric cards into 2x2 grid
        for idx, card in enumerate(self.metric_cards):
            self.cards_grid.remove(card)
            self.cards_grid.attach(card, idx % 2, idx // 2, 1, 1)

        # Reflow bottom diagnostics row into 1-column stack
        self.bottom_grid.remove(self.diag_card)
        self.bottom_grid.attach(self.diag_card, 0, 1, 1, 1)

        if hasattr(self, "profiles_paned"):
            self.profiles_paned.set_position(190)

    def _on_compact_breakpoint_unapply(self, _bp):
        if not self._is_compact_layout:
            return
        self._is_compact_layout = False
        self.sidebar.set_size_request(218, -1)

        # Restore 4 metric cards to 4x1 row
        for idx, card in enumerate(self.metric_cards):
            self.cards_grid.remove(card)
            self.cards_grid.attach(card, idx, 0, 1, 1)

        # Restore bottom diagnostics row to 2 columns
        self.bottom_grid.remove(self.diag_card)
        self.bottom_grid.attach(self.diag_card, 1, 0, 1, 1)

        if hasattr(self, "profiles_paned"):
            self.profiles_paned.set_position(235)

    def _on_nav_clicked(self, _btn, page_id: str):
        self._set_active_nav(page_id)

    def _set_active_nav(self, page_id: str):
        self.stack.set_visible_child_name(page_id)
        for pid, btn in self.nav_buttons.items():
            if pid == page_id:
                btn.add_css_class("nv-nav-btn-active")
            else:
                btn.remove_css_class("nv-nav-btn-active")

    # ------------------------------------------------------------------
    # PAGE 1: DASHBOARD & TELEMETRY
    # ------------------------------------------------------------------
    def _build_dashboard_page(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_top(16)
        box.set_margin_bottom(18)
        box.set_margin_start(18)
        box.set_margin_end(18)

        # GPU Hero Banner
        banner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        banner.add_css_class("nv-banner")

        left_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        left_col.set_hexpand(True)
        self.lbl_gpu_name = Gtk.Label(label=self.last_snap.name, xalign=0)
        self.lbl_gpu_name.add_css_class("nv-gpu-title")
        self.lbl_gpu_name.set_ellipsize(Pango.EllipsizeMode.END)
        self.lbl_gpu_sub = Gtk.Label(label="", xalign=0)
        self.lbl_gpu_sub.add_css_class("nv-card-sub")
        self.lbl_gpu_sub.set_ellipsize(Pango.EllipsizeMode.END)
        left_col.append(self.lbl_gpu_name)
        left_col.append(self.lbl_gpu_sub)
        banner.append(left_col)

        badges_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        badges_box.set_valign(Gtk.Align.CENTER)
        self.badge_pstate = Gtk.Label(label="P0")
        self.badge_pstate.add_css_class("nv-badge")
        self.badge_pcie = Gtk.Label(label="PCIe Gen 4")
        self.badge_pcie.add_css_class("nv-badge-muted")
        self.badge_driver = Gtk.Label(label="Driver")
        self.badge_driver.add_css_class("nv-badge-muted")
        badges_box.append(self.badge_pstate)
        badges_box.append(self.badge_pcie)
        badges_box.append(self.badge_driver)
        banner.append(badges_box)

        box.append(banner)

        # 4 Top Metric Cards (Reflows 4x1 <-> 2x2 via Breakpoint)
        self.cards_grid = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)
        self.card_gpu = MetricCard("GPU UTILIZATION", "0%")
        self.card_vram = MetricCard("VRAM MEMORY", "0 MiB")
        self.card_temp = MetricCard("THERMAL & FAN", "0°C")
        self.card_power = MetricCard("POWER & CLOCKS", "0 W")
        self.metric_cards = [self.card_gpu, self.card_vram, self.card_temp, self.card_power]
        for idx, card in enumerate(self.metric_cards):
            self.cards_grid.attach(card, idx, 0, 1, 1)
        box.append(self.cards_grid)

        # 4 Real-Time Liquid Glass Cairo Graphs (2x2 Grid)
        graphs_grid = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)
        self.graph_util = TelemetryGraph(
            "GPU Load (%)", unit="%", min_val=0, max_val=100, rgb=(0.463, 0.725, 0.0)
        )
        self.graph_clocks = TelemetryGraph(
            "Graphics Core Clock (MHz)",
            unit="MHz",
            min_val=0,
            max_val=max(2100, self.last_snap.clock_graphics_max_mhz),
            rgb=(0.18, 0.72, 0.96),
        )
        self.graph_temp = TelemetryGraph(
            "GPU Temperature (°C)", unit="°C", min_val=20, max_val=95, rgb=(0.98, 0.58, 0.16)
        )
        self.graph_power = TelemetryGraph(
            "GPU Power Draw (W)",
            unit="W",
            min_val=0,
            max_val=max(75.0, self.last_snap.power_max_w),
            rgb=(0.68, 0.45, 0.98),
        )
        graphs_grid.attach(self.graph_util, 0, 0, 1, 1)
        graphs_grid.attach(self.graph_clocks, 1, 0, 1, 1)
        graphs_grid.attach(self.graph_temp, 0, 1, 1, 1)
        graphs_grid.attach(self.graph_power, 1, 1, 1, 1)
        box.append(graphs_grid)

        # Active GPU Processes & Throttle Status Row
        self.bottom_grid = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=False)

        self.proc_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.proc_card.add_css_class("nv-card")
        self.proc_card.set_hexpand(True)
        proc_hdr = Gtk.Label(label="ACTIVE GPU PROCESSES (GRAPHICS & COMPUTE)", xalign=0)
        proc_hdr.add_css_class("nv-card-title")
        proc_hdr.set_ellipsize(Pango.EllipsizeMode.END)
        self.proc_card.append(proc_hdr)

        self.proc_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.proc_card.append(self.proc_list_box)
        self.bottom_grid.attach(self.proc_card, 0, 0, 1, 1)

        self.diag_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.diag_card.add_css_class("nv-card")
        self.diag_card.set_hexpand(True)
        diag_hdr = Gtk.Label(label="CLOCK LIMITERS & BUS TELEMETRY", xalign=0)
        diag_hdr.add_css_class("nv-card-title")
        diag_hdr.set_ellipsize(Pango.EllipsizeMode.END)
        self.diag_card.append(diag_hdr)

        self.lbl_throttle = Gtk.Label(label="", xalign=0, wrap=True)
        self.lbl_throttle.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.lbl_throttle.set_hexpand(True)
        self.lbl_throttle.add_css_class("nv-card-sub")
        self.diag_card.append(self.lbl_throttle)

        self.lbl_bus_stats = Gtk.Label(label="", xalign=0, wrap=True)
        self.lbl_bus_stats.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.lbl_bus_stats.set_hexpand(True)
        self.lbl_bus_stats.add_css_class("nv-card-sub")
        self.diag_card.append(self.lbl_bus_stats)

        self.bottom_grid.attach(self.diag_card, 1, 0, 1, 1)
        box.append(self.bottom_grid)

        scroll.set_child(box)
        return scroll

    # ------------------------------------------------------------------
    # PAGE 2: PERFORMANCE & TUNING
    # ------------------------------------------------------------------
    def _build_tuning_page(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_top(16)
        box.set_margin_bottom(18)
        box.set_margin_start(18)
        box.set_margin_end(18)

        # Top Preset Bar
        preset_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        preset_card.add_css_class("nv-card")
        lbl_p = Gtk.Label(label="Tuning Preset:", xalign=0)
        lbl_p.add_css_class("nv-section-title")
        lbl_p.set_ellipsize(Pango.EllipsizeMode.END)
        lbl_p.set_hexpand(True)
        preset_card.append(lbl_p)

        self.preset_buttons = {}
        active_preset = self.tuning_cfg.get("active_preset", "Balanced (Default)")
        for preset_name in ["Silent / Eco", "Balanced (Default)", "Max Performance (OC)", "Smooth Frametimes"]:
            b = Gtk.Button(label=preset_name)
            b.add_css_class("nv-secondary-btn")
            if preset_name == active_preset:
                b.add_css_class("nv-preset-btn-active")
            b.connect("clicked", self._on_load_tuning_preset, preset_name)
            preset_card.append(b)
            self.preset_buttons[preset_name] = b

        box.append(preset_card)

        # Sliders Card (Power Limit, Core Offset, Memory Offset, Persistence)
        oc_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        oc_card.add_css_class("nv-card")

        oc_hdr = Gtk.Label(label="GPU POWER & CLOCK FREQUENCY OFFSETS (NVML DIRECT)", xalign=0)
        oc_hdr.add_css_class("nv-card-title")
        oc_hdr.set_ellipsize(Pango.EllipsizeMode.END)
        oc_card.append(oc_hdr)

        p_min = min(20.0, self.last_snap.power_min_w)
        p_max = max(70.0, self.last_snap.power_max_w)
        p_cur = self.last_snap.power_limit_w or self.last_snap.power_default_w
        self.scale_power, row_pwr = self._create_slider_row(
            f"Power Limit ({p_min:.0f}W – {p_max:.0f}W)",
            p_min,
            p_max,
            1.0,
            p_cur,
            "W",
            tooltip=(
                "<b>GPU Power Limit (Watts)</b>\n"
                "Controls the maximum electrical power budget for the GPU. Higher limits allow boost clocks to stay sustained during demanding 3D games.\n\n"
                f"<small>Default: {self.last_snap.power_default_w:.0f}W</small>"
            ),
        )
        oc_card.append(row_pwr)

        self.scale_core_offset, row_core = self._create_slider_row(
            "Core Clock Offset",
            -400,
            300,
            5,
            self.last_snap.core_offset_mhz,
            "MHz",
            signed=True,
            tooltip=(
                "<b>GPU Core Clock Offset (MHz)</b>\n"
                "Adjusts the graphics core frequency above or below factory specification. A moderate boost (+50 to +120 MHz) safely provides extra framerates without instability."
            ),
        )
        oc_card.append(row_core)

        self.scale_mem_offset, row_mem = self._create_slider_row(
            "Memory Clock Offset",
            -1000,
            1500,
            25,
            self.last_snap.mem_offset_mhz,
            "MHz",
            signed=True,
            tooltip=(
                "<b>VRAM Video Memory Frequency Offset (MHz)</b>\n"
                "Increases video memory transfer speeds (+200 to +500 MHz), speeding up texture streaming and high-resolution rendering."
            ),
        )
        oc_card.append(row_mem)

        self.sw_persistence = self._add_toggle_row(
            oc_card,
            "Driver Persistence Mode",
            tooltip=(
                "<b>NVIDIA Driver Persistence Daemon</b>\n"
                "Keeps the GPU driver loaded in kernel memory continuously. Eliminates startup lag and driver unloading hitches when launching or closing games."
            ),
        )
        self.sw_persistence.set_active(
            self.last_snap.persistence_mode or bool(self.tuning_cfg.get("persistence", True))
        )

        box.append(oc_card)

        # Kernel & Driver Level Parameters Card
        kern_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        kern_card.add_css_class("nv-card")

        kern_hdr = Gtk.Label(
            label="LINUX KERNEL MODULE, PCIE BUS & GAMING SUBSYSTEM TUNING",
            xalign=0,
        )
        kern_hdr.add_css_class("nv-card-title")
        kern_hdr.set_ellipsize(Pango.EllipsizeMode.END)
        kern_card.append(kern_hdr)

        self.sw_kernel_pcie_pm = self._add_toggle_row(
            kern_card,
            "PCIe Full Performance Mode",
            tooltip=(
                "<b>PCIe Bus Power Management (power/control=on)</b>\n"
                "Locks the PCIe bus at maximum link performance, preventing latency spikes caused by power saving downclocking during gameplay."
            ),
        )
        self.sw_kernel_pcie_pm.set_active(
            self.last_snap.pcie_pm_control == "on" or self.tuning_cfg.get("pcie_pm", "on") == "on"
        )

        self.sw_kernel_rebar = self._add_toggle_row(
            kern_card,
            "Kernel Resizable BAR",
            tooltip=(
                "<b>Resizable BAR Support (NVreg_EnableResizableBar=1)</b>\n"
                "Allows the CPU full, simultaneous access to all GPU video memory, cutting asset streaming bottlenecks in modern games."
            ),
        )
        self.sw_kernel_rebar.set_active(
            self.last_snap.kernel_rebar or bool(self.tuning_cfg.get("kernel_rebar", True))
        )

        self.sw_kernel_stream_memops = self._add_toggle_row(
            kern_card,
            "Stream Memory & Relaxed Ordering",
            tooltip=(
                "<b>Direct Memory Operations (NVreg_EnableStreamMemOPs=1)</b>\n"
                "Enables hardware-level low-latency stream memory operations and relaxed PCIe ordering for smoother Vulkan and DirectX 12 performance."
            ),
        )
        self.sw_kernel_stream_memops.set_active(
            self.last_snap.kernel_stream_memops or bool(self.tuning_cfg.get("kernel_stream_memops", True))
        )

        self.sw_kernel_vrr_memclk = self._add_toggle_row(
            kern_card,
            "Lock VRAM Clock in VRR",
            tooltip=(
                "<b>VRAM Frequency Stabilization (disable_vrr_memclk_switch=1)</b>\n"
                "Prevents video memory clocks from changing P-states when display refresh rates change dynamically, eliminating screen flicker and stutter."
            ),
        )
        self.sw_kernel_vrr_memclk.set_active(
            self.last_snap.kernel_vrr_memclk or bool(self.tuning_cfg.get("kernel_vrr_memclk", False))
        )

        self.sw_kernel_ntsync = self._add_toggle_row(
            kern_card,
            "Kernel NTSYNC & Split-Lock Off",
            tooltip=(
                "<b>In-Kernel NT Synchronization & Bus Lock Mitigation</b>\n"
                "Loads the Linux kernel /dev/ntsync driver for Steam Proton and sets kernel.split_lock_mitigate=0, eliminating wine lock delays and severe CPU micro-stutter."
            ),
        )
        self.sw_kernel_ntsync.set_active(
            self.last_snap.kernel_ntsync or bool(self.tuning_cfg.get("kernel_ntsync", True))
        )

        self.sw_kernel_framegen = self._add_toggle_row(
            kern_card,
            "Kernel OptiScaler Frame Gen",
            tooltip=(
                "<b>Kernel-Level OptiScaler Frame Generation Infrastructure</b>\n"
                "Synchronizes the Linux kernel module, PCIe bus, and Proton runtime parameters for zero-stutter AI frame interpolation:\n"
                "• Enforces PCIe Maximum Performance Mode\n"
                "• Enables NVreg_EnableStreamMemOPs & PCIE Relaxed Ordering\n"
                "• Activates in-kernel NTSYNC (/dev/ntsync) low-latency pacing\n"
                "• Sets kernel.split_lock_mitigate=0 for jitter-free presentation\n"
                "• Persists system-wide OptiScaler Frame Generation environment"
            ),
        )
        self.sw_kernel_framegen.set_active(
            bool(self.tuning_cfg.get("kernel_framegen", True))
        )

        box.append(kern_card)

        # Fan Control & Interactive Curve Card (Only shows controls relevant to active mode)
        fan_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        fan_card.add_css_class("nv-card")

        fan_hdr_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        fan_hdr = Gtk.Label(label="THERMAL & FAN CONTROL POLICY", xalign=0)
        fan_hdr.add_css_class("nv-card-title")
        fan_hdr.set_ellipsize(Pango.EllipsizeMode.END)
        fan_hdr.set_hexpand(True)
        fan_hdr_box.append(fan_hdr)

        self.dd_fan_mode = _make_ellipsizing_dropdown(
            [
                "Automatic (Hardware VBIOS Curve)",
                "Manual Fixed Fan Speed (%)",
                "Custom Interactive Software Curve",
            ],
            max_chars=30,
        )
        if self.tuning_cfg.get("custom_fan_curve_enabled"):
            self.dd_fan_mode.set_selected(2)
        elif self.last_snap.fan_policy == 1:
            self.dd_fan_mode.set_selected(1)
        else:
            self.dd_fan_mode.set_selected(0)
        self.dd_fan_mode.connect("notify::selected", self._on_fan_mode_changed)
        fan_hdr_box.append(self.dd_fan_mode)
        fan_card.append(fan_hdr_box)

        self.lbl_fan_auto_hint = Gtk.Label(
            label="GPU firmware (VBIOS) is automatically managing acoustic & thermal fan curves.",
            xalign=0,
            wrap=True,
        )
        self.lbl_fan_auto_hint.add_css_class("nv-card-sub")
        fan_card.append(self.lbl_fan_auto_hint)

        self.scale_fan_speed, self.row_fan_spd = self._create_slider_row(
            "Manual Target Fan Speed",
            0,
            100,
            5,
            self.last_snap.fan_speeds[0] if self.last_snap.fan_speeds else 50,
            "%",
        )
        fan_card.append(self.row_fan_spd)

        self.fan_curve_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        curve_lbl = Gtk.Label(
            label="Interactive 5-Point Fan Curve (Drag glowing nodes — dashed amber line shows live GPU temp):",
            xalign=0,
            wrap=True,
        )
        curve_lbl.add_css_class("nv-card-sub")
        self.fan_curve_box.append(curve_lbl)

        self.fan_curve_editor = FanCurveEditor(
            self.tuning_cfg.get("fan_curve_points", [[35, 0], [50, 35], [65, 60], [75, 80], [85, 100]]),
            self._on_fan_curve_updated,
        )
        self.fan_curve_box.append(self.fan_curve_editor)
        fan_card.append(self.fan_curve_box)

        self._update_fan_mode_visibility()
        box.append(fan_card)

        # Action Bar (Apply via pkexec & Reset)
        act_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        act_box.add_css_class("nv-card")
        self.lbl_tuning_status = Gtk.Label(
            label="Ready. Hardware power, clock & fan limits are applied via PolicyKit (pkexec).",
            xalign=0,
            wrap=True,
        )
        self.lbl_tuning_status.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.lbl_tuning_status.add_css_class("nv-card-sub")
        self.lbl_tuning_status.set_hexpand(True)
        act_box.append(self.lbl_tuning_status)

        btn_reset = Gtk.Button(label="Reset Defaults")
        btn_reset.set_valign(Gtk.Align.CENTER)
        btn_reset.add_css_class("nv-secondary-btn")
        btn_reset.connect("clicked", self._on_reset_tuning_clicked)
        act_box.append(btn_reset)

        btn_apply = Gtk.Button(label="Apply Hardware Tuning")
        btn_apply.set_valign(Gtk.Align.CENTER)
        btn_apply.add_css_class("nv-primary-btn")
        btn_apply.connect("clicked", self._on_apply_tuning_clicked)
        act_box.append(btn_apply)

        box.append(act_box)

        scroll.set_child(box)
        return scroll

    def _update_fan_mode_visibility(self):
        idx = self.dd_fan_mode.get_selected()
        self.lbl_fan_auto_hint.set_visible(idx == 0)
        self.row_fan_spd.set_visible(idx == 1)
        self.fan_curve_box.set_visible(idx == 2)

    def _create_slider_row(
        self,
        title: str,
        min_v: float,
        max_v: float,
        step: float,
        cur_v: float,
        unit: str,
        signed: bool = False,
        tooltip: Optional[str] = None,
    ):
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        row.add_css_class("nv-setting-row")

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top.set_valign(Gtk.Align.CENTER)

        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title_box.set_hexpand(True)
        title_box.set_valign(Gtk.Align.CENTER)

        lbl = Gtk.Label(label=title, xalign=0)
        lbl.add_css_class("nv-setting-title")
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        title_box.append(lbl)

        if tooltip:
            info_icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
            info_icon.set_pixel_size(14)
            info_icon.add_css_class("nv-info-icon")
            info_icon.set_valign(Gtk.Align.CENTER)
            title_box.append(info_icon)

        top.append(title_box)

        def _fmt(v: float) -> str:
            iv = int(round(v))
            num = f"{iv:+d}" if (signed and iv != 0) else f"{iv}"
            return f"{num} {unit}".strip()

        val_lbl = Gtk.Label(label=_fmt(cur_v), xalign=1)
        val_lbl.add_css_class("nv-card-value-small")
        top.append(val_lbl)
        row.append(top)

        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, min_v, max_v, step)
        scale.set_value(cur_v)
        scale.set_draw_value(False)
        scale.set_hexpand(True)
        _disable_scale_scroll(scale)
        scale.connect("value-changed", lambda s: val_lbl.set_label(_fmt(s.get_value())))
        row.append(scale)

        if tooltip:
            row.set_tooltip_markup(tooltip)
            scale.set_tooltip_markup(tooltip)

        return scale, row

    def _on_load_tuning_preset(self, _btn, preset_name: str):
        presets = self.tuning_cfg.get("presets", {})
        p = presets.get(preset_name)
        if preset_name == "Smooth Frametimes" and not p:
            p = {
                "power_limit": self.last_snap.power_default_w,
                "core_offset": 50,
                "mem_offset": 200,
                "fan_mode": "auto",
                "fan_speed": 50,
            }
        if not p:
            return
        self.tuning_cfg["active_preset"] = preset_name
        for name, b in self.preset_buttons.items():
            if name == preset_name:
                b.add_css_class("nv-preset-btn-active")
            else:
                b.remove_css_class("nv-preset-btn-active")

        if preset_name == "Smooth Frametimes":
            self.sw_persistence.set_active(True)
            self.sw_kernel_pcie_pm.set_active(True)
            self.sw_kernel_rebar.set_active(True)
            self.sw_kernel_stream_memops.set_active(True)
            self.sw_kernel_vrr_memclk.set_active(True)
            self.sw_kernel_ntsync.set_active(True)

        self.scale_power.set_value(float(p.get("power_limit", self.last_snap.power_default_w)))
        self.scale_core_offset.set_value(float(p.get("core_offset", 0)))
        self.scale_mem_offset.set_value(float(p.get("mem_offset", 0)))
        self.scale_fan_speed.set_value(float(p.get("fan_speed", 50)))
        self.dd_fan_mode.set_selected(0 if p.get("fan_mode", "auto") == "auto" else 1)
        self._update_fan_mode_visibility()
        self._on_apply_tuning_clicked(None)

    def _on_fan_mode_changed(self, dd, _pspec):
        idx = dd.get_selected()
        self.tuning_cfg["custom_fan_curve_enabled"] = idx == 2
        self._last_curve_fan_speed = None
        self._update_fan_mode_visibility()
        self.nvml.save_tuning_config(self.tuning_cfg)

    def _on_fan_curve_updated(self, points):
        self.tuning_cfg["fan_curve_points"] = points
        self._last_curve_fan_speed = None
        self.nvml.save_tuning_config(self.tuning_cfg)

    def _save_current_tuning_state(
        self, pwr: float, core_off: int, mem_off: int, fan_mode: str, fan_spd: Optional[int]
    ):
        self.tuning_cfg["persistence"] = self.sw_persistence.get_active()
        self.tuning_cfg["pcie_pm"] = "on" if self.sw_kernel_pcie_pm.get_active() else "auto"
        self.tuning_cfg["kernel_rebar"] = self.sw_kernel_rebar.get_active()
        self.tuning_cfg["kernel_stream_memops"] = self.sw_kernel_stream_memops.get_active()
        self.tuning_cfg["kernel_vrr_memclk"] = self.sw_kernel_vrr_memclk.get_active()
        self.tuning_cfg["kernel_ntsync"] = self.sw_kernel_ntsync.get_active()
        self.tuning_cfg["kernel_framegen"] = self.sw_kernel_framegen.get_active()
        self.tuning_cfg["last_applied"] = {
            "power_limit": pwr,
            "core_offset": core_off,
            "mem_offset": mem_off,
            "fan_mode": fan_mode,
            "fan_speed": fan_spd if fan_spd is not None else int(round(self.scale_fan_speed.get_value())),
        }
        self.nvml.save_tuning_config(self.tuning_cfg)

    def _on_reset_tuning_clicked(self, _btn):
        self.scale_power.set_value(self.last_snap.power_default_w)
        self.scale_core_offset.set_value(0)
        self.scale_mem_offset.set_value(0)
        self.dd_fan_mode.set_selected(0)
        self._update_fan_mode_visibility()
        self._save_current_tuning_state(self.last_snap.power_default_w, 0, 0, "auto", 50)
        self._run_tuning_async(
            power_limit=self.last_snap.power_default_w,
            core_offset=0,
            mem_offset=0,
            fan_mode="auto",
            fan_speed=None,
            persistence="on" if self.sw_persistence.get_active() else "off",
            reset_locked_clocks=True,
            pcie_pm="on" if self.sw_kernel_pcie_pm.get_active() else "auto",
            kernel_rebar="on" if self.sw_kernel_rebar.get_active() else "off",
            kernel_stream_memops="on" if self.sw_kernel_stream_memops.get_active() else "off",
            kernel_vrr_memclk="on" if self.sw_kernel_vrr_memclk.get_active() else "off",
            kernel_ntsync="on" if self.sw_kernel_ntsync.get_active() else "off",
            kernel_framegen="on" if self.sw_kernel_framegen.get_active() else "off",
        )

    def _on_apply_tuning_clicked(self, _btn):
        pwr = self.scale_power.get_value()
        core_off = int(round(self.scale_core_offset.get_value()))
        mem_off = int(round(self.scale_mem_offset.get_value()))
        fan_idx = self.dd_fan_mode.get_selected()
        if fan_idx == 0:
            fan_mode = "auto"
            fan_spd = None
        elif fan_idx == 1:
            fan_mode = "manual"
            fan_spd = int(round(self.scale_fan_speed.get_value()))
        else:
            fan_mode = "manual"
            fan_spd = self.nvml.evaluate_fan_curve(
                self.tuning_cfg.get("fan_curve_points", []),
                self.last_snap.temp_c,
            )
            self._last_curve_fan_speed = fan_spd

        self._save_current_tuning_state(pwr, core_off, mem_off, fan_mode, fan_spd)
        is_smooth = self.tuning_cfg.get("active_preset") == "Smooth Frametimes"
        self._run_tuning_async(
            power_limit=pwr,
            core_offset=core_off,
            mem_offset=mem_off,
            fan_mode=fan_mode,
            fan_speed=fan_spd,
            persistence="on" if self.sw_persistence.get_active() else "off",
            reset_locked_clocks=False,
            pcie_pm="on" if self.sw_kernel_pcie_pm.get_active() else "auto",
            kernel_rebar="on" if self.sw_kernel_rebar.get_active() else "off",
            kernel_stream_memops="on" if self.sw_kernel_stream_memops.get_active() else "off",
            kernel_vrr_memclk="on" if self.sw_kernel_vrr_memclk.get_active() else "off",
            kernel_ntsync="on" if self.sw_kernel_ntsync.get_active() else "off",
            kernel_framegen="on" if self.sw_kernel_framegen.get_active() else "off",
            cpu_governor="performance" if is_smooth else None,
        )

    def _run_tuning_async(self, **kwargs):
        self.lbl_tuning_status.set_label("Applying hardware settings via PolicyKit (pkexec)...")

        def worker():
            ok, msg = self.nvml.apply_hardware_tuning(**kwargs)
            GLib.idle_add(self._on_tuning_done, ok, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_tuning_done(self, ok: bool, msg: str):
        prefix = "SUCCESS:" if ok else "ERROR:"
        self.lbl_tuning_status.set_label(f"{prefix} {msg}")
        return False

    # ------------------------------------------------------------------
    # PAGE 3: UNIFIED GRAPHICS, DLSS & GAME PROFILES
    # ------------------------------------------------------------------
    def _build_profiles_page(self) -> Gtk.Widget:
        self.profiles_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.profiles_paned.add_css_class("nv-paned")
        self.profiles_paned.set_position(235)
        self.profiles_paned.set_shrink_start_child(False)
        self.profiles_paned.set_shrink_end_child(False)
        self.profiles_paned.set_resize_start_child(False)
        self.profiles_paned.set_resize_end_child(True)
        self.profiles_paned.set_hexpand(True)
        self.profiles_paned.set_vexpand(True)

        # Left Pane: Game Library List
        left_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left_wrap.set_margin_top(16)
        left_wrap.set_margin_bottom(18)
        left_wrap.set_margin_start(18)
        left_wrap.set_margin_end(8)

        left_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        left_card.add_css_class("nv-card")
        left_card.set_size_request(175, -1)
        left_card.set_vexpand(True)

        lhdr = Gtk.Label(label="GLOBAL & DETECTED GAMES", xalign=0)
        lhdr.add_css_class("nv-card-title")
        lhdr.set_ellipsize(Pango.EllipsizeMode.END)
        left_card.append(lhdr)

        lscroll = Gtk.ScrolledWindow()
        lscroll.set_vexpand(True)
        lscroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.profile_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        lscroll.set_child(self.profile_list_box)
        left_card.append(lscroll)

        add_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.entry_new_game = Gtk.Entry()
        self.entry_new_game.set_placeholder_text("Add custom game...")
        self.entry_new_game.set_width_chars(10)
        self.entry_new_game.set_hexpand(True)
        self.entry_new_game.connect("activate", self._on_add_custom_game)
        btn_add_game = Gtk.Button(label="+ Add")
        btn_add_game.add_css_class("nv-secondary-btn")
        btn_add_game.connect("clicked", self._on_add_custom_game)
        add_box.append(self.entry_new_game)
        add_box.append(btn_add_game)
        left_card.append(add_box)

        left_wrap.append(left_card)
        self.profiles_paned.set_start_child(left_wrap)

        # Right Pane: Driver & DLSS Overrides for Selected Profile
        rscroll = Gtk.ScrolledWindow()
        rscroll.set_hexpand(True)
        rscroll.set_vexpand(True)
        rscroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        rbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        rbox.set_margin_top(16)
        rbox.set_margin_bottom(18)
        rbox.set_margin_start(10)
        rbox.set_margin_end(18)

        # Selected Game Header
        hdr_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        hdr_card.add_css_class("nv-banner")
        hdr_left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        hdr_left.set_hexpand(True)
        self.lbl_prof_title = Gtk.Label(label=self.selected_profile.name, xalign=0)
        self.lbl_prof_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.lbl_prof_title.add_css_class("nv-gpu-title")
        self.lbl_prof_path = Gtk.Label(label="", xalign=0)
        self.lbl_prof_path.set_ellipsize(Pango.EllipsizeMode.END)
        self.lbl_prof_path.add_css_class("nv-card-sub")
        hdr_left.append(self.lbl_prof_title)
        hdr_left.append(self.lbl_prof_path)
        hdr_card.append(hdr_left)

        self.badge_prof_mode = Gtk.Label(label="Global Profile")
        self.badge_prof_mode.add_css_class("nv-badge")
        self.badge_prof_mode.set_valign(Gtk.Align.CENTER)
        hdr_card.append(self.badge_prof_mode)
        rbox.append(hdr_card)

        # Ultra-Smooth Frametime Mode Card (All-In-One)
        self.smooth_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.smooth_card.add_css_class("nv-smooth-card")

        smooth_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        smooth_top.set_valign(Gtk.Align.CENTER)

        smooth_icon = Gtk.Image.new_from_icon_name("media-playlist-consecutive-symbolic")
        smooth_icon.set_pixel_size(20)
        smooth_icon.add_css_class("nv-status-ok")
        smooth_top.append(smooth_icon)

        smooth_title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        smooth_title_box.set_hexpand(True)
        lbl_sm_title = Gtk.Label(label="Ultra-Smooth Frametime Mode (All-in-One)", xalign=0)
        lbl_sm_title.add_css_class("nv-section-title")
        self.lbl_sm_desc = Gtk.Label(
            label="One-click optimization: locks display-cadence FPS, low latency queue, NTSYNC kernel sync, PCIe full power & zero split-lock latency.",
            xalign=0,
            wrap=True,
        )
        self.lbl_sm_desc.add_css_class("nv-card-sub")
        smooth_title_box.append(lbl_sm_title)
        smooth_title_box.append(self.lbl_sm_desc)
        smooth_top.append(smooth_title_box)

        self.badge_smooth_status = Gtk.Label(label="Disabled")
        self.badge_smooth_status.add_css_class("nv-badge-muted")
        self.badge_smooth_status.set_valign(Gtk.Align.CENTER)
        smooth_top.append(self.badge_smooth_status)

        self.sw_smooth_frametimes = Gtk.Switch()
        self.sw_smooth_frametimes.set_valign(Gtk.Align.CENTER)
        self.sw_smooth_frametimes.connect("notify::active", self._on_smooth_frametimes_toggled)
        smooth_top.append(self.sw_smooth_frametimes)

        self.smooth_card.append(smooth_top)

        self.lbl_smooth_detail = Gtk.Label(label="", xalign=0, wrap=True)
        self.lbl_smooth_detail.add_css_class("nv-status-ok")
        self.lbl_smooth_detail.set_visible(False)
        self.smooth_card.append(self.lbl_smooth_detail)

        tooltip_smooth = (
            "<b>Ultra-Smooth Frametime Mode (All-In-One)</b>\n"
            "Optimizes your entire graphics and Linux kernel pipeline for the absolute smoothest frame pacing:\n\n"
            "• <b>Display Refresh Sync</b>: Detects your monitor (100 Hz) and locks DXVK/VKD3D to exact 100 FPS.\n"
            "• <b>Low Latency Queue</b>: Limits render queue to 1 prerendered frame (__GL_MaxFramesAllowed=1).\n"
            "• <b>Kernel NTSYNC</b>: Fast in-kernel NT synchronization (/dev/ntsync) to eliminate wine lock contention.\n"
            "• <b>Zero Split-Lock Latency</b>: Disables kernel.split_lock_mitigate to stop bus freeze stutter.\n"
            "• <b>PCIe Full Power</b>: Locks PCIe bus out of low-power L0s/L1 states to eliminate bus latency spikes.\n"
            "• <b>Permanent Shader Cache</b>: Stores compiled shaders indefinitely to prevent compilation hitching.\n"
            "• <b>CPU Performance Governor</b>: Sets CPU scaling to full performance to prevent core clock drops."
        )
        self.smooth_card.set_tooltip_markup(tooltip_smooth)
        self.sw_smooth_frametimes.set_tooltip_markup(tooltip_smooth)
        rbox.append(self.smooth_card)

        # DLSS Super Resolution (Upscaling), Ray Reconstruction & Frame Gen
        dlss_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        dlss_card.add_css_class("nv-card")
        dlss_hdr = Gtk.Label(
            label="NVIDIA DLSS SUPER RESOLUTION, RAY RECONSTRUCTION & FRAME GENERATION",
            xalign=0,
        )
        dlss_hdr.add_css_class("nv-card-title")
        dlss_hdr.set_ellipsize(Pango.EllipsizeMode.END)
        dlss_card.append(dlss_hdr)

        self.sw_dlss_override = self._add_toggle_row(
            dlss_card,
            "DLSS Super Resolution",
            tooltip=(
                "<b>DLSS Super Resolution (AI Upscaling)</b>\n"
                "Renders the game at a lower internal resolution and uses NVIDIA AI Tensor Cores to upscale to native resolution, dramatically boosting framerates with high visual fidelity.\n\n"
                "<small>Internal: ngx_dlss_sr_override=on</small>"
            ),
            on_change=self._on_profile_widget_changed,
        )

        self.sw_dlss_upgrade = self._add_toggle_row(
            dlss_card,
            "Auto-Upgrade DLSS DLLs",
            tooltip=(
                "<b>Automatic DLSS DLL Upgrades</b>\n"
                "Automatically replaces outdated in-game nvngx_dlss.dll files with the newest optimized version, improving stability and reducing ghosting.\n\n"
                "<small>Internal: PROTON_DLSS_UPGRADE=1</small>"
            ),
            on_change=self._on_profile_widget_changed,
        )

        self.dd_dlss_sr_mode = self._add_dropdown_row(
            dlss_card,
            "DLSS Quality Preset",
            [v[0] for v in DLSS_SR_MODE_MAP.values()],
            tooltip=(
                "<b>DLSS Upscaling Quality Mode</b>\n"
                "Selects your target balance between image sharpness and framerate:\n"
                "• <b>DLAA (100%)</b>: Native AI Anti-Aliasing (Ultra Quality)\n"
                "• <b>Quality (67%)</b>: Balanced sharpness and performance (1.5x)\n"
                "• <b>Balanced (58%)</b>: Ideal for fast action (1.7x)\n"
                "• <b>Performance (50%)</b>: 2.0x performance scaling\n"
                "• <b>Ultra Performance (33%)</b>: 3.0x maximum performance scaling"
            ),
            on_change=self._on_profile_widget_changed,
        )

        self.scale_dlss_ratio, self.row_dlss_ratio = self._create_slider_row(
            "Custom Render Scale",
            33,
            100,
            1,
            67,
            "%",
            tooltip=(
                "<b>Internal Render Scale Ratio</b>\n"
                "Directly customize internal rendering resolution percentage from 33% (maximum performance) to 100% (native DLAA)."
            ),
        )
        self.scale_dlss_ratio.connect("value-changed", self._on_profile_scale_slider_changed)
        dlss_card.append(self.row_dlss_ratio)

        self.lbl_prof_upscale_preview = Gtk.Label(label="", xalign=0, wrap=True)
        self.lbl_prof_upscale_preview.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.lbl_prof_upscale_preview.set_hexpand(True)
        self.lbl_prof_upscale_preview.add_css_class("nv-status-ok")
        dlss_card.append(self.lbl_prof_upscale_preview)

        self.dd_dlss_preset = self._add_dropdown_row(
            dlss_card,
            "DLSS AI Model Preset",
            [v[0] for v in DLSS_PRESET_MAP.values()],
            tooltip=(
                "<b>DLSS Neural Network Model Architecture</b>\n"
                "Selects which trained AI model executes on Tensor Cores.\n"
                "• <b>Preset K / Latest</b>: Newest Transformer architecture with lowest ghosting.\n"
                "• <b>Preset F / E</b>: High-performance CNN models for fast motion."
            ),
            on_change=self._on_profile_widget_changed,
        )

        self.sw_dlss_rr = self._add_toggle_row(
            dlss_card,
            "DLSS Ray Reconstruction",
            tooltip=(
                "<b>AI Ray Reconstruction (DLSS 3.5)</b>\n"
                "Replaces traditional hand-tuned denoisers with an AI model trained to generate higher fidelity reflections, lighting, and global illumination.\n\n"
                "<small>Internal: ngx_dlss_rr_override=on</small>"
            ),
            on_change=self._on_profile_widget_changed,
        )

        self.sw_optiscaler_fg = self._add_toggle_row(
            dlss_card,
            "OptiScaler Frame Generation",
            tooltip=(
                "<b>OptiScaler Universal Frame Generation (FSR 3.1 & XeFG Bridge)</b>\n"
                "Generates interpolated AI frames for RTX 3050 and non-Ada GPUs using universal compute shaders.\n\n"
                "⚡ <b>Kernel-Level GPU Synchronization</b>:\n"
                "• Linux Kernel NTSYNC (/dev/ntsync) low-latency pacing\n"
                "• Zero split-lock latency (kernel.split_lock_mitigate=0)\n"
                "• Kernel PCIe Max Perf & NVreg_EnableStreamMemOPs\n"
                "• Automatic RTX 4090 Streamline spoofing & DXGI interception\n\n"
                "<small>Internal: PROTON_USE_OPTISCALER=1 / OptiScaler [FrameGen] / fakenvapi</small>"
            ),
            on_change=self._on_optiscaler_fg_toggle_changed,
        )
        self.sw_dlss_fg = self.sw_optiscaler_fg  # Compatibility alias

        self.dd_optiscaler_fg = self._add_dropdown_row(
            dlss_card,
            "OptiScaler Frame Gen Multiplier",
            [v[0] for v in OPTISCALER_FG_MODE_MAP.values()],
            tooltip=(
                "<b>OptiScaler Frame Generation Multiplier</b>\n"
                "• <b>Standard 2x</b>: Inserts 1 interpolated frame per rendered frame.\n"
                "• <b>Multi-Frame 3x / 4x</b>: Multiplies frames (2 or 3 interpolated frames) for ultra-high refresh rate displays."
            ),
            on_change=self._on_profile_widget_changed,
        )
        self.dd_dlss_fg = self.dd_optiscaler_fg  # Compatibility alias

        self.sw_optiscaler = self._add_toggle_row(
            dlss_card,
            "OptiScaler Universal Upscaler & FG",
            tooltip=(
                "<b>OptiScaler Proton Bridge & Frame Gen</b>\n"
                "Deploys directly underneath the app to power Frame Gen (FSR 3.1 FG translation for RTX 20/30 cards) and translate FSR2/FSR3/XeSS calls to NVIDIA DLSS.\n\n"
                "<small>Internal: PROTON_USE_OPTISCALER=1 / WINEDLLOVERRIDES=dxgi=n,b</small>"
            ),
            on_change=self._on_profile_widget_changed,
        )

        self.scale_nis_sharp, row_nis_sharp = self._create_slider_row(
            "CAS Image Sharpening",
            0,
            100,
            5,
            0,
            "%",
            tooltip=(
                "<b>Contrast Adaptive Sharpening (Vulkan CAS)</b>\n"
                "Adds crisp edge clarity without halo artifacts. 15%–25% is recommended."
            ),
        )
        self.scale_nis_sharp.connect("value-changed", self._on_profile_widget_changed)
        dlss_card.append(row_nis_sharp)

        self.sw_dlss_indicator = self._add_toggle_row(
            dlss_card,
            "DLSS On-Screen HUD",
            tooltip=(
                "<b>DLSS Indicator Watermark</b>\n"
                "Displays a small watermark in the bottom corner showing live DLSS resolution, upscale factor, and active preset."
            ),
            on_change=self._on_profile_widget_changed,
        )
        rbox.append(dlss_card)

        # Frame Rate, VSync, G-SYNC & Driver Optimizations
        drv_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        drv_card.add_css_class("nv-card")
        drv_hdr = Gtk.Label(label="DRIVER GRAPHICS, SYNC & LATENCY SETTINGS", xalign=0)
        drv_hdr.add_css_class("nv-card-title")
        drv_hdr.set_ellipsize(Pango.EllipsizeMode.END)
        drv_card.append(drv_hdr)

        self.dd_vsync = self._add_dropdown_row(
            drv_card,
            "Vertical Sync (VSync)",
            [
                "Use 3D Application Setting",
                "Force On (__GL_SYNC_TO_VBLANK=1)",
                "Force Off (__GL_SYNC_TO_VBLANK=0)",
            ],
            tooltip=(
                "<b>Display Synchronization</b>\n"
                "Synchronizes game frame presentation with your monitor's refresh cycles to eliminate screen tearing."
            ),
            on_change=self._on_profile_widget_changed,
        )
        self.sw_vrr = self._add_toggle_row(
            drv_card,
            "G-SYNC & VRR Allowed",
            tooltip=(
                "<b>Variable Refresh Rate (VRR)</b>\n"
                "Allows variable refresh rate dynamically on supported VRR/G-SYNC displays.\n\n"
                "<small>Internal: __GL_VRR_ALLOWED=1</small>"
            ),
            on_change=self._on_profile_widget_changed,
        )
        self.sw_low_latency = self._add_toggle_row(
            drv_card,
            "Ultra Low Latency Mode",
            tooltip=(
                "<b>Low Latency Render Queue</b>\n"
                "Restricts prerendered frames queue to 1 (__GL_MaxFramesAllowed=1). Significantly reduces mouse input lag and eliminates frame timing queue jitter.\n\n"
                "<small>Internal: __GL_MaxFramesAllowed=1</small>"
            ),
            on_change=self._on_profile_widget_changed,
        )
        self.dd_img_qual = self._add_dropdown_row(
            drv_card,
            "Texture Filtering Quality",
            [v[0] for v in IMAGE_QUALITY_MAP.values()],
            tooltip=(
                "<b>Driver Texture Filtering Quality</b>\n"
                "Controls driver anisotropic filtering and texture mipmap precision. 'Quality' or 'High Quality' gives crisp textures with minimal performance impact."
            ),
            on_change=self._on_profile_widget_changed,
        )
        self.sw_threaded = self._add_toggle_row(
            drv_card,
            "Multi-Threaded Optimization",
            tooltip=(
                "<b>Threaded Driver Optimization</b>\n"
                "Enables multi-threaded driver command submission to prevent single CPU core bottlenecks.\n\n"
                "<small>Internal: __GL_THREADED_OPTIMIZATIONS=1</small>"
            ),
            on_change=self._on_profile_widget_changed,
        )
        self.sw_shader_cache = self._add_toggle_row(
            drv_card,
            "Unlimited Shader Cache",
            tooltip=(
                "<b>Permanent Shader Disk Cache</b>\n"
                "Stores compiled shaders permanently on disk without automatic cache cleanup (__GL_SHADER_DISK_CACHE_SKIP_CLEANUP=1). Completely stops shader compilation hitching and micro-stutter when loading new areas in games."
            ),
            on_change=self._on_profile_widget_changed,
        )
        self.sw_prime = self._add_toggle_row(
            drv_card,
            "Force Dedicated NVIDIA GPU",
            tooltip=(
                "<b>PRIME GPU Render Offload</b>\n"
                "Forces the game to run exclusively on the high-performance NVIDIA GeForce GPU instead of integrated graphics.\n\n"
                "<small>Internal: __NV_PRIME_RENDER_OFFLOAD=1</small>"
            ),
            on_change=self._on_profile_widget_changed,
        )
        self.sw_wayland = self._add_toggle_row(
            drv_card,
            "Proton Wayland Driver",
            tooltip=(
                "<b>Direct Wayland Driver</b>\n"
                "Bypasses Xwayland translation to run directly on native KDE Wayland for lower latency in supported Proton builds.\n\n"
                "<small>Internal: PROTON_ENABLE_WAYLAND=1</small>"
            ),
            on_change=self._on_profile_widget_changed,
        )
        self.sw_hdr = self._add_toggle_row(
            drv_card,
            "Proton HDR Passthrough",
            tooltip=(
                "<b>High Dynamic Range (HDR)</b>\n"
                "Enables 10-bit HDR output for supported games when an HDR display is connected.\n\n"
                "<small>Internal: PROTON_ENABLE_HDR=1</small>"
            ),
            on_change=self._on_profile_widget_changed,
        )
        self.sw_mangohud = self._add_toggle_row(
            drv_card,
            "MangoHud Overlay",
            tooltip=(
                "<b>In-Game Performance HUD</b>\n"
                "Shows live FPS, frametime graph, and GPU telemetry on-screen while gaming."
            ),
            on_change=self._on_profile_widget_changed,
        )

        self.scale_fps_limit, row_fps = self._create_slider_row(
            "Frame Rate Limit (FPS)",
            0,
            360,
            5,
            0,
            "FPS",
            tooltip=(
                "<b>Max Frame Rate Cap</b>\n"
                "Limits max framerate to reduce GPU heat or match monitor refresh rate (e.g. 100 FPS) for perfect frame pacing consistency. Set to 0 for unlimited."
            ),
        )
        self.scale_fps_limit.connect("value-changed", self._on_profile_widget_changed)
        drv_card.append(row_fps)

        rbox.append(drv_card)

        # Auto-Sync Status & Profile Reset Bar
        act_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        act_card.add_css_class("nv-card")

        self.lbl_copy_status = Gtk.Label(
            label="Settings sync automatically to Steam Proton & system environment.",
            xalign=0,
            wrap=True,
        )
        self.lbl_copy_status.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.lbl_copy_status.set_hexpand(True)
        self.lbl_copy_status.add_css_class("nv-status-ok")
        act_card.append(self.lbl_copy_status)

        self.btn_reset_prof = Gtk.Button(label="Reset to Defaults")
        self.btn_reset_prof.set_valign(Gtk.Align.CENTER)
        self.btn_reset_prof.add_css_class("nv-secondary-btn")
        self.btn_reset_prof.connect("clicked", self._on_reset_profile_clicked)
        act_card.append(self.btn_reset_prof)

        rbox.append(act_card)

        rscroll.set_child(rbox)
        self.profiles_paned.set_end_child(rscroll)

        self._rebuild_profile_list()
        self._load_profile_into_ui(self.selected_profile)
        return self.profiles_paned

    def _format_upscale_preview(self, sr_mode: str, ratio: int) -> str:
        eff_ratio = DLSS_SR_MODE_MAP.get(sr_mode, ("", "", ratio))[2] if sr_mode != "custom" else ratio
        r = eff_ratio / 100.0
        w1080, h1080 = int(round(1920 * r)), int(round(1080 * r))
        w1440, h1440 = int(round(2560 * r)), int(round(1440 * r))
        w4k, h4k = int(round(3840 * r)), int(round(2160 * r))
        factor = 100.0 / max(1, eff_ratio)
        return (
            f"Active Upscale: {factor:.2f}x ({eff_ratio}% Scale)   •   "
            f"1080p: {w1080}×{h1080}   •   "
            f"1440p: {w1440}×{h1440}   •   "
            f"4K: {w4k}×{h4k}"
        )

    def _update_dlss_sensitivity(self, prof: GameProfile):
        active = bool(prof.dlss_override)
        self.sw_dlss_upgrade.set_sensitive(active)
        self.dd_dlss_sr_mode.set_sensitive(active)
        self.row_dlss_ratio.set_sensitive(active)
        self.lbl_prof_upscale_preview.set_sensitive(active)

    def _add_toggle_row(
        self,
        parent: Gtk.Box,
        title: str,
        subtitle: Optional[str] = None,
        on_change: Optional[Callable] = None,
        tooltip: Optional[str] = None,
    ) -> Gtk.Switch:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("nv-setting-row")

        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title_box.set_hexpand(True)
        title_box.set_valign(Gtk.Align.CENTER)

        lbl_t = Gtk.Label(label=title, xalign=0)
        lbl_t.set_hexpand(True)
        lbl_t.add_css_class("nv-setting-title")
        lbl_t.set_ellipsize(Pango.EllipsizeMode.END)
        title_box.append(lbl_t)

        info_icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
        info_icon.set_pixel_size(14)
        info_icon.add_css_class("nv-info-icon")
        info_icon.set_valign(Gtk.Align.CENTER)
        title_box.append(info_icon)

        row.append(title_box)

        sw = Gtk.Switch()
        sw.set_valign(Gtk.Align.CENTER)
        if on_change is not None:
            sw.connect("notify::active", on_change)
        row.append(sw)

        eff_tooltip = tooltip or subtitle
        if eff_tooltip:
            if not eff_tooltip.startswith("<"):
                markup = f"<b>{GLib.markup_escape_text(title)}</b>\n{GLib.markup_escape_text(eff_tooltip)}"
            else:
                markup = eff_tooltip
            row.set_tooltip_markup(markup)
            sw.set_tooltip_markup(markup)
            info_icon.set_tooltip_markup(markup)

        parent.append(row)
        return sw

    def _add_dropdown_row(
        self,
        parent: Gtk.Box,
        title: str,
        items: list,
        on_change: Optional[Callable] = None,
        tooltip: Optional[str] = None,
    ) -> Gtk.DropDown:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("nv-setting-row")

        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title_box.set_hexpand(True)
        title_box.set_valign(Gtk.Align.CENTER)

        lbl = Gtk.Label(label=title, xalign=0)
        lbl.set_hexpand(True)
        lbl.add_css_class("nv-setting-title")
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        title_box.append(lbl)

        info_icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
        info_icon.set_pixel_size(14)
        info_icon.add_css_class("nv-info-icon")
        info_icon.set_valign(Gtk.Align.CENTER)
        title_box.append(info_icon)

        row.append(title_box)

        dd = _make_ellipsizing_dropdown(items, max_chars=28)
        dd.set_valign(Gtk.Align.CENTER)
        if on_change is not None:
            dd.connect("notify::selected", on_change)
        row.append(dd)

        if tooltip:
            if not tooltip.startswith("<"):
                markup = f"<b>{GLib.markup_escape_text(title)}</b>\n{GLib.markup_escape_text(tooltip)}"
            else:
                markup = tooltip
            row.set_tooltip_markup(markup)
            dd.set_tooltip_markup(markup)
            info_icon.set_tooltip_markup(markup)

        parent.append(row)
        return dd

    def _rebuild_profile_list(self):
        child = self.profile_list_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.profile_list_box.remove(child)
            child = nxt

        for prof in self.profiles_mgr.list_profiles():
            btn = Gtk.Button()
            lbl = Gtk.Label(label=prof.name, xalign=0.0)
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            lbl.set_hexpand(True)
            btn.set_child(lbl)
            btn.add_css_class("nv-nav-btn")
            if prof.app_id == self.selected_profile.app_id:
                btn.add_css_class("nv-nav-btn-active")
            btn.connect("clicked", self._on_select_profile, prof)
            self.profile_list_box.append(btn)

    def _on_select_profile(self, _btn, prof: GameProfile):
        self.selected_profile = self.profiles_mgr.profiles.get(prof.app_id, prof)
        self._rebuild_profile_list()
        self._load_profile_into_ui(self.selected_profile)

    def _on_add_custom_game(self, _widget):
        name = self.entry_new_game.get_text().strip()
        if not name:
            return
        prof = self.profiles_mgr.add_custom_profile(name)
        self.entry_new_game.set_text("")
        self.selected_profile = prof
        self._rebuild_profile_list()
        self._load_profile_into_ui(prof)

    def _update_profile_header_badges(self, prof: GameProfile):
        if prof.app_id == "__global__":
            self.badge_prof_mode.set_label("Global Default (All Games)")
            self.btn_reset_prof.set_label("Reset Global Defaults")
        elif prof.custom_override:
            self.badge_prof_mode.set_label("Custom Per-Game Profile")
            self.btn_reset_prof.set_label("Use Global Settings")
        else:
            self.badge_prof_mode.set_label("Using Global Settings")
            self.btn_reset_prof.set_label("Use Global Settings")

    def _load_profile_into_ui(self, prof: GameProfile):
        self._updating_profile_ui = True
        self.lbl_prof_title.set_label(prof.name)
        self.lbl_prof_path.set_label(
            f"App ID: {prof.app_id}" + (f"  •  {prof.install_dir}" if prof.install_dir else "")
        )
        self._update_profile_header_badges(prof)

        # Smooth Frametimes Mode
        is_smooth = getattr(prof, "smooth_frametimes", False)
        self.sw_smooth_frametimes.set_active(is_smooth)
        if is_smooth:
            self.badge_smooth_status.set_label("ACTIVE")
            self.badge_smooth_status.remove_css_class("nv-badge-muted")
            self.badge_smooth_status.add_css_class("nv-badge")
            self.lbl_smooth_detail.set_label(
                f"⚡ Optimal frame pacing active: locked to {prof.fps_limit or 100} FPS display cadence • Low Latency • NTSYNC • PCIe Max Perf • CPU Performance"
            )
            self.lbl_smooth_detail.set_visible(True)
        else:
            self.badge_smooth_status.set_label("Disabled")
            self.badge_smooth_status.remove_css_class("nv-badge")
            self.badge_smooth_status.add_css_class("nv-badge-muted")
            self.lbl_smooth_detail.set_visible(False)

        self.sw_dlss_override.set_active(prof.dlss_override)
        self.sw_dlss_upgrade.set_active(prof.dlss_upgrade)

        sr_keys = list(DLSS_SR_MODE_MAP.keys())
        self.dd_dlss_sr_mode.set_selected(
            sr_keys.index(prof.dlss_sr_mode) if prof.dlss_sr_mode in sr_keys else 0
        )
        self.scale_dlss_ratio.set_value(float(prof.dlss_scale_ratio))
        self.lbl_prof_upscale_preview.set_label(
            self._format_upscale_preview(prof.dlss_sr_mode, prof.dlss_scale_ratio)
        )
        self._update_dlss_sensitivity(prof)

        preset_keys = list(DLSS_PRESET_MAP.keys())
        self.dd_dlss_preset.set_selected(
            preset_keys.index(prof.dlss_preset) if prof.dlss_preset in preset_keys else 0
        )
        self.sw_dlss_rr.set_active(prof.dlss_rr_override)

        # OptiScaler Frame Generation
        is_fg_active = bool(getattr(prof, "optiscaler_fg_enabled", False) and prof.optiscaler_fg_mode != "off")
        self.sw_optiscaler_fg.set_active(is_fg_active)
        self.dd_optiscaler_fg.set_sensitive(is_fg_active)
        fg_keys = list(OPTISCALER_FG_MODE_MAP.keys())
        cur_fg_mode = prof.optiscaler_fg_mode if prof.optiscaler_fg_mode in fg_keys else ("on" if is_fg_active else "off")
        self.dd_optiscaler_fg.set_selected(fg_keys.index(cur_fg_mode))

        self.sw_optiscaler.set_active(prof.optiscaler_enable)
        self.scale_nis_sharp.set_value(float(prof.nis_sharpening))
        self.sw_dlss_indicator.set_active(prof.dlss_indicator)

        vsync_keys = ["app", "on", "off"]
        self.dd_vsync.set_selected(vsync_keys.index(prof.vsync_mode) if prof.vsync_mode in vsync_keys else 0)
        self.sw_vrr.set_active(prof.vrr_gsync)
        self.sw_low_latency.set_active(prof.low_latency_mode)

        iq_keys = list(IMAGE_QUALITY_MAP.keys())
        self.dd_img_qual.set_selected(
            iq_keys.index(prof.image_quality) if prof.image_quality in iq_keys else 1
        )
        self.sw_threaded.set_active(prof.threaded_optimization)
        self.sw_shader_cache.set_active(prof.unlimited_shader_cache)
        self.sw_prime.set_active(prof.prime_offload)
        self.sw_wayland.set_active(prof.proton_wayland)
        self.sw_hdr.set_active(prof.proton_hdr)
        self.sw_mangohud.set_active(prof.mangohud)
        self.scale_fps_limit.set_value(float(prof.fps_limit))

        self.lbl_copy_status.set_label(
            "Settings sync automatically to Steam Proton & system environment."
        )
        self._updating_profile_ui = False

    def _on_optiscaler_fg_toggle_changed(self, sw, _pspec):
        if self._updating_profile_ui:
            return
        active = sw.get_active()
        prof = self.selected_profile
        prof.optiscaler_fg_enabled = active
        fg_keys = list(OPTISCALER_FG_MODE_MAP.keys())
        if not active:
            prof.optiscaler_fg_mode = "off"
            self._updating_profile_ui = True
            if "off" in fg_keys:
                self.dd_optiscaler_fg.set_selected(fg_keys.index("off"))
            self.dd_optiscaler_fg.set_sensitive(False)
            self._updating_profile_ui = False
        else:
            if prof.optiscaler_fg_mode == "off":
                prof.optiscaler_fg_mode = "on"
            # Automatically enable OptiScaler directly underneath to make Frame Gen work
            prof.optiscaler_enable = True
            self._updating_profile_ui = True
            self.sw_optiscaler.set_active(True)
            if prof.optiscaler_fg_mode in fg_keys:
                self.dd_optiscaler_fg.set_selected(fg_keys.index(prof.optiscaler_fg_mode))
            self.dd_optiscaler_fg.set_sensitive(True)
            self._updating_profile_ui = False
        self._on_profile_widget_changed()

    _on_dlss_fg_toggle_changed = _on_optiscaler_fg_toggle_changed

    def _on_smooth_frametimes_toggled(self, sw, _pspec):
        if self._updating_profile_ui:
            return
        active = sw.get_active()
        prof = self.selected_profile
        if prof.app_id != "__global__":
            prof.custom_override = True
        prof.smooth_frametimes = active

        if active:
            # 1. Determine target display refresh rate
            target_hz = 100
            displays = self.display_mgr.get_displays()
            if displays:
                m = re.search(r"@(\d+)", displays[0].current_mode)
                if m:
                    target_hz = int(m.group(1))

            # 2. Configure graphics profile
            prof.fps_limit = target_hz
            prof.low_latency_mode = True
            prof.threaded_optimization = True
            prof.unlimited_shader_cache = True
            prof.vsync_mode = "app"

            # 3. Synchronize hardware and kernel tuning
            self.sw_persistence.set_active(True)
            self.sw_kernel_pcie_pm.set_active(True)
            self.sw_kernel_rebar.set_active(True)
            self.sw_kernel_stream_memops.set_active(True)
            self.sw_kernel_vrr_memclk.set_active(True)
            self.sw_kernel_ntsync.set_active(True)

            self._save_current_tuning_state(
                self.scale_power.get_value(),
                int(round(self.scale_core_offset.get_value())),
                int(round(self.scale_mem_offset.get_value())),
                "auto",
                None,
            )
            self._run_tuning_async(
                power_limit=self.scale_power.get_value(),
                core_offset=int(round(self.scale_core_offset.get_value())),
                mem_offset=int(round(self.scale_mem_offset.get_value())),
                fan_mode="auto",
                fan_speed=None,
                persistence="on",
                pcie_pm="on",
                kernel_rebar="on",
                kernel_stream_memops="on",
                kernel_vrr_memclk="on",
                kernel_ntsync="on",
                cpu_governor="performance",
            )

            self.badge_smooth_status.set_label("ACTIVE")
            self.badge_smooth_status.remove_css_class("nv-badge-muted")
            self.badge_smooth_status.add_css_class("nv-badge")
            self.lbl_smooth_detail.set_label(
                f"⚡ Optimal frame pacing active: locked to {target_hz} FPS display cadence • Low Latency • NTSYNC • PCIe Max Perf • CPU Performance"
            )
            self.lbl_smooth_detail.set_visible(True)
        else:
            self.badge_smooth_status.set_label("Disabled")
            self.badge_smooth_status.remove_css_class("nv-badge")
            self.badge_smooth_status.add_css_class("nv-badge-muted")
            self.lbl_smooth_detail.set_visible(False)

        self._load_profile_into_ui(prof)
        self._schedule_profile_sync(prof)

    def _on_profile_scale_slider_changed(self, scale):
        if self._updating_profile_ui:
            return
        prof = self.selected_profile
        val = int(round(scale.get_value()))
        prof.dlss_scale_ratio = val
        sr_keys = list(DLSS_SR_MODE_MAP.keys())
        if prof.dlss_sr_mode != "custom" and val != DLSS_SR_MODE_MAP.get(prof.dlss_sr_mode, ("", "", 67))[2]:
            prof.dlss_sr_mode = "custom"
            self._updating_profile_ui = True
            self.dd_dlss_sr_mode.set_selected(sr_keys.index("custom"))
            self._updating_profile_ui = False
        self._on_profile_widget_changed()

    def _on_profile_widget_changed(self, *_args):
        if self._updating_profile_ui:
            return
        prof = self.selected_profile
        if prof.app_id != "__global__":
            prof.custom_override = True

        prof.dlss_override = self.sw_dlss_override.get_active()
        prof.dlss_upgrade = self.sw_dlss_upgrade.get_active()

        sr_keys = list(DLSS_SR_MODE_MAP.keys())
        new_sr_mode = sr_keys[self.dd_dlss_sr_mode.get_selected()]
        if new_sr_mode != prof.dlss_sr_mode:
            prof.dlss_sr_mode = new_sr_mode
            if new_sr_mode != "custom" and new_sr_mode != "default":
                prof.dlss_scale_ratio = DLSS_SR_MODE_MAP[new_sr_mode][2]
                self._updating_profile_ui = True
                self.scale_dlss_ratio.set_value(float(prof.dlss_scale_ratio))
                self._updating_profile_ui = False

        prof.dlss_scale_ratio = int(round(self.scale_dlss_ratio.get_value()))
        self.lbl_prof_upscale_preview.set_label(
            self._format_upscale_preview(prof.dlss_sr_mode, prof.dlss_scale_ratio)
        )
        self._update_dlss_sensitivity(prof)

        preset_keys = list(DLSS_PRESET_MAP.keys())
        prof.dlss_preset = preset_keys[self.dd_dlss_preset.get_selected()]
        prof.dlss_rr_override = self.sw_dlss_rr.get_active()

        prof.optiscaler_fg_enabled = self.sw_optiscaler_fg.get_active()
        fg_keys = list(OPTISCALER_FG_MODE_MAP.keys())
        sel_idx = self.dd_optiscaler_fg.get_selected()
        if prof.optiscaler_fg_enabled:
            prof.optiscaler_fg_mode = fg_keys[sel_idx] if (sel_idx < len(fg_keys) and fg_keys[sel_idx] != "off") else "on"
            # Keep OptiScaler enabled directly underneath Frame Gen
            prof.optiscaler_enable = True
            if not self.sw_optiscaler.get_active():
                self._updating_profile_ui = True
                self.sw_optiscaler.set_active(True)
                self._updating_profile_ui = False
        else:
            prof.optiscaler_fg_mode = "off"
            prof.optiscaler_enable = self.sw_optiscaler.get_active()
        self.dd_optiscaler_fg.set_sensitive(prof.optiscaler_fg_enabled)
        prof.nis_sharpening = int(round(self.scale_nis_sharp.get_value()))
        prof.dlss_indicator = self.sw_dlss_indicator.get_active()

        vsync_keys = ["app", "on", "off"]
        prof.vsync_mode = vsync_keys[self.dd_vsync.get_selected()]
        prof.vrr_gsync = self.sw_vrr.get_active()
        prof.low_latency_mode = self.sw_low_latency.get_active()

        iq_keys = list(IMAGE_QUALITY_MAP.keys())
        prof.image_quality = iq_keys[self.dd_img_qual.get_selected()]
        prof.threaded_optimization = self.sw_threaded.get_active()
        prof.unlimited_shader_cache = self.sw_shader_cache.get_active()
        prof.prime_offload = self.sw_prime.get_active()
        prof.proton_wayland = self.sw_wayland.get_active()
        prof.proton_hdr = self.sw_hdr.get_active()
        prof.mangohud = self.sw_mangohud.get_active()
        prof.fps_limit = int(round(self.scale_fps_limit.get_value()))

        self._update_profile_header_badges(prof)
        self._schedule_profile_sync(prof)

    def _schedule_profile_sync(self, prof: GameProfile):
        """Debounces profile sync by 280ms and runs disk/prefix sync asynchronously off the UI thread."""
        if self._profile_sync_timer_id is not None:
            GLib.source_remove(self._profile_sync_timer_id)

        def _fire():
            self._profile_sync_timer_id = None
            target = prof

            def _worker():
                _ok, msg = self.profiles_mgr.apply_profile_to_proton(target)
                GLib.idle_add(self.lbl_copy_status.set_label, msg)

            threading.Thread(target=_worker, daemon=True).start()
            return False

        self._profile_sync_timer_id = GLib.timeout_add(280, _fire)

    def _on_reset_profile_clicked(self, _btn):
        fresh = self.profiles_mgr.reset_profile_to_defaults(self.selected_profile)
        self.selected_profile = fresh
        self._load_profile_into_ui(fresh)
        self._schedule_profile_sync(fresh)

    # ------------------------------------------------------------------
    # PAGE 4: DISPLAY & COLOR (WAYLAND KSCREEN + VIBRANCE)
    # ------------------------------------------------------------------
    def _build_display_page(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_top(16)
        box.set_margin_bottom(18)
        box.set_margin_start(18)
        box.set_margin_end(18)

        self.displays: list[DisplayOutput] = self.display_mgr.get_displays()
        self.cur_display: DisplayOutput = self.displays[0]

        banner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        banner.add_css_class("nv-banner")
        b_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        b_col.set_hexpand(True)
        self.lbl_disp_title = Gtk.Label(
            label=f"Display Output: {self.cur_display.connector} — {self.cur_display.monitor_name}",
            xalign=0,
        )
        self.lbl_disp_title.add_css_class("nv-gpu-title")
        self.lbl_disp_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.lbl_disp_sub = Gtk.Label(
            label=f"DRM Connector: {self.cur_display.drm_card}-{self.cur_display.connector}  •  KDE KWin Wayland + NVIDIA DRM Modeset",
            xalign=0,
        )
        self.lbl_disp_sub.add_css_class("nv-card-sub")
        self.lbl_disp_sub.set_ellipsize(Pango.EllipsizeMode.END)
        b_col.append(self.lbl_disp_title)
        b_col.append(self.lbl_disp_sub)
        banner.append(b_col)

        disp_names = [f"{d.connector} ({d.monitor_name})" for d in self.displays]
        self.dd_display_sel = _make_ellipsizing_dropdown(disp_names, max_chars=24)
        self.dd_display_sel.set_valign(Gtk.Align.CENTER)
        self.dd_display_sel.connect("notify::selected", self._on_display_selected)
        banner.append(self.dd_display_sel)
        box.append(banner)

        # Mode, VRR, HDR, RGB Range Card
        dcard = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        dcard.add_css_class("nv-card")
        dhdr = Gtk.Label(label="RESOLUTION, REFRESH RATE & G-SYNC / VRR (KDE WAYLAND)", xalign=0)
        dhdr.add_css_class("nv-card-title")
        dhdr.set_ellipsize(Pango.EllipsizeMode.END)
        dcard.append(dhdr)

        self.dd_disp_mode = self._add_dropdown_row(
            dcard,
            "Resolution & Refresh Rate",
            self.cur_display.available_modes,
            tooltip=(
                "<b>Display Mode (Resolution & Refresh Rate)</b>\n"
                "Configures output resolution and refresh rate through KDE KWin Wayland."
            ),
        )
        if self.cur_display.current_mode in self.cur_display.available_modes:
            self.dd_disp_mode.set_selected(
                self.cur_display.available_modes.index(self.cur_display.current_mode)
            )

        vrr_opts = ["automatic", "always", "never"]
        self.dd_disp_vrr = self._add_dropdown_row(
            dcard,
            "G-SYNC / VRR Adaptive Sync",
            vrr_opts,
            tooltip=(
                "<b>KDE Adaptive Sync Policy</b>\n"
                "• <b>automatic</b>: Engages VRR automatically for full-screen games.\n"
                "• <b>always</b>: Forces VRR active at all times.\n"
                "• <b>never</b>: Disables VRR (uses fixed refresh rate)."
            ),
        )
        if self.cur_display.vrr_policy in vrr_opts:
            self.dd_disp_vrr.set_selected(vrr_opts.index(self.cur_display.vrr_policy))

        rgb_opts = ["automatic", "full", "limited"]
        self.dd_disp_rgb = self._add_dropdown_row(
            dcard,
            "Output Dynamic Range",
            rgb_opts,
            tooltip=(
                "<b>Output Dynamic Range (Color Levels)</b>\n"
                "• <b>full</b>: Full 0–255 black-to-white levels for PC monitors.\n"
                "• <b>limited</b>: 16–235 levels for older TVs and AV receivers."
            ),
        )
        if self.cur_display.rgb_range in rgb_opts:
            self.dd_disp_rgb.set_selected(rgb_opts.index(self.cur_display.rgb_range))

        self.sw_disp_hdr = self._add_toggle_row(
            dcard,
            "High Dynamic Range (HDR10)",
            tooltip=(
                "<b>KDE Wayland HDR10 Output</b>\n"
                "Enables 10-bit High Dynamic Range (HDR10) and Wide Color Gamut (BT.2020) for HDR-certified monitors."
            ),
        )
        self.sw_disp_hdr.set_active(self.cur_display.hdr_enabled)

        self.scale_disp_scale, row_scale = self._create_slider_row(
            "Display Fractional Scale",
            100,
            200,
            25,
            int(round(self.cur_display.scale * 100)),
            "%",
            tooltip=(
                "<b>KDE Plasma Wayland Fractional Scaling</b>\n"
                "Scales desktop text and applications cleanly without pixelation on high-DPI displays."
            ),
        )
        dcard.append(row_scale)
        box.append(dcard)

        # Color & Digital Vibrance Card
        ccard = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        ccard.add_css_class("nv-card")
        chdr = Gtk.Label(
            label="COLOR ENHANCEMENT, BRIGHTNESS & DIGITAL VIBRANCE (DRM COLOR PIPELINE)",
            xalign=0,
        )
        chdr.add_css_class("nv-card-title")
        chdr.set_ellipsize(Pango.EllipsizeMode.END)
        ccard.append(chdr)

        self.scale_brightness, row_bright = self._create_slider_row(
            "Hardware Brightness",
            10,
            100,
            5,
            float(self.cur_display.brightness),
            "%",
            tooltip=(
                "<b>Display Hardware / SDR Brightness</b>\n"
                "Directly controls monitor panel backlighting via DDC/CI hardware commands or software color scaling."
            ),
        )
        ccard.append(row_bright)

        self.scale_vibrance, row_vib = self._create_slider_row(
            "Digital Vibrance (Saturation)",
            -1024,
            1023,
            16,
            float(self.cur_display.vibrance),
            "",
            signed=True,
            tooltip=(
                "<b>NVIDIA Digital Vibrance</b>\n"
                "Adjusts color saturation and richness for games through the Linux DRM hardware color pipeline. Neutral is 0."
            ),
        )
        ccard.append(row_vib)
        box.append(ccard)

        act_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        act_row.add_css_class("nv-card")
        self.lbl_disp_status = Gtk.Label(
            label="Ready to apply display & color configuration.", xalign=0, wrap=True
        )
        self.lbl_disp_status.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.lbl_disp_status.add_css_class("nv-card-sub")
        self.lbl_disp_status.set_hexpand(True)
        act_row.append(self.lbl_disp_status)

        btn_apply_disp = Gtk.Button(label="Apply Display Settings")
        btn_apply_disp.set_valign(Gtk.Align.CENTER)
        btn_apply_disp.add_css_class("nv-primary-btn")
        btn_apply_disp.connect("clicked", self._on_apply_display_clicked)
        act_row.append(btn_apply_disp)
        box.append(act_row)

        scroll.set_child(box)
        return scroll

    def _on_display_selected(self, dd, _pspec):
        idx = dd.get_selected()
        if 0 <= idx < len(self.displays):
            d = self.displays[idx]
            self.cur_display = d
            self.lbl_disp_title.set_label(f"Display Output: {d.connector} — {d.monitor_name}")
            self.lbl_disp_sub.set_label(
                f"DRM Connector: {d.drm_card}-{d.connector}  •  KDE KWin Wayland + NVIDIA DRM Modeset"
            )
            self.dd_disp_mode.set_model(Gtk.StringList.new(d.available_modes))
            if d.current_mode in d.available_modes:
                self.dd_disp_mode.set_selected(d.available_modes.index(d.current_mode))
            vrr_opts = ["automatic", "always", "never"]
            if d.vrr_policy in vrr_opts:
                self.dd_disp_vrr.set_selected(vrr_opts.index(d.vrr_policy))
            rgb_opts = ["automatic", "full", "limited"]
            if d.rgb_range in rgb_opts:
                self.dd_disp_rgb.set_selected(rgb_opts.index(d.rgb_range))
            self.sw_disp_hdr.set_active(d.hdr_enabled)
            self.scale_disp_scale.set_value(int(round(d.scale * 100)))
            self.scale_brightness.set_value(float(d.brightness))
            self.scale_vibrance.set_value(float(d.vibrance))

    def _on_apply_display_clicked(self, _btn):
        d = self.cur_display
        modes = d.available_modes
        mode = modes[self.dd_disp_mode.get_selected()] if modes else d.current_mode
        vrr = ["automatic", "always", "never"][self.dd_disp_vrr.get_selected()]
        rgb = ["automatic", "full", "limited"][self.dd_disp_rgb.get_selected()]
        hdr = self.sw_disp_hdr.get_active()
        scale = self.scale_disp_scale.get_value() / 100.0
        bright = int(round(self.scale_brightness.get_value()))
        vib = int(round(self.scale_vibrance.get_value()))
        d.brightness = bright
        d.vibrance = vib

        ok1, msg1 = self.display_mgr.apply_kscreen_settings(
            d.connector, mode, vrr, hdr, rgb, scale, brightness=bright
        )
        _ok2, msg2 = self.display_mgr.apply_vibrance(vib, d.connector)
        self.lbl_disp_status.set_label(f"{msg1} | {msg2}" if ok1 else f"Note: {msg1} | {msg2}")

    # ------------------------------------------------------------------
    # PAGE 5: SYSTEM & DRIVER INSPECTOR
    # ------------------------------------------------------------------
    def _build_system_page(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_top(16)
        box.set_margin_bottom(18)
        box.set_margin_start(18)
        box.set_margin_end(18)

        sys_details = self.nvml.get_system_details()
        s = self.last_snap

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("nv-card")

        hdr = Gtk.Label(label="NVIDIA GRAPHICS & CACHYOS SYSTEM SPECIFICATIONS", xalign=0)
        hdr.add_css_class("nv-card-title")
        hdr.set_ellipsize(Pango.EllipsizeMode.END)
        card.append(hdr)

        rows = [
            ("GPU Processor", s.name),
            ("NVIDIA Driver Version", s.driver_version),
            ("CUDA Driver Version", s.cuda_version),
            ("VBIOS Version", s.vbios),
            ("GPU UUID", s.uuid),
            ("PCI Bus ID", s.pci_bus_id),
            (
                "PCIe Link Config",
                f"Gen {s.pcie_gen_cur} (Max Gen {s.pcie_gen_max})  •  x{s.pcie_width_cur} (Max x{s.pcie_width_max})",
            ),
            ("Dedicated VRAM", f"{s.vram_total_mib} MiB GDDR6"),
            ("Resizable BAR (BAR1)", f"{s.bar1_total_mib} MiB Total ({s.bar1_used_mib} MiB Used)"),
            (
                "Default / Max Power Cap",
                f"{s.power_default_w:.1f} W  (Range: {s.power_min_w:.1f} W – {s.power_max_w:.1f} W)",
            ),
            (
                "Max Boost / Memory Clock",
                f"{s.clock_graphics_max_mhz} MHz Core  •  {s.clock_mem_max_mhz} MHz Memory",
            ),
            ("Thermal Thresholds", f"{s.temp_slowdown_c}°C Slowdown  •  {s.temp_shutdown_c}°C Shutdown"),
        ]
        for k, v in sys_details.items():
            rows.append((k, v))

        self.sys_report_lines = []
        grid = Gtk.Grid(column_spacing=20, row_spacing=10)
        for idx, (label_text, val_text) in enumerate(rows):
            self.sys_report_lines.append(f"{label_text}: {val_text}")
            k_lbl = Gtk.Label(label=label_text, xalign=0)
            k_lbl.set_valign(Gtk.Align.START)
            k_lbl.add_css_class("nv-card-sub")

            v_lbl = Gtk.Label(label=val_text, xalign=0, selectable=True, wrap=True)
            v_lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            v_lbl.set_hexpand(True)
            grid.attach(k_lbl, 0, idx, 1, 1)
            grid.attach(v_lbl, 1, idx, 1, 1)

        card.append(grid)
        box.append(card)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_row.add_css_class("nv-card")
        self.lbl_sys_copied = Gtk.Label(
            label="Export full hardware, kernel module, and driver report to clipboard.",
            xalign=0,
            wrap=True,
        )
        self.lbl_sys_copied.set_hexpand(True)
        self.lbl_sys_copied.add_css_class("nv-card-sub")
        btn_copy_rep = Gtk.Button(label="Copy Full System Report")
        btn_copy_rep.set_valign(Gtk.Align.CENTER)
        btn_copy_rep.add_css_class("nv-primary-btn")
        btn_copy_rep.connect("clicked", self._on_copy_sys_report)
        btn_row.append(self.lbl_sys_copied)
        btn_row.append(btn_copy_rep)
        box.append(btn_row)

        scroll.set_child(box)
        return scroll

    def _on_copy_sys_report(self, _btn):
        report = "\n".join(self.sys_report_lines)
        Gdk.Display.get_default().get_clipboard().set(report)
        self.lbl_sys_copied.set_label("System report copied to clipboard!")
        self.lbl_sys_copied.add_css_class("nv-status-ok")

    # ------------------------------------------------------------------
    # LIVE TELEMETRY UPDATE LOOP
    # ------------------------------------------------------------------
    def _on_timer_tick(self) -> bool:
        self._refresh_telemetry()
        return True

    @staticmethod
    def _set_label_if_changed(lbl: Gtk.Label, text: str):
        if lbl.get_label() != text:
            lbl.set_label(text)

    def _refresh_telemetry(self):
        snap = self.nvml.poll()
        self.last_snap = snap

        # Update top banner & sidebar brand
        self._set_label_if_changed(self.lbl_gpu_name, snap.name)
        self._set_label_if_changed(
            self.lbl_gpu_sub,
            f"VBIOS {snap.vbios}  •  Bus {snap.pci_bus_id}  •  CUDA {snap.cuda_version}",
        )
        self._set_label_if_changed(self.badge_pstate, f"P{snap.pstate}")
        self._set_label_if_changed(
            self.badge_pcie,
            f"PCIe Gen {snap.pcie_gen_cur}/{snap.pcie_gen_max} x{snap.pcie_width_cur}/{snap.pcie_width_max}",
        )
        self._set_label_if_changed(self.badge_driver, f"Driver {snap.driver_version}")
        self._set_label_if_changed(self.lbl_brand_sub, f"DRIVER {snap.driver_version} • CACHYOS")

        # Sidebar mini status
        fan0 = snap.fan_speeds[0] if snap.fan_speeds else 0
        self._set_label_if_changed(
            self.sidebar_mini_lbl,
            f"{snap.gpu_util}% Load  •  {snap.temp_c}°C  •  {snap.power_draw_w:.1f}W",
        )
        self.sidebar_mini_bar.set_fraction(max(0.0, min(1.0, snap.gpu_util / 100.0)))

        # 4 Metric Cards
        self.card_gpu.update(
            f"{snap.gpu_util}%",
            f"Mem Ctrl: {snap.mem_util}%  •  NVENC: {snap.enc_util}%  •  NVDEC: {snap.dec_util}%",
            snap.gpu_util / 100.0,
        )
        vram_frac = snap.vram_used_mib / float(max(1, snap.vram_total_mib))
        self.card_vram.update(
            f"{snap.vram_used_mib} / {snap.vram_total_mib} MiB",
            f"Free: {snap.vram_free_mib} MiB  •  BAR1: {snap.bar1_used_mib}/{snap.bar1_total_mib} MiB",
            vram_frac,
        )
        pol_str = "Manual" if snap.fan_policy == 1 else "Auto"
        self.card_temp.update(
            f"{snap.temp_c}°C   •   Fan {fan0}%",
            f"Policy: {pol_str}  •  Slowdown: {snap.temp_slowdown_c}°C",
            snap.temp_c / float(max(1, snap.temp_slowdown_c)),
        )
        pwr_frac = snap.power_draw_w / float(max(1.0, snap.power_limit_w))
        self.card_power.update(
            f"{snap.power_draw_w:.1f} / {snap.power_limit_w:.0f} W",
            f"Core: {snap.clock_graphics_mhz} MHz ({snap.core_offset_mhz:+d})  •  Mem: {snap.clock_mem_mhz} MHz ({snap.mem_offset_mhz:+d})",
            pwr_frac,
        )

        # 4 Graphs
        self.graph_util.update_data(self.nvml.hist_gpu_util, f"{snap.gpu_util}%")
        self.graph_clocks.update_data(
            self.nvml.hist_clock_gfx,
            f"{snap.clock_graphics_mhz} MHz",
            max_val=max(2100, snap.clock_graphics_max_mhz),
        )
        self.graph_temp.update_data(self.nvml.hist_temp, f"{snap.temp_c}°C  (Fan {fan0}%)")
        self.graph_power.update_data(
            self.nvml.hist_power,
            f"{snap.power_draw_w:.1f} W",
            max_val=max(75.0, snap.power_max_w),
        )

        # Fan curve live temperature line & automatic software fan curve evaluation
        self.fan_curve_editor.set_current_temp(snap.temp_c)
        if (
            self.dd_fan_mode.get_selected() == 2
            and not self._fan_apply_in_flight
            and (
                Path("/etc/polkit-1/rules.d/90-nvidia-control-center.rules").exists()
                or Path("/usr/share/polkit-1/rules.d/90-nvidia-control-center.rules").exists()
            )
        ):
            target_spd = self.nvml.evaluate_fan_curve(
                self.tuning_cfg.get("fan_curve_points", []),
                snap.temp_c,
            )
            if self._last_curve_fan_speed is None or abs(target_spd - self._last_curve_fan_speed) >= 3:
                self._last_curve_fan_speed = target_spd
                self._fan_apply_in_flight = True

                def _apply_curve_spd(spd=target_spd):
                    try:
                        self.nvml.apply_hardware_tuning(fan_mode="manual", fan_speed=spd)
                    finally:
                        self._fan_apply_in_flight = False

                threading.Thread(target=_apply_curve_spd, daemon=True).start()

        # Throttle & Bus info
        reasons_str = ", ".join(snap.throttle_reasons) if snap.throttle_reasons else "None (Full Boost Active)"
        self._set_label_if_changed(self.lbl_throttle, f"Active Clock Limiters: {reasons_str}")
        self._set_label_if_changed(
            self.lbl_bus_stats,
            f"PCIe Bandwidth: TX {snap.pcie_tx_kbps / 1024.0:.2f} MB/s  •  RX {snap.pcie_rx_kbps / 1024.0:.2f} MB/s\n"
            f"SM Clock: {snap.clock_sm_mhz} MHz  •  Video Clock: {snap.clock_video_mhz} MHz",
        )

        # Active Processes List (Only rebuild widget tree when process list signature changes)
        proc_sig = [(p.pid, p.name, p.engine, p.vram_mib) for p in snap.processes[:8]]
        if proc_sig != self._last_proc_signature:
            self._last_proc_signature = proc_sig
            child = self.proc_list_box.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                self.proc_list_box.remove(child)
                child = nxt

            if not proc_sig:
                empty_lbl = Gtk.Label(
                    label="No active graphics/compute processes reported by NVML in this namespace.",
                    xalign=0,
                    wrap=True,
                )
                empty_lbl.add_css_class("nv-card-sub")
                self.proc_list_box.append(empty_lbl)
            else:
                for pid, name, engine, vram_mib in proc_sig:
                    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                    name_lbl = Gtk.Label(label=f"{name} (PID {pid})", xalign=0)
                    name_lbl.set_ellipsize(Pango.EllipsizeMode.END)
                    name_lbl.set_hexpand(True)
                    eng_lbl = Gtk.Label(label=engine, xalign=0)
                    eng_lbl.add_css_class("nv-badge-muted")
                    vram_txt = f"{vram_mib} MiB" if vram_mib is not None else "Shared"
                    mem_lbl = Gtk.Label(label=vram_txt, xalign=1)
                    mem_lbl.add_css_class("nv-status-ok")
                    row.append(name_lbl)
                    row.append(eng_lbl)
                    row.append(mem_lbl)
                    self.proc_list_box.append(row)


class NvidiaControlCenterApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.cachyos.NvidiaControlCenter")
        self.win = None

    def do_activate(self):
        if not self.win:
            self.win = NvidiaControlCenterWindow(self)
        self.win.present()


def main():
    app = NvidiaControlCenterApp()
    sys.exit(app.run(sys.argv))
