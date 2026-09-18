# TS-CODING-STYLE | extends common/coding-style | for-AI-parsing
<!-- 2026-08-04: REACT 段新增 state-not-derived-condition，來源為 ERPD-11967 用能力偵測常數當 render 模式條件、辨識失敗後切不到手動輸入；改前備份 coding-style.md.bak -->

<rules>

IMMUTABILITY:
  pattern: spread operator for updates → { ...original, field: newValue }
  banned: in-place mutation(obj.field = value)

ERROR-HANDLING:
  pattern: async/await + try-catch
  catch: log error + throw new Error(user-friendly message)

INPUT-VALIDATION:
  tool: Zod
  pattern: z.object({ ... }).parse(input)

CONSOLE-LOG:
  logging: 使用專案 logging library；console.log 僅限本地 debug，commit 前移除
  detection: see hooks

REACT:
  re-render: 避免不必要的 re-render；適當使用 React.memo / useCallback / useMemo
  useEffect-cleanup: useEffect 有訂閱或計時器時必須有 cleanup function
  state-not-derived-condition: 靜態能力偵測（瀏覽器 API 是否存在、feature flag、環境值）不可直接當 render 分支條件；「能不能做」與「現在是哪個模式」要分成兩個值，初始化時由前者決定後者
  why: 一個布林同時承擔兩個語意時缺的是 state 不是 if——執行期失敗要切換模式，但能力偵測結果不會變，綁在一起就改不動。ERPD-11967 用 `{SpeechRecognitionApi ? 辨識結果區 : textarea}`，辨識執行期失敗時跳了「已切換為手動輸入」但 textarea 出不來，使用者被告知可以打字卻無處可打
  class-context-consumption: class component 只需讀單一 context 值時，優先用 `Component.contextType = X`（或既有 class 外部靜態賦值慣例，如已有 `Component.propTypes = {...}` 就照同樣位置加），不要用 `<Context.Consumer>` render-prop 包住整個 render tree
  why-class-context: Consumer render-prop 會把整個既有 JSX 樹多包一層縮排、且該箭頭函式每次 render 都重新宣告（若元件有 interval/subscription 持續觸發 render，等於持續重複配置閉包+多一層 context 訂閱節點要 diff）；`contextType`/靜態賦值只多一行、無額外巢狀、無重複配置。LVB-8340 修 ConfirmMapPage.js 時第一版用了 Consumer 包住 ~60 行既有 JSX，經 review（Simplification/Efficiency 面向）抓出應改用 `ConfirmMapPage.contextType = SafeAreaInsetsContext`，改完 diff 從「整段重新縮排」變成「只新增 2 行」

REACT-NATIVE:
  large-list: 大列表必須使用 FlatList/SectionList，禁止 ScrollView+map
  static-style: 靜態樣式使用 StyleSheet.create() 抽出；動態樣式（依據螢幕尺寸等）可寫在 render 內

</rules>
