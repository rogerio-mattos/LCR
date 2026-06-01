from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gtk

from lcr.aspect import aspect_ratio_from_resolution
from lcr.backend.display import preferred_apply_rate
from lcr.i18n import _


def _icon_label_button(icon_name: str, label: str) -> Gtk.Button:
    button = Gtk.Button()
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    box.set_halign(Gtk.Align.CENTER)
    image = Gtk.Image.new_from_icon_name(icon_name)
    image.set_icon_size(Gtk.IconSize.NORMAL)
    box.append(image)
    box.append(Gtk.Label(label=label))
    button.set_child(box)
    button.set_hexpand(True)
    return button


def _circle_btn(icon_name: str, tooltip: str) -> Gtk.Button:
    btn = Gtk.Button()
    btn.add_css_class("circular")
    btn.add_css_class("flat")
    img = Gtk.Image.new_from_icon_name(icon_name)
    img.set_icon_size(Gtk.IconSize.NORMAL)
    btn.set_child(img)
    btn.set_tooltip_text(tooltip)
    return btn


def _resolution_label(resolution: str) -> str:
    if "x" not in resolution:
        return resolution
    width, height = resolution.split("x", 1)
    ratio = aspect_ratio_from_resolution(resolution)
    label = f"{width}\u00d7{height}"
    if ratio:
        label += f"  ({ratio})"
    return label


class SupportedModesDialog(Adw.Dialog):
    def __init__(
        self,
        *,
        parent: Gtk.Window,
        output_name: str,
        groups: list[tuple[str, tuple[float, ...], float | None]],
        on_pick=None,
        on_apply=None,
    ) -> None:
        super().__init__()
        self._on_pick = on_pick
        self._on_apply = on_apply

        self.set_title(_("Supported resolutions"))
        self.set_content_width(540)
        self.set_content_height(580)

        toolbar = Adw.ToolbarView()
        self.set_child(toolbar)

        header = Adw.HeaderBar()
        header.set_title_widget(
            Gtk.Label(label=_("Supported resolutions"), css_classes=["title"])
        )
        toolbar.add_top_bar(header)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_margin_top(4)
        outer.set_margin_bottom(16)
        outer.set_margin_start(16)
        outer.set_margin_end(16)
        toolbar.set_content(outer)

        info = Gtk.Label(
            label=_(
                "Modes reported by xrandr for {output}. "
                "TVs and some monitors only accept these — custom modes may fail."
            ).format(output=output_name),
            wrap=True,
            xalign=0,
        )
        info.add_css_class("dim-label")
        outer.append(info)

        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")

        if not groups:
            empty_row = Gtk.ListBoxRow()
            empty_row.set_activatable(False)
            empty_row.set_selectable(False)
            empty_row.set_child(
                Gtk.Label(
                    label=_("No modes reported for this display."),
                    margin_top=16,
                    margin_bottom=16,
                    margin_start=12,
                    margin_end=12,
                )
            )
            listbox.append(empty_row)
        else:
            for resolution, rates, active in groups:
                listbox.append(self._build_mode_row(resolution, rates, active))

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_child(listbox)
        outer.append(scrolled)

        tip = Gtk.Label(
            label=_(
                "Tip: use ▶ to apply a mode now. Use the copy button to fill the form."
            ),
            wrap=True,
            xalign=0,
        )
        tip.add_css_class("dim-label")
        tip.add_css_class("caption")
        outer.append(tip)

        self.present(parent)

    def _build_mode_row(
        self,
        resolution: str,
        rates: tuple[float, ...],
        active: float | None,
    ) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        row.set_selectable(False)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.add_css_class("lcr-mode-row")
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(10)
        box.set_margin_end(10)
        row.set_child(box)

        monitor = Gtk.Image.new_from_icon_name("video-display-symbolic")
        monitor.set_icon_size(Gtk.IconSize.LARGE)
        monitor.add_css_class("dim-label")
        monitor.set_valign(Gtk.Align.CENTER)
        box.append(monitor)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        text_box.set_hexpand(True)
        text_box.set_valign(Gtk.Align.CENTER)

        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title_lbl = Gtk.Label(label=_resolution_label(resolution), xalign=0)
        title_lbl.add_css_class("lcr-mode-title")
        title_row.append(title_lbl)

        if active is not None:
            badge = Gtk.Label(label=_("Current"))
            badge.add_css_class("lcr-badge-current")
            title_row.append(badge)

        text_box.append(title_row)

        rates_str = ", ".join(f"{rate:g} Hz" for rate in rates)
        rates_lbl = Gtk.Label(label=rates_str, xalign=0)
        rates_lbl.add_css_class("dim-label")
        rates_lbl.add_css_class("caption")
        text_box.append(rates_lbl)

        box.append(text_box)

        if "x" not in resolution:
            return row

        use_rate = preferred_apply_rate(rates, active)
        width_val, height_val = resolution.split("x", 1)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        actions.set_valign(Gtk.Align.CENTER)

        if self._on_apply is not None:
            play_btn = _circle_btn("media-playback-start-symbolic", _("Apply now"))
            play_btn.connect(
                "clicked",
                lambda *_b, w=width_val, h=height_val, r=use_rate: self._apply(
                    int(w), int(h), float(r)
                ),
            )
            actions.append(play_btn)

        if self._on_pick is not None:
            copy_btn = _circle_btn("edit-copy-symbolic", _("Fill form fields"))
            copy_btn.connect(
                "clicked",
                lambda *_b, w=width_val, h=height_val, r=use_rate: self._pick(
                    int(w), int(h), float(r)
                ),
            )
            actions.append(copy_btn)

        box.append(actions)
        return row

    def _pick(self, width: int, height: int, refresh: float) -> None:
        if self._on_pick is not None:
            self._on_pick(width, height, refresh)
        self.close()

    def _apply(self, width: int, height: int, refresh: float) -> None:
        if self._on_apply is not None:
            self._on_apply(width, height, refresh)
        self.close()


