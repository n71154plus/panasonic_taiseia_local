"""Select platform for Panasonic TaiSEIA local."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity

from .capability import filter_option_map, supported_values
from .const import (
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    SELECT_DEFINITIONS_AC,
    SELECT_DEFINITIONS_DH,
    SELECT_DEFINITIONS_RF,
    STATUS_POWER,
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
        defs = SELECT_DEFINITIONS_AC
    elif sa_type == TYPE_DEHUMIDIFIER:
        defs = SELECT_DEFINITIONS_DH
    elif sa_type == TYPE_REFRIGERATOR:
        defs = SELECT_DEFINITIONS_RF
    else:
        return True

    entities = []
    for service, status_key, label, icon, option_map in defs:
        if client.device.services and service not in client.device.services:
            continue
        entities.append(
            TaiSeiaSelect(
                coordinator,
                client,
                entry.entry_id,
                service=service,
                status_key=status_key,
                select_label=label,
                icon_name=icon,
                option_map=option_map,
            )
        )
    async_add_entities(entities, True)
    return True


class TaiSeiaSelect(TaiSeiaBaseEntity, SelectEntity):
    def __init__(
        self,
        coordinator,
        client,
        entry_id,
        *,
        service: int,
        status_key: str,
        select_label: str,
        icon_name: str,
        option_map: dict[int, str] | None,
    ) -> None:
        self._service = service
        self._status_key = status_key
        self._select_label = select_label
        self._icon_name = icon_name
        self._option_map = option_map
        self._entity_key = f"select_{service:02x}"
        super().__init__(coordinator, client, entry_id)

    def _options_map(self) -> dict[int, str]:
        if self._option_map is not None:
            return filter_option_map(self.client, self._service, self._option_map)
        info = self.client.device.services.get(self._service)
        values = supported_values(info, list(range(-25, 8)))
        # Prefer compact range from device descriptor
        if info and info.min_value <= info.max_value and abs(info.max_value - info.min_value) < 80:
            lo, hi = info.min_value, info.max_value
            # signed byte heuristic for freezer
            if lo > 127:
                lo = lo - 256
            if hi > 127:
                hi = hi - 256
            values = list(range(lo, hi + 1))
        return {v: f"{v}°C" for v in values}

    @property
    def label(self) -> str:
        return f"{self.nickname} {self._select_label}"

    @property
    def icon(self) -> str:
        return self._icon_name

    @property
    def available(self) -> bool:
        if self.client.device.sa_type_id == TYPE_REFRIGERATOR:
            return self.has_status(self._status_key)
        return self.has_status(STATUS_POWER)

    @property
    def options(self) -> list[str]:
        return list(self._options_map().values())

    @property
    def current_option(self) -> str | None:
        raw = self.status_int(self._status_key, 0)
        # signed display for freezer-like values
        if raw > 200:
            raw = raw - 256
        opts = self._options_map()
        return opts.get(raw, f"{raw}°C" if self._option_map is None else str(raw))

    async def async_select_option(self, option: str) -> None:
        opts = self._options_map()
        value = None
        for k, v in opts.items():
            if v == option:
                value = k
                break
        if value is None:
            return
        store = value if value >= 0 else (value + 256)
        self.set_local_status(self._status_key, str(store))
        await self.client.async_write_device(self._service, store & 0xFFFF)
