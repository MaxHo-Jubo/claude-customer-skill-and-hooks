---
name: explore-report
description: "探索指定目錄並產出結構化報告。當使用者提到 /explore-report、「看看這個資料夾」、「這個模組的架構」、想了解目錄結構時觸發。"
version: 1.1.0
context: fork
agent: Explore
---

# Explore Report 探索報告

探索指定目錄並強制產出結構化報告，確保每次探索都有具體產出。

## 使用方式

- `/explore-report <目錄路徑>` — 探索並產出報告
- `/explore-report <目錄路徑> --to-spec` — 探索後直接轉成 spec 文件

範例：
- `/explore-report react_18/src/redux/sagas`
- `/explore-report react_15/company --to-spec`

## 核心原則

**禁止空手而歸。** 這個 skill 的存在就是為了防止「只讀了一堆檔案但什麼都沒寫」的 session。

## 執行步驟

### 探索階段（蒐集到足以填滿報告各欄位就轉入產出，不求讀遍）

1. 直接掃描目標目錄（本 skill 已在 Explore agent 裡執行，沒有再派 subagent 的工具）：
   - 檔案總數、行數統計
   - 目錄結構樹
   - 主要 export 和入口點
   - 使用的技術棧（框架版本、狀態管理、路由等）

2. 對關鍵檔案進行精讀（限 5-10 個最重要的檔案）：
   - 入口檔案（index.js / index.tsx）
   - 最大的檔案（通常是核心邏輯）
   - 連接外部模組的檔案

### 產出階段（必須執行）

3. 撰寫探索報告，**作為最終回覆完整回傳，不在本 skill 內寫檔**（Explore agent 沒有 Write／Edit 工具，寫檔由主 session 收到報告後做），格式：

   ```markdown
   ---
   ## <目錄名稱>（探索日期：YYYY-MM-DD）

   ### 規模
   - 檔案數：N
   - 總行數：N
   - 語言分布：JS N% / TS N% / JSX N% / TSX N%

   ### 目錄結構
   ```
   <tree output>
   ```

   ### 關鍵發現
   - [發現 1]
   - [發現 2]
   - ...

   ### 架構模式
   - [模式描述]

   ### 待深入項目
   - [ ] [需要進一步探索的項目 1]
   - [ ] [需要進一步探索的項目 2]

   ### 品質觀察
   - [觀察 1]
   ---
   ```

4. 報告結尾附一段給主 session 的指示（主 session 讀得到回覆，讀不到本 skill 內文）：
   - 「請把上方報告 append 到 `spec/.exploration-log.md`（檔案不存在就建立，保留歷次記錄）」
   - 如果帶 `--to-spec`：再加「請以此報告為輸入，接著在主 session 執行 `/spec-module` 產出正式 spec」（本 skill 不呼叫 `/spec-module`，它需要寫檔）

5. 報告完成後向使用者摘要：
   - 掃描了什麼
   - 發現了什麼
   - 建議下一步（寫 spec？寫測試？重構？）

## 報告品質要求

- 每份報告必須有「關鍵發現」和「品質觀察」
- 「關鍵發現」至少 3 條
- 數字要實測，不要估算
- 「待深入項目」用 checkbox 格式，方便後續追蹤

## 注意事項

- 使用 Glob/Grep/Read 等原生工具進行探索，不要用 bash 的 cat/head/grep
- 如果目錄超過 100 檔，先用 Glob 建立全局觀，再挑代表性檔案精讀
- `spec/.exploration-log.md` 由主 session 用 append 模式寫入，保留歷次探索記錄
- 每次報告用 `---` 分隔，方便閱讀
