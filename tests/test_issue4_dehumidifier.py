"""Regression tests for GitHub issue #4 (LXW cloud lock + NXW modes)."""

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

from panasonic_taiseia_local.capability import filter_option_map  # noqa: E402
from panasonic_taiseia_local.catalog import (  # noqa: E402
    build_profile,
    dehumidifier_mode_map,
    get_command,
    parse_enum_params,
)
from panasonic_taiseia_local.const import (  # noqa: E402
    DEHUMIDIFIER_AVAILABLE_MODE,
    TYPE_DEHUMIDIFIER,
)
from panasonic_taiseia_local.taiseia import ServiceInfo  # noqa: E402


class Issue4DehumidifierCatalogTest(unittest.TestCase):
    def test_nxw_lxw_are_dehumidifiers(self) -> None:
        for mt in ("NXW", "LXW"):
            profile = build_profile(mt)
            assert profile is not None
            self.assertEqual(profile.device_type, TYPE_DEHUMIDIFIER)

    def test_nxw_mode_map_includes_panel_modes(self) -> None:
        profile = build_profile("NXW")
        modes = dehumidifier_mode_map(profile)
        assert modes is not None
        self.assertEqual(modes[0], "連續除濕")
        self.assertEqual(modes[1], "智慧節能")
        self.assertEqual(modes[2], "防霉抑菌")
        self.assertEqual(modes[4], "衣物乾燥")
        self.assertEqual(modes[5], "保持乾燥")
        self.assertEqual(modes[6], "濕度設定")
        self.assertEqual(modes[7], "送風")

    def test_lxw_mode_map_matches_nxw_panel_labels(self) -> None:
        nxw = dehumidifier_mode_map(build_profile("NXW"))
        lxw = dehumidifier_mode_map(build_profile("LXW"))
        self.assertEqual(nxw, lxw)

    def test_nxw_fan_shortcut_labels(self) -> None:
        profile = build_profile("NXW")
        assert profile is not None
        fan = get_command(profile, 0x0E)
        assert fan is not None
        labels = parse_enum_params(fan.parameters)
        self.assertEqual(labels[1], "靜音除濕")
        self.assertEqual(labels[3], "快速除濕")

    def test_jhw_keeps_air_clean_label(self) -> None:
        modes = dehumidifier_mode_map(build_profile("JHW"))
        assert modes is not None
        self.assertEqual(modes[7], "空氣清淨")
        self.assertIn(2, modes)
        self.assertEqual(modes[2], "防霉抑菌")

    def test_fallback_mode_map_has_fan_only(self) -> None:
        self.assertEqual(DEHUMIDIFIER_AVAILABLE_MODE[7], "送風")

    def test_capability_filters_unsupported_modes(self) -> None:
        profile = build_profile("NXW")
        base = dehumidifier_mode_map(profile)
        assert base is not None
        # TaiSEIA bitmask maxima are 1/3/7/15/…; 15 ⇒ values 0–3 only.
        client = SimpleNamespace(
            device=SimpleNamespace(services={0x01: ServiceInfo(0x01, True, 0, 15)})
        )
        filtered = filter_option_map(client, 0x01, base)
        self.assertIn(0, filtered)
        self.assertIn(1, filtered)
        self.assertIn(2, filtered)
        self.assertNotIn(4, filtered)
        self.assertNotIn(7, filtered)

    def test_capability_exposes_extra_bits(self) -> None:
        profile = build_profile("NXW")
        base = dehumidifier_mode_map(profile)
        assert base is not None
        # 255 ⇒ bits 0–7, including 防霉抑菌 (2) and 送風 (7).
        client = SimpleNamespace(
            device=SimpleNamespace(services={0x01: ServiceInfo(0x01, True, 0, 255)})
        )
        filtered = filter_option_map(client, 0x01, base)
        self.assertEqual(filtered[2], "防霉抑菌")
        self.assertEqual(filtered[7], "送風")


if __name__ == "__main__":
    unittest.main()
