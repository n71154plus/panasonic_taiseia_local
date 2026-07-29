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

from .catalog import (
    default_model_type,
    list_model_types,
    model_type_matches_device,
    resolve_model_type,
)
from .cloud import CloudAccount, CloudAuthError, CloudApiError, CloudDevice
from .cloud_sync import (
    async_sync_cloud_to_devices,
    cloud_fields_from_device,
)
from .flow_helpers import (
    cloud_only_import_data as _cloud_only_import_data,
    coalesce_sa_type,
    configured_ids as _configured_ids,
    configured_macs as _configured_macs,
    ems_to_sa_type as _ems_to_sa_type,
    hub_entry as _hub_entry,
)
from .const import (
    CONF_CLOUD_AUTH,
    CONF_CLOUD_DEVICE_TYPE,
    CONF_CLOUD_GWID,
    CONF_CLOUD_MODEL,
    CONF_CLOUD_MODEL_ID,
    CONF_CLOUD_MODEL_TYPE,
    CONF_CLOUD_NICKNAME,
    CONF_CONTROL_MODE,
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
    CONTROL_MODE_CLOUD,
    CONTROL_MODE_OPTIONS,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DATA_ENERGY,
    DEFAULT_CONTROL_MODE,
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
    TYPE_AC,
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
from .naming import format_cloud_title, format_local_title, mask_account
from .taiseia import TaiSeiaError, configure_lan_concurrency


def _model_type_choices(sa_type: int | None = None) -> dict[str, str]:
    """ModelType picker: preferred for this SA type first, then the rest."""
    choices: dict[str, str] = {"": "自動（依設備類型預設）"}
    all_types = list_model_types()
    preferred = list_model_types(sa_type) if sa_type else []
    for mt in preferred + [t for t in all_types if t not in preferred]:
        choices[mt] = mt
    return choices




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

    def _upgrade_existing_to_lan(
        self, *, host: str, mac: str | None
    ) -> None:
        """If unique_id exists as cloud-only, attach LAN host and unlock control.

        Always ends in ``_abort_if_unique_id_configured`` when an entry matches.
        """
        updates: dict[str, Any] = {
            CONF_HOST: host,
            "cloud_only": False,
        }
        if mac:
            updates["mac"] = mac
        # Restore hybrid when a prior cloud-only lock forced CONTROL_MODE_CLOUD.
        for existing in self._async_current_entries():
            if existing.unique_id != self.unique_id:
                continue
            was_cloud_only = bool(existing.data.get("cloud_only")) or (
                str(existing.data.get(CONF_HOST) or "") in ("", "0.0.0.0")
            )
            if (
                was_cloud_only
                and existing.options.get(CONF_CONTROL_MODE) == CONTROL_MODE_CLOUD
            ):
                self.hass.config_entries.async_update_entry(
                    existing,
                    options={
                        **dict(existing.options),
                        CONF_CONTROL_MODE: DEFAULT_CONTROL_MODE,
                    },
                )
            break
        self._abort_if_unique_id_configured(updates=updates)

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
            from .control import async_get_shared_gate

            gate = await async_get_shared_gate(self.hass)
            client = CloudAccount(session, username, password, gate=gate)
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

    def _subnet_hints(self) -> list[str]:
        hints: list[str] = []
        local_ip = getattr(self.hass.config, "local_ip", None)
        if local_ip:
            hints.append(str(local_ip))
        return hints

    async def _async_cloud_client(self) -> CloudAccount | None:
        """Cloud client from in-progress login or existing hub entry."""
        from .control import async_get_shared_gate

        session = async_get_clientsession(self.hass)
        gate = await async_get_shared_gate(self.hass)
        if self._account and self._password:
            return CloudAccount(
                session,
                self._account,
                self._password,
                refresh_token=self._refresh_token,
                cp_token=self._cp_token,
                gate=gate,
            )
        hub = _hub_entry(self.hass)
        if not hub:
            return None
        return CloudAccount(
            session,
            hub.data.get(CONF_USERNAME, ""),
            hub.data.get(CONF_PASSWORD, ""),
            refresh_token=hub.data.get(CONF_REFRESH_TOKEN),
            cp_token=hub.data.get(CONF_CP_TOKEN),
            gate=gate,
        )

    async def _async_build_import_candidates(self) -> dict[str, str]:
        """Merge cloud inventory with LAN discovery. Return key → label."""
        session = async_get_clientsession(self.hass)
        try:
            found = await async_discover_devices(
                session,
                include_subnet_scan=True,
                subnet_hints=self._subnet_hints(),
            )
        except Exception:  # noqa: BLE001
            found = []
        by_mac = {(d.mac or "").upper(): d for d in found if d.mac}

        cloud = await self._async_cloud_client()
        if not self._cloud_devices and cloud is not None:
            try:
                self._cloud_devices = await cloud.async_get_devices()
                hub = _hub_entry(self.hass)
                if hub is not None:
                    from .entry_helpers import async_update_entry_data

                    new_data = dict(hub.data)
                    new_data[CONF_CP_TOKEN] = cloud.cp_token
                    new_data[CONF_REFRESH_TOKEN] = cloud.refresh_token
                    async_update_entry_data(self.hass, hub, data=new_data)
                if self._account:
                    self._cp_token = cloud.cp_token
                    self._refresh_token = cloud.refresh_token
            except Exception:  # noqa: BLE001
                self._cloud_devices = []

        configured = _configured_ids(self.hass)
        self._import_candidates = {}
        choices: dict[str, str] = {}
        seen_macs: set[str] = set()
        seen_gwids: set[str] = set()

        def _add_cloud_only(cd: CloudDevice, *, mac: str | None = None, reason: str) -> None:
            gwid = (cd.gwid or "").strip()
            if not gwid or not cd.auth:
                return
            gkey = gwid.lower()
            if gkey in configured or gkey in seen_gwids:
                return
            if mac and mac.lower() in configured:
                return
            seen_gwids.add(gkey)
            type_name = DEVICE_TYPE_NAMES.get(
                _ems_to_sa_type(cd.device_type), str(cd.device_type)
            )
            key = f"cloud:{gwid}"
            label = (
                f"{cd.nickname} · {cd.model or '?'} · {cd.model_type or '?'} "
                f"[{type_name} · 僅雲端 · {reason}]"
            )
            self._import_candidates[key] = _cloud_only_import_data(cd, mac=mac)
            choices[key] = label

        # Phase 1: resolve missing LAN hosts via EMS GWIP (bounded concurrency)
        need_gwip: list[CloudDevice] = []
        for cd in self._cloud_devices:
            if not cd.is_local_candidate or not cd.mac:
                continue
            mac = cd.mac.upper()
            if mac.lower() in configured:
                continue
            if by_mac.get(mac) is None:
                need_gwip.append(cd)

        if need_gwip and cloud is not None:
            import asyncio

            sem = asyncio.Semaphore(4)

            async def _resolve(cd: CloudDevice) -> None:
                mac = cd.mac.upper()
                async with sem:
                    try:
                        gw_ip = await cloud.async_get_gw_ip(cd.gwid)
                    except Exception:  # noqa: BLE001
                        return
                    if not gw_ip:
                        return
                    probed = await async_probe_host(session, gw_ip)
                    if probed is None:
                        return
                    probed_mac = (probed.mac or "").upper()
                    if probed_mac and probed_mac != mac:
                        return
                    by_mac[mac] = probed

            await asyncio.gather(*(_resolve(cd) for cd in need_gwip))

        # Phase 2: build choices
        lan_discovered_macs = {(d.mac or "").upper() for d in found if d.mac}
        for cd in self._cloud_devices:
            gwid = (cd.gwid or "").strip()
            if gwid and gwid.lower() in configured:
                continue

            # Pure cloud devices (fridge etc. — non-MAC GWID)
            if not cd.is_local_candidate or not cd.mac:
                _add_cloud_only(cd, reason="無區網模組")
                continue

            mac = cd.mac.upper()
            seen_macs.add(mac)
            if mac.lower() in configured:
                continue

            local = by_mac.get(mac)
            type_name = DEVICE_TYPE_NAMES.get(cd.device_type, str(cd.device_type))
            source = "區網掃描" if mac in lan_discovered_macs else "官網 IP"

            if local:
                label = (
                    f"{cd.nickname} · {cd.model or local.model} · "
                    f"{cd.model_type or '?'} · {local.host} "
                    f"[{type_name} · {source}]"
                )
                sa_type = coalesce_sa_type(
                    local.sa_type, cd.device_type, default=TYPE_AC
                )
                if sa_type is None:
                    sa_type = TYPE_AC
                mt = (cd.model_type or "").strip() or None
                if mt and not model_type_matches_device(mt, sa_type):
                    mt = None
                self._import_candidates[mac] = {
                    CONF_HOST: local.host,
                    CONF_NAME: format_local_title(cd.nickname),
                    CONF_INDOOR_MODEL: cd.model or None,
                    CONF_MODEL_TYPE: mt,
                    CONF_DEVICE_TYPE: sa_type,
                    "mac": mac,
                    "cloud_only": False,
                    **cloud_fields_from_device(cd),
                }
                choices[mac] = label
            else:
                _add_cloud_only(cd, mac=mac, reason="區網未發現，可雲端控制")

        # LAN devices not in cloud
        for mac, local in by_mac.items():
            if mac in seen_macs or mac.lower() in configured:
                continue
            label = f"{local.label} · （官網無對應，僅本地）"
            self._import_candidates[mac] = {
                CONF_HOST: local.host,
                CONF_NAME: local.name or local.model or local.host,
                CONF_INDOOR_MODEL: None,
                CONF_MODEL_TYPE: default_model_type(local.sa_type),
                CONF_DEVICE_TYPE: local.sa_type,
                "mac": mac,
                "cloud_only": False,
            }
            choices[mac] = label

        return choices

    async def async_step_import_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        self._errors = {}
        choices = await self._async_build_import_candidates()
        selectable = dict(choices)

        if user_input is not None:
            selected = user_input.get("devices") or []
            if isinstance(selected, str):
                selected = [selected]
            selected = [s for s in selected if s in self._import_candidates]
            hub = _hub_entry(self.hass)
            if not selected and hub is None and self._account:
                return await self._async_finish_import([])
            if not selected:
                self._errors["base"] = "no_selection"
            else:
                return await self._async_finish_import(selected)

        if not selectable and not self._account:
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
                "skipped": "無（無法區網者會標「僅雲端」並可勾選匯入）",
            },
        )

    async def _async_finish_import(self, selected: list[str]) -> FlowResult:
        hub = _hub_entry(self.hass)

        if hub is None:
            self.hass.data.setdefault(DOMAIN, {})
            self.hass.data[DOMAIN]["_pending_imports"] = [
                self._import_candidates[key] for key in selected
            ]
            return self.async_create_entry(
                title=f"Panasonic TaiSEIA（{mask_account(self._account)}）",
                data={
                    CONF_ENTRY_TYPE: ENTRY_TYPE_HUB,
                    CONF_USERNAME: self._account,
                    CONF_PASSWORD: self._password,
                    CONF_CP_TOKEN: self._cp_token,
                    CONF_REFRESH_TOKEN: self._refresh_token,
                },
            )

        for key in selected:
            data = dict(self._import_candidates[key])
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
        mac = (user_input.get("mac") or "").upper() or None
        gwid = (user_input.get(CONF_CLOUD_GWID) or "").strip()
        host = (user_input.get(CONF_HOST) or "0.0.0.0").strip() or "0.0.0.0"
        cloud_only = bool(user_input.get("cloud_only")) or host in ("", "0.0.0.0")
        if mac and len(mac) == 12:
            uid = mac.lower()
        elif gwid:
            uid = f"gwid:{gwid.lower()}"
        else:
            uid = host
        await self.async_set_unique_id(uid)
        updates: dict[str, Any] = {}
        if host and host not in ("", "0.0.0.0"):
            updates[CONF_HOST] = host
        if updates:
            self._abort_if_unique_id_configured(updates=updates)
        else:
            self._abort_if_unique_id_configured()
        title = user_input.get(CONF_NAME) or gwid or host
        sa_type = coalesce_sa_type(
            user_input.get(CONF_DEVICE_TYPE), default=TYPE_AC
        )
        if sa_type is None:
            sa_type = TYPE_AC
        mt = resolve_model_type(
            user_input.get(CONF_MODEL_TYPE),
            sa_type,
            None,
        )
        options = {
            CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
            CONF_ENERGY_ENABLED: True,
            CONF_ENERGY_INCLUDE_HOUSE: True,
        }
        if cloud_only:
            options[CONF_CONTROL_MODE] = CONTROL_MODE_CLOUD
        cloud_keys = {
            k: user_input[k]
            for k in (
                CONF_CLOUD_NICKNAME,
                CONF_CLOUD_MODEL,
                CONF_CLOUD_MODEL_ID,
                CONF_CLOUD_MODEL_TYPE,
                CONF_CLOUD_DEVICE_TYPE,
                CONF_CLOUD_GWID,
                CONF_CLOUD_AUTH,
            )
            if user_input.get(k) not in (None, "")
        }
        return self.async_create_entry(
            title=title,
            data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_DEVICE,
                CONF_HOST: host,
                CONF_NAME: title,
                CONF_DEVICE_TYPE: sa_type,
                CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
                CONF_INDOOR_MODEL: user_input.get(CONF_INDOOR_MODEL),
                CONF_MODEL_TYPE: mt,
                CONF_HUB_ENTRY_ID: user_input.get(CONF_HUB_ENTRY_ID),
                "mac": mac,
                "cloud_only": cloud_only,
                **cloud_keys,
            },
            options=options,
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
            found = await async_discover_devices(
                session,
                include_subnet_scan=True,
                subnet_hints=self._subnet_hints(),
            )
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
        self._upgrade_existing_to_lan(
            host=host,
            mac=(device.mac or "").upper() or None,
        )
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
        # Re-adding a previously cloud-only MAC with a working LAN host upgrades it.
        self._upgrade_existing_to_lan(
            host=device.host,
            mac=(device.mac or "").upper() or None,
        )
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
                from .control import async_get_shared_gate

                session = async_get_clientsession(self.hass)
                gate = await async_get_shared_gate(self.hass)
                cloud = CloudAccount(
                    session,
                    new_data.get(CONF_USERNAME, ""),
                    new_data.get(CONF_PASSWORD, ""),
                    gate=gate,
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

            from .entry_helpers import async_update_entry_data

            async_update_entry_data(self.hass, entry, data=new_data)
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

    def _device_is_cloud_only(self, entry: ConfigEntry) -> bool:
        slot = (self.hass.data.get(DOMAIN) or {}).get(entry.entry_id) or {}
        coord = slot.get(DATA_COORDINATOR)
        cloud_only = bool(
            coord and (getattr(coord, "data", None) or {}).get("cloud_only")
        )
        if cloud_only:
            return True
        if bool(entry.data.get("cloud_only")):
            return True
        host = (entry.data.get(CONF_HOST) or "").strip()
        if (
            entry.data.get(CONF_CLOUD_GWID)
            and entry.data.get(CONF_CLOUD_AUTH)
            and host in ("", "0.0.0.0")
        ):
            return True
        return False

    def _device_options_schema(
        self,
        entry: ConfigEntry,
        *,
        has_hub: bool,
        energy: Any,
        lan: Any,
    ) -> vol.Schema:
        sa_type = coalesce_sa_type(
            entry.data.get(CONF_DEVICE_TYPE),
            entry.data.get(CONF_CLOUD_DEVICE_TYPE),
            default=TYPE_AC,
        )
        if sa_type is None:
            sa_type = TYPE_AC
        current_mt = (
            entry.data.get(CONF_MODEL_TYPE) or default_model_type(sa_type) or ""
        )
        opts = entry.options
        host_default = (entry.data.get(CONF_HOST) or "").strip()
        if host_default == "0.0.0.0":
            host_default = ""
        schema: dict[Any, Any] = {
            vol.Optional(
                CONF_NAME,
                default=entry.data.get(CONF_NAME) or entry.title or "",
            ): str,
            vol.Optional(CONF_HOST, default=host_default): str,
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
        cloud_only = self._device_is_cloud_only(entry)
        if cloud_only:
            # Still show the dropdown (cloud only) — unlock by filling Host IP.
            schema[
                vol.Optional(
                    CONF_CONTROL_MODE,
                    default=CONTROL_MODE_CLOUD,
                )
            ] = vol.In({CONTROL_MODE_CLOUD: CONTROL_MODE_OPTIONS[CONTROL_MODE_CLOUD]})
        else:
            schema[
                vol.Optional(
                    CONF_CONTROL_MODE,
                    default=opts.get(CONF_CONTROL_MODE, DEFAULT_CONTROL_MODE),
                )
            ] = vol.In(CONTROL_MODE_OPTIONS)
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
        return vol.Schema(schema)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        entry = self.config_entry
        has_hub = _hub_entry(self.hass) is not None
        energy = await async_get_energy_settings(self.hass)
        lan = await async_get_lan_settings(self.hass)
        errors: dict[str, str] = {}

        if user_input is not None:
            name = (user_input.get(CONF_NAME) or "").strip()
            indoor = (user_input.get(CONF_INDOOR_MODEL) or "").strip() or None
            mt_raw = (user_input.get(CONF_MODEL_TYPE) or "").strip() or None
            interval = int(
                user_input.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
            )
            sa_type = coalesce_sa_type(
                entry.data.get(CONF_DEVICE_TYPE),
                entry.data.get(CONF_CLOUD_DEVICE_TYPE),
                default=TYPE_AC,
            )
            if sa_type is None:
                sa_type = TYPE_AC
            mt = resolve_model_type(mt_raw, sa_type, None)
            new_data = dict(entry.data)
            if name:
                new_data[CONF_NAME] = name
            new_data[CONF_INDOOR_MODEL] = indoor
            new_data[CONF_MODEL_TYPE] = mt
            # Preserve existing options; only overwrite keys this form manages.
            new_options = dict(entry.options)
            new_options[CONF_UPDATE_INTERVAL] = interval
            new_options[CONF_ENERGY_ENABLED] = bool(
                user_input.get(CONF_ENERGY_ENABLED, True)
            )
            new_options[CONF_ENERGY_INCLUDE_HOUSE] = bool(
                user_input.get(CONF_ENERGY_INCLUDE_HOUSE, True)
            )
            domain = self.hass.data.get(DOMAIN) or {}
            slot = domain.get(entry.entry_id) or {}

            # Allow unlocking cloud-only entries by entering a reachable LAN IP.
            host_in = (user_input.get(CONF_HOST) or "").strip()
            host = host_in or (entry.data.get(CONF_HOST) or "").strip()
            probe_failed = False
            if host_in and host_in not in ("", "0.0.0.0"):
                session = async_get_clientsession(self.hass)
                probed = await async_probe_host(session, host_in)
                if probed is None:
                    errors["base"] = "cannot_connect"
                    probe_failed = True
                else:
                    host = host_in
                    new_data[CONF_HOST] = host
                    new_data["cloud_only"] = False
                    if probed.mac:
                        new_data["mac"] = probed.mac.upper()
                    if probed.sa_type and new_data.get(CONF_DEVICE_TYPE) in (None, ""):
                        new_data[CONF_DEVICE_TYPE] = probed.sa_type
            elif host_in in ("", "0.0.0.0") and CONF_HOST in user_input:
                # Explicit clear → keep/resume cloud-only when cloud creds exist.
                host = "0.0.0.0"
                new_data[CONF_HOST] = host
                if entry.data.get(CONF_CLOUD_GWID) and entry.data.get(CONF_CLOUD_AUTH):
                    new_data["cloud_only"] = True

            if not probe_failed:
                cloud_only = bool(new_data.get("cloud_only")) or host in (
                    "",
                    "0.0.0.0",
                )
                if cloud_only:
                    new_options[CONF_CONTROL_MODE] = CONTROL_MODE_CLOUD
                else:
                    mode = str(
                        user_input.get(CONF_CONTROL_MODE) or DEFAULT_CONTROL_MODE
                    )
                    if mode not in CONTROL_MODE_OPTIONS:
                        mode = DEFAULT_CONTROL_MODE
                    new_options[CONF_CONTROL_MODE] = mode
                for k in (
                    "mold_dry_simulate",
                    "mold_dry_minutes",
                    "mold_dry_air",
                    "mold_dry_fan",
                ):
                    new_options.pop(k, None)
                tracker = slot.get(DATA_ENERGY)
                if tracker is not None:
                    if user_input.get(CONF_ENERGY_RESET_PERIOD):
                        tracker.reset_period()
                    if user_input.get(CONF_ENERGY_RESET_TOTAL):
                        tracker.reset_total()
                    from .energy import async_save_tracker

                    await async_save_tracker(self.hass, entry.entry_id, tracker)

            if not probe_failed and not has_hub:
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

            if not probe_failed:
                from .entry_helpers import async_update_entry_options

                async_update_entry_options(
                    self.hass,
                    entry,
                    options=new_options,
                    reload=True,
                    data=new_data,
                    title=name or entry.title,
                )
                return self.async_create_entry(title="", data=new_options)

        return self.async_show_form(
            step_id="init",
            data_schema=self._device_options_schema(
                entry, has_hub=has_hub, energy=energy, lan=lan
            ),
            errors=errors,
        )


# Back-compat alias
OptionsFlowHandler = DeviceOptionsFlowHandler
