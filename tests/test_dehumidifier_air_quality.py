"""Dehumidifier air-quality services are readable despite the 0x07 advertisement.

F-YV32MH (MHW) advertises 12 services but answers 0x51/0x52/0x53/0x56 on LAN
reads; entities must be built and backfilled for them.
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
    sensor = pkg("homeassistant.components.sensor")
    backports = pkg("homeassistant.backports")
    enum = pkg("homeassistant.backports.enum")

    class StrEnum(str):
        pass

    enum.StrEnum = StrEnum
    ha.components = components
    components.climate = climate
    components.sensor = sensor
    ha.backports = backports
    backports.enum = enum


_stub_homeassistant()
sys.path.insert(0, str(ROOT / "custom_components"))

from panasonic_taiseia_local import catalog  # noqa: E402
from panasonic_taiseia_local.const import (  # noqa: E402
    PROBED_CORE_BY_TYPE,
    SVC_DH_ODOR,
    SVC_DH_PM_LEVEL,
    SVC_DH_PM10,
    SVC_DH_PM25,
    TYPE_DEHUMIDIFIER,
)


class _Svc:
    def __init__(self, sid: int):
        self.service = sid


class DehumidifierAirQualityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = catalog.build_profile("MHW")
        self.assertIsNotNone(self.profile)
        # Module advertisement (0x07 probe, F-YV32MH): 12 services, no AQ regs.
        advertised = (0x00, 0x01, 0x02, 0x04, 0x07, 0x09, 0x0A, 0x0D, 0x0E, 0x12, 0x18, 0x1D)
        self.services = {sid: None for sid in advertised}

    def test_advertisement_omits_air_quality_services(self) -> None:
        for sid in (SVC_DH_ODOR, SVC_DH_PM_LEVEL, SVC_DH_PM25, SVC_DH_PM10):
            self.assertNotIn(sid, self.services)

    def test_probed_core_gate_allows_reads_and_entities(self) -> None:
        for sid in (SVC_DH_ODOR, SVC_DH_PM_LEVEL, SVC_DH_PM25, SVC_DH_PM10):
            self.assertIn(sid, PROBED_CORE_BY_TYPE[TYPE_DEHUMIDIFIER])
            self.assertTrue(
                catalog.service_allowed(self.services, sid, TYPE_DEHUMIDIFIER)
            )

    def test_gate_still_blocks_unknown_services(self) -> None:
        self.assertFalse(
            catalog.service_allowed(self.services, 0x61, TYPE_DEHUMIDIFIER)
        )

    def test_extra_sensors_built_for_pm_values(self) -> None:
        extras = catalog.extra_local_sensors(TYPE_DEHUMIDIFIER, self.profile)
        by_sid = {e.command.service: e for e in extras}
        self.assertIn(SVC_DH_PM25, by_sid)
        self.assertIn(SVC_DH_PM10, by_sid)
        self.assertEqual(by_sid[SVC_DH_PM25].device_class_hint, "pm25")
        self.assertEqual(by_sid[SVC_DH_PM10].device_class_hint, "pm10")

    def test_odor_and_pm_level_come_from_command_list_profile(self) -> None:
        classified = {c.command.service: c for c in self.profile.classified}
        self.assertIn(SVC_DH_ODOR, classified)
        self.assertEqual(classified[SVC_DH_ODOR].kind, "sensor")


if __name__ == "__main__":
    unittest.main()
