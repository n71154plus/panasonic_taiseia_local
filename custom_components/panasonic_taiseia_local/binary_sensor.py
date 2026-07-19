"""Binary sensor platform — APK CommandList warning flags + TaiSEIA extras."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .catalog import extra_local_binaries, iter_kind, service_allowed
from .const import (
    DATA_CLIENT,
    DATA_COORDINATOR,
    DATA_PROFILE,
    DOMAIN,
    STATUS_POWER,
    TYPE_AC,
)
from .entity import TaiSeiaBaseEntity


async def async_setup_entry(hass, entry, async_add_entities) -> bool:
    client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    profile = hass.data[DOMAIN][entry.entry_id].get(DATA_PROFILE)

    entities: list = []
    seen: set[int] = set()

    if profile:
        for item in iter_kind(profile, "binary_sensor"):
            if not service_allowed(client.device.services, item.command.service):
                continue
            seen.add(item.command.service)
            entities.append(
                TaiSeiaBinaryFlag(
                    coordinator,
                    client,
                    entry.entry_id,
                    item.command.service,
                    item.command.name,
                    item.icon,
                    f"bin_{item.command.service:02x}",
                    BinarySensorDeviceClass.PROBLEM
                    if item.device_class_hint == "problem"
                    else None,
                )
            )

    for item in extra_local_binaries(client.device.sa_type_id, profile):
        if item.command.service in seen:
            continue
        if not service_allowed(client.device.services, item.command.service):
            continue
        entities.append(
            TaiSeiaBinaryFlag(
                coordinator,
                client,
                entry.entry_id,
                item.command.service,
                item.command.name,
                item.icon,
                f"bin_{item.command.service:02x}",
                BinarySensorDeviceClass.PROBLEM,
            )
        )

    async_add_entities(entities, True)
    return True


class TaiSeiaBinaryFlag(TaiSeiaBaseEntity, BinarySensorEntity):
    def __init__(
        self,
        coordinator,
        client,
        entry_id,
        service: int,
        label: str,
        icon: str,
        key: str,
        device_class: BinarySensorDeviceClass | None,
    ) -> None:
        self._service = service
        self._status_key = f"0x{service:02X}"
        self._label_suffix = label
        self._icon_name = icon
        self._entity_key = key
        if device_class:
            self._attr_device_class = device_class
        super().__init__(coordinator, client, entry_id)

    @property
    def label(self) -> str:
        return f"{self.nickname} {self._label_suffix}"

    @property
    def icon(self) -> str:
        return self._icon_name

    @property
    def available(self) -> bool:
        if self.client.device.sa_type_id == TYPE_AC:
            return self.has_status(STATUS_POWER) and self.has_status(self._status_key)
        return self.has_status(self._status_key)

    @property
    def is_on(self) -> bool:
        return self.status_bool(self._status_key)
