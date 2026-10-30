"""LAN power-off can run the AC mold-prevention drying cycle (issue #3).

Plain ``power=0`` written over LAN stops the appliance *without* starting the
mold-dry cycle, while the same logical off via cloud does run it. The AC
firmware additionally accepts the undocumented stop code 2
("power off + mold-prevention drying") over LAN — verified on CS-RX50JA2
(PXGD): the post-off fan/power curve matches a cloud-initiated drying run.

When the per-device option is on, the hybrid/local LAN write path maps the
logical power-off to code 2, but only while the appliance's own drying switch
(0x17) is on, so the option mirrors cloud semantics instead of overriding a
user's setting.
"""

from __future__ import annotations

import asyncio
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
    const = pkg("homeassistant.const")
    const.CONF_HOST = "host"
    const.CONF_NAME = "name"
    const.CONF_PASSWORD = "password"
    const.CONF_DEVICE_ID = "device_id"
    core = pkg("homeassistant.core")
    core.HomeAssistant = object
    pkg("homeassistant.config_entries")
    sys.modules["homeassistant.config_entries"].ConfigEntry = object
    pkg("homeassistant.helpers")
    storage = pkg("homeassistant.helpers.storage")
    storage.Store = object
    aiohttp_client = pkg("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None

    pkg_name = "panasonic_taiseia_local"
    pkg_mod = types.ModuleType(pkg_name)
    pkg_mod.__path__ = [str(ROOT / "custom_components" / "panasonic_taiseia_local")]
    sys.modules[pkg_name] = pkg_mod


_stub_homeassistant()
sys.path.insert(0, str(ROOT / "custom_components"))

from panasonic_taiseia_local.const import (  # noqa: E402
    CONF_CONTROL_MODE,
    CONF_DEVICE_TYPE,
    CONF_LAN_MOLD_DRY,
    CONTROL_MODE_LOCAL,
    DATA_COORDINATOR,
    DOMAIN,
    STATUS,
    SVC_MOLD,
    SVC_POWER,
    SVC_POWER_LAN_MOLD_DRY,
    TYPE_AC,
    TYPE_DEHUMIDIFIER,
)
from panasonic_taiseia_local.control import DeviceControl  # noqa: E402


def _control(
    *,
    sa_type: int = TYPE_AC,
    options: dict | None = None,
    mold_flag: str | None = "1",
) -> tuple[DeviceControl, list]:
    entry = SimpleNamespace(
        entry_id="e1",
        title="冷氣",
        data={CONF_DEVICE_TYPE: sa_type},
        options={CONF_CONTROL_MODE: CONTROL_MODE_LOCAL, **(options or {})},
    )
    writes: list[tuple[int, int]] = []

    async def _write_device(service: int, value: int) -> int:
        writes.append((service, value))
        return value

    client = SimpleNamespace(
        host="192.168.1.10",
        poll_services=[],
        async_write_device=_write_device,
    )
    coord = SimpleNamespace(
        data=({STATUS[SVC_MOLD]: mold_flag} if mold_flag is not None else {})
    )
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_get_entry=lambda _eid: entry),
        data={DOMAIN: {"e1": {DATA_COORDINATOR: coord}}},
    )
    control = DeviceControl(hass, entry, client, cloud_only=False, lan_ok=True)
    return control, writes


class LanMoldDryPowerOffTest(unittest.TestCase):
    def test_option_off_keeps_plain_stop_code(self) -> None:
        control, writes = _control()
        self.assertEqual(
            asyncio.run(control.async_write(SVC_POWER, 0)), "lan"
        )
        self.assertEqual(writes, [(SVC_POWER, 0)])

    def test_option_on_maps_power_off_to_drying_stop_code(self) -> None:
        control, writes = _control(options={CONF_LAN_MOLD_DRY: True})
        self.assertEqual(
            asyncio.run(control.async_write(SVC_POWER, 0)), "lan"
        )
        self.assertEqual(writes, [(SVC_POWER, SVC_POWER_LAN_MOLD_DRY)])

    def test_power_on_is_never_mapped(self) -> None:
        control, writes = _control(options={CONF_LAN_MOLD_DRY: True})
        asyncio.run(control.async_write(SVC_POWER, 1))
        self.assertEqual(writes, [(SVC_POWER, 1)])

    def test_other_services_are_never_mapped(self) -> None:
        control, writes = _control(options={CONF_LAN_MOLD_DRY: True})
        asyncio.run(control.async_write(0x03, 26))  # temp set
        self.assertEqual(writes, [(0x03, 26)])

    def test_non_ac_devices_ignore_the_mapping(self) -> None:
        control, writes = _control(
            sa_type=TYPE_DEHUMIDIFIER, options={CONF_LAN_MOLD_DRY: True}
        )
        asyncio.run(control.async_write(SVC_POWER, 0))
        self.assertEqual(writes, [(SVC_POWER, 0)])

    def test_drying_switch_off_means_plain_stop(self) -> None:
        # The appliance's own 0x17 switch wins: off → no forced drying.
        control, writes = _control(
            options={CONF_LAN_MOLD_DRY: True}, mold_flag="0"
        )
        asyncio.run(control.async_write(SVC_POWER, 0))
        self.assertEqual(writes, [(SVC_POWER, 0)])

    def test_unknown_flag_defaults_to_drying(self) -> None:
        # No 0x17 in coordinator data (device never polled, or model without
        # the switch): keep the behaviour the user opted into.
        control, writes = _control(
            options={CONF_LAN_MOLD_DRY: True}, mold_flag=None
        )
        asyncio.run(control.async_write(SVC_POWER, 0))
        self.assertEqual(writes, [(SVC_POWER, SVC_POWER_LAN_MOLD_DRY)])


if __name__ == "__main__":
    unittest.main()
