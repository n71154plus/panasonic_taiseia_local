"""Discover Panasonic CZ-T006 / TaiSEIA modules on the LAN."""

from __future__ import annotations

import asyncio
import logging
import re
import socket
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


async def _subnet_hosts(hass_host_hint: str | None = None) -> list[str]:
    """Best-effort /24 scan based on local outbound IP."""
    hint = hass_host_hint
    if not hint:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            hint = s.getsockname()[0]
            s.close()
        except Exception:  # noqa: BLE001
            return []
    parts = hint.split(".")
    if len(parts) != 4:
        return []
    prefix = ".".join(parts[:3])
    return [f"{prefix}.{i}" for i in range(1, 255)]


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


async def async_discover_devices(
    session: aiohttp.ClientSession,
    *,
    include_subnet_scan: bool = True,
) -> list[DiscoveredDevice]:
    """SSDP first, optionally fall back to subnet TCP scan on :57223."""
    hosts = await _ssdp_search()
    _LOGGER.debug("SSDP candidates: %s", hosts)
    if include_subnet_scan:
        subnet = await _subnet_hosts()
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


async def async_find_host_by_mac(
    session: aiohttp.ClientSession,
    mac: str,
    *,
    include_subnet_scan: bool = True,
) -> DiscoveredDevice | None:
    """Re-locate a module after DHCP gave it a new IP (match by MAC)."""
    want = _normalize_mac(mac)
    if not want:
        return None
    found = await async_discover_devices(
        session, include_subnet_scan=include_subnet_scan
    )
    for dev in found:
        if _normalize_mac(dev.mac) == want:
            return dev
    return None
