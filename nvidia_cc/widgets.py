"""
Custom GTK4 + Cairo Liquid Glass widgets for NVIDIA Control Center:
- TelemetryGraph: Real-time smooth spline area chart with Liquid Glass surface, glow stroke, and live orb.
- FanCurveEditor: Interactive 5-point temperature-to-fan-speed curve editor with hover/drag physics.
- MetricCard: Liquid Glass dashboard telemetry stat card.
"""

import math
from typing import Callable, List, Optional, Sequence, Tuple
import cairo
import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk, Pango  # noqa: E402


def _rounded_rect(cr: cairo.Context, x: float, y: float, w: float, h: float, radius: float):
    r = max(0.0, min(radius, w / 2.0, h / 2.0))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _draw_glass_surface(
    cr: cairo.Context,
    width: int,
    height: int,
    radius: float = 14.0,
    accent_rgb: Optional[Tuple[float, float, float]] = None,
):
    """Renders a translucent Liquid Glass card backdrop with refractive top specular edge."""
    if width <= 2 or height <= 2:
        return

    # Base liquid glass vertical gradient
    bg_grad = cairo.LinearGradient(0, 0, 0, height)
    bg_grad.add_color_stop_rgba(0.0, 0.125, 0.155, 0.205, 0.72)
    bg_grad.add_color_stop_rgba(0.45, 0.082, 0.102, 0.138, 0.78)
    bg_grad.add_color_stop_rgba(1.0, 0.055, 0.070, 0.098, 0.88)
    _rounded_rect(cr, 0.5, 0.5, width - 1.0, height - 1.0, radius)
    cr.set_source(bg_grad)
    cr.fill_preserve()

    # Subtle ambient radial tint in top-right if accent provided
    if accent_rgb is not None:
        ar, ag, ab = accent_rgb
        rad = cairo.RadialGradient(width * 0.82, height * 0.15, 4.0, width * 0.82, height * 0.15, max(width, height) * 0.65)
        rad.add_color_stop_rgba(0.0, ar, ag, ab, 0.11)
        rad.add_color_stop_rgba(1.0, ar, ag, ab, 0.0)
        cr.set_source(rad)
        cr.fill_preserve()

    # Outer refractive border (brighter on top, softer on bottom)
    border_grad = cairo.LinearGradient(0, 0, 0, height)
    border_grad.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.22)
    border_grad.add_color_stop_rgba(0.35, 1.0, 1.0, 1.0, 0.09)
    border_grad.add_color_stop_rgba(1.0, 1.0, 1.0, 1.0, 0.05)
    cr.set_source(border_grad)
    cr.set_line_width(1.0)
    cr.stroke()

    # Top specular sheen line
    sheen_w = max(0.0, width - 2 * radius)
    if sheen_w > 12:
        sheen = cairo.LinearGradient(radius, 1.2, width - radius, 1.2)
        sheen.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.0)
        sheen.add_color_stop_rgba(0.25, 1.0, 1.0, 1.0, 0.28)
        sheen.add_color_stop_rgba(0.75, 1.0, 1.0, 1.0, 0.28)
        sheen.add_color_stop_rgba(1.0, 1.0, 1.0, 1.0, 0.0)
        cr.set_source(sheen)
        cr.set_line_width(1.0)
        cr.move_to(radius, 1.2)
        cr.line_to(width - radius, 1.2)
        cr.stroke()


def _trace_smooth_spline(
    cr: cairo.Context,
    pts: Sequence[Tuple[float, float]],
    min_y: float,
    max_y: float,
):
    """Traces a smooth Catmull-Rom cubic Bezier path through pts, clamped to [min_y, max_y]."""
    n = len(pts)
    if n == 0:
        return
    cr.move_to(pts[0][0], pts[0][1])
    if n == 1:
        return
    if n == 2:
        cr.line_to(pts[1][0], pts[1][1])
        return

    for i in range(n - 1):
        p0 = pts[max(0, i - 1)]
        p1 = pts[i]
        p2 = pts[i + 1]
        p3 = pts[min(n - 1, i + 2)]

        cp1x = p1[0] + (p2[0] - p0[0]) / 6.0
        cp1y = max(min_y, min(max_y, p1[1] + (p2[1] - p0[1]) / 6.0))
        cp2x = p2[0] - (p3[0] - p1[0]) / 6.0
        cp2y = max(min_y, min(max_y, p2[1] - (p3[1] - p1[1]) / 6.0))
        cr.curve_to(cp1x, cp1y, cp2x, cp2y, p2[0], p2[1])


