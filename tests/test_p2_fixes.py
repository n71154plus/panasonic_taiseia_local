"""P2 regression: SP alias, cloud type priority, account mask."""

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
    ha.components = components
    components.climate = climate
    const = pkg("homeassistant.const")
    const.CONF_HOST = "host"
    const.CONF_NAME = "name"
    const.CONF_PASSWORD = "password"
    core = pkg("homeassistant.core")
    core.HomeAssistant = object
    core.callback = lambda f: f
    pkg("homeassistant.config_entries")
    sys.modules["homeassistant.config_entries"].ConfigEntry = object
    helpers = pkg("homeassistant.helpers")
    aiohttp_client = pkg("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None
    helpers.aiohttp_client = aiohttp_client
    device_registry = pkg("homeassistant.helpers.device_registry")
    device_registry.async_get = lambda hass: None
    helpers.device_registry = device_registry
    sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

    pkg_name = "panasonic_taiseia_local"
    pkg_mod = types.ModuleType(pkg_name)
    pkg_mod.__path__ = [str(ROOT / "custom_components" / "panasonic_taiseia_local")]
    sys.modules[pkg_name] = pkg_mod


_stub_homeassistant()
sys.path.insert(0, str(ROOT / "custom_components"))

from panasonic_taiseia_local.catalog import (  # noqa: E402
    build_profile,
    model_type_matches_device,
    resolve_model_type,
)
from panasonic_taiseia_local.const import (  # noqa: E402
    ENTITY_SERVICES_BY_TYPE,
    TYPE_WASHING_MACHINE,
)
from panasonic_taiseia_local.control import default_cloud_command_types  # noqa: E402
from panasonic_taiseia_local.cloud import command_type_hex  # noqa: E402
from panasonic_taiseia_local.naming import mask_account  # noqa: E402


class SpWasherAliasTest(unittest.TestCase):
    def test_sp_and_rph_resolve(self) -> None:
        self.assertTrue(model_type_matches_device("SP", TYPE_WASHING_MACHINE))
        self.assertTrue(model_type_matches_device("RPH", TYPE_WASHING_MACHINE))
        self.assertEqual(resolve_model_type("SP", TYPE_WASHING_MACHINE), "SP")
        profile = build_profile("SP")
        assert profile is not None
        self.assertEqual(profile.device_type, TYPE_WASHING_MACHINE)
        self.assertGreater(len(profile.commands), 0)


class CloudCommandPriorityTest(unittest.TestCase):
    def test_core_services_come_first_within_limit(self) -> None:
        core = ENTITY_SERVICES_BY_TYPE[TYPE_WASHING_MACHINE]
        # Put junk ids first in the profile list; core must still win truncation.
        bloated = list(range(0x80, 0x80 + 40)) + list(core)
        types = default_cloud_command_types(
            bloated, sa_type_id=TYPE_WASHING_MACHINE, limit=24
        )
        self.assertEqual(len(types), 24)
        for sid in core:
            self.assertIn(command_type_hex(sid), types)


class MaskAccountTest(unittest.TestCase):
    def test_email_masked(self) -> None:
        self.assertEqual(mask_account("alice@example.com"), "a***@example.com")

    def test_short_local(self) -> None:
        self.assertEqual(mask_account("a@x.tw"), "*@x.tw")


if __name__ == "__main__":
    unittest.main()
