"""Sensor platform — APK CommandList read-only + TaiSEIA extras + energy + probe."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    EntityCategory,
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.typing import StateType

from .catalog import extra_local_sensors, iter_kind, service_allowed
from .cloud_sync import cloud_attrs_from_entry, hub_device_identifier
from .const import (
    CONF_ENERGY_ENABLED,
    CONF_ENERGY_INCLUDE_HOUSE,
    CONF_ENTRY_TYPE,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DATA_ENERGY,
    DATA_HOUSE_ENERGY,
    DATA_PROFILE,
    DOMAIN,
    ENTRY_TYPE_HUB,
    STATUS_POWER,
    SVC_OPERATING_POWER,
)
from .entity import TaiSeiaBaseEntity
from .probe_info import (
    services_as_list,
    status_as_list,
    status_highlights,
    type_summary,
)


def _signed(raw: int) -> int:
    if raw > 200:
        return raw - 256
    return raw


def _hub_exists(hass: HomeAssistant) -> bool:
    return any(
        e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB
        for e in hass.config_entries.async_entries(DOMAIN)
    )


async def async_setup_entry(hass, entry, async_add_entities) -> bool:
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
        domain_data = hass.data[DOMAIN]
        domain_data[DATA_HOUSE_ENERGY] = entry.entry_id
        async_add_entities(
            [TaiSeiaHouseMonthlyEnergySensor(hass, entry)],
            True,
        )
        return True

    client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    profile = hass.data[DOMAIN][entry.entry_id].get(DATA_PROFILE)

    entities: list = [TaiSeiaProbeInfoSensor(coordinator, client, entry.entry_id)]
    seen: set[int] = set()

    items = []
    if profile:
        items.extend(iter_kind(profile, "sensor"))
    items.extend(extra_local_sensors(client.device.sa_type_id, profile))

    for item in items:
        sid = item.command.service
        if sid in seen:
            continue
        if not service_allowed(client.device.services, sid):
            continue
        seen.add(sid)
        hint = item.device_class_hint
        if hint == "temperature":
            entities.append(
                TaiSeiaNumericSensor(
                    coordinator,
                    client,
                    entry.entry_id,
                    service=sid,
                    label_suffix=item.command.name,
                    icon_name=item.icon,
                    key=f"sensor_{sid:02x}",
                    device_class=SensorDeviceClass.TEMPERATURE,
                    unit=UnitOfTemperature.CELSIUS,
                    signed=True,
                )
            )
        elif hint == "humidity":
            entities.append(
                TaiSeiaNumericSensor(
                    coordinator,
                    client,
                    entry.entry_id,
                    service=sid,
                    label_suffix=item.command.name,
                    icon_name=item.icon,
                    key=f"sensor_{sid:02x}",
                    device_class=SensorDeviceClass.HUMIDITY,
                    unit=PERCENTAGE,
                    signed=False,
                )
            )
        elif hint == "power":
            entities.append(
                TaiSeiaNumericSensor(
                    coordinator,
                    client,
                    entry.entry_id,
                    service=sid,
                    label_suffix=item.command.name,
                    icon_name=item.icon,
                    key=f"sensor_{sid:02x}",
                    device_class=SensorDeviceClass.POWER,
                    unit=UnitOfPower.WATT,
                    signed=False,
                    require_power=True,
                )
            )
        elif hint == "pm25":
            entities.append(
                TaiSeiaNumericSensor(
                    coordinator,
                    client,
                    entry.entry_id,
                    service=sid,
                    label_suffix=item.command.name,
                    icon_name=item.icon,
                    key=f"sensor_{sid:02x}",
                    device_class=SensorDeviceClass.PM25
                    if "1.0" not in item.command.name and "10" not in item.command.name
                    else None,
                    unit=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
                    signed=False,
                )
            )
        else:
            entities.append(
                TaiSeiaGenericSensor(
                    coordinator,
                    client,
                    entry.entry_id,
                    service=sid,
                    label_suffix=item.command.name,
                    icon_name=item.icon,
                    key=f"sensor_{sid:02x}",
                )
            )

    if entry.options.get(CONF_ENERGY_ENABLED, True) and service_allowed(
        client.device.services, SVC_OPERATING_POWER
    ):
        mac = (client.device.mac or entry.entry_id).lower()
        entities.append(
            TaiSeiaEnergySensor(
                coordinator,
                client,
                entry.entry_id,
                kind="period",
                suggested_object_id=f"taiseia_{mac}_monthly_energy",
            )
        )
        entities.append(
            TaiSeiaEnergySensor(
                coordinator,
                client,
                entry.entry_id,
                kind="total",
                suggested_object_id=f"taiseia_{mac}_total_energy",
            )
        )

    # Legacy: no hub yet → keep house total on first device entry
    if not _hub_exists(hass):
        domain_data = hass.data[DOMAIN]
        if not domain_data.get(DATA_HOUSE_ENERGY):
            domain_data[DATA_HOUSE_ENERGY] = True
            entities.append(TaiSeiaHouseMonthlyEnergySensor(hass, None))

    async_add_entities(entities, True)
    return True


class TaiSeiaEnergySensor(TaiSeiaBaseEntity, SensorEntity):
    """Per-device energy from integrated operating power."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:lightning-bolt"

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
        self._entity_key = f"energy_{kind}"
        self._attr_suggested_object_id = suggested_object_id
        if kind == "total":
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        else:
            self._attr_state_class = SensorStateClass.TOTAL
        super().__init__(coordinator, client, entry_id)

    @property
    def label(self) -> str:
        if self._kind == "total":
            suffix = "累計耗電"
        else:
            suffix = (self.coordinator.data or {}).get("energy_period_label") or "本期耗電"
        return f"{self.nickname} {suffix}"

    @property
    def available(self) -> bool:
        return bool((self.coordinator.data or {}).get("has_power_energy"))

    @property
    def native_value(self) -> float:
        data = self.coordinator.data or {}
        if self._kind == "total":
            return round(float(data.get("energy_total_kwh") or 0.0), 3)
        return round(
            float(data.get("energy_period_kwh") or data.get("energy_monthly_kwh") or 0.0),
            3,
        )

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "period": data.get("energy_period_key") or data.get("energy_month_key"),
            "cycle": data.get("energy_cycle"),
            "cycle_days": data.get("energy_cycle_days"),
            "method": "left_riemann_from_operating_power",
        }


