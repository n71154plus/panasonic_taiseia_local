"""Capability helpers — detect supported AC features from TaiSEIA service list."""

from __future__ import annotations

from .taiseia import ServiceInfo, TaiSeiaClient

# Typical bitmask maxima from TaiSEIA AC service descriptors
_BITMASK_MAXIMA = frozenset({1, 3, 7, 15, 31, 63, 127, 255})


def looks_like_bitmask(info: ServiceInfo) -> bool:
    """Enum-style services encode supported values as a bit field in max_value."""
    return info.min_value == 0 and info.max_value in _BITMASK_MAXIMA


def supported_values(info: ServiceInfo | None, fallback: list[int] | None = None) -> list[int]:
    """Return supported numeric values for a service descriptor."""
    if info is None:
        return list(fallback or [])
    if looks_like_bitmask(info):
        return [i for i in range(16) if info.max_value & (1 << i)]
    if info.min_value <= info.max_value:
        # Continuous / discrete range (e.g. temperature 16–30, timer 5–160)
        hi = info.max_value
        lo = info.min_value
        if hi - lo > 200:
            return list(fallback or [])
        return list(range(lo, hi + 1))
    return list(fallback or [])


def filter_option_map(
    client: TaiSeiaClient,
    service: int,
    option_map: dict[int, str],
) -> dict[int, str]:
    """Filter a value→label map by device capability; keep full map if unknown."""
    info = client.device.services.get(service)
    if not info:
        return dict(option_map)
    values = supported_values(info, list(option_map.keys()))
    if not values:
        return dict(option_map)
    filtered = {k: v for k, v in option_map.items() if k in values}
    return filtered or dict(option_map)


# Longer than a week is not a TaiSEIA timer ceiling.
_TIMER_CEILING_LIMIT = 7 * 24 * 60


def timer_ceiling(info: ServiceInfo) -> int | None:
    """Return the timer maximum advertised by a service-list entry.

    Timer entries store one big-endian maximum, not separate min and max
    bytes. ``0x05 0xA0`` is 1440 minutes (24 h). Treating those bytes as
    min=5 and max=160 caps the slider at 160.
    """
    try:
        hi_b = int(info.min_value)
        lo_b = int(info.max_value)
    except (TypeError, ValueError):
        return None
    if 0 <= hi_b <= 0xFF and 0 <= lo_b <= 0xFF:
        ceiling = (hi_b << 8) | lo_b
    elif lo_b > hi_b >= 0:
        # Synthetic ServiceInfo that already holds a decoded maximum.
        ceiling = lo_b
    else:
        return None
    if ceiling <= 0 or ceiling > _TIMER_CEILING_LIMIT:
        return None
    return ceiling


def timer_limits(
    client: TaiSeiaClient,
    service: int,
    default_min: int,
    default_max: int,
) -> tuple[int, int]:
    """Return (min, max) for timer numbers; always allow 0 = off."""
    info = client.device.services.get(service)
    if info is None:
        return default_min, default_max
    ceiling = timer_ceiling(info)
    if ceiling is None:
        return default_min, default_max
    return 0, ceiling