class EditResolutionDialog(Adw.Dialog):
    def __init__(
        self,
        *,
        parent: Gtk.Window,
        entry: dict,
        outputs: list[str],
        on_save,
    ) -> None:
        super().__init__()
        self._entry = entry
        self._on_save = on_save

        self.set_title(_("Edit Resolution"))
        self.set_content_width(420)
        self.set_content_height(480)

        toolbar = Adw.ToolbarView()
        self.set_child(toolbar)

        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label=_("Edit Resolution"), css_classes=["title"]))
        toolbar.add_top_bar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(18)
        content.set_margin_end(18)
        toolbar.set_content(content)

        form = Adw.PreferencesGroup()

        self.output_row = Adw.ActionRow(title=_("Monitor"))
        self.output_combo = Gtk.DropDown(model=Gtk.StringList.new(outputs))
        output_index = outputs.index(entry["output"]) if entry["output"] in outputs else 0
        self.output_combo.set_selected(output_index)
        self.output_row.add_suffix(self.output_combo)
        form.add(self.output_row)

        self.width_row = Adw.SpinRow(
            title=_("Width"),
            adjustment=Gtk.Adjustment(
                lower=320,
                upper=7680,
                step_increment=1,
                value=entry["width"],
            ),
        )
        form.add(self.width_row)

        self.height_row = Adw.SpinRow(
            title=_("Height"),
            adjustment=Gtk.Adjustment(
                lower=240,
                upper=4320,
                step_increment=1,
                value=entry["height"],
            ),
        )
        form.add(self.height_row)

        self.refresh_row = Adw.SpinRow(
            title=_("Refresh Rate (Hz)"),
            adjustment=Gtk.Adjustment(
                lower=30,
                upper=240,
                step_increment=1,
                value=entry["refresh"],
            ),
        )
        form.add(self.refresh_row)

        self.login_row = Adw.SwitchRow(
            title=_("Apply when the computer starts"),
            subtitle=_(
                "If enabled, this resolution is selected automatically after you "
                "log in or restart. If disabled, it remains saved and you choose "
                "when to use it."
            ),
        )
        self.login_row.set_active(entry.get("activate", False))
        form.add(self.login_row)

        content.append(form)

        buttons = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        save_button = Gtk.Button(label=_("Save Changes"))
        save_button.add_css_class("suggested-action")
        save_button.connect("clicked", lambda *_: self._emit_save(apply_now=False))
        buttons.append(save_button)

        save_apply_button = Gtk.Button(label=_("Save and Apply"))
        save_apply_button.connect("clicked", lambda *_: self._emit_save(apply_now=True))
        buttons.append(save_apply_button)

        cancel_button = Gtk.Button(label=_("Cancel"))
        cancel_button.connect("clicked", lambda *_: self.close())
        buttons.append(cancel_button)

        content.append(buttons)
        self.present(parent)

    def _emit_save(self, *, apply_now: bool) -> None:
        model = self.output_combo.get_model()
        selected = self.output_combo.get_selected()
        if model is None or selected == Gtk.INVALID_LIST_POSITION:
            return

        self._on_save(
            self._entry,
            {
                "output": model.get_string(selected),
                "width": int(self.width_row.get_value()),
                "height": int(self.height_row.get_value()),
                "refresh": float(self.refresh_row.get_value()),
                "activate": self.login_row.get_active(),
                "apply_now": apply_now,
            },
        )
        self.close()
