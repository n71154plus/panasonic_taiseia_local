"""Regression: multi-appliance CommandList / type guard coverage.

Covers dryer, ERV, air cleaner, smart switch, weight plate, living-space
controller — same DeviceType-consistency rules as washing machines.
"""

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
    list_model_types,
    resolve_model_type,
)
from panasonic_taiseia_local.const import (  # noqa: E402
    DEVICE_TYPE_NAMES,
    TYPE_AC,
    TYPE_AIR_CLEANER,
    TYPE_DEHUMIDIFIER,
    TYPE_DRYING_MACHINE,
    TYPE_FULL_HEAT_EXCHANGER,
    TYPE_LAMP,
    TYPE_LIVING_SPACE_CONTROLLER,
    TYPE_WASHING_MACHINE,
    TYPE_WEIGHT_PLATE,
)
from panasonic_taiseia_local.probe_info import service_label  # noqa: E402


class MultiApplianceCatalogTest(unittest.TestCase):
    def test_catalog_has_expected_model_types(self) -> None:
        self.assertIn("CN-HP", list_model_types(TYPE_DRYING_MACHINE))
        self.assertIn("FYZY", list_model_types(TYPE_FULL_HEAT_EXCHANGER))
        self.assertIn("LHW", list_model_types(TYPE_AIR_CLEANER))
        self.assertIn("WTY", list_model_types(TYPE_LAMP))
        self.assertIn("WTYF", list_model_types(TYPE_LAMP))
        self.assertIn("PZE1", list_model_types(TYPE_WEIGHT_PLATE))
        self.assertIn("CSC", list_model_types(TYPE_LIVING_SPACE_CONTROLLER))

    def test_defaults_resolve(self) -> None:
        self.assertEqual(resolve_model_type(None, TYPE_DRYING_MACHINE), "CN-HP")
        self.assertEqual(resolve_model_type(None, TYPE_FULL_HEAT_EXCHANGER), "FYZY")
        self.assertEqual(resolve_model_type(None, TYPE_AIR_CLEANER), "LHW")
        self.assertEqual(resolve_model_type(None, TYPE_LAMP), "WTY")
        self.assertEqual(resolve_model_type(None, TYPE_WEIGHT_PLATE), "PZE1")
        self.assertEqual(resolve_model_type(None, TYPE_LIVING_SPACE_CONTROLLER), "CSC")

    def test_wrong_type_rejected(self) -> None:
        # Dehumidifier code must not stick on a dryer / ERV / switch.
        self.assertEqual(resolve_model_type("JHW", TYPE_DRYING_MACHINE), "CN-HP")
        self.assertEqual(resolve_model_type("JHW", TYPE_FULL_HEAT_EXCHANGER), "FYZY")
        self.assertEqual(resolve_model_type("JHW", TYPE_LAMP), "WTY")
        self.assertEqual(resolve_model_type("FYZY", TYPE_DEHUMIDIFIER), "JHW")

    def test_dryer_command_names(self) -> None:
        profile = build_profile("CN-HP")
        assert profile is not None
        self.assertEqual(profile.device_type, TYPE_DRYING_MACHINE)
        names = {c.service: c.name for c in profile.commands}
        self.assertEqual(names[0x00], "電源")
        self.assertEqual(names[0x01], "運轉狀態")
        self.assertEqual(names[0x03], "運轉模式")
        self.assertNotEqual(names.get(0x04), "濕度設定")

    def test_erv_command_names(self) -> None:
        profile = build_profile("FYZY")
        assert profile is not None
        self.assertEqual(profile.device_type, TYPE_FULL_HEAT_EXCHANGER)
        names = {c.service: c.name for c in profile.commands}
        self.assertEqual(names[0x00], "運轉狀態")
        self.assertEqual(names[0x15], "換氣模式")
        self.assertEqual(names[0x56], "風量")

    def test_switch_command_names(self) -> None:
        wty = build_profile("WTY")
        wtyf = build_profile("WTYF")
        assert wty is not None and wtyf is not None
        self.assertEqual(wty.device_type, TYPE_LAMP)
        self.assertEqual({c.service: c.name for c in wty.commands}[0x70], "全狀態查詢")
        self.assertEqual({c.service: c.name for c in wtyf.commands}[0x01], "亮度")

    def test_weight_plate_command_names(self) -> None:
        profile = build_profile("PZE1")
        assert profile is not None
        self.assertEqual(profile.device_type, TYPE_WEIGHT_PLATE)
        names = {c.service: c.name for c in profile.commands}
        self.assertEqual(names[0x52], "取得重量")
        self.assertEqual(names[0x8C], "總重量")
        self.assertEqual(names[0x8E], "電量不足")

    def test_labels_are_type_specific(self) -> None:
        self.assertEqual(service_label(0x15, TYPE_FULL_HEAT_EXCHANGER), "換氣模式")
        self.assertEqual(service_label(0x15, TYPE_WASHING_MACHINE), "預約殘時間")
        self.assertEqual(service_label(0x70, TYPE_LAMP), "全狀態查詢")
        self.assertEqual(service_label(0x70, TYPE_AC), "服務 0x70")
        self.assertEqual(DEVICE_TYPE_NAMES[TYPE_DRYING_MACHINE], "乾衣機")
        self.assertEqual(DEVICE_TYPE_NAMES[TYPE_LAMP], "智慧開關")
        self.assertEqual(DEVICE_TYPE_NAMES[TYPE_WEIGHT_PLATE], "重量檢知盤")
        self.assertEqual(
            DEVICE_TYPE_NAMES[TYPE_LIVING_SPACE_CONTROLLER], "住空間控制器"
        )


if __name__ == "__main__":
    unittest.main()
