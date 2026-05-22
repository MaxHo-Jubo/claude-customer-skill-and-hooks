// @ts-nocheck
// ============================================================================
// jira-test-report skill — S3.5 三合一規範範例（v2.5.2+）
// ============================================================================
// 這是「片段」非完整 cjs，缺 require / launchBrowser / finally 包裝。
// 用途：示範 LVB-7963 A3.2 / A3.3 對齊「斷言截圖三合一規範」的寫法。
//
// 三合一三要素（每個斷言 step 必須同時具備）：
//   1. 程式邏輯斷言：throw new Error 含實測 vs 預期對比
//   2. 真實頁面操作或視覺變更：DOM 至少一處可截圖識別的變化
//   3. 斷言結論可視化：injectEvidence overlay 注入右上角
//
// 純資料斷言 step 補 UI 證據的三種方式：
//   (a) 強制 native 元素展開：<select>.size = N 變 listbox（用 expandSelectAsListbox helper）
//   (b) 逐項真實 UI 互動：selectLocator.selectOption(value) 逐一選一遍
//   (c) DOM highlight：evaluate 加 outline / badge 標出比對元素
//
// 寫 cjs 時可作 reference 直接複製 + 改 selector / 預期值
// ============================================================================

// A3.2 必要選項皆可選取 — 程式邏輯 + UI 逐一選取 + evidence
await step(page, 'A3.2', '必要選項皆可選取', '逐一在下拉中選取 4 個必要選項（value 9/10/11/12），確認 UI 接受', async (p) => {
  const selectLocator = p.locator(MODAL_SELECT_SEL).first();
  const requiredValues = ['9', '10', '11', '12'];
  // STEP 01: 真實 UI 操作 — 逐一 selectOption（不只是 DOM 存在，UI 可選才算）
  for (const v of requiredValues) {
    await selectLocator.selectOption(v);
    await waitStable(p, 150);
  }
  // STEP 02: 程式邏輯斷言
  const missing = findMissingOptions(actualOptions, REQUIRED_NEW_OPTIONS);
  // STEP 03: evidence overlay（不論 pass / fail 都注入）
  await injectEvidence(p, {
    title: 'A3.2 必要選項皆可選取',
    actual: actualOptions.filter((o) => REQUIRED_NEW_OPTIONS.includes(o)),
    expected: REQUIRED_NEW_OPTIONS,
    conclusion: missing.length === 0
      ? `4 個必要選項皆出現於下拉且 UI 可選（已逐一 selectOption 驗證）`
      : `缺少 ${missing.length} 項：${JSON.stringify(missing)}`,
    ok: missing.length === 0,
  });
  if (missing.length > 0) {
    throw new Error(`結案原因下拉缺少必要選項：${JSON.stringify(missing)}`);
  }
});

// A3.3 完整 14 項皆存在 — 把 select 展開成 listbox 視覺呈現（用 evidence.cjs::expandSelectAsListbox）
await step(page, 'A3.3', '完整 14 項列表展示', '將 select 強制展開為 listbox 視覺呈現 14 項，搭配 evidence 標示比對結果', async (p) => {
  // STEP 01: 真實 UI 變更 — helper 一行搞定（內部就是 s.size = s.options.length + 樣式）
  const selectLocator = p.locator(MODAL_SELECT_SEL).first();
  await expandSelectAsListbox(selectLocator);
  // STEP 02: 程式邏輯斷言
  const missing = findMissingOptions(actualOptions, EXPECTED_FULL_ORDER);
  // STEP 03: evidence
  await injectEvidence(p, {
    title: `A3.3 完整 ${actualOptions.length} 項`,
    actual: actualOptions,
    expected: EXPECTED_FULL_ORDER,
    conclusion: missing.length === 0
      ? `實測 ${actualOptions.length} 項 / 預期 ${EXPECTED_FULL_ORDER.length} 項，完全覆蓋`
      : `缺少 ${missing.length} 項：${JSON.stringify(missing)}`,
    ok: missing.length === 0 && actualOptions.length === EXPECTED_FULL_ORDER.length,
  });
  if (missing.length > 0) {
    throw new Error(`結案原因下拉缺少完整選項：${JSON.stringify(missing)}`);
  }
});
