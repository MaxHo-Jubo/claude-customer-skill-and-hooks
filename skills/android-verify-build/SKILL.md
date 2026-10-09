---
name: android-verify-build
description: 建置簽章過的 release APK 並安裝到已連線的 Android 實機，用於本機驗證（不是發版）。當使用者提到 /android-verify-build、「建 release APK 裝到手機」、「用正式版 build 驗證」、「release build 裝 Pixel」時觸發。發版走 fastlane release_android／GitHub Actions release.yml，不用本 skill。
version: 1.0.0
---

# Android Verify Build — 本機驗證用 release APK

把指定 App 建成**簽章的 release APK**並裝到已連線的 Android 實機，讓使用者在接近正式環境的 build 上驗證（release build 沒有 Metro、JS bundle 內嵌，行為與 debug 不同）。**這不是發版**：不改版號、不 commit、不上傳。

## 使用方式

- `/android-verify-build` — 問要建哪個 App
- `/android-verify-build home|day|family` — 居服／日照／家屬
- 可附裝置序號：`/android-verify-build home <serial>`

## App 對照

| 代號 | 對應 `~/.claude/CLAUDE.md` PROJECT-MAP 的列 |
|---|---|
| `home` | 居服app |
| `day` | 日照app |
| `family` | 家屬App |

專案目錄名取自 PROJECT-MAP（本機檔，不在此重複），以 `find ~ -maxdepth 4 -type d -name <目錄名> -not -path '*/node_modules/*'` 解析成絕對路徑；找不到或有多個就問使用者，不要猜。下文 `$APP` = 解析出的專案根目錄、`$ANDROID` = `$APP/android`。

## 執行步驟

### STEP 01: 決定 App 與裝置

1. App 沒指定就問使用者。
2. 執行 `adb devices`，依結果：
   - **0 台** → 停止並回報「沒有連線的 Android 裝置」。**不要**自己啟動模擬器。
   - **1 台** → 用它。
   - **多台** → 序號不是 `emulator-` 開頭的實機優先；仍有多台，用 `adb -s <serial> shell getprop ro.product.model` 列出型號請使用者選。**不要寫死特定機型**（最近常用 Pixel 6，但每次以連線結果為準）。
3. 回報選定的 App、裝置序號與型號，再往下。

### STEP 02: 檢查簽章設定（不得印出機密）

`$ANDROID/gradle.properties` 需有四個 key：`MYAPP_UPLOAD_STORE_FILE`、`MYAPP_UPLOAD_KEY_ALIAS`、`MYAPP_UPLOAD_STORE_PASSWORD`、`MYAPP_UPLOAD_KEY_PASSWORD`。**只檢查 key 在不在、keystore 檔存不存在，禁止印出任何值**：

```bash
A=<$ANDROID>   # Android 專案根目錄（$APP/android）
for k in MYAPP_UPLOAD_STORE_FILE MYAPP_UPLOAD_KEY_ALIAS MYAPP_UPLOAD_STORE_PASSWORD MYAPP_UPLOAD_KEY_PASSWORD; do   # k：逐一檢查的簽章 key 名稱
  grep -q "^$k=" "$A/gradle.properties" && echo "ok $k" || echo "MISSING $k"
done
SF=$(grep '^MYAPP_UPLOAD_STORE_FILE=' "$A/gradle.properties" | cut -d= -f2-)   # SF：keystore 檔名（只用來判斷檔案存在，不印出）
[ -f "$A/app/$SF" ] && echo "keystore 檔存在" || echo "MISSING keystore 檔（路徑相對於 android/app）"
```

任一 MISSING → 停止並回報缺哪個 key 名稱，不要猜、不要用 debug keystore 湊數（release 簽章不同會讓行為與驗證目的脫節）。

### STEP 03: 建置

建置**必須以 exit code 0 結束**（輸出會有 `BUILD SUCCESSFUL`）。失敗就停在這一步：APK 目錄裡可能留著上一次建出的舊 APK（2026-10-09 實測某 App 目錄有 10-06 的 170 MB 舊 APK），建置失敗時絕不可往下安裝。

在**同一次呼叫內**用解析出的絕對路徑進目錄執行（建置要數分鐘，用背景執行或 `timeout: 600000`）：

```bash
cd <$ANDROID> && ./gradlew assembleRelease
```

- **不要帶 `clean`**：gradle 升版後 `.cxx` 的 CMake 快取會記著已被清掉的路徑，`clean` 反而炸在 fbjni prefab（2026-08-18 實測）。
- 若錯誤訊息指向 CMake／`.cxx`／fbjni prefab → `rm -rf <$ANDROID>/app/.cxx <$ANDROID>/app/build`，再執行一次 `assembleRelease`（仍不帶 clean）。
- 其他建置錯誤：回報錯誤最後 30 行，不要自行改 gradle 設定或升版。

### STEP 04: 安裝

產物固定在 `$ANDROID/app/build/outputs/apk/release/app-release.apk`。

**安裝的前提是 STEP 03 的 gradle 以 exit code 0 結束**，且 APK 檔存在。不要用 APK 修改時間判斷「是不是這次建的」：原始碼沒變時 gradle 會判定 `assembleRelease` 為 UP-TO-DATE，APK 修改時間不會更新，這是正常的成功建置、仍可安裝（重跑 skill 或把同一個 APK 裝到另一台裝置都屬此類）。回報時附 APK 修改時間供使用者自行判斷。

```bash
adb -s <serial> install -r <apk 絕對路徑>
```

- 回報 `INSTALL_FAILED_UPDATE_INCOMPATIBLE`（與裝置上已裝版本簽章不同）→ **停止並回報**，由使用者決定是否解除安裝。**不要自動 `adb uninstall`**：那會清掉該 App 的本機資料。
- 其他安裝錯誤：回報完整 adb 輸出。

### STEP 05: 回報

- APK 絕對路徑與大小
- **版本以產物為準**：`~/Library/Android/sdk/build-tools/<最新版>/aapt2 dump badging <apk> | head -1`，取 `name`／`versionCode`／`versionName`（例：`versionCode='478' versionName='1.50.38'`）。不要只讀 `build.gradle`，那是來源值、不是產物值
- 已安裝到哪台裝置（序號＋型號）
- 提醒：release build 的 JS 是內嵌的，改 JS 後要重跑本 skill 才會生效

## 禁止事項

- 不印 `gradle.properties` 內任何值（密碼、alias、keystore 路徑）
- 不改裝置系統設定（定位服務、App 權限、網路、開發者選項）——沿用 `harness/judgment-matrix.md` §3 第 8 點；開啟驗證流程必要的 App 權限不必問，但要列出改了什麼
- 不自動解除安裝、不啟動模擬器、不 commit、不改版號
- 不用於發版：發版走 `fastlane release_android` 與 GitHub Actions `release.yml`
