"""AC power/current/energy entity classification tests.

Regression tests for devices like PXGD whose advertised service descriptors
report span 0 (255–255) for numeric telemetry services:
- 0x27 即時功率 must be a numeric sensor (W), not a binary_sensor.
- 0x24 室外機電流 must carry device_class hint current.
- 0x28 累計耗電 / 0x33 本月耗電 must carry energy hint (0.1 kWh counters);
  per-unit 耗電 (0x22/0x23) stays unitless.
- 功率因數/功率限制 must not be mislabeled as power.
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
    sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

    pkg_name = "panasonic_taiseia_local"
    if pkg_name not in sys.modules:
        pkg_mod = types.ModuleType(pkg_name)
        pkg_mod.__path__ = [str(ROOT / "custom_components" / "panasonic_taiseia_local")]
        sys.modules[pkg_name] = pkg_mod


_stub_homeassistant()
sys.path.insert(0, str(ROOT / "custom_components"))

from panasonic_taiseia_local import catalog  # noqa: E402
from panasonic_taiseia_local.catalog import (  # noqa: E402
    _command_from_device_service,
    _sensor_hint,
    classify_command,
    extra_local_sensors,
)
from panasonic_taiseia_local.const import TYPE_AC  # noqa: E402


class _Svc:
    """TaiSEIA service descriptor with span 0 (255–255), as PXGD reports."""

    def __init__(self, writable: bool = False):
        self.writable = writable
        self.min_value = 255
        self.max_value = 255


class SensorHintTest(unittest.TestCase):
    def test_current(self):
        self.assertEqual(_sensor_hint("室外機電流"), "current")

    def test_operating_power(self):
        self.assertEqual(_sensor_hint("即時功率"), "power")

    def test_energy_counters(self):
        self.assertEqual(_sensor_hint("累計耗電"), "energy")
        self.assertEqual(_sensor_hint("本月耗電"), "energy")
        self.assertEqual(_sensor_hint("本期耗電"), "energy")

    def test_per_unit_energy_stays_unitless(self):
        # 0x22/0x23 are undocumented constants on F-YV/PXGD models.
        self.assertIsNone(_sensor_hint("室內機耗電"))
        self.assertIsNone(_sensor_hint("室外機耗電"))

    def test_dimensionless_names_not_power(self):
        self.assertIsNone(_sensor_hint("室外機功率因數"))
        self.assertIsNone(_sensor_hint("功率限制"))


class DeviceServiceClassificationTest(unittest.TestCase):
    def test_table_has_operating_power(self):
        self.assertEqual(catalog._AC_SERVICE_KIND.get(0x27), "sensor")

    def test_span0_ro_power_is_numeric_sensor(self):
        cmd = _command_from_device_service(TYPE_AC, 0x27, _Svc(), name="即時功率")
        self.assertEqual(cmd.parameter_type, "")
        item = classify_command(cmd, TYPE_AC)
        self.assertEqual(item.kind, "sensor")
        self.assertEqual(item.device_class_hint, "power")

    def test_span0_writable_counter_is_energy_sensor(self):
        cmd = _command_from_device_service(
            TYPE_AC, 0x28, _Svc(writable=True), name="累計耗電"
        )
        item = classify_command(cmd, TYPE_AC)
        self.assertEqual(item.kind, "sensor")
        self.assertEqual(item.device_class_hint, "energy")

    def test_current_service_hint(self):
        cmd = _command_from_device_service(TYPE_AC, 0x24, _Svc(), name="室外機電流")
        item = classify_command(cmd, TYPE_AC)
        self.assertEqual(item.kind, "sensor")
        self.assertEqual(item.device_class_hint, "current")


class ExtraSensorsTest(unittest.TestCase):
    def test_ac_extras_hints(self):
        extras = {c.command.service: c for c in extra_local_sensors(TYPE_AC, None)}
        self.assertIsNone(extras[0x22].device_class_hint)
        self.assertIsNone(extras[0x23].device_class_hint)
        self.assertEqual(extras[0x24].device_class_hint, "current")
        self.assertEqual(extras[0x27].device_class_hint, "power")


if __name__ == "__main__":
    unittest.main()
