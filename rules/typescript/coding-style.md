# TS-CODING-STYLE | extends common/coding-style | for-AI-parsing

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
  banned: production code
  action: use proper logging libraries
  detection: see hooks

REACT:
  re-render: 避免不必要的 re-render；適當使用 React.memo / useCallback / useMemo
  useEffect-cleanup: useEffect 有訂閱或計時器時必須有 cleanup function

REACT-NATIVE:
  large-list: 大列表必須使用 FlatList/SectionList，禁止 ScrollView+map
  static-style: 靜態樣式使用 StyleSheet.create() 抽出；動態樣式（依據螢幕尺寸等）可寫在 render 內

</rules>
