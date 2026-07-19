# Panasonic TaiSEIA Local

Home Assistant 自訂整合，透過區域網路（LAN）控制配備 Panasonic CZ-T006 / TaiSEIA 模組的空調與除濕機，並可選用官方 EMS 雲端帳號匯入裝置暱稱與機型資訊。

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/n71154plus/panasonic_taiseia_local/actions/workflows/validate.yml/badge.svg)](https://github.com/n71154plus/panasonic_taiseia_local/actions/workflows/validate.yml)

## 功能

- 本地輪詢控制空調（climate）與除濕機（humidifier）
- 感測器、開關、選項、數值、按鈕等實體
- SSDP / LAN 埠掃描發現裝置
- 可登入 Panasonic 台灣 EMS 帳號，批次匯入雲端裝置對應的區域網設備
- 可選用電能統計感測器

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

1. **EMS 帳號匯入**：使用與官方 App 相同的帳號登入，比對雲端裝置與區域網 MAC 後批次匯入
2. **自動發現**：掃描 LAN 埠 `57223` 與 SSDP
3. **手動輸入**：直接填寫 CZ-T006 模組的 IP

Hub 條目會保存帳號與共用 LAN／電能設定；各裝置條目可調整顯示名稱、ModelType、輪詢間隔等。

## 需求

- Home Assistant **2024.1.0** 或更新版本
- 裝置需在同一區域網路，且模組可連線（預設埠 `57223`）

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
