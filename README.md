# Panasonic TaiSEIA Local

Home Assistant custom integration for **Panasonic TaiSEIA** appliances — **LAN and/or Taiwan EMS cloud**, with a per-device control path you can choose.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/n71154plus/panasonic_taiseia_local/actions/workflows/validate.yml/badge.svg)](https://github.com/n71154plus/panasonic_taiseia_local/actions/workflows/validate.yml)

> **Traditional Chinese:** [README.zh-Hant.md](README.zh-Hant.md)

## Changelog

### v1.7.0 — Hybrid cloud + local control

**Why:** Turning the AC **off over LAN `SetSaanet` alone does not run Panasonic’s official 乾燥防霉 (mold prevention)** the way the official App / EMS `DeviceSetCommand` path does. That mismatch was the reason for this release.

**What changed:**

- **Per-device control path** (device options): **hybrid** (default) / **local only** / **cloud only**
  - **Write (commands):** hybrid → **cloud first**, LAN fallback
  - **Read (status):** hybrid → **LAN first**, cloud assist on failure
- EMS APIs follow the **official IoT TW APK** contract (`DeviceSetCommand` / `DeviceGetInfo`, with `CPToken` + `auth` + `GWID`), plus a cleaner rate-limit gate (not a copy of other GitHub clients)
- **Cloud-only import:** non-LAN GWID devices (e.g. some fridges) and LAN-unreachable modules can be imported as **(雲端)** and controlled via EMS
- Device titles: **(本地)** vs **(雲端)** by path
- Official mold prevention after power-off works when OFF is sent on the **cloud** write path (hybrid/cloud modes). A separate LAN “simulate dry” path was **deferred**

Upgrade: reload the integration, then set **Control path** on each device. Prefer **hybrid** on ACs if you want App-like shutdown behavior including 乾燥防霉.

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
| **Dehumidifier** | `4` | **Yes** | Same as AC when LAN is open |
| **Air cleaner** | `8` | **Conditional** | LHW / LHW-40 + open `57223`, or cloud if available |
| **Refrigerator** | `2` | **Cloud-only** (typical) | Import as **(雲端)** when there is no `57223` |
| Washer / dryer / others | … | Limited | Cloud if in EMS list; LAN only if `57223` exists |

### AC / dehumidifier ModelTypes

Built-in App **CommandList** platforms:

| Class | Platform | ModelTypes (bold = default when unsure) |
| --- | --- | --- |
| AC | `climate` + … | GX, J, J-DUCT, LJ, LJV, LX, PU, PX, **PXGD**, QX, RX-N, SX-DUCT, UJ, UX, VX |
| Dehumidifier | `humidifier` + … | CXW, EHW, GHW, JHV2, **JHW**, LXW, MHW, NHW, NNW, NNW-L, NXW |

Override ModelType in device options.

## Features

- **climate** / **humidifier** plus sensors, binary sensors, switches, selects, numbers, buttons (CommandList)
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
3. Per device: name, ModelType, poll interval, **control path**, energy options

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
