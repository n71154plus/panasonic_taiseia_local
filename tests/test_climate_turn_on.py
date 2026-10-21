"""Regression: climate.turn_on must resume the last mode, not default to heat.

HA core's ClimateEntity default turn_on picks the first supported mode in a
fixed (heat_cool, heat, cool) order, so an AC whose device supports heat but
not heat_cool always starts in heat. See home-assistant/core#181909: the core
team expects integrations to own this behaviour.
"""

from __future__ import annotations

import asyncio
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
    climate.ClimateEntity = object
    climate.ClimateEntityFeature = types.SimpleNamespace(
        TURN_ON=1, TURN_OFF=2, TARGET_TEMPERATURE=16, FAN_MODE=8, SWING_MODE=32
    )
    ha.components = components
    components.climate = climate

    const = pkg("homeassistant.const")
    const.ATTR_TEMPERATURE = "temperature"
    const.UnitOfTemperature = types.SimpleNamespace(CELSIUS="°C")
    ha.const = const

    exceptions = pkg("homeassistant.exceptions")
    exceptions.HomeAssistantError = Exception
    ha.exceptions = exceptions

    helpers = pkg("homeassistant.helpers")
    update_coordinator = pkg("homeassistant.helpers.update_coordinator")

    class _CoordinatorEntity:  # real-enough base for MRO with ABC
        def __init__(self, coordinator=None) -> None:
            self.coordinator = coordinator

    update_coordinator.CoordinatorEntity = _CoordinatorEntity
    helpers.update_coordinator = update_coordinator
    device_registry = pkg("homeassistant.helpers.device_registry")
    device_registry.CONNECTION_NETWORK_MAC = "mac"
    helpers.device_registry = device_registry

    sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

    pkg_name = "panasonic_taiseia_local"
    pkg_mod = types.ModuleType(pkg_name)
    pkg_mod.__path__ = [str(ROOT / "custom_components" / "panasonic_taiseia_local")]
    sys.modules[pkg_name] = pkg_mod


_stub_homeassistant()
sys.path.insert(0, str(ROOT / "custom_components"))

from panasonic_taiseia_local.climate import TaiSeiaClimate  # noqa: E402
from panasonic_taiseia_local.const import STATUS_MODE, STATUS_POWER  # noqa: E402


class _FakeDevice:
    services: dict = {}


class _FakeClient:
    host = "127.0.0.1"

    def __init__(self) -> None:
        self.device = _FakeDevice()

    def has_service(self, service: int) -> bool:
        return False

    def service_range(self, service: int):
        return (16, 30)


class _FakeCoordinator:
    def __init__(self, status: dict) -> None:
        self.data = {"status": status, "name": "TEST"}


def _make_climate(status: dict) -> TaiSeiaClimate:
    entity = TaiSeiaClimate.__new__(TaiSeiaClimate)
    entity.coordinator = _FakeCoordinator(status)
    entity.client = _FakeClient()
    entity.entry_id = "test"
    entity._profile = None
    entity._attr_unique_id = "test_climate"
    return entity


def _capture_set_mode(entity: TaiSeiaClimate) -> list:
    calls: list = []

    async def fake_set_hvac_mode(hvac_mode) -> None:
        calls.append(hvac_mode)

    entity.async_set_hvac_mode = fake_set_hvac_mode  # type: ignore[method-assign]
    return calls


class TurnOnModeTest(unittest.TestCase):
    def test_turn_on_resumes_last_cool_mode(self) -> None:
        # Powered off (power=0) but the mode register still says cool (0).
        entity = _make_climate({STATUS_POWER: "0", STATUS_MODE: "0"})
        calls = _capture_set_mode(entity)
        asyncio.run(entity.async_turn_on())
        self.assertEqual(calls, ["cool"])

    def test_turn_on_resumes_last_heat_mode(self) -> None:
        entity = _make_climate({STATUS_POWER: "0", STATUS_MODE: "4"})
        calls = _capture_set_mode(entity)
        asyncio.run(entity.async_turn_on())
        self.assertEqual(calls, ["heat"])

    def test_turn_on_falls_back_to_cool_without_mode_history(self) -> None:
        # No mode register at all: must NOT default to heat like the core does.
        entity = _make_climate({STATUS_POWER: "0"})
        calls = _capture_set_mode(entity)
        asyncio.run(entity.async_turn_on())
        self.assertEqual(calls, ["cool"])

    def test_turn_on_ignores_off_mapping_code(self) -> None:
        # Mode register reads -1 (off sentinel): fall through to cool.
        entity = _make_climate({STATUS_POWER: "0", STATUS_MODE: "-1"})
        calls = _capture_set_mode(entity)
        asyncio.run(entity.async_turn_on())
        self.assertEqual(calls, ["cool"])

    def test_resume_mode_requires_supported_mode(self) -> None:
        # Mode register says heat (4) but the device profile here supports
        # heat; sanity-check that the resolved mode is always in hvac_modes.
        entity = _make_climate({STATUS_POWER: "0", STATUS_MODE: "4"})
        self.assertIn(entity._resume_mode(), entity.hvac_modes)


if __name__ == "__main__":
    unittest.main()
