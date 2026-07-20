"""Unit tests for diagnostic helpers (redaction, service id, snapshot)."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

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
    sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))
    const = pkg("homeassistant.const")
    const.CONF_HOST = "host"
    const.CONF_NAME = "name"
    const.CONF_PASSWORD = "password"
    const.CONF_DEVICE_ID = "device_id"
    core = pkg("homeassistant.core")
    core.HomeAssistant = object
    pkg("homeassistant.config_entries")

    pkg_name = "panasonic_taiseia_local"
    pkg_mod = types.ModuleType(pkg_name)
    pkg_mod.__path__ = [str(ROOT / "custom_components" / "panasonic_taiseia_local")]
    sys.modules[pkg_name] = pkg_mod


_stub_homeassistant()
sys.path.insert(0, str(ROOT / "custom_components"))

from panasonic_taiseia_local.diagnostics_data import (  # noqa: E402
    build_device_snapshot,
    mask_username,
    parse_service_id,
    probe_sensor_attributes,
    redact_mapping,
)
from panasonic_taiseia_local.taiseia import DeviceInfo, ServiceInfo  # noqa: E402


class DiagnosticsDataTest(unittest.TestCase):
    def test_parse_service_id(self) -> None:
        self.assertEqual(parse_service_id(18), 18)
        self.assertEqual(parse_service_id("0x12"), 0x12)
        self.assertEqual(parse_service_id("12h"), 0x12)
        self.assertEqual(parse_service_id("18"), 18)
        with self.assertRaises(ValueError):
            parse_service_id("")

    def test_mask_and_redact(self) -> None:
        self.assertEqual(mask_username("ab@example.com"), "**@example.com")
        self.assertEqual(mask_username("user@example.com"), "u***r@example.com")
        redacted = redact_mapping(
            {
                "username": "user@example.com",
                "password": "secret",
                "cp_token": "tok",
                "host": "192.168.0.10",
            }
        )
        self.assertEqual(redacted["password"], "**REDACTED**")
        self.assertEqual(redacted["cp_token"], "**REDACTED**")
        self.assertEqual(redacted["host"], "192.168.0.10")
        self.assertNotIn("secret", str(redacted.values()))

    def test_snapshot_and_probe_attrs(self) -> None:
        entry = SimpleNamespace(
            entry_id="abc",
            title="客廳冷氣",
            unique_id="aabbccddeeff",
            version=2,
            data={
                "host": "192.168.0.10",
                "mac": "AABBCCDDEEFF",
                "password": "nope",
                "model_type": "PXGD",
            },
            options={},
        )
        device = DeviceInfo(host="192.168.0.10", mac="AABBCCDDEEFF", sa_type_id=1)
        device.services[0x00] = ServiceInfo(0x00, True, 0, 1)
        device.services[0x12] = ServiceInfo(0x12, True, 0, 1)
        snapshot = build_device_snapshot(
            entry=entry,
            device=device,
            status={"0x00": "1", "0x12": "0"},
            profile=None,
            coordinator_ok=True,
            poll_interval=30,
            lan={"timeout": 12.0},
            extra={"model_type": "PXGD"},
        )
        self.assertEqual(snapshot["entry"]["data"]["password"], "**REDACTED**")
        self.assertEqual(snapshot["services"][0]["id_hex"], "0x00")
        attrs = probe_sensor_attributes(snapshot)
        self.assertEqual(attrs["ModelType"], "PXGD")
        self.assertEqual(attrs["服務數量"], 2)
        self.assertTrue(any("0x00" in line for line in attrs["服務清單"]))


if __name__ == "__main__":
    unittest.main()
