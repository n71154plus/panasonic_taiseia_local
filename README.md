# Panasonic TaiSEIA (Local)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/OWNER/panasonic_taiseia.svg)](https://github.com/OWNER/panasonic_taiseia/releases)
[![Validate](https://github.com/OWNER/panasonic_taiseia/actions/workflows/validate.yml/badge.svg)](https://github.com/OWNER/panasonic_taiseia/actions/workflows/validate.yml)

Home Assistant **custom integration** for **local** control of Taiwan Panasonic IoT appliances that speak **TaiSEIA 101** over the CZ-T006 Wi‑Fi module (UPnP `SetSaanet` on TCP **57223**).

Does **not** use the Panasonic cloud API. Works alongside (or instead of) cloud integrations such as `panasonic_smart_app`.

## Supported devices

| Type | TaiSEIA TYPE | Platforms |
|------|--------------|-----------|
| Air conditioner (冷氣) | `0x01` | `climate`, switches, selects, numbers, sensors |
| Refrigerator (冰箱) | `0x02` | selects, switches, sensors, binary sensors |
| Dehumidifier (除濕機) | `0x04` | `humidifier`, switches, selects, numbers, sensors |

> Only appliances whose Wi‑Fi module exposes LAN port **57223** / `SetSaanet` can be controlled locally. Some newer fridges are cloud‑only on the LAN (pingable but no open ports).

## Features

- Config flow with **auto discovery** (SSDP + subnet scan of port 57223) or manual IP
- Local polling via TaiSEIA `ALL_STATES` (register `0x08`)
- Capability filtering from the device service list
- Optional nickname hints from an existing `panasonic_smart_app` device registry / GWID map

## Installation

### HACS (recommended)

1. HACS → Integrations → ⋮ → **Custom repositories**
2. Repository URL: `https://github.com/OWNER/panasonic_taiseia`
3. Category: **Integration**
4. Download **Panasonic TaiSEIA (Local)**
5. Restart Home Assistant
6. Settings → Devices & services → Add integration → **Panasonic TaiSEIA (Local)**

### Manual

Copy `custom_components/panasonic_taiseia` into your HA `config/custom_components/` folder, restart, then add the integration.

## Protocol (summary)

```
HA  --HTTP POST-->  http://<IP>:57223/SmartHome/Control
    SOAP action: urn:schemas-upnp-org:service:SwitchPower:1#SetSaanet
    Body: NewSaanetValue = hex TaiSEIA PDU
```

PDU: `[LEN][TYPE][SERVICE][DATA_HI][DATA_LO][XOR]`

- Read: `service & 0x7F`, data `0xFFFF`
- Write: `service | 0x80`

## Options

- **Update interval** (seconds): default `30`

## Notes

- Indoor model names shown in the Panasonic app (e.g. `CS-RX90JA2`) may differ from the Wi‑Fi SA model in `device.xml` (e.g. `RX-20250A06`).
- Cloud‑only stats (monthly energy from the official app, CO₂, etc.) are not available over TaiSEIA; derive energy locally from the power sensor if needed.

## License

MIT
