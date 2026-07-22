"""Panasonic Taiwan EMS cloud client — APK contract (login + control + status).

Paths/headers match official IoT TW APK BaseEmsApiService:
  GET  /api/DeviceSetCommand?DeviceID=1  (CPToken, auth, GWID + CommandType/Value)
  POST /api/DeviceGetInfo               (CPToken, auth, GWID + body)
Transport/rate-limit: ems_transport.EmsTransport (not community smart_app).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import aiohttp

from .ems_transport import (
    CloudApiError,
    CloudAuthError,
    CloudDeviceOffline,
    CloudRateLimited,
    EmsGate,
    EmsSettings,
    EmsTransport,
    RequestPriority,
)

_LOGGER = logging.getLogger(__package__)

BASE_URL = "https://ems2.panasonic.com.tw/api"
APP_TOKEN = "D8CBFF4C-2824-4342-B22D-189166FEF503"
_LOGIN = "/userlogin1"
_REFRESH = "/RefreshToken1"
_DEVICES = "/UserGetRegisteredGwList2"
_GW_IP = "/UserGetGWIP"
_SET_COMMAND = "/DeviceSetCommand"
_GET_INFO = "/DeviceGetInfo"
_OVERVIEW = "/UserGetDeviceStatus"

_MAC_RE = re.compile(r"^[0-9A-Fa-f]{12}$")
_IPV4_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d?\d)$"
)

# Re-export for callers
__all__ = [
    "BASE_URL",
    "APP_TOKEN",
    "CloudAccount",
    "CloudApiError",
    "CloudAuthError",
    "CloudDevice",
    "CloudDeviceOffline",
    "CloudRateLimited",
    "command_type_hex",
    "parse_device_get_info",
    "parse_gw_ip_payload",
]


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


def command_type_hex(service: int) -> str:
    """APK portal passes CommandType as hex string e.g. '0x00'."""
    return f"0x{int(service) & 0xFF:02X}"


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
    if text.startswith("{"):
        try:
            import json as _json

            return parse_gw_ip_payload(_json.loads(text))
        except Exception:  # noqa: BLE001
            return None
    return None


def parse_device_get_info(payload: Any) -> dict[str, str]:
    """Map DeviceGetInfoV0 → status dict keyed like LAN ('0x00', ...)."""
    result: dict[str, str] = {}
    if not isinstance(payload, dict):
        return result
    devices = payload.get("devices") or payload.get("Devices") or []
    if not devices:
        return result
    device = devices[0] if isinstance(devices, list) else devices
    if not isinstance(device, dict):
        return result
    infos = device.get("Info") or device.get("info") or []
    for info in infos:
        if not isinstance(info, dict):
            continue
        ctype = str(info.get("CommandType") or info.get("commandType") or "")
        status = info.get("status", info.get("Status"))
        if not ctype:
            continue
        # Normalize to 0xNN
        key = ctype if ctype.lower().startswith("0x") else f"0x{int(ctype):02X}"
        try:
            # Prefer uppercase 0xNN
            key = f"0x{int(key, 16):02X}"
        except ValueError:
            key = ctype
        if status is None:
            continue
        result[key] = str(status)
    return result


def build_device_get_info_body(
    command_types: list[str], *, device_id: int = 1
) -> list[dict[str, Any]]:
    """APK DeviceGetInfo body: JSON array of {DeviceID, CommandTypes[]}."""
    return [
        {
            "DeviceID": device_id,
            "CommandTypes": [{"CommandType": ct} for ct in command_types],
        }
    ]


class CloudAccount:
    """Panasonic Taiwan EMS account (inventory + set/get per APK)."""

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
        gate: EmsGate | None = None,
        transport: EmsTransport | None = None,
    ) -> None:
        self._session = session
        self.account = account
        self.password = password
        self.refresh_token = refresh_token
        self.cp_token = cp_token
        settings = EmsSettings(
            timeout=timeout,
            base_urls=[base_url.rstrip("/")],
        )
        self._gate = gate or EmsGate(settings)
        if transport is not None:
            self._transport = transport
        else:
            self._transport = EmsTransport(session, self._gate, settings)

    @property
    def transport(self) -> EmsTransport:
        return self._transport

    async def _raw(
        self,
        method: str,
        path: str,
        *,
        headers: dict | None = None,
        params: dict | None = None,
        json_body: Any = None,
        priority: RequestPriority = RequestPriority.NORMAL,
        expect_json: bool = True,
    ) -> Any:
        return await self._transport.request(
            method,
            path,
            headers=headers,
            params=params,
            json_body=json_body,
            priority=priority,
            expect_json=expect_json,
        )

    async def login(self) -> None:
        data = await self._raw(
            "POST",
            _LOGIN,
            json_body={
                "MemId": self.account,
                "PW": self.password,
                "AppToken": APP_TOKEN,
            },
            priority=RequestPriority.USER,
        )
        if not isinstance(data, dict) or "CPToken" not in data or "RefreshToken" not in data:
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
        data = await self._raw(
            "POST",
            _REFRESH,
            json_body={"RefreshToken": self.refresh_token},
            priority=RequestPriority.USER,
        )
        if not isinstance(data, dict) or "CPToken" not in data:
            raise CloudAuthError(str(data)[:200])
        self.cp_token = data["CPToken"]
        if data.get("RefreshToken"):
            self.refresh_token = data["RefreshToken"]

    def _auth_headers(self, *, auth: str | None = None, gwid: str | None = None) -> dict[str, str]:
        assert self.cp_token
        hdrs = {
            "CPToken": self.cp_token,
            "cptoken": self.cp_token,
            "Content-Type": "application/json",
        }
        if auth:
            hdrs["auth"] = auth
        if gwid:
            hdrs["GWID"] = gwid
        return hdrs

    async def _with_auth_retry(self, factory):
        await self.ensure_login()
        try:
            return await factory()
        except CloudAuthError:
            await self.login()
            return await factory()

    async def async_get_devices(self) -> list[CloudDevice]:
        async def _call():
            assert self.cp_token
            return await self._raw(
                "GET",
                _DEVICES,
                headers={"cptoken": self.cp_token, "CPToken": self.cp_token},
                priority=RequestPriority.NORMAL,
            )

        data = await self._with_auth_retry(_call)
        out: list[CloudDevice] = []
        if not isinstance(data, dict):
            return out
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

        async def _call():
            assert self.cp_token
            return await self._raw(
                "POST",
                _GW_IP,
                headers=self._auth_headers(),
                json_body={"GWID": gwid},
                priority=RequestPriority.BACKGROUND,
                expect_json=False,
            )

        try:
            text = await self._with_auth_retry(_call)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("UserGetGWIP %s failed: %s", gwid, err)
            return None
        ip = parse_gw_ip_payload(text if isinstance(text, str) else None)
        if ip:
            return ip
        if isinstance(text, str):
            try:
                import json as _json

                return parse_gw_ip_payload(_json.loads(text))
            except Exception:  # noqa: BLE001
                return None
        return parse_gw_ip_payload(text if isinstance(text, dict) else None)

    async def async_set_command(
        self,
        *,
        auth: str,
        gwid: str,
        command_type: str | int,
        value: int | str,
        device_id: int = 1,
        priority: RequestPriority = RequestPriority.USER,
    ) -> Any:
        """APK getDeviceSetCommandType — GET DeviceSetCommand with headers."""
        ctype = (
            command_type
            if isinstance(command_type, str)
            else command_type_hex(int(command_type))
        )
        # Portal uses decimal string values ("0"/"1"); accept int too.
        val = str(value)

        async def _call():
            assert self.cp_token
            return await self._raw(
                "GET",
                _SET_COMMAND,
                headers=self._auth_headers(auth=auth, gwid=gwid),
                params={
                    "DeviceID": str(device_id),
                    "CommandType": ctype,
                    "Value": val,
                },
                priority=priority,
            )

        return await self._with_auth_retry(_call)

    async def async_get_device_info(
        self,
        *,
        auth: str,
        gwid: str,
        command_types: list[str],
        device_id: int = 1,
        priority: RequestPriority = RequestPriority.BACKGROUND,
    ) -> dict[str, str]:
        """APK postDeviceGetInfo — returns normalized status map."""
        body = build_device_get_info_body(command_types, device_id=device_id)

        async def _call():
            assert self.cp_token
            return await self._raw(
                "POST",
                _GET_INFO,
                headers=self._auth_headers(auth=auth, gwid=gwid),
                json_body=body,
                priority=priority,
            )

        payload = await self._with_auth_retry(_call)
        return parse_device_get_info(payload)

    async def async_get_overview(self) -> dict[str, dict[str, str]]:
        """UserGetDeviceStatus — gwid → status map (assist / batch)."""

        async def _call():
            assert self.cp_token
            return await self._raw(
                "GET",
                _OVERVIEW,
                headers={"CPToken": self.cp_token, "cptoken": self.cp_token},
                priority=RequestPriority.BACKGROUND,
            )

        data = await self._with_auth_retry(_call)
        result: dict[str, dict[str, str]] = {}
        if not isinstance(data, dict):
            return result
        for device in data.get("GwList") or []:
            if not isinstance(device, dict):
                continue
            gwid = str(device.get("GWID") or "")
            status: dict[str, str] = {}
            for info in device.get("List") or []:
                if not isinstance(info, dict):
                    continue
                ctype = str(info.get("CommandType") or "")
                raw = info.get("Status", info.get("status"))
                if not ctype or raw is None:
                    continue
                try:
                    key = f"0x{int(ctype, 16):02X}"
                except ValueError:
                    key = ctype
                status[key] = str(raw)
            if gwid:
                result[gwid] = status
        return result
