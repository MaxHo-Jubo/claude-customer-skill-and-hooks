/**
 * codex review 引擎的面向定義與 prompt 建構。
 *
 * 消費端：scripts/codex-review.ts（平行 runner）。抽在此處是為了讓「面向清單」有單一出處——
 * 面向數必須與 lib/review-marker.ts 的 aspectsForTier()（Tier 3 = 6、Tier 2 = 1）永遠一致，
 * 否則 review 跑完後 clear-pending-review.ts 會因 N 不足而拒絕解鎖。
 *
 * 面向與現行 Claude agent 路徑一一對應（見各項 claudeCounterpart），確保換引擎不換覆蓋範圍：
 * codex 引擎與 agent 引擎跑的是同一組面向，差別只在誰執行、結果怎麼交回。
 */

/** 單一 review 面向的定義 */
export interface ReviewAspect {
  /** 面向代號；用於輸出檔名 `aspect-<key>.json`、schema 的 aspect 欄位交叉比對、--aspects 選填 */
  key: string;
  /** 面向中文名稱，供 runner 彙整輸出的狀態表顯示 */
  label: string;
  /** 對應的現行 Claude subagent_type，供文件對照與日後同步檢查（本檔不使用，僅供人閱讀） */
  claudeCounterpart: string;
  /** 該面向的審查重點，嵌入 prompt。寫成「要找什麼」而非「是什麼」，避免 codex 只做描述性摘要 */
  focus: string;
}

/** 逐條規則比對面向的代號；Tier 2 只跑這一個，對應現行的 pr-reviewer lite */
export const RULES_ASPECT_KEY = 'rules';

/**
 * 全部六個 review 面向，順序即彙整報表的顯示順序。
 * 對應 skills/commit-review/SKILL.md §3 Tier 3 的五面向表加上 pr-reviewer lite。
 */
export const REVIEW_ASPECTS: ReviewAspect[] = [
  {
    key: RULES_ASPECT_KEY,
    label: '規則逐條比對',
    claudeCounterpart: 'pr-reviewer（lite）',
    focus: [
      '逐條比對 CODE-REVIEW-RULE.md 的每一條規則，對本次 diff 新增或修改的程式碼檢查是否違反。',
      '重點條目：if 必須有大括號、不可變性（禁 in-place mutation）、禁 console.log、禁 Magic Number、',
      '變數與常數註解、函式 JSDoc、STEP 註解格式與編號連續性（禁 STEP 00、插入須整段重排）、',
      '註解與程式邏輯一致（含錯字）、修改全域變數或共用狀態時是否搜尋過所有使用點。',
      '**新增的檔案一律照規則字面檢查，不比對既有 codebase 慣例**——既有檔案採用率低不構成豁免理由。',
      'summary 欄位須包含品味評分：🟢/🟡/🔴 加上 Magic Number / 邏輯註解一致 / 函式註解 / 變數註解 /',
      '註解錯字 / 系統穩定性各 1-5 分與總分（滿分 30）。',
    ].join('\n'),
  },
  {
    key: 'code-review',
    label: '一般程式碼審查',
    claudeCounterpart: 'pr-review-toolkit:code-reviewer',
    focus: [
      '找實際會出錯的缺陷：邏輯錯誤、邊界條件、off-by-one、競態、資源洩漏、未處理的 async 中斷。',
      '特別檢查六個 async 中斷點是否各有明確出口：使用者中途取消、元件卸載或頁面離開、重複觸發、',
      '上游回 200 但 0 筆可用、上游定義或組態缺失、前置步驟失敗後的降級。',
      '`return` 在 forEach callback 內只跳出當次迭代——看到宣稱「已中止」的程式碼要確認 scope。',
      '同一概念的判斷邏輯出現在 2 個以上呼叫點（含同檔）而未抽共用 helper，算 IMPORTANT。',
    ].join('\n'),
  },
  {
    key: 'silent-failure',
    label: '靜默失敗',
    claudeCounterpart: 'pr-review-toolkit:silent-failure-hunter',
    focus: [
      '找會把錯誤吞掉的程式碼：空的 catch、catch 後只 log 不 throw、`?? defaultValue` 形式的 silent fallback、',
      '`return true` 掩蓋失敗、Promise 缺 .catch()、把「拿到回應但 0 筆可用」當成正常結果回報。',
      '判準：治本之後不該再加防護性 fallback；silent fallback 比 crash 更糟，它把 crash 換成隱性資料錯誤。',
      'NULL-SAFETY 只適用「來源本來就可能是 null/undefined」，不適用「shape 已收斂的值」——',
      '對後者加 `?? 0` 這類預設值是掩蓋 bug，不是防護。',
      '共用 helper 若把守衛放在呼叫端的記憶力上（要求每個 caller 都記得傳值），算 CRITICAL。',
    ].join('\n'),
  },
  {
    key: 'comments',
    label: '註解正確性',
    claudeCounterpart: 'pr-review-toolkit:comment-analyzer',
    focus: [
      '檢查註解與實際邏輯是否一致：描述錯誤的註解、改了程式沒同步更新的舊註解、已無對應程式碼的殘留註解、',
      '錯字、STEP 編號斷號或重複、JSDoc 的參數與回傳值和實際簽章不符。',
      '整檔重寫的檔案要特別確認原有註解沒有遺失（檔案層 JSDoc / 函式 JSDoc / @type / STEP 編號）。',
      '註解宣稱的行為與程式實際行為不符時，一律至少 IMPORTANT——錯的註解比沒有註解更糟。',
      '「用註解警告後續維護者要記得做某事」不是解法，是訊號：該處應該抽共用 helper 或加 runtime assertion。',
    ].join('\n'),
  },
  {
    key: 'tests',
    label: '測試覆蓋',
    claudeCounterpart: 'pr-review-toolkit:pr-test-analyzer',
    focus: [
      '檢查本次改動是否有對應測試、既有測試是否因改動而失效、測試是否只驗了成功路徑。',
      '錯誤路徑覆蓋：400/401/403/404、重複操作、空結果、上游逾時。',
      '判斷測試是否真的會失敗——只斷言「有輸出」而不驗內容、mock 掉待測邏輯本身、',
      '斷言恆真（例如比對兩個都由同一份程式算出的值）都算無效測試，列 IMPORTANT。',
      '若本次是修 bug，檢查是否有一條會在修復前失敗、修復後通過的回歸測試；沒有則列 IMPORTANT。',
    ].join('\n'),
  },
  {
    key: 'types',
    label: '型別設計',
    claudeCounterpart: 'pr-review-toolkit:type-design-analyzer',
    focus: [
      '檢查新增或修改的型別是否表達了該有的不變條件：可為 null 的欄位是否真的可能為 null、',
      'optional 欄位是否只是為了規避編譯錯誤（把 fail-open 寫進型別）、用 string 表達本該是列舉的值。',
      '一個布林同時承擔兩個語意（「能不能做」與「現在是哪個模式」）是缺 state 而非缺 if，列 IMPORTANT。',
      '檢查是否有 `as` 斷言掩蓋了實際不成立的假設，以及 any / unknown 是否用在邊界以外的地方。',
      '資料結構優先於程式碼：看到大量邊界 if，評估能不能改資料結構讓這些 if 消失。',
    ].join('\n'),
  },
];

