"""Climate platform for Panasonic TaiSEIA local."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError

from .capability import filter_option_map, supported_values
from .catalog import (
    climate_fan_map,
    climate_hvac_mappings,
    climate_preset_codes,
    climate_swing_map,
    climate_temp_limits,
)
from .const import (
    AC_CODE_TO_PRESET,
    AC_EXTENDED_HVAC_ALIAS,
    AC_MODE_LABELS,
    AC_PRESET_TO_CODE,
    CLIMATE_AVAILABLE_FAN_MODE,
    CLIMATE_AVAILABLE_MODE,
    CLIMATE_AVAILABLE_SWING_MODE,
    CLIMATE_MAXIMUM_TEMPERATURE,
    CLIMATE_MINIMUM_TEMPERATURE,
    CLIMATE_PRESET_NONE,
    CLIMATE_TEMPERATURE_STEP,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DATA_PROFILE,
    DOMAIN,
    ICON_CLIMATE,
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

PARALLEL_UPDATES = 1


def _key_from_dict(target: dict, mode_name: str):
    for key, value in target.items():
        if mode_name == value:
            return key
    return None


async def async_setup_entry(hass, entry, async_add_entities) -> bool:
    client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    profile = hass.data[DOMAIN][entry.entry_id].get(DATA_PROFILE)
    # Only the probed / entry SA type decides climate — never trust catalog
    # DeviceType alone (wrong ModelType must not create a climate entity).
    if client.device.sa_type_id != TYPE_AC:
        return True
    async_add_entities(
        [TaiSeiaClimate(coordinator, client, entry.entry_id, profile)],
        True,
    )
    return True


class TaiSeiaClimate(TaiSeiaBaseEntity, ClimateEntity):
    _entity_key = "climate"
    _attr_icon = ICON_CLIMATE

    def __init__(self, coordinator, client, entry_id, profile) -> None:
        self._profile = profile
        super().__init__(coordinator, client, entry_id)

    def _mode_table(self) -> list[dict]:
        catalog = climate_hvac_mappings(self._profile)
        return catalog or CLIMATE_AVAILABLE_MODE

    @property
    def available(self) -> bool:
        return self.has_status(STATUS_POWER)

    @property
    def label(self) -> str:
        return LABEL_CLIMATE

    @property
    def icon(self) -> str:
        return ICON_CLIMATE

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
        if len(self.preset_modes) > 1:
            features |= ClimateEntityFeature.PRESET_MODE
        return features

    @property
    def temperature_unit(self) -> str:
        return UnitOfTemperature.CELSIUS

    def _fan_map(self) -> dict[int, str]:
        base = climate_fan_map(self._profile) or CLIMATE_AVAILABLE_FAN_MODE
        return filter_option_map(self.client, SVC_FAN, base)

    def _swing_map(self) -> dict[int, str]:
        base = climate_swing_map(self._profile) or CLIMATE_AVAILABLE_SWING_MODE
        return filter_option_map(self.client, SVC_SWING, base)

    def _mode_codes(self) -> set[int]:
        table = self._mode_table()
        info = self.client.device.services.get(SVC_MODE)
        codes = [m["mappingCode"] for m in table if m["mappingCode"] >= 0]
        if not info:
            return set(codes)
        return set(supported_values(info, codes))

    def _raw_mode(self) -> int | None:
        if not self.has_status(STATUS_MODE):
            return None
        return self.status_int(STATUS_MODE)

    def _mode_label(self, code: int | None) -> str | None:
        if code is None:
            return None
        catalog = climate_preset_codes(self._profile)
        if code in catalog:
            return catalog[code]
        return AC_MODE_LABELS.get(code)

    def _offers_preset_code(self, code: int) -> bool:
        """Whether this appliance can use an extended mode / preset."""
        raw = self._raw_mode()
        if raw == code:
            return True
        return code in climate_preset_codes(self._profile)

    @property
    def hvac_mode(self) -> HVACMode:
        if not self.status_bool(STATUS_POWER):
            return HVACMode.OFF
        if not self.has_status(STATUS_MODE):
            return HVACMode.OFF
        value = self.status_int(STATUS_MODE)
        for mode in self._mode_table():
            if mode["mappingCode"] == value:
                return mode["key"]
        # Extended manufacturer modes (e.g. 舒適冷房=5): still powered on.
        alias = AC_EXTENDED_HVAC_ALIAS.get(value)
        if alias is not None:
            return alias
        # Unknown but powered: prefer cool over a false OFF (issue #19).
        return HVACMode.COOL

    @property
    def hvac_modes(self) -> list[HVACMode]:
        allowed = self._mode_codes()
        table = self._mode_table()
        modes = [
            m["key"]
            for m in table
            if m["mappingCode"] >= 0 and m["mappingCode"] in allowed
        ]
        if not modes:
            modes = [m["key"] for m in table if m["mappingCode"] >= 0]
        modes.append(HVACMode.OFF)
        return modes

    @property
    def preset_mode(self) -> str | None:
        raw = self._raw_mode()
        if raw is None:
            return CLIMATE_PRESET_NONE
        return AC_CODE_TO_PRESET.get(raw, CLIMATE_PRESET_NONE)

    @property
    def preset_modes(self) -> list[str]:
        modes = [CLIMATE_PRESET_NONE]
        for code in AC_PRESET_TO_CODE.values():
            if self._offers_preset_code(code):
                preset = AC_CODE_TO_PRESET[code]
                if preset not in modes:
                    modes.append(preset)
        return modes

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        raw = self._raw_mode()
        attrs: dict[str, Any] = {
            "control_mode": data.get("control_mode"),
            "control_path": data.get("control_path"),
            "lan_ok": data.get("lan_ok"),
        }
        auth = data.get("auth") or {}
        if isinstance(auth, dict) and auth.get("credentials_ok") is not None:
            attrs["ems_credentials_ok"] = auth.get("credentials_ok")
        if raw is not None:
            attrs["mode_code"] = raw
            label = self._mode_label(raw)
            if label:
                attrs["mode_label"] = label
        return attrs

    def _resume_mode(self) -> HVACMode | None:
        """Return the mode the device was last set to, even while powered off.

        TaiSEIA controllers keep the mode register (0x01) when power is off,
        so the last-used mode survives a plain off/on cycle.
        """
        raw = self._raw_mode()
        if raw is None:
            return None
        if raw in AC_EXTENDED_HVAC_ALIAS:
            # Extended codes are resumed via raw write in async_turn_on.
            return None
        for mode in self._mode_table():
            if (
                mode["mappingCode"] == raw
                and mode["key"] != HVACMode.OFF
                and mode["key"] in self.hvac_modes
            ):
                return mode["key"]
        return None

    async def _async_apply_mode_code(self, mode_code: int) -> None:
        """Write 0x01 and power on if needed (shared by HVAC + preset paths)."""
        was_off = not self.status_bool(STATUS_POWER)
        prev_mode = self.device_status.get(STATUS_MODE)
        await self.async_write_with_rollback(
            SVC_MODE, mode_code, STATUS_MODE, prev_mode
        )
        if was_off:
            prev_pwr = self.device_status.get(STATUS_POWER)
            try:
                await self.async_write_with_rollback(
                    SVC_POWER, 1, STATUS_POWER, prev_pwr
                )
            except Exception:
                try:
                    if prev_mode not in (None, ""):
                        await self.async_write_with_rollback(
                            SVC_MODE,
                            int(prev_mode),
                            STATUS_MODE,
                            str(mode_code),
                        )
                    else:
                        self.set_local_status(STATUS_MODE, prev_mode)
                except Exception:  # noqa: BLE001
                    self.set_local_status(STATUS_MODE, prev_mode)
                raise

    async def async_turn_on(self) -> None:
        """Turn on, resuming the last-used mode instead of heat.

        The core ClimateEntity default picks the first supported mode in a
        fixed (heat_cool, heat, cool) order, which makes cooling-capable ACs
        with a heat mode always start in heat. HA core deliberately leaves
        this to integrations (see home-assistant/core#181909).
        """
        raw = self._raw_mode()
        if raw is not None and raw in AC_EXTENDED_HVAC_ALIAS:
            try:
                await self._async_apply_mode_code(raw)
            except Exception as err:  # noqa: BLE001
                raise HomeAssistantError(str(err)) from err
            return

        mode = self._resume_mode()
        if mode is None:
            supported = [m for m in self.hvac_modes if m != HVACMode.OFF]
            if HVACMode.COOL in supported:
                mode = HVACMode.COOL
            elif supported:
                mode = supported[0]
        if mode is None:
            raise HomeAssistantError(f"[{self.label}] 無可運轉的 HVAC 模式")
        await self.async_set_hvac_mode(mode)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        _LOGGER.debug("[%s] set_hvac_mode %s", self.label, hvac_mode)
        try:
            if hvac_mode == HVACMode.OFF:
                prev = self.device_status.get(STATUS_POWER)
                await self.async_write_with_rollback(SVC_POWER, 0, STATUS_POWER, prev)
                return

            mapping = next(m for m in self._mode_table() if m["key"] == hvac_mode)
            await self._async_apply_mode_code(mapping["mappingCode"])
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        _LOGGER.debug("[%s] set_preset_mode %s", self.label, preset_mode)
        try:
            if preset_mode == CLIMATE_PRESET_NONE:
                raw = self._raw_mode()
                if raw in AC_CODE_TO_PRESET:
                    # Leave extended mode for standard cool (HVAC still cool).
                    await self._async_apply_mode_code(0)
                return
            code = AC_PRESET_TO_CODE.get(preset_mode)
            if code is None:
                raise HomeAssistantError(f"[{self.label}] 不支援的預設模式: {preset_mode}")
            if not self._offers_preset_code(code):
                raise HomeAssistantError(f"[{self.label}] 此機種不支援 {preset_mode}")
            await self._async_apply_mode_code(code)
        except HomeAssistantError:
            raise
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err

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
        prev = self.device_status.get(STATUS_FAN)
        try:
            await self.async_write_with_rollback(SVC_FAN, mode_id, STATUS_FAN, prev)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err

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
        prev = self.device_status.get(STATUS_SWING)
        try:
            await self.async_write_with_rollback(SVC_SWING, mode_id, STATUS_SWING, prev)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err

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
        prev = self.device_status.get(STATUS_TEMP_SET)
        try:
            await self.async_write_with_rollback(
                SVC_TEMP_SET, value, STATUS_TEMP_SET, prev
            )
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err

    @property
    def min_temp(self) -> float:
        clo, chi = climate_temp_limits(self._profile)
        lo, hi = self.client.service_range(SVC_TEMP_SET)
        if self.client.has_service(SVC_TEMP_SET) and 10 <= lo <= hi <= 40:
            return float(lo)
        if clo is not None:
            return float(clo)
        return float(CLIMATE_MINIMUM_TEMPERATURE)

    @property
    def max_temp(self) -> float:
        clo, chi = climate_temp_limits(self._profile)
        lo, hi = self.client.service_range(SVC_TEMP_SET)
        if self.client.has_service(SVC_TEMP_SET) and 10 <= lo <= hi <= 40:
            return float(hi)
        if chi is not None:
            return float(chi)
        return float(CLIMATE_MAXIMUM_TEMPERATURE)

    @property
    def target_temperature_step(self) -> float:
        return CLIMATE_TEMPERATURE_STEP
