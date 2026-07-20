"""Unit tests for type-aware TaiSEIA diagnostic service labels."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _stub_homeassistant() -> None:
    """Minimal HA package stubs so the integration imports without HA installed."""

    class _HVACMode:
        OFF = "off"
        COOL = "cool"
        DRY = "dry"
        FAN_ONLY = "fan_only"
        AUTO = "auto"
        HEAT = "heat"

    def pkg(name: str) -> types.ModuleType:
        mod = types.ModuleType(name)
        mod.__path__ = []  # mark as package
        sys.modules[name] = mod
        return mod

    ha = pkg("homeassistant")
    components = pkg("homeassistant.components")
    climate = pkg("homeassistant.components.climate")
    climate.HVACMode = _HVACMode
    ha.components = components
    components.climate = climate

    # taiseia.py imports aiohttp at module level.
    sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

    # Keep package __init__ from loading during `from panasonic_taiseia_local.X`.
    pkg_name = "panasonic_taiseia_local"
    pkg_mod = types.ModuleType(pkg_name)
    pkg_mod.__path__ = [str(ROOT / "custom_components" / "panasonic_taiseia_local")]
    sys.modules[pkg_name] = pkg_mod


_stub_homeassistant()
sys.path.insert(0, str(ROOT / "custom_components"))

from panasonic_taiseia_local.const import (  # noqa: E402
    TYPE_AC,
    TYPE_AIR_CLEANER,
    TYPE_DEHUMIDIFIER,
    TYPE_REFRIGERATOR,
)
from panasonic_taiseia_local.probe_info import (  # noqa: E402
    decode_status_value,
    service_label,
    services_as_list,
    status_highlights,
)
from panasonic_taiseia_local.taiseia import ServiceInfo  # noqa: E402


class TypeAwareServiceLabelsTest(unittest.TestCase):
    def test_same_service_id_differs_by_device_type(self) -> None:
        self.assertEqual(service_label(0x02, TYPE_AC), "風量")
        self.assertEqual(service_label(0x02, TYPE_DEHUMIDIFIER), "時間到關")
        self.assertEqual(service_label(0x04, TYPE_AC), "室內溫度")
        self.assertEqual(service_label(0x04, TYPE_DEHUMIDIFIER), "濕度設定")
        self.assertEqual(service_label(0x00, TYPE_AC), "電源")
        self.assertEqual(service_label(0x00, TYPE_REFRIGERATOR), "冷凍庫溫設定")
        self.assertEqual(service_label(0x01, TYPE_AIR_CLEANER), "風量")

    def test_name_overrides_from_commandlist_win(self) -> None:
        self.assertEqual(
            service_label(
                0x0D,
                TYPE_DEHUMIDIFIER,
                name_overrides={0x0D: "nanoeX(脫臭)"},
            ),
            "nanoeX(脫臭)",
        )
        # ModelType variants (e.g. AC 0x08 = 濾網重置 on some models)
        self.assertEqual(
            service_label(0x08, TYPE_AC, name_overrides={0x08: "濾網重置"}),
            "濾網重置",
        )

    def test_services_as_list_uses_type_labels(self) -> None:
        services = {
            0x02: ServiceInfo(0x02, True, 0, 12),
            0x04: ServiceInfo(0x04, True, 0, 6),
        }
        lines = services_as_list(services, sa_type=TYPE_DEHUMIDIFIER)
        self.assertIn("0x02 時間到關 [讀寫] 0–12", lines)
        self.assertIn("0x04 濕度設定 [讀寫] 0–6", lines)

    def test_refrigerator_status_not_decoded_as_power(self) -> None:
        # App F657: 0x00 is setpoint enum, not power / not °C
        self.assertEqual(
            decode_status_value(TYPE_REFRIGERATOR, 0x00, "2"),
            "中",
        )
        self.assertEqual(
            decode_status_value(TYPE_REFRIGERATOR, 0x03, "238"),
            "-18°C",
        )
        self.assertEqual(
            decode_status_value(TYPE_AC, 0x00, "1"),
            "開",
        )

    def test_dehumidifier_humidity_set_maps_index(self) -> None:
        self.assertEqual(
            decode_status_value(TYPE_DEHUMIDIFIER, 0x04, "3"),
            "55%",
        )
        self.assertEqual(
            decode_status_value(TYPE_DEHUMIDIFIER, 0x07, "58"),
            "58%",
        )

    def test_air_cleaner_timer_is_minutes(self) -> None:
        self.assertEqual(
            decode_status_value(TYPE_AIR_CLEANER, 0x53, "60"),
            "60 分",
        )

    def test_status_highlights_are_type_specific(self) -> None:
        ac = status_highlights({"0x00": "1", "0x04": "26"}, TYPE_AC)
        self.assertIn("電源", ac)
        self.assertIn("室內溫度", ac)

        dh = status_highlights(
            {"0x00": "1", "0x04": "3", "0x07": "55"}, TYPE_DEHUMIDIFIER
        )
        self.assertIn("濕度設定", dh)
        self.assertEqual(dh["濕度設定"], "55%")
        self.assertNotIn("室內溫度", dh)

        rf = status_highlights({"0x00": "2", "0x03": "238"}, TYPE_REFRIGERATOR)
        self.assertIn("冷凍庫溫設定", rf)
        self.assertEqual(rf["冷凍庫溫設定"], "中")
        self.assertNotIn("電源", rf)


if __name__ == "__main__":
    unittest.main()
