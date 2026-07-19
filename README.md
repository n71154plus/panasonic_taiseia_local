# Panasonic TaiSEIA Local（本地控制）

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![HA](https://img.shields.io/badge/Home%20Assistant-2024.1+-blue.svg)](https://www.home-assistant.io/)

> 整合 domain：`panasonic_taiseia_local`  
> 一句話：讓 Home Assistant **走區網直接控**台灣 Panasonic 智慧家電（冷氣／除濕機等），不用每次都繞雲端。

---

## 這是幹嘛的？

你家若有裝 Panasonic 官方 App（智慧空調節能服務）的冷氣、除濕機，機上通常會有一顆 **CZ-T006** 之類的 Wi‑Fi 模組。  
這顆模組在區網上會開 **57223** 埠，講一套叫 **TaiSEIA** 的協定。

這個整合做的事很單純：

1. 在區網找到這些機器  
2. 用和官方 App 同一套指令表（CommandList）建立 HA 實體  
3. **本地開關、調溫、看狀態**——HA 跟機器直接對話，不經過雲端下指令

官網帳號登入是**可選的**，主要用來一次撈出 App 裡的暱稱、室內機型號、ModelType，讓你勾選要匯入哪些機，不用一台一台手打。

控制本身仍然是本地的；登入後雲端掛了，區網控照常。

---

## 適合誰？

- 想把 Panasonic 冷氣／除濕機進 Home Assistant，又希望 **反應快、少依賴雲端**
- 已經在用 `panasonic_smart_app`（雲端整合），想再加一層 **本地備援／本地控制**
- 想在 HA 裡看 **即時功率、本期／累計耗電、全室加總**

## 不適合／做不到的

| 狀況 | 說明 |
|------|------|
| 只有雲端、區網沒開 57223 的機種 | 例如部分新冰箱：能 ping、App 能控，但區網沒有 TaiSEIA 埠 → **這整合控不到**，請繼續用雲端整合 |
| App 排程、情境、遠端 WAN、OTA | 屬於雲端功能，本整合不做 |
| 非台灣 EMS／非 TaiSEIA 模組 | 不保證可用 |
| 無 CommandList 的品類 | 仍可通用控制，但選項常是數字而非 App 中文名稱 |

---

## 支援什麼設備？

依 **TaiSEIA Table_10** 認得全部品類名稱（洗衣機、電視、熱水器、電扇…）。實際能不能控，要看機器區網有沒有開 **57223**。

| 類型 | 區網 TYPE | HA 大致會出現 |
|------|-----------|----------------|
| 冷氣 | `0x01` | climate、開關、選單、數值、感測器、耗電（CommandList） |
| 電冰箱 | `0x02` | 通用／CommandList 實體（很多新冰箱無本地埠） |
| 除濕機 | `0x04` | humidifier、開關、選單、數值、感測器（CommandList） |
| 空氣清淨機 | `0x08` | 開關／選單／感測器（CommandList，如 LHW） |
| 其他品類（洗衣、電視、電扇…） | 其餘 | 有 57223 時依服務清單自動長出通用實體 |

功能精緻程度取決於：

- 官方 App **CommandList（ModelType）** → 有中文選項的專用實體  
- 否則 → 機器回報的服務清單（`0x07`）自動產生「服務 0xNN」類通用控制  

兩邊有 CommandList 時再與服務清單取交集，避免生出機器不支援的按鈕。

---

## 怎麼裝？

### 用 HACS（建議）

1. HACS → **Integrations** → 右上角 ⋮ → **Custom repositories**
2. 貼上本 repo 網址（例如 `https://github.com/<你的帳號>/panasonic_taiseia_local`），類別選 **Integration**
3. 搜尋並下載 **Panasonic TaiSEIA Local**
4. **重啟 Home Assistant**
5. 設定 → 裝置與服務 → **新增整合** → 選 **Panasonic TaiSEIA Local**

也可在 HA 裡開：[加入此 HACS 儲存庫](https://my.home-assistant.io/redirect/hacs_repository/?owner=YOUR_GITHUB_USERNAME&repository=panasonic_taiseia_local&category=integration)（請把連結裡的 `YOUR_GITHUB_USERNAME` 改成你的 GitHub 帳號）。

### 手動安裝

把資料夾 `custom_components/panasonic_taiseia_local` 拷進 HA 的 `config/custom_components/`，重啟後再新增整合。

---

## 第一次怎麼設？（建議流程）

畫面上會引導你走這條路：

### ① 新增整合 → 選「官網帳號登入並匯入設備」

用的是跟官方 App **同一組** Panasonic 台灣 EMS 帳號（Email／密碼）。

### ② 登入成功後，勾選要匯入的機器

整合會：

- 從官網拉設備清單（暱稱、室內機型號、ModelType…）  
- 掃區網找有開 57223 的模組  
- 用 **MAC** 對起來  

清單大概長這樣：

- ✅ 官網有、區網也找到 → 可以勾選匯入  
- ⛔ 官網有、區網找不到／無 57223（例如部分冰箱）→ 只顯示「略過」，不會硬匯入  

### ③ 會出現兩種設定

| 名稱 | 角色 |
|------|------|
| **主設定**（例如 `Panasonic TaiSEIA（你的帳號）`） | 存帳號、共用參數；底下有「全室耗電」感測器 |
| **各台設備** | 真正連那台冷氣／除濕機的本地控制 |

之後若要再匯入其他機：再「新增整合」一次，選 **從官網帳號匯入更多區網設備** 即可。

### 不想登入官網也可以

進階選項裡還有：

- **僅區網搜尋**  
- **手動輸入 IP**  

這樣也能控，只是暱稱／室內機型號要自己填，ModelType 可選「自動」或手動挑。

---

## 設定怎麼調？

### 主設定（點主設定 → 設定／選項）

全室共用、改一次全部生效：

- 更新密碼／勾選重新登入（順便把官網暱稱、ModelType 同步回各機）
- 區網逾時、重試次數、同時連線上限（多台冷氣時建議 **1～3**，避免模組被打爆）
- **耗電歸零週期**  
  - 每月（可指定幾號）  
  - 每日／每週／每年  
  - **每 N 天**（自己填天數，例如 30）  
  - 或不自動歸零（只手動重置）

### 各台設備（點那台冷氣 → 設定）

只影響這一台：

- 顯示名稱、室內機型號、ModelType  
- 輪詢間隔（預設約 30 秒）  
- 要不要算耗電、要不要計入「全室加總」  
- 手動重置本期／累計耗電  

> 還沒建主設定的舊安裝：共用參數仍會出現在設備選項裡，行為跟以前一樣。

---

## 耗電感測器是什麼？

機器有回報「即時功率」（服務 `0x27`）時，整合會用功率對時間做積分（W → kWh）：

| 實體（概念） | 意思 |
|--------------|------|
| 各機「本期耗電」 | 依你設的週期自動歸零（月／日／週／N 天…） |
| 各機「累計耗電」 | 從頭累加（可手動歸零） |
| **全室冷氣本期耗電** | 掛在**主設定裝置**上，把有勾「計入全室」的機加總 |

entity id 大致是：

- `sensor.taiseia_<mac>_monthly_energy`（本期；名稱會隨週期變）  
- `sensor.taiseia_<mac>_total_energy`  
- `sensor.house_climate_energy_taiseia_local`（全室）

也有重置用的 button。  
這是本地估算，不是電表，拿來看趨勢、自動化門檻很夠用；要對電費請以真實電表為準。

---

## 跟 `panasonic_smart_app` 差在哪？可以一起裝嗎？

| | 本整合（TaiSEIA 本地） | panasonic_smart_app（雲端） |
|--|------------------------|------------------------------|
| 控制路徑 | 區網 57223 | 官網 API |
| 離線（外網掛、雲掛） | 區網在就能控 | 通常不行 |
| 冰箱等雲端專用機 | ❌ | ✅ |
| App 排程／情境 | ❌ | ✅（視雲端能力） |
| 暱稱／室內機型號 | 登入後可同步；也可手填 | 本來就有 |

**可以同時裝。** 常見用法：日常用本地控，雲端整合留著看雲端專用機或當備援。

---

## 常見問題

**Q：搜不到設備？**  
確認冷氣／除濕機與 HA 在同一區網（或路由有允許互相存取）、模組有上網、防火牆沒擋 **TCP 57223**。也可改手動輸入 IP 試試。

**Q：冰箱為什麼不能勾？**  
很多新冰箱區網沒有 TaiSEIA 埠，只能走雲端。清單會標略過是正常的。

**Q：實體很少／少了 nanoe、ECONAVI？**  
到該設備選項確認 **ModelType** 是否正確（可從官網同步，或對照 App／說明選 `PXGD` 等）。ModelType 錯了，指令表對不上，實體就會變少。

**Q：多台一起控會卡住、超時？**  
到主設定把「同時連線上限」調低（例如 1 或 2），必要時略為拉長逾時／重試。CZ-T006 同時被多人打容易喘不過氣。

**Q：診斷裡的「探測資訊」是什麼？**  
診斷用感測器，會列出類型、ModelType、服務清單、即時狀態（含白話解讀）、IP／MAC、官網暱稱與機型等，排查很好用，平常可藏起來。

**Q：密碼存在哪？**  
存在 Home Assistant 的設定項目裡（跟多數雲端整合一樣）。控制指令不依賴雲端；登入只為了匯入／同步中繼資料。

---

## 技術備註（給想鑽的人）

- 協定：HTTP + SOAP `SetSaanet`，埠 **57223**  
- PDU：`[LEN][TYPE][SERVICE][DATA_HI][DATA_LO][XOR]`  
- 讀：`service & 0x7F`，資料 `0xFFFF`；寫：`service | 0x80`  
- 功能定義：內建官方 App CommandList（多種 ModelType），再與裝置 `0x07` 服務清單取交集  
- 狀態輪詢：TaiSEIA `ALL_STATES`（`0x08`）  
- `iot_class`：`local_polling`

更完整的產業規格可參考 [TaiSEIA](https://www.taiseia.org.tw/)。

---

## 授權

MIT
