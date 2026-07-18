"""Climate platform for Panasonic TaiSEIA local."""

from __future__ import annotations

import logging

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from .capability import filter_option_map
from .const import (
    CLIMATE_AVAILABLE_FAN_MODE,
    CLIMATE_AVAILABLE_MODE,
    CLIMATE_AVAILABLE_SWING_MODE,
    CLIMATE_MAXIMUM_TEMPERATURE,
    CLIMATE_MINIMUM_TEMPERATURE,
    CLIMATE_TEMPERATURE_STEP,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    LABEL_CLIMATE,
    STATUS_FAN,
    STATUS_MODE,
    STATUS_POWER,
    STATUS_SWING,
    STATUS_TEMP_IN,
    STATUS_TEMP_SET,
    SVC_FAN,
    SVC_MODE,
    SVC_POWER,
    SVC_SWING,
    SVC_TEMP_SET,
    TYPE_AC,
)
from .entity import TaiSeiaBaseEntity

_LOGGER = logging.getLogger(__package__)


def _key_from_dict(target: dict, mode_name: str):
    for key, value in target.items():
        if mode_name == value:
            return key
    return None


async def async_setup_entry(hass, entry, async_add_entities) -> bool:
    client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    if client.device.sa_type_id != TYPE_AC:
        return True
    async_add_entities(
        [TaiSeiaClimate(coordinator, client, entry.entry_id)],
        True,
    )
    return True


class TaiSeiaClimate(TaiSeiaBaseEntity, ClimateEntity):
    _entity_key = "climate"

    @property
    def available(self) -> bool:
        return self.has_status(STATUS_POWER)

    @property
    def label(self) -> str:
        return f"{self.nickname} {LABEL_CLIMATE}".strip()

    @property
    def supported_features(self) -> ClimateEntityFeature:
        features = (
            ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TARGET_TEMPERATURE
        )
        if self.client.has_service(SVC_FAN) or self.has_status(STATUS_FAN):
            features |= ClimateEntityFeature.FAN_MODE
        if self.client.has_service(SVC_SWING) or self.has_status(STATUS_SWING):
            features |= ClimateEntityFeature.SWING_MODE
        return features

    @property
    def temperature_unit(self) -> str:
        return UnitOfTemperature.CELSIUS

    def _fan_map(self) -> dict[int, str]:
        return filter_option_map(self.client, SVC_FAN, CLIMATE_AVAILABLE_FAN_MODE)

    def _swing_map(self) -> dict[int, str]:
        return filter_option_map(self.client, SVC_SWING, CLIMATE_AVAILABLE_SWING_MODE)

    def _mode_codes(self) -> set[int]:
        info = self.client.device.services.get(SVC_MODE)
        if not info:
            return {m["mappingCode"] for m in CLIMATE_AVAILABLE_MODE if m["mappingCode"] >= 0}
        from .capability import supported_values

        vals = supported_values(
            info, [m["mappingCode"] for m in CLIMATE_AVAILABLE_MODE if m["mappingCode"] >= 0]
        )
        return set(vals)

    @property
    def hvac_mode(self) -> HVACMode:
        if not self.status_bool(STATUS_POWER):
            return HVACMode.OFF
        if not self.has_status(STATUS_MODE):
            return HVACMode.OFF
        value = self.status_int(STATUS_MODE)
        for mode in CLIMATE_AVAILABLE_MODE:
            if mode["mappingCode"] == value:
                return mode["key"]
        return HVACMode.OFF

    @property
    def hvac_modes(self) -> list[HVACMode]:
        allowed = self._mode_codes()
        modes = [
            m["key"]
            for m in CLIMATE_AVAILABLE_MODE
            if m["mappingCode"] >= 0 and m["mappingCode"] in allowed
        ]
        if not modes:
            modes = [m["key"] for m in CLIMATE_AVAILABLE_MODE if m["mappingCode"] >= 0]
        modes.append(HVACMode.OFF)
        return modes

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        _LOGGER.debug("[%s] set_hvac_mode %s", self.label, hvac_mode)
        if hvac_mode == HVACMode.OFF:
            self.set_local_status(STATUS_POWER, "0")
            await self.client.async_write_ac(SVC_POWER, 0)
            return

        mapping = next(m for m in CLIMATE_AVAILABLE_MODE if m["key"] == hvac_mode)
        mode = mapping["mappingCode"]
        was_off = not self.status_bool(STATUS_POWER)
        self.set_local_status(STATUS_MODE, str(mode))
        await self.client.async_write_ac(SVC_MODE, mode)
        if was_off:
            self.set_local_status(STATUS_POWER, "1")
            await self.client.async_write_ac(SVC_POWER, 1)

    @property
    def fan_mode(self) -> str:
        fmap = self._fan_map()
        raw = self.status_int(STATUS_FAN, 0)
        return fmap.get(raw, next(iter(fmap.values()), "自動"))

    @property
    def fan_modes(self) -> list[str]:
        return list(self._fan_map().values())

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        mode_id = int(_key_from_dict(self._fan_map(), fan_mode))
        self.set_local_status(STATUS_FAN, str(mode_id))
        await self.client.async_write_ac(SVC_FAN, mode_id)

    @property
    def swing_mode(self) -> str:
        smap = self._swing_map()
        raw = self.status_int(STATUS_SWING, 0)
        return smap.get(raw, next(iter(smap.values()), "自動"))

    @property
    def swing_modes(self) -> list[str]:
        return list(self._swing_map().values())

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        mode_id = int(_key_from_dict(self._swing_map(), swing_mode))
        self.set_local_status(STATUS_SWING, str(mode_id))
        await self.client.async_write_ac(SVC_SWING, mode_id)

    @property
    def target_temperature(self) -> float:
        return float(self.status_int(STATUS_TEMP_SET, 0))

    @property
    def current_temperature(self) -> float:
        return float(self.status_int(STATUS_TEMP_IN, 0))

    async def async_set_temperature(self, **kwargs) -> None:
        target = kwargs.get(ATTR_TEMPERATURE)
        if target is None:
            return
        value = int(target)
        self.set_local_status(STATUS_TEMP_SET, str(value))
        await self.client.async_write_ac(SVC_TEMP_SET, value)

    @property
    def min_temp(self) -> float:
        lo, hi = self.client.service_range(SVC_TEMP_SET)
        if self.client.has_service(SVC_TEMP_SET) and 10 <= lo <= hi <= 40:
            return float(lo)
        return float(CLIMATE_MINIMUM_TEMPERATURE)

    @property
    def max_temp(self) -> float:
        lo, hi = self.client.service_range(SVC_TEMP_SET)
        if self.client.has_service(SVC_TEMP_SET) and 10 <= lo <= hi <= 40:
            return float(hi)
        return float(CLIMATE_MAXIMUM_TEMPERATURE)

    @property
    def target_temperature_step(self) -> float:
        return CLIMATE_TEMPERATURE_STEP
