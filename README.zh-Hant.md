# Panasonic TaiSEIA Local

Home Assistant 自訂整合：控制配備 **TaiSEIA** 的 Panasonic 家電，支援**區網 LAN**與台灣 **EMS 雲端**，並可**每機選擇**控制路徑。

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/n71154plus/panasonic_taiseia_local/actions/workflows/validate.yml/badge.svg)](https://github.com/n71154plus/panasonic_taiseia_local/actions/workflows/validate.yml)

> **English:** [README.md](README.md)

## 更新紀錄

### v1.7.4

- 僅雲端除濕機（如匯入時區網未發現的 LXW）可於設定時自動重試區網／GWIP，或在裝置選項填入 IP 解除鎖定
- 擴充 NXW／LXW 等除濕 `CommandList`：智慧節能、防霉抑菌、送風；風量標示靜音除濕／快速除濕
- 運轉模式依模組能力位元顯示（不限於精簡 App 清單）
- 說明：烘鞋衣櫃為面板專用，官方 App／IoT 無法選取（說明書註明）

### v1.7.3

- Climate／Humidifier 只依探測到的 SA 類型建立實體
- 暫時區網失敗不再鎖成僅雲端
- 雲端 Auth 過期強制刷新；ModelType／DeviceType 守衛更嚴
- 洗衣機 SP／RPH 別名到 MDH；雲端輪詢優先核心服務
- README 品類／ModelType 表更新；主設定帳號標題遮罩
- 升級自動癒合：區網主機上的黏住 cloud-only；優先採 EMS 類型覆蓋錯誤本地類型
- 探測失敗不再預設成冷氣；區網＋雲端匯入也守衛 ModelType

### v1.7.2

- 修正洗衣機等機型被誤判成除濕機
- 補上乾衣機、全熱交換器、空氣清淨機、智慧開關、重量檢知盤等 CommandList

### v1.7.1

- 減少不必要重載；診斷／認證資料更安全
- EMS 寫入更即時；區網輪詢與探索較輕
- 寫入失敗可還原；實體命名整理

### v1.7.0

- 每機可選混合／僅本地／僅雲端（雲端關機可觸發官方乾燥防霉）
- 支援無區網模組的僅雲端匯入

---

## 與其他 Panasonic 套件有何不同

常見套件多半**只走雲端**。本套件可 **LAN TaiSEIA** 與／或 **台灣 EMS**，並由你決定每台要用哪種路徑。

| | 本套件 | 常見雲端 Panasonic 整合 |
| --- | --- | --- |
| **控制路徑** | **混合／僅本地／僅雲端**（每機） | 僅雲端 API |
| **是否需要外網** | 視模式：僅本地可離線；混合／雲端寫入需 EMS | 通常需要 |
| **區網協定** | TaiSEIA／UPnP `SetSaanet`（TCP **57223**） | — |
| **雲端** | 台灣 EMS（與官方台版 App 同系） | Comfort Cloud／Smart App／MirAIe 等 |

### 可共存

可與官方 App、其他 HA 雲端整合並存。**不建議**同一個 EMS 帳號被兩個 HA 整合同時狂打（共用配額／限流）。

## 能不能用？

### 30 秒自測

| 步驟 | 通過條件 |
| --- | --- |
| ① EMS／官方 App | 看得到設備 |
| ② GWID | **12 碼 hex**（區網模組）或 **非 MAC 形狀**（僅雲端候選） |
| ③ 區網 | 真實 IP + **TCP 57223** → 本地／混合；`0.0.0.0`／不通 → **僅雲端**匯入 |

### 品類

| 品類 | DeviceType | 本套件 | 說明 |
| --- | --- | --- | --- |
| **冷氣** | `1` | **可用** | 建議 **混合**，雲端關機可走官方乾燥防霉 |
| **電冰箱** | `2` | **可用**（多為僅雲端） | 無 climate → CommandList 實體；無 57223 時以「(雲端)」匯入 |
| **洗衣機** | `3` | **可用** | 無專用 washer 平台 → 依 CommandList 建開關／選項／感測 |
| **除濕機** | `4` | **可用** | 有開 57223 時同冷氣 |
| **乾衣機** | `6` | **可用** | CommandList（App 目錄有 `CN-HP`／`HP`） |
| **空氣清淨機** | `8` | **可用** | LHW／LHW-40／MH + 57223，或雲端 |
| **全熱交換器** | `14` | **可用** | CommandList（`FYZY`） |
| **智慧／調光開關** | `17` | **可用** | `WTY`／`WTYF` |
| **重量檢知盤** | `23` | **可用** | `PZE1` |
| **住空間控制器** | `24` | **有限** | `CSC`（指令很少） |

雲端每次 GetInfo 最多送 **24** 個指令型別（優先核心實體服務）。沒有專用 HA 平台的品類仍可透過 CommandList 實體控制。

### ModelType（App CommandList）

| 品類 | HA 平台 | ModelType（不確定用粗體） |
| --- | --- | --- |
| 冷氣 | `climate` 等 | GX、J、J-DUCT、LJ、LJV、LX、PU、PX、**PXGD**、QX、RX-N、SX-DUCT、UJ、UX、VX |
| 電冰箱 | 實體 | **F657** |
| 洗衣機 | 實體 | DDH、DW、HDH、KBS、LX128B、**MDH**；**SP**／**RPH** 別名 → MDH（App 無獨立 JSON） |
| 除濕 | `humidifier` 等 | CXW、EHW、GHW、JHV2、**JHW**、LXW、MHW、NHW、NNW、NNW-L、NXW |
| 乾衣機 | 實體 | **CN-HP**、HP |
| 空氣清淨機 | 實體 | **LHW**、LHW-40、MH |
| 全熱交換器 | 實體 | **FYZY** |
| 智慧／調光開關 | 實體 | **WTY**、WTYF |
| 重量檢知盤 | 實體 | **PZE1** |
| 住空間控制器 | 實體 | **CSC** |

可在裝置選項覆寫 ModelType。

## 功能

- climate／humidifier（冷氣／除濕）；其他品類依 CommandList 建感測／開關／選項／數值／按鈕
- 控制路徑：混合／僅本地／僅雲端
- SSDP + LAN 發現；EMS 匯入（區網＋僅雲端）
- 可選耗電感測器

## 需求

- Home Assistant **2024.1.0+**
- 本地模式：同網段 TaiSEIA、TCP **57223**
- 混合／雲端：Panasonic 台灣 EMS 帳號

## 安裝（HACS）

1. HACS → **Integrations** → **Custom repositories**
2. 新增 `https://github.com/n71154plus/panasonic_taiseia_local`（Integration）
3. 搜尋安裝 **Panasonic TaiSEIA Local**，重啟 HA
4. **設定 → 裝置與服務 → 新增整合**

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=n71154plus&repository=panasonic_taiseia_local&category=integration)

