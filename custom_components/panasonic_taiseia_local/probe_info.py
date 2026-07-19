"""Format TaiSEIA probe metadata for device / diagnostic display."""

from __future__ import annotations

from typing import Any

from .const import (
    CLIMATE_AVAILABLE_FAN_MODE,
    CLIMATE_AVAILABLE_INDICATOR,
    CLIMATE_AVAILABLE_MOTION,
    CLIMATE_AVAILABLE_SWING_LR,
    CLIMATE_AVAILABLE_SWING_MODE,
    DEHUMIDIFIER_AVAILABLE_FAN,
    DEHUMIDIFIER_AVAILABLE_FAN_DIR,
    DEHUMIDIFIER_AVAILABLE_MODE,
    DEVICE_TYPE_NAMES,
    LABEL_BUZZER,
    LABEL_CLIMATE_CLEAN,
    LABEL_CLIMATE_INDICATOR,
    LABEL_CLIMATE_MOLD_PREVENTION,
    LABEL_CLIMATE_MOTION,
    LABEL_CLIMATE_OFF_TIMER,
    LABEL_CLIMATE_ON_TIMER,
    LABEL_CLIMATE_SLEEP,
    LABEL_CLIMATE_SWING_LR,
    LABEL_DH_FAN,
    LABEL_DH_FAN_DIR,
    LABEL_DH_OFF_TIMER,
    LABEL_DH_ON_TIMER,
    LABEL_ECONAVI,
    LABEL_FILTER_NOTIFY,
    LABEL_HUMIDITY,
    LABEL_NANOE,
    LABEL_NANOEX,
    LABEL_OPERATING_POWER,
    LABEL_OUTDOOR_TEMPERATURE,
    LABEL_PM10,
    LABEL_PM25,
    LABEL_RF_DEFROST,
    LABEL_RF_ECO,
    LABEL_RF_FREEZER_SET,
    LABEL_RF_FREEZER_TEMP,
    LABEL_RF_FRIDGE_SET,
    LABEL_RF_FRIDGE_TEMP,
    LABEL_RF_PARTIAL_SET,
    LABEL_RF_PARTIAL_TEMP,
    LABEL_RF_QUICK_ICE,
    LABEL_RF_RAPID,
    LABEL_RF_SHOPPING,
    LABEL_RF_STOP_ICE,
    LABEL_RF_VACATION,
    LABEL_RF_WINTER,
    LABEL_TANK,
    LABEL_TURBO,
    SVC_BUZZER,
    SVC_DH_BUZZER,
    SVC_DH_FAN,
    SVC_DH_FAN_DIR,
    SVC_DH_HUMIDITY_IN,
    SVC_DH_HUMIDITY_SET,
    SVC_DH_NANOE,
    SVC_DH_OFF_TIMER,
    SVC_DH_ON_TIMER,
    SVC_DH_PM10,
    SVC_DH_PM25,
    SVC_DH_TANK,
    SVC_ECONAVI,
    SVC_FAN,
    SVC_FILTER_NOTIFY,
    SVC_INDICATOR,
    SVC_MODE,
    SVC_MOLD,
    SVC_MOTION,
    SVC_NANOE,
    SVC_OPERATING_POWER,
    SVC_PM25,
    SVC_PM25_FLAG,
    SVC_POWER,
    SVC_RF_DEFROST,
    SVC_RF_ECO,
    SVC_RF_FREEZER_SET,
    SVC_RF_FREEZER_TEMP,
    SVC_RF_FRIDGE_SET,
    SVC_RF_FRIDGE_TEMP,
    SVC_RF_NANOE,
    SVC_RF_PARTIAL_SET,
    SVC_RF_PARTIAL_TEMP,
    SVC_RF_QUICK_ICE,
    SVC_RF_RAPID_FREEZE,
    SVC_RF_SHOPPING,
    SVC_RF_STOP_ICE,
    SVC_RF_VACATION,
    SVC_RF_WINTER,
    SVC_SELF_CLEAN,
    SVC_SLEEP,
    SVC_SWING,
    SVC_SWING_LR,
    SVC_TEMP_IN,
    SVC_TEMP_OUT,
    SVC_TEMP_SET,
    SVC_TIMER_OFF,
    SVC_TIMER_ON,
    SVC_TURBO,
    TYPE_AC,
    TYPE_DEHUMIDIFIER,
    TYPE_REFRIGERATOR,
)
from .taiseia import DeviceInfo, ServiceInfo

