# Panasonic TaiSEIA Local

Home Assistant 自訂整合：透過**區域網路（LAN）**直接控制配備 **CZ-T006 / TaiSEIA** Wi‑Fi 模組的 Panasonic 空調與除濕機。

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/n71154plus/panasonic_taiseia_local/actions/workflows/validate.yml/badge.svg)](https://github.com/n71154plus/panasonic_taiseia_local/actions/workflows/validate.yml)

> **English:** [README.md](README.md)

## 與其他 Panasonic 套件有何不同

社群常見的 Panasonic 整合（例如 Comfort Cloud、Smart App、MirAIe 等）多半是走**原廠雲端 API**：控制指令先離開你家網路，再由雲端轉發；網路或雲端服務異常時，控制就會跟著失效。

**本套件定位不同——以區域網路為主：**

| | 本套件（TaiSEIA Local） | 常見雲端 Panasonic 整合 |
| --- | --- | --- |
| **控制路徑** | HA **直接連線 LAN** 上的 CZ-T006 / TaiSEIA 模組 | 原廠雲端 API |
| **控制是否需要外網** | **不需要**（HA 與設備同一區網即可） | 通常**需要** |
| **通訊方式** | 本地 TaiSEIA / UPnP `SetSaanet`（預設埠 **57223**） | 雲端 HTTP API |
| **雲端帳號** | **可選**：僅用台灣 EMS 匯入暱稱／機型／對應 LAN 裝置 | 日常控制幾乎都要登入 |
| **適合情境** | 模組可在區網被掃描／連線 | 只有 App 雲端可控、沒有本地模組埠 |

日常開關機、模式、溫度與感測器等，都在**區網內輪詢與下指令**。可選的 EMS 雲端登入只做**裝置清冊／對應**（暱稱、室內機型號、ModelType 等），**不用來下空調控制指令**。

若你目前用的是 Comfort Cloud / Smart App 類型整合，且設備只能透過那些 App 雲端控制、區網上也找不到 TaiSEIA 模組，則本套件無法取代那條雲端路徑。

## 功能

- 本地輪詢：**climate**（空調）、**humidifier**（除濕機）
- 感測器、二元感測器、開關、選項、數值、按鈕等實體
- 以 **SSDP** 與 LAN 埠 **57223** 掃描發現裝置
- 可選登入 Panasonic 台灣 **EMS**，依 MAC 批次匯入對應的區網設備
- 可選電能統計感測器

## 需求

- Home Assistant **2024.1.0** 或更新版本
- 具備 **CZ-T006 / TaiSEIA** 模組，且與 Home Assistant 位於**同一區域網路**
- 模組可連線 TCP 埠 **57223**（請確認防火牆／VLAN）

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

1. **EMS 帳號匯入**：使用與官方 App 相同的台灣 EMS 帳號登入，比對雲端清冊與區網 MAC 後批次匯入
2. **自動發現**：掃描 LAN 埠 `57223` 與 SSDP
3. **手動輸入**：直接填寫 CZ-T006 模組 IP

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
