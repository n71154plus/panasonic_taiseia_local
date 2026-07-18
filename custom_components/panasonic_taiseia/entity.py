"""Base entity for Panasonic TaiSEIA."""

from __future__ import annotations

from abc import ABC, abstractmethod

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .taiseia import TaiSeiaClient


class TaiSeiaBaseEntity(CoordinatorEntity, ABC):
    _entity_key: str = "base"

    def __init__(self, coordinator, client: TaiSeiaClient, entry_id: str) -> None:
        super().__init__(coordinator)
        self.client = client
        self.entry_id = entry_id
        # Force registry registration (HA reads unique_id during add)
        self._attr_unique_id = f"{client.device.unique_id}_{self._entity_key}"
        self._attr_has_entity_name = False

    @property
    @abstractmethod
    def label(self) -> str:
        ...

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
        indoor = (self.coordinator.data or {}).get("indoor_model")
        model_base = indoor or d.sa_model or d.model_number or d.model_name
        info = {
            "identifiers": {(DOMAIN, d.unique_id)},
            "name": self.nickname,
            "manufacturer": d.manufacturer or MANUFACTURER,
            "model": f"{model_base} ({d.type_name})".strip(),
            "connections": connections,
        }
        if d.sw_version:
            info["sw_version"] = d.sw_version
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

    def set_local_status(self, status_key: str, value) -> None:
        self.coordinator.update_local_state(status_key, value)  # type: ignore[attr-defined]
        self.coordinator.async_set_updated_data(self.coordinator.data)
        self.async_write_ha_state()
