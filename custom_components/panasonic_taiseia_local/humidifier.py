"""Humidifier (dehumidifier) platform for Panasonic TaiSEIA local."""

from __future__ import annotations

import logging

from homeassistant.components.humidifier import (
    HumidifierDeviceClass,
    HumidifierEntity,
    HumidifierEntityFeature,
)

from .capability import filter_option_map
from .catalog import dehumidifier_humidity_map, dehumidifier_mode_map
from .const import (
    DATA_CLIENT,
    DATA_COORDINATOR,
    DATA_PROFILE,
    DEHUMIDIFIER_AVAILABLE_HUMIDITY,
    DEHUMIDIFIER_AVAILABLE_MODE,
    DEHUMIDIFIER_MAX_HUMD,
    DEHUMIDIFIER_MIN_HUMD,
    DOMAIN,
    LABEL_DEHUMIDIFIER,
    STATUS_MODE,
    STATUS_POWER,
    SVC_DH_HUMIDITY_SET,
    SVC_MODE,
    SVC_POWER,
    TYPE_DEHUMIDIFIER,
)
from .entity import TaiSeiaBaseEntity

_LOGGER = logging.getLogger(__package__)


def _key_from_dict(target: dict, mode_name: str):
    for key, value in target.items():
        if mode_name == value:
            return key
    return None


async def async_setup_entry(hass, entry, async_add_entities) -> bool:
    client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    profile = hass.data[DOMAIN][entry.entry_id].get(DATA_PROFILE)
    if client.device.sa_type_id != TYPE_DEHUMIDIFIER and not (
        profile and profile.device_type == 4
    ):
        return True
    async_add_entities(
        [TaiSeiaDehumidifier(coordinator, client, entry.entry_id, profile)],
        True,
    )
    return True


class TaiSeiaDehumidifier(TaiSeiaBaseEntity, HumidifierEntity):
    _entity_key = "dehumidifier"
    _attr_device_class = HumidifierDeviceClass.DEHUMIDIFIER
    _attr_supported_features = HumidifierEntityFeature.MODES

    def __init__(self, coordinator, client, entry_id, profile) -> None:
        self._profile = profile
        super().__init__(coordinator, client, entry_id)

    @property
    def label(self) -> str:
        return f"{self.nickname} {LABEL_DEHUMIDIFIER}".strip()

    @property
    def available(self) -> bool:
        return self.has_status(STATUS_POWER)

    @property
    def is_on(self) -> bool:
        return self.status_bool(STATUS_POWER)

    def _mode_map(self) -> dict[int, str]:
        base = dehumidifier_mode_map(self._profile) or DEHUMIDIFIER_AVAILABLE_MODE
        return filter_option_map(self.client, SVC_MODE, base)

    def _humidity_map(self) -> dict[int, int]:
        return dehumidifier_humidity_map(self._profile) or DEHUMIDIFIER_AVAILABLE_HUMIDITY

    @property
    def mode(self) -> str | None:
        raw = self.status_int(STATUS_MODE, 0)
        return self._mode_map().get(raw)

    @property
    def available_modes(self) -> list[str]:
        return list(self._mode_map().values())

    @property
    def target_humidity(self) -> int | None:
        raw = self.status_int(f"0x{SVC_DH_HUMIDITY_SET:02X}", 0)
        return self._humidity_map().get(raw)

    @property
    def current_humidity(self) -> int | None:
        if not self.has_status("0x07"):
            return None
        return self.status_int("0x07", 0)

    @property
    def min_humidity(self) -> int:
        vals = list(self._humidity_map().values())
        return min(vals) if vals else DEHUMIDIFIER_MIN_HUMD

    @property
    def max_humidity(self) -> int:
        vals = list(self._humidity_map().values())
        return max(vals) if vals else DEHUMIDIFIER_MAX_HUMD

    async def async_turn_on(self, **kwargs) -> None:
        self.set_local_status(STATUS_POWER, "1")
        await self.client.async_write_device(SVC_POWER, 1)

    async def async_turn_off(self, **kwargs) -> None:
        self.set_local_status(STATUS_POWER, "0")
        await self.client.async_write_device(SVC_POWER, 0)

    async def async_set_mode(self, mode: str) -> None:
        mode_id = _key_from_dict(self._mode_map(), mode)
        if mode_id is None:
            return
        self.set_local_status(STATUS_MODE, str(mode_id))
        await self.client.async_write_device(SVC_MODE, int(mode_id))

    async def async_set_humidity(self, humidity: int) -> None:
        hum_map = self._humidity_map()
        target = min(hum_map.values(), key=lambda x: abs(x - humidity))
        key = _key_from_dict(hum_map, target)
        if key is None:
            return
        self.set_local_status(f"0x{SVC_DH_HUMIDITY_SET:02X}", str(key))
        await self.client.async_write_device(SVC_DH_HUMIDITY_SET, int(key))
