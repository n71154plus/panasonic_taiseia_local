"""Switch platform — APK CommandList toggle enums."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .catalog import iter_kind, service_allowed
from .const import (
    DATA_CLIENT,
    DATA_COORDINATOR,
    DATA_PROFILE,
    DOMAIN,
    STATUS_POWER,
    TYPE_REFRIGERATOR,
)
from .entity import TaiSeiaBaseEntity

_LOGGER = logging.getLogger(__package__)

PARALLEL_UPDATES = 1


async def async_setup_entry(hass, entry, async_add_entities) -> bool:
    client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    profile = hass.data[DOMAIN][entry.entry_id].get(DATA_PROFILE)
    if not profile:
        return True

    entities = []
    for item in iter_kind(profile, "switch"):
        if not service_allowed(client.device.services, item.command.service):
            continue
        entities.append(
            TaiSeiaSwitch(
                coordinator,
                client,
                entry.entry_id,
                service=item.command.service,
                status_key=item.command.status_key,
                switch_label=item.command.name,
                icon_name=item.icon,
                inverted=item.inverted,
            )
        )
    async_add_entities(entities, True)
    return True


class TaiSeiaSwitch(TaiSeiaBaseEntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG

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
    ) -> None:
        self._service = service
        self._status_key = status_key
        self._switch_label = switch_label
        self._icon_name = icon_name
        self._inverted = inverted
        self._entity_key = f"switch_{service:02x}"
        super().__init__(coordinator, client, entry_id)

    @property
    def label(self) -> str:
        return self._switch_label

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
        if self._inverted:
            value = 0 if turn_on else 1
        else:
            value = 1 if turn_on else 0
        prev = self.device_status.get(self._status_key)
        try:
            await self.async_write_with_rollback(
                self._service, value, self._status_key, prev
            )
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err
