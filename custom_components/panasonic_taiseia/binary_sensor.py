"""Binary sensor platform for Panasonic TaiSEIA local."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .const import (
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    ICON_DEFROST,
    ICON_ECONAVI,
    ICON_FILTER,
    ICON_NANOE,
    ICON_TANK,
    LABEL_FILTER_NOTIFY,
    LABEL_RF_DEFROST,
    LABEL_RF_ECO,
    LABEL_NANOE,
    LABEL_TANK,
    STATUS_FILTER_NOTIFY,
    STATUS_POWER,
    SVC_DH_TANK,
    SVC_FILTER_NOTIFY,
    SVC_RF_DEFROST,
    SVC_RF_ECO,
    SVC_RF_NANOE,
    TYPE_AC,
    TYPE_DEHUMIDIFIER,
    TYPE_REFRIGERATOR,
)
from .entity import TaiSeiaBaseEntity


async def async_setup_entry(hass, entry, async_add_entities) -> bool:
    client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    entities = []
    sa = client.device.sa_type_id
    svc = client.device.services

    def has(service: int) -> bool:
        return (not svc) or service in svc

    if sa == TYPE_AC and has(SVC_FILTER_NOTIFY):
        entities.append(TaiSeiaFilterNotify(coordinator, client, entry.entry_id))
    if sa == TYPE_DEHUMIDIFIER and has(SVC_DH_TANK):
        entities.append(
            TaiSeiaBinaryFlag(
                coordinator,
                client,
                entry.entry_id,
                SVC_DH_TANK,
                LABEL_TANK,
                ICON_TANK,
                "tank",
                BinarySensorDeviceClass.PROBLEM,
            )
        )
    if sa == TYPE_REFRIGERATOR:
        for service, label, icon, key, device_class in (
            (SVC_RF_DEFROST, LABEL_RF_DEFROST, ICON_DEFROST, "rf_defrost", BinarySensorDeviceClass.RUNNING),
            (SVC_RF_ECO, LABEL_RF_ECO, ICON_ECONAVI, "rf_eco", None),
            (SVC_RF_NANOE, LABEL_NANOE, ICON_NANOE, "rf_nanoe", None),
        ):
            if has(service):
                entities.append(
                    TaiSeiaBinaryFlag(
                        coordinator,
                        client,
                        entry.entry_id,
                        service,
                        label,
                        icon,
                        key,
                        device_class,
                    )
                )
    async_add_entities(entities, True)
    return True


class TaiSeiaFilterNotify(TaiSeiaBaseEntity, BinarySensorEntity):
    _entity_key = "filter_notify"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def label(self) -> str:
        return f"{self.nickname} {LABEL_FILTER_NOTIFY}"

    @property
    def icon(self) -> str:
        return ICON_FILTER

    @property
    def available(self) -> bool:
        return self.has_status(STATUS_POWER) and self.has_status(STATUS_FILTER_NOTIFY)

    @property
    def is_on(self) -> bool:
        return self.status_int(STATUS_FILTER_NOTIFY, 0) != 0


class TaiSeiaBinaryFlag(TaiSeiaBaseEntity, BinarySensorEntity):
    def __init__(
        self,
        coordinator,
        client,
        entry_id,
        service,
        label,
        icon,
        key,
        device_class,
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
        return self.has_status(self._status_key)

    @property
    def is_on(self) -> bool:
        return self.status_bool(self._status_key)
