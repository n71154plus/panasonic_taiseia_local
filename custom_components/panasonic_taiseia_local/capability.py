"""Capability helpers — detect supported AC features from TaiSEIA service list."""

from __future__ import annotations

from .taiseia import ServiceInfo, TaiSeiaClient

# Typical bitmask maxima from TaiSEIA AC service descriptors
_BITMASK_MAXIMA = frozenset({1, 3, 7, 15, 31, 63, 127, 255})


# A real min/max such as temperature 16–30. Wider pairs are a 16-bit
# support mask: bit N means value N. NXW reports 0x1E 0x59, which is not
# the range 30–89.
_CONTIGUOUS_SPAN = 16


def looks_like_bitmask(info: ServiceInfo) -> bool:
    """Enum-style services encode supported values as a bit field in max_value."""
    return info.min_value == 0 and info.max_value in _BITMASK_MAXIMA


def _bitmask_values(mask: int) -> list[int]:
    return [i for i in range(16) if mask & (1 << i)]


def supported_values(info: ServiceInfo | None, fallback: list[int] | None = None) -> list[int]:
    """Return supported numeric values for a service descriptor."""
    if info is None:
        return list(fallback or [])
    hi = int(info.min_value)
    lo = int(info.max_value)
    if not (0 <= hi <= 0xFF and 0 <= lo <= 0xFF):
        if lo > hi >= 0 and lo - hi <= 200:
            return list(range(hi, lo + 1))
        return list(fallback or [])
    if looks_like_bitmask(info):
        return _bitmask_values(lo)
    if hi <= lo and lo - hi <= _CONTIGUOUS_SPAN:
        return list(range(hi, lo + 1))
    # Two-byte enum capability. 0x1E59 supports values 0, 3, 4, 6, …
    bits = _bitmask_values((hi << 8) | lo)
    return bits or list(fallback or [])


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


def timer_limits(
    client: TaiSeiaClient,
    service: int,
    default_min: int,
    default_max: int,
) -> tuple[int, int]:
    """Return (min, max) for timer numbers; always allow 0 = off."""
    info = client.device.services.get(service)
    if not info:
        return default_min, default_max
    lo, hi = info.min_value, info.max_value
    # Device may advertise step-range like 5–160; keep 0 for disable
    if 0 < lo <= hi <= 2000:
        return 0, hi
    if lo == 0 and 0 < hi <= 2000:
        return 0, hi
    return default_min, default_max
