# Panasonic TaiSEIA Local

Home Assistant custom integration for **local LAN control** of Panasonic air conditioners and dehumidifiers that use a **TaiSEIA** Wi‑Fi controller.

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

If you already use Comfort Cloud / Smart App style integrations and your units are only reachable through those apps, this component will not replace that path unless the hardware exposes a local TaiSEIA Wi‑Fi controller on the network.

## Features

- Local polling for **climate** (AC) and **humidifier** (dehumidifier) platforms
- Sensors, binary sensors, switches, selects, numbers, and buttons from the CommandList / TaiSEIA capability set
- Discovery via **SSDP** and LAN scan on port **57223**
- Optional Panasonic Taiwan **EMS** sign-in to conveniently import the device list (matched to LAN devices)
- Optional energy-tracking sensors

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

## Debugging

Add to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.panasonic_taiseia_local: debug
```

## License

MIT — see [LICENSE](LICENSE).