class TelemetryGraph(Gtk.DrawingArea):
    """Smooth real-time Cairo Liquid Glass area chart."""

    def __init__(
        self,
        title: str,
        unit: str = "%",
        min_val: float = 0.0,
        max_val: float = 100.0,
        rgb: Tuple[float, float, float] = (0.463, 0.725, 0.0),
        height: int = 148,
    ):
        super().__init__()
        self.title = title
        self.unit = unit
        self.min_val = min_val
        self.max_val = max_val
        self.rgb = rgb
        self.values: List[float] = [0.0] * 60
        self.subtitle: str = ""

        self.set_content_width(180)
        self.set_content_height(height)
        self.set_hexpand(True)
        self.set_draw_func(self._on_draw)

    def update_data(
        self,
        values: Sequence[float],
        subtitle: str = "",
        max_val: Optional[float] = None,
    ):
        self.values = list(values) if values else [0.0]
        if subtitle:
            self.subtitle = subtitle
        if max_val is not None and max_val > self.min_val:
            self.max_val = max_val
        self.queue_draw()

    def _on_draw(self, _area, cr: cairo.Context, width: int, height: int):
        if width <= 10 or height <= 10:
            return

        r, g, b = self.rgb
        _draw_glass_surface(cr, width, height, radius=14.0, accent_rgb=self.rgb)

        pad_l, pad_r, pad_t, pad_b = 16.0, 16.0, 42.0, 14.0
        plot_w = max(10.0, width - pad_l - pad_r)
        plot_h = max(10.0, height - pad_t - pad_b)

        # Horizontal glass grid lines
        cr.set_line_width(1.0)
        for i in range(5):
            y = pad_t + (plot_h * i / 4.0)
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.055 if i in (0, 4) else 0.035)
            cr.move_to(pad_l, y)
            cr.line_to(pad_l + plot_w, y)
            cr.stroke()

        # Live value badge on top-right
        cur_val = self.values[-1] if self.values else 0.0
        val_str = self.subtitle if self.subtitle else f"{cur_val:.0f} {self.unit}"
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(12.0)
        val_ext = cr.text_extents(val_str)

        pill_pad_x = 9.0
        pill_h = 22.0
        pill_w = val_ext.width + pill_pad_x * 2
        pill_x = max(pad_l, width - pad_r - pill_w)
        pill_y = 10.0

        _rounded_rect(cr, pill_x, pill_y, pill_w, pill_h, 7.0)
        cr.set_source_rgba(r, g, b, 0.16)
        cr.fill_preserve()
        cr.set_source_rgba(r, g, b, 0.42)
        cr.set_line_width(1.0)
        cr.stroke()

        cr.set_source_rgb(min(1.0, r + 0.18), min(1.0, g + 0.18), min(1.0, b + 0.18))
        cr.move_to(pill_x + pill_pad_x, pill_y + 15.0)
        cr.show_text(val_str)

        # Title on top-left (truncated cleanly so it never collides with value pill)
        avail_title_w = max(20.0, pill_x - pad_l - 10.0)
        cr.set_font_size(12.0)
        title_str = self.title
        if cr.text_extents(title_str).width > avail_title_w:
            while len(title_str) > 3 and cr.text_extents(title_str + "…").width > avail_title_w:
                title_str = title_str[:-1]
            title_str = title_str.rstrip() + "…"

        cr.set_source_rgba(0.90, 0.93, 0.97, 0.92)
        cr.move_to(pad_l, 25.0)
        cr.show_text(title_str)

        if len(self.values) < 2:
            return

        span = max(1e-6, self.max_val - self.min_val)
        n = len(self.values)
        pts: List[Tuple[float, float]] = []
        for idx, val in enumerate(self.values):
            clamped = max(self.min_val, min(self.max_val, float(val)))
            norm = (clamped - self.min_val) / span
            x = pad_l + (idx / float(n - 1)) * plot_w
            y = pad_t + plot_h - (norm * plot_h)
            pts.append((x, y))

        # Clip plot area so spline and glow stay inside chart bounds
        cr.save()
        cr.rectangle(pad_l - 2.0, pad_t - 4.0, plot_w + 8.0, plot_h + 8.0)
        cr.clip()

        # Luminous gradient fill under smooth spline
        cr.new_path()
        _trace_smooth_spline(cr, pts, pad_t, pad_t + plot_h)
        cr.line_to(pts[-1][0], pad_t + plot_h)
        cr.line_to(pts[0][0], pad_t + plot_h)
        cr.close_path()

        fill_grad = cairo.LinearGradient(0, pad_t, 0, pad_t + plot_h)
        fill_grad.add_color_stop_rgba(0.0, r, g, b, 0.42)
        fill_grad.add_color_stop_rgba(0.65, r, g, b, 0.12)
        fill_grad.add_color_stop_rgba(1.0, r, g, b, 0.01)
        cr.set_source(fill_grad)
        cr.fill()

        # Soft outer glow stroke
        cr.new_path()
        _trace_smooth_spline(cr, pts, pad_t, pad_t + plot_h)
        cr.set_source_rgba(r, g, b, 0.24)
        cr.set_line_width(5.0)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.stroke()

        # Crisp top spline stroke
        cr.new_path()
        _trace_smooth_spline(cr, pts, pad_t, pad_t + plot_h)
        cr.set_source_rgb(min(1.0, r + 0.1), min(1.0, g + 0.1), min(1.0, b + 0.1))
        cr.set_line_width(2.2)
        cr.stroke()
        cr.restore()

        # Glowing live orb at latest data point
        lx, ly = pts[-1]
        cr.set_source_rgba(r, g, b, 0.32)
        cr.arc(lx, ly, 6.5, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgb(1.0, 1.0, 1.0)
        cr.arc(lx, ly, 3.0, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgb(r, g, b)
        cr.set_line_width(1.6)
        cr.arc(lx, ly, 3.5, 0, 2 * math.pi)
        cr.stroke()


class FanCurveEditor(Gtk.DrawingArea):
    """Interactive 5-node Liquid Glass fan curve editor (Temp 20–100°C vs Fan Speed 0–100%)."""

    def __init__(
        self,
        points: List[List[int]],
        on_change: Callable[[List[List[int]]], None],
    ):
        super().__init__()
        self.points = [list(p) for p in points]
        self.on_change = on_change
        self.current_temp = 40
        self.dragging_idx = -1
        self.hover_idx = -1
        self._drag_node_origin = (0.0, 0.0)

        self.set_content_width(240)
        self.set_content_height(225)
        self.set_hexpand(True)
        self.set_draw_func(self._on_draw)

        drag = Gtk.GestureDrag.new()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        motion = Gtk.EventControllerMotion.new()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

    def set_points(self, points: List[List[int]]):
        self.points = [list(p) for p in points]
        self.queue_draw()

    def set_current_temp(self, temp_c: int):
        if self.current_temp != temp_c:
            self.current_temp = temp_c
            self.queue_draw()

    @staticmethod
    def _plot_bounds(width: int, height: int) -> Tuple[float, float, float, float]:
        pad_l, pad_r, pad_t, pad_b = 46.0, 22.0, 34.0, 32.0
        return pad_l, pad_t, max(20.0, width - pad_l - pad_r), max(20.0, height - pad_t - pad_b)

    def _pt_to_screen(self, temp: float, speed: float, width: int, height: int) -> Tuple[float, float]:
        pl, pt, pw, ph = self._plot_bounds(width, height)
        x = pl + ((temp - 20.0) / 80.0) * pw
        y = pt + ph - (speed / 100.0) * ph
        return x, y

    def _screen_to_pt(self, x: float, y: float, width: int, height: int) -> Tuple[int, int]:
        pl, pt, pw, ph = self._plot_bounds(width, height)
        temp = 20.0 + ((x - pl) / float(pw)) * 80.0
        speed = ((pt + ph - y) / float(ph)) * 100.0
        return int(round(max(20.0, min(100.0, temp)))), int(round(max(0.0, min(100.0, speed))))

    def _find_nearest_node(self, x: float, y: float, radius: float = 22.0) -> int:
        w, h = self.get_width(), self.get_height()
        best_idx = -1
        best_dist = radius
        for idx, (t, s) in enumerate(self.points):
            px, py = self._pt_to_screen(t, s, w, h)
            dist = math.hypot(px - x, py - y)
            if dist < best_dist:
                best_dist = dist
                best_idx = idx
        return best_idx

    def _on_motion(self, _ctrl, x: float, y: float):
        if self.dragging_idx >= 0:
            return
        idx = self._find_nearest_node(x, y)
        if idx != self.hover_idx:
            self.hover_idx = idx
            self.set_cursor_from_name("grab" if idx >= 0 else None)
            self.queue_draw()

    def _on_leave(self, _ctrl):
        if self.dragging_idx < 0 and self.hover_idx != -1:
            self.hover_idx = -1
            self.set_cursor_from_name(None)
            self.queue_draw()

    def _on_drag_begin(self, _gesture, start_x: float, start_y: float):
        w, h = self.get_width(), self.get_height()
        idx = self._find_nearest_node(start_x, start_y, radius=26.0)
        self.dragging_idx = idx
        if idx >= 0:
            t, s = self.points[idx]
            self._drag_node_origin = self._pt_to_screen(t, s, w, h)
            self.set_cursor_from_name("grabbing")
            self.queue_draw()

    def _on_drag_update(self, _gesture, offset_x: float, offset_y: float):
        if self.dragging_idx < 0:
            return
        w, h = self.get_width(), self.get_height()
        cur_x = self._drag_node_origin[0] + offset_x
        cur_y = self._drag_node_origin[1] + offset_y
        new_t, new_s = self._screen_to_pt(cur_x, cur_y, w, h)

        idx = self.dragging_idx
        if idx > 0:
            new_t = max(new_t, self.points[idx - 1][0] + 3)
        if idx < len(self.points) - 1:
            new_t = min(new_t, self.points[idx + 1][0] - 3)

        if self.points[idx] != [new_t, new_s]:
            self.points[idx] = [new_t, new_s]
            self.queue_draw()
            if self.on_change:
                self.on_change(self.points)

    def _on_drag_end(self, _gesture, _offset_x: float, _offset_y: float):
        self.dragging_idx = -1
        self.set_cursor_from_name("grab" if self.hover_idx >= 0 else None)
        self.queue_draw()

    def _eval_speed_at_temp(self, temp_c: float) -> int:
        if not self.points:
            return 50
        pts = sorted(self.points, key=lambda p: p[0])
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
                return int(round(s0 + ((temp_c - t0) / float(t1 - t0)) * (s1 - s0)))
        return 50

    def _on_draw(self, _area, cr: cairo.Context, width: int, height: int):
        if width <= 10 or height <= 10:
            return

        _draw_glass_surface(cr, width, height, radius=14.0, accent_rgb=(0.463, 0.725, 0.0))
        pl, pt, pw, ph = self._plot_bounds(width, height)

        # Header title & live operating point readout
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11.5)
        cr.set_source_rgba(0.86, 0.90, 0.95, 0.88)
        cr.move_to(pl, 21.0)
        cr.show_text("TEMPERATURE (°C)  →  TARGET FAN SPEED (%)")

        live_spd = self._eval_speed_at_temp(self.current_temp)
        live_txt = f"Live: {self.current_temp}°C → {live_spd}%"
        ext = cr.text_extents(live_txt)
        if width - 16 - ext.width > pl + 240:
            cr.set_source_rgb(0.98, 0.68, 0.20)
            cr.move_to(width - 18.0 - ext.width, 21.0)
            cr.show_text(live_txt)

        # Grid and axis labels
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(10.5)
        for i, pct in enumerate([100, 75, 50, 25, 0]):
            y = pt + (ph * i / 4.0)
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.06)
            cr.set_line_width(1.0)
            cr.move_to(pl, y)
            cr.line_to(pl + pw, y)
            cr.stroke()
            cr.set_source_rgba(0.75, 0.80, 0.88, 0.82)
            cr.move_to(10.0, y + 4.0)
            cr.show_text(f"{pct}%")

        for temp in [20, 40, 60, 80, 100]:
            x = pl + ((temp - 20.0) / 80.0) * pw
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.05)
            cr.set_line_width(1.0)
            cr.move_to(x, pt)
            cr.line_to(x, pt + ph)
            cr.stroke()
            lbl = f"{temp}°C"
            t_ext = cr.text_extents(lbl)
            lx = max(4.0, min(width - t_ext.width - 4.0, x - t_ext.width / 2.0))
            cr.set_source_rgba(0.75, 0.80, 0.88, 0.82)
            cr.move_to(lx, pt + ph + 19.0)
            cr.show_text(lbl)

        # Curve fill and stroke
        scr_pts = [self._pt_to_screen(t, s, width, height) for t, s in self.points]
        if len(scr_pts) >= 2:
            # Fill under curve
            cr.move_to(pl, pt + ph)
            cr.line_to(pl, scr_pts[0][1])
            for x, y in scr_pts:
                cr.line_to(x, y)
            cr.line_to(pl + pw, scr_pts[-1][1])
            cr.line_to(pl + pw, pt + ph)
            cr.close_path()

            grad = cairo.LinearGradient(0, pt, 0, pt + ph)
            grad.add_color_stop_rgba(0.0, 0.463, 0.725, 0.0, 0.30)
            grad.add_color_stop_rgba(1.0, 0.463, 0.725, 0.0, 0.02)
            cr.set_source(grad)
            cr.fill()

            # Glow stroke
            cr.set_source_rgba(0.463, 0.725, 0.0, 0.25)
            cr.set_line_width(5.5)
            cr.move_to(pl, scr_pts[0][1])
            for x, y in scr_pts:
                cr.line_to(x, y)
            cr.line_to(pl + pw, scr_pts[-1][1])
            cr.stroke()

            # Main curve stroke
            cr.set_source_rgb(0.54, 0.85, 0.04)
            cr.set_line_width(2.4)
            cr.move_to(pl, scr_pts[0][1])
            for x, y in scr_pts:
                cr.line_to(x, y)
            cr.line_to(pl + pw, scr_pts[-1][1])
            cr.stroke()

        # Live temperature vertical line & intersection marker
        clamped_temp = max(20, min(100, self.current_temp))
        tx, ty = self._pt_to_screen(clamped_temp, live_spd, width, height)
        cr.set_source_rgba(0.98, 0.65, 0.15, 0.55)
        cr.set_line_width(1.5)
        cr.set_dash([4.0, 4.0])
        cr.move_to(tx, pt)
        cr.line_to(tx, pt + ph)
        cr.stroke()
        cr.set_dash([])

        cr.set_source_rgba(0.98, 0.65, 0.15, 0.28)
        cr.arc(tx, ty, 7.5, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgb(0.98, 0.68, 0.18)
        cr.arc(tx, ty, 3.8, 0, 2 * math.pi)
        cr.fill()

        # Draggable nodes & smart-clamped pill labels
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(10.0)
        for idx, ((t, s), (x, y)) in enumerate(zip(self.points, scr_pts)):
            is_active = idx in (self.dragging_idx, self.hover_idx)
            node_r = 8.0 if is_active else 6.5

            if is_active:
                cr.set_source_rgba(0.55, 0.88, 0.05, 0.32)
                cr.arc(x, y, 13.0, 0, 2 * math.pi)
                cr.fill()

            cr.set_source_rgb(0.08, 0.10, 0.14)
            cr.arc(x, y, node_r, 0, 2 * math.pi)
            cr.fill()

            cr.set_source_rgb(0.62, 0.96, 0.10) if is_active else cr.set_source_rgb(0.463, 0.725, 0.0)
            cr.set_line_width(2.5)
            cr.arc(x, y, node_r, 0, 2 * math.pi)
            cr.stroke()

            tag = f"{t}°:{s}%"
            ext = cr.text_extents(tag)
            tx_lbl = max(pl + 2.0, min(pl + pw - ext.width - 2.0, x - ext.width / 2.0))
            ty_lbl = y - 12.0 if y - 18.0 >= pt else y + 20.0

            _rounded_rect(cr, tx_lbl - 4.0, ty_lbl - 10.5, ext.width + 8.0, 14.0, 4.0)
            cr.set_source_rgba(0.05, 0.07, 0.10, 0.82)
            cr.fill()

            cr.set_source_rgba(0.95, 0.98, 1.0, 0.95)
            cr.move_to(tx_lbl, ty_lbl)
            cr.show_text(tag)


class MetricCard(Gtk.Box):
    """Liquid Glass telemetry stat card with header, primary readout, subtitle, and glowing progress bar."""

    def __init__(self, title: str, initial_val: str = "0"):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add_css_class("nv-card")
        self.add_css_class("nv-metric-card")
        self.set_hexpand(True)

        hdr_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        dot = Gtk.Box()
        dot.set_size_request(7, 7)
        dot.set_valign(Gtk.Align.CENTER)
        dot.add_css_class("nv-card-dot")
        hdr_row.append(dot)

        self.title_lbl = Gtk.Label(label=title, xalign=0)
        self.title_lbl.add_css_class("nv-card-title")
        self.title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.title_lbl.set_hexpand(True)
        hdr_row.append(self.title_lbl)
        self.append(hdr_row)

        self.val_lbl = Gtk.Label(label=initial_val, xalign=0)
        self.val_lbl.add_css_class("nv-card-value")
        self.val_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.val_lbl.set_hexpand(True)
        self.append(self.val_lbl)

        self.sub_lbl = Gtk.Label(label="", xalign=0)
        self.sub_lbl.add_css_class("nv-card-sub")
        self.sub_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.sub_lbl.set_hexpand(True)
        self.append(self.sub_lbl)

        self.bar = Gtk.ProgressBar()
        self.bar.add_css_class("nv-progress")
        self.bar.set_margin_top(2)
        self.append(self.bar)

    def update(self, value_text: str, sub_text: str, fraction: float):
        if self.val_lbl.get_label() != value_text:
            self.val_lbl.set_label(value_text)
        if self.sub_lbl.get_label() != sub_text:
            self.sub_lbl.set_label(sub_text)
        clamped = max(0.0, min(1.0, fraction))
        if abs(self.bar.get_fraction() - clamped) > 0.002:
            self.bar.set_fraction(clamped)
