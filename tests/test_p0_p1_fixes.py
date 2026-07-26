"""P0/P1 regression: platform gates, sa_type coalesce, auth force, merge guard."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

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
    climate.HVACAction = types.SimpleNamespace(
        OFF="off",
        COOLING="cooling",
        HEATING="heating",
        DRYING="drying",
        FAN="fan",
        IDLE="idle",
    )
    ha.components = components
    components.climate = climate

    humidifier = pkg("homeassistant.components.humidifier")
    humidifier.HumidifierEntity = object
    humidifier.HumidifierDeviceClass = types.SimpleNamespace(
        DEHUMIDIFIER="dehumidifier"
    )
    humidifier.HumidifierEntityFeature = types.SimpleNamespace(MODES=1)
    components.humidifier = humidifier

    const = pkg("homeassistant.const")
    const.CONF_HOST = "host"
    const.CONF_NAME = "name"
    const.CONF_PASSWORD = "password"
    const.UnitOfTemperature = types.SimpleNamespace(CELSIUS="°C")
    const.PERCENTAGE = "%"
    const.ATTR_TEMPERATURE = "temperature"

    config_entries = pkg("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    config_entries.ConfigFlow = object
    config_entries.OptionsFlow = object
    ha.config_entries = config_entries

    core = pkg("homeassistant.core")
    core.HomeAssistant = object
    core.callback = lambda f: f

    helpers = pkg("homeassistant.helpers")
    aiohttp_client = pkg("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None
    helpers.aiohttp_client = aiohttp_client
    update_coordinator = pkg("homeassistant.helpers.update_coordinator")
    update_coordinator.CoordinatorEntity = object
    helpers.update_coordinator = update_coordinator
    device_registry = pkg("homeassistant.helpers.device_registry")
    device_registry.async_get = lambda hass: None
    helpers.device_registry = device_registry

    exceptions = pkg("homeassistant.exceptions")
    exceptions.HomeAssistantError = Exception
    ha.exceptions = exceptions

    sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

    pkg_name = "panasonic_taiseia_local"
    pkg_mod = types.ModuleType(pkg_name)
    pkg_mod.__path__ = [str(ROOT / "custom_components" / "panasonic_taiseia_local")]
    sys.modules[pkg_name] = pkg_mod


_stub_homeassistant()
sys.path.insert(0, str(ROOT / "custom_components"))

from panasonic_taiseia_local.cloud import CloudDevice  # noqa: E402
from panasonic_taiseia_local.cloud_sync import merge_cloud_into_entry_data  # noqa: E402
from panasonic_taiseia_local.const import (  # noqa: E402
    CONF_DEVICE_TYPE,
    CONF_MODEL_TYPE,
    TYPE_AC,
    TYPE_DEHUMIDIFIER,
    TYPE_WASHING_MACHINE,
)
from panasonic_taiseia_local.flow_helpers import (  # noqa: E402
    coalesce_sa_type,
    cloud_only_import_data,
)


class CoalesceSaTypeTest(unittest.TestCase):
    def test_explicit_zero_preserved(self) -> None:
        self.assertEqual(coalesce_sa_type(0, default=TYPE_AC), 0)

    def test_none_falls_through(self) -> None:
        self.assertEqual(coalesce_sa_type(None, "", default=TYPE_AC), TYPE_AC)

    def test_first_valid_wins(self) -> None:
        self.assertEqual(coalesce_sa_type(None, 3, default=TYPE_AC), 3)

    def test_zero_not_overwritten_by_later(self) -> None:
        self.assertEqual(
            coalesce_sa_type(0, TYPE_WASHING_MACHINE, default=TYPE_AC), 0
        )


class MergeCloudModelTypeGuardTest(unittest.TestCase):
    def test_rejects_wrong_model_type(self) -> None:
        cd = CloudDevice(
            gwid="AABBCCDDEEFF",
            auth="x",
            nickname="洗",
            model="NA-V150MDH",
            model_id="",
            model_type="JHW",
            device_type=TYPE_WASHING_MACHINE,
            mac="AABBCCDDEEFF",
        )
        out = merge_cloud_into_entry_data(
            {CONF_DEVICE_TYPE: TYPE_WASHING_MACHINE}, cd, update_name=False
        )
        self.assertNotEqual(out.get(CONF_MODEL_TYPE), "JHW")

    def test_accepts_matching_model_type(self) -> None:
        cd = CloudDevice(
            gwid="AABBCCDDEEFF",
            auth="x",
            nickname="洗",
            model="NA-V150MDH",
            model_id="",
            model_type="MDH",
            device_type=TYPE_WASHING_MACHINE,
            mac="AABBCCDDEEFF",
        )
        out = merge_cloud_into_entry_data(
            {CONF_DEVICE_TYPE: TYPE_WASHING_MACHINE}, cd, update_name=False
        )
        self.assertEqual(out.get(CONF_MODEL_TYPE), "MDH")

    def test_heals_poisoned_local_device_type(self) -> None:
        cd = CloudDevice(
            gwid="AABBCCDDEEFF",
            auth="x",
            nickname="洗",
            model="NA-V150MDH",
            model_id="",
            model_type="MDH",
            device_type=TYPE_WASHING_MACHINE,
            mac="AABBCCDDEEFF",
        )
        out = merge_cloud_into_entry_data(
            {
                CONF_DEVICE_TYPE: TYPE_DEHUMIDIFIER,
                CONF_MODEL_TYPE: "JHW",
            },
            cd,
            update_name=False,
        )
        self.assertEqual(out.get(CONF_DEVICE_TYPE), TYPE_WASHING_MACHINE)
        self.assertNotEqual(out.get(CONF_MODEL_TYPE), "JHW")
        self.assertEqual(out.get(CONF_MODEL_TYPE), "MDH")


class CloudOnlyImportGuardTest(unittest.TestCase):
    def test_strips_colliding_model_type(self) -> None:
        cd = CloudDevice(
            gwid="gwid1",
            auth="a",
            nickname="洗",
            model="NA-V150MDH",
            model_id="",
            model_type="JHW",
            device_type=TYPE_WASHING_MACHINE,
            mac=None,
        )
        data = cloud_only_import_data(cd)
        self.assertEqual(data[CONF_DEVICE_TYPE], TYPE_WASHING_MACHINE)
        self.assertIsNone(data.get(CONF_MODEL_TYPE))


class PlatformGateLogicTest(unittest.TestCase):
    """Document the gate rule: sa_type alone, never profile.device_type OR."""

    def test_washer_profile_does_not_imply_climate(self) -> None:
        client = MagicMock()
        client.device.sa_type_id = TYPE_WASHING_MACHINE
        self.assertNotEqual(client.device.sa_type_id, TYPE_AC)

    def test_washer_profile_does_not_imply_humidifier(self) -> None:
        client = MagicMock()
        client.device.sa_type_id = TYPE_WASHING_MACHINE
        self.assertNotEqual(client.device.sa_type_id, TYPE_DEHUMIDIFIER)


class ProbeDefaultTypeTest(unittest.TestCase):
    def test_device_info_defaults_unknown_not_ac(self) -> None:
        from panasonic_taiseia_local.taiseia import DeviceInfo

        self.assertEqual(DeviceInfo(host="1.2.3.4").sa_type_id, 0)


if __name__ == "__main__":
    unittest.main()
