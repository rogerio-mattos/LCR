from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from lcr.aspect import format_resolution_details


APP_ID = "com.linuxcustomresolution.LCR"
CONFIG_DIR = Path.home() / ".config" / "linux-custom-resolution"
CONFIG_FILE = CONFIG_DIR / "resolutions.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
AUTOSTART_DIR = Path.home() / ".config" / "autostart"
AUTOSTART_FILE = AUTOSTART_DIR / f"{APP_ID}.desktop"


def _ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_resolutions() -> list[dict]:
    if not CONFIG_FILE.exists():
        return []

    with CONFIG_FILE.open(encoding="utf-8") as handle:
        data = json.load(handle)

    return data.get("resolutions", [])


def save_resolutions(resolutions: list[dict]) -> None:
    _ensure_config_dir()
    payload = {"resolutions": resolutions}
    with CONFIG_FILE.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def load_settings() -> dict:
    if not SETTINGS_FILE.exists():
        return {}

    with SETTINGS_FILE.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_settings(settings: dict) -> None:
    _ensure_config_dir()
    with SETTINGS_FILE.open("w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2, ensure_ascii=False)


def save_language(language: str) -> None:
    settings = load_settings()
    settings["language"] = language
    save_settings(settings)


def _make_entry(
    *,
    entry_id: str,
    output: str,
    width: int,
    height: int,
    refresh: float,
    mode_name: str,
    modeline_args: list[str],
    activate: bool,
) -> dict:
    return {
        "id": entry_id,
        "output": output,
        "width": width,
        "height": height,
        "refresh": refresh,
        "mode_name": mode_name,
        "modeline_args": modeline_args,
        "activate": activate,
        "label": format_resolution_details(width, height, refresh),
    }


def add_resolution(
    *,
    output: str,
    width: int,
    height: int,
    refresh: float,
    mode_name: str,
    modeline_args: list[str],
    activate: bool = False,
) -> dict:
    entry = _make_entry(
        entry_id=str(uuid.uuid4()),
        output=output,
        width=width,
        height=height,
        refresh=refresh,
        mode_name=mode_name,
        modeline_args=modeline_args,
        activate=activate,
    )

    resolutions = load_resolutions()
    resolutions = [item for item in resolutions if not _same_entry(item, entry)]
    resolutions.append(entry)
    save_resolutions(resolutions)
    install_autostart()
    return entry


def update_resolution(
    entry_id: str,
    *,
    output: str,
    width: int,
    height: int,
    refresh: float,
    mode_name: str,
    modeline_args: list[str],
    activate: bool,
) -> tuple[dict | None, dict | None]:
    resolutions = load_resolutions()
    previous = None
    kept: list[dict] = []

    for item in resolutions:
        if item["id"] == entry_id:
            previous = item
        else:
            kept.append(item)

    if previous is None:
        return None, None

    updated = _make_entry(
        entry_id=entry_id,
        output=output,
        width=width,
        height=height,
        refresh=refresh,
        mode_name=mode_name,
        modeline_args=modeline_args,
        activate=activate,
    )

    kept = [
        item
        for item in kept
        if not (
            item.get("output") == updated["output"]
            and item.get("mode_name") == updated["mode_name"]
        )
    ]
    kept.append(updated)
    save_resolutions(kept)
    install_autostart()
    return previous, updated


def remove_resolution(entry_id: str) -> dict | None:
    resolutions = load_resolutions()
    removed = None
    kept: list[dict] = []

    for item in resolutions:
        if item["id"] == entry_id:
            removed = item
        else:
            kept.append(item)

    save_resolutions(kept)
    if kept:
        install_autostart()
    else:
        remove_autostart()

    return removed


def _same_entry(left: dict, right: dict) -> bool:
    return (
        left.get("output") == right.get("output")
        and left.get("mode_name") == right.get("mode_name")
    )


def find_resolution(
    output: str,
    width: int,
    height: int,
    refresh: float,
    *,
    exclude_id: str | None = None,
) -> dict | None:
    for item in load_resolutions():
        if exclude_id and item.get("id") == exclude_id:
            continue
        if item.get("output") != output:
            continue
        if item.get("width") != width or item.get("height") != height:
            continue
        if abs(float(item.get("refresh", 0)) - refresh) >= 0.5:
            continue
        return item
    return None


def install_autostart() -> None:
    AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)

    if _in_flatpak():
        exec_line = f"flatpak run --command=lcr {APP_ID} --apply"
    else:
        exec_line = "lcr --apply"

    desktop = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name=Linux Custom Resolution\n"
        f"Exec={exec_line}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        "X-GNOME-Autostart-Delay=2\n"
        "Comment=Restaura resoluções personalizadas salvas pelo LCR\n"
    )

    AUTOSTART_FILE.write_text(desktop, encoding="utf-8")


def remove_autostart() -> None:
    if AUTOSTART_FILE.exists():
        AUTOSTART_FILE.unlink()


def _in_flatpak() -> bool:
    return os.path.exists("/.flatpak-info")
