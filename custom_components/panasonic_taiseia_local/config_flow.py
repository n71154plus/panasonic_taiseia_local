"""Config flow for Panasonic TaiSEIA local.

Recommended path:
  1. Hub entry — official EMS login + shared LAN/energy settings
  2. Multi-select import of LAN devices matched to cloud nicknames / ModelType

Advanced: local-only discovery / manual IP (no cloud).
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD
from homeassistant.core import callback, HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .catalog import default_model_type, list_model_types, resolve_model_type
from .cloud import CloudAccount, CloudAuthError, CloudApiError, CloudDevice
from .cloud_sync import (
    async_sync_cloud_to_devices,
    cloud_fields_from_device,
)
from .const import (
    CONF_CLOUD_DEVICE_TYPE,
    CONF_CLOUD_GWID,
    CONF_CLOUD_MODEL,
    CONF_CLOUD_MODEL_ID,
    CONF_CLOUD_MODEL_TYPE,
    CONF_CLOUD_NICKNAME,
    CONF_CP_TOKEN,
    CONF_DEVICE_TYPE,
    CONF_ENERGY_CYCLE,
    CONF_ENERGY_CYCLE_DAYS,
    CONF_ENERGY_ENABLED,
    CONF_ENERGY_INCLUDE_HOUSE,
    CONF_ENERGY_RESET_DAY,
    CONF_ENERGY_RESET_PERIOD,
    CONF_ENERGY_RESET_TOTAL,
    CONF_ENERGY_RESET_WEEKDAY,
    CONF_ENTRY_TYPE,
    CONF_HUB_ENTRY_ID,
    CONF_INDOOR_MODEL,
    CONF_MAX_CONCURRENT,
    CONF_MODEL_TYPE,
    CONF_REFRESH_TOKEN,
    CONF_REQUEST_RETRIES,
    CONF_REQUEST_RETRY_DELAY,
    CONF_REQUEST_TIMEOUT,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DATA_CLIENT,
    DATA_ENERGY,
    DEFAULT_ENERGY_CYCLE,
    DEFAULT_ENERGY_CYCLE_DAYS,
    DEFAULT_ENERGY_RESET_DAY,
    DEFAULT_ENERGY_RESET_WEEKDAY,
    DEFAULT_MAX_CONCURRENT,
    DEFAULT_REQUEST_RETRIES,
    DEFAULT_REQUEST_RETRY_DELAY,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_UPDATE_INTERVAL,
    DEVICE_TYPE_NAMES,
    DOMAIN,
    ENERGY_CYCLE_OPTIONS,
    ENERGY_WEEKDAY_OPTIONS,
    ENTRY_TYPE_DEVICE,
    ENTRY_TYPE_HUB,
)
from .discovery import DiscoveredDevice, async_discover_devices, async_probe_host
from .energy import (
    EnergySettings,
    async_get_energy_settings,
    async_save_energy_settings,
)
from .lan_settings import (
    LanSettings,
    async_get_lan_settings,
    async_save_lan_settings,
)
from .naming import format_local_title
from .taiseia import TaiSeiaError, configure_lan_concurrency


def _model_type_choices(sa_type: int | None = None) -> dict[str, str]:
    types = list_model_types()
    cloud_dt = {1: 1, 2: 2, 4: 4}.get(sa_type or 0)
    choices: dict[str, str] = {"": "自動（依設備類型預設）"}
    preferred = list_model_types(cloud_dt) if cloud_dt else []
    for mt in preferred + [t for t in types if t not in preferred]:
        choices[mt] = mt
    return choices


def _hub_entry(hass: HomeAssistant) -> ConfigEntry | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
            return entry
    return None


def _configured_macs(hass: HomeAssistant) -> set[str]:
    out: set[str] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
            continue
        uid = (entry.unique_id or "").lower()
        if len(uid) == 12:
            out.add(uid)
        mac = (entry.data.get("mac") or "").lower()
        if len(mac) == 12:
            out.add(mac)
    return out


class TaiSeiaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._errors: dict[str, str] = {}
        self._discovered: dict[str, DiscoveredDevice] = {}
        self._cloud_devices: list[CloudDevice] = []
        self._account: str = ""
        self._password: str = ""
        self._cp_token: str | None = None
        self._refresh_token: str | None = None
        self._import_candidates: dict[str, dict[str, Any]] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        if config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
            return HubOptionsFlowHandler()
        return DeviceOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        hub = _hub_entry(self.hass)
        if user_input is not None:
            choice = user_input.get("setup_mode")
            if choice == "cloud":
                if hub:
                    return await self.async_step_import_devices()
                return await self.async_step_account()
            if choice == "import" and hub:
                return await self.async_step_import_devices()
            if choice == "discover":
                return await self.async_step_discover()
            return await self.async_step_manual()

        modes: dict[str, str] = {}
        if hub:
            modes["import"] = "從官網帳號匯入更多區網設備"
            modes["discover"] = "僅區網搜尋（進階）"
            modes["manual"] = "手動輸入 IP（進階）"
            default = "import"
        else:
            modes["cloud"] = "官網帳號登入並匯入設備（建議）"
            modes["discover"] = "僅區網搜尋（不登入）"
            modes["manual"] = "手動輸入 IP（不登入）"
            default = "cloud"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("setup_mode", default=default): vol.In(modes),
                }
            ),
        )

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        self._errors = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            session = async_get_clientsession(self.hass)
            client = CloudAccount(session, username, password)
            try:
                await client.login()
                devices = await client.async_get_devices()
            except CloudAuthError:
                self._errors["base"] = "auth"
            except CloudApiError:
                self._errors["base"] = "cloud_api"
            except Exception:  # noqa: BLE001
                self._errors["base"] = "cloud_api"
            else:
                await self.async_set_unique_id(f"hub:{username.lower()}")
                self._abort_if_unique_id_configured()
                self._account = username
                self._password = password
                self._cp_token = client.cp_token
                self._refresh_token = client.refresh_token
                self._cloud_devices = devices
                return await self.async_step_import_devices()

        return self.async_show_form(
            step_id="account",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=self._errors,
            description_placeholders={
                "hint": "使用 Panasonic 台灣智慧空調節能服務（EMS）帳號，與官方 App 相同。",
            },
        )

    async def _async_build_import_candidates(self) -> dict[str, str]:
        """Merge cloud inventory with LAN discovery. Return key → label."""
        session = async_get_clientsession(self.hass)
        try:
            found = await async_discover_devices(session, include_subnet_scan=True)
        except Exception:  # noqa: BLE001
            found = []
        by_mac = {(d.mac or "").upper(): d for d in found if d.mac}

        # Refresh cloud list if we have hub credentials but empty cache
        if not self._cloud_devices:
            hub = _hub_entry(self.hass)
            if hub:
                session = async_get_clientsession(self.hass)
                cloud = CloudAccount(
                    session,
                    hub.data.get(CONF_USERNAME, ""),
                    hub.data.get(CONF_PASSWORD, ""),
                    refresh_token=hub.data.get(CONF_REFRESH_TOKEN),
                    cp_token=hub.data.get(CONF_CP_TOKEN),
                )
                try:
                    self._cloud_devices = await cloud.async_get_devices()
                    # Persist refreshed tokens
                    new_data = dict(hub.data)
                    new_data[CONF_CP_TOKEN] = cloud.cp_token
                    new_data[CONF_REFRESH_TOKEN] = cloud.refresh_token
                    self.hass.config_entries.async_update_entry(hub, data=new_data)
                except Exception:  # noqa: BLE001
                    self._cloud_devices = []

        configured = _configured_macs(self.hass)
        self._import_candidates = {}
        choices: dict[str, str] = {}

        # Cloud-first (local-capable)
        seen_macs: set[str] = set()
        for cd in self._cloud_devices:
            if not cd.is_local_candidate or not cd.mac:
                continue
            mac = cd.mac.upper()
            seen_macs.add(mac)
            if mac.lower() in configured:
                continue
            local = by_mac.get(mac)
            type_name = DEVICE_TYPE_NAMES.get(cd.device_type, str(cd.device_type))
            if local:
                label = (
                    f"{cd.nickname} · {cd.model or local.model} · "
                    f"{cd.model_type or '?'} · {local.host} [{type_name}]"
                )
                self._import_candidates[mac] = {
                    CONF_HOST: local.host,
                    CONF_NAME: format_local_title(cd.nickname),
                    CONF_INDOOR_MODEL: cd.model or None,
                    CONF_MODEL_TYPE: cd.model_type or None,
                    CONF_DEVICE_TYPE: local.sa_type or cd.device_type,
                    "mac": mac,
                    **cloud_fields_from_device(cd),
                }
                choices[mac] = label
            else:
                # Cloud knows it but LAN miss — still list as unavailable note
                label = (
                    f"{cd.nickname} · {cd.model} · {cd.model_type} "
                    f"[區網未發現，略過]"
                )
                # not selectable
                choices[f"skip:{mac}"] = label

        # LAN devices not in cloud
        for mac, local in by_mac.items():
            if mac in seen_macs or mac.lower() in configured:
                continue
            type_name = DEVICE_TYPE_NAMES.get(local.sa_type, "")
            label = f"{local.label} · （官網無對應，僅本地）"
            self._import_candidates[mac] = {
                CONF_HOST: local.host,
                CONF_NAME: local.name or local.model or local.host,
                CONF_INDOOR_MODEL: None,
                CONF_MODEL_TYPE: default_model_type(local.sa_type),
                CONF_DEVICE_TYPE: local.sa_type,
                "mac": mac,
            }
            choices[mac] = label

        return choices

    async def async_step_import_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        self._errors = {}
        choices = await self._async_build_import_candidates()
        selectable = {k: v for k, v in choices.items() if not k.startswith("skip:")}
        skipped = [v for k, v in choices.items() if k.startswith("skip:")]

        if user_input is not None:
            selected = user_input.get("devices") or []
            if isinstance(selected, str):
                selected = [selected]
            selected = [s for s in selected if s in self._import_candidates]
            hub = _hub_entry(self.hass)
            # First-time cloud setup: allow hub-only (import devices later)
            if not selected and hub is None and self._account:
                return await self._async_finish_import([])
            if not selected:
                self._errors["base"] = "no_selection"
            else:
                return await self._async_finish_import(selected)

        if not selectable and not skipped and not self._account:
            self._errors["base"] = "no_devices"

        schema_dict: dict[Any, Any] = {}
        if selectable:
            schema_dict[
                vol.Required("devices", default=list(selectable))
            ] = cv.multi_select(selectable)

        return self.async_show_form(
            step_id="import_devices",
            data_schema=vol.Schema(schema_dict) if schema_dict else vol.Schema({}),
            errors=self._errors,
            description_placeholders={
                "skipped": ("\n".join(skipped) if skipped else "無"),
            },
        )

    async def _async_finish_import(self, selected: list[str]) -> FlowResult:
        hub = _hub_entry(self.hass)

        if hub is None:
            self.hass.data.setdefault(DOMAIN, {})
            self.hass.data[DOMAIN]["_pending_imports"] = [
                self._import_candidates[mac] for mac in selected
            ]
            return self.async_create_entry(
                title=f"Panasonic TaiSEIA（{self._account}）",
                data={
                    CONF_ENTRY_TYPE: ENTRY_TYPE_HUB,
                    CONF_USERNAME: self._account,
                    CONF_PASSWORD: self._password,
                    CONF_CP_TOKEN: self._cp_token,
                    CONF_REFRESH_TOKEN: self._refresh_token,
                },
            )

        for mac in selected:
            data = dict(self._import_candidates[mac])
            data[CONF_HUB_ENTRY_ID] = hub.entry_id
            data[CONF_ENTRY_TYPE] = ENTRY_TYPE_DEVICE
            await self.hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "device_import"},
                data=data,
            )
        return self.async_abort(reason="devices_imported")

    async def async_step_device_import(self, user_input: dict[str, Any]) -> FlowResult:
        """Create a single device entry (invoked programmatically)."""
        mac = (user_input.get("mac") or "").upper()
        host = user_input[CONF_HOST]
        uid = mac.lower() if mac else host
        await self.async_set_unique_id(uid)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        title = user_input.get(CONF_NAME) or host
        mt = resolve_model_type(
            user_input.get(CONF_MODEL_TYPE),
            int(user_input.get(CONF_DEVICE_TYPE) or 1),
            None,
        )
        return self.async_create_entry(
            title=title,
            data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_DEVICE,
                CONF_HOST: host,
                CONF_NAME: title,
                CONF_DEVICE_TYPE: int(user_input.get(CONF_DEVICE_TYPE) or 1),
                CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
                CONF_INDOOR_MODEL: user_input.get(CONF_INDOOR_MODEL),
                CONF_MODEL_TYPE: mt,
                CONF_HUB_ENTRY_ID: user_input.get(CONF_HUB_ENTRY_ID),
                "mac": mac or None,
                **{
                    k: user_input[k]
                    for k in (
                        CONF_CLOUD_NICKNAME,
                        CONF_CLOUD_MODEL,
                        CONF_CLOUD_MODEL_ID,
                        CONF_CLOUD_MODEL_TYPE,
                        CONF_CLOUD_DEVICE_TYPE,
                        CONF_CLOUD_GWID,
                    )
                    if user_input.get(k) not in (None, "")
                },
            },
            options={
                CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
                CONF_ENERGY_ENABLED: True,
                CONF_ENERGY_INCLUDE_HOUSE: True,
            },
        )

    # ---- advanced local-only paths (unchanged behaviour) ----

    async def async_step_discover(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        self._errors = {}
        if user_input is not None:
            key = user_input["device"]
            if key == "manual":
                return await self.async_step_manual()
            device = self._discovered.get(key)
            if not device:
                self._errors["base"] = "cannot_connect"
            else:
                return await self._async_create_local_device(
                    device,
                    user_input.get(CONF_NAME, ""),
                    user_input.get(CONF_INDOOR_MODEL, ""),
                    user_input.get(CONF_MODEL_TYPE, ""),
                )

        session = async_get_clientsession(self.hass)
        try:
            found = await async_discover_devices(session, include_subnet_scan=True)
        except Exception:  # noqa: BLE001
            found = []

        self._discovered = {}
        choices: dict[str, str] = {}
        configured = _configured_macs(self.hass)
        for dev in found:
            uid = (dev.mac or f"{dev.host}:{dev.port}").lower()
            if uid in configured or uid in {
                e.unique_id for e in self._async_current_entries() if e.unique_id
            }:
                continue
            self._discovered[uid] = dev
            choices[uid] = dev.label
        if not choices:
            self._errors["base"] = "no_devices"
        choices["manual"] = "改為手動輸入 IP…"
        return self.async_show_form(
            step_id="discover",
            data_schema=vol.Schema(
                {
                    vol.Required("device"): vol.In(choices),
                    vol.Optional(CONF_NAME, default=""): str,
                    vol.Optional(CONF_INDOOR_MODEL, default=""): str,
                    vol.Optional(CONF_MODEL_TYPE, default=""): vol.In(
                        _model_type_choices()
                    ),
                }
            ),
            errors=self._errors,
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        self._errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            session = async_get_clientsession(self.hass)
            try:
                device = await async_probe_host(session, host)
                if device is None:
                    raise TaiSeiaError("probe failed")
            except Exception:  # noqa: BLE001
                self._errors["base"] = "cannot_connect"
            else:
                return await self._async_create_local_device(
                    device,
                    user_input.get(CONF_NAME, ""),
                    user_input.get(CONF_INDOOR_MODEL, ""),
                    user_input.get(CONF_MODEL_TYPE, ""),
                )
        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_NAME, default=""): str,
                    vol.Optional(CONF_INDOOR_MODEL, default=""): str,
                    vol.Optional(CONF_MODEL_TYPE, default=""): vol.In(
                        _model_type_choices()
                    ),
                    vol.Optional(
                        CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
                    ): int,
                }
            ),
            errors=self._errors,
        )

    async def async_step_ssdp(self, discovery_info) -> FlowResult:
        host = discovery_info.ssdp_headers.get("_host") or discovery_info.upnp.get(
            "host"
        )
        if not host and discovery_info.ssdp_location:
            from urllib.parse import urlparse

            host = urlparse(discovery_info.ssdp_location).hostname
        if not host:
            return self.async_abort(reason="cannot_connect")
        session = async_get_clientsession(self.hass)
        device = await async_probe_host(session, host)
        if not device:
            return self.async_abort(reason="cannot_connect")
        await self.async_set_unique_id(
            device.mac.lower() if device.mac else device.host
        )
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self.context["title_placeholders"] = {"name": device.label}
        self._discovered = {(device.mac or host).lower(): device}
        return await self.async_step_discover_confirm()

    async def async_step_discover_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        device = next(iter(self._discovered.values()), None)
        if device is None:
            return self.async_abort(reason="cannot_connect")
        if user_input is not None:
            return await self._async_create_local_device(
                device,
                user_input.get(CONF_NAME, ""),
                user_input.get(CONF_INDOOR_MODEL, ""),
                user_input.get(CONF_MODEL_TYPE, ""),
            )
        return self.async_show_form(
            step_id="discover_confirm",
            description_placeholders={"name": device.label},
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_NAME, default=""): str,
                    vol.Optional(CONF_INDOOR_MODEL, default=""): str,
                    vol.Optional(CONF_MODEL_TYPE, default=""): vol.In(
                        _model_type_choices(device.sa_type)
                    ),
                }
            ),
        )

    async def _async_create_local_device(
        self,
        device: DiscoveredDevice,
        name: str,
        indoor_model: str = "",
        model_type: str = "",
    ) -> FlowResult:
        uid = (device.mac or f"{device.host}:{device.port}").lower()
        await self.async_set_unique_id(uid)
        self._abort_if_unique_id_configured(updates={CONF_HOST: device.host})
        type_name = DEVICE_TYPE_NAMES.get(device.sa_type, "")
        manual = (name or "").strip()
        indoor = (indoor_model or "").strip() or None
        mt = resolve_model_type(
            (model_type or "").strip() or None,
            device.sa_type,
            None,
        )
        if manual:
            title = manual
        else:
            title = device.model or device.name or device.host
            if type_name and type_name not in title:
                title = f"{title} ({type_name})"
        hub = _hub_entry(self.hass)
        return self.async_create_entry(
            title=title,
            data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_DEVICE,
                CONF_HOST: device.host,
                CONF_NAME: title,
                CONF_DEVICE_TYPE: device.sa_type,
                CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
                CONF_INDOOR_MODEL: indoor,
                CONF_MODEL_TYPE: mt,
                CONF_HUB_ENTRY_ID: hub.entry_id if hub else None,
                "mac": device.mac or None,
            },
            options={
                CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
                CONF_ENERGY_ENABLED: True,
                CONF_ENERGY_INCLUDE_HOUSE: True,
            },
        )


class HubOptionsFlowHandler(config_entries.OptionsFlow):
    """Shared account + LAN + energy settings."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        entry = self.config_entry
        energy = await async_get_energy_settings(self.hass)
        lan = await async_get_lan_settings(self.hass)

        if user_input is not None:
            new_data = dict(entry.data)
            if user_input.get(CONF_PASSWORD):
                new_data[CONF_PASSWORD] = user_input[CONF_PASSWORD]
            # Re-login if password changed
            if user_input.get(CONF_PASSWORD) or user_input.get("refresh_cloud"):
                session = async_get_clientsession(self.hass)
                cloud = CloudAccount(
                    session,
                    new_data.get(CONF_USERNAME, ""),
                    new_data.get(CONF_PASSWORD, ""),
                )
                try:
                    await cloud.login()
                    new_data[CONF_CP_TOKEN] = cloud.cp_token
                    new_data[CONF_REFRESH_TOKEN] = cloud.refresh_token
                except Exception:  # noqa: BLE001
                    return self.async_show_form(
                        step_id="init",
                        data_schema=self._schema(entry, energy, lan),
                        errors={"base": "auth"},
                    )

            settings = EnergySettings(
                cycle=str(user_input.get(CONF_ENERGY_CYCLE) or DEFAULT_ENERGY_CYCLE),
                reset_day=int(
                    user_input.get(CONF_ENERGY_RESET_DAY) or DEFAULT_ENERGY_RESET_DAY
                ),
                reset_weekday=int(
                    user_input.get(CONF_ENERGY_RESET_WEEKDAY)
                    or DEFAULT_ENERGY_RESET_WEEKDAY
                ),
                cycle_days=int(
                    user_input.get(CONF_ENERGY_CYCLE_DAYS)
                    or DEFAULT_ENERGY_CYCLE_DAYS
                ),
            )
            await async_save_energy_settings(self.hass, settings)

            lan_settings = LanSettings(
                timeout=float(
                    user_input.get(CONF_REQUEST_TIMEOUT) or DEFAULT_REQUEST_TIMEOUT
                ),
                retries=int(
                    user_input.get(CONF_REQUEST_RETRIES) or DEFAULT_REQUEST_RETRIES
                ),
                retry_delay=float(
                    user_input.get(CONF_REQUEST_RETRY_DELAY)
                    or DEFAULT_REQUEST_RETRY_DELAY
                ),
                max_concurrent=int(
                    user_input.get(CONF_MAX_CONCURRENT) or DEFAULT_MAX_CONCURRENT
                ),
            )
            await async_save_lan_settings(self.hass, lan_settings)
            configure_lan_concurrency(lan_settings.max_concurrent)

            domain = self.hass.data.get(DOMAIN) or {}
            for _eid, data in domain.items():
                if not isinstance(data, dict):
                    continue
                other = data.get(DATA_ENERGY)
                if other is not None:
                    other.apply_settings(settings)
                    other.ensure_period()
                client = data.get(DATA_CLIENT)
                if client is not None:
                    client.apply_lan_settings(
                        timeout=lan_settings.timeout,
                        retries=lan_settings.retries,
                        retry_delay=lan_settings.retry_delay,
                        max_concurrent=lan_settings.max_concurrent,
                    )

            self.hass.config_entries.async_update_entry(entry, data=new_data)
            if user_input.get(CONF_PASSWORD) or user_input.get("refresh_cloud"):
                await async_sync_cloud_to_devices(self.hass, entry)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=self._schema(entry, energy, lan),
        )

    @staticmethod
    def _schema(entry: ConfigEntry, energy: EnergySettings, lan: LanSettings):
        return vol.Schema(
            {
                vol.Optional(CONF_PASSWORD, default=""): str,
                vol.Optional("refresh_cloud", default=False): bool,
                vol.Optional(
                    CONF_REQUEST_TIMEOUT, default=lan.timeout
                ): vol.All(vol.Coerce(float), vol.Range(min=2, max=60)),
                vol.Optional(
                    CONF_REQUEST_RETRIES, default=lan.retries
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
                vol.Optional(
                    CONF_REQUEST_RETRY_DELAY, default=lan.retry_delay
                ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=10)),
                vol.Optional(
                    CONF_MAX_CONCURRENT, default=lan.max_concurrent
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
                vol.Optional(CONF_ENERGY_CYCLE, default=energy.cycle): vol.In(
                    ENERGY_CYCLE_OPTIONS
                ),
                vol.Optional(
                    CONF_ENERGY_CYCLE_DAYS, default=energy.cycle_days
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=365)),
                vol.Optional(
                    CONF_ENERGY_RESET_DAY, default=energy.reset_day
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=28)),
                vol.Optional(
                    CONF_ENERGY_RESET_WEEKDAY, default=energy.reset_weekday
                ): vol.In(ENERGY_WEEKDAY_OPTIONS),
            }
        )


