#!/usr/bin/env python3
"""Mini player popup for the waybar music module."""

import atexit
import os
import signal
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
gi.require_version("GtkLayerShell", "0.1")

from gi.repository import (  # noqa: E402
    Gdk,
    GdkPixbuf,
    GLib,
    Gtk,
    Pango,
    PangoCairo,
    GtkLayerShell,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import music_lib  # noqa: E402

COVER_SIZE = 160
PIDFILE = os.path.join(music_lib.CACHE_DIR, "music-popup.pid")

# rofi purple theme + kitty ANSI palette (same as waybar/style.css)
CSS = """
window { background-color: transparent; }

.player {
    background-color: #2f1e2e;
    border: 1px solid #3b2839;
    padding: 16px;
    font-family: "JetBrainsMono Nerd Font";
}

.title  { font-size: 14px; font-weight: 700; color: #eff0f1; }
.artist { font-size: 12px; color: #b48ead; }
.album  { font-size: 11px; color: #7f8c8d; }
.state  { font-size: 10px; color: #7f8c8d; }
.time   { font-size: 10px; color: #7f8c8d; }

button.ctl {
    background: none;
    border: none;
    border-radius: 0;
    box-shadow: none;
    color: #eff0f1;
    font-size: 17px;
    padding: 8px 12px;
    min-width: 22px;
}
button.ctl:hover { background-color: #3b2839; }

button.play {
    background-color: #815ba4;
    color: #ffffff;
    font-size: 20px;
    padding: 12px 18px;
}
button.play:hover { background-color: #9469bb; }

button.close {
    background: none;
    border: none;
    border-radius: 0;
    box-shadow: none;
    color: #7f8c8d;
    font-size: 13px;
    padding: 4px 8px;
    min-width: 0;
}
button.close:hover { color: #ef6155; }
"""


def fmt_time(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def toggle_instance():
    """Exit quietly if this popup is already open (second run = close)."""
    try:
        with open(PIDFILE, encoding="utf-8") as handle:
            pid = int(handle.read().strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        pid = None
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        return True
    return False


class CoverArt(Gtk.DrawingArea):
    """Album art, cover-cropped to a square."""

    def __init__(self):
        super().__init__()
        self.set_size_request(COVER_SIZE, COVER_SIZE)
        self._stamp = (None, None)
        self._pixbuf = None
        self.connect("draw", self._on_draw)

    def set_path(self, path):
        # The cache path is stable across tracks, so compare the file's mtime
        # too -- otherwise a new song would keep showing the old cover.
        try:
            stamp = os.stat(path).st_mtime_ns if path else None
        except OSError:
            stamp = None
        if (path, stamp) == self._stamp:
            return
        self._stamp = (path, stamp)
        self._pixbuf = self._load(path)
        self.queue_draw()

    @staticmethod
    def _load(path):
        if not path or not os.path.exists(path):
            return None
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        except GLib.Error:
            return None
        width, height = pixbuf.get_width(), pixbuf.get_height()
        side = min(width, height)
        pixbuf = pixbuf.new_subpixbuf((width - side) // 2, (height - side) // 2, side, side)
        return pixbuf.scale_simple(COVER_SIZE, COVER_SIZE, GdkPixbuf.InterpType.BILINEAR)

    def _on_draw(self, _widget, cr):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        if self._pixbuf is None:
            cr.set_source_rgb(0x3B / 255, 0x28 / 255, 0x39 / 255)
            cr.rectangle(0, 0, width, height)
            cr.fill()

            layout = PangoCairo.create_layout(cr)
            layout.set_text("♪", -1)
            desc = Pango.FontDescription()
            desc.set_family("JetBrainsMono Nerd Font")
            desc.set_size(44 * Pango.SCALE)
            layout.set_font_description(desc)
            text_width, text_height = layout.get_pixel_size()
            cr.set_source_rgb(0x7F / 255, 0x8C / 255, 0x8D / 255)
            cr.move_to((width - text_width) / 2, (height - text_height) / 2)
            PangoCairo.show_layout(cr, layout)
            return False

        Gdk.cairo_set_source_pixbuf(cr, self._pixbuf, 0, 0)
        cr.paint()
        return False


class SeekBar(Gtk.DrawingArea):
    """Flat progress bar: click or drag to jump to another point."""

    BAR = 4
    HEIGHT = 18

    def __init__(self, on_seek, on_preview):
        super().__init__()
        self.set_size_request(-1, self.HEIGHT)
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )
        self._on_seek = on_seek
        self._on_preview = on_preview
        self._dragging = False
        self.fraction = 0.0
        self.seekable = False
        self.set_tooltip_text("Click or drag to seek")
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._pressed)
        self.connect("motion-notify-event", self._moved)
        self.connect("button-release-event", self._released)
        self.connect("enter-notify-event", self._enter)
        self.connect("leave-notify-event", self._leave)
        self._cursor = Gdk.Cursor.new_for_display(
            Gdk.Display.get_default(), Gdk.CursorType.HAND2
        )

    def set_fraction(self, fraction):
        if self._dragging:
            return
        self.fraction = max(0.0, min(1.0, fraction))
        self.queue_draw()

    def _fraction_at(self, x):
        width = max(1, self.get_allocated_width())
        return max(0.0, min(1.0, x / width))

    def _draw(self, _widget, cr):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        top = (height - self.BAR) / 2

        cr.set_source_rgb(0x3B / 255, 0x28 / 255, 0x39 / 255)
        cr.rectangle(0, top, width, self.BAR)
        cr.fill()

        filled = width * self.fraction
        cr.set_source_rgb(0x81 / 255, 0x5B / 255, 0xA4 / 255)
        cr.rectangle(0, top, filled, self.BAR)
        cr.fill()

        if self.seekable:
            cr.set_source_rgb(0xB4 / 255, 0x8E / 255, 0xAD / 255)
            cr.rectangle(max(0, filled - 1), top - 3, 2, self.BAR + 6)
            cr.fill()
        return False

    def _pressed(self, _widget, event):
        if not self.seekable or event.button != 1:
            return False
        self._dragging = True
        self.fraction = self._fraction_at(event.x)
        self.queue_draw()
        self._on_preview(self.fraction)
        return True

    def _moved(self, _widget, event):
        if not self._dragging:
            return False
        self.fraction = self._fraction_at(event.x)
        self.queue_draw()
        self._on_preview(self.fraction)
        return True

    def _released(self, _widget, event):
        if not self._dragging:
            return False
        self._dragging = False
        self.fraction = self._fraction_at(event.x)
        self.queue_draw()
        self._on_seek(self.fraction)
        return True

    def _enter(self, widget, _event):
        widget.get_window().set_cursor(self._cursor)
        return False

    def _leave(self, widget, _event):
        widget.get_window().set_cursor(None)
        return False


class MusicPopup(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)
        self.set_app_paintable(True)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 6)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, 10)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)

        self.player = None
        self.length = 0.0
        self._had_focus = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        root.get_style_context().add_class("player")

        overlay = Gtk.Overlay()
        overlay.add(root)
        self.add(overlay)

        # ---- cover + text -------------------------------------------------
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        root.pack_start(top, False, False, 0)

        self.cover = CoverArt()
        top.pack_start(self.cover, False, False, 0)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        info.set_size_request(190, -1)
        info.set_valign(Gtk.Align.START)
        top.pack_start(info, True, True, 0)

        self.title = Gtk.Label(xalign=0)
        self.title.get_style_context().add_class("title")
        self.title.set_line_wrap(True)
        self.title.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.title.set_lines(3)
        self.title.set_ellipsize(Pango.EllipsizeMode.END)
        self.title.set_max_width_chars(22)
        info.pack_start(self.title, False, False, 0)

        self.artist = Gtk.Label(xalign=0)
        self.artist.get_style_context().add_class("artist")
        self.artist.set_ellipsize(Pango.EllipsizeMode.END)
        self.artist.set_max_width_chars(28)
        info.pack_start(self.artist, False, False, 0)

        self.album = Gtk.Label(xalign=0)
        self.album.get_style_context().add_class("album")
        self.album.set_ellipsize(Pango.EllipsizeMode.END)
        self.album.set_max_width_chars(32)
        info.pack_start(self.album, False, False, 0)

        self.state = Gtk.Label(xalign=0)
        self.state.get_style_context().add_class("state")
        self.state.set_ellipsize(Pango.EllipsizeMode.END)
        info.pack_start(self.state, False, False, 0)

        # ---- seek ---------------------------------------------------------
        self.seek = SeekBar(self._seek, self._preview)
        root.pack_start(self.seek, False, False, 0)

        times = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.times = times
        root.pack_start(times, False, False, 0)

        self.position = Gtk.Label(label="0:00", xalign=0)
        self.position.get_style_context().add_class("time")
        times.pack_start(self.position, False, False, 0)

        self.total = Gtk.Label(label="0:00", xalign=1)
        self.total.get_style_context().add_class("time")
        times.pack_end(self.total, False, False, 0)

        # ---- controls -----------------------------------------------------
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.controls = controls
        controls.set_halign(Gtk.Align.CENTER)
        root.pack_start(controls, False, False, 0)

        self.prev = Gtk.Button(label="\uf048")
        self.prev.get_style_context().add_class("ctl")
        self.prev.set_tooltip_text("Previous track")
        self.prev.connect("clicked", lambda *_: self.control("previous"))
        controls.pack_start(self.prev, False, False, 0)

        self.play = Gtk.Button(label="\uf04b")
        self.play.get_style_context().add_class("ctl")
        self.play.get_style_context().add_class("play")
        self.play.set_tooltip_text("Play / pause")
        self.play.connect("clicked", lambda *_: self.control("play-pause"))
        controls.pack_start(self.play, False, False, 0)

        self.next = Gtk.Button(label="\uf051")
        self.next.get_style_context().add_class("ctl")
        self.next.set_tooltip_text("Next track")
        self.next.connect("clicked", lambda *_: self.control("next"))
        controls.pack_start(self.next, False, False, 0)

        close = Gtk.Button(label="✕")
        close.get_style_context().add_class("close")
        close.set_tooltip_text("Close")
        close.set_halign(Gtk.Align.END)
        close.set_valign(Gtk.Align.START)
        close.set_margin_top(6)
        close.set_margin_end(6)
        close.connect("clicked", lambda *_: self.destroy())
        overlay.add_overlay(close)

        self.connect("destroy", lambda *_: Gtk.main_quit())
        self.connect("key-press-event", self._on_key)
        self.connect("focus-in-event", self._on_focus_in)
        self.connect("focus-out-event", self._on_focus_out)

        GLib.timeout_add(1000, self.refresh)

    # -- behaviour ---------------------------------------------------------

    def control(self, *args):
        cmd = ["playerctl"]
        if self.player:
            cmd += ["-p", self.player]
        cmd += list(args)
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return
        GLib.timeout_add(250, self.refresh)

    def _seek(self, fraction):
        if self.length > 0:
            self.control("position", str(int(fraction * self.length)))

    def _preview(self, fraction):
        if self.length > 0:
            self.position.set_text(fmt_time(fraction * self.length))

    def _on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        if event.keyval == Gdk.KEY_space:
            self.control("play-pause")
            return True
        if event.keyval == Gdk.KEY_Left:
            self.control("previous")
            return True
        if event.keyval == Gdk.KEY_Right:
            self.control("next")
            return True
        return False

    def _on_focus_in(self, *_):
        self._had_focus = True
        return False

    def _on_focus_out(self, *_):
        if self._had_focus:
            self.destroy()
        return False

    def refresh(self):
        nfo = music_lib.info()

        if not nfo or not nfo["title"]:
            self.player = None
            self.length = 0.0
            self.title.set_text("Nothing playing")
            self.artist.set_text("")
            self.album.set_text("")
            self.artist.hide()
            self.album.hide()
            self.state.set_text("open a player to see it here")
            self.cover.set_path(None)
            self.seek.seekable = False
            self.seek.set_fraction(0.0)
            self.seek.hide()
            self.times.hide()
            self.controls.hide()
            self.position.set_text("")
            self.total.set_text("")
            self.play.set_label("\uf04b")
            for button in (self.prev, self.play, self.next):
                button.set_sensitive(False)
            return True

        self.player = nfo["player"]
        self.length = nfo["length"]
        self.times.show()
        self.controls.show()
        self.seek.show()
        self.title.set_text(nfo["title"])
        self.artist.set_text(nfo["artist"] or "Unknown artist")
        self.artist.show()
        self.album.set_text(nfo["album"])
        self.album.set_visible(bool(nfo["album"]))
        self.state.set_text(f"{nfo['status']} · {nfo['player']}")
        self.cover.set_path(music_lib.update_cover(nfo["art"]))
        self.play.set_label("\uf04c" if nfo["status"] == "playing" else "\uf04b")

        self.seek.seekable = nfo["length"] > 0
        if nfo["length"] > 0:
            self.seek.set_fraction(nfo["position"] / nfo["length"])

        self.position.set_text(fmt_time(nfo["position"]))
        self.total.set_text(fmt_time(nfo["length"]))
        for button in (self.prev, self.play, self.next):
            button.set_sensitive(True)
        return True


def main():
    if toggle_instance():
        return

    os.makedirs(music_lib.CACHE_DIR, exist_ok=True)
    with open(PIDFILE, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    atexit.register(lambda: os.path.exists(PIDFILE) and os.remove(PIDFILE))

    provider = Gtk.CssProvider()
    provider.load_from_data(CSS.encode())
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

    settings = Gtk.Settings.get_default()
    if settings:
        settings.set_property("gtk-application-prefer-dark-theme", True)

    popup = MusicPopup()
    popup.show_all()
    popup.refresh()

    signal.signal(signal.SIGTERM, lambda *_: Gtk.main_quit())
    Gtk.main()


if __name__ == "__main__":
    main()
