"""Regression tests: wrong-type ModelType must not change the appliance kind.

Real-world report: a washing machine (SA type 0x03) was set up as a
dehumidifier because its cloud ModelType string collided with a dehumidifier
CommandList code and resolve_model_type accepted it blindly.
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
    build_generic_profile,
    load_catalog,
    model_type_matches_device,
    resolve_model_type,
)
from panasonic_taiseia_local.const import (  # noqa: E402
    TYPE_AC,
    TYPE_DEHUMIDIFIER,
    TYPE_WASHING_MACHINE,
)
from panasonic_taiseia_local.probe_info import service_label  # noqa: E402


class ResolveModelTypeGuardTest(unittest.TestCase):
    def test_dehumidifier_code_rejected_for_washing_machine(self) -> None:
        # Every dehumidifier catalog code must be rejected for SA type 0x03,
        # then the washer default (MDH) wins.
        for mt, info in load_catalog().items():
            if info["DeviceType"] != TYPE_DEHUMIDIFIER:
                continue
            self.assertEqual(
                resolve_model_type(mt, TYPE_WASHING_MACHINE),
                "MDH",
                f"{mt} (dehumidifier) must not stick; washer default MDH expected",
            )

    def test_explicit_wrong_type_is_rejected(self) -> None:
        # Persisted CONF_MODEL_TYPE from older versions may be wrong too:
        # the wrong code is skipped and the per-type default wins instead.
        self.assertEqual(resolve_model_type("JHW", TYPE_AC), "PXGD")
        self.assertEqual(resolve_model_type("PXGD", TYPE_DEHUMIDIFIER), "JHW")

    def test_matching_type_still_resolves(self) -> None:
        self.assertEqual(resolve_model_type("JHW", TYPE_DEHUMIDIFIER), "JHW")
        self.assertEqual(resolve_model_type("PXGD", TYPE_AC), "PXGD")
        # Defaults per SA type keep working.
        self.assertEqual(resolve_model_type(None, TYPE_AC), "PXGD")
        self.assertEqual(resolve_model_type(None, TYPE_DEHUMIDIFIER), "JHW")

    def test_washing_machine_has_no_default(self) -> None:
        self.assertEqual(resolve_model_type(None, TYPE_WASHING_MACHINE), "MDH")

    def test_model_type_matches_device(self) -> None:
        self.assertTrue(model_type_matches_device("JHW", TYPE_DEHUMIDIFIER))
        self.assertFalse(model_type_matches_device("JHW", TYPE_WASHING_MACHINE))
        self.assertTrue(model_type_matches_device("MDH", TYPE_WASHING_MACHINE))
        self.assertTrue(model_type_matches_device("HDH", TYPE_WASHING_MACHINE))
        self.assertFalse(model_type_matches_device("not-a-code", TYPE_AC))
        # Unknown SA type (0) must refuse catalog codes (would guess wrong).
        self.assertFalse(model_type_matches_device("JHW", 0))
        self.assertFalse(model_type_matches_device("MDH", 0))


class WashingMachineProfileTest(unittest.TestCase):
    def test_generic_profile_keeps_sa_type(self) -> None:
        profile = build_generic_profile(TYPE_WASHING_MACHINE, {})
        self.assertEqual(profile.device_type, TYPE_WASHING_MACHINE)
        self.assertEqual(profile.device_name, "洗衣機")

    def test_mdh_profile_from_catalog(self) -> None:
        from panasonic_taiseia_local.catalog import build_profile

        profile = build_profile("MDH")
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.device_type, TYPE_WASHING_MACHINE)
        names = {c.service: c.name for c in profile.commands}
        self.assertEqual(names[0x01], "開始洗衣")
        self.assertEqual(names[0x50], "運轉情報")
        self.assertEqual(names[0x55], "行程別訊息")
        # Must not look like dehumidifier services
        self.assertNotEqual(names.get(0x04), "濕度設定")

    def test_labels_use_washer_table(self) -> None:
        self.assertEqual(service_label(0x04, TYPE_WASHING_MACHINE), "服務 0x04")
        self.assertEqual(service_label(0x01, TYPE_WASHING_MACHINE), "開始洗衣")
        self.assertEqual(service_label(0x50, TYPE_WASHING_MACHINE), "運轉情報")
        # AC keeps its own labels untouched.
        self.assertEqual(service_label(0x04, TYPE_AC), "室內溫度")


if __name__ == "__main__":
    unittest.main()
