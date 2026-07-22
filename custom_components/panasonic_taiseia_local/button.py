"""Button platform — energy resets + filter cleaned."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError

from .catalog import service_allowed
from .const import (
    CONF_ENERGY_ENABLED,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DATA_ENERGY,
    DOMAIN,
    ICON_FILTER,
    LABEL_FILTER_NOTIFY,
    STATUS_FILTER_NOTIFY,
    SVC_FILTER_NOTIFY,
    SVC_OPERATING_POWER,
    TYPE_AC,
)
from .energy import async_save_tracker
from .entity import TaiSeiaBaseEntity


async def async_setup_entry(hass, entry, async_add_entities) -> bool:
    client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    mac = (client.device.mac or entry.entry_id).lower()
    entities: list = []

    # TaiSEIA 0x12 WRITE 0 = reset filter-clean notify ("濾網已清洗")
    if client.device.sa_type_id == TYPE_AC and service_allowed(
        client.device.services, SVC_FILTER_NOTIFY
    ):
        entities.append(
            TaiSeiaFilterCleanedButton(
                coordinator,
                client,
                entry.entry_id,
                suggested_object_id=f"taiseia_{mac}_filter_cleaned",
            )
        )

    if entry.options.get(CONF_ENERGY_ENABLED, True) and service_allowed(
        client.device.services, SVC_OPERATING_POWER
    ):
        entities.extend(
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
            ]
        )

    if entities:
        async_add_entities(entities, True)
    return True


class TaiSeiaFilterCleanedButton(TaiSeiaBaseEntity, ButtonEntity):
    """Press after cleaning the filter — clears the 須清洗 flag on the AC."""

    _attr_icon = ICON_FILTER

    def __init__(
        self,
        coordinator,
        client,
        entry_id,
        *,
        suggested_object_id: str,
    ) -> None:
        self._entity_key = "filter_cleaned"
        self._attr_suggested_object_id = suggested_object_id
        super().__init__(coordinator, client, entry_id)

    @property
    def label(self) -> str:
        return f"{self.nickname} 濾網已清洗"

    async def async_press(self) -> None:
        try:
            await self.async_device_write(SVC_FILTER_NOTIFY, 0)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(
                f"無法重置{LABEL_FILTER_NOTIFY}: {err}"
            ) from err
        self.set_local_status(STATUS_FILTER_NOTIFY, "0")
        await self.coordinator.async_request_refresh()


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
        data = dict(self.coordinator.data or {})
        data["energy_total_kwh"] = tracker.total_kwh
        data["energy_monthly_kwh"] = tracker.period_kwh
        data["energy_period_kwh"] = tracker.period_kwh
        data["energy_month_key"] = tracker.period_key
        data["energy_period_key"] = tracker.period_key
        self.coordinator.async_set_updated_data(data)
