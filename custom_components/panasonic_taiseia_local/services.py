"""Developer diagnostic services (probe / read / write / LAN scan)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_ENTRY_TYPE,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DATA_PROFILE,
    DOMAIN,
    ENTRY_TYPE_DEVICE,
)
from .diagnostics_data import (
    async_build_device_diagnostics,
    parse_service_id,
    services_structured,
)
from .discovery import async_discover_devices
from .probe_info import decode_status_value, service_label

_LOGGER = logging.getLogger(__package__)

ATTR_ENTRY_ID = "entry_id"
ATTR_SERVICE = "service"
ATTR_VALUE = "value"
ATTR_INCLUDE_SUBNET_SCAN = "include_subnet_scan"

SERVICE_PROBE_DEVICE = "probe_device"
SERVICE_READ_SERVICE = "read_service"
SERVICE_WRITE_SERVICE = "write_service"
SERVICE_SCAN_LAN = "scan_lan"

DATA_SERVICES_REGISTERED = "_services_registered"

PROBE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Optional(CONF_DEVICE_ID): cv.string,
    }
)

READ_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Optional(CONF_DEVICE_ID): cv.string,
        vol.Required(ATTR_SERVICE): vol.Any(int, cv.string),
    }
)

WRITE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Optional(CONF_DEVICE_ID): cv.string,
        vol.Required(ATTR_SERVICE): vol.Any(int, cv.string),
        vol.Required(ATTR_VALUE): vol.Coerce(int),
    }
)

SCAN_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_INCLUDE_SUBNET_SCAN, default=True): cv.boolean,
    }
)


def _resolve_entry_id(hass: HomeAssistant, call: ServiceCall) -> str:
    entry_id = call.data.get(ATTR_ENTRY_ID)
    device_id = call.data.get(CONF_DEVICE_ID)
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(f"Unknown entry_id: {entry_id}")
        if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
            raise ServiceValidationError("entry_id must be a device entry")
        return entry_id
    if device_id:
        registry = dr.async_get(hass)
        device = registry.async_get(device_id)
        if device is None:
            raise ServiceValidationError(f"Unknown device_id: {device_id}")
        for conf_entry_id in device.config_entries:
            entry = hass.config_entries.async_get_entry(conf_entry_id)
            if (
                entry is not None
                and entry.domain == DOMAIN
                and entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_DEVICE
            ):
                return conf_entry_id
        raise ServiceValidationError(
            f"device_id {device_id} is not linked to a TaiSEIA device entry"
        )
    raise ServiceValidationError("Provide entry_id or device_id")


def _client_for_entry(hass: HomeAssistant, entry_id: str):
    data = hass.data.get(DOMAIN, {}).get(entry_id) or {}
    client = data.get(DATA_CLIENT)
    if client is None:
        raise HomeAssistantError(f"Device entry {entry_id} is not loaded")
    return client, data


async def _async_handle_probe(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    entry_id = _resolve_entry_id(hass, call)
    client, _data = _client_for_entry(hass, entry_id)
    device = await client.async_probe()
    entry = hass.config_entries.async_get_entry(entry_id)
    profile = (hass.data.get(DOMAIN, {}).get(entry_id) or {}).get(DATA_PROFILE)
    overrides = (
        {cmd.service: cmd.name for cmd in profile.commands} if profile else None
    )
    return {
        "entry_id": entry_id,
        "title": entry.title if entry else None,
        "host": device.host,
        "mac": device.mac or None,
        "type_id": device.sa_type_id,
        "type_id_hex": f"0x{device.sa_type_id:02X}",
        "sa_model": device.sa_model or device.model_number or None,
        "service_count": len(device.services),
        "services": services_structured(device, name_overrides=overrides),
    }


async def _async_handle_read(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    entry_id = _resolve_entry_id(hass, call)
    client, data = _client_for_entry(hass, entry_id)
    try:
        service_id = parse_service_id(call.data[ATTR_SERVICE])
    except ValueError as err:
        raise ServiceValidationError(f"Invalid service: {err}") from err
    value = await client.async_read_device(service_id)
    sa_type = client.device.sa_type_id
    profile = data.get(DATA_PROFILE)
    overrides = (
        {cmd.service: cmd.name for cmd in profile.commands} if profile else None
    )
    name = service_label(service_id, sa_type, name_overrides=overrides)
    decoded = decode_status_value(sa_type, service_id, value)
    return {
        "entry_id": entry_id,
        "service": service_id,
        "service_hex": f"0x{service_id:02X}",
        "name": name,
        "value": value,
        "decoded": decoded,
    }


async def _async_handle_write(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    entry_id = _resolve_entry_id(hass, call)
    client, data = _client_for_entry(hass, entry_id)
    try:
        service_id = parse_service_id(call.data[ATTR_SERVICE])
    except ValueError as err:
        raise ServiceValidationError(f"Invalid service: {err}") from err
    value = int(call.data[ATTR_VALUE])
    _LOGGER.warning(
        "Diagnostic write_service entry=%s service=0x%02X value=%s",
        entry_id,
        service_id,
        value,
    )
    written = await client.async_write_device(service_id, value)
    coordinator = data.get(DATA_COORDINATOR)
    if coordinator is not None:
        await coordinator.async_request_refresh()
    sa_type = client.device.sa_type_id
    profile = data.get(DATA_PROFILE)
    overrides = (
        {cmd.service: cmd.name for cmd in profile.commands} if profile else None
    )
    return {
        "entry_id": entry_id,
        "service": service_id,
        "service_hex": f"0x{service_id:02X}",
        "name": service_label(service_id, sa_type, name_overrides=overrides),
        "written_value": value,
        "response_value": written,
    }


async def _async_handle_scan(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    include_subnet = call.data.get(ATTR_INCLUDE_SUBNET_SCAN, True)
    session = async_get_clientsession(hass)
    found = await async_discover_devices(
        session, include_subnet_scan=bool(include_subnet)
    )
    return {
        "include_subnet_scan": bool(include_subnet),
        "count": len(found),
        "devices": [
            {
                "host": d.host,
                "port": d.port,
                "mac": d.mac or None,
                "name": d.name,
                "type_id": d.sa_type,
                "type_id_hex": f"0x{d.sa_type:02X}",
                "model": d.model,
            }
            for d in found
        ],
    }


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register domain diagnostic services once."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(DATA_SERVICES_REGISTERED):
        return

    async def handle_probe(call: ServiceCall) -> dict[str, Any]:
        return await _async_handle_probe(hass, call)

    async def handle_read(call: ServiceCall) -> dict[str, Any]:
        return await _async_handle_read(hass, call)

    async def handle_write(call: ServiceCall) -> dict[str, Any]:
        return await _async_handle_write(hass, call)

    async def handle_scan(call: ServiceCall) -> dict[str, Any]:
        return await _async_handle_scan(hass, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_PROBE_DEVICE,
        handle_probe,
        schema=PROBE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_READ_SERVICE,
        handle_read,
        schema=READ_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_WRITE_SERVICE,
        handle_write,
        schema=WRITE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SCAN_LAN,
        handle_scan,
        schema=SCAN_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    domain_data[DATA_SERVICES_REGISTERED] = True
    _LOGGER.debug("Registered %s diagnostic services", DOMAIN)


# Re-export for tests / callers that want a full snapshot after probe.
__all__ = [
    "async_register_services",
    "parse_service_id",
    "async_build_device_diagnostics",
]
