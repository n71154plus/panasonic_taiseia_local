"""Unified device control: hybrid / local / cloud routing."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .cloud import (
    CloudAccount,
    CloudApiError,
    CloudAuthError,
    CloudDeviceOffline,
    CloudRateLimited,
    command_type_hex,
)
from .const import (
    CONF_CLOUD_AUTH,
    CONF_CLOUD_GWID,
    CONF_CONTROL_MODE,
    CONF_CP_TOKEN,
    CONF_ENTRY_TYPE,
    CONF_HUB_ENTRY_ID,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_USERNAME,
    CONTROL_MODE_CLOUD,
    CONTROL_MODE_HYBRID,
    CONTROL_MODE_LOCAL,
    DATA_EMS_GATE,
    DEFAULT_CONTROL_MODE,
    DOMAIN,
    ENTRY_TYPE_HUB,
)
from .ems_transport import EmsGate, EmsSettings, RequestPriority
from .taiseia import TaiSeiaClient, status_key

_LOGGER = logging.getLogger(__package__)


def resolve_control_mode(entry: ConfigEntry, *, cloud_only: bool = False) -> str:
    if cloud_only:
        return CONTROL_MODE_CLOUD
    mode = entry.options.get(CONF_CONTROL_MODE) or DEFAULT_CONTROL_MODE
    if mode not in (
        CONTROL_MODE_HYBRID,
        CONTROL_MODE_LOCAL,
        CONTROL_MODE_CLOUD,
    ):
        return DEFAULT_CONTROL_MODE
    return str(mode)


def entry_has_cloud_creds(entry: ConfigEntry) -> bool:
    return bool(entry.data.get(CONF_CLOUD_GWID) and entry.data.get(CONF_CLOUD_AUTH))


def _hub_entry(hass: HomeAssistant, device_entry: ConfigEntry) -> ConfigEntry | None:
    hub_id = device_entry.data.get(CONF_HUB_ENTRY_ID)
    if hub_id:
        hub = hass.config_entries.async_get_entry(hub_id)
        if hub and hub.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
            return hub
    for ent in hass.config_entries.async_entries(DOMAIN):
        if ent.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
            return ent
    return None


async def async_get_shared_gate(hass: HomeAssistant) -> EmsGate:
    domain = hass.data.setdefault(DOMAIN, {})
    gate = domain.get(DATA_EMS_GATE)
    if isinstance(gate, EmsGate):
        return gate
    gate = EmsGate(EmsSettings())
    domain[DATA_EMS_GATE] = gate
    return gate


async def async_get_cloud_account(
    hass: HomeAssistant, device_entry: ConfigEntry
) -> CloudAccount | None:
    hub = _hub_entry(hass, device_entry)
    if hub is None:
        return None
    username = hub.data.get(CONF_USERNAME)
    password = hub.data.get(CONF_PASSWORD)
    if not username or not password:
        return None
    gate = await async_get_shared_gate(hass)
    session = async_get_clientsession(hass)
    return CloudAccount(
        session,
        username,
        password,
        refresh_token=hub.data.get(CONF_REFRESH_TOKEN),
        cp_token=hub.data.get(CONF_CP_TOKEN),
        gate=gate,
    )


async def async_refresh_cloud_auth(
    hass: HomeAssistant, entry: ConfigEntry
) -> tuple[str, str] | None:
    """Return (gwid, auth), refreshing Auth from hub GwList if needed."""
    gwid = (entry.data.get(CONF_CLOUD_GWID) or "").strip()
    auth = (entry.data.get(CONF_CLOUD_AUTH) or "").strip()
    if gwid and auth:
        return gwid, auth
    cloud = await async_get_cloud_account(hass, entry)
    if cloud is None:
        return None
    try:
        devices = await cloud.async_get_devices()
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("refresh cloud auth failed: %s", err)
        return None
    # Persist tokens if refreshed
    hub = _hub_entry(hass, entry)
    if hub is not None and (cloud.cp_token or cloud.refresh_token):
        new_hub = dict(hub.data)
        if cloud.cp_token:
            new_hub[CONF_CP_TOKEN] = cloud.cp_token
        if cloud.refresh_token:
            new_hub[CONF_REFRESH_TOKEN] = cloud.refresh_token
        hass.config_entries.async_update_entry(hub, data=new_hub)

    match = None
    if gwid:
        match = next((d for d in devices if d.gwid == gwid), None)
    if match is None:
        mac = (entry.data.get("mac") or entry.unique_id or "").replace(":", "").upper()
        if len(mac) == 12:
            match = next((d for d in devices if (d.mac or "").upper() == mac), None)
    if match is None or not match.auth:
        return (gwid, auth) if gwid and auth else None
    new_data = dict(entry.data)
    new_data[CONF_CLOUD_GWID] = match.gwid
    new_data[CONF_CLOUD_AUTH] = match.auth
    hass.config_entries.async_update_entry(entry, data=new_data)
    return match.gwid, match.auth


class DeviceControl:
    """Route writes/reads per control_mode."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: TaiSeiaClient,
        *,
        cloud_only: bool = False,
        lan_ok: bool = True,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client
        self.cloud_only = cloud_only
        self.lan_ok = lan_ok
        self.last_path: str | None = None
        self._cloud: CloudAccount | None = None

    @property
    def mode(self) -> str:
        live = self.hass.config_entries.async_get_entry(self.entry.entry_id) or self.entry
        return resolve_control_mode(live, cloud_only=self.cloud_only)

    def can_use_lan(self) -> bool:
        return self.lan_ok and not self.cloud_only and bool(self.client.host)

    def can_use_cloud(self) -> bool:
        live = self.hass.config_entries.async_get_entry(self.entry.entry_id) or self.entry
        return entry_has_cloud_creds(live) or bool(live.data.get(CONF_CLOUD_GWID))

    async def _cloud_account(self) -> CloudAccount | None:
        if self._cloud is None:
            self._cloud = await async_get_cloud_account(self.hass, self.entry)
        return self._cloud

    async def async_write(self, service: int, value: int) -> str:
        """Write one TaiSEIA service; return path used ('cloud'|'lan')."""
        mode = self.mode
        errors: list[str] = []

        async def _cloud() -> None:
            creds = await async_refresh_cloud_auth(self.hass, self.entry)
            if not creds:
                raise CloudApiError("missing cloud GWID/Auth")
            gwid, auth = creds
            cloud = await self._cloud_account()
            if cloud is None:
                raise CloudApiError("no hub cloud account")
            await cloud.async_set_command(
                auth=auth,
                gwid=gwid,
                command_type=command_type_hex(service),
                value=value,
                priority=RequestPriority.USER,
            )
            # Persist refreshed tokens
            hub = _hub_entry(self.hass, self.entry)
            if hub is not None:
                new_hub = dict(hub.data)
                changed = False
                if cloud.cp_token and new_hub.get(CONF_CP_TOKEN) != cloud.cp_token:
                    new_hub[CONF_CP_TOKEN] = cloud.cp_token
                    changed = True
                if (
                    cloud.refresh_token
                    and new_hub.get(CONF_REFRESH_TOKEN) != cloud.refresh_token
                ):
                    new_hub[CONF_REFRESH_TOKEN] = cloud.refresh_token
                    changed = True
                if changed:
                    self.hass.config_entries.async_update_entry(hub, data=new_hub)

        async def _lan() -> None:
            await self.client.async_write_device(service, value)

        if mode == CONTROL_MODE_LOCAL:
            if not self.can_use_lan():
                raise CloudApiError("local mode but LAN unavailable")
            await _lan()
            self.last_path = "lan"
            return "lan"

        if mode == CONTROL_MODE_CLOUD:
            await _cloud()
            self.last_path = "cloud"
            return "cloud"

        # hybrid: cloud first, LAN assist
        if self.can_use_cloud():
            try:
                await _cloud()
                self.last_path = "cloud"
                return "cloud"
            except (CloudRateLimited, CloudDeviceOffline, CloudAuthError, CloudApiError) as err:
                errors.append(f"cloud:{err}")
                _LOGGER.info(
                    "hybrid write cloud failed (%s); trying LAN", err
                )
        if self.can_use_lan():
            try:
                await _lan()
                self.last_path = "lan"
                return "lan"
            except Exception as err:  # noqa: BLE001
                errors.append(f"lan:{err}")
                raise
        raise CloudApiError("; ".join(errors) or "no write path available")

    async def async_fetch_status(
        self, command_types: list[str] | None = None
    ) -> tuple[dict[str, Any], str]:
        """Return (status, path)."""
        mode = self.mode
        errors: list[str] = []

        async def _lan() -> dict[str, Any]:
            return await self.client.async_fetch_status()

        async def _cloud() -> dict[str, Any]:
            creds = await async_refresh_cloud_auth(self.hass, self.entry)
            if not creds:
                raise CloudApiError("missing cloud GWID/Auth")
            gwid, auth = creds
            cloud = await self._cloud_account()
            if cloud is None:
                raise CloudApiError("no hub cloud account")
            types = command_types or [
                command_type_hex(sid) for sid in (self.client.poll_services or [0, 1, 3, 4])
            ]
            # Cap batch size to reduce EMS load
            types = types[:24]
            return await cloud.async_get_device_info(
                auth=auth,
                gwid=gwid,
                command_types=types,
                priority=RequestPriority.BACKGROUND,
            )

        if mode == CONTROL_MODE_LOCAL:
            status = await _lan()
            self.last_path = "lan"
            return status, "lan"

        if mode == CONTROL_MODE_CLOUD:
            status = await _cloud()
            self.last_path = "cloud"
            return status, "cloud"

        # hybrid: LAN first
        if self.can_use_lan():
            try:
                status = await _lan()
                self.last_path = "lan"
                return status, "lan"
            except Exception as err:  # noqa: BLE001
                errors.append(f"lan:{err}")
                _LOGGER.debug("hybrid read LAN failed (%s); trying cloud", err)
        if self.can_use_cloud():
            try:
                status = await _cloud()
                self.last_path = "cloud"
                return status, "cloud"
            except Exception as err:  # noqa: BLE001
                errors.append(f"cloud:{err}")
                raise CloudApiError("; ".join(errors)) from err
        raise CloudApiError("; ".join(errors) or "no read path available")


def default_cloud_command_types(profile_service_ids: list[int] | None) -> list[str]:
    ids = profile_service_ids or [0x00, 0x01, 0x02, 0x03, 0x04, 0x0F, 0x17]
    return [command_type_hex(i) for i in ids]


# Avoid unused import lint for status_key when used by callers
_ = status_key
