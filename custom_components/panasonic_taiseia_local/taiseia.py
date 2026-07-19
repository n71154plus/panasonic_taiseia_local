"""Async TaiSEIA 101 client over Panasonic CZ-T006 UPnP SetSaanet."""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import aiohttp

from .const import (
    DEFAULT_MAX_CONCURRENT,
    DEFAULT_PORT,
    DEFAULT_REQUEST_RETRIES,
    DEFAULT_REQUEST_RETRY_DELAY,
    DEFAULT_REQUEST_TIMEOUT,
    ENTITY_SERVICES_BY_TYPE,
    REG_ALL_STATES,
    REG_MODEL,
    REG_REGISTER,
    REG_SERVICES,
    REG_TYPE_ID,
    TYPE_AC,
    TYPE_DEHUMIDIFIER,
    TYPE_REGISTER,
    TYPE_REFRIGERATOR,
)

_LOGGER = logging.getLogger(__package__)

SOAP_NS = "urn:schemas-upnp-org:service:SwitchPower:1"
CONTROL_PATH = "/SmartHome/Control"
DEVICE_XML_PATH = "/device.xml"

# Shared across all clients in this HA process (limits LAN thundering herd).
_LAN_SEM: asyncio.Semaphore | None = None
_LAN_SEM_LIMIT: int = DEFAULT_MAX_CONCURRENT


def configure_lan_concurrency(max_concurrent: int) -> None:
    """Recreate the shared semaphore when the configured limit changes."""
    global _LAN_SEM, _LAN_SEM_LIMIT
    limit = max(1, min(8, int(max_concurrent)))
    if _LAN_SEM is None or _LAN_SEM_LIMIT != limit:
        _LAN_SEM = asyncio.Semaphore(limit)
        _LAN_SEM_LIMIT = limit


def _lan_semaphore() -> asyncio.Semaphore:
    global _LAN_SEM
    if _LAN_SEM is None:
        configure_lan_concurrency(DEFAULT_MAX_CONCURRENT)
    assert _LAN_SEM is not None
    return _LAN_SEM


def _is_transient(err: BaseException) -> bool:
    return isinstance(
        err,
        (
            TimeoutError,
            asyncio.TimeoutError,
            aiohttp.ClientError,
            ConnectionError,
        ),
    )


class TaiSeiaError(Exception):
    """Base error for TaiSEIA client."""


class TaiSeiaCommandError(TaiSeiaError):
    """Device returned FFFFFFFFFFFF or invalid PDU."""


def xor_checksum(data: bytes) -> int:
    c = 0
    for b in data:
        c ^= b
    return c


def make_pdu(type_id: int, service: int, data: int = 0xFFFF, write: bool = False) -> bytes:
    sid = (0x80 | service) if write else (service & 0x7F)
    body = bytes([6, type_id & 0xFF, sid, (data >> 8) & 0xFF, data & 0xFF])
    return body + bytes([xor_checksum(body)])


def parse_pdu_value(resp: bytes) -> int:
    if len(resp) < 6:
        raise TaiSeiaCommandError(f"short response: {resp.hex()}")
    return (resp[3] << 8) | resp[4]


def status_key(service: int) -> str:
    return f"0x{service:02X}"


@dataclass
class ServiceInfo:
    service_id: int
    writable: bool
    min_value: int
    max_value: int


