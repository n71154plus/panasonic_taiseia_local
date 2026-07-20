"""Tests for known TaiSEIA labels and 0/1 entity classification."""

from __future__ import annotations

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
    sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

    pkg_name = "panasonic_taiseia_local"
    pkg_mod = types.ModuleType(pkg_name)
    pkg_mod.__path__ = [str(ROOT / "custom_components" / "panasonic_taiseia_local")]
    sys.modules[pkg_name] = pkg_mod


_stub_homeassistant()
sys.path.insert(0, str(ROOT / "custom_components"))

from panasonic_taiseia_local.catalog import (  # noqa: E402
    build_profile,
    classify_command,
    merge_hidden_device_services,
)
from panasonic_taiseia_local.const import TYPE_AC  # noqa: E402
from panasonic_taiseia_local.probe_info import (  # noqa: E402
    is_known_service_label,
    service_label,
)
from panasonic_taiseia_local.taiseia import ServiceInfo  # noqa: E402


class KnownServiceAndClassifyTest(unittest.TestCase):
    def test_taiseia_ac_labels(self) -> None:
        self.assertEqual(service_label(0x15, TYPE_AC), "系統點檢")
        self.assertEqual(service_label(0x22, TYPE_AC), "室內機耗電")
        self.assertEqual(service_label(0x23, TYPE_AC), "室外機耗電")
        self.assertEqual(service_label(0x24, TYPE_AC), "室外機電流")
        self.assertEqual(service_label(0x29, TYPE_AC), "顯示錯誤")
        self.assertTrue(is_known_service_label(service_label(0x17, TYPE_AC)))
        self.assertFalse(is_known_service_label(service_label(0x7A, TYPE_AC)))

    def test_merge_known_without_device_suffix(self) -> None:
        profile = build_profile("PXGD")
        assert profile is not None
        # Pretend device also advertises services not in PXGD list
        services = {
            c.service: ServiceInfo(c.service, True, 0, 1) for c in profile.commands
        }
        services[0x12] = ServiceInfo(0x12, True, 0, 1)  # 濾網
        services[0x15] = ServiceInfo(0x15, False, 0, 15)
        services[0x22] = ServiceInfo(0x22, False, 0, 65535)
        services[0x38] = ServiceInfo(0x38, False, 0, 1)
        services[0x7A] = ServiceInfo(0x7A, True, 0, 1)

        # Remove 0x17 from profile commands to force merge path for 乾燥防霉
        profile.commands = [c for c in profile.commands if c.service != 0x17]
        profile.classified = [
            c for c in profile.classified if c.command.service != 0x17
        ]
        services[0x17] = ServiceInfo(0x17, True, 0, 1)

        merged = merge_hidden_device_services(profile, services)
        by_sid = {c.service: c for c in merged.commands}

        self.assertEqual(by_sid[0x17].name, "乾燥防霉")
        self.assertNotIn("裝置回報", by_sid[0x17].name)
        self.assertEqual(by_sid[0x15].name, "系統點檢")
        self.assertEqual(by_sid[0x22].name, "室內機耗電")
        self.assertIn("裝置回報", by_sid[0x7A].name)

        kinds = {
            item.command.service: item.kind
            for item in merged.classified
            if item.command.service in (0x17, 0x12, 0x38, 0x15, 0x22, 0x7A)
        }
        self.assertEqual(kinds[0x17], "switch")
        self.assertEqual(kinds[0x12], "binary_sensor")
        self.assertEqual(kinds[0x38], "binary_sensor")
        self.assertEqual(kinds[0x15], "sensor")
        self.assertEqual(kinds[0x22], "sensor")
        self.assertEqual(kinds[0x7A], "switch")

    def test_swing_lr_options_use_segments(self) -> None:
        profile = build_profile("PXGD")
        assert profile is not None
        item = next(
            c for c in profile.classified if c.command.service == 0x11
        )
        self.assertEqual(item.kind, "select")
        self.assertEqual(item.option_map[0], "自動")
        self.assertEqual(item.option_map[1], "1段")


if __name__ == "__main__":
    unittest.main()
