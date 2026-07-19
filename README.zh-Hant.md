# Panasonic TaiSEIA Local

Home Assistant 自訂整合：透過**區域網路（LAN）**直接控制配備 **TaiSEIA** Wi‑Fi 控制器（如 CZ-T006）的 Panasonic 家電。

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/n71154plus/panasonic_taiseia_local/actions/workflows/validate.yml/badge.svg)](https://github.com/n71154plus/panasonic_taiseia_local/actions/workflows/validate.yml)

> **English:** [README.md](README.md)

## 與其他 Panasonic 套件有何不同

社群常見的 Panasonic 整合（例如 Comfort Cloud、Smart App、MirAIe 等）多半是走**原廠雲端 API**：控制指令先離開你家網路，再由雲端轉發；網路或雲端服務異常時，控制就會跟著失效。

**本套件定位不同——以區域網路為主：**

| | 本套件（TaiSEIA Local） | 常見雲端 Panasonic 整合 |
| --- | --- | --- |
| **控制路徑** | HA **LAN 直連**帶有 TaiSEIA 的 Wi‑Fi 控制器 | 原廠雲端 API |
| **控制／讀取是否需要外網** | **不需要**（HA 與設備同一區網即可） | 通常**需要** |
| **通訊方式** | 本地 TaiSEIA / UPnP `SetSaanet`（預設埠 **57223**） | 雲端 HTTP API |
| **雲端帳號** | **可選**：EMS 僅方便匯入設備清單 | 日常控制幾乎都要登入 |
| **適合情境** | 區網上可連線到 TaiSEIA Wi‑Fi 控制器 | 只有 App 雲端可控、沒有本地控制器埠 |

日常開關機、模式、溫度與感測器等，都在**區網內輪詢與下指令**。EMS 帳號僅用於方便使用者**匯入設備清單**（暱稱／ModelType／室內機型號），**不負責下控制指令與讀取指令**。

### 可共存（不是二選一）

本套件是**多一條本地控制路徑**，**不必**卸載官方 App，也**不必**移除其他 Panasonic 的 Home Assistant 整合（Comfort Cloud、Smart App、MirAIe 等）。

- 官方 App 可繼續照常使用
- 家裡若已裝其他 Panasonic HA 雲端套件，也可以一起保留
- 本套件走 **LAN** 直連 TaiSEIA Wi‑Fi 控制器；官方 App／其他雲端整合仍走原本路徑

可依情境並用（例如在家用本地控制、出門用官方 App）。安裝本套件不是要取代那些工具。

若設備只能靠雲端 App 控制、區網上也找不到 TaiSEIA Wi‑Fi 控制器，本套件無法憑空提供本地控制，請繼續使用雲端型整合。

## 功能

- 本地輪詢：**climate**（空調）、**humidifier**（除濕機）
- 感測器、二元感測器、開關、選項、數值、按鈕等實體（來自 App **CommandList**）
- 無 CommandList 的品類：依機器服務清單（`0x07`）自動產生通用實體
- 以 **SSDP** 與 LAN 埠 **57223** 掃描發現裝置
- 可選登入 Panasonic 台灣 **EMS**，方便匯入設備清單（以 MAC 對應區網）
- 可選耗電感測器（本期／累計／全室加總），週期可設每月／每日／每週／每年／每 N 天

## 確定能支援的設備

**前提：** 區網要開 TCP **57223**。沒有本地埠就無法用本套件控制。

| 品類 | TYPE | 支援程度 |
| --- | --- | --- |
| 冷氣 | `0x01` | **完整** — ModelType：GX、J、J-DUCT、LJ、LJV、LX、PU、PX、**PXGD**（預設）、QX、RX-N、SX-DUCT、UJ、UX、VX |
| 除濕機 | `0x04` | **完整** — CXW、EHW、GHW、JHV2、**JHW**（預設）、LXW、MHW、NHW、NNW、NNW-L、NXW |
| 空氣清淨機 | `0x08` | CommandList **LHW**／**LHW-40**（需有 57223） |
| 電冰箱 | `0x02` | CommandList **F657**（許多新冰箱為雲端專用、無本地埠） |
| 其他 TaiSEIA 品類 | 洗衣、電視、電扇… | 認得類型；有 57223 時為**通用實體**（非 App 級中文選項） |

## 需求

- Home Assistant **2024.1.0** 或更新版本
- 具備 **TaiSEIA** Wi‑Fi 控制器，且與 Home Assistant 位於**同一區域網路**
- 控制器可連線 TCP 埠 **57223**（請確認防火牆／VLAN）

## 安裝（HACS）

1. 開啟 HACS → **Integrations** → 右上角選單 → **Custom repositories**
2. 新增儲存庫：
   - Repository：`https://github.com/n71154plus/panasonic_taiseia_local`
   - Category：`Integration`
3. 在 HACS 搜尋 **Panasonic TaiSEIA Local** 並安裝
4. 重新啟動 Home Assistant
5. 到 **設定 → 裝置與服務 → 新增整合**，搜尋 **Panasonic TaiSEIA Local**

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=n71154plus&repository=panasonic_taiseia_local&category=integration)

## 手動安裝

1. 將 `custom_components/panasonic_taiseia_local` 複製到 Home Assistant 設定目錄的 `custom_components/`
2. 重新啟動 Home Assistant
3. 新增整合 **Panasonic TaiSEIA Local**

## 設定方式

設定流程支援：

1. **EMS 帳號匯入**：登入台灣 EMS／官方 App 帳號，方便匯入設備清單（對應區網裝置）。EMS **不負責**下控制指令與讀取指令
2. **自動發現**：掃描 LAN 埠 `57223` 與 SSDP
3. **手動輸入**：直接填寫 TaiSEIA Wi‑Fi 控制器 IP

**Hub** 條目保存帳號與共用 LAN／電能設定；各**裝置**條目可調整顯示名稱、ModelType、輪詢間隔等。

## 除錯

在 `configuration.yaml` 加入：

```yaml
logger:
  default: info
  logs:
    custom_components.panasonic_taiseia_local: debug
```

## 授權

MIT — 詳見 [LICENSE](LICENSE)。