SERVICE_LABELS: dict[int, str] = {
    SVC_POWER: "電源",
    SVC_MODE: "運轉模式",
    SVC_FAN: "風量",
    SVC_TEMP_SET: "設定溫度",
    SVC_TEMP_IN: "室內溫度",
    SVC_SLEEP: LABEL_CLIMATE_SLEEP,
    SVC_NANOE: LABEL_NANOE,
    SVC_TIMER_ON: LABEL_CLIMATE_ON_TIMER,
    SVC_TIMER_OFF: LABEL_CLIMATE_OFF_TIMER,
    SVC_SWING: "上下風向",
    SVC_SWING_LR: LABEL_CLIMATE_SWING_LR,
    SVC_FILTER_NOTIFY: LABEL_FILTER_NOTIFY,
    SVC_MOLD: LABEL_CLIMATE_MOLD_PREVENTION,
    SVC_SELF_CLEAN: LABEL_CLIMATE_CLEAN,
    SVC_MOTION: LABEL_CLIMATE_MOTION,
    SVC_TURBO: LABEL_TURBO,
    SVC_ECONAVI: LABEL_ECONAVI,
    SVC_BUZZER: LABEL_BUZZER,
    SVC_INDICATOR: LABEL_CLIMATE_INDICATOR,
    SVC_TEMP_OUT: LABEL_OUTDOOR_TEMPERATURE,
    SVC_OPERATING_POWER: LABEL_OPERATING_POWER,
    SVC_PM25: LABEL_PM25,
    SVC_PM25_FLAG: "PM2.5 旗標",
    SVC_DH_OFF_TIMER: LABEL_DH_OFF_TIMER,
    SVC_DH_HUMIDITY_SET: "設定溼度",
    SVC_DH_HUMIDITY_IN: LABEL_HUMIDITY,
    SVC_DH_FAN_DIR: LABEL_DH_FAN_DIR,
    SVC_DH_TANK: LABEL_TANK,
    SVC_DH_NANOE: LABEL_NANOEX,
    SVC_DH_FAN: LABEL_DH_FAN,
    SVC_DH_BUZZER: LABEL_BUZZER,
    SVC_DH_PM25: LABEL_PM25,
    SVC_DH_ON_TIMER: LABEL_DH_ON_TIMER,
    SVC_DH_PM10: LABEL_PM10,
    SVC_RF_FREEZER_SET: LABEL_RF_FREEZER_SET,
    SVC_RF_FRIDGE_SET: LABEL_RF_FRIDGE_SET,
    SVC_RF_FREEZER_TEMP: LABEL_RF_FREEZER_TEMP,
    SVC_RF_FRIDGE_TEMP: LABEL_RF_FRIDGE_TEMP,
    SVC_RF_ECO: LABEL_RF_ECO,
    SVC_RF_DEFROST: LABEL_RF_DEFROST,
    SVC_RF_STOP_ICE: LABEL_RF_STOP_ICE,
    SVC_RF_QUICK_ICE: LABEL_RF_QUICK_ICE,
    SVC_RF_RAPID_FREEZE: LABEL_RF_RAPID,
    SVC_RF_PARTIAL_SET: LABEL_RF_PARTIAL_SET,
    SVC_RF_PARTIAL_TEMP: LABEL_RF_PARTIAL_TEMP,
    SVC_RF_WINTER: LABEL_RF_WINTER,
    SVC_RF_SHOPPING: LABEL_RF_SHOPPING,
    SVC_RF_VACATION: LABEL_RF_VACATION,
    SVC_RF_NANOE: LABEL_NANOE,
}

_AC_MODE_BY_CODE = {
    0: "冷氣",
    1: "除濕",
    2: "送風",
    3: "自動",
    4: "暖氣",
}


def service_label(service_id: int) -> str:
    return SERVICE_LABELS.get(service_id, f"服務 0x{service_id:02X}")


def format_service_line(service_id: int, info: ServiceInfo) -> str:
    rw = "讀寫" if info.writable else "唯讀"
    name = service_label(service_id)
    return f"0x{service_id:02X} {name} [{rw}] {info.min_value}–{info.max_value}"


def services_as_list(services: dict[int, ServiceInfo]) -> list[str]:
    return [
        format_service_line(sid, info)
        for sid, info in sorted(services.items())
    ]


def services_as_text(services: dict[int, ServiceInfo]) -> str:
    return "\n".join(services_as_list(services)) if services else ""


def _parse_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _signed_temp(raw: int) -> int:
    if raw > 200:
        return raw - 256
    return raw


def _on_off(raw: int) -> str:
    return "開" if raw else "關"


