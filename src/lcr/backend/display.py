from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ModeOption:
    name: str
    refresh: float
    active: bool = False


@dataclass(frozen=True)
class DisplayOutput:
    name: str
    connected: bool
    current_mode: str | None
    current_refresh: float | None
    active_mode_name: str | None
    modes: tuple[str, ...]
    mode_options: tuple[ModeOption, ...] = ()
    primary: bool = False
    pos_x: int | None = None
    pos_y: int | None = None
    rotation: str | None = None
    has_edid: bool = False

    @property
    def current_label(self) -> str | None:
        if not self.current_mode:
            return None
        if self.current_refresh is not None:
            return f"{self.current_mode} @ {self.current_refresh:g} Hz"
        return self.current_mode


@dataclass(frozen=True)
class Modeline:
    name: str
    args: tuple[str, ...]


class DisplayError(Exception):
    pass


def _in_flatpak() -> bool:
    return os.path.exists("/.flatpak-info")


def _host_command(base: list[str]) -> list[str]:
    if _in_flatpak():
        return ["flatpak-spawn", "--host", *base]
    return base


def _run(base: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    if not shutil.which(base[0]) and not _in_flatpak():
        raise DisplayError(f"Comando não encontrado: {base[0]}")

    try:
        result = subprocess.run(
            _host_command(base),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DisplayError(f"Falha ao executar: {' '.join(base)}") from exc

    if check and result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        raise DisplayError(_humanize_xrandr_error(stderr or f"Comando falhou: {' '.join(base)}"))

    return result


def session_type() -> str:
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session:
        return session
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def xrandr_available() -> bool:
    try:
        _run(["xrandr", "--version"], check=False)
        return True
    except DisplayError:
        return False


def _humanize_xrandr_error(message: str) -> str:
    lowered = message.lower()
    if "badmatch" in lowered or "bad match" in lowered:
        return (
            "O monitor recusou esta resolução ou taxa de atualização (BadMatch). "
            "Tente outra taxa na lista — em geral 60 Hz funciona melhor em VMs e TVs."
        )
    if "configure crtc" in lowered:
        return (
            "Falha ao configurar o monitor (Configure crtc). Com mais de um monitor "
            "conectado, o LCR precisa aplicar o layout completo — tente de novo. "
            "Se persistir, desconecte/reconecte o cabo de vídeo."
        )
    if "cvt" in lowered and ("inexistente" in lowered or "no such file" in lowered):
        return (
            "O comando cvt não está instalado no sistema. "
            "Instale xorg-xserver-utils (Debian/Ubuntu) ou equivalente."
        )
    return message


def _parse_connector_layout(
    rest: str,
) -> tuple[bool, str | None, float | None, int | None, int | None, str | None]:
    primary = " primary " in f" {rest} " or rest.startswith("primary ")
    if rest.startswith("primary "):
        rest = rest[len("primary ") :]

    mode_match = re.search(r"(\d+x\d+)\+(\d+)\+(\d+)", rest)
    current_mode = mode_match.group(1) if mode_match else None
    pos_x = int(mode_match.group(2)) if mode_match else None
    pos_y = int(mode_match.group(3)) if mode_match else None

    rotation_match = re.search(r"\(([^)]+)\)", rest)
    rotation = rotation_match.group(1).split()[0] if rotation_match else None

    return primary, current_mode, None, pos_x, pos_y, rotation


def _with_layout(output: DisplayOutput, **kwargs) -> DisplayOutput:
    return replace(output, **kwargs)


def _parse_xrandr_query(stdout: str) -> list[DisplayOutput]:
    outputs: list[DisplayOutput] = []
    current: DisplayOutput | None = None

    for line in stdout.splitlines():
        if not line:
            continue

        connected_match = re.match(
            r"^(\S+)\s+(connected|disconnected)(?:\s+(.*))?$",
            line,
        )
        if connected_match:
            if current:
                outputs.append(current)

            name, state, rest = connected_match.groups()
            rest = rest or ""
            primary, current_mode, _, pos_x, pos_y, rotation = _parse_connector_layout(rest)
            has_edid = bool(re.search(r"\d+mm x \d+mm", rest))
            current = DisplayOutput(
                name=name,
                connected=state == "connected",
                current_mode=current_mode,
                current_refresh=None,
                active_mode_name=None,
                modes=(),
                primary=primary,
                pos_x=pos_x,
                pos_y=pos_y,
                rotation=rotation,
                has_edid=has_edid,
            )
            continue

        mode_line = re.match(r"^\s+(\S+)\s+(.+)$", line)
        if mode_line and current:
            mode_name = mode_line.group(1)
            rest = mode_line.group(2)

            if mode_name in ("h:", "v:") or "start" in rest or "skew" in rest:
                continue
            if not re.match(r"^\d+x\d+", mode_name):
                continue
            if "MHz" in rest:
                if mode_name not in current.modes:
                    current = _with_layout(current, modes=current.modes + (mode_name,))
                continue

            new_options = list(current.mode_options)
            line_active: ModeOption | None = None

            for entry in re.finditer(r"([\d.]+)", rest):
                refresh = float(entry.group(1))
                if refresh > 500:
                    continue
                pos = entry.end(1)
                active = pos < len(rest) and rest[pos : pos + 1] == "*"
                option = ModeOption(mode_name, refresh, active)
                new_options.append(option)
                if active:
                    line_active = option

            if not re.findall(r"([\d.]+)", rest):
                continue

            modes = current.modes if mode_name in current.modes else current.modes + (mode_name,)
            updates: dict = {"modes": modes, "mode_options": tuple(new_options)}
            if line_active:
                resolution = (
                    mode_name.split("_", 1)[0]
                    if "x" in mode_name.split("_")[0]
                    else mode_name
                )
                if "x" in resolution:
                    updates["current_mode"] = resolution
                updates["current_refresh"] = line_active.refresh
                updates["active_mode_name"] = mode_name
            current = _with_layout(current, **updates)
            continue

        mode_match = re.match(r"^\s+(\S+)", line)
        if mode_match and current:
            mode_name = mode_match.group(1)
            if re.match(r"^\d+x\d+", mode_name) and mode_name not in current.modes:
                current = _with_layout(current, modes=current.modes + (mode_name,))

    if current:
        outputs.append(current)

    return outputs


def _list_active_monitor_names() -> frozenset[str]:
    result = _run(["xrandr", "--listactivemonitors"], check=False)
    names: set[str] = set()
    for line in result.stdout.splitlines():
        match = re.match(r"^\s*\d+:\s+.+\s+(\S+)\s*$", line)
        if match:
            names.add(match.group(1))
    return frozenset(names)


def list_outputs() -> list[DisplayOutput]:
    result = _run(["xrandr", "--query"])
    outputs = _parse_xrandr_query(result.stdout)
    active_names = _list_active_monitor_names()
    return [
        output
        for output in outputs
        if output.connected
        and (
            output.name in active_names
            or output.current_mode is not None
            or (output.has_edid and output.mode_options)
        )
    ]


def supported_mode_groups(
    output: DisplayOutput,
) -> list[tuple[str, tuple[float, ...], float | None]]:
    """Group supported modes as (resolution, refresh_rates, active_refresh)."""
    if not output.mode_options:
        return []

    grouped: dict[str, dict] = {}
    for opt in output.mode_options:
        res = opt.name.split("_", 1)[0] if "x" in opt.name.split("_")[0] else opt.name
        if "x" not in res:
            continue
        entry = grouped.setdefault(res, {"rates": set(), "active": None})
        entry["rates"].add(opt.refresh)
        if opt.active:
            entry["active"] = opt.refresh

    def sort_key(res: str) -> tuple[int, int]:
        if "x" not in res:
            return (0, 0)
        width, height = res.split("x", 1)
        return (-int(width), -int(height))

    result: list[tuple[str, tuple[float, ...], float | None]] = []
    for res in sorted(grouped.keys(), key=sort_key):
        rates = tuple(sorted(grouped[res]["rates"], reverse=True))
        result.append((res, rates, grouped[res]["active"]))
    return result


def find_native_mode(
    output: DisplayOutput,
    width: int,
    height: int,
    refresh: float,
) -> tuple[str, float] | None:
    """Return native mode name and refresh if xrandr already lists it."""
    target = f"{width}x{height}"
    best: tuple[str, float, float] | None = None

    for opt in output.mode_options:
        base = opt.name.split("_", 1)[0] if "x" in opt.name.split("_")[0] else opt.name
        if base != target:
            continue
        diff = abs(opt.refresh - refresh)
        if best is None or diff < best[2]:
            best = (opt.name, opt.refresh, diff)

    if best is None:
        return None
    return best[0], best[1]


def preferred_apply_rate(rates: tuple[float, ...], active: float | None) -> float:
    """Pick a refresh rate likely to work (VM/TV safe defaults)."""
    if active is not None:
        return active
    for preferred in (60.0, 59.94, 75.0, 50.0, 30.0):
        for rate in rates:
            if abs(rate - preferred) < 0.5:
                return rate
    return min(rates)


def _native_rate_candidates(
    output: DisplayOutput,
    width: int,
    height: int,
    preferred_refresh: float,
) -> list[tuple[str, float]]:
    target = f"{width}x{height}"
    options: list[tuple[str, float]] = []

    for opt in output.mode_options:
        base = opt.name.split("_", 1)[0] if "x" in opt.name.split("_")[0] else opt.name
        if base != target:
            continue
        options.append((opt.name, opt.refresh))

    if not options:
        return []

    def sort_key(item: tuple[str, float]) -> tuple[float, float]:
        _name, rate = item
        return (abs(rate - preferred_refresh), abs(rate - 60.0))

    return sorted(options, key=sort_key)


def _apply_single_output(
    output_name: str,
    mode_name: str,
    *,
    refresh: float | None = None,
) -> None:
    cmd = ["xrandr", "--output", output_name, "--mode", mode_name]
    if refresh is not None:
        cmd.extend(["--rate", f"{refresh:g}"])
    _run(cmd)


def _apply_single_output_fallback(
    output_name: str,
    mode_name: str,
    *,
    refresh: float | None,
) -> None:
    try:
        _apply_single_output(output_name, mode_name, refresh=refresh)
    except DisplayError:
        if refresh is not None:
            _apply_single_output(output_name, mode_name, refresh=None)
            return
        raise


def _resolved_mode(out: DisplayOutput) -> str | None:
    if out.active_mode_name:
        return out.active_mode_name
    if out.current_mode and out.current_mode in out.modes:
        return out.current_mode
    if out.current_mode:
        for mode in out.modes:
            if mode.split("_", 1)[0] == out.current_mode:
                return mode
    return out.modes[0] if out.modes else None


def _xrandr_apply_layout(
    outputs: list[DisplayOutput],
    *,
    target: str | None = None,
    mode_name: str | None = None,
    refresh: float | None = None,
    use_auto: bool = False,
) -> None:
    """Apply all outputs in one xrandr call (required for multi-monitor)."""
    if not outputs:
        raise DisplayError("Nenhum monitor conectado.")

    cmd = ["xrandr"]
    for out in outputs:
        cmd.extend(["--output", out.name])

        if target and out.name == target and use_auto:
            cmd.append("--auto")
        elif target and out.name == target and mode_name:
            cmd.extend(["--mode", mode_name])
            if refresh is not None:
                cmd.extend(["--rate", f"{refresh:g}"])
        else:
            resolved = _resolved_mode(out)
            if resolved:
                cmd.extend(["--mode", resolved])
                if out.current_refresh is not None:
                    cmd.extend(["--rate", f"{out.current_refresh:g}"])

        if out.pos_x is not None and out.pos_y is not None:
            cmd.extend(["--pos", f"{out.pos_x}x{out.pos_y}"])
        if out.rotation:
            cmd.extend(["--rotate", out.rotation])
        if out.primary:
            cmd.append("--primary")

    _run(cmd)


def apply_native_mode(
    output_name: str,
    mode_name: str,
    *,
    refresh: float | None = None,
    outputs: list[DisplayOutput] | None = None,
) -> None:
    if outputs is None:
        outputs = list_outputs()

    if len(outputs) == 1:
        _apply_single_output_fallback(output_name, mode_name, refresh=refresh)
        return

    try:
        _xrandr_apply_layout(
            outputs,
            target=output_name,
            mode_name=mode_name,
            refresh=refresh,
        )
    except DisplayError:
        _apply_single_output_fallback(output_name, mode_name, refresh=refresh)


def generate_modeline(width: int, height: int, refresh: float) -> Modeline:
    if width < 320 or height < 240:
        raise DisplayError("Resolução mínima: 320x240")
    if width > 7680 or height > 4320:
        raise DisplayError("Resolução máxima: 7680x4320")
    if refresh < 30 or refresh > 240:
        raise DisplayError("Taxa de atualização deve estar entre 30 e 240 Hz")

    result = _run(["cvt", str(width), str(height), f"{refresh:g}"])
    match = re.search(r'Modeline\s+"([^"]+)"\s+(.+)', result.stdout)
    if not match:
        raise DisplayError("Não foi possível gerar o modeline com cvt")

    mode_name = match.group(1)
    args = tuple(match.group(2).split())
    return Modeline(name=mode_name, args=args)


def apply_modeline(
    output: str,
    modeline: Modeline,
    *,
    activate: bool = True,
    outputs: list[DisplayOutput] | None = None,
) -> None:
    if outputs is None:
        outputs = list_outputs()

    _run(["xrandr", "--newmode", modeline.name, *modeline.args], check=False)

    try:
        _run(["xrandr", "--addmode", output, modeline.name])
    except DisplayError as exc:
        if "already" not in str(exc).lower():
            raise

    if activate:
        _xrandr_apply_layout(
            outputs,
            target=output,
            mode_name=modeline.name,
        )


def apply_resolution(
    output_name: str,
    width: int,
    height: int,
    refresh: float,
    *,
    activate: bool = True,
) -> tuple[str, list[str]]:
    """Apply resolution, preferring native xrandr modes over custom cvt.

    Returns (mode_name, modeline_args). modeline_args is empty for native modes.
    """
    outputs = list_outputs()
    display = next((item for item in outputs if item.name == output_name), None)
    if display is None:
        raise DisplayError(f"Monitor não encontrado: {output_name}")

    native = find_native_mode(display, width, height, refresh)
    if native:
        if activate:
            last_error: DisplayError | None = None
            for mode_name, native_refresh in _native_rate_candidates(
                display, width, height, refresh
            ):
                try:
                    apply_native_mode(
                        output_name,
                        mode_name,
                        refresh=native_refresh,
                        outputs=outputs,
                    )
                    return mode_name, []
                except DisplayError as exc:
                    last_error = exc
            if last_error is not None:
                raise last_error
        return native[0], []

    modeline = generate_modeline(width, height, refresh)
    apply_modeline(output_name, modeline, activate=activate, outputs=outputs)
    return modeline.name, list(modeline.args)


def remove_mode(output: str, mode_name: str) -> None:
    outputs = list_outputs()
    _run(["xrandr", "--output", output, "--auto"], check=False)
    _run(["xrandr", "--delmode", output, mode_name], check=False)
    _run(["xrandr", "--rmmode", mode_name], check=False)


def reset_output_to_default(output: str) -> None:
    outputs = list_outputs()
    _xrandr_apply_layout(outputs, target=output, use_auto=True)


def apply_saved_resolutions(entries: list[dict]) -> list[str]:
    messages: list[str] = []
    outputs = list_outputs()

    for entry in entries:
        output = entry["output"]
        activate = entry.get("activate", False)
        modeline_args = entry.get("modeline_args") or []

        try:
            if not modeline_args:
                if activate:
                    apply_native_mode(
                        output,
                        entry["mode_name"],
                        refresh=float(entry["refresh"]),
                        outputs=outputs,
                    )
                    messages.append(f"Aplicado {entry['mode_name']} em {output}")
                else:
                    messages.append(f"Modo nativo {entry['mode_name']} em {output}")
                continue

            modeline = Modeline(name=entry["mode_name"], args=tuple(modeline_args))
            apply_modeline(output, modeline, activate=activate, outputs=outputs)
            if activate:
                messages.append(f"Aplicado {entry['mode_name']} em {output}")
            else:
                messages.append(f"Adicionado {entry['mode_name']} em {output}")
        except DisplayError as exc:
            messages.append(f"Falha em {output}: {exc}")

    return messages
