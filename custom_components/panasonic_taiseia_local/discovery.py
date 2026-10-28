"""Discover Panasonic CZ-T006 / TaiSEIA modules on the LAN."""

from __future__ import annotations

import asyncio
import logging
import re
import socket
import time
from dataclasses import dataclass

import aiohttp

from .const import DEFAULT_PORT, DEVICE_TYPE_NAMES
from .taiseia import TaiSeiaClient, TaiSeiaError

_LOGGER = logging.getLogger(__package__)

SSDP_ADDR = ("239.255.255.250", 1900)
SSDP_STS = (
    "ssdp:all",
    "urn:schemas-upnp-org:service:SwitchPower:1",
    "urn:schemas-upnp-org:device:airconditonDevice:1",
)


@dataclass
class DiscoveredDevice:
    host: str
    port: int
    mac: str
    name: str
    sa_type: int
    model: str

    @property
    def label(self) -> str:
        type_name = DEVICE_TYPE_NAMES.get(self.sa_type, f"type={self.sa_type}")
        base = self.name or self.model or self.host
        return f"{base} ({self.host}) [{type_name}]"


def _parse_ssdp_location(payload: str) -> str | None:
    m = re.search(r"(?i)^LOCATION:\s*(\S+)", payload, re.M)
    return m.group(1).strip() if m else None


def _host_from_location(location: str) -> str | None:
    m = re.search(r"https?://([^/:]+)", location)
    return m.group(1) if m else None


async def _ssdp_search(timeout: float = 3.0) -> set[str]:
    """Return candidate hosts from SSDP M-SEARCH."""
    hosts: set[str] = set()
    loop = asyncio.get_running_loop()

    def _sync_search() -> set[str]:
        found: set[str] = set()
        for st in SSDP_STS:
            msg = (
                "M-SEARCH * HTTP/1.1\r\n"
                f"HOST: {SSDP_ADDR[0]}:{SSDP_ADDR[1]}\r\n"
                'MAN: "ssdp:discover"\r\n'
                "MX: 2\r\n"
                f"ST: {st}\r\n"
                "\r\n"
            ).encode()
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(timeout)
            try:
                sock.sendto(msg, SSDP_ADDR)
                while True:
                    try:
                        data, _addr = sock.recvfrom(65535)
                    except socket.timeout:
                        break
                    text = data.decode("utf-8", "replace")
                    if (
                        "SwitchPower" not in text
                        and "57223" not in text
                        and "airconditon" not in text.lower()
                        and "panasonic" not in text.lower()
                    ):
                        continue
                    loc = _parse_ssdp_location(text)
                    if not loc:
                        continue
                    host = _host_from_location(loc)
                    if host:
                        found.add(host)
            finally:
                sock.close()
        return found

    try:
        hosts = await loop.run_in_executor(None, _sync_search)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("SSDP search failed: %s", err)
    return hosts


async def async_port_open(
    host: str, port: int = DEFAULT_PORT, timeout: float = 3.0
) -> bool:
    """True when TCP connects. One attempt, no SOAP and no retries."""
    if not host or host in ("0.0.0.0", ""):
        return False
    return await _port_open(host, port, timeout)


async def _port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        return True
    except Exception:  # noqa: BLE001
        return False


async def _local_outbound_ip() -> str | None:
    """Resolve outbound IP off the event loop (UDP connect is sync)."""
    loop = asyncio.get_running_loop()

    def _sync() -> str | None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
            finally:
                s.close()
        except Exception:  # noqa: BLE001
            return None

    return await loop.run_in_executor(None, _sync)


async def _subnet_hosts(
    hass_host_hint: str | None = None,
    *,
    extra_hints: list[str] | None = None,
) -> list[str]:
    """Best-effort /24 scan based on local outbound IP (+ optional hints)."""
    hints: list[str] = []
    for candidate in [hass_host_hint, *(extra_hints or [])]:
        if candidate and candidate not in hints:
            hints.append(candidate)
    if not hints:
        outbound = await _local_outbound_ip()
        if outbound:
            hints.append(outbound)
        else:
            return []

    hosts: list[str] = []
    seen_prefixes: set[str] = set()
    for hint in hints:
        parts = hint.split(".")
        if len(parts) != 4:
            continue
        prefix = ".".join(parts[:3])
        if prefix in seen_prefixes:
            continue
        seen_prefixes.add(prefix)
        hosts.extend(f"{prefix}.{i}" for i in range(1, 255))
    return hosts


async def _scan_port_57223(hosts: list[str], limit: int = 64) -> set[str]:
    sem = asyncio.Semaphore(limit)
    found: set[str] = set()

    async def _one(host: str) -> None:
        async with sem:
            if await _port_open(host, DEFAULT_PORT):
                found.add(host)

    await asyncio.gather(*(_one(h) for h in hosts))
    return found


