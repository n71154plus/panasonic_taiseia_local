"""EMS password rejection must stop retries and surface as credentials invalid."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components"))

from panasonic_taiseia_local import cloud as cloud_mod  # noqa: E402
from panasonic_taiseia_local.cloud import (  # noqa: E402
    CloudAccount,
    CloudCredentialsInvalid,
    CloudRateLimited,
    clear_credentials_rejected,
    credentials_rejected,
    take_reauth_notify_slot,
)
from panasonic_taiseia_local.ems_transport import CloudAuthError  # noqa: E402


class CredentialsRejectGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.account = "bad-pass@example.com"
        clear_credentials_rejected(self.account)
        cloud_mod._reauth_locks.pop(self.account, None)
        cloud_mod._reauth_tokens.pop(self.account, None)

    def tearDown(self) -> None:
        clear_credentials_rejected(self.account)

    def test_bad_password_stops_further_login_http(self) -> None:
        class _Stub:
            def __init__(self) -> None:
                self.login_calls = 0

            async def request(self, method, path, **kwargs):
                if path == "/userlogin1":
                    self.login_calls += 1
                    return {"State": "fail", "StateMsg": "帳號或密碼錯誤"}
                raise AssertionError(path)

        stub = _Stub()
        account = CloudAccount(
            None,  # type: ignore[arg-type]
            self.account,
            "wrong",
            transport=stub,  # type: ignore[arg-type]
        )
        with self.assertRaises(CloudCredentialsInvalid):
            asyncio.run(account.login())
        self.assertTrue(credentials_rejected(self.account))
        self.assertEqual(stub.login_calls, 1)

        with self.assertRaises(CloudCredentialsInvalid):
            asyncio.run(account.login())
        with self.assertRaises(CloudCredentialsInvalid):
            asyncio.run(account.ensure_login())
        # Second attempt must not hit EMS again.
        self.assertEqual(stub.login_calls, 1)

    def test_rate_limit_on_login_does_not_lock_account(self) -> None:
        class _Stub:
            async def request(self, method, path, **kwargs):
                raise CloudRateLimited("系統檢測您當前超量使用")

        account = CloudAccount(
            None,  # type: ignore[arg-type]
            self.account,
            "secret",
            transport=_Stub(),  # type: ignore[arg-type]
        )
        with self.assertRaises(CloudRateLimited):
            asyncio.run(account.login())
        self.assertFalse(credentials_rejected(self.account))

    def test_token_expiry_still_falls_back_to_password_once(self) -> None:
        class _Stub:
            def __init__(self) -> None:
                self.paths: list[str] = []

            async def request(self, method, path, **kwargs):
                self.paths.append(path)
                headers = kwargs.get("headers") or {}
                if path == "/RefreshToken1":
                    raise CloudAuthError("無效RefreshToken")
                if path == "/userlogin1":
                    return {"CPToken": "fresh", "RefreshToken": "r2"}
                if path == "/UserGetRegisteredGwList2":
                    if headers.get("cptoken") != "fresh":
                        raise CloudAuthError("此CPToken已經逾時")
                    return {"GwList": []}
                raise AssertionError(path)

        stub = _Stub()
        account = CloudAccount(
            None,  # type: ignore[arg-type]
            self.account,
            "secret",
            refresh_token="old",
            cp_token="expired",
            transport=stub,  # type: ignore[arg-type]
        )
        devices = asyncio.run(account.async_get_devices())
        self.assertEqual(devices, [])
        self.assertIn("/userlogin1", stub.paths)
        self.assertFalse(credentials_rejected(self.account))

    def test_rejected_password_during_token_retry_locks_account(self) -> None:
        class _Stub:
            def __init__(self) -> None:
                self.login_calls = 0

            async def request(self, method, path, **kwargs):
                if path == "/UserGetRegisteredGwList2":
                    raise CloudAuthError("此CPToken已經逾時")
                if path == "/RefreshToken1":
                    raise CloudAuthError("無效RefreshToken")
                if path == "/userlogin1":
                    self.login_calls += 1
                    return {"State": "fail"}
                raise AssertionError(path)

        stub = _Stub()
        account = CloudAccount(
            None,  # type: ignore[arg-type]
            self.account,
            "wrong",
            refresh_token="old",
            cp_token="expired",
            transport=stub,  # type: ignore[arg-type]
        )
        with self.assertRaises(CloudCredentialsInvalid):
            asyncio.run(account.async_get_devices())
        self.assertEqual(stub.login_calls, 1)
        with self.assertRaises(CloudCredentialsInvalid):
            asyncio.run(account.async_get_devices())
        self.assertEqual(stub.login_calls, 1)

    def test_reauth_notify_slot_only_once_until_cleared(self) -> None:
        self.assertTrue(take_reauth_notify_slot(self.account))
        self.assertFalse(take_reauth_notify_slot(self.account))
        clear_credentials_rejected(self.account)
        self.assertTrue(take_reauth_notify_slot(self.account))


if __name__ == "__main__":
    unittest.main()
