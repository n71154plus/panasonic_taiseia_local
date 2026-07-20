"""APK / EMS CommandList catalog (primary feature definition for entities)."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from typing import Any, Literal

from homeassistant.components.climate import HVACMode

from .const import TYPE_AC, TYPE_AIR_CLEANER, TYPE_DEHUMIDIFIER, TYPE_REFRIGERATOR

_LOGGER = logging.getLogger(__package__)

EntityKind = Literal["switch", "select", "number", "sensor", "binary_sensor", "owned"]

# Claimed by climate / humidifier platforms (not duplicated as generic entities).
_OWNED_BY_CLIMATE = {0x00, 0x01, 0x02, 0x03, 0x0F}
_OWNED_BY_HUMIDIFIER = {0x00, 0x01, 0x04}

# TaiSEIA-only sensors often missing from CommandList (still useful locally).
_EXTRA_AC_SENSORS = (
    (0x21, "室外溫度", "temperature"),
    (0x27, "即時功率", "power"),
    (0x37, "PM2.5", "pm25"),
)
_EXTRA_AC_BINARY = ((0x12, "濾網清洗通知"),)
_EXTRA_RF_SENSORS = (
    (0x03, "冷凍溫度", "temperature"),
    (0x05, "冷藏溫度", "temperature"),
    (0x58, "微凍結溫度", "temperature"),
)

_DEFAULT_MODEL_TYPE = {
    TYPE_AC: "PXGD",
    TYPE_DEHUMIDIFIER: "JHW",
    TYPE_REFRIGERATOR: "F657",
    TYPE_AIR_CLEANER: "LHW",
}

_HVAC_NAME_MAP = {
    "冷氣": HVACMode.COOL,
    "制冷": HVACMode.COOL,
    "除濕": HVACMode.DRY,
    "清淨": HVACMode.FAN_ONLY,
    "送風": HVACMode.FAN_ONLY,
    "自動": HVACMode.AUTO,
    "暖氣": HVACMode.HEAT,
    "制熱": HVACMode.HEAT,
}

_ICON_RULES = (
    ("nanoe", "mdi:atom"),
    ("econavi", "mdi:leaf"),
    ("急速", "mdi:clock-fast"),
    ("睡眠", "mdi:sleep"),
    ("舒眠", "mdi:sleep"),
    ("睡眠", "mdi:sleep"),
    ("防霉", "mdi:weather-windy"),
    ("自體淨", "mdi:broom"),
    ("提示音", "mdi:volume-high"),
    ("燈光", "mdi:lightbulb-on-outline"),
    ("動向", "mdi:motion-sensor"),
    ("風向", "mdi:arrow-up-down"),
    ("風量", "mdi:fan"),
    ("時間", "mdi:timer-outline"),
    ("定時", "mdi:timer-outline"),
    ("濕度", "mdi:water-percent"),
    ("pm", "mdi:dots-hexagon"),
    ("異味", "mdi:air-filter"),
    ("滿水", "mdi:cup-water"),
    ("錯誤", "mdi:alert"),
    ("ai", "mdi:brain"),
    ("製冰", "mdi:ice-cream"),
    ("除霜", "mdi:car-defrost-rear"),
    ("電源", "mdi:power"),
)


@dataclass(frozen=True)
class CommandDef:
    service: int
    name: str
    parameter_type: str
    parameters: list
    unit: str = ""

    @property
    def status_key(self) -> str:
        return f"0x{self.service:02X}"


@dataclass
class ClassifiedCommand:
    command: CommandDef
    kind: EntityKind
    inverted: bool = False
    option_map: dict[int, str] = field(default_factory=dict)
    range_min: int | None = None
    range_max: int | None = None
    icon: str = "mdi:tune"
    device_class_hint: str | None = None  # temperature | power | pm25 | humidity | problem


@dataclass
class DeviceProfile:
    model_type: str
    device_type: int
    device_name: str
    protocol: str
    commands: list[CommandDef]
    classified: list[ClassifiedCommand]

    @property
    def service_ids(self) -> list[int]:
        return [c.service for c in self.commands]


_CATALOG: dict[str, dict[str, Any]] | None = None


def _catalog_path() -> Path:
    return Path(__file__).parent / "commands" / "command_list.json"


def load_catalog() -> dict[str, dict[str, Any]]:
    """Load ModelType → metadata + command list (cached)."""
    global _CATALOG
    if _CATALOG is not None:
        return _CATALOG
    path = _catalog_path()
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("CommandList", raw)
    catalog: dict[str, dict[str, Any]] = {}
    for entry in entries:
        mt = entry.get("ModelType")
        if not mt:
            continue
        block = (entry.get("JSON") or [{}])[0]
        cmds: list[CommandDef] = []
        for item in block.get("list") or []:
            try:
                sid = int(str(item.get("CommandType", "0")), 16)
            except ValueError:
                continue
            cmds.append(
                CommandDef(
                    service=sid,
                    name=str(item.get("CommandName") or f"0x{sid:02X}"),
                    parameter_type=str(item.get("ParameterType") or ""),
                    parameters=list(item.get("Parameters") or []),
                    unit=str(item.get("ParameterUnit") or ""),
                )
            )
        catalog[mt] = {
            "ModelType": mt,
            "DeviceType": int(block.get("DeviceType") or 0),
            "DeviceName": str(block.get("DeviceName") or ""),
            "ProtocalType": str(block.get("ProtocalType") or ""),
            "commands": cmds,
        }
    _CATALOG = catalog
    _LOGGER.debug("Loaded CommandList: %s ModelTypes", len(catalog))
    return catalog


def list_model_types(device_type: int | None = None) -> list[str]:
    cat = load_catalog()
    if device_type is None:
        return sorted(cat)
    return sorted(mt for mt, info in cat.items() if info["DeviceType"] == device_type)


def default_model_type(sa_type_id: int) -> str | None:
    return _DEFAULT_MODEL_TYPE.get(sa_type_id)


def parse_enum_params(parameters: list) -> dict[int, str]:
    out: dict[int, str] = {}
    for row in parameters:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        label, value = row[0], row[1]
        try:
            out[int(value)] = str(label)
        except (TypeError, ValueError):
            continue
    return out


def parse_range_params(parameters: list) -> tuple[int | None, int | None]:
    lo = hi = None
    for row in parameters:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        key, value = str(row[0]), row[1]
        try:
            ivalue = int(value)
        except (TypeError, ValueError):
            continue
        if key.lower() == "min":
            lo = ivalue
        elif key.lower() == "max":
            hi = ivalue
    return lo, hi


def parse_range_a_params(parameters: list) -> dict[int, str]:
    """Auto + Min..Max → option map (APK rangeA)."""
    auto_label, auto_val = "自動", 0
    lo = hi = None
    for row in parameters:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        key, value = str(row[0]), row[1]
        try:
            ivalue = int(value)
        except (TypeError, ValueError):
            continue
        kl = key.lower()
        if kl == "auto":
            auto_label, auto_val = key if key != "Auto" else "自動", ivalue
        elif kl == "min":
            lo = ivalue
        elif kl == "max":
            hi = ivalue
    out = {auto_val: auto_label}
    if lo is not None and hi is not None and lo <= hi:
        for i in range(lo, hi + 1):
            out.setdefault(i, str(i))
    return out


def _icon_for(name: str) -> str:
    low = name.lower()
    for needle, icon in _ICON_RULES:
        if needle.lower() in low or needle in name:
            return icon
    return "mdi:tune"


def _is_toggle_enum(option_map: dict[int, str]) -> bool:
    if len(option_map) != 2:
        return False
    labels = set(option_map.values())
    joined = "".join(labels)
    if labels <= {"關閉", "開啟", "開", "關", "停止", "運轉", "OFF", "ON", "Off", "On"}:
        return True
    if {"關閉", "開啟"} <= labels or {"停止", "運轉"} <= labels:
        return True
    return "開" in joined and "關" in joined and len(option_map) == 2


def _toggle_inverted(option_map: dict[int, str]) -> bool:
    """True when 'on' label maps to 0 (e.g. 操作提示音 開啟=0)."""
    on_labels = {"開啟", "開", "運轉", "ON", "On"}
    for value, label in option_map.items():
        if label in on_labels or label.endswith("開"):
            return value == 0
    return False


def _is_binary_name(name: str) -> bool:
    return any(k in name for k in ("警告", "滿水", "通知", "錯誤"))


def _sensor_hint(name: str) -> str | None:
    if "溫" in name:
        return "temperature"
    if "濕" in name:
        return "humidity"
    if "功率" in name or "耗電" in name:
        return "power"
    if "PM" in name.upper() or "pm" in name.lower():
        return "pm25"
    return None


def classify_command(cmd: CommandDef, device_type: int) -> ClassifiedCommand:
    owned = set()
    if device_type == 1:
        owned = _OWNED_BY_CLIMATE
    elif device_type == 4:
        owned = _OWNED_BY_HUMIDIFIER

    if cmd.service in owned:
        return ClassifiedCommand(command=cmd, kind="owned", icon=_icon_for(cmd.name))

    pt = cmd.parameter_type
    icon = _icon_for(cmd.name)

    if pt == "enum":
        option_map = parse_enum_params(cmd.parameters)
        if _is_toggle_enum(option_map):
            return ClassifiedCommand(
                command=cmd,
                kind="switch",
                inverted=_toggle_inverted(option_map),
                option_map=option_map,
                icon=icon,
            )
        return ClassifiedCommand(
            command=cmd, kind="select", option_map=option_map, icon=icon
        )

    if pt == "rangeA":
        return ClassifiedCommand(
            command=cmd,
            kind="select",
            option_map=parse_range_a_params(cmd.parameters),
            icon=icon,
        )

    if pt == "range":
        lo, hi = parse_range_params(cmd.parameters)
        return ClassifiedCommand(
            command=cmd,
            kind="number",
            range_min=lo,
            range_max=hi,
            icon=icon,
        )

    # Empty ParameterType → read-only
    if _is_binary_name(cmd.name):
        return ClassifiedCommand(
            command=cmd,
            kind="binary_sensor",
            icon=icon,
            device_class_hint="problem",
        )
    return ClassifiedCommand(
        command=cmd,
        kind="sensor",
        icon=icon,
        device_class_hint=_sensor_hint(cmd.name),
    )


def build_profile(model_type: str) -> DeviceProfile | None:
    cat = load_catalog()
    info = cat.get(model_type)
    if not info:
        return None
    commands: list[CommandDef] = list(info["commands"])
    device_type = int(info["DeviceType"])
    classified = [classify_command(c, device_type) for c in commands]
    return DeviceProfile(
        model_type=model_type,
        device_type=device_type,
        device_name=info["DeviceName"],
        protocol=info["ProtocalType"],
        commands=commands,
        classified=classified,
    )


def build_generic_profile(
    sa_type_id: int,
    services: dict[int, Any] | None,
) -> DeviceProfile:
    """Build entities from TaiSEIA service descriptors when no CommandList exists."""
    from .const import DEVICE_TYPE_NAMES
    from .probe_info import service_label

    services = services or {}
    commands: list[CommandDef] = []
    classified: list[ClassifiedCommand] = []
    device_name = DEVICE_TYPE_NAMES.get(sa_type_id, f"0x{sa_type_id:02X}")

    for sid, info in sorted(services.items()):
        name = service_label(sid, sa_type_id)
        if name.startswith("服務 "):
            name = f"{name}（裝置回報）"
        writable = bool(getattr(info, "writable", False))
        try:
            lo = int(getattr(info, "min_value", 0))
            hi = int(getattr(info, "max_value", 0))
        except (TypeError, ValueError):
            lo, hi = 0, 0
        if hi < lo:
            lo, hi = hi, lo
        span = hi - lo

        if not writable:
            cmd = CommandDef(sid, name, "", [], "")
        elif span <= 1:
            cmd = CommandDef(
                sid,
                name,
                "enum",
                [["關", lo], ["開", hi if hi != lo else lo + 1]],
                "",
            )
        elif span <= 20:
            cmd = CommandDef(
                sid,
                name,
                "enum",
                [[str(i), i] for i in range(lo, hi + 1)],
                "",
            )
        else:
            cmd = CommandDef(
                sid,
                name,
                "range",
                [["Min", lo], ["Max", hi]],
                "",
            )
        commands.append(cmd)
        classified.append(classify_command(cmd, sa_type_id))

    return DeviceProfile(
        model_type="",
        device_type=sa_type_id,
        device_name=device_name,
        protocol="SAANET",
        commands=commands,
        classified=classified,
    )


def merge_hidden_device_services(
    profile: DeviceProfile,
    services: dict[int, Any] | None,
) -> DeviceProfile:
    """Add entities for services the module advertises but App CommandList omits.

    Panasonic sometimes exposes extra TaiSEIA services on the LAN that never
    appear in the official App CommandList. Keep App names for listed commands;
    surface the rest as generic entities so they are still visible/controllable.
    """
    services = services or {}
    present = {c.service for c in profile.commands}
    missing = {sid: info for sid, info in services.items() if sid not in present}
    if not missing:
        return profile

    hidden = build_generic_profile(profile.device_type, missing)
    # Mark names so users can tell App vs hidden LAN-only services.
    renamed_commands: list[CommandDef] = []
    for cmd in hidden.commands:
        label = cmd.name
        if "（裝置回報）" not in label:
            label = f"{label}（裝置回報）"
        renamed_commands.append(
            CommandDef(
                cmd.service,
                label,
                cmd.parameter_type,
                list(cmd.parameters),
                cmd.unit,
            )
        )
    hidden_classified = [
        classify_command(c, profile.device_type) for c in renamed_commands
    ]
    return DeviceProfile(
        model_type=profile.model_type,
        device_type=profile.device_type,
        device_name=profile.device_name,
        protocol=profile.protocol,
        commands=[*profile.commands, *renamed_commands],
        classified=[*profile.classified, *hidden_classified],
    )


def resolve_model_type(
    explicit: str | None,
    sa_type_id: int,
    suggested: str | None = None,
) -> str | None:
    """Pick ModelType: user/option → hint → default for SA type."""
    for candidate in (explicit, suggested, default_model_type(sa_type_id)):
        if not candidate:
            continue
        if candidate in load_catalog():
            return candidate
    return None


def get_command(profile: DeviceProfile, service: int) -> CommandDef | None:
    for cmd in profile.commands:
        if cmd.service == service:
            return cmd
    return None


def climate_hvac_mappings(profile: DeviceProfile | None) -> list[dict]:
    """Build HVACMode mappings from CommandList 0x01 when available."""
    if not profile:
        return []
    cmd = get_command(profile, 0x01)
    if not cmd or cmd.parameter_type != "enum":
        return []
    mappings = []
    for value, label in parse_enum_params(cmd.parameters).items():
        mode = _HVAC_NAME_MAP.get(label)
        if mode is None:
            continue
        mappings.append({"key": mode, "mappingCode": value, "label": label})
    return mappings


def climate_fan_map(profile: DeviceProfile | None) -> dict[int, str] | None:
    if not profile:
        return None
    cmd = get_command(profile, 0x02)
    if not cmd:
        return None
    if cmd.parameter_type == "rangeA":
        return parse_range_a_params(cmd.parameters)
    if cmd.parameter_type == "enum":
        return parse_enum_params(cmd.parameters)
    return None


def climate_swing_map(profile: DeviceProfile | None) -> dict[int, str] | None:
    if not profile:
        return None
    cmd = get_command(profile, 0x0F)
    if not cmd:
        return None
    if cmd.parameter_type == "rangeA":
        return parse_range_a_params(cmd.parameters)
    if cmd.parameter_type == "enum":
        return parse_enum_params(cmd.parameters)
    return None


def climate_temp_limits(profile: DeviceProfile | None) -> tuple[int | None, int | None]:
    if not profile:
        return None, None
    cmd = get_command(profile, 0x03)
    if not cmd or cmd.parameter_type != "range":
        return None, None
    return parse_range_params(cmd.parameters)


def dehumidifier_mode_map(profile: DeviceProfile | None) -> dict[int, str] | None:
    if not profile:
        return None
    cmd = get_command(profile, 0x01)
    if not cmd or cmd.parameter_type != "enum":
        return None
    return parse_enum_params(cmd.parameters)


def dehumidifier_humidity_map(profile: DeviceProfile | None) -> dict[int, int] | None:
    """Map index → humidity % from CommandList 0x04 enum if present."""
    if not profile:
        return None
    cmd = get_command(profile, 0x04)
    if not cmd or cmd.parameter_type != "enum":
        return None
    out: dict[int, int] = {}
    for value, label in parse_enum_params(cmd.parameters).items():
        digits = "".join(ch for ch in label if ch.isdigit())
        if digits:
            out[value] = int(digits)
    return out or None


def iter_kind(profile: DeviceProfile, kind: EntityKind):
    for item in profile.classified:
        if item.kind == kind:
            yield item


def service_allowed(client_services: dict, service: int) -> bool:
    """If device reported a service list, require membership; else allow."""
    if not client_services:
        return True
    return service in client_services


def extra_local_sensors(sa_type_id: int, profile: DeviceProfile | None) -> list[ClassifiedCommand]:
    """TaiSEIA sensors not always present in APK CommandList."""
    present = {c.service for c in (profile.commands if profile else [])}
    extras: list[ClassifiedCommand] = []
    if sa_type_id == TYPE_AC:
        for sid, name, hint in _EXTRA_AC_SENSORS:
            if sid in present:
                continue
            extras.append(
                ClassifiedCommand(
                    command=CommandDef(sid, name, "", [], ""),
                    kind="sensor",
                    icon=_icon_for(name),
                    device_class_hint=hint,
                )
            )
    elif sa_type_id == TYPE_REFRIGERATOR:
        for sid, name, hint in _EXTRA_RF_SENSORS:
            if sid in present:
                continue
            extras.append(
                ClassifiedCommand(
                    command=CommandDef(sid, name, "", [], ""),
                    kind="sensor",
                    icon=_icon_for(name),
                    device_class_hint=hint,
                )
            )
    return extras


def extra_local_binaries(sa_type_id: int, profile: DeviceProfile | None) -> list[ClassifiedCommand]:
    present = {c.service for c in (profile.commands if profile else [])}
    extras: list[ClassifiedCommand] = []
    if sa_type_id == TYPE_AC:
        for sid, name in _EXTRA_AC_BINARY:
            if sid in present:
                continue
            extras.append(
                ClassifiedCommand(
                    command=CommandDef(sid, name, "", [], ""),
                    kind="binary_sensor",
                    icon=_icon_for(name),
                    device_class_hint="problem",
                )
            )
    return extras
