"""A module that rejects the REGISTER read is still a usable LAN device.

PIOT-V2 modules (seen on a dehumidifier, SW_VER 2.0.5) answer FFFFFFFFFFFF to
``REG_REGISTER`` but serve type id, model, services and ALL_STATES normally.
Failing the probe on that one read hid the device from LAN discovery and
import fell back to a cloud-only entry.
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

from panasonic_taiseia_local.const import TYPE_DEHUMIDIFIER  # noqa: E402
from panasonic_taiseia_local.taiseia import (  # noqa: E402
    TaiSeiaClient,
    TaiSeiaCommandError,
)

# Replies captured from a PIOT-V2 dehumidifier, keyed by the request frame.
PIOT_V2_REPLIES = {
    "060004FFFF02": "060004000406",
    "060006FFFF00": "120006465954572D3231383730423342002A",
    "060007FFFF01": (
        "280007800003811FF582000C84007F07006389000F0A00038D00038E000F"
        "12FFFF9800039DFFFF42"
    ),
}


class _PiotV2Client(TaiSeiaClient):
    async def async_get_device_xml(self) -> dict:
        self.device.mac = "0011223344AA"
        return {}

    async def async_set_saanet(self, frame: bytes) -> bytes:
        reply = PIOT_V2_REPLIES.get(frame.hex().upper())
        if reply is None:
            raise TaiSeiaCommandError(f"command rejected: {frame.hex().upper()}")
        return bytes.fromhex(reply)


class TestProbeRegisterRejected(unittest.TestCase):
    def test_probe_succeeds_without_register(self) -> None:
        client = _PiotV2Client(None, "192.0.2.19")
        device = asyncio.run(client.async_probe())
        self.assertEqual(device.sa_type_id, TYPE_DEHUMIDIFIER)
        self.assertEqual(device.sa_model, "FYTW-21870B3B")
        self.assertEqual(
            sorted(device.services),
            [0x00, 0x01, 0x02, 0x04, 0x07, 0x09, 0x0A, 0x0D, 0x0E, 0x12, 0x18, 0x1D],
        )
        self.assertTrue(device.services[0x00].writable)
        self.assertFalse(device.services[0x07].writable)

    def test_probe_fails_when_nothing_answers(self) -> None:
        class _Dead(_PiotV2Client):
            async def async_set_saanet(self, frame: bytes) -> bytes:
                raise TaiSeiaCommandError("command rejected")

        with self.assertRaises(TaiSeiaCommandError):
            asyncio.run(_Dead(None, "192.0.2.19").async_probe())


if __name__ == "__main__":
    unittest.main()
