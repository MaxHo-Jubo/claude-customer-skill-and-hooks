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

REACT-NATIVE:
  large-list: 大列表必須使用 FlatList/SectionList，禁止 ScrollView+map
  static-style: 靜態樣式使用 StyleSheet.create() 抽出；動態樣式（依據螢幕尺寸等）可寫在 render 內

</rules>