@dataclass
class DeviceInfo:
    host: str
    port: int = DEFAULT_PORT
    friendly_name: str = ""
    manufacturer: str = "Panasonic"
    model_name: str = ""
    model_number: str = ""
    model_description: str = ""
    sw_version: str = ""
    udn: str = ""
    mac: str = ""
    brand: str = ""
    sa_model: str = ""
    sa_type_id: int = TYPE_AC
    services: dict[int, ServiceInfo] = field(default_factory=dict)

    @property
    def unique_id(self) -> str:
        if self.mac:
            return self.mac.lower()
        if self.udn:
            return self.udn.lower()
        return f"{self.host}:{self.port}"

    @property
    def type_name(self) -> str:
        from .const import DEVICE_TYPE_NAMES

        return DEVICE_TYPE_NAMES.get(self.sa_type_id, f"0x{self.sa_type_id:02X}")


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def parse_device_xml(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    info: dict[str, str] = {}
    for elem in root.iter():
        tag = _strip_ns(elem.tag)
        if tag in (
            "friendlyName",
            "manufacturer",
            "modelName",
            "modelNumber",
            "modelDescription",
            "UDN",
            "presentationURL",
            "manufacturerURL",
        ):
            info[tag] = (elem.text or "").strip()
    udn = info.get("UDN", "")
    mac = ""
    # uuid:...-XXXXXXXXXXXX — last hyphen segment is MAC (12 hex)
    if "-" in udn:
        tail = udn.rsplit("-", 1)[-1]
        if re.fullmatch(r"[0-9A-Fa-f]{12}", tail):
            mac = tail.upper()
    info["mac"] = mac
    desc = info.get("modelDescription", "")
    sw = ""
    m = re.search(r"SW_VER\s*([0-9.]+)", desc)
    if m:
        sw = m.group(1)
    info["sw_version"] = sw
    # presentationURL is typically http://<lan-ip>:57223
    pres = info.get("presentationURL", "")
    m = re.search(r"https?://([^/:]+)", pres)
    if m:
        info["presentation_host"] = m.group(1)
    return info


def parse_services_pdu(resp: bytes) -> dict[int, ServiceInfo]:
    """Parse REG_SERVICES or service list from register dump."""
    services: dict[int, ServiceInfo] = {}
    if len(resp) < 4:
        return services
    # Response: [len][0x00][service_id][payload...][ck]
    # For services (0x07): payload starts at index 3
    # For register (0x00): skip header until after brand/model nulls
    body = resp[3:-1]
    if resp[2] & 0x7F == REG_REGISTER:
        # skip brand\0 model\0
        try:
            z1 = body.index(0)
            z2 = body.index(0, z1 + 1)
            body = body[z2 + 1 :]
        except ValueError:
            return services

    i = 0
    while i + 2 < len(body):
        raw = body[i]
        sid = raw & 0x7F
        writable = bool(raw & 0x80)
        b1, b2 = body[i + 1], body[i + 2]
        # Signed-ish ranges for sensors sometimes use high values; store raw
        services[sid] = ServiceInfo(sid, writable, b1, b2)
        i += 3
    return services


def parse_all_states(resp: bytes) -> dict[int, int]:
    """Parse REG_ALL_STATES: triples (sid, hi, lo)."""
    states: dict[int, int] = {}
    if len(resp) < 4:
        return states
    body = resp[3:-1]
    i = 0
    while i + 2 < len(body):
        sid, hi, lo = body[i], body[i + 1], body[i + 2]
        states[sid] = (hi << 8) | lo
        i += 3
    return states


def states_to_status(states: dict[int, int]) -> dict[str, str]:
    return {status_key(k): str(v) for k, v in states.items()}


class TaiSeiaClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_REQUEST_TIMEOUT,
        retries: int = DEFAULT_REQUEST_RETRIES,
        retry_delay: float = DEFAULT_REQUEST_RETRY_DELAY,
    ) -> None:
        self._session = session
        self.host = host
        self.port = port
        self.retries = max(1, int(retries))
        self.retry_delay = float(retry_delay)
        self._timeout = aiohttp.ClientTimeout(total=float(timeout))
        self.device: DeviceInfo = DeviceInfo(host=host, port=port)
        # Extra services to poll (from APK CommandList profile).
        self.poll_services: list[int] = []

    def apply_lan_settings(
        self,
        *,
        timeout: float | None = None,
        retries: int | None = None,
        retry_delay: float | None = None,
        max_concurrent: int | None = None,
    ) -> None:
        """Update per-client timeout/retry and optional global concurrency."""
        if timeout is not None:
            self._timeout = aiohttp.ClientTimeout(total=float(timeout))
        if retries is not None:
            self.retries = max(1, int(retries))
        if retry_delay is not None:
            self.retry_delay = float(retry_delay)
        if max_concurrent is not None:
            configure_lan_concurrency(max_concurrent)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    async def async_get_device_xml(self) -> dict:
        url = f"{self.base_url}{DEVICE_XML_PATH}"
        async with self._session.get(url, timeout=self._timeout) as resp:
            resp.raise_for_status()
            text = await resp.text()
        info = parse_device_xml(text)
        self.device.friendly_name = info.get("friendlyName", "")
        self.device.manufacturer = info.get("manufacturer", "Panasonic")
        self.device.model_name = info.get("modelName", "")
        self.device.model_number = info.get("modelNumber", "")
        self.device.model_description = info.get("modelDescription", "")
        self.device.sw_version = info.get("sw_version", "")
        self.device.udn = info.get("UDN", "")
        self.device.mac = info.get("mac", "")
        return info

    async def async_set_saanet(self, frame: bytes) -> bytes:
        hexv = frame.hex().upper()
        body = (
            '<?xml version="1.0"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            "<s:Body>"
            f'<u:SetSaanet xmlns:u="{SOAP_NS}">'
            f"<NewSaanetValue>{hexv}</NewSaanetValue>"
            "</u:SetSaanet></s:Body></s:Envelope>"
        )
        headers = {
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPACTION": f'"{SOAP_NS}#SetSaanet"',
        }
        url = f"{self.base_url}{CONTROL_PATH}"
        last_err: BaseException | None = None
        retries = max(1, int(self.retries))
        for attempt in range(1, retries + 1):
            try:
                async with _lan_semaphore():
                    async with self._session.post(
                        url,
                        data=body.encode(),
                        headers=headers,
                        timeout=self._timeout,
                    ) as resp:
                        text = await resp.text()
                m = re.search(r"<RetSaanetValue>([^<]*)</RetSaanetValue>", text)
                if not m:
                    raise TaiSeiaCommandError(
                        f"no RetSaanetValue in response: {text[:200]}"
                    )
                ret = m.group(1)
                if ret.upper() == "FFFFFFFFFFFF":
                    raise TaiSeiaCommandError(f"command rejected: {hexv}")
                raw = bytes.fromhex(ret)
                if not raw or raw[0] != len(raw) or xor_checksum(raw[:-1]) != raw[-1]:
                    raise TaiSeiaCommandError(f"invalid TaiSEIA response: {ret}")
                return raw
            except TaiSeiaCommandError:
                raise
            except Exception as err:  # noqa: BLE001 — classify transient below
                last_err = err
                if not _is_transient(err) or attempt >= retries:
                    raise
                _LOGGER.debug(
                    "TaiSEIA %s attempt %s/%s failed: %s; retrying",
                    self.host,
                    attempt,
                    retries,
                    err,
                )
                await asyncio.sleep(self.retry_delay * attempt)
        assert last_err is not None
        raise last_err

    async def async_read(self, type_id: int, service: int) -> bytes:
        return await self.async_set_saanet(make_pdu(type_id, service, write=False))

    async def async_write(self, type_id: int, service: int, value: int) -> bytes:
        return await self.async_set_saanet(
            make_pdu(type_id, service, value & 0xFFFF, write=True)
        )

    async def async_read_device(self, service: int) -> int:
        resp = await self.async_read(self.device.sa_type_id, service)
        return parse_pdu_value(resp)

    async def async_write_device(self, service: int, value: int) -> int:
        resp = await self.async_write(self.device.sa_type_id, service, value)
        return parse_pdu_value(resp)

    # Back-compat aliases
    async def async_read_ac(self, service: int) -> int:
        return await self.async_read_device(service)

    async def async_write_ac(self, service: int, value: int) -> int:
        return await self.async_write_device(service, value)

    async def async_probe(self) -> DeviceInfo:
        """Validate connectivity and load device metadata + SA type."""
        await self.async_get_device_xml()
        # Prefer dedicated type-id service
        try:
            type_resp = await self.async_read(TYPE_REGISTER, REG_TYPE_ID)
            self.device.sa_type_id = parse_pdu_value(type_resp) & 0xFF
        except TaiSeiaError:
            self.device.sa_type_id = TYPE_AC

        reg = await self.async_read(TYPE_REGISTER, REG_REGISTER)
        # brand/model from register
        body = reg[8:-1] if len(reg) > 8 else b""
        try:
            z1 = body.index(0)
            self.device.brand = body[:z1].decode("utf-8", "replace")
            rest = body[z1 + 1 :]
            z2 = rest.index(0)
            self.device.sa_model = rest[:z2].decode("utf-8", "replace")
        except ValueError:
            pass
        # type_id from register header bytes 6-8 if still unknown / zero
        if self.device.sa_type_id in (0, TYPE_AC) and len(reg) >= 8:
            maybe = (reg[6] << 8) | reg[7]
            if maybe in (TYPE_AC, TYPE_REFRIGERATOR, TYPE_DEHUMIDIFIER):
                self.device.sa_type_id = maybe
        if not self.device.sa_model:
            try:
                model_resp = await self.async_read(TYPE_REGISTER, REG_MODEL)
                self.device.sa_model = model_resp[3:-1].split(b"\x00")[0].decode(
                    "utf-8", "replace"
                )
            except TaiSeiaError:
                pass
        try:
            svc_resp = await self.async_read(TYPE_REGISTER, REG_SERVICES)
            self.device.services = parse_services_pdu(svc_resp)
        except TaiSeiaError:
            self.device.services = parse_services_pdu(reg)
        if not self.device.services:
            self.device.services = parse_services_pdu(reg)
        return self.device

    def has_service(self, service: int) -> bool:
        return service in self.device.services

    def service_range(self, service: int) -> tuple[int, int]:
        info = self.device.services.get(service)
        if not info:
            return 0, 0
        return info.min_value, info.max_value

    async def async_fetch_status(self) -> dict[str, str]:
        """Fetch ALL_STATES and normalize to status dict."""
        base = ENTITY_SERVICES_BY_TYPE.get(
            self.device.sa_type_id, ENTITY_SERVICES_BY_TYPE[TYPE_AC]
        )
        poll = list(dict.fromkeys([*base, *self.poll_services]))
        try:
            resp = await self.async_read(TYPE_REGISTER, REG_ALL_STATES)
            states = parse_all_states(resp)
        except Exception as err:  # noqa: BLE001
            if not isinstance(err, TaiSeiaError) and not _is_transient(err):
                raise
            _LOGGER.warning("ALL_STATES failed on %s: %s; falling back", self.host, err)
            states = {}
            for svc in poll:
                if self.device.services and svc not in self.device.services:
                    continue
                try:
                    states[svc] = await self.async_read_device(svc)
                except Exception:  # noqa: BLE001
                    continue
        for svc in poll:
            if svc not in states and (not self.device.services or svc in self.device.services):
                try:
                    states[svc] = await self.async_read_device(svc)
                except Exception:  # noqa: BLE001
                    pass
        return states_to_status(states)
