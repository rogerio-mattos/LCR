from __future__ import annotations

import math
import re


# (width_ratio, height_ratio, display_name)
_KNOWN_RATIOS: tuple[tuple[int, int, str], ...] = (
    (32, 9, "32:9"),
    (21, 9, "21:9"),
    (64, 27, "21:9"),
    (43, 18, "21:9"),
    (18, 9, "18:9"),
    (16, 9, "16:9"),
    (16, 10, "16:10"),
    (5, 4, "5:4"),
    (4, 3, "4:3"),
    (3, 2, "3:2"),
    (5, 3, "5:3"),
)


def aspect_ratio_from_resolution(resolution: str) -> str | None:
    """Parse '1920x1080' and return aspect label like '16:9'."""
    match = re.match(r"^(\d+)x(\d+)$", resolution.strip())
    if not match:
        return None
    return aspect_ratio_name(int(match.group(1)), int(match.group(2)))


def aspect_ratio_name(width: int, height: int) -> str:
    if width < 1 or height < 1:
        return ""

    target = width / height
    best_name = ""
    best_diff = float("inf")

    for rw, rh, name in _KNOWN_RATIOS:
        diff = abs(target - rw / rh)
        if diff < best_diff:
            best_diff = diff
            best_name = name

    # Within ~2% of a well-known ratio — show the friendly name.
    if best_name and best_diff < 0.02:
        return best_name

    divisor = math.gcd(width, height)
    reduced_w = width // divisor
    reduced_h = height // divisor
    if reduced_w <= 32 and reduced_h <= 32:
        return f"{reduced_w}:{reduced_h}"

    return best_name or f"{reduced_w}:{reduced_h}"


def format_resolution_size(width: int, height: int) -> str:
    ratio = aspect_ratio_name(width, height)
    if ratio:
        return f"{width}x{height} ({ratio})"
    return f"{width}x{height}"


def format_resolution_details(width: int, height: int, refresh: float) -> str:
    return f"{format_resolution_size(width, height)} @ {refresh:g} Hz"
