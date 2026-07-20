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

## Will it work for my device? (start here)

This integration does **one** thing: talk TaiSEIA over LAN **TCP 57223** via UPnP **`SetSaanet`**.
“Works in the official app” ≠ “works here.” Use the checklist and table below.

### 30-second check

| Step | Pass if |
| --- | --- |
| ① EMS / official app | Device is listed |
| ② GWID | **12 hex digits** (MAC-like, e.g. `7061BE7FD9C2`) |
| ③ LAN IP | `UserGetGWIP` / router shows a real IP (**not** `0.0.0.0`) |
| ④ Port | **TCP 57223** connects to that IP |

**All of ①–④** → likely supported (then match ModelType).
**④ fails** → **no** local control with this integration (use cloud / official app).
**② not MAC-shaped** (long / Base64 string) → almost always a cloud-only module (common on newer fridges).

> Prefer **EMS account import** during setup: if LAN discovery misses a module, the flow asks EMS for the module IP and probes `57223`.

### By appliance class

| Class | DeviceType | Supported? | Notes |
| --- | --- | --- | --- |
| **Air conditioner** | `1` | **Yes** (primary) | CZ-T006-class modules usually keep `57223` open; see ModelTypes below |
| **Dehumidifier** | `4` | **Yes** (primary) | Same as AC |
| **Air cleaner** | `8` | **Conditional** | **LHW / LHW-40** only, and only if `57223` is open |
| **Refrigerator** | `2` | **Usually no** | Pairing uses SoftAP `192.168.102.1` or BLE — **not** 57223; day-to-day control is cloud. F657 exists on paper; newer NR units often have no local port |
| Washer / dryer | `3` / `6` | **No** | No TaiSEIA command table; pairing is BLE / JP SoftAP |
| TV, fan, other small appliances | other | **No / experimental** | Even with an open port you only get generic entities |

### AC / dehumidifier ModelTypes

Built-in App **CommandList** with dedicated platforms:

| Class | Platform | ModelTypes (bold = default when unsure) |
| --- | --- | --- |
| AC | `climate` + sensors / switches / … | GX, J, J-DUCT, LJ, LJV, LX, PU, PX, **PXGD**, QX, RX-N, SX-DUCT, UJ, UX, VX |
| Dehumidifier | `humidifier` + … | CXW, EHW, GHW, JHV2, **JHW**, LXW, MHW, NHW, NNW, NNW-L, NXW |

Override ModelType in device options. Name in the table but device not found → almost always network / VLAN / closed port — **not** an unsupported series name (same for UX / PX).

### Pairing path ≠ day-to-day local control (from the official APK)

| Pairing (app) | Day-to-day (app) | This integration |
| --- | --- | --- |
| AC / dehumidifier: SoftAP `pana-aircondition-*` / `panasonicsmart-*` → `192.168.1.1:57223`, or BLE pairing | **Cloud** `DeviceSetCommand` | If LAN `57223` stays open → **SetSaanet works** |
| Fridge: SoftAP `Panasonic-NR-*` → `192.168.102.1`, or BLE+QR | **Cloud only** | **No** 57223 path |

The official app does **not** use SetSaanet for normal remote control. This component is a **parallel local protocol** on the same hardware port.

## Features

- Local polling for **climate** (AC) and **humidifier** (dehumidifier) platforms
- Sensors, binary sensors, switches, selects, numbers, and buttons from the App **CommandList** / TaiSEIA capability set
- For types without a CommandList: generic entities from the device service list (`0x07`)
- Discovery via **SSDP** and LAN scan on port **57223**
- Optional Panasonic Taiwan **EMS** sign-in to import nicknames / ModelType / indoor model (MAC match; EMS IP fallback when scan misses)
- Optional energy sensors (period / total / house total) with configurable reset cycles (monthly, daily, weekly, yearly, or every N days)

## Advanced / experimental classes

| Class | Type | Notes |
| --- | --- | --- |
| Air cleaner | `0x08` | CommandList: **LHW**, **LHW-40**. Requires open `57223`. |
| Refrigerator | `0x02` | CommandList lists **F657**; most newer smart fridges have **no** local port — see “Usually no” above. |
| Other TaiSEIA classes | — | If `57223` is **actually** open, generic numeric entities are created; experimental only. |

## Common failure modes

| Situation | Why |
| --- | --- |
| **No TCP 57223 on the LAN** | No local control path. EMS import does not replace LAN control. |
| **Newer smart refrigerators (NR, …)** | SoftAP/BLE pairing then cloud; GWID often non-MAC; GWIP often `0.0.0.0`. |
| **Washers, dryers, TVs, …** | No CommandList / no long-lived 57223. |
| **Comfort Cloud / MirAIe / non–Taiwan only** | Different protocols — out of scope. |
| **Firewall, guest Wi‑Fi, VLAN** | HA and module on different segments without `57223`. |
| **Wrong ModelType** | Connects but options wrong — override in device options or report diagnostics. |
| **Too many clients on one module** | CZ-T006 can stall; lower concurrency / poll interval. |

**Quick check:** probe TCP **57223** on the module IP. Connects → this integration may work; does not → treat as cloud-only.

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
