# Panasonic TaiSEIA Local

Home Assistant 自訂整合：控制配備 **TaiSEIA** 的 Panasonic 家電，支援**區網 LAN**與台灣 **EMS 雲端**，並可**每機選擇**控制路徑。

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/n71154plus/panasonic_taiseia_local/actions/workflows/validate.yml/badge.svg)](https://github.com/n71154plus/panasonic_taiseia_local/actions/workflows/validate.yml)

> **English:** [README.md](README.md)

## 更新紀錄

### v1.7.0 — 雲端＋本地混合控制

**起因：** 只靠區網 `SetSaanet` **關冷氣時，不會觸發原廠「乾燥防霉」**；官方 App／EMS 走 `DeviceSetCommand` 關機才會。此版為解決這個差異而做。

**變更摘要：**

- 每機可設控制路徑：**混合**（預設）／**僅本地**／**僅雲端**
  - **寫入（下指令）**：混合 → **雲端優先**，失敗再 LAN
  - **讀取（狀態）**：混合 → **本地優先**，失敗再雲端輔助
- 雲端協定依官方 IoT TW **APK**（`DeviceSetCommand`／`DeviceGetInfo`，含 `CPToken` + `auth` + `GWID`），並有較乾淨的限流閘門
- **僅雲端匯入**：無區網模組（如部分冰箱）或埠不通的設備可標「(雲端)」匯入
- 名稱後綴：**(本地)**／**(雲端)**
- 關機走**雲端寫入**時可觸發官方乾燥防霉（混合／僅雲端）。LAN 模擬乾燥防霉**暫緩**

升級後請重載整合，到各設備選項設定「控制路徑」。冷氣若要接近 App 關機（含乾燥防霉），請用 **混合**。

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
| **除濕機** | `4` | **可用** | 有開 57223 時同冷氣 |
| **空氣清淨機** | `8` | **有條件** | LHW／LHW-40 + 57223，或雲端 |
| **電冰箱** | `2` | **多為僅雲端** | 無 57223 時以「(雲端)」匯入 |
| 其他 | … | 有限 | EMS 有清單才可雲端；有 57223 才可本地 |

### 冷氣／除濕 ModelType

| 品類 | 平台 | ModelType（不確定用粗體） |
| --- | --- | --- |
| 冷氣 | `climate` 等 | GX、J、J-DUCT、LJ、LJV、LX、PU、PX、**PXGD**、QX、RX-N、SX-DUCT、UJ、UX、VX |
| 除濕 | `humidifier` 等 | CXW、EHW、GHW、JHV2、**JHW**、LXW、MHW、NHW、NNW、NNW-L、NXW |

可在裝置選項覆寫 ModelType。

## 功能

- climate／humidifier 與感測、開關、選項、數值、按鈕等（CommandList）
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
3. 每機：名稱、ModelType、輪詢、**控制路徑**、耗電選項

## 動態 IP

身分以 **MAC**（或僅雲端的 `gwid:…`）為主；LAN 斷線時可依 MAC 重找（v1.6.1+）。建議路由器 DHCP 保留。

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
