"""A powered-off module must not walk every service on a dead socket.

Smart-plug setups cut power while Home Assistant restarts. ALL_STATES then
times out. Falling through to one read per service (12s × 3 retries) holds
startup until the 300s bootstrap cancel, which leaves the entry in
setup_error. A closed TCP port skips that walk. A module that answers — or
rejects ALL_STATES while the port is open — still uses the per-service path.
"""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _stub_homeassistant() -> None:
    class _HVACMode:
        OFF = "off"
        COOL = "cool"
        DRY = "dry"
        FAN_ONLY = "fan_only"
        AUTO = "auto"
        HEAT = "heat"

    def pkg(name: str) -> types.ModuleType:
        mod = types.ModuleType(name)
        mod.__path__ = []
        sys.modules[name] = mod
        return mod

    ha = pkg("homeassistant")
    components = pkg("homeassistant.components")
    climate = pkg("homeassistant.components.climate")
    climate.HVACMode = _HVACMode
    ha.components = components
    components.climate = climate
    aiohttp = sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))
    for name, value in (
        ("ClientTimeout", lambda total=None: total),
        ("ClientError", OSError),
        ("ClientSession", object),
    ):
        if not hasattr(aiohttp, name):
            setattr(aiohttp, name, value)

    pkg_name = "panasonic_taiseia_local"
    pkg_mod = types.ModuleType(pkg_name)
    pkg_mod.__path__ = [str(ROOT / "custom_components" / "panasonic_taiseia_local")]
    sys.modules[pkg_name] = pkg_mod


_stub_homeassistant()
sys.path.insert(0, str(ROOT / "custom_components"))

from panasonic_taiseia_local.discovery import (  # noqa: E402
    async_port_open,
    clear_host_scan_cache,
)
from panasonic_taiseia_local import discovery  # noqa: E402
from panasonic_taiseia_local.taiseia import (  # noqa: E402
    ServiceInfo,
    TaiSeiaClient,
    TaiSeiaCommandError,
    is_lan_transport_error,
)


class _StatusClient(TaiSeiaClient):
    def __init__(self, *, reachable: bool, error: BaseException) -> None:
        super().__init__(None, "192.0.2.20", retries=1)
        self.reachable = reachable
        self.error = error
        self.calls = 0
        self.tcp_checks = 0
        self.device.sa_type_id = 0x04
        self.device.services = {
            0x00: ServiceInfo(0x00, True, 0, 1),
            0x01: ServiceInfo(0x01, True, 0, 1),
        }
        self.poll_services = [0x00, 0x01]

    async def _tcp_open(self, timeout: float = 3.0) -> bool:
        self.tcp_checks += 1
        return self.reachable

    async def async_set_saanet(self, frame: bytes) -> bytes:
        self.calls += 1
        raise self.error


class LanOfflineFastTest(unittest.TestCase):
    def test_closed_port_does_not_walk_services(self) -> None:
        client = _StatusClient(reachable=False, error=TimeoutError("no route"))
        with self.assertRaises(TimeoutError):
            asyncio.run(client.async_fetch_status())
        self.assertEqual(client.calls, 1)
        self.assertEqual(client.tcp_checks, 1)

    def test_open_port_timeout_still_falls_back(self) -> None:
        client = _StatusClient(reachable=True, error=TimeoutError("slow"))
        asyncio.run(client.async_fetch_status())
        self.assertGreater(client.calls, 1)
        self.assertEqual(client.tcp_checks, 1)

    def test_command_reject_falls_back_without_port_check(self) -> None:
        client = _StatusClient(
            reachable=False, error=TaiSeiaCommandError("command rejected")
        )
        asyncio.run(client.async_fetch_status())
        self.assertGreater(client.calls, 1)
        self.assertEqual(client.tcp_checks, 0)

    def test_transport_error_classifier(self) -> None:
        self.assertTrue(is_lan_transport_error(TimeoutError("x")))
        self.assertTrue(is_lan_transport_error(ConnectionError("x")))
        self.assertFalse(is_lan_transport_error(TaiSeiaCommandError("rejected")))

    def test_blank_host_is_not_open(self) -> None:
        self.assertFalse(asyncio.run(async_port_open("")))
        self.assertFalse(asyncio.run(async_port_open("0.0.0.0")))

    def test_concurrent_mac_lookups_share_one_scan(self) -> None:
        clear_host_scan_cache()
        original = discovery.async_discover_devices
        calls: list[bool] = []

        async def fake_discover(session, *, include_subnet_scan=True, subnet_hints=None):
            calls.append(bool(include_subnet_scan))
            await asyncio.sleep(0.02)
            return []

        async def both() -> None:
            await asyncio.gather(
                discovery.async_find_host_by_mac(None, "001122334455"),
                discovery.async_find_host_by_mac(None, "AABBCCDDEEFF"),
            )

        discovery.async_discover_devices = fake_discover
        try:
            asyncio.run(both())
            self.assertEqual(calls, [False, True])
            asyncio.run(discovery.async_find_host_by_mac(None, "001122334455"))
            self.assertEqual(calls, [False, True])
        finally:
            discovery.async_discover_devices = original
            clear_host_scan_cache()


if __name__ == "__main__":
    unittest.main()
