# Panasonic TaiSEIA Local

Home Assistant custom integration for **local LAN control** of Panasonic appliances that use a **TaiSEIA** Wi‑Fi controller (CZ-T006 and similar).

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/n71154plus/panasonic_taiseia_local/actions/workflows/validate.yml/badge.svg)](https://github.com/n71154plus/panasonic_taiseia_local/actions/workflows/validate.yml)

> **Traditional Chinese:** [README.zh-Hant.md](README.zh-Hant.md)

## How this differs from other Panasonic integrations

Most existing Panasonic Home Assistant integrations talk to a **cloud service** (Comfort Cloud, Smart App, MirAIe, and similar). Commands leave your home network, depend on the vendor API being online, and stop working when the internet or cloud is down.

**Panasonic TaiSEIA Local is different:**

| | This integration | Typical cloud Panasonic integrations |
| --- | --- | --- |
| **Control path** | Direct **LAN** to a TaiSEIA Wi‑Fi controller | Vendor cloud API |
| **Internet required for control / status?** | **No** — HA and the device must be on the same local network | Usually **yes** |
| **Protocol** | Local TaiSEIA / UPnP `SetSaanet` (default port **57223**) | Cloud HTTP APIs |
| **Cloud account** | **Optional** — Taiwan EMS login only to import the device list for convenience | Required for day-to-day control |
| **Best fit** | Homes with TaiSEIA Wi‑Fi controllers reachable on LAN | Accounts that only expose cloud control |

Day-to-day on/off, modes, setpoints, and sensors are polled and commanded **on your LAN**. The optional EMS account is only a convenience to **import the device inventory** — it is **not** used to send control commands or to read device status.

### Coexistence (not either/or)

This integration is an **additional local path**. It does **not** require you to remove the official Panasonic app or other Panasonic Home Assistant integrations (Comfort Cloud, Smart App, MirAIe, and similar).

- Keep using the **official app** as usual
- Keep any **existing cloud Panasonic HA integrations** if you want
- This component talks to the TaiSEIA Wi‑Fi controller on your **LAN**; the app and cloud integrations keep their own cloud paths

You can use them together by situation (for example local control at home, official app when away). Installing this is not a replacement for those tools.

If your units are only reachable through cloud apps and no TaiSEIA Wi‑Fi controller appears on the LAN, this component cannot create a local control path for you — keep using the cloud integration in that case.

## Features

- Local polling for **climate** (AC) and **humidifier** (dehumidifier) platforms
- Sensors, binary sensors, switches, selects, numbers, and buttons from the App **CommandList** / TaiSEIA capability set
- For types without a CommandList: generic entities from the device service list (`0x07`)
- Discovery via **SSDP** and LAN scan on port **57223**
- Optional Panasonic Taiwan **EMS** sign-in to import nicknames / ModelType / indoor model (matched by MAC)
- Optional energy sensors (period / total / house total) with configurable reset cycles (monthly, daily, weekly, yearly, or every N days)

## Stable supported devices

This integration only talks to the **TaiSEIA LAN port TCP 57223** (UPnP `SetSaanet`, commonly on CZ-T006-class controllers). The tables below list App **CommandList** ModelTypes that map to dedicated platforms — closest to official-app behaviour.

### Stable (recommended)

| Class | Type | Platform | Built-in ModelTypes (CommandList) |
| --- | --- | --- | --- |
| **Air conditioner** | `0x01` | `climate` + sensors / switches / … | GX, J, J-DUCT, LJ, LJV, LX, PU, PX, **PXGD** (default), QX, RX-N, SX-DUCT, UJ, UX, VX |
| **Dehumidifier** | `0x04` | `humidifier` + sensors / switches / … | CXW, EHW, GHW, JHV2, **JHW** (default), LXW, MHW, NHW, NNW, NNW-L, NXW |

In practice: Taiwan units that expose `57223` on the LAN and show one of the ModelTypes above in EMS / the official app are treated as **stable**. You can override ModelType in device options; when unsure, try **PXGD** (AC) or **JHW** (dehumidifier) first.

### Conditional (needs `57223`; fewer ModelTypes)

| Class | Type | Notes |
| --- | --- | --- |
| Air cleaner | `0x08` | CommandList: **LHW**, **LHW-40**. No LAN port → no local control. |
| Refrigerator | `0x02` | CommandList: **F657** only. Most newer smart fridges are cloud-only — see below. |

### Experimental / generic

TaiSEIA also defines washers, dryers, TVs, fans, heat-pump water heaters, rice cookers, drink machines, induction cookers, dishwashers, microwaves, heat exchangers, gas water heaters, lamps, and more. If a unit **actually opens `57223`**, this integration builds **generic numeric entities** from the service list (`0x07`) — not App-quality Chinese option maps, and writes are not guaranteed. Treat these as experimental; do not expect AC/dehumidifier-level polish.

## Devices that may not work

Do **not** rely on this integration in the cases below; use the official app or a cloud HA integration (Comfort Cloud, Smart App, MirAIe, …) instead.

| Situation | Why it fails or works poorly |
| --- | --- |
| **No TCP 57223 on the LAN** | There is no local control path. EMS import only brings nicknames / model metadata — it does **not** replace LAN control. |
| **Most newer smart refrigerators** (e.g. cloud-only NR series) | Common in practice: the fridge has an IP and works in the official app, but **does not** open `57223` → this integration cannot control it. Rare exceptions need F657 **and** an open local port. |
| **Washers, dryers, TVs, fans, …** | No CommandList for these classes; even with a port you only get generic entities, far short of AC/dehumidifier support. |
| **Comfort Cloud / MirAIe / non–Taiwan TaiSEIA only** | Different protocols — **out of scope** for this component. |
| **Cloud-only / away-from-home control with no LAN reachability** | Designed for the **same LAN** as Home Assistant. |
| **Firewall, guest Wi‑Fi, or VLAN isolation** | HA and the controller on different segments without `57223` allowed → discovery and polling fail. |
| **Wrong ModelType / model mismatch** | You may connect but see wrong options or dead features. Override ModelType in device options, or report diagnostics. |
| **Too many clients hammering one module** | CZ-T006-class modules can stall under concurrent SetSaanet load; lower concurrency / poll interval and avoid scanning the same IP from multiple tools at once. |

**Quick check:** from the HA network, probe TCP **57223** on the device IP. If it connects, local control may work; if not, treat the unit as cloud-only.

## Requirements

- Home Assistant **2024.1.0** or newer
- Panasonic unit with a **TaiSEIA** Wi‑Fi controller on the **same LAN** as Home Assistant
- Controller reachable on TCP port **57223** (firewall / VLAN rules permitting)

## Installation (HACS)

1. Open HACS → **Integrations** → ⋮ → **Custom repositories**
2. Add:
   - Repository: `https://github.com/n71154plus/panasonic_taiseia_local`
   - Category: **Integration**
3. Search for **Panasonic TaiSEIA Local** and install
4. Restart Home Assistant
5. Go to **Settings → Devices & services → Add integration** and search for **Panasonic TaiSEIA Local**

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=n71154plus&repository=panasonic_taiseia_local&category=integration)