async def async_probe_host(
    session: aiohttp.ClientSession, host: str
) -> DiscoveredDevice | None:
    client = TaiSeiaClient(session, host)
    try:
        device = await client.async_probe()
    except (TaiSeiaError, asyncio.TimeoutError, aiohttp.ClientError, OSError) as err:
        _LOGGER.debug("Probe %s failed: %s", host, err)
        return None
    return DiscoveredDevice(
        host=host,
        port=device.port,
        mac=device.mac or device.unique_id,
        name=device.friendly_name or device.sa_model or host,
        sa_type=device.sa_type_id,
        model=device.sa_model or device.model_number or device.model_name,
    )


def _normalize_mac(mac: str | None) -> str | None:
    if not mac:
        return None
    cleaned = mac.replace(":", "").replace("-", "").upper()
    return cleaned if len(cleaned) == 12 else None


def _match_mac(devices: list[DiscoveredDevice], want: str) -> DiscoveredDevice | None:
    for dev in devices:
        if _normalize_mac(dev.mac) == want:
            return dev
    return None


async def async_discover_devices(
    session: aiohttp.ClientSession,
    *,
    include_subnet_scan: bool = True,
    subnet_hints: list[str] | None = None,
) -> list[DiscoveredDevice]:
    """SSDP first, optionally fall back to subnet TCP scan on :57223."""
    hosts = await _ssdp_search()
    _LOGGER.debug("SSDP candidates: %s", hosts)
    if include_subnet_scan:
        subnet = await _subnet_hosts(extra_hints=subnet_hints)
        if subnet:
            open_hosts = await _scan_port_57223(subnet)
            hosts |= open_hosts
            _LOGGER.debug("Port-scan candidates added: %s", open_hosts)

    results: list[DiscoveredDevice] = []
    for host in sorted(hosts):
        dev = await async_probe_host(session, host)
        if dev:
            results.append(dev)
    return results


# Several entries reboot together. Share one SSDP /24 pass so three powered-off
# dehumidifiers do not each probe every other live module.
_HOST_SCAN_TTL_S = 300.0
_host_scan_lock: asyncio.Lock | None = None
# (monotonic, included a subnet scan, hints, devices)
_host_scan_cache: tuple[float, bool, tuple[str, ...], list[DiscoveredDevice]] | None = (
    None
)


def clear_host_scan_cache() -> None:
    """Drop the shared MAC-scan cache (tests)."""
    global _host_scan_cache
    _host_scan_cache = None


def _host_scan_lock_get() -> asyncio.Lock:
    global _host_scan_lock
    if _host_scan_lock is None:
        _host_scan_lock = asyncio.Lock()
    return _host_scan_lock


async def _scan_hosts_shared(
    session: aiohttp.ClientSession,
    *,
    include_subnet_scan: bool,
    subnet_hints: list[str] | None,
) -> list[DiscoveredDevice]:
    """Return discovered modules, reusing a fresh scan when one is in hand."""
    global _host_scan_cache
    hints = tuple(subnet_hints or ())
    now = time.monotonic()
    cached = _host_scan_cache
    if (
        cached is not None
        and now - cached[0] < _HOST_SCAN_TTL_S
        and cached[2] == hints
        and (cached[1] or not include_subnet_scan)
    ):
        return list(cached[3])
    devices = await async_discover_devices(
        session,
        include_subnet_scan=include_subnet_scan,
        subnet_hints=subnet_hints,
    )
    _host_scan_cache = (time.monotonic(), include_subnet_scan, hints, list(devices))
    return list(devices)


async def async_find_host_by_mac(
    session: aiohttp.ClientSession,
    mac: str,
    *,
    include_subnet_scan: bool = True,
    subnet_hints: list[str] | None = None,
) -> DiscoveredDevice | None:
    """Re-locate a module after DHCP gave it a new IP (match by MAC).

    SSDP-only first; full /24 scan only if still missing. Concurrent lookups
    share one scan for ``_HOST_SCAN_TTL_S`` seconds.
    """
    want = _normalize_mac(mac)
    if not want:
        return None
    async with _host_scan_lock_get():
        found = await _scan_hosts_shared(
            session,
            include_subnet_scan=False,
            subnet_hints=subnet_hints,
        )
        hit = _match_mac(found, want)
        if hit is not None or not include_subnet_scan:
            return hit
        found = await _scan_hosts_shared(
            session,
            include_subnet_scan=True,
            subnet_hints=subnet_hints,
        )
        return _match_mac(found, want)
