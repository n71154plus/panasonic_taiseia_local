"""Operating watts count only while the indoor unit itself is on."""

from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
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
    core = pkg("homeassistant.core")

    class HomeAssistant:
        pass

    core.HomeAssistant = HomeAssistant
    helpers = pkg("homeassistant.helpers")
    storage = pkg("homeassistant.helpers.storage")

    class Store:
        pass

    storage.Store = Store
    helpers.storage = storage

    pkg_name = "panasonic_taiseia_local"
    pkg_mod = types.ModuleType(pkg_name)
    pkg_mod.__path__ = [str(ROOT / "custom_components" / "panasonic_taiseia_local")]
    sys.modules[pkg_name] = pkg_mod


_stub_homeassistant()
sys.path.insert(0, str(ROOT / "custom_components"))

from panasonic_taiseia_local.energy import (  # noqa: E402
    EnergyTracker,
    billable_operating_power,
)


class BillablePowerTests(unittest.TestCase):
    def test_off_indoor_drops_shared_outdoor_watts(self) -> None:
        self.assertEqual(billable_operating_power(420.0, "0"), 0.0)
        self.assertEqual(billable_operating_power(27.0, 0), 0.0)

    def test_on_indoor_keeps_outdoor_watts(self) -> None:
        self.assertEqual(billable_operating_power(420.0, "1"), 420.0)

    def test_missing_switch_keeps_reading(self) -> None:
        self.assertEqual(billable_operating_power(27.0, None), 27.0)
        self.assertIsNone(billable_operating_power(None, None))

    def test_turning_off_stops_later_intervals(self) -> None:
        tracker = EnergyTracker()
        start = datetime(2026, 10, 20, 13, 0, tzinfo=timezone.utc)
        tracker.update(billable_operating_power(400.0, "1"), start)
        tracker.update(
            billable_operating_power(400.0, "0"), start + timedelta(hours=1)
        )
        after_on = tracker.period_kwh
        self.assertAlmostEqual(after_on, 0.4, places=3)
        tracker.update(
            billable_operating_power(400.0, "0"), start + timedelta(hours=2)
        )
        self.assertAlmostEqual(tracker.period_kwh, after_on, places=3)


if __name__ == "__main__":
    unittest.main()
