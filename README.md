# Panasonic TaiSEIA Local

Home Assistant custom integration for **Panasonic TaiSEIA** appliances — **LAN and/or Taiwan EMS cloud**, with a per-device control path you can choose.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Release](https://img.shields.io/github/v/release/n71154plus/panasonic_taiseia_local?label=v1.7.7)](https://github.com/n71154plus/panasonic_taiseia_local/releases/tag/v1.7.7)
[![Validate](https://github.com/n71154plus/panasonic_taiseia_local/actions/workflows/validate.yml/badge.svg)](https://github.com/n71154plus/panasonic_taiseia_local/actions/workflows/validate.yml)

> **Traditional Chinese:** [README.zh-Hant.md](README.zh-Hant.md)

## What's new in v1.7.7

- **Restart while unpowered (#6):** if a smart plug has cut the module, setup does one 3-second TCP 57223 check and does not send SOAP to that address or walk dozens of services. The entry finishes loading, entities stay unavailable, and startup is no longer held until the 300-second cancel that left the entry in `setup_error`. When the socket accepts again, the next poll reloads and runs a full probe. A module that is already on still probes as before. Hybrid and cloud keep using EMS while LAN is down. If ALL_STATES is rejected but the port is open, per-service reads still run.

Full notes: [Release v1.7.7](https://github.com/n71154plus/panasonic_taiseia_local/releases/tag/v1.7.7).

## Changelog

### v1.7.7

- See **What's new in v1.7.7** above.

### v1.7.6

- **Timer ceilings (#7 / #12):** service-list bytes form one big-endian maximum. An AC off-timer of `0x05 0xA0` is 1440 minutes, not a 5–160 range.
- **AC energy (#13):** `0x27` is outdoor-unit watts copied onto every indoor head. Integration now bills those watts only while that indoor unit is on, matching the official app `UserGetInfo` Power screen (unused study/kitchen heads stay at 0 kWh).
- **Dehumidifier modes (#6 / #14):** service `0x01` bytes are a 16-bit support mask, not a numeric range, so the picker no longer lists 「模式 30」–「模式 89」. On NXW/LXW, local code `3` is 送風 and `9` is 節能; catalog codes without a set bit (智慧節能 `1`, CommandList 送風 `7`) stay hidden. Until the service list is probed, the full CommandList is not shown, so a restart no longer briefly offers modes the module rejects.
- **Remote beep:** dehumidifier `0x18` is labeled 「遠端控制提示音」 (0 = sound, 1 = mute) and only covers remote/LAN writes; panel keys still beep.
- **AC power entities (#16):** operating power is a watt sensor; current/energy registers are no longer misclassified as switches when the span is 0.
- **Dehumidifier air quality (#15):** PM2.5, PM1.0, PM Level, and odor are probed even when omitted from the advertised 0x07 service list.
- **Cloud monthly energy (#17):** appliances without LAN power telemetry read the official app Power report (`UserGetInfo`) for the current-month kWh total.

### v1.7.5

- **Cloud appliance powered off:** EMS `503:DeviceJPInfo` (the module drops offline when the panel is off, or the appliance is unplugged) no longer fails setup. The entry loads, entities stay unavailable, and the next poll recovers them.
- **PIOT-V2 LAN probe:** modules that answer `FFFFFFFFFFFF` to the REGISTER read still expose type, model, services, and states. A reachable TCP 57223 device is no longer imported as cloud-only because of that one rejection.
- **Air conditioner turn on:** `climate.turn_on` resumes the last mode kept in register `0x01`, instead of Home Assistant's heat-first default. With no usable history it falls back to cool.
- **Dehumidifier LAN unlock (F-YV32LX / LXW):** setup retries MAC rediscovery, EMS `UserGetGWIP`, and a LAN probe for cloud-only entries. Device options accept a host IP; a reachable address clears the cloud-only lock and restores hybrid or local control. Adding the same MAC again upgrades the old cloud-only entry.
- **Dehumidifier modes (F-YV28NX / NXW and LXW):** CommandList `0x01` adds 智慧節能, 防霉抑菌, and 送風 when the module capability bitmask includes them. Fan `0x0E` labels are 靜音除濕 and 快速除濕. 烘鞋衣櫃 stays panel-only, the same limit as the official app.
- **Event loop:** the CommandList is read off the loop before setup, the config flow, and cloud sync. Optional nickname files use `hass.config.path()` and are loaded in an executor, so a missing file no longer calls `open()` on the loop.

### v1.7.4

- Cloud control re-authenticates when EMS rejects an expired CPToken (plain-text HTTP 417), then stores the new token

### v1.7.3

- Platform entities only follow probed SA type (not catalog profile)
- Temporary LAN outage no longer locks devices into cloud-only
- Cloud auth retry on expiry; ModelType / DeviceType guards tightened
- SP/RPH washer ModelTypes alias to MDH; cloud poll prioritizes core services
- README appliance / ModelType tables updated; hub account title masked
- Upgrade heals: sticky cloud-only on LAN hosts; prefer EMS type over poisoned local type
- Probe no longer defaults unknown SA type to AC; import ModelType guarded for LAN+cloud match

### v1.7.2

- Fix washing machines (and other types) being misidentified as dehumidifiers
- Add CommandList support for dryer, ERV, air cleaner, smart switch, weight plate, etc.

### v1.7.1

- Fewer unnecessary reloads; safer auth handling in diagnostics
- Faster EMS writes and lighter LAN polling / discovery
- Write rollback and entity naming cleanup

### v1.7.0

- Hybrid / local / cloud control per device (cloud writes enable official mold prevention on AC off)
- Cloud-only import for non-LAN devices

---

## How this differs from other Panasonic integrations

Most existing Panasonic Home Assistant integrations talk **only** to a cloud service. This one can use **LAN TaiSEIA** and/or **Taiwan EMS**, and you pick the mix per device.

| | This integration | Typical cloud-only Panasonic integrations |
| --- | --- | --- |
| **Control path** | **Hybrid / LAN / cloud** (per device) | Vendor cloud API only |
| **Internet required?** | Depends on mode — **local** can work offline; **hybrid/cloud** need EMS for cloud writes | Usually **yes** |
| **LAN protocol** | TaiSEIA / UPnP `SetSaanet` (TCP **57223**) | — |
| **Cloud** | Taiwan EMS (same family as official TW App) | Comfort Cloud / Smart App / MirAIe / … |
| **Best fit** | TaiSEIA modules on LAN, with optional cloud for App-parity (e.g. mold prevention on OFF) | Cloud-only appliances |

### Coexistence (not either/or)

You can keep the official app and other HA cloud integrations. Prefer **not** hammering the same EMS account from two HA integrations at once (shared rate limits).

## Will it work for my device? (start here)

### 30-second check

| Step | Pass if |
| --- | --- |
| ① EMS / official app | Device is listed |
| ② GWID | **12 hex** (LAN module) **or** opaque GWID (cloud-only candidate) |
| ③ LAN IP | Real IP + **TCP 57223** → local/hybrid; `0.0.0.0` / closed port → **cloud-only** import |

### By appliance class

| Class | DeviceType | Supported? | Notes |
| --- | --- | --- | --- |
| **Air conditioner** | `1` | **Yes** | Prefer **hybrid** so cloud OFF can trigger official 乾燥防霉 |
| **Refrigerator** | `2` | **Yes** (typical cloud-only) | `climate` N/A → CommandList entities; import as **(雲端)** when no `57223` |
| **Washer** | `3` | **Yes** | No dedicated washer platform → switches/selects/sensors from CommandList |
| **Dehumidifier** | `4` | **Yes** | Same as AC when LAN is open |
| **Dryer** | `6` | **Yes** | CommandList entities (`CN-HP` / `HP` from App catalog) |
| **Air cleaner** | `8` | **Yes** | LHW / LHW-40 / MH + open `57223`, or cloud |
| **ERV** | `14` | **Yes** | CommandList entities (`FYZY`) |
| **Smart / dimmer switch** | `17` | **Yes** | `WTY` / `WTYF` |
| **Weight plate** | `23` | **Yes** | `PZE1` |
| **Living-space controller** | `24` | **Limited** | `CSC` (very small CommandList) |

Cloud polling sends up to **24** command types per GetInfo call (core entity services first). Types without a dedicated HA platform still work via generic CommandList entities.

### ModelTypes (App CommandList)

| Class | HA platform | ModelTypes (bold = default when unsure) |
| --- | --- | --- |
| AC | `climate` + … | GX, J, J-DUCT, LJ, LJV, LX, PU, PX, **PXGD**, QX, RX-N, SX-DUCT, UJ, UX, VX |
| Refrigerator | entities | **F657** |
| Washer | entities | DDH, DW, HDH, KBS, LX128B, **MDH**; **SP** / **RPH** alias → MDH (no separate App JSON) |
| Dehumidifier | `humidifier` + … | CXW, EHW, GHW, JHV2, **JHW**, LXW, MHW, NHW, NNW, NNW-L, NXW |
| Dryer | entities | **CN-HP**, HP |
| Air cleaner | entities | **LHW**, LHW-40, MH |
| ERV | entities | **FYZY** |
| Switch / dimmer | entities | **WTY**, WTYF |
| Weight plate | entities | **PZE1** |
| Living-space controller | entities | **CSC** |

Override ModelType in device options.

## Features

- **climate** / **humidifier** for AC / dehumidifier; other classes use CommandList sensors / switches / selects / numbers / buttons
- Control modes: **hybrid** / **local** / **cloud**
- SSDP + LAN `57223` discovery; EMS import (LAN + cloud-only)
- Optional energy sensors (period / total / house)

## Requirements

- Home Assistant **2024.1.0+**
- For LAN modes: TaiSEIA controller on the same network, TCP **57223**
- For hybrid/cloud: Panasonic Taiwan EMS account (same as official TW App)

## Install (HACS)

1. HACS → **Integrations** → **Custom repositories**
2. Add `https://github.com/n71154plus/panasonic_taiseia_local` as **Integration**
3. Install **Panasonic TaiSEIA Local**, restart HA
4. **Settings → Devices & services → Add integration**

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=n71154plus&repository=panasonic_taiseia_local&category=integration)

## Manual install

Copy `custom_components/panasonic_taiseia_local` into your HA `custom_components/`, restart, add the integration.

## Setup

1. **EMS account import** (recommended): hub login, then multi-select devices (LAN and/or cloud-only)
2. **Discovery** / **manual IP** for LAN modules
3. Per device: name, **LAN host IP**, ModelType, poll interval, **control path**, energy options
4. If a unit was imported cloud-only but TCP 57223 is open: set the LAN IP in device options (or reload so setup retries GWIP/MAC discovery) to unlock local/hybrid

## Dynamic IP (DHCP)

Entries keep IP but identity is **MAC** (or `gwid:…` for cloud-only). On LAN failure the integration can rediscover by MAC (see v1.6.1+). Prefer DHCP reservation.

## Lovelace: Universal Device Card (recommended)

AC and dehumidifier devices expose many entities on one HA device (setpoint, swing, eco, power, switches, …). The stock thermostat card is awkward for that. Pair this integration with [Universal Device Card](https://github.com/n71154plus/universal-device-card): everyday controls stay on the main card; tap the top-right button for a **same-device popup** with the rest.

### Install the card

**HACS (recommended)**

1. HACS → **Frontend** → **Custom repositories**
2. Add `https://github.com/n71154plus/universal-device-card` as **Dashboard**
3. Install, reload the frontend (resource is usually `/hacsfiles/universal-device-card/universal-device-card.js`)

**Manual**

1. Download `dist/` from the latest [Release](https://github.com/n71154plus/universal-device-card/releases) (`universal-device-card.js` + `translations/`)
2. Place under `config/www/universal-device-card/`
3. Add a Lovelace resource (JavaScript Module):

```text
/local/universal-device-card/universal-device-card.js
```

### Example

Replace `climate.livingroom` with your entity ID:

```yaml
type: custom:universal-device-card
entity: climate.livingroom
layout: standard          # standard | mini | bar
language: en              # auto | en | zh-TW | zh-CN | ja
disable_popup: false      # false = top-right opens same-device popup
```

Compact row:

```yaml
type: custom:universal-device-card
entity: climate.bedroom
layout: mini
language: en
```

Optional popup filters (e.g. sensors + controls only):

```yaml
type: custom:universal-device-card
entity: climate.livingroom
language: en
include_domains: sensor,switch,select,number
include_sensor_classes: temperature,humidity,power
```

See the card README for full options. This integration’s climate / humidifier entities and their sibling switches, selects, numbers, and sensors work out of the box.

## Diagnostics

Download diagnostics from the config entry, or use developer services `probe_device` / `read_service` / `write_service` / `scan_lan`.

```yaml
logger:
  default: info
  logs:
    custom_components.panasonic_taiseia_local: debug
```

## License

MIT — see [LICENSE](LICENSE).
