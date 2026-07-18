"""Number platform for Panasonic TaiSEIA local (timers)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode

from .capability import timer_limits
from .const import (
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    NUMBER_DEFINITIONS_AC,
    NUMBER_DEFINITIONS_DH,
    STATUS_POWER,
    TYPE_AC,
    TYPE_DEHUMIDIFIER,
)
from .entity import TaiSeiaBaseEntity


async def async_setup_entry(hass, entry, async_add_entities) -> bool:
    client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    sa_type = client.device.sa_type_id
    if sa_type == TYPE_AC:
        defs = NUMBER_DEFINITIONS_AC
    elif sa_type == TYPE_DEHUMIDIFIER:
        defs = NUMBER_DEFINITIONS_DH
    else:
        return True

    entities = []
    for row in defs:
        service, status_key, label, icon, default_min, default_max, off_only, unit = row
        if client.device.services and service not in client.device.services:
            continue
        entities.append(
            TaiSeiaTimerNumber(
                coordinator,
                client,
                entry.entry_id,
                service=service,
                status_key=status_key,
                number_label=label,
                icon_name=icon,
                default_min=default_min,
                default_max=default_max,
                available_when_off_only=off_only,
                unit=unit,
            )
        )
    async_add_entities(entities, True)
    return True


class TaiSeiaTimerNumber(TaiSeiaBaseEntity, NumberEntity):
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1

    def __init__(
        self,
        coordinator,
        client,
        entry_id,
        *,
        service: int,
        status_key: str,
        number_label: str,
        icon_name: str,
        default_min: int,
        default_max: int,
        available_when_off_only: bool,
        unit: str,
    ) -> None:
        self._service = service
        self._status_key = status_key
        self._number_label = number_label
        self._icon_name = icon_name
        self._default_min = default_min
        self._default_max = default_max
        self._available_when_off_only = available_when_off_only
        self._attr_native_unit_of_measurement = unit
        self._entity_key = f"number_{service:02x}"
        super().__init__(coordinator, client, entry_id)

    @property
    def label(self) -> str:
        return f"{self.nickname} {self._number_label}"

    @property
    def icon(self) -> str:
        return self._icon_name

    @property
    def available(self) -> bool:
        if not self.has_status(STATUS_POWER):
            return False
        if self._available_when_off_only:
            return not self.status_bool(STATUS_POWER)
        return True

    @property
    def native_value(self) -> float:
        raw = self.status_int(self._status_key, 0)
        return float(0 if raw < 0 else raw)

    @property
    def native_min_value(self) -> float:
        lo, _ = timer_limits(
            self.client, self._service, self._default_min, self._default_max
        )
        return float(lo)

    @property
    def native_max_value(self) -> float:
        _, hi = timer_limits(
            self.client, self._service, self._default_min, self._default_max
        )
        return float(hi)

    async def async_set_native_value(self, value: float) -> None:
        ivalue = int(value)
        self.set_local_status(self._status_key, str(ivalue))
        await self.client.async_write_device(self._service, ivalue)