def decode_status_value(sa_type: int, service_id: int, raw: Any) -> str | None:
    """Human-readable decode for common TaiSEIA status values."""
    val = _parse_int(raw)
    if val is None:
        return None

    if service_id in (
        SVC_POWER,
        SVC_SLEEP,
        SVC_NANOE,
        SVC_ECONAVI,
        SVC_TURBO,
        SVC_MOLD,
        SVC_SELF_CLEAN,
        SVC_BUZZER,
        SVC_FILTER_NOTIFY,
        SVC_DH_NANOE,
        SVC_DH_BUZZER,
        SVC_DH_TANK,
        SVC_RF_ECO,
        SVC_RF_DEFROST,
        SVC_RF_STOP_ICE,
        SVC_RF_QUICK_ICE,
        SVC_RF_RAPID_FREEZE,
        SVC_RF_WINTER,
        SVC_RF_SHOPPING,
        SVC_RF_VACATION,
        SVC_RF_NANOE,
    ):
        return _on_off(val)

    if service_id in (SVC_TEMP_SET, SVC_TEMP_IN, SVC_TEMP_OUT):
        return f"{_signed_temp(val)}°C"

    if service_id == SVC_OPERATING_POWER:
        return f"{val} W"

    if service_id in (SVC_PM25, SVC_DH_PM25, SVC_DH_PM10):
        return f"{val} µg/m³"

    if sa_type == TYPE_AC:
        if service_id == SVC_MODE:
            return _AC_MODE_BY_CODE.get(val, str(val))
        if service_id == SVC_FAN:
            return CLIMATE_AVAILABLE_FAN_MODE.get(val, str(val))
        if service_id == SVC_SWING:
            return CLIMATE_AVAILABLE_SWING_MODE.get(val, str(val))
        if service_id == SVC_SWING_LR:
            return CLIMATE_AVAILABLE_SWING_LR.get(val, str(val))
        if service_id == SVC_INDICATOR:
            return CLIMATE_AVAILABLE_INDICATOR.get(val, str(val))
        if service_id == SVC_MOTION:
            return CLIMATE_AVAILABLE_MOTION.get(val, str(val))
        if service_id in (SVC_TIMER_ON, SVC_TIMER_OFF):
            return f"{val} 分"

    if sa_type == TYPE_DEHUMIDIFIER:
        if service_id == SVC_MODE:
            return DEHUMIDIFIER_AVAILABLE_MODE.get(val, str(val))
        if service_id == SVC_DH_FAN:
            return DEHUMIDIFIER_AVAILABLE_FAN.get(val, str(val))
        if service_id == SVC_DH_FAN_DIR:
            return DEHUMIDIFIER_AVAILABLE_FAN_DIR.get(val, str(val))
        if service_id in (SVC_DH_HUMIDITY_SET, SVC_DH_HUMIDITY_IN):
            return f"{val}%"
        if service_id in (SVC_DH_ON_TIMER, SVC_DH_OFF_TIMER):
            return f"{val} 時"

    if sa_type == TYPE_REFRIGERATOR and service_id in (
        SVC_RF_FREEZER_SET,
        SVC_RF_FRIDGE_SET,
        SVC_RF_PARTIAL_SET,
        SVC_RF_FREEZER_TEMP,
        SVC_RF_FRIDGE_TEMP,
        SVC_RF_PARTIAL_TEMP,
    ):
        return f"{_signed_temp(val)}°C"

    return str(val)


def status_as_list(
    status: dict[str, str], *, sa_type: int | None = None
) -> list[str]:
    lines: list[str] = []
    for key in sorted(
        status.keys(),
        key=lambda k: int(k, 16) if str(k).lower().startswith("0x") else str(k),
    ):
        try:
            sid = int(key, 16)
            name = service_label(sid)
            decoded = (
                decode_status_value(sa_type, sid, status[key])
                if sa_type is not None
                else None
            )
            if decoded and decoded != str(status[key]):
                lines.append(f"{key} {name} = {status[key]}（{decoded}）")
            else:
                lines.append(f"{key} {name} = {status[key]}")
        except ValueError:
            lines.append(f"{key} = {status[key]}")
    return lines


def status_as_text(status: dict[str, str], *, sa_type: int | None = None) -> str:
    return "\n".join(status_as_list(status, sa_type=sa_type)) if status else ""


def status_highlights(
    status: dict[str, str], sa_type: int
) -> dict[str, str]:
    """Compact decoded highlights for diagnostic attributes."""
    out: dict[str, str] = {}
    interesting = (
        SVC_POWER,
        SVC_MODE,
        SVC_FAN,
        SVC_TEMP_SET,
        SVC_TEMP_IN,
        SVC_TEMP_OUT,
        SVC_OPERATING_POWER,
        SVC_SWING,
        SVC_NANOE,
        SVC_ECONAVI,
        SVC_TURBO,
        SVC_DH_HUMIDITY_IN,
        SVC_DH_TANK,
        SVC_DH_FAN,
    )
    for sid in interesting:
        key = f"0x{sid:02X}"
        raw = status.get(key)
        if raw is None or raw == "":
            # case-insensitive fallback
            for k, v in status.items():
                if k.lower() == key.lower():
                    raw = v
                    break
        if raw is None or raw == "":
            continue
        decoded = decode_status_value(sa_type, sid, raw)
        if decoded is not None:
            out[service_label(sid)] = decoded
    return out


def type_summary(device: DeviceInfo) -> str:
    return f"{device.type_name} (0x{device.sa_type_id:02X})"


def cloud_type_name(device_type: int | None) -> str | None:
    if device_type is None:
        return None
    return DEVICE_TYPE_NAMES.get(int(device_type), str(device_type))
