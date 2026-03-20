# 程式碼標準

---

## Commit Message 規則

### 格式

```
[Jira編號] 類型(專案標識): 說明
```

- Jira 編號從 branch 名稱取得，如 `ERPD-7777/feat/max_ho/測試` → `[ERPD-7777]`
- 類型：`feat`, `fix`, `refactor`, `chore`, `docs`, `test` 等
- 專案標識：`(App)` / `(FE)` / `(BE)`
- 說明若檔案有 `FeaturePath` 標註，必須以完整 FeaturePath 開頭再接描述

### 範例

```
[LVB-7866] fix(App): 居服App-我的班表-班表-班表-修正忘簽退因請假班被擋住而失效
[ERPD-11696] feat(FE): luna-首頁-移除舊版公告元件
[ERPD-12345] fix(BE): luna-API-修正排班查詢效能問題
```

---

## 程式碼風格規則

### if 語句必須有大括號

```javascript
// ❌ 禁止
if (!value) return;

// ✅ 正確
if (!value) {
  return;
}
```

### 不可變性（Immutability）

永遠建立新物件，不要修改原物件：

```javascript
// ❌ 禁止 mutation
user.name = newName;

// ✅ 建立新物件
const updatedUser = { ...user, name: newName };
```

### 禁止 console.log

正式程式碼中不得殘留 `console.log`。

### 禁止 Magic Number

程式碼中不得出現未經解釋的數字常數，必須抽出為具名常數並加上註解。

---

## 安全性規則

- 禁止 hardcoded secrets（API key、token、密碼）
- 禁止在 log 中印出敏感資料（token、password 等）

---

## 錯誤處理規則

- `async/await` 必須搭配 `try-catch`
- 空值 / undefined 存取必須做防護

---

## 註解規則

### 變數與常數

所有變數與常數都必須加上註解，說明其用途與意義。

### 函式與方法

所有函式與方法都必須加上註解，說明用途、參數與回傳值格式。JS / TS 程式碼的註解必須符合 JSDoc 規範。

### STEP 格式

- 依照函式內執行順序加上 STEP 註解，從 STEP 01 開始
- 最多 4 階層：`STEP 01.01.01.01`
- 遇到縮排或邏輯分支，階層增加一個
- 每個函式獨立編碼，皆從 STEP 01 開始
- **Functional component 內部不需要 STEP 註解**
- **內部成員函式的邏輯需要 STEP 註解**

### 註解正確性

- 程式邏輯與註解說明必須一致，不得有過時或錯誤的註解
- 註解不得出現錯字

---

## 修改全域變數或共用狀態的注意事項

移除或修改全域變數、共用常數、共用函式時，必須搜尋該檔案中所有使用該變數的位置，確認全部都已處理。不能假設「改了主要方法就夠了」。

---

## Code Review 品質評分

PR review 時依以下 6 項評分，每項 1-5 分：

| 分數 | 意義 |
|------|------|
| 5 | 完美 |
| 4 | 不錯 |
| 3 | 還可以 |
| 2 | 不好 |
| 1 | 拒絕接受 |

### 評分項目

1. **Magic Number** — 程式內是否有未經解釋的數字常數
2. **邏輯與註解一致性** — 程式邏輯與註解說明是否相符
3. **函式註解** — 是否有完整的函式註解說明（JSDoc）
4. **變數/常數/props/state 註解** — 是否有加上用途說明
5. **註解錯字** — 註解說明是否有錯字
6. **系統穩定性** — 是否有造成系統 crash 的可能

滿分 30 分。

---

## React 規則（適用 FE / React Native）

- 避免不必要的 re-render：適當使用 `React.memo`、`useCallback`、`useMemo`
- `useEffect` 有訂閱或計時器時必須有 cleanup function

---

## React Native 規則（僅適用 App）

- 大列表必須使用 `FlatList` / `SectionList`，禁止用 `ScrollView` + `map`
- 靜態樣式應使用 `StyleSheet.create()` 抽出；動態樣式（依據螢幕尺寸等）可寫在 render 內
