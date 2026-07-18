"""Sensor platform for Panasonic TaiSEIA local."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    PERCENTAGE,
    UnitOfPower,
    UnitOfTemperature,
)

from .const import (
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    ICON_FREEZER,
    ICON_FRIDGE,
    ICON_HUMIDITY,
    ICON_PM25,
    ICON_POWER,
    ICON_THERMOMETER,
    LABEL_HUMIDITY,
    LABEL_OPERATING_POWER,
    LABEL_OUTDOOR_TEMPERATURE,
    LABEL_PM10,
    LABEL_PM25,
    LABEL_RF_FREEZER_TEMP,
    LABEL_RF_FRIDGE_TEMP,
    LABEL_RF_PARTIAL_TEMP,
    LABEL_RF_RAPID,
    LABEL_RF_SHOPPING,
    LABEL_RF_VACATION,
    LABEL_RF_WINTER,
    STATUS_OPERATING_POWER,
    STATUS_PM25,
    STATUS_PM25_FLAG,
    STATUS_POWER,
    STATUS_TEMP_OUT,
    SVC_DH_HUMIDITY_IN,
    SVC_DH_PM10,
    SVC_DH_PM25,
    SVC_OPERATING_POWER,
    SVC_PM25,
    SVC_RF_FREEZER_TEMP,
    SVC_RF_FRIDGE_TEMP,
    SVC_RF_PARTIAL_TEMP,
    SVC_RF_RAPID_FREEZE,
    SVC_RF_SHOPPING,
    SVC_RF_VACATION,
    SVC_RF_WINTER,
    SVC_TEMP_OUT,
    TYPE_AC,
    TYPE_DEHUMIDIFIER,
    TYPE_REFRIGERATOR,
)
from .entity import TaiSeiaBaseEntity


def _signed(raw: int) -> int:
    if raw > 200:
        return raw - 256
    return raw


async def async_setup_entry(hass, entry, async_add_entities) -> bool:
    client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    entities: list = []
    sa = client.device.sa_type_id
    svc = client.device.services

    def has(service: int) -> bool:
        return (not svc) or service in svc

    if sa == TYPE_AC:
        if has(SVC_TEMP_OUT):
            entities.append(TaiSeiaOutdoorTemperature(coordinator, client, entry.entry_id))
        if has(SVC_PM25):
            entities.append(TaiSeiaPM25(coordinator, client, entry.entry_id, SVC_PM25, LABEL_PM25, "pm25"))
        if has(SVC_OPERATING_POWER):
            entities.append(TaiSeiaOperatingPower(coordinator, client, entry.entry_id))
    elif sa == TYPE_DEHUMIDIFIER:
        if has(SVC_DH_HUMIDITY_IN):
            entities.append(TaiSeiaHumidity(coordinator, client, entry.entry_id))
        if has(SVC_DH_PM25):
            entities.append(
                TaiSeiaPM25(coordinator, client, entry.entry_id, SVC_DH_PM25, LABEL_PM25, "pm25")
            )
        if has(SVC_DH_PM10):
            entities.append(
                TaiSeiaPM25(coordinator, client, entry.entry_id, SVC_DH_PM10, LABEL_PM10, "pm10")
            )
    elif sa == TYPE_REFRIGERATOR:
        for service, label, icon, key in (
            (SVC_RF_FREEZER_TEMP, LABEL_RF_FREEZER_TEMP, ICON_FREEZER, "rf_freezer"),
            (SVC_RF_FRIDGE_TEMP, LABEL_RF_FRIDGE_TEMP, ICON_FRIDGE, "rf_fridge"),
            (SVC_RF_PARTIAL_TEMP, LABEL_RF_PARTIAL_TEMP, ICON_FREEZER, "rf_partial"),
        ):
            if has(service):
                entities.append(
                    TaiSeiaFridgeTemp(coordinator, client, entry.entry_id, service, label, icon, key)
                )
        for service, label, key in (
            (SVC_RF_RAPID_FREEZE, LABEL_RF_RAPID, "rf_rapid"),
            (SVC_RF_WINTER, LABEL_RF_WINTER, "rf_winter"),
            (SVC_RF_SHOPPING, LABEL_RF_SHOPPING, "rf_shopping"),
            (SVC_RF_VACATION, LABEL_RF_VACATION, "rf_vacation"),
        ):
            if has(service):
                entities.append(
                    TaiSeiaEnumSensor(coordinator, client, entry.entry_id, service, label, key)
                )

    async_add_entities(entities, True)
    return True


class TaiSeiaOutdoorTemperature(TaiSeiaBaseEntity, SensorEntity):
    _entity_key = "outdoor_temp"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def label(self) -> str:
        return f"{self.nickname} {LABEL_OUTDOOR_TEMPERATURE}"

    @property
    def icon(self) -> str:
        return ICON_THERMOMETER

    @property
    def available(self) -> bool:
        return self.has_status(STATUS_POWER) and self.has_status(STATUS_TEMP_OUT)

    @property
    def native_value(self):
        raw = self.status_int(STATUS_TEMP_OUT, -1)
        if raw < 0 or raw == 0xFFFF:
            return None
        return _signed(raw)


class TaiSeiaHumidity(TaiSeiaBaseEntity, SensorEntity):
    _entity_key = "humidity"
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    @property
    def label(self) -> str:
        return f"{self.nickname} {LABEL_HUMIDITY}"

    @property
    def icon(self) -> str:
        return ICON_HUMIDITY

    @property
    def available(self) -> bool:
        return self.has_status(STATUS_POWER) and self.has_status(f"0x{SVC_DH_HUMIDITY_IN:02X}")

    @property
    def native_value(self):
        return self.status_int(f"0x{SVC_DH_HUMIDITY_IN:02X}", 0)


class TaiSeiaPM25(TaiSeiaBaseEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = CONCENTRATION_MICROGRAMS_PER_CUBIC_METER

    def __init__(self, coordinator, client, entry_id, service, label, key) -> None:
        self._service = service
        self._status_key = f"0x{service:02X}"
        self._label_suffix = label
        self._entity_key = key
        if service in (SVC_PM25, SVC_DH_PM25):
            self._attr_device_class = SensorDeviceClass.PM25
        else:
            self._attr_device_class = SensorDeviceClass.PM1
        super().__init__(coordinator, client, entry_id)

    @property
    def label(self) -> str:
        return f"{self.nickname} {self._label_suffix}"

    @property
    def icon(self) -> str:
        return ICON_PM25

    @property
    def available(self) -> bool:
        # Keep entity available even when AC is off / sensor idle
        return self.coordinator.last_update_success and self.has_status(self._status_key)

    @property
    def native_value(self):
        if self.client.device.sa_type_id == TYPE_AC and not self.status_bool(STATUS_POWER):
            if not (
                self.has_status(STATUS_PM25_FLAG) and self.status_int(STATUS_PM25_FLAG) != 0
            ):
                return None
        raw = self.status_int(self._status_key, -1)
        if raw < 0 or raw >= 0xFFFF:
            return None
        return raw


class TaiSeiaOperatingPower(TaiSeiaBaseEntity, SensorEntity):
    _entity_key = "operating_power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    @property
    def label(self) -> str:
        return f"{self.nickname} {LABEL_OPERATING_POWER}"

    @property
    def icon(self) -> str:
        return ICON_POWER

    @property
    def available(self) -> bool:
        return self.has_status(STATUS_OPERATING_POWER)

    @property
    def native_value(self):
        raw = self.status_int(STATUS_OPERATING_POWER, -1)
        if raw < 0 or raw >= 0xFFFF:
            return None
        return raw


class TaiSeiaFridgeTemp(TaiSeiaBaseEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, client, entry_id, service, label, icon, key) -> None:
        self._service = service
        self._status_key = f"0x{service:02X}"
        self._label_suffix = label
        self._icon_name = icon
        self._entity_key = key
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
    def native_value(self):
        return _signed(self.status_int(self._status_key, 0))


class TaiSeiaEnumSensor(TaiSeiaBaseEntity, SensorEntity):
    def __init__(self, coordinator, client, entry_id, service, label, key) -> None:
        self._service = service
        self._status_key = f"0x{service:02X}"
        self._label_suffix = label
        self._entity_key = key
        super().__init__(coordinator, client, entry_id)

    @property
    def label(self) -> str:
        return f"{self.nickname} {self._label_suffix}"

    @property
    def available(self) -> bool:
        return self.has_status(self._status_key)

    @property
    def native_value(self):
        return self.status_int(self._status_key, 0)
