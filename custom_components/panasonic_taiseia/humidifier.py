"""Humidifier (dehumidifier) platform for Panasonic TaiSEIA local."""

from __future__ import annotations

import logging

from homeassistant.components.humidifier import (
    HumidifierDeviceClass,
    HumidifierEntity,
    HumidifierEntityFeature,
)

from .capability import filter_option_map
from .const import (
    DATA_CLIENT,
    DATA_COORDINATOR,
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
    if client.device.sa_type_id != TYPE_DEHUMIDIFIER:
        return True
    async_add_entities(
        [TaiSeiaDehumidifier(coordinator, client, entry.entry_id)],
        True,
    )
    return True


class TaiSeiaDehumidifier(TaiSeiaBaseEntity, HumidifierEntity):
    _entity_key = "dehumidifier"
    _attr_device_class = HumidifierDeviceClass.DEHUMIDIFIER
    _attr_supported_features = HumidifierEntityFeature.MODES

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
        return filter_option_map(self.client, SVC_MODE, DEHUMIDIFIER_AVAILABLE_MODE)

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
        return DEHUMIDIFIER_AVAILABLE_HUMIDITY.get(raw)

    @property
    def current_humidity(self) -> int | None:
        # 0x07 indoor humidity
        if not self.has_status("0x07"):
            return None
        return self.status_int("0x07", 0)

    @property
    def min_humidity(self) -> int:
        return DEHUMIDIFIER_MIN_HUMD

    @property
    def max_humidity(self) -> int:
        return DEHUMIDIFIER_MAX_HUMD

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
        target = min(
            DEHUMIDIFIER_AVAILABLE_HUMIDITY.values(),
            key=lambda x: abs(x - humidity),
        )
        key = _key_from_dict(DEHUMIDIFIER_AVAILABLE_HUMIDITY, target)
        if key is None:
            return
        self.set_local_status(f"0x{SVC_DH_HUMIDITY_SET:02X}", str(key))
        await self.client.async_write_device(SVC_DH_HUMIDITY_SET, int(key))
