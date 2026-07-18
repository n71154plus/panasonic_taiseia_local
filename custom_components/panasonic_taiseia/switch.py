"""Switch platform for Panasonic TaiSEIA local."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    STATUS_POWER,
    SWITCH_DEFINITIONS_AC,
    SWITCH_DEFINITIONS_DH,
    SWITCH_DEFINITIONS_RF,
    TYPE_AC,
    TYPE_DEHUMIDIFIER,
    TYPE_REFRIGERATOR,
)
from .entity import TaiSeiaBaseEntity

_LOGGER = logging.getLogger(__package__)


async def async_setup_entry(hass, entry, async_add_entities) -> bool:
    client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    sa_type = client.device.sa_type_id
    if sa_type == TYPE_AC:
        defs = SWITCH_DEFINITIONS_AC
    elif sa_type == TYPE_DEHUMIDIFIER:
        defs = SWITCH_DEFINITIONS_DH
    elif sa_type == TYPE_REFRIGERATOR:
        defs = SWITCH_DEFINITIONS_RF
    else:
        return True

    entities = []
    for service, status_key, label, icon, inverted, require_power in defs:
        if client.device.services and service not in client.device.services:
            continue
        entities.append(
            TaiSeiaSwitch(
                coordinator,
                client,
                entry.entry_id,
                service=service,
                status_key=status_key,
                switch_label=label,
                icon_name=icon,
                inverted=inverted,
                require_power=require_power,
            )
        )
    async_add_entities(entities, True)
    return True


class TaiSeiaSwitch(TaiSeiaBaseEntity, SwitchEntity):
    def __init__(
        self,
        coordinator,
        client,
        entry_id,
        *,
        service: int,
        status_key: str,
        switch_label: str,
        icon_name: str,
        inverted: bool,
        require_power: bool,
    ) -> None:
        self._service = service
        self._status_key = status_key
        self._switch_label = switch_label
        self._icon_name = icon_name
        self._inverted = inverted
        self._require_power = require_power
        self._entity_key = f"switch_{service:02x}"
        super().__init__(coordinator, client, entry_id)

    @property
    def label(self) -> str:
        return f"{self.nickname} {self._switch_label}"

    @property
    def icon(self) -> str:
        return self._icon_name

    @property
    def available(self) -> bool:
        if self.client.device.sa_type_id == TYPE_REFRIGERATOR:
            return self.has_status(self._status_key)
        return self.has_status(STATUS_POWER)

    @property
    def is_on(self) -> bool:
        raw = self.status_bool(self._status_key)
        return (not raw) if self._inverted else raw

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(False)

    async def _async_set(self, turn_on: bool) -> None:
        if self._require_power and not self.status_bool(STATUS_POWER):
            raise HomeAssistantError("請先開啟電源")
        if self._inverted:
            value = 0 if turn_on else 1
        else:
            value = 1 if turn_on else 0
        self.set_local_status(self._status_key, str(value))
        await self.client.async_write_device(self._service, value)
