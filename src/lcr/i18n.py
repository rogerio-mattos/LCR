from __future__ import annotations

import gettext
import locale
import os
from pathlib import Path

from lcr.backend.persistence import load_settings, save_language as persist_language


DOMAIN = "lcr"

LANGUAGE_CODES: tuple[str, ...] = (
    "system",
    "en",
    "pt_BR",
    "es",
    "ru",
    "zh_CN",
    "zh_TW",
    "fr",
    "de",
    "ja",
    "ar",
    "hi",
    "it",
    "ko",
)

_translation: gettext.GNUTranslations | gettext.NullTranslations = gettext.NullTranslations()


def _locale_dir() -> Path:
    candidates = (
        Path("/app/share/locale"),
        Path(__file__).resolve().parents[2] / "share" / "locale",
    )
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]


def current_language() -> str:
    return load_settings().get("language", "system")


def _load_translation(code: str) -> gettext.GNUTranslations | gettext.NullTranslations:
    locale_dir = str(_locale_dir())

    if code == "system":
        for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
            if os.environ.get(name):
                try:
                    locale.setlocale(locale.LC_ALL, "")
                except locale.Error:
                    pass
                break
        try:
            return gettext.translation(DOMAIN, locale_dir, fallback=True)
        except FileNotFoundError:
            return gettext.NullTranslations()

    if code == "en":
        return gettext.NullTranslations()

    aliases = {"pt": "pt_BR", "zh": "zh_CN"}
    lookup = aliases.get(code, code)

    try:
        return gettext.translation(
            DOMAIN,
            locale_dir,
            languages=[lookup],
            fallback=True,
        )
    except FileNotFoundError:
        return gettext.NullTranslations()


def init_i18n() -> None:
    global _translation
    _translation = _load_translation(current_language())


def set_language(code: str) -> None:
    persist_language(code)
    init_i18n()


def language_menu_label(code: str) -> str:
    labels = {
        "system": _("System Default"),
        "en": _("English"),
        "pt_BR": _("Portuguese (Brazil)"),
        "es": _("Spanish"),
        "ru": _("Russian"),
        "zh_CN": _("Chinese (Simplified)"),
        "zh_TW": _("Chinese (Traditional)"),
        "fr": _("French"),
        "de": _("German"),
        "ja": _("Japanese"),
        "ar": _("Arabic"),
        "hi": _("Hindi"),
        "it": _("Italian"),
        "ko": _("Korean"),
    }
    return labels.get(code, code)


def _(message: str) -> str:
    return _translation.gettext(message)
