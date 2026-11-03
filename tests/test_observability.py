"""Regression: observable failure snapshots and mold-dry honesty helpers."""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


sys.path.insert(0, str(ROOT / "custom_components"))

# Lightweight stubs only if Home Assistant is not importable as a package.
try:
    import homeassistant.config_entries  # noqa: F401
except Exception:  # noqa: BLE001
    def pkg(name: str) -> types.ModuleType:
        mod = types.ModuleType(name)
        mod.__path__ = []
        sys.modules[name] = mod
        return mod

    pkg("homeassistant")
    conf = pkg("homeassistant.config_entries")
    conf.ConfigEntry = type("ConfigEntry", (), {})
    core = pkg("homeassistant.core")
    core.HomeAssistant = object
    core.callback = lambda f: f
    const = pkg("homeassistant.const")
    const.CONF_HOST = "host"
    const.CONF_NAME = "name"
    const.CONF_PASSWORD = "password"
    pkg("homeassistant.helpers")
    pkg("homeassistant.helpers.aiohttp_client")
    sys.modules["homeassistant.helpers.aiohttp_client"].async_get_clientsession = (
        lambda hass: None
    )
    sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

from panasonic_taiseia_local import cloud as cloud_mod  # noqa: E402
from panasonic_taiseia_local.catalog import _known_service_kind  # noqa: E402
from panasonic_taiseia_local.const import (  # noqa: E402
    CONF_CONTROL_MODE,
    CONTROL_MODE_HYBRID,
    SVC_MOLD_ALT,
    TYPE_AC,
    TYPE_DEHUMIDIFIER,
)
from panasonic_taiseia_local.diagnostics_data import (  # noqa: E402
    build_device_snapshot,
    probe_sensor_attributes,
)
from panasonic_taiseia_local.ems_transport import EmsSettings, EmsTransport  # noqa: E402
from panasonic_taiseia_local.observability import (  # noqa: E402
    MOLD_DRY_BEHAVIOR,
    auth_health_snapshot,
    control_health_snapshot,
)
from panasonic_taiseia_local.taiseia import DeviceInfo, ServiceInfo  # noqa: E402


class ObservabilityTest(unittest.TestCase):
    def test_mold_dry_behavior_is_honest(self) -> None:
        self.assertEqual(
            MOLD_DRY_BEHAVIOR["official_start"],
            "ems_power_off_while_preference_on",
        )
        self.assertIn("RX-20", MOLD_DRY_BEHAVIOR["lan_power_off"])
        self.assertEqual(MOLD_DRY_BEHAVIOR["preference_service"]["ux_vx"], "0x56")

    def test_ac_0x56_is_switch_but_dehumidifier_is_not_forced(self) -> None:
        self.assertEqual(
            _known_service_kind(TYPE_AC, SVC_MOLD_ALT, writable=True, span=1),
            "switch",
        )
        # Dehumidifier 0x56 stays on the span heuristic / DH sensors path.
        self.assertEqual(
            _known_service_kind(
                TYPE_DEHUMIDIFIER, SVC_MOLD_ALT, writable=False, span=255
            ),
            None,
        )

    def test_control_and_auth_snapshots(self) -> None:
        entry = SimpleNamespace(
            entry_id="dev1",
            options={CONF_CONTROL_MODE: CONTROL_MODE_HYBRID},
            data={},
        )
        control = SimpleNamespace(
            lan_ok=False,
            last_path="offline",
            can_use_lan=lambda: False,
            can_use_cloud=lambda: True,
        )
        snap = control_health_snapshot(
            control=control, entry=entry, cloud_only=False
        )
        self.assertFalse(snap["lan_ok"])
        self.assertEqual(snap["last_path"], "offline")
        self.assertEqual(snap["control_mode"], CONTROL_MODE_HYBRID)

        account = "ops@example.com"
        cloud_mod.clear_credentials_rejected(account)
        hub = SimpleNamespace(
            entry_id="hub1",
            data={"username": account},
        )
        ok = auth_health_snapshot(hub)
        self.assertTrue(ok["credentials_ok"])
        cloud_mod.mark_credentials_rejected(account, "bad")
        bad = auth_health_snapshot(hub)
        self.assertFalse(bad["credentials_ok"])
        cloud_mod.clear_credentials_rejected(account)

    def test_transport_cooldown_snapshot(self) -> None:
        class _Session:
            pass

        transport = EmsTransport(_Session(), object(), EmsSettings())  # type: ignore[arg-type]
        transport._mark_blocked("https://ems2.panasonic.com.tw/api", 30, "test")
        snap = transport.cooldown_snapshot()
        self.assertTrue(snap["bases"][0]["blocked"])
        self.assertGreater(snap["bases"][0]["cooldown_remaining_s"], 0)

    def test_diagnostics_include_health_and_behavior(self) -> None:
        entry = SimpleNamespace(
            entry_id="e1",
            title="書房",
            unique_id="aabbccddeeff",
            version=2,
            data={"host": "192.0.2.10", "hub_entry_id": "hub1"},
            options={CONF_CONTROL_MODE: CONTROL_MODE_HYBRID},
        )
        device = DeviceInfo(
            host="192.0.2.10",
            port=57223,
            sa_type_id=TYPE_AC,
            services={0x00: ServiceInfo(0x00, True, 0, 1)},
        )
        snapshot = build_device_snapshot(
            entry=entry,
            device=device,
            status={"0x00": "0"},
            profile=None,
            coordinator_ok=True,
            poll_interval=30,
            lan={"timeout": 3, "retries": 1, "max_concurrent": 2},
            extra={
                "control": {
                    "control_mode": CONTROL_MODE_HYBRID,
                    "lan_ok": False,
                    "last_path": "offline",
                },
                "auth": {"credentials_ok": True},
                "ems": {"queue_depth": 0, "transport": {"in_cooldown": False}},
            },
        )
        self.assertIn("behavior", snapshot)
        self.assertEqual(
            snapshot["behavior"]["mold_dry"]["official_start"],
            "ems_power_off_while_preference_on",
        )
        self.assertFalse(snapshot["control"]["lan_ok"])
        attrs = probe_sensor_attributes(snapshot)
        self.assertEqual(attrs.get("LAN可用"), False)
        self.assertEqual(attrs.get("控制模式"), CONTROL_MODE_HYBRID)
        self.assertIn("乾燥防霉說明", attrs)

    def test_hybrid_without_cloud_keeps_transport_error(self) -> None:
        """#21 regression: hybrid + no cloud must not wrap TimeoutError."""
        # Import here so HA stubs from other tests do not break DeviceControl.
        from panasonic_taiseia_local.control import DeviceControl
        from panasonic_taiseia_local.taiseia import is_lan_transport_error

        entry = SimpleNamespace(
            entry_id="e1",
            title="除濕機",
            data={},
            options={CONF_CONTROL_MODE: CONTROL_MODE_HYBRID},
        )
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_get_entry=lambda _eid: entry)
        )

        async def _fetch():
            raise TimeoutError()

        client = SimpleNamespace(
            host="192.0.2.1", poll_services=[], async_fetch_status=_fetch
        )
        control = DeviceControl(hass, entry, client, cloud_only=False, lan_ok=True)
        with self.assertRaises(TimeoutError) as caught:
            asyncio.run(control.async_fetch_status())
        self.assertTrue(is_lan_transport_error(caught.exception))
        self.assertFalse(control.lan_ok)


if __name__ == "__main__":
    unittest.main()