/**
 * 依 Tier 取得該跑的面向清單。
 * 與 lib/review-marker.ts 的 aspectsForTier() 是同一份政策的兩種表述（該函式回數量、本函式回內容），
 * 兩者的長度必須永遠相等——runner 會在執行前做這項交叉比對，不一致即拒絕執行。
 *
 * @param tier 判定出的 Tier（僅 2 與 3 有意義）
 * @returns 該 Tier 應執行的面向陣列；Tier 2 為 rules 單一面向，Tier 3 以上為全部六面向
 */
export function aspectsForTierKeys(tier: number): ReviewAspect[] {
  if (tier >= 3) {
    return REVIEW_ASPECTS;
  }
  const rulesAspect = REVIEW_ASPECTS.find((aspect) => aspect.key === RULES_ASPECT_KEY);
  if (!rulesAspect) {
    throw new Error(`面向清單缺少 ${RULES_ASPECT_KEY}，REVIEW_ASPECTS 定義已損壞`);
  }
  return [rulesAspect];
}

/** buildAspectPrompt 所需的本次 commit 上下文 */
export interface AspectPromptContext {
  /** repo 根目錄絕對路徑 */
  repoRoot: string;
  /** 審查目標 commit ref（HEAD / hash / HEAD~3） */
  target: string;
  /** 目標 commit 的 subject 行 */
  commitSubject: string;
  /** 規則檔絕對路徑，codex 會自行讀取 */
  ruleFilePath: string;
}

/**
 * 組出單一面向要交給 `codex exec` 的 prompt。
 *
 * 必含四項（對應 skills/commit-review/SKILL.md §3 對面向 prompt 的要求，缺一該面向等於審錯目標）：
 * repo 絕對路徑、審查目標的取得方式（帶實際 target ref）、commit message、回報格式。
 * 其中「審查目標」特別重要——commit 已完成、工作目錄乾淨，若不明寫 target，
 * 預設的 `git diff` 會是空的，該面向會對著空 diff 回報「沒有問題」。
 *
 * @param aspect 本次要跑的面向定義
 * @param ctx 本次 commit 的上下文
 * @returns 完整 prompt 字串
 */
export function buildAspectPrompt(aspect: ReviewAspect, ctx: AspectPromptContext): string {
  return [
    `你是 code review 的「${aspect.label}」面向審查者。只審這個面向，其他面向由別的審查者負責，不要越界。`,
    '',
    '## 審查目標',
    `repo 根目錄：${ctx.repoRoot}`,
    `目標 commit：${ctx.target}（${ctx.commitSubject}）`,
    '',
    '**這個 commit 已經完成、工作目錄是乾淨的**，所以請自己執行下列指令取得要審的 diff，',
    '不要使用 `git diff`（那會是空的）：',
    '```',
    `git diff-tree --no-commit-id -r -p ${ctx.target}`,
    '```',
    '需要看檔案完整脈絡時，用 `git show <ref>:<path>` 或直接讀工作目錄的檔案。',
    '',
    '## 本面向的審查重點',
    aspect.focus,
    '',
    '## 規則依據',
    `專案的程式碼標準在 ${ctx.ruleFilePath}，請先讀它再開始審查。`,
    '你可以讀取這個 repo 以外的路徑，該檔案確實存在。',
    '',
    '## 回報要求',
    `- 輸出必須符合指定的 JSON schema，其中 aspect 欄位固定填 "${aspect.key}"。`,
    '- 只回報這次 diff 新增或修改的程式碼的問題。既有程式碼的既有問題不在本次範圍，除非這次改動讓它變得更糟。',
    '- 每個 finding 都要能指到具體檔案與行號。指不出位置的泛論不要寫進 findings。',
    '- 沒發現問題時 findings 給空陣列，並在 summary 說明你實際檢查了哪些檔案與哪些點，',
    '  好讓人能判斷這是「檢查過沒問題」還是「根本沒檢查到」。',
    '- 不要修改任何檔案。你的工作只有審查與回報。',
  ].join('\n');
}
