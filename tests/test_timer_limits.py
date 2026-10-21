"""Timer service-list bytes are one 16-bit maximum, not min and max."""

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

    pkg_name = "panasonic_taiseia_local"
    pkg_mod = types.ModuleType(pkg_name)
    pkg_mod.__path__ = [str(ROOT / "custom_components" / "panasonic_taiseia_local")]
    sys.modules[pkg_name] = pkg_mod


_stub_homeassistant()
sys.path.insert(0, str(ROOT / "custom_components"))

from panasonic_taiseia_local.capability import timer_limits  # noqa: E402
from panasonic_taiseia_local.const import SVC_TIMER_OFF  # noqa: E402
from panasonic_taiseia_local.taiseia import ServiceInfo, parse_services_pdu  # noqa: E402


def _client(info: ServiceInfo | None):
    services = {} if info is None else {info.service_id: info}
    return SimpleNamespace(device=SimpleNamespace(services=services))


class TimerLimitTests(unittest.TestCase):
    def test_two_bytes_are_one_maximum(self) -> None:
        # 0x05 0xA0 == 1440 minutes, not min 5 / max 160.
        info = ServiceInfo(SVC_TIMER_OFF, True, 0x05, 0xA0)
        self.assertEqual(timer_limits(_client(info), SVC_TIMER_OFF, 0, 1440), (0, 1440))

    def test_hour_timer_still_uses_small_ceiling(self) -> None:
        info = ServiceInfo(0x02, True, 0x00, 12)
        self.assertEqual(timer_limits(_client(info), 0x02, 0, 12), (0, 12))

    def test_decoded_maximum_is_kept(self) -> None:
        info = ServiceInfo(SVC_TIMER_OFF, True, 0, 1440)
        self.assertEqual(timer_limits(_client(info), SVC_TIMER_OFF, 0, 160), (0, 1440))

    def test_missing_service_uses_defaults(self) -> None:
        self.assertEqual(timer_limits(_client(None), SVC_TIMER_OFF, 0, 1440), (0, 1440))

    def test_service_list_pdu_feeds_the_slider(self) -> None:
        payload = bytes([0x80 | SVC_TIMER_OFF, 0x05, 0xA0])
        resp = bytes([len(payload) + 3, 0x00, 0x07]) + payload + bytes([0])
        services = parse_services_pdu(resp)
        info = services[SVC_TIMER_OFF]
        self.assertEqual((info.min_value, info.max_value), (0x05, 0xA0))
        self.assertEqual(
            timer_limits(
                SimpleNamespace(device=SimpleNamespace(services=services)),
                SVC_TIMER_OFF,
                0,
                1440,
            ),
            (0, 1440),
        )


if __name__ == "__main__":
    unittest.main()
