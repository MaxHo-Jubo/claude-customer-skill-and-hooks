# Jira Wiki Markup 速查

> 由 jira-test-report skill S7「發 inline comment」用（v2.5.3+ 從 SKILL.md 抽出）。
> Wiki Markup 走 Jira REST API v2 `/rest/api/2/issue/{key}/comment`，後端自動轉成 ADF mediaSingle node，是讓截圖 inline 顯示的唯一可靠方式。

## 語法表

| 功能 | 語法 |
|------|------|
| h2 標題 | `h2. 文字` |
| h3 標題 | `h3. 文字` |
| 粗體 | `*文字*` |
| 斜體 | `_文字_` |
| 行內 code | `{{code}}` |
| Code block | `{code:javascript}...{code}` |
| 引用 | `bq. 文字` |
| 分隔線 | `----` |
| 圖片 inline | `!filename.png\|width=900!` |
| 表頭 | `\|\| col1 \|\| col2 \|\|` |
| 表格 | `\| cell \| cell \|` |
| 連結 | `[文字\|https://url]` |
| 編號清單 | `# item` |
| 項目清單 | `* item` |

## 注意

- 一定要 **REST v2**（v3 不接受 wiki），endpoint：`/rest/api/2/issue/{key}/comment`
- `!filename.png|width=900!` 中 width 視截圖比例調整（一般 800-900 看得清）
- 標題 `h2.` `h3.` **要有空格**（`h2.文字` 不會生效）
- 粗體 `*text*` 兩端不可有空格直接接英數，會被當 list bullet
- Code block 含 `{code}` 配對，內部任何字串都不會被解析（含 `\|`）

## 為什麼不用 ADF v3

- MCP `addCommentToJiraIssue` 走 ADF v3，attachment id 不能直接當 media id（回 `ATTACHMENT_VALIDATION_ERROR`）
- 嘗試從 attachment redirect 拿 media UUID 自己拼 ADF 也不可靠（location header 可能被 CDN 截斷）
- v2 wiki markup `!filename!` 由後端 server-side 解析為正確 ADF mediaSingle node，含真正的 media UUID
