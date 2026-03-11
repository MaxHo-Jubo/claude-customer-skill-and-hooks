---
name: explore-report
description: "探索指定目錄並強制產出結構化報告，確保每次探索都有具體產出。當使用者提到 /explore-report、想探索某個目錄、說「看看這個資料夾」、或想了解某個模組的架構時使用此 skill。"
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

### 探索階段（限時：不超過整體 40% effort）

1. 用 Explore subagent 快速掃描目標目錄：
   - 檔案總數、行數統計
   - 目錄結構樹
   - 主要 export 和入口點
   - 使用的技術棧（框架版本、狀態管理、路由等）

2. 對關鍵檔案進行精讀（限 5-10 個最重要的檔案）：
   - 入口檔案（index.js / index.tsx）
   - 最大的檔案（通常是核心邏輯）
   - 連接外部模組的檔案

### 產出階段（必須執行）

3. 撰寫探索報告到 `spec/.exploration-log.md`（append 模式）：

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

4. 如果帶 `--to-spec`：
   - 在報告完成後，調用 `/spec-module` 的邏輯產出正式 spec
   - 報告作為 spec 的輸入素材

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
- `spec/.exploration-log.md` 用 append 模式，保留歷次探索記錄
- 每次報告用 `---` 分隔，方便閱讀
