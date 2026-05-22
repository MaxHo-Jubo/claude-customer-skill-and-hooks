// @ts-nocheck
// ============================================================================
// jira-test-report skill — S3.6 機構切換 cjs 範本（v2.5.2+）
// ============================================================================
// 這是「片段」非完整 cjs，缺 require / launchBrowser / finally 包裝。
// 用途：例外 case 屬非預設 compal 機構（如豐原醫院、台南御宇）時，A1 前切過去、
//       finally 切回 compal，避免污染後續測試。
//
// 兩種寫法（依需要選一）：
//   - 推薦版：A0 / Z9 step 結構，切換動作也進 evidence（finally 區用 try/catch
//     包，避免切回失敗中斷收尾）
//   - 簡化版：不註冊成 step、純前後切換（無 evidence overlay，純機構切換）
//
// helper API（v2.4.6+）：
//   const { switchOrg, currentOrg, DEFAULT_ORG } = require('helpers/orgGuard.cjs');
//   DEFAULT_ORG = { keyword: 'compal', expectedDisplay: '仁寶長照機構' }
//
// REQUIRED_ORG 寫法：
//   keyword         — 帶 internal code（穩定），如 'compal' / '豐原'（顯示名片段）
//   expectedDisplay — 切後右上角 .list-dropdown-text 顯示文字（不是 dropdown 內 text）
// ============================================================================

// =========================================================================
// 推薦版：A0 / Z9 step 結構
// =========================================================================

const { switchOrg, DEFAULT_ORG } = require(path.join(HELPERS_DIR, 'orgGuard.cjs'));

// 該 issue 的 case_id 屬於豐原醫院機構
const REQUIRED_ORG = {
  keyword: '豐原',
  expectedDisplay: '衛生福利部豐原醫院附設居家長照機構',
};

(async () => {
  const { browser, page } = await launchBrowser({ /* opts */ });
  try {
    // ... goto + waitAndDismissOnEntry ...

    // A0: 切換到測試機構
    await step(page, 'A0', '切換到測試機構',
      `從預設 compal 切換到豐原醫院機構（${REQUIRED_ORG.expectedDisplay}），準備跑該機構的測試`,
      async (p) => {
        const r = await switchOrg(p, REQUIRED_ORG);
        await injectEvidence(p, {
          title: 'A0 切換到測試機構',
          actual: r,
          expected: { after: REQUIRED_ORG.expectedDisplay },
          conclusion: r.switched ? `切換成功：${r.before} → ${r.after}` : `已是目標機構，無需切換`,
          ok: true,
        });
      });

    // A1-AN: 正常測試步驟
    // ...

  } finally {
    // Z9: 切回預設機構（finally 強制執行，即使中間 step fail）
    try {
      await switchOrg(page, DEFAULT_ORG);
    } catch (e) {
      console.error('[orgGuard] 切回預設機構失敗：', e.message, '— 請手動切回避免後續測試污染');
    }
    // ... writeResultsJson + browser.close + exit ...
  }
})();

// =========================================================================
// 簡化版：不註冊成 step、純前後切換
// =========================================================================

await switchOrg(page, REQUIRED_ORG);
try {
  // 測試 step
} finally {
  await switchOrg(page, DEFAULT_ORG);
}
