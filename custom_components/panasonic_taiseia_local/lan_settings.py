"""Shared LAN request behaviour (timeout / retry / concurrency)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    CONF_MAX_CONCURRENT,
    CONF_REQUEST_RETRIES,
    CONF_REQUEST_RETRY_DELAY,
    CONF_REQUEST_TIMEOUT,
    DEFAULT_MAX_CONCURRENT,
    DEFAULT_REQUEST_RETRIES,
    DEFAULT_REQUEST_RETRY_DELAY,
    DEFAULT_REQUEST_TIMEOUT,
    DOMAIN,
)

STORAGE_VERSION = 1


@dataclass
class LanSettings:
    timeout: float = DEFAULT_REQUEST_TIMEOUT
    retries: int = DEFAULT_REQUEST_RETRIES
    retry_delay: float = DEFAULT_REQUEST_RETRY_DELAY
    max_concurrent: int = DEFAULT_MAX_CONCURRENT

    def as_dict(self) -> dict[str, Any]:
        return {
            CONF_REQUEST_TIMEOUT: self.timeout,
            CONF_REQUEST_RETRIES: self.retries,
            CONF_REQUEST_RETRY_DELAY: self.retry_delay,
            CONF_MAX_CONCURRENT: self.max_concurrent,
        }


def _clamp(settings: LanSettings) -> LanSettings:
    settings.timeout = max(2.0, min(60.0, float(settings.timeout)))
    settings.retries = max(1, min(10, int(settings.retries)))
    settings.retry_delay = max(0.1, min(10.0, float(settings.retry_delay)))
    settings.max_concurrent = max(1, min(8, int(settings.max_concurrent)))
    return settings


async def async_get_lan_settings(hass: HomeAssistant) -> LanSettings:
    store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_lan_settings")
    raw = await store.async_load()
    if not isinstance(raw, dict):
        return LanSettings()
    try:
        return _clamp(
            LanSettings(
                timeout=float(raw.get(CONF_REQUEST_TIMEOUT) or DEFAULT_REQUEST_TIMEOUT),
                retries=int(raw.get(CONF_REQUEST_RETRIES) or DEFAULT_REQUEST_RETRIES),
                retry_delay=float(
                    raw.get(CONF_REQUEST_RETRY_DELAY) or DEFAULT_REQUEST_RETRY_DELAY
                ),
                max_concurrent=int(
                    raw.get(CONF_MAX_CONCURRENT) or DEFAULT_MAX_CONCURRENT
                ),
            )
        )
    except (TypeError, ValueError):
        return LanSettings()


async def async_save_lan_settings(hass: HomeAssistant, settings: LanSettings) -> None:
    store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_lan_settings")
    await store.async_save(_clamp(settings).as_dict())
