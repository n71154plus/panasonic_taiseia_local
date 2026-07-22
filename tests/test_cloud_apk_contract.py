"""APK-aligned EMS helpers (no network)."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _stub() -> None:
    def pkg(name: str) -> types.ModuleType:
        mod = types.ModuleType(name)
        mod.__path__ = []
        sys.modules[name] = mod
        return mod

    ha = pkg("homeassistant")
    components = pkg("homeassistant.components")
    climate = pkg("homeassistant.components.climate")

    class _HVACMode:
        OFF = "off"
        COOL = "cool"
        DRY = "dry"
        FAN_ONLY = "fan_only"
        AUTO = "auto"
        HEAT = "heat"

    climate.HVACMode = _HVACMode
    ha.components = components
    components.climate = climate
    sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))
    pkg_name = "panasonic_taiseia_local"
    pkg_mod = types.ModuleType(pkg_name)
    pkg_mod.__path__ = [str(ROOT / "custom_components" / "panasonic_taiseia_local")]
    sys.modules[pkg_name] = pkg_mod


_stub()

from panasonic_taiseia_local.cloud import (  # noqa: E402
    build_device_get_info_body,
    command_type_hex,
    parse_device_get_info,
)
from panasonic_taiseia_local.const import (  # noqa: E402
    CONTROL_MODE_CLOUD,
    CONTROL_MODE_HYBRID,
    CONTROL_MODE_LOCAL,
    DEFAULT_CONTROL_MODE,
)
from panasonic_taiseia_local.ems_transport import classify_state_msg, CloudRateLimited  # noqa: E402


class ApkContractTests(unittest.TestCase):
    def test_command_type_hex(self):
        self.assertEqual(command_type_hex(0), "0x00")
        self.assertEqual(command_type_hex(23), "0x17")

    def test_get_info_body(self):
        body = build_device_get_info_body(["0x00", "0x01"])
        self.assertEqual(body[0]["DeviceID"], 1)
        self.assertEqual(body[0]["CommandTypes"][0]["CommandType"], "0x00")

    def test_parse_get_info(self):
        payload = {
            "devices": [
                {
                    "DeviceID": 1,
                    "Info": [
                        {"CommandType": "0x00", "status": "1"},
                        {"CommandType": "0x01", "status": "0"},
                    ],
                }
            ]
        }
        status = parse_device_get_info(payload)
        self.assertEqual(status["0x00"], "1")
        self.assertEqual(status["0x01"], "0")

    def test_defaults(self):
        self.assertEqual(DEFAULT_CONTROL_MODE, CONTROL_MODE_HYBRID)
        self.assertIn(CONTROL_MODE_LOCAL, (CONTROL_MODE_LOCAL, CONTROL_MODE_CLOUD))

    def test_rate_limit_msg(self):
        self.assertIs(classify_state_msg("系統檢測您當前超量使用"), CloudRateLimited)



class CloudDeviceFlagsTests(unittest.TestCase):
    def test_mac_gwid_is_local(self):
        from panasonic_taiseia_local.cloud import CloudDevice
        d = CloudDevice(
            gwid="AABBCCDDEEFF",
            auth="x",
            nickname="AC",
            model="X",
            model_id="",
            model_type="UX",
            device_type=1,
            mac="AABBCCDDEEFF",
        )
        self.assertTrue(d.is_local_candidate)
        d2 = CloudDevice(
            gwid="opaqueGwid123456",
            auth="y",
            nickname="Fridge",
            model="F",
            model_id="",
            model_type="F657",
            device_type=2,
            mac=None,
        )
        self.assertFalse(d2.is_local_candidate)


if __name__ == "__main__":
    unittest.main()
