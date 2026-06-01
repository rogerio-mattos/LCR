from __future__ import annotations

import os
import re
import subprocess

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gio, GLib, Gdk, Gtk


_PORTAL_BUS = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"
_PORTAL_IFACE = "org.freedesktop.portal.Settings"
_APPEARANCE = "org.freedesktop.appearance"

_UI_CSS = """
@keyframes lcr-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

button.lcr-refresh-active image {
  animation: lcr-spin 0.65s linear infinite;
}

.lcr-mode-row {
  padding: 4px 2px;
}

.lcr-mode-title {
  font-weight: 600;
}

.lcr-badge-current {
  border-radius: 999px;
  padding: 2px 10px;
  background-color: @accent_bg_color;
  color: @accent_fg_color;
  font-size: 0.78em;
  font-weight: 600;
}

toast {
  margin: 10px 14px;
}

toast label {
  white-space: normal;
}
"""


def init_ui_styles() -> None:
    """Load application-wide CSS (refresh animation, etc.)."""
    display = Gdk.Display.get_default()
    if display is None:
        return

    provider = Gtk.CssProvider()
    provider.load_from_string(_UI_CSS)
    Gtk.StyleContext.add_provider_for_display(
        display,
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


def init_theme() -> None:
    """Apply the system colour scheme on startup."""
    try:
        _apply_from_system(Adw.StyleManager.get_default())
    except Exception:
        pass


def refresh_theme() -> None:
    """Re-read and apply the system colour scheme (call on window focus)."""
    try:
        _apply_from_system(Adw.StyleManager.get_default())
    except Exception:
        pass


# ── apply ──────────────────────────────────────────────────────────────────

def _apply_from_system(style: Adw.StyleManager) -> None:
    # 1. Cinnamon GTK theme name (most reliable on Mint / Cinnamon)
    gtk_theme = _read_setting("org.cinnamon.desktop.interface", "gtk-theme")
    if gtk_theme:
        scheme = (
            Adw.ColorScheme.FORCE_DARK
            if _name_implies_dark(gtk_theme)
            else Adw.ColorScheme.FORCE_LIGHT
        )
        style.set_color_scheme(scheme)
        return

    # 2. Standard color-scheme key (GNOME, XFCE)
    for schema, key in (
        ("org.gnome.desktop.interface", "color-scheme"),
        ("org.xfce.desktop.appearance", "color-scheme"),
    ):
        value = _read_setting(schema, key)
        if value == "prefer-dark":
            style.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            return
        if value in ("prefer-light", "default"):
            style.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
            return

    # 3. Portal fallback (KDE, etc.)
    scheme = _portal_color_scheme()
    if scheme == 1:
        style.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
    else:
        style.set_color_scheme(Adw.ColorScheme.DEFAULT)


# ── helpers ─────────────────────────────────────────────────────────────────

def _read_setting(schema: str, key: str) -> str | None:
    if _in_flatpak():
        return _read_host_gsettings(schema, key)
    return _read_local_gsettings(schema, key)


def _read_host_gsettings(schema: str, key: str) -> str | None:
    try:
        r = subprocess.run(
            ["flatpak-spawn", "--host", "gsettings", "get", schema, key],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return _parse(r.stdout) if r.returncode == 0 else None


def _read_local_gsettings(schema: str, key: str) -> str | None:
    try:
        settings = Gio.Settings.new(schema)
    except GLib.Error:
        return None
    if key not in settings.list_keys():
        return None
    return _parse(str(settings.get_value(key)))


def _parse(raw: str) -> str | None:
    text = raw.strip()
    if not text or text == "@as []":
        return None
    if text in {"true", "false"}:
        return text
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1]
    return text


def _name_implies_dark(name: str) -> bool:
    return bool(re.search(r"dark", name, re.IGNORECASE))


def _portal_color_scheme() -> int | None:
    proxy = _portal_proxy()
    if proxy is None:
        return None
    v = _portal_read(proxy, "color-scheme")
    try:
        return int(v.unpack()) if v else None
    except (TypeError, ValueError):
        return None


def _in_flatpak() -> bool:
    return os.path.exists("/.flatpak-info")


def _portal_proxy() -> Gio.DBusProxy | None:
    try:
        return Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION,
            Gio.DBusProxyFlags.NONE,
            None,
            _PORTAL_BUS,
            _PORTAL_PATH,
            _PORTAL_IFACE,
            None,
        )
    except GLib.Error:
        return None


def _portal_read(proxy: Gio.DBusProxy, key: str) -> GLib.Variant | None:
    try:
        r = proxy.call_sync(
            "Read",
            GLib.Variant("(ss)", (_APPEARANCE, key)),
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
        return r.get_child_value(0) if r else None
    except GLib.Error:
        return None
