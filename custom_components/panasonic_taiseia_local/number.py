"""Number platform — APK CommandList range parameters (timers etc.)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode

from .capability import timer_limits
from .catalog import iter_kind, service_allowed
from .const import (
    DATA_CLIENT,
    DATA_COORDINATOR,
    DATA_PROFILE,
    DOMAIN,
    STATUS_POWER,
    UNIT_MINUTE,
)
from .entity import TaiSeiaBaseEntity


async def async_setup_entry(hass, entry, async_add_entities) -> bool:
    client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    profile = hass.data[DOMAIN][entry.entry_id].get(DATA_PROFILE)
    if not profile:
        return True

    entities = []
    for item in iter_kind(profile, "number"):
        if not service_allowed(client.device.services, item.command.service):
            continue
        unit = item.command.unit or UNIT_MINUTE
        # Dehumidifier timers in APK are often hours (max 12)
        lo = item.range_min if item.range_min is not None else 0
        hi = item.range_max if item.range_max is not None else 1440
        if hi <= 24 and "時間" in item.command.name:
            unit = "小時"
        # On-timer typically only when powered off
        off_only = "開" in item.command.name and "關" not in item.command.name
        entities.append(
            TaiSeiaTimerNumber(
                coordinator,
                client,
                entry.entry_id,
                service=item.command.service,
                status_key=item.command.status_key,
                number_label=item.command.name,
                icon_name=item.icon,
                default_min=lo,
                default_max=hi,
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
            return self.has_status(self._status_key)
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
        await self.async_device_write(self._service, ivalue)