## 手動安裝

將 `custom_components/panasonic_taiseia_local` 放入 HA 的 `custom_components/`，重啟後新增整合。

## 設定

1. **EMS 帳號匯入**（建議）：主設定登入後勾選設備（區網與／或僅雲端）
2. **自動發現**／**手動 IP**
3. 每機：名稱、**區網 IP**、ModelType、輪詢、**控制路徑**、耗電選項
4. 若誤標「僅雲端」但模組其實開著 57223：在裝置選項填入區網 IP（或重載整合讓它自動 GWIP／掃 MAC）即可解鎖本地／混合

## 動態 IP

身分以 **MAC**（或僅雲端的 `gwid:…`）為主；LAN 斷線時可依 MAC 重找（v1.6.1+）。建議路由器 DHCP 保留。

## Lovelace：Universal Device Card（建議）

冷氣／除濕機會帶出大量同裝置實體（溫度、風向、eco、耗電、開關等）。內建 thermostat 卡片不好一次操作這些參數；建議搭配 [Universal Device Card](https://github.com/n71154plus/universal-device-card)：主畫面做常用控制，點右上角即可彈出**同一 device** 的其餘感測與控制。

### 安裝卡片

**HACS（建議）**

1. HACS → **前端** → **自訂儲存庫**
2. 新增 `https://github.com/n71154plus/universal-device-card`（Dashboard）
3. 安裝後重新載入前端（資源通常為 `/hacsfiles/universal-device-card/universal-device-card.js`）

**手動**

1. 自 [Release](https://github.com/n71154plus/universal-device-card/releases) 下載 `dist/`（含 `universal-device-card.js` 與 `translations/`）
2. 放到 `config/www/universal-device-card/`
3. Lovelace 資源新增（JavaScript Module）：

```text
/local/universal-device-card/universal-device-card.js
```

### 範例

將 `climate.livingroom` 換成你的實體 ID：

```yaml
type: custom:universal-device-card
entity: climate.livingroom
layout: standard          # standard | mini | bar
language: zh-TW           # auto | en | zh-TW | zh-CN | ja
disable_popup: false      # false = 右上角開啟同裝置彈出層
```

精簡列：

```yaml
type: custom:universal-device-card
entity: climate.bedroom
layout: mini
language: zh-TW
```

彈出層可過濾 domain／實體（例如只留感測與開關）：

```yaml
type: custom:universal-device-card
entity: climate.livingroom
language: zh-TW
include_domains: sensor,switch,select,number
include_sensor_classes: temperature,humidity,power
```

詳見卡片倉庫 README；本整合的 climate／humidifier 與同裝置開關、選項、數值、感測器皆可直接套用。

## 診斷

設定條目可下載診斷；開發者服務：`probe_device`／`read_service`／`write_service`／`scan_lan`。

```yaml
logger:
  default: info
  logs:
    custom_components.panasonic_taiseia_local: debug
```

## 授權

MIT — 見 [LICENSE](LICENSE)。
