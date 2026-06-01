from __future__ import annotations

import sys
import time
import traceback

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, GLib, Gio, Gtk

from lcr.aspect import aspect_ratio_from_resolution, format_resolution_details
from lcr.backend.display import (
    DisplayError,
    Modeline,
    apply_modeline,
    apply_native_mode,
    apply_resolution,
    apply_saved_resolutions,
    generate_modeline,
    list_outputs,
    remove_mode,
    reset_output_to_default,
    session_type,
    supported_mode_groups,
    xrandr_available,
)
from lcr.backend.persistence import (
    add_resolution,
    find_resolution,
    load_resolutions,
    remove_resolution,
    update_resolution,
)
from lcr.dialogs import EditResolutionDialog, SupportedModesDialog, _icon_label_button
from lcr.i18n import _, LANGUAGE_CODES, current_language, init_i18n, language_menu_label, set_language
from lcr.theme import init_theme, init_ui_styles, refresh_theme


def _resolution_details(width: int, height: int, refresh: float) -> str:
    return format_resolution_details(width, height, refresh)


def _row_label(entry: dict) -> str:
    base = format_resolution_details(
        entry["width"],
        entry["height"],
        float(entry["refresh"]),
    )
    if entry.get("activate"):
        return f"{base} · {_('On startup')}"
    return base


def _entry_is_active(entry: dict, outputs: dict) -> bool:
    display = outputs.get(entry["output"])
    if display is None or not display.current_mode:
        return False

    expected = f"{entry['width']}x{entry['height']}"
    if display.current_mode != expected:
        return False

    if display.current_refresh is None:
        return True
    return abs(display.current_refresh - float(entry["refresh"])) < 0.5


