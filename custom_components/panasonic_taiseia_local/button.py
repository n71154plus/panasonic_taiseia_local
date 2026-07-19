"""Button platform — manual energy resets."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity

from .const import (
    CONF_ENERGY_ENABLED,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DATA_ENERGY,
    DOMAIN,
    SVC_OPERATING_POWER,
)
from .energy import async_save_tracker
from .entity import TaiSeiaBaseEntity
from .catalog import service_allowed


async def async_setup_entry(hass, entry, async_add_entities) -> bool:
    client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    if not entry.options.get(CONF_ENERGY_ENABLED, True):
        return True
    if not service_allowed(client.device.services, SVC_OPERATING_POWER):
        return True
    mac = (client.device.mac or entry.entry_id).lower()
    async_add_entities(
        [
            TaiSeiaEnergyResetButton(
                coordinator,
                client,
                entry.entry_id,
                kind="period",
                suggested_object_id=f"taiseia_{mac}_reset_period_energy",
            ),
            TaiSeiaEnergyResetButton(
                coordinator,
                client,
                entry.entry_id,
                kind="total",
                suggested_object_id=f"taiseia_{mac}_reset_total_energy",
            ),
        ],
        True,
    )
    return True


class TaiSeiaEnergyResetButton(TaiSeiaBaseEntity, ButtonEntity):
    _attr_icon = "mdi:restart"

    def __init__(
        self,
        coordinator,
        client,
        entry_id,
        *,
        kind: str,
        suggested_object_id: str,
    ) -> None:
        self._kind = kind
        self._entity_key = f"energy_reset_{kind}"
        self._attr_suggested_object_id = suggested_object_id
        super().__init__(coordinator, client, entry_id)

    @property
    def label(self) -> str:
        if self._kind == "total":
            return f"{self.nickname} 重置累計耗電"
        return f"{self.nickname} 重置本期耗電"

    async def async_press(self) -> None:
        tracker = self.hass.data[DOMAIN][self.entry_id].get(DATA_ENERGY)
        if tracker is None:
            return
        if self._kind == "total":
            tracker.reset_total()
        else:
            tracker.reset_period()
        await async_save_tracker(self.hass, self.entry_id, tracker)
        # Refresh coordinator payload so sensors update immediately
        data = dict(self.coordinator.data or {})
        data["energy_total_kwh"] = tracker.total_kwh
        data["energy_monthly_kwh"] = tracker.period_kwh
        data["energy_period_kwh"] = tracker.period_kwh
        data["energy_month_key"] = tracker.period_key
        data["energy_period_key"] = tracker.period_key
        self.coordinator.async_set_updated_data(data)
