"""The Panasonic TaiSEIA local integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .catalog import build_generic_profile, build_profile, merge_hidden_device_services, resolve_model_type
from .cloud_sync import async_ensure_hub_device, async_sync_cloud_to_devices
from .const import (
    CONF_CLOUD_AUTH,
    CONF_CLOUD_DEVICE_TYPE,
    CONF_CLOUD_GWID,
    CONF_CLOUD_MODEL,
    CONF_CLOUD_MODEL_ID,
    CONF_CLOUD_MODEL_TYPE,
    CONF_CLOUD_NICKNAME,
    CONF_CONTROL_MODE,
    CONF_DEVICE_TYPE,
    CONF_ENERGY_ENABLED,
    CONF_ENERGY_INCLUDE_HOUSE,
    CONF_ENTRY_TYPE,
    CONF_HUB_ENTRY_ID,
    CONF_INDOOR_MODEL,
    CONF_MODEL_TYPE,
    CONF_UPDATE_INTERVAL,
    CONTROL_MODE_CLOUD,
    DATA_CLIENT,
    DATA_CONTROL,
    DATA_COORDINATOR,
    DATA_ENERGY,
    DATA_PROFILE,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    ENTRY_TYPE_DEVICE,
    ENTRY_TYPE_HUB,
    PLATFORMS,
    STATUS_OPERATING_POWER,
    SVC_OPERATING_POWER,
    TYPE_AC,
)
from .control import (
    DeviceControl,
    default_cloud_command_types,
    entry_has_cloud_creds,
    resolve_control_mode,
)
from .discovery import async_find_host_by_mac
from .energy import (
    async_get_energy_settings,
    async_load_tracker,
    async_save_tracker,
    period_label,
)
from .lan_settings import async_get_lan_settings
from .naming import async_suggest_name, format_cloud_title, format_local_title, looks_like_module_model
from .taiseia import ServiceInfo, TaiSeiaClient, configure_lan_concurrency

_LOGGER = logging.getLogger(__package__)

HUB_PLATFORMS = ["sensor"]
# Avoid flooding the LAN with full /24 scans on every failed poll.
_HOST_REDISCOVER_COOLDOWN_S = 300.0


def _is_hub(entry: ConfigEntry) -> bool:
    return entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB


def _interval(entry: ConfigEntry) -> int:
    return (
        entry.options.get(CONF_UPDATE_INTERVAL)
        or entry.data.get(CONF_UPDATE_INTERVAL)
        or DEFAULT_UPDATE_INTERVAL
    )


def _setup_stagger_seconds(host: str) -> float:
    """Spread first refresh so five ACs don't probe simultaneously at HA boot."""
    return (sum(ord(c) for c in host) % 10) * 0.35


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    from .services import async_register_services

    async_register_services(hass)

    if _is_hub(entry):
        return await _async_setup_hub(hass, entry)

    return await _async_setup_device(hass, entry)