class ResolutionRow(Gtk.Box):
    def __init__(self, entry: dict, on_edit, on_remove, on_apply, *, active: bool = False) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.entry = entry
        self.on_edit = on_edit
        self.on_remove = on_remove
        self.on_apply = on_apply

        if active:
            indicator = Gtk.Label(label="●", css_classes=["accent"])
            self.append(indicator)

        label = Gtk.Label(label=_row_label(entry), xalign=0, hexpand=True)
        if active:
            label.add_css_class("title-4")
        self.append(label)

        edit_button = Gtk.Button(icon_name="document-edit-symbolic")
        edit_button.set_tooltip_text(_("Edit resolution"))
        edit_button.connect("clicked", self._on_edit)
        self.append(edit_button)

        apply_button = Gtk.Button(icon_name="media-playback-start-symbolic")
        apply_button.set_tooltip_text(_("Apply this resolution now"))
        apply_button.connect("clicked", self._on_apply)
        self.append(apply_button)

        remove_button = Gtk.Button(icon_name="user-trash-symbolic")
        remove_button.set_tooltip_text(_("Remove saved resolution"))
        remove_button.add_css_class("destructive-action")
        remove_button.connect("clicked", self._on_remove)
        self.append(remove_button)

    def _on_edit(self, _button) -> None:
        self.on_edit(self.entry)

    def _on_apply(self, _button) -> None:
        self.on_apply(self.entry)

    def _on_remove(self, _button) -> None:
        self.on_remove(self.entry)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title=_("Linux Custom Resolution"))
        self.set_default_size(520, 640)
        self._output_names: list[str] = []
        self._outputs: dict = {}
        self._language_row_codes: dict[Gtk.ListBoxRow, str] = {}
        self._active_toast: Adw.Toast | None = None
        self._last_toast_message: str | None = None
        self._last_toast_at: float = 0.0

        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        toolbar = Adw.ToolbarView()
        self.toast_overlay.set_child(toolbar)

        header = Adw.HeaderBar()
        header.set_title_widget(
            Gtk.Label(label=_("Linux Custom Resolution"), css_classes=["title"])
        )

        language_button = self._build_language_button()
        header.pack_end(language_button)

        self._refresh_in_progress = False

        refresh_button = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_button.set_tooltip_text(_("Refresh monitors"))
        refresh_button.connect("clicked", self._on_refresh_clicked)
        self._refresh_button = refresh_button
        header.pack_end(refresh_button)
        toolbar.add_top_bar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(18)
        content.set_margin_end(18)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(560)
        clamp.set_child(content)
        toolbar.set_content(clamp)

        if session_type() == "wayland":
            self._show_info(
                content,
                _(
                    "Wayland session detected. LCR uses xrandr (X11) and works best "
                    "on X11 sessions or when the compositor exposes XWayland."
                ),
            )

        if not xrandr_available():
            self._show_info(
                content,
                _("xrandr is not available. Install xorg-xrandr on your system."),
            )

        monitor_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        monitor_group = Adw.PreferencesGroup()
        self.output_row = Adw.ActionRow(title=_("Monitor"))
        self.output_combo = Gtk.DropDown()
        self.output_row.add_suffix(self.output_combo)
        self.output_combo.connect("notify::selected", lambda *_: self._on_monitor_changed())
        monitor_group.add(self.output_row)
        monitor_section.append(monitor_group)

        monitor_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        monitor_actions.set_homogeneous(True)

        supported_button = _icon_label_button(
            "video-display-symbolic",
            _("Supported resolutions"),
        )
        supported_button.set_tooltip_text(_("Supported resolutions"))
        supported_button.connect("clicked", lambda *_: self._show_supported_modes())
        monitor_actions.append(supported_button)

        restore_button = _icon_label_button(
            "edit-undo-symbolic",
            _("Restore default"),
        )
        restore_button.set_tooltip_text(_("Restore default"))
        restore_button.connect("clicked", lambda *_: self._on_restore_default())
        monitor_actions.append(restore_button)

        monitor_section.append(monitor_actions)

        content.append(monitor_section)

        form = Adw.PreferencesGroup()
        form.set_title(_("New Resolution"))

        self.width_row = Adw.SpinRow(
            title=_("Width"),
            adjustment=Gtk.Adjustment(lower=320, upper=7680, step_increment=1, value=1920),
        )
        form.add(self.width_row)

        self.height_row = Adw.SpinRow(
            title=_("Height"),
            adjustment=Gtk.Adjustment(lower=240, upper=4320, step_increment=1, value=1080),
        )
        form.add(self.height_row)

        self.refresh_row = Adw.SpinRow(
            title=_("Refresh Rate (Hz)"),
            adjustment=Gtk.Adjustment(lower=30, upper=240, step_increment=1, value=60),
        )
        form.add(self.refresh_row)

        content.append(form)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        buttons.set_halign(Gtk.Align.CENTER)

        add_button = Gtk.Button(label=_("Add to System"))
        add_button.add_css_class("suggested-action")
        add_button.connect("clicked", lambda *_: self._on_add(activate=False))
        buttons.append(add_button)

        add_apply_button = Gtk.Button(label=_("Add and Apply"))
        add_apply_button.connect("clicked", lambda *_: self._on_add(activate=True))
        buttons.append(add_apply_button)

        content.append(buttons)

        self.saved_group = Adw.PreferencesGroup()
        self.saved_group.set_title(_("Saved Resolutions"))
        self.saved_list = Gtk.ListBox()
        self.saved_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.saved_list.add_css_class("boxed-list")
        self.saved_group.add(self.saved_list)
        content.append(self.saved_group)

        GLib.idle_add(self._deferred_init)
        self.connect("notify::is-active", self._on_focus_change)

    def _deferred_init(self) -> None:
        self.refresh_outputs()
        return False

    def _on_focus_change(self, _window, _param) -> None:
        if self.is_active():
            refresh_theme()

    def _build_language_button(self) -> Gtk.Button:
        button = Gtk.Button()
        label = Gtk.Label(label="Aa")
        label.add_css_class("title-4")
        button.set_child(label)
        button.set_tooltip_text(_("Language"))
        button.add_css_class("flat")

        popover = Gtk.Popover()
        popover.set_parent(button)

        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")

        selected = current_language()
        self._language_row_codes.clear()
        for code in LANGUAGE_CODES:
            row = Gtk.ListBoxRow()
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row_box.set_margin_top(10)
            row_box.set_margin_bottom(10)
            row_box.set_margin_start(14)
            row_box.set_margin_end(14)
            name_label = Gtk.Label(label=language_menu_label(code), xalign=0, hexpand=True)
            row_box.append(name_label)
            if code == selected:
                row_box.append(Gtk.Label(label="✓"))
            row.set_child(row_box)
            self._language_row_codes[row] = code
            listbox.append(row)

        listbox.connect("row-activated", self._on_language_row_activated, popover)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_size_request(300, 420)
        scrolled.set_child(listbox)
        popover.set_child(scrolled)

        button.connect("clicked", lambda *_: popover.popup())
        return button

    def _on_language_row_activated(self, _listbox, row, popover) -> None:
        code = self._language_row_codes.get(row)
        if code is None:
            return
        popover.popdown()
        self._apply_language(code)

    def _apply_language(self, code: str) -> None:
        if code == current_language():
            return

        set_language(code)
        app = self.get_application()

        def recreate() -> None:
            for window in list(app.get_windows()):
                window.destroy()
            MainWindow(app).present()

        GLib.idle_add(recreate)

    def _show_info(self, parent: Gtk.Box, message: str) -> None:
        parent.append(Adw.Banner(title=message))

    def toast(self, message: str, *, replace: bool = True, timeout: int = 4) -> None:
        now = time.monotonic()
        if (
            replace
            and message == self._last_toast_message
            and now - self._last_toast_at < 1.5
        ):
            return

        if self._active_toast is not None:
            self._active_toast.dismiss()
            self._active_toast = None

        toast = Adw.Toast.new("")
        label = Gtk.Label(
            label=message,
            wrap=True,
            justify=Gtk.Justification.LEFT,
            xalign=0,
        )
        label.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        label.set_max_width_chars(self._toast_max_chars())
        toast.set_custom_title(label)
        toast.set_timeout(timeout)

        def on_dismissed(current: Adw.Toast) -> None:
            if self._active_toast is current:
                self._active_toast = None

        toast.connect("dismissed", on_dismissed)
        self._active_toast = toast
        self._last_toast_message = message
        self._last_toast_at = now
        self.toast_overlay.add_toast(toast)

    def _toast_max_chars(self) -> int:
        width = self.get_width()
        if width <= 0:
            return 42
        return max(26, min(52, width // 10))

    def toast_resolution(
        self,
        summary: str,
        width: int,
        height: int,
        refresh: float,
    ) -> None:
        details = _resolution_details(width, height, refresh)
        self.toast(f"{summary}\n{details}")

    def _on_refresh_clicked(self, _button) -> None:
        if self._refresh_in_progress:
            return

        self._refresh_in_progress = True
        self._refresh_started_at = time.monotonic()
        self._refresh_button.set_sensitive(False)
        self._refresh_button.add_css_class("lcr-refresh-active")

        def finish() -> bool:
            self.refresh_outputs()
            elapsed = time.monotonic() - self._refresh_started_at
            remaining_ms = max(0, int((0.55 - elapsed) * 1000))
            GLib.timeout_add(remaining_ms, self._end_refresh_animation)
            return False

        GLib.idle_add(finish)

    def _end_refresh_animation(self) -> bool:
        self._refresh_button.remove_css_class("lcr-refresh-active")
        self._refresh_button.set_sensitive(True)
        self._refresh_in_progress = False
        return False

    def refresh_outputs(self) -> None:
        try:
            outputs = list_outputs()
        except DisplayError as exc:
            self.toast(str(exc))
            return

        previous = self._selected_output()
        self._outputs = {output.name: output for output in outputs}
        self._output_names = [output.name for output in outputs]
        if not self._output_names:
            self.toast(_("No connected monitor found."))
            self._output_names = [_("No monitor")]

        self.output_combo.set_model(Gtk.StringList.new(self._output_names))
        if previous in self._output_names:
            self.output_combo.set_selected(self._output_names.index(previous))
        self._update_monitor_subtitle()
        self.refresh_saved_list()

    def _on_monitor_changed(self) -> None:
        self._update_monitor_subtitle()
        self.refresh_saved_list()

    def _update_monitor_subtitle(self) -> None:
        output = self._selected_output()
        if not output or output == _("No monitor"):
            self.output_row.set_subtitle("")
            return

        display = self._outputs.get(output)
        if not display:
            self.output_row.set_subtitle("")
            return

        label = display.current_label or ""
        if display.current_mode:
            ratio = aspect_ratio_from_resolution(display.current_mode)
            if ratio:
                label = f"{label} · {ratio}" if label else ratio
        mode_count = len(supported_mode_groups(display))
        if mode_count:
            suffix = _("({count} supported modes)").format(count=mode_count)
            label = f"{label} · {suffix}" if label else suffix
        self.output_row.set_subtitle(label)

    def _show_supported_modes(self) -> None:
        output = self._selected_output()
        if not output or output == _("No monitor"):
            self.toast(_("Select a valid monitor."))
            return

        display = self._outputs.get(output)
        if not display:
            self.toast(_("No connected monitor found."))
            return

        SupportedModesDialog(
            parent=self,
            output_name=output,
            groups=supported_mode_groups(display),
            on_pick=self._fill_resolution_fields,
            on_apply=self._apply_supported_mode,
        )

    def _fill_resolution_fields(self, width: int, height: int, refresh: float) -> None:
        self.width_row.set_value(width)
        self.height_row.set_value(height)
        self.refresh_row.set_value(refresh)
        details = _resolution_details(width, height, refresh)
        self.toast(f"{_('Fields filled.')}\n{details}")

    def _apply_supported_mode(self, width: int, height: int, refresh: float) -> None:
        output = self._selected_output()
        if not output or output == _("No monitor"):
            self.toast(_("Select a valid monitor."))
            return

        details = _resolution_details(width, height, refresh)
        existing = find_resolution(output, width, height, refresh)

        try:
            mode_name, modeline_args = apply_resolution(
                output, width, height, refresh, activate=True
            )
        except DisplayError as exc:
            self.toast(str(exc))
            return

        if not existing:
            add_resolution(
                output=output,
                width=width,
                height=height,
                refresh=refresh,
                mode_name=mode_name,
                modeline_args=modeline_args,
                activate=True,
            )
            self.toast_resolution(_("Added and applied."), width, height, refresh)
        else:
            self.toast_resolution(_("Applied."), width, height, refresh)

        self.refresh_outputs()

    def refresh_saved_list(self) -> None:
        while child := self.saved_list.get_first_child():
            self.saved_list.remove(child)

        output = self._selected_output()
        if output and output != _("No monitor"):
            self.saved_group.set_title(
                _("Saved resolutions for {output}").format(output=output)
            )
            entries = [
                entry for entry in load_resolutions() if entry.get("output") == output
            ]
        else:
            self.saved_group.set_title(_("Saved Resolutions"))
            entries = []

        if not entries:
            empty = Gtk.Label(
                label=_("No saved resolutions for this monitor."),
                margin_top=12,
                margin_bottom=12,
            )
            self.saved_list.append(empty)
            return

        for entry in entries:
            active = _entry_is_active(entry, self._outputs)
            row_box = ResolutionRow(
                entry,
                self._on_edit_saved,
                self._on_remove_saved,
                self._on_apply_saved,
                active=active,
            )
            list_row = Gtk.ListBoxRow()
            list_row.set_selectable(False)
            list_row.set_activatable(False)
            if active:
                list_row.add_css_class("selected")
            list_row.set_child(row_box)
            self.saved_list.append(list_row)

    def _on_add(self, *, activate: bool) -> None:
        output = self._selected_output()
        if not output or output == _("No monitor"):
            self.toast(_("Select a valid monitor."))
            return

        width = int(self.width_row.get_value())
        height = int(self.height_row.get_value())
        refresh = float(self.refresh_row.get_value())

        existing = find_resolution(output, width, height, refresh)
        if existing:
            self._prompt_duplicate_add(output, width, height, refresh)
            return

        self._execute_add(output, width, height, refresh, activate=activate)

    def _prompt_duplicate_add(
        self,
        output: str,
        width: int,
        height: int,
        refresh: float,
    ) -> None:
        details = _resolution_details(width, height, refresh)
        dialog = Adw.AlertDialog(
            heading=_("Resolution already saved"),
            body=_("{details} is already saved for monitor {output}.").format(
                details=details,
                output=output,
            ),
        )
        dialog.add_response("ok", _("OK"))
        dialog.set_default_response("ok")
        dialog.set_close_response("ok")
        dialog.choose(self, None, lambda *_a, **_k: None)

    def _execute_add(
        self,
        output: str,
        width: int,
        height: int,
        refresh: float,
        *,
        activate: bool,
    ) -> None:
        details = _resolution_details(width, height, refresh)

        try:
            mode_name, modeline_args = apply_resolution(
                output, width, height, refresh, activate=activate
            )
            add_resolution(
                output=output,
                width=width,
                height=height,
                refresh=refresh,
                mode_name=mode_name,
                modeline_args=modeline_args,
                activate=activate,
            )
        except DisplayError as exc:
            self.toast(str(exc))
            return

        if activate:
            self.toast_resolution(_("Added and applied."), width, height, refresh)
            self.refresh_outputs()
        else:
            self.toast_resolution(_("Added to the system."), width, height, refresh)
            self.refresh_saved_list()

    def _on_restore_default(self) -> None:
        output = self._selected_output()
        if not output or output == _("No monitor"):
            self.toast(_("Select a valid monitor."))
            return

        try:
            reset_output_to_default(output)
        except DisplayError as exc:
            self.toast(str(exc))
            return

        self.toast(
            _("Monitor {output} restored to default resolution.").format(output=output)
        )
        self.refresh_outputs()

    def _on_edit_saved(self, entry: dict) -> None:
        outputs = [name for name in self._output_names if name != _("No monitor")]
        if not outputs:
            self.toast(_("No connected monitor found."))
            return

        EditResolutionDialog(
            parent=self,
            entry=entry,
            outputs=outputs,
            on_save=self._on_save_edited,
        )

    def _on_save_edited(self, entry: dict, data: dict) -> None:
        width = data["width"]
        height = data["height"]
        refresh = data["refresh"]
        output = data["output"]
        details = _resolution_details(width, height, refresh)

        duplicate = find_resolution(
            output,
            width,
            height,
            refresh,
            exclude_id=entry["id"],
        )
        if duplicate:
            self.toast(_("Another saved resolution already uses these settings."))
            return

        try:
            mode_name, modeline_args = apply_resolution(
                output, width, height, refresh, activate=data["apply_now"]
            )
        except DisplayError as exc:
            self.toast(_("Failed to update resolution: {error}").format(error=exc))
            return

        previous, updated = update_resolution(
            entry["id"],
            output=output,
            width=width,
            height=height,
            refresh=refresh,
            mode_name=mode_name,
            modeline_args=modeline_args,
            activate=data["activate"],
        )
        if previous is None or updated is None:
            self.toast(_("Resolution not found."))
            return

        try:
            if previous.get("modeline_args"):
                remove_mode(previous["output"], previous["mode_name"])
        except DisplayError:
            pass

        if data["apply_now"]:
            self.toast_resolution(_("Updated and applied."), width, height, refresh)
            self.refresh_outputs()
        else:
            self.toast_resolution(_("Updated."), width, height, refresh)
            self.refresh_saved_list()

    def _on_apply_saved(self, entry: dict) -> None:
        try:
            modeline_args = entry.get("modeline_args") or []
            if modeline_args:
                modeline = Modeline(
                    name=entry["mode_name"],
                    args=tuple(modeline_args),
                )
                apply_modeline(entry["output"], modeline, activate=True)
            else:
                apply_resolution(
                    entry["output"],
                    entry["width"],
                    entry["height"],
                    float(entry["refresh"]),
                    activate=True,
                )
        except DisplayError as exc:
            self.toast(str(exc))
            return

        self.toast_resolution(
            _("Applied."),
            entry["width"],
            entry["height"],
            float(entry["refresh"]),
        )
        self.refresh_outputs()

    def _on_remove_saved(self, entry: dict) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Remove saved resolution?"),
            body=_("Remove {details} from your saved resolutions?").format(
                details=entry["label"]
            ),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("remove", _("Remove"))
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_chosen(_dialog, result) -> None:
            try:
                response = dialog.choose_finish(result)
            except GLib.Error:
                return
            if response == "remove":
                self._execute_remove_saved(entry)

        dialog.choose(self, None, on_chosen)

    def _execute_remove_saved(self, entry: dict) -> None:
        removed = remove_resolution(entry["id"])
        if not removed:
            self.toast(_("Resolution not found."))
            return

        try:
            remove_mode(removed["output"], removed["mode_name"])
        except DisplayError as exc:
            self.toast(
                _("Removed from profile, but xrandr failed: {error}").format(error=exc)
            )
            self.refresh_outputs()
            return

        self.toast(f"{_('Removed.')}\n{removed['label']}")
        self.refresh_outputs()

    def _selected_output(self) -> str | None:
        model = self.output_combo.get_model()
        if model is None:
            return None
        selected = self.output_combo.get_selected()
        if selected == Gtk.INVALID_LIST_POSITION:
            return None
        return model.get_string(selected)


class LcrApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id="com.linuxcustomresolution.LCR")
        # Avoid D-Bus single-instance issues on some desktops (e.g. Cinnamon/Mint).
        self.set_flags(Gio.ApplicationFlags.NON_UNIQUE)

    def do_activate(self) -> None:
        try:
            window = self.get_active_window()
            if window is None:
                window = MainWindow(self)
            window.present()
        except Exception:
            traceback.print_exc()
            raise


def run_gui() -> int:
    init_i18n()
    app = LcrApplication()

    def on_startup(_app: Adw.Application) -> None:
        init_ui_styles()
        init_theme()

    app.connect("startup", on_startup)
    return app.run(sys.argv)


def run_apply() -> int:
    init_i18n()
    if not xrandr_available():
        print(_("xrandr is not available."), file=sys.stderr)
        return 1

    entries = load_resolutions()
    if not entries:
        return 0

    for message in apply_saved_resolutions(entries):
        print(message)
    return 0


def main() -> None:
    if "--apply" in sys.argv:
        raise SystemExit(run_apply())
    raise SystemExit(run_gui())
