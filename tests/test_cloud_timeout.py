"""EMS TimeoutError must surface as CloudTimeout (transient cloud jitter)."""

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

import aiohttp  # noqa: E402

from panasonic_taiseia_local.ems_transport import (  # noqa: E402
    CloudTimeout,
    EmsSettings,
    EmsTransport,
)


class CloudTimeoutTransportTest(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_error_becomes_cloud_timeout(self) -> None:
        class _Timeout:
            def __init__(self, total=None):
                self.total = total

        aiohttp.ClientTimeout = _Timeout

        class _Boom:
            async def __aenter__(self):
                raise TimeoutError()

            async def __aexit__(self, *args):
                return False

        class _Session:
            def request(self, *args, **kwargs):
                return _Boom()

        transport = EmsTransport(
            _Session(), object(), EmsSettings(base_urls=["https://ems.example/api"])
        )  # type: ignore[arg-type]
        with self.assertRaises(CloudTimeout) as caught:
            await transport._request_once(
                "POST",
                "/DeviceGetInfo",
                headers=None,
                params=None,
                json_body={},
                data=None,
                expect_json=True,
            )
        self.assertIn("TimeoutError", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