## Manual installation

1. Copy `custom_components/panasonic_taiseia_local` into your Home Assistant `custom_components/` folder
2. Restart Home Assistant
3. Add the **Panasonic TaiSEIA Local** integration

## Setup

The config flow supports:

1. **EMS account import** — Sign in with the Taiwan EMS / official app account to conveniently import the device list (matched to LAN devices). EMS is not used for control or status reads.
2. **Discovery** — Scan LAN port `57223` and SSDP
3. **Manual** — Enter the TaiSEIA Wi‑Fi controller IP directly

A **hub** entry stores shared credentials and LAN / energy settings. Each **device** entry can override display name, ModelType, poll interval, and related options.

## Dynamic / DHCP IPs

Config entries store the last-known IP, but identity is **MAC-based** (`unique_id`). You usually do not need to delete and re-add the device when DHCP hands out a new address.

**Recommended (most reliable):** create a **DHCP reservation** on your router so the TaiSEIA module’s MAC always gets the same IP.

**Automatic recovery (v1.6.1+):**

1. If setup or polling cannot reach the stored IP and the entry has a MAC, the integration runs SSDP + a LAN `:57223` scan, matches by MAC, and writes the new IP back into the config entry
2. Re-discovery is rate-limited to about once every **5 minutes** so the LAN is not flooded
3. Home Assistant SSDP rediscovery of the same MAC also updates the stored host

**May still fail if:** no MAC was stored (manual IP-only add), HA and the module are not on the same /24, VLANs block discovery, or the new address does not open `57223`. In those cases, reserve a static lease on the router, or re-run LAN discovery (same MAC updates the existing entry).

## Diagnostics and testing

### Download diagnostics (for bug reports)

1. **Settings → Devices & services → Panasonic TaiSEIA Local**
2. Open the hub or device entry → related device → **Download diagnostics**
3. Attach the JSON to a GitHub issue (passwords / tokens are redacted)

Each device also has a diagnostic **Probe info** sensor (attributes include the service list and live status).

### Developer services (Developer tools → Services)

| Service | Purpose |
| --- | --- |
| `panasonic_taiseia_local.probe_device` | Re-run probe; return service list |
| `panasonic_taiseia_local.read_service` | Read one service (`service`: `0x00` or int) |
| `panasonic_taiseia_local.write_service` | **Advanced:** write one service (may change device state) |
| `panasonic_taiseia_local.scan_lan` | SSDP + optional /24 `:57223` scan |

Example (Developer tools → Actions; enable response):

1. Choose `panasonic_taiseia_local.read_service`
2. **Device**: pick the AC/dehumidifier with the selector (do not paste raw IDs)
3. **Service id**: choose `0x00` from the dropdown, or type e.g. `0x15`
4. Check `value` / `decoded` in the response

Use `write_service` only for advanced testing, and only against **configured** entries. Prefer diagnostics download / `probe_device` / `read_service` when filing issues.

### Debug logging

Add to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.panasonic_taiseia_local: debug
```

## License

MIT — see [LICENSE](LICENSE).
