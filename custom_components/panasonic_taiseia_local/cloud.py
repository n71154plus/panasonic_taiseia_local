"""Minimal Panasonic EMS cloud client (login + device list only)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__package__)

BASE_URL = "https://ems2.panasonic.com.tw/api"
APP_TOKEN = "D8CBFF4C-2824-4342-B22D-189166FEF503"
USER_AGENT = "okhttp/4.9.1"
_LOGIN = "/userlogin1"
_REFRESH = "/RefreshToken1"
_DEVICES = "/UserGetRegisteredGwList2"
_GW_IP = "/UserGetGWIP"

_MAC_RE = re.compile(r"^[0-9A-Fa-f]{12}$")
_IPV4_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d?\d)$"
)


class CloudAuthError(Exception):
    """Login / token failure."""


class CloudApiError(Exception):
    """Unexpected API response."""


@dataclass(frozen=True)
class CloudDevice:
    gwid: str
    auth: str
    nickname: str
    model: str
    model_id: str
    model_type: str
    device_type: int
    mac: str | None  # 12 hex if CZ-T006-style

    @property
    def is_local_candidate(self) -> bool:
        """Any device with MAC-style GWID may have a LAN module."""
        return self.mac is not None


def _mac_from_gwid(gwid: str) -> str | None:
    g = (gwid or "").strip()
    if _MAC_RE.match(g):
        return g.upper()
    return None


def parse_gw_ip_payload(raw: str | dict | None) -> str | None:
    """Normalize UserGetGWIP body (quoted IP string or tiny JSON) → IPv4."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        for key in ("IP", "Ip", "ip", "GWIP", "GwIP", "Host", "host"):
            value = raw.get(key)
            if isinstance(value, str) and _IPV4_RE.match(value.strip()):
                return value.strip()
        return None
    text = str(raw).strip().strip('"').strip("'")
    if _IPV4_RE.match(text):
        return text
    # Rare: JSON object as string
    if text.startswith("{"):
        try:
            import json as _json

            return parse_gw_ip_payload(_json.loads(text))
        except Exception:  # noqa: BLE001
            return None
    return None


class CloudAccount:
    """Panasonic Taiwan EMS account (read-only device inventory)."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        account: str,
        password: str,
        *,
        refresh_token: str | None = None,
        cp_token: str | None = None,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self._session = session
        self.account = account
        self.password = password
        self.refresh_token = refresh_token
        self.cp_token = cp_token
        self.base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict | None = None,
        json_body: Any = None,
    ) -> dict:
        url = f"{self.base_url}{path}"
        hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
        async with self._session.request(
            method,
            url,
            headers=hdrs,
            json=json_body,
            timeout=self._timeout,
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise CloudApiError(f"HTTP {resp.status}: {text[:200]}")
            try:
                import json as _json

                data = _json.loads(text)
            except Exception as err:
                raise CloudApiError(f"non-JSON response: {text[:200]}") from err
        if not isinstance(data, dict):
            raise CloudApiError(f"unexpected payload type: {type(data)}")
        return data

    async def login(self) -> None:
        data = await self._request(
            "POST",
            _LOGIN,
            json_body={
                "MemId": self.account,
                "PW": self.password,
                "AppToken": APP_TOKEN,
            },
        )
        if "CPToken" not in data or "RefreshToken" not in data:
            raise CloudAuthError(str(data)[:200])
        self.cp_token = data["CPToken"]
        self.refresh_token = data["RefreshToken"]

    async def ensure_login(self) -> None:
        if self.cp_token:
            return
        if self.refresh_token:
            try:
                await self.refresh()
                return
            except (CloudAuthError, CloudApiError):
                _LOGGER.debug("Refresh failed; falling back to password login")
        await self.login()

    async def refresh(self) -> None:
        if not self.refresh_token:
            raise CloudAuthError("no refresh token")
        data = await self._request(
            "POST",
            _REFRESH,
            json_body={"RefreshToken": self.refresh_token},
        )
        if "CPToken" not in data:
            raise CloudAuthError(str(data)[:200])
        self.cp_token = data["CPToken"]
        if data.get("RefreshToken"):
            self.refresh_token = data["RefreshToken"]

    async def async_get_devices(self) -> list[CloudDevice]:
        await self.ensure_login()
        assert self.cp_token
        try:
            data = await self._request(
                "GET",
                _DEVICES,
                headers={"cptoken": self.cp_token},
            )
        except CloudApiError:
            await self.login()
            assert self.cp_token
            data = await self._request(
                "GET",
                _DEVICES,
                headers={"cptoken": self.cp_token},
            )
        out: list[CloudDevice] = []
        for item in data.get("GwList") or []:
            if not isinstance(item, dict):
                continue
            gwid = str(item.get("GWID") or "")
            try:
                dtype = int(item.get("DeviceType") or 0)
            except (TypeError, ValueError):
                dtype = 0
            out.append(
                CloudDevice(
                    gwid=gwid,
                    auth=str(item.get("Auth") or ""),
                    nickname=str(item.get("NickName") or gwid),
                    model=str(item.get("Model") or ""),
                    model_id=str(item.get("ModelID") or ""),
                    model_type=str(item.get("ModelType") or ""),
                    device_type=dtype,
                    mac=_mac_from_gwid(gwid),
                )
            )
        return out

    async def async_get_gw_ip(self, gwid: str) -> str | None:
        """Ask EMS for the module's last-known LAN IP (UserGetGWIP)."""
        gwid = (gwid or "").strip()
        if not gwid:
            return None
        await self.ensure_login()
        assert self.cp_token
        url = f"{self.base_url}{_GW_IP}"
        hdrs = {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "CPToken": self.cp_token,
            "cptoken": self.cp_token,
        }
        try:
            async with self._session.post(
                url,
                headers=hdrs,
                json={"GWID": gwid},
                timeout=self._timeout,
            ) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    _LOGGER.debug(
                        "UserGetGWIP %s HTTP %s: %s",
                        gwid,
                        resp.status,
                        text[:120],
                    )
                    return None
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("UserGetGWIP %s failed: %s", gwid, err)
            return None
        # Prefer raw body (APK treats response as quoted IP string)
        ip = parse_gw_ip_payload(text)
        if ip:
            return ip
        try:
            import json as _json

            data = _json.loads(text)
        except Exception:  # noqa: BLE001
            return None
        return parse_gw_ip_payload(data)
