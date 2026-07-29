# Panasonic TaiSEIA Local

Home Assistant custom integration for **Panasonic TaiSEIA** appliances — **LAN and/or Taiwan EMS cloud**, with a per-device control path you can choose.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/n71154plus/panasonic_taiseia_local/actions/workflows/validate.yml/badge.svg)](https://github.com/n71154plus/panasonic_taiseia_local/actions/workflows/validate.yml)

> **Traditional Chinese:** [README.zh-Hant.md](README.zh-Hant.md)

## Changelog

### v1.7.4

- Cloud-only dehumidifiers (e.g. LXW missed at import) can recover LAN via setup GWIP/MAC rediscovery, or unlock by entering a host IP in device options
- Expand NXW/LXW dehumidifier CommandList modes (智慧節能 / 防霉抑菌 / 送風) and fan labels (靜音除濕 / 快速除濕)
- Mode list follows device capability bits, not only the sparse App enum
- Note: shoe-closet mode is panel-only; official App/IoT cannot select it (per manual)

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
