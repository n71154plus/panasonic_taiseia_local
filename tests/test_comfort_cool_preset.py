"""Comfort-cool (舒適冷房, 0x01=5) as climate preset — issue #19.

HA climate HVACMode cannot express manufacturer modes. Power-on with mode 5
must still report cool (not OFF), and VX/UX expose preset ``comfort``.
"""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
        TURN_ON=1,
        TURN_OFF=2,
        TARGET_TEMPERATURE=16,
        FAN_MODE=8,
        SWING_MODE=32,
        PRESET_MODE=4,
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

    class _CoordinatorEntity:
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

from panasonic_taiseia_local.catalog import (  # noqa: E402
    DeviceProfile,
    build_profile,
    climate_hvac_mappings,
    climate_preset_codes,
)
from panasonic_taiseia_local.climate import TaiSeiaClimate  # noqa: E402
from panasonic_taiseia_local.const import (  # noqa: E402
    AC_MODE_COMFORT_COOL,
    CLIMATE_PRESET_COMFORT,
    CLIMATE_PRESET_NONE,
    STATUS_MODE,
    STATUS_POWER,
    SVC_MODE,
    SVC_POWER,
)


class _FakeDevice:
    def __init__(self) -> None:
        self.services: dict = {}
        self.unique_id = "test"
        self.sa_model = "VX"
        self.host = "127.0.0.1"
        self.port = 57223
        self.mac = ""
        self.manufacturer = "Panasonic"
        self.model_number = ""
        self.model_name = ""
        self.sw_version = ""
        self.sa_type_id = 1


class _FakeClient:
    host = "127.0.0.1"

    def __init__(self) -> None:
        self.device = _FakeDevice()
        self.writes: list[tuple[int, int]] = []

    def has_service(self, service: int) -> bool:
        return service in self.device.services

    def service_range(self, service: int):
        return (16, 30)

    async def async_write_device(self, service: int, value: int) -> int:
        self.writes.append((service, value))
        return value


class _FakeCoordinator:
    def __init__(self, status: dict) -> None:
        self.data = {"status": dict(status), "name": "書房冷氣"}

    def update_local_state(self, key: str, value) -> None:
        self.data.setdefault("status", {})[key] = value

    def async_set_updated_data(self, data) -> None:
        self.data = data


def _vx_profile() -> DeviceProfile:
    profile = build_profile("VX")
    assert profile is not None
    return profile


def _make_climate(status: dict, *, profile=None) -> TaiSeiaClimate:
    entity = TaiSeiaClimate.__new__(TaiSeiaClimate)
    entity.coordinator = _FakeCoordinator(status)
    entity.client = _FakeClient()
    entity.entry_id = "test"
    entity._profile = profile
    entity._attr_unique_id = "test_climate"
    entity.hass = SimpleNamespace(data={})
    entity.async_write_ha_state = lambda: None  # type: ignore[method-assign]
    return entity


class ComfortCoolStatusTest(unittest.TestCase):
    def test_powered_comfort_cool_reports_cool_not_off(self) -> None:
        entity = _make_climate(
            {STATUS_POWER: "1", STATUS_MODE: str(AC_MODE_COMFORT_COOL)}
        )
        self.assertEqual(entity.hvac_mode, "cool")
        self.assertNotEqual(entity.hvac_mode, "off")

    def test_preset_is_comfort_when_mode_5(self) -> None:
        entity = _make_climate(
            {STATUS_POWER: "1", STATUS_MODE: str(AC_MODE_COMFORT_COOL)},
            profile=_vx_profile(),
        )
        self.assertEqual(entity.preset_mode, CLIMATE_PRESET_COMFORT)
        self.assertIn(CLIMATE_PRESET_COMFORT, entity.preset_modes)

    def test_attributes_expose_mode_label(self) -> None:
        entity = _make_climate(
            {STATUS_POWER: "1", STATUS_MODE: str(AC_MODE_COMFORT_COOL)},
            profile=_vx_profile(),
        )
        attrs = entity.extra_state_attributes
        self.assertEqual(attrs["mode_code"], 5)
        self.assertEqual(attrs["mode_label"], "舒適冷房")

    def test_unknown_powered_mode_not_off(self) -> None:
        entity = _make_climate({STATUS_POWER: "1", STATUS_MODE: "9"})
        self.assertEqual(entity.hvac_mode, "cool")


class ComfortCoolControlTest(unittest.TestCase):
    def test_set_preset_comfort_writes_code_5(self) -> None:
        entity = _make_climate(
            {STATUS_POWER: "1", STATUS_MODE: "0"}, profile=_vx_profile()
        )
        entity.async_device_write = AsyncMock(  # type: ignore[method-assign]
            side_effect=entity.client.async_write_device
        )
        asyncio.run(entity.async_set_preset_mode(CLIMATE_PRESET_COMFORT))
        self.assertEqual(entity.client.writes, [(SVC_MODE, AC_MODE_COMFORT_COOL)])

    def test_clear_preset_writes_standard_cool(self) -> None:
        entity = _make_climate(
            {STATUS_POWER: "1", STATUS_MODE: str(AC_MODE_COMFORT_COOL)},
            profile=_vx_profile(),
        )
        entity.async_device_write = AsyncMock(  # type: ignore[method-assign]
            side_effect=entity.client.async_write_device
        )
        asyncio.run(entity.async_set_preset_mode(CLIMATE_PRESET_NONE))
        self.assertEqual(entity.client.writes, [(SVC_MODE, 0)])

    def test_turn_on_resumes_comfort_cool_raw_code(self) -> None:
        entity = _make_climate(
            {STATUS_POWER: "0", STATUS_MODE: str(AC_MODE_COMFORT_COOL)},
            profile=_vx_profile(),
        )
        entity.async_device_write = AsyncMock(  # type: ignore[method-assign]
            side_effect=entity.client.async_write_device
        )
        asyncio.run(entity.async_turn_on())
        self.assertEqual(
            entity.client.writes,
            [(SVC_MODE, AC_MODE_COMFORT_COOL), (SVC_POWER, 1)],
        )

    def test_gx_without_catalog_preset_hides_comfort(self) -> None:
        # No profile and not currently in mode 5 → no comfort preset.
        entity = _make_climate({STATUS_POWER: "1", STATUS_MODE: "0"}, profile=None)
        self.assertEqual(entity.preset_modes, [CLIMATE_PRESET_NONE])


class CatalogComfortCoolTest(unittest.TestCase):
    def test_vx_catalog_lists_preset_not_hvac(self) -> None:
        profile = _vx_profile()
        presets = climate_preset_codes(profile)
        self.assertEqual(presets.get(5), "舒適冷房")
        hvac_codes = {m["mappingCode"] for m in climate_hvac_mappings(profile)}
        self.assertNotIn(5, hvac_codes)
        self.assertIn(0, hvac_codes)


if __name__ == "__main__":
    unittest.main()
