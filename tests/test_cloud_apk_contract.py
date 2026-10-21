"""APK-aligned EMS helpers (no network)."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _stub() -> None:
    def pkg(name: str) -> types.ModuleType:
        mod = types.ModuleType(name)
        mod.__path__ = []
        sys.modules[name] = mod
        return mod

    ha = pkg("homeassistant")
    components = pkg("homeassistant.components")
    climate = pkg("homeassistant.components.climate")

    class _HVACMode:
        OFF = "off"
        COOL = "cool"
        DRY = "dry"
        FAN_ONLY = "fan_only"
        AUTO = "auto"
        HEAT = "heat"

    climate.HVACMode = _HVACMode
    ha.components = components
    components.climate = climate
    sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))
    pkg_name = "panasonic_taiseia_local"
    pkg_mod = types.ModuleType(pkg_name)
    pkg_mod.__path__ = [str(ROOT / "custom_components" / "panasonic_taiseia_local")]
    sys.modules[pkg_name] = pkg_mod


_stub()

from panasonic_taiseia_local.cloud import (  # noqa: E402
    build_device_get_info_body,
    command_type_hex,
    parse_device_get_info,
)
from panasonic_taiseia_local.const import (  # noqa: E402
    CONTROL_MODE_CLOUD,
    CONTROL_MODE_HYBRID,
    CONTROL_MODE_LOCAL,
    DEFAULT_CONTROL_MODE,
)
from panasonic_taiseia_local.ems_transport import (  # noqa: E402
    CloudAuthError,
    CloudRateLimited,
    EmsSettings,
    EmsTransport,
    classify_state_msg,
    exception_from_body,
)


class ApkContractTests(unittest.TestCase):
    def test_command_type_hex(self):
        self.assertEqual(command_type_hex(0), "0x00")
        self.assertEqual(command_type_hex(23), "0x17")

    def test_get_info_body(self):
        body = build_device_get_info_body(["0x00", "0x01"])
        self.assertEqual(body[0]["DeviceID"], 1)
        self.assertEqual(body[0]["CommandTypes"][0]["CommandType"], "0x00")

    def test_parse_get_info(self):
        payload = {
            "devices": [
                {
                    "DeviceID": 1,
                    "Info": [
                        {"CommandType": "0x00", "status": "1"},
                        {"CommandType": "0x01", "status": "0"},
                    ],
                }
            ]
        }
        status = parse_device_get_info(payload)
        self.assertEqual(status["0x00"], "1")
        self.assertEqual(status["0x01"], "0")

    def test_defaults(self):
        self.assertEqual(DEFAULT_CONTROL_MODE, CONTROL_MODE_HYBRID)
        self.assertIn(CONTROL_MODE_LOCAL, (CONTROL_MODE_LOCAL, CONTROL_MODE_CLOUD))

    def test_rate_limit_msg(self):
        self.assertIs(classify_state_msg("系統檢測您當前超量使用"), CloudRateLimited)



class CloudDeviceFlagsTests(unittest.TestCase):
    def test_mac_gwid_is_local(self):
        from panasonic_taiseia_local.cloud import CloudDevice
        d = CloudDevice(
            gwid="AABBCCDDEEFF",
            auth="x",
            nickname="AC",
            model="X",
            model_id="",
            model_type="UX",
            device_type=1,
            mac="AABBCCDDEEFF",
        )
        self.assertTrue(d.is_local_candidate)
        d2 = CloudDevice(
            gwid="opaqueGwid123456",
            auth="y",
            nickname="Fridge",
            model="F",
            model_id="",
            model_type="F657",
            device_type=2,
            mac=None,
        )
        self.assertFalse(d2.is_local_candidate)


class ExpiredCpTokenTests(unittest.IsolatedAsyncioTestCase):
    def test_plain_text_expiry_is_auth_error(self):
        err = exception_from_body("此CPToken已經逾時")
        self.assertIsInstance(err, CloudAuthError)

    def test_json_state_msg_still_classified(self):
        err = exception_from_body('{"State":"fail","StateMsg":"此CPToken已經逾時"}')
        self.assertIsInstance(err, CloudAuthError)
        limited = exception_from_body('{"StateMsg":"系統檢測您當前超量使用"}')
        self.assertIsInstance(limited, CloudRateLimited)

    async def test_transport_plain_417_raises_auth(self):
        import aiohttp

        class _Timeout:
            def __init__(self, total=None):
                self.total = total

        aiohttp.ClientTimeout = _Timeout

        class _Resp:
            status = 417

            async def text(self):
                return "此CPToken已經逾時"

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        class _Session:
            def request(self, *args, **kwargs):
                return _Resp()

        transport = EmsTransport(_Session(), object(), EmsSettings())  # type: ignore[arg-type]
        with self.assertRaises(CloudAuthError):
            await transport._request_once(
                "GET",
                "/UserGetRegisteredGwList2",
                headers=None,
                params=None,
                json_body=None,
                data=None,
                expect_json=True,
            )

    async def test_expired_token_password_login(self):
        from panasonic_taiseia_local import cloud as cloud_mod
        from panasonic_taiseia_local.cloud import CloudAccount

        account_name = "expired-token@example.com"
        cloud_mod._reauth_locks.pop(account_name, None)
        cloud_mod._reauth_tokens.pop(account_name, None)

        class _Stub:
            def __init__(self):
                self.paths: list[str] = []

            async def request(self, method, path, **kwargs):
                self.paths.append(path)
                headers = kwargs.get("headers") or {}
                if path == "/RefreshToken1":
                    raise CloudAuthError("無效RefreshToken")
                if path == "/userlogin1":
                    return {"CPToken": "fresh-token", "RefreshToken": "refresh-2"}
                if path == "/UserGetRegisteredGwList2":
                    if headers.get("cptoken") != "fresh-token":
                        raise CloudAuthError("此CPToken已經逾時")
                    return {"GwList": []}
                raise AssertionError(path)

        stub = _Stub()
        account = CloudAccount(
            None,  # type: ignore[arg-type]
            account_name,
            "secret",
            refresh_token="old-refresh",
            cp_token="expired-token",
            transport=stub,  # type: ignore[arg-type]
        )
        devices = await account.async_get_devices()
        self.assertEqual(devices, [])
        self.assertEqual(account.cp_token, "fresh-token")
        self.assertEqual(account.refresh_token, "refresh-2")
        self.assertIn("/userlogin1", stub.paths)
        self.assertEqual(stub.paths[-1], "/UserGetRegisteredGwList2")


if __name__ == "__main__":
    unittest.main()