class TaiSeiaHouseMonthlyEnergySensor(SensorEntity):
    """Sum of panasonic_taiseia_local period energy trackers (on hub device when present)."""

    _attr_has_entity_name = False
    _attr_name = "全室冷氣本期耗電"
    _attr_suggested_object_id = "house_climate_energy_taiseia_local"
    _attr_unique_id = f"{DOMAIN}_house_monthly_energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:home-lightning-bolt"
    _attr_should_poll = True

    def __init__(
        self, hass: HomeAssistant, hub_entry: ConfigEntry | None
    ) -> None:
        self.hass = hass
        self._hub_entry = hub_entry
        self._unsubs: list = []
        if hub_entry is not None:
            self._attr_device_info = {
                "identifiers": {hub_device_identifier(hub_entry)},
                "name": hub_entry.title,
            }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._bind_listeners()

    async def async_update(self) -> None:
        self._bind_listeners()

    @callback
    def _bind_listeners(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs = []
        for _key, data in self.hass.data.get(DOMAIN, {}).items():
            if not isinstance(data, dict):
                continue
            coordinator = data.get(DATA_COORDINATOR)
            if coordinator is None:
                continue

            @callback
            def _updated() -> None:
                self.async_write_ha_state()

            self._unsubs.append(coordinator.async_add_listener(_updated))

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs = []
        self.hass.data.get(DOMAIN, {}).pop(DATA_HOUSE_ENERGY, None)
        await super().async_will_remove_from_hass()

    @property
    def available(self) -> bool:
        return self._month_total() is not None

    @property
    def native_value(self) -> float | None:
        total = self._month_total()
        return None if total is None else round(total, 3)

    def _month_total(self) -> float | None:
        total = 0.0
        found = False
        for entry_id, data in self.hass.data.get(DOMAIN, {}).items():
            if not isinstance(data, dict):
                continue
            tracker = data.get(DATA_ENERGY)
            if tracker is None:
                continue
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry is not None:
                if not entry.options.get(CONF_ENERGY_ENABLED, True):
                    continue
                if not entry.options.get(CONF_ENERGY_INCLUDE_HOUSE, True):
                    continue
            found = True
            total += float(tracker.period_kwh)
        return total if found else None

    @property
    def name(self) -> str:
        for _eid, data in self.hass.data.get(DOMAIN, {}).items():
            if not isinstance(data, dict):
                continue
            coord = data.get(DATA_COORDINATOR)
            if coord and coord.data and coord.data.get("energy_period_label"):
                label = coord.data["energy_period_label"]
                return f"全室冷氣{label}"
        return "全室冷氣本期耗電"

    @property
    def extra_state_attributes(self) -> dict:
        cycle = None
        cycle_days = None
        for _eid, data in self.hass.data.get(DOMAIN, {}).items():
            if isinstance(data, dict) and data.get(DATA_ENERGY):
                cycle = data[DATA_ENERGY].settings.cycle
                cycle_days = data[DATA_ENERGY].settings.cycle_days
                break
        return {
            "friendly_note": "由 panasonic_taiseia_local 各機本期耗電加總（可排除單機）",
            "cycle": cycle,
            "cycle_days": cycle_days,
        }


class TaiSeiaProbeInfoSensor(TaiSeiaBaseEntity, SensorEntity):
    _entity_key = "probe_info"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:information-outline"

    @property
    def label(self) -> str:
        return f"{self.nickname} 探測資訊"

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> StateType:
        mt = (self.coordinator.data or {}).get("model_type")
        base = type_summary(self.client.device)
        return f"{base} · {mt}" if mt else base

    @property
    def extra_state_attributes(self) -> dict:
        d = self.client.device
        status = self.device_status
        data = self.coordinator.data or {}
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        attrs: dict = {
            "設備類型": type_summary(d),
            "ModelType": data.get("model_type"),
            "類型代碼": f"0x{d.sa_type_id:02X}",
            "服務數量": len(d.services),
            "服務清單": services_as_list(d.services),
            "即時狀態數量": len(status),
            "狀態摘要": status_highlights(status, d.sa_type_id),
            "即時狀態": status_as_list(status, sa_type=d.sa_type_id),
            "即時狀態原始": dict(status),
            "IP": d.host or self.client.host,
            "埠": d.port or self.client.port,
            "MAC": d.mac or None,
            "SA模組": d.sa_model or d.model_number or None,
            "室內機型號": data.get("indoor_model"),
            "輪詢間隔秒": data.get("poll_interval"),
            "LAN逾時": data.get("lan_timeout"),
            "LAN重試": data.get("lan_retries"),
            "LAN併發上限": data.get("lan_max_concurrent"),
            "協調器成功": self.coordinator.last_update_success,
        }
        last = getattr(self.coordinator, "last_update_success_time", None)
        if last is not None:
            attrs["上次成功更新"] = last.isoformat()

        if entry is not None:
            attrs.update(cloud_attrs_from_entry(entry))
            if entry.data.get("hub_entry_id"):
                attrs["主設定 entry"] = entry.data.get("hub_entry_id")
        for key, label in (
            ("cloud_nickname", "官網暱稱"),
            ("cloud_model", "官網機型"),
            ("cloud_model_id", "官網 ModelID"),
            ("cloud_model_type", "官網 ModelType"),
            ("cloud_gwid", "官網 GWID"),
        ):
            val = data.get(key)
            if val not in (None, ""):
                attrs[label] = val
        return attrs


class TaiSeiaNumericSensor(TaiSeiaBaseEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator,
        client,
        entry_id,
        *,
        service: int,
        label_suffix: str,
        icon_name: str,
        key: str,
        device_class: SensorDeviceClass | None,
        unit: str | None,
        signed: bool,
        require_power: bool = False,
    ) -> None:
        self._service = service
        self._status_key = f"0x{service:02X}"
        self._label_suffix = label_suffix
        self._icon_name = icon_name
        self._entity_key = key
        self._signed = signed
        self._require_power = require_power
        if device_class:
            self._attr_device_class = device_class
        if unit:
            self._attr_native_unit_of_measurement = unit
        super().__init__(coordinator, client, entry_id)

    @property
    def label(self) -> str:
        return f"{self.nickname} {self._label_suffix}"

    @property
    def icon(self) -> str:
        return self._icon_name

    @property
    def available(self) -> bool:
        if self._require_power and not self.has_status(STATUS_POWER):
            return False
        return self.has_status(self._status_key)

    @property
    def native_value(self):
        raw = self.status_int(self._status_key, -1)
        if raw < 0 or raw == 0xFFFF:
            return None
        return _signed(raw) if self._signed else raw


class TaiSeiaGenericSensor(TaiSeiaBaseEntity, SensorEntity):
    def __init__(
        self,
        coordinator,
        client,
        entry_id,
        *,
        service: int,
        label_suffix: str,
        icon_name: str,
        key: str,
    ) -> None:
        self._service = service
        self._status_key = f"0x{service:02X}"
        self._label_suffix = label_suffix
        self._icon_name = icon_name
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
        return self.status_int(self._status_key, 0)
