"""EMS HTTP transport: min-interval gate, multi-base failover, rate-limit handling.

Behaviour informed by real EMS limits (429 / WAF / StateMsg); structure is a
clean gate + transport — not a port of community decorator-based clients.
APK contract for paths/headers lives in cloud.py.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import IntEnum
from http import HTTPStatus
from typing import Any

import aiohttp

from .const import (
    DEFAULT_EMS_MIN_INTERVAL,
    DEFAULT_EMS_RATE_LIMIT_BACKOFF,
    DEFAULT_EMS_TIMEOUT,
    DEFAULT_EMS_WAF_BACKOFF,
)

_LOGGER = logging.getLogger(__package__)

USER_AGENT = "okhttp/4.9.1"

# Official EMS StateMsg fragments (APK / live EMS)
MSG_RATE_LIMIT = "系統檢測您當前超量使用"
MSG_TOKEN_EXPIRED = "無法依據您的CPToken"
MSG_CPTOKEN_EXPIRED = "此CPToken已經逾時"
MSG_INVALID_REFRESH = "無效RefreshToken"
MSG_DEVICE_OFFLINE = (
    "deviceOffline",
    "deviceNoResponse",
    "DeviceJPInfo",
)


class RequestPriority(IntEnum):
    BACKGROUND = 0
    NORMAL = 1
    USER = 2


class CloudAuthError(Exception):
    """Login / token failure."""


class CloudApiError(Exception):
    """Unexpected API response."""


class CloudRateLimited(CloudApiError):
    """EMS rate limit / all bases cooling down."""


class CloudDeviceOffline(CloudApiError):
    """Device unreachable via EMS."""


@dataclass
class EmsSettings:
    min_interval: float = DEFAULT_EMS_MIN_INTERVAL
    timeout: float = DEFAULT_EMS_TIMEOUT
    rate_limit_backoff: float = DEFAULT_EMS_RATE_LIMIT_BACKOFF
    waf_backoff: float = DEFAULT_EMS_WAF_BACKOFF
    base_urls: list[str] = field(
        default_factory=lambda: ["https://ems2.panasonic.com.tw/api"]
    )


class EmsGate:
    """Process-wide spacing for EMS calls (single lock + min interval)."""

    def __init__(self, settings: EmsSettings | None = None) -> None:
        self.settings = settings or EmsSettings()
        self._lock = asyncio.Lock()
        self._last_done = 0.0

    def apply_settings(self, settings: EmsSettings) -> None:
        self.settings = settings

    async def run(
        self,
        coro_factory,
        *,
        priority: RequestPriority = RequestPriority.NORMAL,
    ):
        """Serialize EMS work with min_interval. priority reserved for future queue."""
        _ = priority
        async with self._lock:
            gap = self.settings.min_interval - (time.monotonic() - self._last_done)
            if gap > 0:
                await asyncio.sleep(gap)
            try:
                return await coro_factory()
            finally:
                self._last_done = time.monotonic()


def _is_waf_block(status: int, body: str) -> bool:
    if status in (403, 503) and body:
        lowered = body.lower()
        return any(
            m in lowered
            for m in (
                "access denied",
                "edgesuite.net",
                "errors.edgesuite.net",
                "you don't have permission to access",
            )
        )
    return False


def classify_state_msg(msg: str | None) -> type[Exception] | None:
    if not msg:
        return None
    if MSG_RATE_LIMIT in msg:
        return CloudRateLimited
    if MSG_INVALID_REFRESH in msg or MSG_TOKEN_EXPIRED in msg or MSG_CPTOKEN_EXPIRED in msg:
        return CloudAuthError
    if any(x in msg for x in MSG_DEVICE_OFFLINE):
        return CloudDeviceOffline
    return None


class EmsTransport:
    """HTTP helper with per-base cooldown and optional multi-base failover."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        gate: EmsGate,
        settings: EmsSettings | None = None,
    ) -> None:
        self._session = session
        self.gate = gate
        self.settings = settings or gate.settings
        self._base_index = 0
        self._blocked_until: dict[str, float] = {}

    def _available_bases(self) -> list[str]:
        now = time.monotonic()
        bases = self.settings.base_urls
        avail = [b for b in bases if self._blocked_until.get(b, 0) <= now]
        if avail:
            return avail
        return sorted(bases, key=lambda b: self._blocked_until.get(b, 0))

    def _next_base(self) -> str:
        avail = self._available_bases()
        base = avail[self._base_index % len(avail)]
        self._base_index += 1
        return base

    def _mark_blocked(self, base: str, seconds: float, reason: str) -> None:
        until = time.monotonic() + seconds
        self._blocked_until[base] = until
        _LOGGER.warning("EMS base %s blocked %.0fs (%s)", base, seconds, reason)

    def in_cooldown(self) -> bool:
        now = time.monotonic()
        return all(self._blocked_until.get(b, 0) > now for b in self.settings.base_urls)

    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        data: Any = None,
        priority: RequestPriority = RequestPriority.NORMAL,
        expect_json: bool = True,
    ) -> Any:
        async def _do():
            return await self._request_once(
                method,
                path,
                headers=headers,
                params=params,
                json_body=json_body,
                data=data,
                expect_json=expect_json,
            )

        return await self.gate.run(_do, priority=priority)

    async def _request_once(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None,
        params: dict[str, Any] | None,
        json_body: Any,
        data: Any,
        expect_json: bool,
    ) -> Any:
        last_rate = False
        last_err = ""
        timeout = aiohttp.ClientTimeout(total=self.settings.timeout)
        bases = self._available_bases()
        # Try preferred rotation then remaining
        ordered = []
        preferred = self._next_base()
        ordered.append(preferred)
        for b in bases:
            if b not in ordered:
                ordered.append(b)

        for base in ordered:
            url = f"{base.rstrip('/')}{path}" if path.startswith("/") else path
            hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
            try:
                async with self._session.request(
                    method,
                    url,
                    headers=hdrs,
                    params=params,
                    json=json_body,
                    data=data,
                    timeout=timeout,
                ) as resp:
                    text = await resp.text()
                    if resp.status == HTTPStatus.OK:
                        if not expect_json:
                            return text
                        if not text.strip():
                            return {}
                        import json as _json

                        try:
                            return _json.loads(text)
                        except Exception as err:
                            raise CloudApiError(
                                f"non-JSON response: {text[:200]}"
                            ) from err

                    if resp.status == HTTPStatus.TOO_MANY_REQUESTS:
                        last_rate = True
                        self._mark_blocked(
                            base, self.settings.rate_limit_backoff, "HTTP 429"
                        )
                        continue

                    if _is_waf_block(resp.status, text):
                        self._mark_blocked(
                            base, self.settings.waf_backoff, f"WAF {resp.status}"
                        )
                        continue

                    # 417 Expectation Failed — EMS often puts StateMsg here
                    state_msg = None
                    try:
                        import json as _json

                        payload = _json.loads(text) if text else {}
                        if isinstance(payload, dict):
                            state_msg = payload.get("StateMsg")
                    except Exception:  # noqa: BLE001
                        payload = {}

                    cls = classify_state_msg(str(state_msg) if state_msg else None)
                    if cls is CloudRateLimited:
                        last_rate = True
                        self._mark_blocked(
                            base,
                            self.settings.rate_limit_backoff,
                            "StateMsg rate limit",
                        )
                        continue
                    if cls is CloudAuthError:
                        raise CloudAuthError(str(state_msg)[:200])
                    if cls is CloudDeviceOffline:
                        raise CloudDeviceOffline(str(state_msg)[:200])

                    last_err = text[:200]
                    if resp.status >= 400:
                        raise CloudApiError(f"HTTP {resp.status}: {last_err}")

            except (CloudAuthError, CloudDeviceOffline, CloudApiError):
                raise
            except Exception as err:  # noqa: BLE001
                last_err = f"{type(err).__name__}: {err}"
                _LOGGER.debug("EMS request to %s failed: %s", base, last_err)
                continue

        if last_rate or self.in_cooldown():
            raise CloudRateLimited(last_err or "EMS rate limited")
        raise CloudApiError(last_err or "EMS request failed")
