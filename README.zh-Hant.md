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

## 穩定支援的設備

本套件只走 **TaiSEIA 區網埠 TCP 57223**（UPnP `SetSaanet`，常見於 CZ-T006 一類控制器）。下列為 App CommandList 已內建、且有專用平台對應的品類，使用體驗最接近官方 App。

### 穩定（建議主力使用）

| 品類 | TYPE | 專用平台 | 內建 ModelType（CommandList） |
| --- | --- | --- | --- |
| **冷氣** | `0x01` | `climate` + 感測器／開關等 | GX、J、J-DUCT、LJ、LJV、LX、PU、PX、**PXGD**（預設）、QX、RX-N、SX-DUCT、UJ、UX、VX |
| **除濕機** | `0x04` | `humidifier` + 感測器／開關等 | CXW、EHW、GHW、JHV2、**JHW**（預設）、LXW、MHW、NHW、NNW、NNW-L、NXW |

實務上：台灣市售、能在區網掃到 `57223`、且 EMS／App 顯示為上述 ModelType 系列的冷氣與除濕機，可視為**穩定支援**。ModelType 可在裝置選項覆寫；不確定時冷氣用 PXGD、除濕用 JHW 通常可先試。

### 有條件（有 57223 才可用；實體較完整但仍屬少數機型）

| 品類 | TYPE | 說明 |
| --- | --- | --- |
| 空氣清淨機 | `0x08` | CommandList：**LHW**、**LHW-40**。必須區網開 `57223`，否則無法本地控制。 |
| 電冰箱 | `0x02` | CommandList：**F657**。僅少數仍開本地埠的機型；多數新冰箱見下方「可能無法使用」。 |

### 實驗／通用（認得品類，但不是 App 級體驗）

TaiSEIA 規格尚有洗衣機、烘衣機、電視、電扇、熱泵熱水器、電子鍋、開飲機、電磁爐、烘碗機、微波爐、全熱交換器、燃氣熱水器、燈具等。若機器**真的開了 57223**，本套件會依服務清單（`0x07`）產生**通用數值實體**（例如「服務 0xNN」），**沒有**官方 App 那套中文選項對應，也不保證每支服務可寫入。這類請當實驗用途，不要期待與冷氣／除濕同等穩定。

## 哪些裝置可能無法使用

下列情況**不適合**依賴本套件，或只能得到很差／沒有的本地控制；請改用官方 App 或雲端型 HA 整合（Comfort Cloud、Smart App、MirAIe 等）。

| 情況 | 為什麼用不了／不好用 |
| --- | --- |
| **區網掃不到 TCP 57223** | 沒有本地控制通道。EMS 帳號匯入只能帶暱稱／型號，**不能**代替 LAN 控制。 |
| **多數新型智慧冰箱**（例如僅雲端可控的 NR 系列） | 實測常見：有 IP、官方 App 可遙控，但**不開** `57223` → 本套件無法控制。僅極少數（如仍對應 F657 且開埠）可能例外。 |
| **洗衣機、烘衣機、電視、電扇等** | 內建 CommandList **沒有**這些品類；即使有埠也只是通用實體，功能與穩定度都不如冷氣／除濕。 |
| **只有 Comfort Cloud／MirAIe／海外雲、沒有台灣 TaiSEIA 控制器** | 通訊協定不同，本套件**不適用**。 |
| **只能靠外網、人在外面才控得了、家裡區網永遠連不到模組** | 本套件設計在**同一 LAN**；跨網／純雲端場景請用官方 App 或其他雲端整合。 |
| **防火牆、訪客 Wi‑Fi、VLAN 隔離** | HA 與控制器不同網段且未放行 `57223` → 發現與輪詢都會失敗。 |
| **ModelType／機種對不上** | 冷氣／除濕仍可能「連得上但選項錯、部分功能無效」。請在裝置選項改對 ModelType，或回報機型與診斷資訊。 |
| **同一模組被過多客戶端同時狂打** | CZ-T006 類模組在開機／多整合並發時可能暫時無回應；可調低並發與輪詢間隔，並避免與其他程式同時猛掃同一 IP。 |

**快速自測：** 在與 HA 同一網段對裝置 IP 探測 TCP **57223**。連得上 → 才有機會用本套件；連不上 → 請當雲端專用設備，改走雲端整合。

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

## 動態 IP（DHCP）怎麼辦

裝置條目會記住當下的 IP，但辨識身分是以 **MAC** 為主（unique_id）。IP 變了不一定要刪掉重建。

**建議（最穩）：** 在路由器／防火牆幫 TaiSEIA 模組做 **DHCP 保留（固定租約）**，讓 MAC 永遠拿到同一個 IP。多數家用路由器都支援「依 MAC 綁定 IP」。

**本套件也會自動補救（v1.6.1+）：**

1. 開機或輪詢連不上舊 IP 時，若條目已有 MAC，會用 SSDP + 區網 `:57223` 掃描，依 MAC 找回新 IP 並寫回設定
2. 為避免狂掃區網，自動重找約每 **5 分鐘**最多一次
3. Home Assistant 的 SSDP 再次發現同一台時，也會用 MAC 對上並更新 IP

**仍可能失敗的情況：** 沒記到 MAC（例如早期手動只填 IP）、模組與 HA 不在同一 /24、VLAN 隔離、或新 IP 上根本沒開 `57223`。這時請在路由器綁固定 IP，或到整合選項／重新設定流程用「區網搜尋」再加一次（同一 MAC 會更新既有條目）。

## 診斷與測試

### 下載診斷（回報 issue 用）

1. **設定 → 裝置與服務 → Panasonic TaiSEIA Local**
2. 開啟 Hub 或裝置條目 → 相關裝置 → **下載診斷**
3. 將 JSON 附在 GitHub issue（密碼／token 會自動遮罩）

裝置上也有診斷感測器 **「探測資訊」**（屬性含服務清單與即時狀態）。

### 開發者服務（開發者工具 → 服務）

| 服務 | 用途 |
| --- | --- |
| `panasonic_taiseia_local.probe_device` | 重跑 probe，回傳服務清單 |
| `panasonic_taiseia_local.read_service` | 讀單一服務（`service`: `0x00` 或整數） |
| `panasonic_taiseia_local.write_service` | **進階**：寫入單一服務（可能改變設備狀態） |
| `panasonic_taiseia_local.scan_lan` | SSDP + 可選 /24 `:57223` 掃描 |

範例（開發者工具 → 服務；請勾選「回傳回應」）：

1. 選服務 `panasonic_taiseia_local.read_service`
2. **裝置**：用選擇器挑冷氣／除濕（不要手填 ID）
3. **服務編號**：下拉選 `0x00`，或自行輸入如 `0x15`
4. 執行後在回應中看 `value`／`decoded`

`write_service` 僅供進階測試，且只能操作**已設定**的裝置條目；回報問題時請優先用診斷下載／`probe_device`／`read_service`。

### 除錯日誌

在 `configuration.yaml` 加入：

```yaml
logger:
  default: info
  logs:
    custom_components.panasonic_taiseia_local: debug
```

## 授權

MIT — 詳見 [LICENSE](LICENSE)。
