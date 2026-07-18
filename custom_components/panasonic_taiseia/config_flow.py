"""Config flow for Panasonic TaiSEIA local."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_DEVICE_TYPE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DEVICE_TYPE_NAMES,
    DOMAIN,
)
from .discovery import DiscoveredDevice, async_discover_devices, async_probe_host
from .naming import async_suggest_name, format_local_title
from .taiseia import TaiSeiaError


class TaiSeiaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._errors: dict[str, str] = {}
        self._discovered: dict[str, DiscoveredDevice] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowHandler:
        return OptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            choice = user_input.get("setup_mode")
            if choice == "discover":
                return await self.async_step_discover()
            return await self.async_step_manual()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("setup_mode", default="discover"): vol.In(
                        {
                            "discover": "自動搜尋區網設備",
                            "manual": "手動輸入 IP",
                        }
                    ),
                }
            ),
        )

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
                return await self._async_create_from_discovered(
                    device, user_input.get(CONF_NAME, "")
                )

        session = async_get_clientsession(self.hass)
        try:
            found = await async_discover_devices(session, include_subnet_scan=True)
        except Exception:  # noqa: BLE001
            found = []

        self._discovered = {}
        choices: dict[str, str] = {}
        current_ids = {
            entry.unique_id for entry in self._async_current_entries() if entry.unique_id
        }
        for dev in found:
            uid = (dev.mac or f"{dev.host}:{dev.port}").lower()
            if uid in current_ids:
                continue
            self._discovered[uid] = dev
            suggested = async_suggest_name(self.hass, dev.mac)
            if suggested:
                type_name = DEVICE_TYPE_NAMES.get(dev.sa_type, "")
                label = f"{suggested.nickname} ({dev.host})"
                if type_name:
                    label = f"{label} [{type_name}]"
                if suggested.indoor_model:
                    label = f"{label} · {suggested.indoor_model}"
                choices[uid] = label
            else:
                choices[uid] = dev.label

        if not choices:
            self._errors["base"] = "no_devices"
            choices["manual"] = "改為手動輸入 IP…"
        else:
            choices["manual"] = "改為手動輸入 IP…"

        return self.async_show_form(
            step_id="discover",
            data_schema=vol.Schema(
                {
                    vol.Required("device"): vol.In(choices),
                    vol.Optional(CONF_NAME, default=""): str,
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
            name = (user_input.get(CONF_NAME) or "").strip()
            session = async_get_clientsession(self.hass)
            try:
                device = await async_probe_host(session, host)
                if device is None:
                    raise TaiSeiaError("probe failed")
            except Exception:  # noqa: BLE001
                self._errors["base"] = "cannot_connect"
            else:
                return await self._async_create_from_discovered(device, name)

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_NAME, default=""): str,
                    vol.Optional(
                        CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
                    ): int,
                }
            ),
            errors=self._errors,
        )

    async def async_step_ssdp(self, discovery_info) -> FlowResult:
        """Handle HA SSDP discovery."""
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
        await self.async_set_unique_id(device.mac.lower() if device.mac else device.host)
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
            return await self._async_create_from_discovered(device, "")
        return self.async_show_form(
            step_id="discover_confirm",
            description_placeholders={"name": device.label},
        )

    async def _async_create_from_discovered(
        self, device: DiscoveredDevice, name: str
    ) -> FlowResult:
        uid = (device.mac or f"{device.host}:{device.port}").lower()
        await self.async_set_unique_id(uid)
        self._abort_if_unique_id_configured(updates={CONF_HOST: device.host})
        type_name = DEVICE_TYPE_NAMES.get(device.sa_type, "")
        suggested = async_suggest_name(self.hass, device.mac)
        manual = (name or "").strip()
        if manual:
            title = manual
        elif suggested:
            title = format_local_title(suggested.nickname)
        else:
            title = device.model or device.name or device.host
            if type_name and type_name not in title:
                title = f"{title} ({type_name})"
        return self.async_create_entry(
            title=title,
            data={
                CONF_HOST: device.host,
                CONF_NAME: title,
                CONF_DEVICE_TYPE: device.sa_type,
                CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
                "indoor_model": (suggested.indoor_model if suggested else None),
            },
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_UPDATE_INTERVAL,
                            self.config_entry.data.get(
                                CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                            ),
                        ),
                    ): int,
                }
            ),
        )