async def _async_setup_hub(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Hub holds cloud credentials + shared settings + house energy sensor."""
    lan = await async_get_lan_settings(hass)
    configure_lan_concurrency(lan.max_concurrent)
    await async_ensure_hub_device(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = {"hub": True}

    pending = hass.data[DOMAIN].pop("_pending_imports", None)
    if pending:
        for info in pending:
            data = dict(info)
            data[CONF_ENTRY_TYPE] = ENTRY_TYPE_DEVICE
            data[CONF_HUB_ENTRY_ID] = entry.entry_id
            hass.async_create_task(
                hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": "device_import"},
                    data=data,
                )
            )

    # Refresh cloud nicknames / ModelType onto linked devices
    hass.async_create_task(async_sync_cloud_to_devices(hass, entry))

    await hass.config_entries.async_forward_entry_setups(entry, HUB_PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


def _entry_mac(entry: ConfigEntry) -> str | None:
    mac = (entry.data.get("mac") or entry.unique_id or "").replace(":", "").replace(
        "-", ""
    )
    return mac.upper() if len(mac) == 12 else None


async def _async_rebinding_host(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: TaiSeiaClient,
    *,
    reason: str,
) -> str | None:
    """If DHCP moved the module, find it by MAC and persist the new IP."""
    mac = _entry_mac(entry)
    if not mac:
        return None
    session = async_get_clientsession(hass)
    found = await async_find_host_by_mac(session, mac)
    if not found or found.host == client.host:
        return None
    _LOGGER.info(
        "TaiSEIA %s moved %s → %s (%s); updating config entry",
        mac,
        client.host,
        found.host,
        reason,
    )
    client.host = found.host
    client.device.host = found.host
    if found.mac:
        client.device.mac = found.mac
    new_data = dict(entry.data)
    new_data[CONF_HOST] = found.host
    if found.mac:
        new_data["mac"] = found.mac.upper()
    hass.config_entries.async_update_entry(entry, data=new_data)
    return found.host


async def _async_setup_device(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data.get(CONF_HOST) or "0.0.0.0"
    session = async_get_clientsession(hass)
    lan = await async_get_lan_settings(hass)
    configure_lan_concurrency(lan.max_concurrent)
    client = TaiSeiaClient(
        session,
        host,
        timeout=lan.timeout,
        retries=lan.retries,
        retry_delay=lan.retry_delay,
    )

    intentionally_cloud = host in ("", "0.0.0.0") and (
        entry_has_cloud_creds(entry)
        or bool(entry.data.get(CONF_CLOUD_GWID))
        or bool(entry.data.get("cloud_only"))
        or entry.options.get(CONF_CONTROL_MODE) == CONTROL_MODE_CLOUD
    )

    lan_ok = False
    cloud_only = False

    if intentionally_cloud:
        cloud_only = True
        sa_type = int(
            entry.data.get(CONF_DEVICE_TYPE)
            or entry.data.get(CONF_CLOUD_DEVICE_TYPE)
            or TYPE_AC
        )
        client.device.sa_type_id = sa_type
        client.device.host = host
        mac = _entry_mac(entry)
        if mac:
            client.device.mac = mac
        gwid = (entry.data.get(CONF_CLOUD_GWID) or "").strip()
        if gwid:
            client.device.udn = f"gwid:{gwid.lower()}"
        _LOGGER.info(
            "TaiSEIA cloud-only setup for %s (GWID=%s)",
            entry.title or host,
            gwid or "?",
        )
    else:
        stagger = _setup_stagger_seconds(host)
        if stagger:
            await asyncio.sleep(stagger)

        try:
            await client.async_probe()
            lan_ok = True
        except Exception as err:
            rebound = await _async_rebinding_host(
                hass, entry, client, reason="setup unreachable"
            )
            if rebound:
                try:
                    await client.async_probe()
                    lan_ok = True
                    host = rebound
                except Exception as err2:
                    err = err2
            if not lan_ok:
                if entry_has_cloud_creds(entry) or entry.data.get(CONF_CLOUD_GWID):
                    cloud_only = True
                    _LOGGER.warning(
                        "TaiSEIA %s LAN unreachable (%s); starting cloud-only",
                        host,
                        err,
                    )
                    sa_type = int(
                        entry.data.get(CONF_DEVICE_TYPE)
                        or entry.data.get(CONF_CLOUD_DEVICE_TYPE)
                        or TYPE_AC
                    )
                    client.device.sa_type_id = sa_type
                    client.device.host = host
                    mac = _entry_mac(entry)
                    if mac:
                        client.device.mac = mac
                    gwid = (entry.data.get(CONF_CLOUD_GWID) or "").strip()
                    if gwid and not client.device.mac:
                        client.device.udn = f"gwid:{gwid.lower()}"
                else:
                    raise ConfigEntryNotReady(
                        f"Cannot reach TaiSEIA device at {host}: {err}"
                    ) from err

    # Cloud-only devices are locked to cloud control mode
    if cloud_only:
        opts = dict(entry.options)
        if opts.get(CONF_CONTROL_MODE) != CONTROL_MODE_CLOUD:
            opts[CONF_CONTROL_MODE] = CONTROL_MODE_CLOUD
            hass.config_entries.async_update_entry(entry, options=opts)

    new_data = dict(entry.data)
    changed = False
    if new_data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
        new_data[CONF_ENTRY_TYPE] = ENTRY_TYPE_DEVICE
        changed = True
    if client.device.mac and new_data.get("mac") != client.device.mac.upper():
        new_data["mac"] = client.device.mac.upper()
        changed = True
    if lan_ok and new_data.get(CONF_HOST) != client.host:
        new_data[CONF_HOST] = client.host
        host = client.host
        changed = True
    if new_data.get("device_type") != client.device.sa_type_id:
        new_data["device_type"] = client.device.sa_type_id
        changed = True

    suggested = async_suggest_name(hass, client.device.mac)
    new_title = entry.title
    if suggested:
        if suggested.indoor_model and not new_data.get(CONF_INDOOR_MODEL):
            new_data[CONF_INDOOR_MODEL] = suggested.indoor_model
            changed = True
        if suggested.model_type and not new_data.get(CONF_MODEL_TYPE):
            new_data[CONF_MODEL_TYPE] = suggested.model_type
            changed = True
        if looks_like_module_model(entry.data.get(CONF_NAME)) or looks_like_module_model(
            entry.title
        ):
            nice = (
                format_cloud_title(suggested.nickname)
                if cloud_only
                else format_local_title(suggested.nickname)
            )
            new_data[CONF_NAME] = nice
            new_title = nice
            changed = True

    # Fix wrong (本地) suffix on intentional cloud-only entries
    if cloud_only:
        cur_name = str(new_data.get(CONF_NAME) or new_title or "")
        nick = (
            new_data.get(CONF_CLOUD_NICKNAME)
            or new_data.get(CONF_NAME)
            or entry.title
            or ""
        )
        if "(本地)" in cur_name or looks_like_module_model(cur_name):
            # strip path tag for rebuild
            base = cur_name
            for suffix in (" (本地)", " (雲端)", "(本地)", "(雲端)"):
                if base.endswith(suffix):
                    base = base[: -len(suffix)].rstrip()
                    break
            source = new_data.get(CONF_CLOUD_NICKNAME) or base or nick
            nice = format_cloud_title(str(source))
            if new_data.get(CONF_NAME) != nice:
                new_data[CONF_NAME] = nice
                new_title = nice
                changed = True

    model_type = resolve_model_type(
        new_data.get(CONF_MODEL_TYPE) or entry.options.get(CONF_MODEL_TYPE),
        client.device.sa_type_id,
        suggested.model_type if suggested else None,
    )
    if model_type and new_data.get(CONF_MODEL_TYPE) != model_type:
        new_data[CONF_MODEL_TYPE] = model_type
        changed = True

    profile = build_profile(model_type) if model_type else None
    if profile is None:
        profile = build_generic_profile(
            client.device.sa_type_id, client.device.services
        )
        _LOGGER.info(
            "TaiSEIA %s using generic service profile type=0x%02X (%s services)",
            host,
            client.device.sa_type_id,
            len(profile.commands),
        )
    else:
        before = len(profile.commands)
        profile = merge_hidden_device_services(profile, client.device.services)
        hidden_n = len(profile.commands) - before
        _LOGGER.info(
            "TaiSEIA %s using CommandList ModelType=%s (%s cmds, +%s device-only)",
            host,
            model_type,
            before,
            hidden_n,
        )

    if cloud_only and not client.device.services:
        for sid in profile.service_ids:
            client.device.services[sid] = ServiceInfo(sid, True, 0, 65535)

    # Poll App CommandList services plus anything the module advertises (hidden).
    client.poll_services = list(
        dict.fromkeys(
            [
                *profile.service_ids,
                *client.device.services.keys(),
            ]
        )
    )

    if changed:
        hass.config_entries.async_update_entry(entry, data=new_data, title=new_title)

    energy_settings = await async_get_energy_settings(hass)
    energy_tracker = await async_load_tracker(hass, entry.entry_id, energy_settings)
    energy_enabled = entry.options.get(CONF_ENERGY_ENABLED, True)
    include_house = entry.options.get(CONF_ENERGY_INCLUDE_HOUSE, True)
    has_power = (not client.device.services) or (
        SVC_OPERATING_POWER in client.device.services
    )
    entry_id = entry.entry_id
    last_rediscover_mono = 0.0

    control = DeviceControl(
        hass,
        entry,
        client,
        cloud_only=cloud_only,
        lan_ok=lan_ok,
    )
    cloud_types = default_cloud_command_types(list(client.poll_services or []))

    async def async_update_data():
        nonlocal last_rediscover_mono, lan_ok
        live = hass.config_entries.async_get_entry(entry_id)
        current_host = client.host
        path = "unknown"
        try:
            status, path = await control.async_fetch_status(cloud_types)
            if path == "lan":
                lan_ok = True
                control.lan_ok = True
        except Exception as err:
            if control.mode != CONTROL_MODE_CLOUD and not cloud_only:
                now = time.monotonic()
                if now - last_rediscover_mono >= _HOST_REDISCOVER_COOLDOWN_S:
                    last_rediscover_mono = now
                    live_entry = live or entry
                    rebound = await _async_rebinding_host(
                        hass, live_entry, client, reason="poll unreachable"
                    )
                    if rebound:
                        try:
                            status, path = await control.async_fetch_status(cloud_types)
                            current_host = rebound
                            lan_ok = True
                            control.lan_ok = True
                        except Exception as err2:
                            raise UpdateFailed(
                                f"TaiSEIA update failed for {rebound}: "
                                f"{type(err2).__name__}: {err2}"
                            ) from err2
                    else:
                        # Last chance: cloud assist if hybrid with credentials
                        if entry_has_cloud_creds(live or entry) or (
                            live or entry
                        ).data.get(CONF_CLOUD_GWID):
                            try:
                                control.lan_ok = False
                                status, path = await control.async_fetch_status(
                                    cloud_types
                                )
                            except Exception as err3:
                                raise UpdateFailed(
                                    f"TaiSEIA update failed for {current_host}: "
                                    f"{type(err3).__name__}: {err3}"
                                ) from err3
                        else:
                            raise UpdateFailed(
                                f"TaiSEIA update failed for {current_host}: "
                                f"{type(err).__name__}: {err}"
                            ) from err
                else:
                    raise UpdateFailed(
                        f"TaiSEIA update failed for {current_host}: "
                        f"{type(err).__name__}: {err}"
                    ) from err
            else:
                raise UpdateFailed(
                    f"TaiSEIA cloud update failed: {type(err).__name__}: {err}"
                ) from err

        try:
            power_w = None
            settings = await async_get_energy_settings(hass)
            energy_tracker.apply_settings(settings)
            if has_power and energy_enabled:
                raw = status.get(STATUS_OPERATING_POWER)
                if raw is not None and raw != "":
                    try:
                        power_w = float(raw)
                    except (TypeError, ValueError):
                        power_w = None
                energy_tracker.update(power_w)
                await async_save_tracker(hass, entry_id, energy_tracker)
            live = hass.config_entries.async_get_entry(entry_id)
            live_data = live.data if live else new_data
            live_entry = live or entry
            return {
                "status": status,
                "device": client.device,
                "name": live_data.get(CONF_NAME)
                or client.device.sa_model
                or current_host,
                "indoor_model": live_data.get(CONF_INDOOR_MODEL),
                "model_type": live_data.get(CONF_MODEL_TYPE) or model_type,
                "cloud_nickname": live_data.get(CONF_CLOUD_NICKNAME),
                "cloud_model": live_data.get(CONF_CLOUD_MODEL),
                "cloud_model_id": live_data.get(CONF_CLOUD_MODEL_ID),
                "cloud_model_type": live_data.get(CONF_CLOUD_MODEL_TYPE),
                "cloud_gwid": live_data.get(CONF_CLOUD_GWID),
                "control_mode": resolve_control_mode(
                    live_entry, cloud_only=cloud_only
                ),
                "control_path": path,
                "cloud_only": cloud_only,
                "energy_total_kwh": energy_tracker.total_kwh,
                "energy_monthly_kwh": energy_tracker.period_kwh,
                "energy_period_kwh": energy_tracker.period_kwh,
                "energy_month_key": energy_tracker.period_key,
                "energy_period_key": energy_tracker.period_key,
                "energy_cycle": energy_tracker.settings.cycle,
                "energy_cycle_days": energy_tracker.settings.cycle_days,
                "energy_period_label": period_label(
                    energy_tracker.settings.cycle,
                    energy_tracker.settings.cycle_days,
                ),
                "energy_include_house": include_house,
                "has_power_energy": bool(has_power and energy_enabled),
                "poll_interval": _interval(live) if live else _interval(entry),
                "lan_timeout": lan.timeout,
                "lan_retries": lan.retries,
                "lan_max_concurrent": lan.max_concurrent,
            }
        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(
                f"TaiSEIA update failed for {current_host}: "
                f"{type(err).__name__}: {err}"
            ) from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"panasonic_taiseia_local_{host}",
        update_method=async_update_data,
        update_interval=timedelta(seconds=_interval(entry)),
    )

    def update_local_state(status_key: str, value) -> None:
        if not coordinator.data:
            return
        status = dict(coordinator.data.get("status") or {})
        status[status_key] = str(value)
        coordinator.data = {**coordinator.data, "status": status}

    coordinator.update_local_state = update_local_state  # type: ignore[attr-defined]

    base_interval = _interval(entry)
    skew = sum(ord(c) for c in str(host)) % 5
    # Cloud-only: poll less aggressively to respect EMS limits
    if cloud_only:
        base_interval = max(base_interval, 60)
    coordinator.update_interval = timedelta(seconds=base_interval + skew)

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CLIENT: client,
        DATA_COORDINATOR: coordinator,
        DATA_PROFILE: profile,
        DATA_ENERGY: energy_tracker,
        DATA_CONTROL: control,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if _is_hub(entry):
        unload_ok = await hass.config_entries.async_unload_platforms(
            entry, HUB_PLATFORMS
        )
        if unload_ok:
            hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        return unload_ok
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old single-device entries to v2 (entry_type=device)."""
    if entry.version >= 2:
        return True
    data = dict(entry.data)
    if CONF_ENTRY_TYPE not in data:
        data[CONF_ENTRY_TYPE] = (
            ENTRY_TYPE_HUB if CONF_HOST not in data else ENTRY_TYPE_DEVICE
        )
    hass.config_entries.async_update_entry(entry, data=data, version=2)
    _LOGGER.info("Migrated %s to config entry version 2", entry.entry_id)
    return True
