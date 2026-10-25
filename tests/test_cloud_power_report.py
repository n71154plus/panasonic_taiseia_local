"""Cloud Power report (UserGetInfo name=Power) parsing and entity gating.

MHW dehumidifiers have no LAN power service (all power registers answer
0xFFFF), but the official app shows monthly kWh — it comes from
POST /UserGetInfo {"name":"Power",...}. The integration must parse that
response and expose a monthly-energy sensor for cloud-linked devices.
"""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _stub_homeassistant() -> None:
    def pkg(name: str) -> types.ModuleType:
        mod = sys.modules.get(name)
        if mod is None:
            mod = types.ModuleType(name)
            mod.__path__ = []
            sys.modules[name] = mod
        return mod

    class _Enum:
        def __init__(self, value):
            self.value = value

    class _EnumMeta(type):
        def __getattr__(cls, name):
            return _Enum(name.lower())

    ha = pkg("homeassistant")
    components = pkg("homeassistant.components")
    sensor = pkg("homeassistant.components.sensor")

    class SensorEntity:
        pass

    sensor.SensorEntity = SensorEntity
    sensor.SensorDeviceClass = _EnumMeta(
        "SensorDeviceClass", (), {}
    )
    sensor.SensorStateClass = _EnumMeta("SensorStateClass", (), {})
    const = pkg("homeassistant.const")
    const.UnitOfEnergy = type(
        "UnitOfEnergy", (), {"KILO_WATT_HOUR": "kWh"}
    )
    const.UnitOfPower = type("UnitOfPower", (), {"WATT": "W"})
    const.UnitOfTemperature = type(
        "UnitOfTemperature", (), {"CELSIUS": "°C"}
    )
    const.PERCENTAGE = "%"
    const.CONCENTRATION_MICROGRAMS_PER_CUBIC_METER = "µg/m³"
    const.EntityCategory = type(
        "EntityCategory", (), {"DIAGNOSTIC": "diagnostic"}
    )
    const.CONF_NAME = "name"
    const.CONF_HOST = "host"
    const.CONF_PORT = "port"
    const.CONF_USERNAME = "username"
    const.CONF_PASSWORD = "password"
    ce = pkg("homeassistant.config_entries")
    ce.ConfigEntry = object
    core = pkg("homeassistant.core")
    core.HomeAssistant = object
    core.callback = lambda f: f
    helpers = pkg("homeassistant.helpers")
    typing_mod = pkg("homeassistant.helpers.typing")
    typing_mod.StateType = object
    dr = pkg("homeassistant.helpers.device_registry")
    dr.CONNECTION_NETWORK_MAC = "mac"
    ac = pkg("homeassistant.helpers.aiohttp_client")
    ac.async_get_clientsession = lambda hass: None
    uc = pkg("homeassistant.helpers.update_coordinator")

    class CoordinatorEntity:
        def __init__(self, coordinator):
            self.coordinator = coordinator

    uc.CoordinatorEntity = CoordinatorEntity
    ha.components = components
    ha.const = const
    ha.core = core
    ha.helpers = helpers
    components.sensor = sensor
    helpers.typing = typing_mod
    helpers.device_registry = dr
    helpers.aiohttp_client = ac
    helpers.update_coordinator = uc


_stub_homeassistant()
sys.path.insert(0, str(ROOT / "custom_components"))

from panasonic_taiseia_local import cloud as cloud_mod  # noqa: E402
from panasonic_taiseia_local import sensor as sensor_mod  # noqa: E402


def _account_with_response(payload):
    """CloudAccount whose _raw returns ``payload`` and records the request."""
    calls = []

    async def _fake_raw(method, path, *, headers=None, params=None,
                        json_body=None, priority=None, expect_json=True):
        calls.append({"method": method, "path": path, "json_body": json_body})
        return payload

    acct = cloud_mod.CloudAccount.__new__(cloud_mod.CloudAccount)
    acct.cp_token = "tok"
    acct._raw = _fake_raw  # type: ignore[assignment]

    async def _pass_auth_retry(factory):
        return await factory()

    acct._with_auth_retry = _pass_auth_retry  # type: ignore[assignment]
    return acct, calls


class PowerReportParsing(unittest.TestCase):
    def test_parses_total_kwh_per_gwid(self):
        payload = {
            "GwList": [
                {"GwID": "29be351864f8b638ff6723244cc64371",
                 "Total_kwh": 12.34,
                 "List": [{"Date": "2026/10/01", "kWh": 0.5}]},
                {"GwID": "f26983f411b528fd43f38563bceae06a",
                 "Total_kwh": "94.2"},
                {"GwID": "no-data-device"},
            ]
        }
        acct, calls = _account_with_response(payload)
        result = asyncio.run(acct.async_get_power_report())
        self.assertEqual(
            result,
            {
                "29be351864f8b638ff6723244cc64371": {"total_kwh": 12.34},
                "f26983f411b528fd43f38563bceae06a": {"total_kwh": 94.2},
            },
        )

    def test_request_payload_matches_app_contract(self):
        acct, calls = _account_with_response({"GwList": []})
        asyncio.run(acct.async_get_power_report())
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["path"], "/UserGetInfo")
        body = call["json_body"]
        self.assertEqual(body["name"], "Power")
        self.assertEqual(body["unit"], "day")
        self.assertEqual(body["max_num"], 31)
        # from = first day of the current month, YYYY/MM/DD
        self.assertRegex(body["from"], r"^\d{4}/\d{2}/01$")

    def test_gwid_uppercase_variant(self):
        payload = {"GwList": [{"GWID": "abc", "Total_kwh": 1}]}
        acct, _ = _account_with_response(payload)
        result = asyncio.run(acct.async_get_power_report())
        self.assertEqual(result, {"abc": {"total_kwh": 1.0}})

    def test_malformed_responses_do_not_raise(self):
        for payload in ({}, {"GwList": None}, {"GwList": ["x"]}, {"GwList": [{"GwID": "a", "Total_kwh": "n/a"}]}):
            acct, _ = _account_with_response(payload)
            result = asyncio.run(acct.async_get_power_report())
            self.assertEqual(result, {}, payload)


class CloudEnergySensorGate(unittest.TestCase):
    def test_sensor_class_metadata(self):
        from panasonic_taiseia_local import sensor as sensor_mod

        cls = sensor_mod.TaiSeiaCloudEnergySensor
        self.assertEqual(cls._entity_key, "cloud_monthly_energy")
        self.assertEqual(
            cls._attr_device_class.value, "energy"
        )
        self.assertEqual(cls._attr_native_unit_of_measurement, "kWh")

    def test_native_value_reads_coordinator_key(self):
        from panasonic_taiseia_local import sensor as sensor_mod

        class _Coord:
            def __init__(self, data):
                self.data = data

        class _Dev:
            unique_id = "dev1"
            mac = None
            sa_model = "F-YV32MH"
            host = "h"
            port = 0
            services = ()
            sa_type_id = 0x04

        class _Client:
            device = _Dev()
            host = "h"
            port = 0

        inst = sensor_mod.TaiSeiaCloudEnergySensor.__new__(
            sensor_mod.TaiSeiaCloudEnergySensor
        )
        inst.coordinator = _Coord({"energy_cloud_month_kwh": 12.3})
        self.assertEqual(inst.native_value, 12.3)
        inst.coordinator = _Coord({})
        self.assertIsNone(inst.native_value)


if __name__ == "__main__":
    unittest.main()
