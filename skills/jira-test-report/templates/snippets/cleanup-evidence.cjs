// @ts-nocheck
// ============================================================================
// jira-test-report skill — S3.5 Cleanup 鐵則範例（v2.5.2+）
// ============================================================================
// 這是「片段」非完整 cjs，缺 require / launchBrowser / finally 包裝。
// 用途：示範 CLEANUP-EVIDENCE-BEFORE-UI 鐵則的正確 pattern。
//
// 鐵則：同 step 內 injectEvidence 之後若還有任何 UI 互動（closeModal / click /
//       fill / selectOption 等），動作前必須 await clearEvidence(p);
//
// Why：#e2e-evidence-panel 注入在 viewport 右上角 fixed 定位，Modal 寬度大時
//      會 intercept pointer events → Playwright click 60 次 retry 全被擋 →
//      30s timeout step FAIL（功能本身沒 bug、人工點得下去）
//
// Case：ERPD-11841 A8 staging 100% 重現；修法是 closeModal 前一行加
//       await clearEvidence(p); 從 47s elapsed FAIL → 16s 全 PASS
//
// 寫 cjs 時可作 reference，特別是 step 結尾要 closeModal / cancel modal 場景
// ============================================================================

// case 1: step 結尾要 closeModal — injectEvidence 後、closeModal 前 clearEvidence
await step(page, 'A8', '重開selectedCase為空', '...', async (p) => {
  await clearEvidence(p);              // step 開頭清前一輪
  await openModalAndCheck(p);
  await injectEvidence(p, { /* ev fields */ });    // 注入證據
  if (failed) { throw new Error('...'); }
  await clearEvidence(p);              // ← 鐵則：closeModal 前必清
  await closeModal(p);
});

// case 2: step 結尾要 cancel modal — 同理
await step(page, 'A4.1', '取消 Modal 不送出', '...', async (p) => {
  await clearEvidence(p);
  const cancelBtn = p.locator(MODAL_FOOTER_BTN_SEL).filter({ hasText: /取消|cancel/i }).first();
  await cancelBtn.click();
  await p.waitForSelector(MODAL_OPEN_SEL, { state: 'hidden', timeout: 5000 });
});
