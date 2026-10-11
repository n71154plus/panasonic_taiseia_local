"""EMS "device offline" is a normal state for cloud entries, not a failed poll.

A powered-off washer (or unplugged dehumidifier) makes EMS answer
``503:DeviceJPInfo:aStatusCode`` / ``deviceOffline``. That must not fail the
coordinator refresh: a failed *first* refresh raises ConfigEntryNotReady and
leaves the entry in setup-retry with no entities until the appliance is on.
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
    CONTROL_MODE_CLOUD,
)
from panasonic_taiseia_local.control import DeviceControl  # noqa: E402
from panasonic_taiseia_local.ems_transport import (  # noqa: E402
    CloudDeviceOffline,
    CloudRateLimited,
    classify_state_msg,
)

# StateMsg EMS returned for the powered-off washer on a live install.
WASHER_OFF_MSG = "503:DeviceJPInfo:aStatusCode"


def _control(*, cloud_only: bool, lan_ok: bool, replies: list) -> DeviceControl:
    entry = SimpleNamespace(
        entry_id="e1",
        title="洗衣機 (雲端)",
        data={},
        options={CONF_CONTROL_MODE: CONTROL_MODE_CLOUD},
    )
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_get_entry=lambda _eid: entry)
    )
    client = SimpleNamespace(host="0.0.0.0", poll_services=[])
    control = DeviceControl(hass, entry, client, cloud_only=cloud_only, lan_ok=lan_ok)

    async def _cloud_status(_types):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    control._cloud_status = _cloud_status  # type: ignore[method-assign]
    return control


class CloudDeviceOfflineTest(unittest.TestCase):
    def test_live_washer_message_classified_offline(self) -> None:
        self.assertIs(classify_state_msg(WASHER_OFF_MSG), CloudDeviceOffline)

    def test_offline_is_empty_status_then_recovers(self) -> None:
        control = _control(
            cloud_only=True,
            lan_ok=False,
            replies=[
                CloudDeviceOffline(WASHER_OFF_MSG),
                CloudDeviceOffline(WASHER_OFF_MSG),
                {"0x00": "1"},
            ],
        )
        # Powered off (also the very first refresh during entry setup).
        self.assertEqual(asyncio.run(control.async_fetch_status()), ({}, "offline"))
        self.assertEqual(asyncio.run(control.async_fetch_status()), ({}, "offline"))
        # Powered back on: next poll recovers without a reload.
        self.assertEqual(
            asyncio.run(control.async_fetch_status()), ({"0x00": "1"}, "cloud")
        )
        self.assertEqual(control.last_path, "cloud")

    def test_other_cloud_errors_still_fail_the_poll(self) -> None:
        control = _control(
            cloud_only=True, lan_ok=False, replies=[CloudRateLimited("429")]
        )
        with self.assertRaises(CloudRateLimited):
            asyncio.run(control.async_fetch_status())

    def test_unprobed_lan_module_keeps_failing_for_setup_retry(self) -> None:
        # LAN-capable entry forced to cloud mode whose setup probe failed:
        # setup must keep retrying so the module gets probed once it is back.
        control = _control(
            cloud_only=False,
            lan_ok=False,
            replies=[CloudDeviceOffline(WASHER_OFF_MSG)],
        )
        with self.assertRaises(CloudDeviceOffline):
            asyncio.run(control.async_fetch_status())


if __name__ == "__main__":
    unittest.main()