class DeviceOptionsFlowHandler(config_entries.OptionsFlow):
    """Per-device options. Shared LAN/energy only if no hub entry exists."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        entry = self.config_entry
        has_hub = _hub_entry(self.hass) is not None
        energy = await async_get_energy_settings(self.hass)
        lan = await async_get_lan_settings(self.hass)

        if user_input is not None:
            name = (user_input.get(CONF_NAME) or "").strip()
            indoor = (user_input.get(CONF_INDOOR_MODEL) or "").strip() or None
            mt_raw = (user_input.get(CONF_MODEL_TYPE) or "").strip() or None
            interval = int(
                user_input.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
            )
            sa_type = int(entry.data.get(CONF_DEVICE_TYPE) or 1)
            mt = resolve_model_type(mt_raw, sa_type, None)
            new_data = dict(entry.data)
            if name:
                new_data[CONF_NAME] = name
            new_data[CONF_INDOOR_MODEL] = indoor
            new_data[CONF_MODEL_TYPE] = mt
            new_options = {
                CONF_UPDATE_INTERVAL: interval,
                CONF_ENERGY_ENABLED: bool(user_input.get(CONF_ENERGY_ENABLED, True)),
                CONF_ENERGY_INCLUDE_HOUSE: bool(
                    user_input.get(CONF_ENERGY_INCLUDE_HOUSE, True)
                ),
            }
            domain = self.hass.data.get(DOMAIN) or {}
            slot = domain.get(entry.entry_id) or {}
            tracker = slot.get(DATA_ENERGY)
            if tracker is not None:
                if user_input.get(CONF_ENERGY_RESET_PERIOD):
                    tracker.reset_period()
                if user_input.get(CONF_ENERGY_RESET_TOTAL):
                    tracker.reset_total()
                from .energy import async_save_tracker

                await async_save_tracker(self.hass, entry.entry_id, tracker)

            if not has_hub:
                settings = EnergySettings(
                    cycle=str(
                        user_input.get(CONF_ENERGY_CYCLE) or DEFAULT_ENERGY_CYCLE
                    ),
                    reset_day=int(
                        user_input.get(CONF_ENERGY_RESET_DAY)
                        or DEFAULT_ENERGY_RESET_DAY
                    ),
                    reset_weekday=int(
                        user_input.get(CONF_ENERGY_RESET_WEEKDAY)
                        or DEFAULT_ENERGY_RESET_WEEKDAY
                    ),
                    cycle_days=int(
                        user_input.get(CONF_ENERGY_CYCLE_DAYS)
                        or DEFAULT_ENERGY_CYCLE_DAYS
                    ),
                )
                await async_save_energy_settings(self.hass, settings)
                lan_settings = LanSettings(
                    timeout=float(
                        user_input.get(CONF_REQUEST_TIMEOUT)
                        or DEFAULT_REQUEST_TIMEOUT
                    ),
                    retries=int(
                        user_input.get(CONF_REQUEST_RETRIES)
                        or DEFAULT_REQUEST_RETRIES
                    ),
                    retry_delay=float(
                        user_input.get(CONF_REQUEST_RETRY_DELAY)
                        or DEFAULT_REQUEST_RETRY_DELAY
                    ),
                    max_concurrent=int(
                        user_input.get(CONF_MAX_CONCURRENT)
                        or DEFAULT_MAX_CONCURRENT
                    ),
                )
                await async_save_lan_settings(self.hass, lan_settings)
                configure_lan_concurrency(lan_settings.max_concurrent)
                for _eid, data in domain.items():
                    if not isinstance(data, dict):
                        continue
                    other = data.get(DATA_ENERGY)
                    if other is not None:
                        other.apply_settings(settings)
                        other.ensure_period()
                    client = data.get(DATA_CLIENT)
                    if client is not None:
                        client.apply_lan_settings(
                            timeout=lan_settings.timeout,
                            retries=lan_settings.retries,
                            retry_delay=lan_settings.retry_delay,
                            max_concurrent=lan_settings.max_concurrent,
                        )

            self.hass.config_entries.async_update_entry(
                entry,
                data=new_data,
                title=name or entry.title,
                options=new_options,
            )
            return self.async_create_entry(title="", data=new_options)

        sa_type = int(entry.data.get(CONF_DEVICE_TYPE) or 1)
        current_mt = (
            entry.data.get(CONF_MODEL_TYPE) or default_model_type(sa_type) or ""
        )
        opts = entry.options
        schema: dict[Any, Any] = {
            vol.Optional(
                CONF_NAME,
                default=entry.data.get(CONF_NAME) or entry.title or "",
            ): str,
            vol.Optional(
                CONF_INDOOR_MODEL,
                default=entry.data.get(CONF_INDOOR_MODEL) or "",
            ): str,
            vol.Optional(CONF_MODEL_TYPE, default=current_mt): vol.In(
                _model_type_choices(sa_type)
            ),
            vol.Optional(
                CONF_UPDATE_INTERVAL,
                default=opts.get(
                    CONF_UPDATE_INTERVAL,
                    entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=600)),
            vol.Optional(
                CONF_ENERGY_ENABLED,
                default=opts.get(CONF_ENERGY_ENABLED, True),
            ): bool,
            vol.Optional(
                CONF_ENERGY_INCLUDE_HOUSE,
                default=opts.get(CONF_ENERGY_INCLUDE_HOUSE, True),
            ): bool,
            vol.Optional(CONF_ENERGY_RESET_PERIOD, default=False): bool,
            vol.Optional(CONF_ENERGY_RESET_TOTAL, default=False): bool,
        }
        if not has_hub:
            schema.update(
                {
                    vol.Optional(
                        CONF_REQUEST_TIMEOUT, default=lan.timeout
                    ): vol.All(vol.Coerce(float), vol.Range(min=2, max=60)),
                    vol.Optional(
                        CONF_REQUEST_RETRIES, default=lan.retries
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
                    vol.Optional(
                        CONF_REQUEST_RETRY_DELAY, default=lan.retry_delay
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=10)),
                    vol.Optional(
                        CONF_MAX_CONCURRENT, default=lan.max_concurrent
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
                    vol.Optional(CONF_ENERGY_CYCLE, default=energy.cycle): vol.In(
                        ENERGY_CYCLE_OPTIONS
                    ),
                    vol.Optional(
                        CONF_ENERGY_CYCLE_DAYS, default=energy.cycle_days
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=365)),
                    vol.Optional(
                        CONF_ENERGY_RESET_DAY, default=energy.reset_day
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=28)),
                    vol.Optional(
                        CONF_ENERGY_RESET_WEEKDAY, default=energy.reset_weekday
                    ): vol.In(ENERGY_WEEKDAY_OPTIONS),
                }
            )
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))


# Back-compat alias
OptionsFlowHandler = DeviceOptionsFlowHandler
