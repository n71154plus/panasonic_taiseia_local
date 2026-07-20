"""Tests for App enum → HA entity kind classification."""

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
    _is_toggle_enum,
    build_profile,
    parse_enum_params,
)


class EntityKindFixTest(unittest.TestCase):
    def test_stop_start_is_toggle(self) -> None:
        om = parse_enum_params([["停止", 0], ["啟動", 1]])
        self.assertTrue(_is_toggle_enum(om))

    def test_eco_and_defrost_are_toggle(self) -> None:
        self.assertTrue(
            _is_toggle_enum(parse_enum_params([["通常", 0], ["運作中", 1]]))
        )
        self.assertTrue(
            _is_toggle_enum(parse_enum_params([["通常", 0], ["除霜中", 1]]))
        )

    def test_weak_mid_strong_not_toggle(self) -> None:
        om = parse_enum_params([["弱", 0], ["中", 2], ["強", 4]])
        self.assertFalse(_is_toggle_enum(om))

    def test_f657_ice_and_eco_are_switches(self) -> None:
        profile = build_profile("F657")
        assert profile is not None
        kinds = {
            item.command.service: item.kind for item in profile.classified
        }
        self.assertEqual(kinds[0x52], "switch")  # 製冰停止
        self.assertEqual(kinds[0x53], "switch")  # 快速製冰
        self.assertEqual(kinds[0x0C], "switch")  # ECO
        self.assertEqual(kinds[0x50], "switch")  # 除霜
        # multi-state stay select
        self.assertEqual(kinds[0x00], "select")  # 冷凍庫溫
        self.assertEqual(kinds[0x56], "select")  # 新鮮急凍結
        self.assertEqual(kinds[0x5A], "select")  # 冬季模式 3態

    def test_jhw_ai_comfort_binary(self) -> None:
        profile = build_profile("JHW")
        assert profile is not None
        kinds = {
            item.command.service: item.kind for item in profile.classified
        }
        self.assertEqual(kinds[0x58], "binary_sensor")  # AI舒適
        self.assertEqual(kinds[0x0A], "binary_sensor")  # 滿水
        self.assertEqual(kinds[0x51], "sensor")  # 異味偵測（可能為等級）


if __name__ == "__main__":
    unittest.main()
