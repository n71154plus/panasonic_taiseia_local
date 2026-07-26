"""Tests for EMS gate priority queue and diagnostics auth redaction."""

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
    helpers = pkg("homeassistant.helpers")
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
    CONF_CLOUD_AUTH,
    CONF_CONTROL_MODE,
    CONTROL_MODE_CLOUD,
    CONTROL_MODE_HYBRID,
    CONTROL_MODE_LOCAL,
)
from panasonic_taiseia_local.control import resolve_control_mode  # noqa: E402
from panasonic_taiseia_local.diagnostics_data import redact_mapping  # noqa: E402
from panasonic_taiseia_local.ems_transport import EmsGate, RequestPriority  # noqa: E402
from panasonic_taiseia_local.entry_helpers import (  # noqa: E402
    options_changed_since_seed,
    seed_options_snapshot,
)


class EmsGatePriorityTest(unittest.TestCase):
    def test_user_jumps_ahead_of_background_queue(self) -> None:
        async def _run() -> list[str]:
            gate = EmsGate()
            gate.settings.min_interval = 0.0
            order: list[str] = []
            started = asyncio.Event()

            async def bg():
                await started.wait()
                await asyncio.sleep(0.01)
                order.append("bg")
                return "bg"

            async def user():
                order.append("user")
                return "user"

            # Occupy the worker with a slow first job so both waiters queue
            async def first():
                started.set()
                await asyncio.sleep(0.05)
                order.append("first")
                return "first"

            t_first = asyncio.create_task(
                gate.run(first, priority=RequestPriority.NORMAL)
            )
            await started.wait()
            t_bg = asyncio.create_task(
                gate.run(bg, priority=RequestPriority.BACKGROUND)
            )
            await asyncio.sleep(0.01)
            t_user = asyncio.create_task(
                gate.run(user, priority=RequestPriority.USER)
            )
            await asyncio.gather(t_first, t_bg, t_user)
            return order

        order = asyncio.run(_run())
        self.assertEqual(order[0], "first")
        # USER should run before BACKGROUND when both were waiting
        self.assertLess(order.index("user"), order.index("bg"))

    def test_worker_restarts_after_idle(self) -> None:
        async def _run() -> list[str]:
            gate = EmsGate()
            gate.settings.min_interval = 0.0
            order: list[str] = []

            async def one():
                order.append("one")
                return "one"

            async def two():
                order.append("two")
                return "two"

            await gate.run(one, priority=RequestPriority.NORMAL)
            # Let worker exit on idle
            await asyncio.sleep(0.12)
            await gate.run(two, priority=RequestPriority.USER)
            return order

        self.assertEqual(asyncio.run(_run()), ["one", "two"])


class RedactAuthTest(unittest.TestCase):
    def test_cloud_auth_redacted(self) -> None:
        redacted = redact_mapping(
            {
                "cloud_auth": "secret-auth",
                "auth": "also-secret",
                CONF_CLOUD_AUTH: "tok",
                "host": "192.168.0.1",
            }
        )
        self.assertEqual(redacted["cloud_auth"], "**REDACTED**")
        self.assertEqual(redacted["auth"], "**REDACTED**")
        self.assertEqual(redacted[CONF_CLOUD_AUTH], "**REDACTED**")
        self.assertEqual(redacted["host"], "192.168.0.1")


class ControlModeTest(unittest.TestCase):
    def test_resolve_modes(self) -> None:
        entry = SimpleNamespace(options={}, data={})
        self.assertEqual(resolve_control_mode(entry), CONTROL_MODE_HYBRID)
        self.assertEqual(
            resolve_control_mode(entry, cloud_only=True), CONTROL_MODE_CLOUD
        )
        entry.options = {CONF_CONTROL_MODE: CONTROL_MODE_LOCAL}
        self.assertEqual(resolve_control_mode(entry), CONTROL_MODE_LOCAL)


class EntryReloadGateTest(unittest.TestCase):
    def test_options_unchanged_skips_reload_signal(self) -> None:
        hass = SimpleNamespace(data={})
        entry = SimpleNamespace(entry_id="e1", options={"poll_interval": 30})
        seed_options_snapshot(hass, entry)
        self.assertFalse(options_changed_since_seed(hass, entry))
        entry.options = {"poll_interval": 60}
        self.assertTrue(options_changed_since_seed(hass, entry))


if __name__ == "__main__":
    unittest.main()
