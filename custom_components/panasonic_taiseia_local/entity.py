"""Base entity for Panasonic TaiSEIA."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_CONTROL, DOMAIN, MANUFACTURER
from .probe_info import type_summary
from .taiseia import TaiSeiaClient, status_key


class TaiSeiaBaseEntity(CoordinatorEntity, ABC):
    _entity_key: str = "base"
    _attr_has_entity_name = True

    def __init__(self, coordinator, client: TaiSeiaClient, entry_id: str) -> None:
        super().__init__(coordinator)
        self.client = client
        self.entry_id = entry_id
        # Force registry registration (HA reads unique_id during add)
        self._attr_unique_id = f"{client.device.unique_id}_{self._entity_key}"

    @property
    @abstractmethod
    def label(self) -> str:
        """Feature name (without device nickname); used as entity name."""

    @property
    def nickname(self) -> str:
        data = self.coordinator.data or {}
        return data.get("name") or self.client.device.sa_model or self.client.host

    @property
    def name(self) -> str:
        return self.label

    @property
    def unique_id(self) -> str:
        return f"{self.client.device.unique_id}_{self._entity_key}"

    @property
    def device_info(self) -> dict:
        d = self.client.device
        connections = set()
        if d.mac and len(d.mac) == 12:
            mac = ":".join(d.mac[i : i + 2] for i in range(0, 12, 2)).lower()
            connections.add((CONNECTION_NETWORK_MAC, mac))
        data = self.coordinator.data or {}
        indoor = data.get("indoor_model") or data.get("cloud_model")
        model_type = data.get("model_type") or data.get("cloud_model_type")
        model_base = indoor or d.sa_model or d.model_number or d.model_name
        host = d.host or self.client.host
        port = d.port or self.client.port
        model_bits = [model_base, type_summary(d)]
        if model_type:
            model_bits.append(model_type)
        info: dict[str, Any] = {
            "identifiers": {(DOMAIN, d.unique_id)},
            "name": self.nickname,
            "manufacturer": d.manufacturer or MANUFACTURER,
            "model": " · ".join(str(b) for b in model_bits if b),
            "connections": connections,
        }
        if host and host not in ("", "0.0.0.0"):
            info["configuration_url"] = f"http://{host}:{port}"
        if d.sw_version:
            info["sw_version"] = d.sw_version
        hw = d.model_name or d.sa_model or d.model_number
        if hw:
            info["hw_version"] = str(hw)
        serial = data.get("cloud_gwid") or d.mac
        if serial:
            info["serial_number"] = str(serial).upper()
        return info

    @property
    def device_status(self) -> dict:
        return (self.coordinator.data or {}).get("status") or {}

    @staticmethod
    def parse_status_int(raw, default: int = 0) -> int:
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except (ValueError, TypeError):
            return default

    def status_int(self, key: str, default: int = 0) -> int:
        status = self.device_status
        if key in status:
            return self.parse_status_int(status.get(key), default)
        for k, v in status.items():
            if k.lower() == key.lower():
                return self.parse_status_int(v, default)
        return default

    def status_bool(self, key: str, default: bool = False) -> bool:
        return bool(self.status_int(key, 1 if default else 0))

    def has_status(self, key: str) -> bool:
        status = self.device_status
        for k, raw in status.items():
            if k.lower() == key.lower():
                return raw is not None and raw != ""
        return False

    def set_local_status(self, status_key_name: str, value) -> None:
        self.coordinator.update_local_state(status_key_name, value)  # type: ignore[attr-defined]
        self.coordinator.async_set_updated_data(self.coordinator.data)
        self.async_write_ha_state()

    async def async_write_with_rollback(
        self, service: int, value: int, status_key_name: str, previous
    ) -> None:
        """Optimistic UI update; restore previous status if the write fails."""
        self.set_local_status(status_key_name, str(value))
        try:
            await self.async_device_write(service, value)
        except Exception:
            self.set_local_status(status_key_name, previous)
            raise

    async def async_device_write(self, service: int, value: int) -> None:
        """Write via DeviceControl facade (hybrid/local/cloud)."""
        slot = (self.hass.data.get(DOMAIN) or {}).get(self.entry_id) or {}
        control = slot.get(DATA_CONTROL)
        if control is not None:
            path = await control.async_write(service, value)
            data = dict(self.coordinator.data or {})
            data["control_path"] = path
            self.coordinator.async_set_updated_data(data)
            return
        await self.client.async_write_device(service, value)
        self.set_local_status(status_key(service), str(value))
