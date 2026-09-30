> 原文：https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5｜翻譯日期：2026-09-29｜來源取得方式：curl .md

本指南介紹 Claude Sonnet 5.5 專屬的提示詞（prompt）撰寫模式。關於此模型的 API 變更，請參閱 [What's new in Claude Sonnet 5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/whats-new-sonnet-5-5)。關於適用於所有現行 Claude 模型的技巧，請參閱 [Prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)。

現有的 Claude Sonnet 5 提示詞應該不需修改就能有良好表現，[Prompting Claude Sonnet 5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5) 中的模式仍是合理的起點。對於最困難的長時程工作，Opus 模型是更好的選擇。請從符合你所觀察到現象的章節開始閱讀：

* 不確定該用哪個 effort 等級，或是每一輪的執行時間比在 Claude Sonnet 5 上更長或更短：[Calibrate effort](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5#calibrate-effort)
* 模型在程式開發任務完成前就停下來確認，或做的事比你要求的更多：[Steer initiative and scope](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5#steer-initiative-and-scope)
* 你的整合目前是在關閉思考（thinking）的情況下執行：[Running without up-front thinking](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5#running-without-up-front-thinking)
* 需要幾個步驟推演的任務，其 JSON 答案有誤或無法解析：[Reasoning tasks with JSON output](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5#reasoning-tasks-with-json-output)
* 長時間的代理式（agentic）回合看起來一片沉默：[User-facing progress updates](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5#user-facing-progress-updates)
* 當搜尋能抓到已變動的細節時，模型卻憑訓練知識作答：[Tool use in chat and knowledge work](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5#tool-use-in-chat-and-knowledge-work)
* 使用者在任務進行中送出的訊息被忽略，或被當成注入的文字：[Mid-turn user messages](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5#mid-turn-user-messages-and-task-budgets)
* 程式碼變更被回報為完成，卻沒有執行測試或建置：[Verification on coding tasks](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5#verification-on-coding-tasks)
* 模型以錯誤的大小寫呼叫工具，或以略有出入的名稱傳入參數：[Tolerant tool-call handling](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5#tolerant-tool-call-handling)
* 針對密集圖表或技術圖面的回答漏掉細節：[Tools for complex visual inputs](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5#tools-for-complex-visual-inputs)
* 請求回傳 `stop_reason: "refusal"`：[Safeguard refusals](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5#safeguard-refusals)

<Note>
  關於從 Claude Sonnet 5 遷移時的五項破壞性 API 變更，請參閱[遷移指南](https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide#migrating-from-claude-sonnet-5)。
</Note>

## Calibrate effort（校準 effort）

[Effort](https://platform.claude.com/docs/en/build-with-claude/effort) 是控制 Claude Sonnet 5.5 思考多寡的主要參數，同時也影響品質、延遲與成本。它的各個等級已重新校準：同一個等級所產生的思考量，與 Claude Sonnet 5 上的同名等級並不相同。請用你自己的評測（evals）重新掃描一輪，不要沿用你在 Claude Sonnet 5 上的設定。除非你的工作負載屬於代理式或對延遲敏感，否則請從 Claude API 的預設值 `high` 開始。對於代理式程式開發與多步驟工具使用，規格明確的任務從 `medium` 開始，較困難或較長的任務再提升到 `high`。對於聊天與其他對延遲敏感的工作，從 `medium` 或 `low` 開始，因為 effort 越高，回覆開始之前的等待就越久。若品質有需要，再提高 effort。

較低的 effort 也會改變模型完成代理式工作的方式。在 `low` 時，模型的思考會保持簡短，並可能略過對變更的驗證。請參閱 [Verification on coding tasks](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5#verification-on-coding-tasks)。在 `low` 與 `medium` 時，於長時間的代理式任務中，模型更可能在完成之前停下來向使用者確認。請參閱 [Steer initiative and scope](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5#steer-initiative-and-scope)。

以下三項調整會有幫助：

* 設定 `max_tokens` 時，要為思考與你預期的回覆留出空間。即使思考內容沒有回傳給你，思考仍會計入 `max_tokens`。以沒有思考的請求為基準所訂的上限，可能會把回覆截斷。對於代理式程式開發，請將 `max_tokens` 設為 128,000（模型的上限），並以[串流](https://platform.claude.com/docs/en/build-with-claude/streaming)方式接收回應。
* 只有在你已量測到品質提升的工作上，才使用 `xhigh` 與 `max`，因為在這些等級下，思考與回覆都會長得多。在這些等級下不接受 `between_tools`，因此無法關閉預先思考（up-front thinking）。
* 想要較少的思考，就降低 effort 等級。從 `medium` 起，模型幾乎在每次回覆前都會簡短思考，即使只是一句問候，這會增加第一個可見 token 出現前的時間。在 system prompt 中要求模型少想一點，並不能可靠地減少其思考。在 `low` 時，模型對大多數簡單請求會略過思考。

在請求之間更改頂層的 `effort` 值，會使提示詞快取（prompt cache）失效。若要讓個別回合以不同等級執行，請改用[逐訊息 effort 變更](https://platform.claude.com/docs/en/build-with-claude/effort#change-effort-mid-conversation-beta)（beta），它能保留快取。例如，讓互動式工作階段以 `low` 執行，當使用者送出困難的問題時再將 effort 提高到 `high`。逐訊息的 effort 變更需要自適應思考（adaptive thinking）。搭配 `between_tools` 時，它們會回傳 400 錯誤，詳見 [Running without up-front thinking](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5#running-without-up-front-thinking) 的說明。

## Steer initiative and scope（引導主動性與範圍）

Claude Sonnet 5.5 能自行推進到多遠，取決於 effort 等級與請求內容。在較低的 effort 下，它有時會在程式開發任務完成前先確認。在較高的 effort 下，或面對開放式請求時，它可能做得比你要求的更多。你可以透過 effort 等級與 system prompt 中的指示來引導它。

**讓工作一路完成。** 在 `low` 與 `medium` effort 的代理式程式開發任務中，模型有時會在工作完成前先確認。它可能會暫停以確認計畫、提出一個它自己就能回答的問題，或在多部分任務完成一部分後停下來詢問是否繼續。請先試試較高的 effort 等級。若要在不變更 effort 的情況下讓模型持續工作，請將以下內容加入你的 system prompt：

```text wrap
Keep working until everything the user asked for is done, and only stop to ask when you can't go on without the user or before a risky step.

When the work the user asked for is done and checked, stop and report. Don't add features, tests, files, docs or refactors that weren't asked for. If you think one would help, mention it at the end instead of doing it.
```

使用這段提示詞後，模型在 `low` 與 `medium` effort 下會把更多工作做完，因此這些等級的工作階段會執行更久、花費更多。這段提示詞不會取代你自己針對高風險或不可逆操作所訂的規則。請將這些規則保留在你的 system prompt 中。

**程式開發時未被要求的附加內容。** 即使你沒有要求，模型也傾向新增符合你程式庫慣例的測試、文件與小型輔助檔案。它在每個 effort 等級都會這麼做，effort 越高越明顯。至於被要求的變更本身，則會貼近你的要求。多數團隊會樂見這一點。如果你偏好只做明確要求的變更，請只加入該段提示詞的第二段，也就是以 "When the work the user asked for is done" 開頭的那段。在 `xhigh` 與 `max` effort 下，那一段能減少這些附加內容，並讓整體變更更小。

**`xhigh` 與 `max` effort 下的徹底程度。** 在這些等級下，模型特別徹底。完成任務後，它可能自行展開多輪審查與驗證，在你的執行框架（harness）提供子代理（subagent）時，有時還會動用子代理。它也可能順手修正沿途注意到的相關問題。這會花費更多時間與 token，因此一般工作請以 `high` 或更低的等級執行，在那些等級這種情況很少見。如果你確實想要這些 effort 等級的額外徹底程度，但希望把它導向任務本身，請將以下內容加入你的 system prompt：

```text wrap
When the work the user asked for is done and its checks pass, stop and report. Don't start extra rounds of review or hardening on your own, and don't launch reviewer sub-agents unless the user asked for a review. If you think a deeper review is worth doing, say so at the end.
```

在 `max` effort 的程式開發任務測試中，這段提示詞讓模型不再啟動審查用的子代理，使工作階段成本降低約三分之一，而品質沒有變化。它會降低主代理自行發起審查輪次的頻率，但不會完全消除。

**開放式請求。** 當請求是開放式的，例如「show me what you can do with this」，而你其實只想要一些點子時，模型可能會開始製作簡報、報告或影片。如果你希望先得到點子或計畫，請在請求中明說，或將以下內容加入你的 system prompt：

```text wrap
When the user asks for ideas, options or a plan, give them that and stop. Don't start building or changing anything until they say to go ahead.
```

## Running without up-front thinking（不進行預先思考的執行方式）

若要讓 Claude Sonnet 5.5 在沒有預先思考的情況下執行，請傳送 `thinking: {"type": "between_tools"}`。這是此模型最低的思考設定，在 `high` effort 或以下皆可使用。如果你的整合目前是關閉思考的，請改成 `between_tools`，並檢查以下幾點：

* **在 `high` effort 或以下才傳送 `between_tools`。** 在 `xhigh` 或 `max` effort 下，帶有 `between_tools` 的請求會回傳 400 錯誤。使用 `between_tools` 時，effort 也無法在對話中途變更：逐訊息的 `output_config.effort` 若與目前生效的等級不同，會回傳 400 錯誤。若要逐回合調整 effort，請使用自適應思考。使用 `between_tools` 時，請移除任何要求模型不要思考的指示。這類指示會讓模型更容易在可見輸出中寫出內部 XML 標籤。
* **依區塊類型讀取回應。** 使用自適應思考時，回應可能以一個 `thinking` 區塊開頭，在預設的 `display: "omitted"` 下，其 `thinking` 欄位是空的。使用 `between_tools` 時，回應可能以一個進度更新的 `thinking` 區塊開頭。不要假設第一個內容區塊一定是文字。
* **原封不動地傳回 `thinking` 區塊。** 使用 `between_tools` 時，模型在工具呼叫之間所寫的筆記，只要長度超過一兩句話，仍會以 `thinking` 區塊的形式回傳。每個區塊都帶有該筆記的摘要。請連同該助理回合的其餘內容一起原封不動傳回。你傳回的區塊會讓模型取得它當初所寫的完整筆記，而不只是摘要。
* **不使用工具的推理任務請用自適應思考。** 在沒有工具的請求中，`between_tools` 代表模型不會先思考就直接回答。對於需要幾個步驟推演的任務，請改用自適應思考。請參閱 [Reasoning tasks with JSON output](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5#reasoning-tasks-with-json-output)。

## Reasoning tasks with JSON output（輸出 JSON 的推理任務）

本節適用於：你要求 Claude Sonnet 5.5 針對一項需要幾個步驟推演的任務回傳 JSON 答案。例如加總文件中的數字、套用規則或對項目排序。在這類任務上，模型常會不先思考就直接作答，在 `low` 與 `medium` effort 下尤其如此。有什麼做法有幫助，取決於你如何要求 JSON。在可用的情況下，請使用[結構化輸出](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-outputs)。此時回應文字就是符合你 schema 的 JSON，不需要另外解析。

使用結構化輸出時，回應文字只包含 JSON，因此模型只能在它的思考中推演問題。當它略過思考時，在這類任務上的準確度可能會下降。以下調整有助於維持高準確度。

**請模型先思考。** 使用自適應思考時，將這一行加到 system prompt 的結尾：

```text wrap
Think the problem through before you answer.
```

加上這一行後，模型更常在作答前先思考。在 `high` effort 下，這一行能讓準確度接近模型在 `xhigh` 所達到的水準，而輸出 token 只小幅增加。在 `low` 與 `medium` effort 下，它能提高準確度，但達不到模型在 `high` 的水準，且輸出 token 的增幅較大。

**或使用 `xhigh` effort。** 搭配自適應思考時，即使沒有那一行，`xhigh` 也能在這類任務上給出最高的準確度。它使用的輸出 token 比 `high` 更多。

**使用自適應思考，而非 `between_tools`。** 在沒有工具的請求中，模型在 `between_tools` 下不會在作答前思考。那一行在此無效，且這類任務的準確度較低。對這類請求請使用自適應思考，並依本節的步驟操作。在測試中，把請求拆成兩個，一個請求取得答案、另一個請求產生 JSON，雖然能得到很高的答案準確度與 JSON 合規性，但成本與延遲都非常高。

使用結構化輸出時，在 `low` 與 `medium` effort 下，模型偶爾會一直思考直到達到 `max_tokens`。在 `high` effort 及以上，這幾乎不會發生。凡是 `stop_reason` 為 `"max_tokens"` 的回應，即使其文字包含有效的 JSON，也請視為失敗並重試。請將 `max_tokens` 設得足以容納思考與 JSON，如 [Calibrate effort](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5#calibrate-effort) 所述，但不要高於你願意為單次嘗試付出的花費。

如果你無法使用結構化輸出，而是在提示詞中要求 JSON，模型常會在回應文字中推演問題，最後才寫出 JSON。這份 JSON 通常包含正確答案，但預期整個回應都是 JSON 的解析器會失敗。有兩件事有幫助：

* **解析回應中的最後一個 JSON 值。** 只讀取 `text` 區塊，並將 `stop_reason` 為 `"max_tokens"` 的回應視為失敗。從每個 `{` 或 `[` 開始，嘗試解析一個 JSON 值。當某個值解析成功，就從該值的結尾繼續，這樣巢狀在其中的值就不會被單獨計算。保留最後找到的值。不要取第一個 `{` 到最後一個 `}` 之間的全部內容。模型偶爾會在最終 JSON 之前先寫一份草稿，這個範圍會把兩者都包含進去。如果你的答案是連續的多個 JSON 值，例如每行一筆紀錄，則保留最後一段僅以空格、逗號或換行分隔的連續值。檢查結果是否包含你預期的欄位，若沒有就重試一次。在測試中，這讓幾乎每個回應都可用，且不影響準確度。
* **也可考慮搭配自適應思考使用 `xhigh` effort。** 此時模型在其思考中推演問題，並幾乎總是只回傳 JSON。總輸出 token 與 `high` 大致相同，因為推演過程從回應文字移到了思考中。

## User-facing progress updates（面向使用者的進度更新）

在工具呼叫之間，Claude Sonnet 5.5 會寫下面向使用者的筆記，說明它剛發現了什麼、接下來要做什麼。超過一兩句話的筆記會以[進度更新 `thinking` 區塊](https://platform.claude.com/docs/en/build-with-claude/thinking#progress-updates)的形式回傳，較短的評語則維持為 `text`。在預設的 `thinking.display` 下，進度更新區塊的文字是空的，因此只渲染 `text` 區塊的用戶端在長時間的代理式回合中看起來可能一片沉默。這在聊天介面，以及使用者會即時追蹤模型工作的其他產品中最為重要。

若要顯示這些筆記，請設定 `display: "updates"`（beta，`thinking-display-updates-2026-08-18` 標頭）。使用 `between_tools` 時，這些筆記會連同其摘要文字一起回傳，因此不需要 `display` 欄位。`between_tools` 不接受其他欄位：連同它一起傳送 `display`、`budget_tokens` 或 `block_binding` 會回傳 400 錯誤。[遷移指南](https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide#text-between-tool-calls)說明了如何渲染這些筆記。有時模型需要在長回合的中途向使用者顯示確切的文字，例如一段程式碼片段，或它需要使用者回答的問題。針對這種情況，請給它一個用來傳送訊息給使用者的簡單工具，並告訴模型只在這類內容時使用該工具。請在工作階段的第一個請求中宣告這個工具，使 `tools` 清單之後不會變動。

接著，移除較舊的指示，例如「hold all findings for the final response」。如果你希望在可預期的時間點收到更新，例如在第一次工具呼叫前用一行說明它即將做什麼，並在結尾附上簡短回顧，請在 system prompt 中說明。模型會遵循這類指示。在固定時間點更新，對有人參與迴路（human-in-the-loop）的工作最有幫助。

如果長時間的工具呼叫回合仍然沉默得比你希望的更久，你的執行框架可以促使模型更新。讓它計算連續多少個工具呼叫步驟沒有向使用者送出文字或進度更新。連續數次之後，例如五次，就在最新的工具結果之後附加一則單回合的提醒。請將它作為[回合範圍的 system 訊息](https://platform.claude.com/docs/en/build-with-claude/mid-conversation-system-messages#turn-scoped-system-messages)（beta）傳送，文字大致如下：

```text wrap
The user hasn't heard from you in a while — say in a few words what you're doing, then continue.
```

如果該回合仍然保持沉默，在第二或第三次之後就停止送出提醒。在工具結果之後頻繁出現執行框架的文字，會讓模型懷疑這是提示詞注入（prompt injection），詳見 [Mid-turn user messages](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5#mid-turn-user-messages-and-task-budgets) 的說明。在之後的請求中，請將每則提醒保留在 `messages` 裡。由於提醒是附加上去的，而不是插入後又刪除，提示詞快取與[保留思考（preserved thinking）](https://platform.claude.com/docs/en/build-with-claude/preserved-thinking)都會維持完整。在 `high` effort 下，若有可用的傳送訊息給使用者的工具，這則提醒會讓模型更頻繁地更新使用者，並縮短其最長的沉默時段，而任務品質沒有可量測的變化。

## Tool use in chat and knowledge work（聊天與知識工作中的工具使用）

在聊天與知識工作的任務中，Claude Sonnet 5.5 有時會憑訓練知識作答，而網路搜尋原本能抓到已經變動的細節。例子包括什麼是允許的、必要的，或需要付費的。

首先，檢查你的提示詞中是否有不鼓勵使用工具的措辭，例如「only use tools when strictly necessary」或「minimize tool calls」，並將其移除。接著，如果你的產品提供模型搜尋工具，請將以下內容加入你的 system prompt：

```text wrap
Use the search tool to check specifics that may have changed since your training, such as what is allowed, required or charged, even when you feel confident. For researched work such as a report or a comparison, gather current sources rather than writing from your training knowledge.
```

這對研究與客服類產品最為重要，因為這類產品的答案取決於最新的細節。

## Mid-turn user messages（回合中途的使用者訊息）

Claude Sonnet 5.5 經過訓練，能抵抗間接提示詞注入，也就是透過工具結果與模型在任務中讀取的其他內容所傳入的惡意指示。有時它會把真正的使用者訊息當成可能的注入。假設使用者在任務進行中輸入的訊息，是以[對話中途的 system 訊息](https://platform.claude.com/docs/en/build-with-claude/mid-conversation-system-messages)的形式，直接放在工具結果之後，或放在 `tool_result` 區塊內送達模型。模型就可能告訴使用者，該工具結果含有偽裝成使用者訊息的文字，然後忽略該訊息或要求使用者確認。

你的執行框架在每次工具結果後加上 token 倒數，可能造成這種情況。讓使用者在模型處於多步驟回合中途時發送訊息，或讓執行框架在每一步的工具結果之後都加上指示或脈絡，也可能造成。在每一種情況下，都是有文字緊接在工具結果之後出現。若是倒數或每一步的指示，這可能在每次工具呼叫時都發生。偶爾出現的單回合提醒，例如 [User-facing progress updates](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5#user-facing-progress-updates) 中的那一則，出現的頻率就低得多。如果你對自己的提醒看到這種反應，請降低送出提醒的頻率。為避免這種誤判：

* 切勿把使用者文字放在 `tool_result` 區塊內。模型最常在這種放置方式下誤判。
* 將回合中途的使用者輸入作為使用者回合（user turn）傳遞。把使用者的話以文字區塊的形式，附加在帶有 `tool_result` 區塊的使用者訊息中，放在最後一個 `tool_result` 之後。
* 將執行框架的通知（例如提醒）放在使用者的話之後、另一則獨立的對話中途 system 訊息裡。切勿把通知與使用者的話放在同一個區塊。
* 在使用者可能於回合中途輸入的互動式工作階段中，不要在工具結果之後自行加上 token 或預算倒數。[任務預算（Task budgets）](https://platform.claude.com/docs/en/build-with-claude/task-budgets)（beta）會加入類似的倒數，但目前尚未觀察到它造成這種誤判。如果你在設有任務預算時看到這種誤判，請試試不設預算的工作階段。

## Verification on coding tasks（程式開發任務的驗證）

在代理式程式開發任務中，Claude Sonnet 5.5 通常會在回報變更完成之前先檢查自己的工作。不過在 `low` effort 下，它有時會在沒有執行任何能實際驗證該變更的檢查的情況下，就回報變更已完成。例如，它可能因為專案的相依套件尚未安裝，而略過專案的測試。

如果你看到變更被回報為完成，但對話紀錄中沒有測試或建置輸出，請將這一段或類似的內容加入 system prompt。在 `low` effort 下，它能讓略過或流於表面的檢查變得罕見，任務品質沒有可量測的變化，每個任務的成本只略微增加：

```text wrap
When you change code that can be run, built, or type-checked, run a real check that exercises the change before reporting it done: the project's tests, type-checker, or build, or the changed command itself. A syntax-only check, or a check command that failed to start, does not count; if all that is missing is the project's declared dependencies, install them with its own package manager and lockfile (e.g. npm install, pip install -r requirements.txt), never via sudo or the system package manager, unless told not to. Only if no real check can run here, say which one you did not run and why instead of reporting the change as done.
```

## Tolerant tool-call handling（寬容的工具呼叫處理）

Claude Sonnet 5.5 偶爾會用僅有大小寫不同的名稱來呼叫已宣告的工具，例如把 `Bash` 呼叫成 `bash`。它也可能以略有出入的名稱傳入已知的參數。與其把這類呼叫視為致命錯誤，不如讓你的執行框架以下列兩種方式之一處理：

* 當比對結果明確無歧義時接受該呼叫，即使大小寫不對。
* 回傳一個帶有 `is_error: true` 的 `tool_result`，並指出確切的預期名稱。模型通常會在下一回合修正該呼叫。請參閱 [Handling errors with `is_error`](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls#handling-errors-with-is-error)。

## Tools for complex visual inputs（處理複雜視覺輸入的工具）

對於密集的圖表與技術圖面，請給 Claude Sonnet 5.5 一種可以裁切、縮放或對影像執行程式碼的方式。有了這些工具，模型讀取這類輸入的準確度會明顯提高。在圖表上，這些工具在每個 effort 等級都有幫助。在技術圖面上，只有從 `high` effort 起才有幫助，並在 `xhigh` 與 `max` 時幫助最大。對圖表而言，加入工具比提高 effort 更有效：在測試中，於 `high` effort 搭配工具時，模型讀取圖表的準確度高於在 `max` effort 不搭配工具，而成本只是其一小部分。[裁切工具範例（crop tool recipe）](https://platform.claude.com/cookbook/multimodal-crop-tool)提供了可運作的工具定義。

## Safeguard refusals（安全防護拒絕）

Claude Sonnet 5.5 執行安全分類器，可以拒絕某些請求。拒絕會以一般回應的形式送達，帶有 `stop_reason: "refusal"`，且 `stop_details.category` 會指出[拒絕類別](https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback#refusal-response)：

* `cyber`：該請求可能助長網路危害，例如惡意程式或漏洞利用程式（exploit）開發。在原始碼中尋找漏洞是允許的。高風險的雙用途資安工作則不允許。
* `bio`：該請求可能助長生物危害，例如危險的實驗室方法。日常的健康與教育類問題不受影響。
* `frontier_llm`：該請求可能協助開發競爭性的 AI 模型。
* `reasoning_extraction`：該請求要求模型在回應文字中重現其內部推理。
* `general_harms`：該請求屬於其他使用政策範疇。良性的工作也可能觸發此類別。

如果 `bio` 分類器阻擋了你所屬組織的生命科學工作，你可以申請 [Life Sciences Verification Program](https://www.anthropic.com/news/life-sciences-verification-program)。

如果你開啟[伺服器端備援（server-side fallback）](https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback#server-side-fallback)（beta），它會在 Claude Sonnet 5 上重試 `cyber` 與 `frontier_llm` 的拒絕。它不會重試 `bio`、`reasoning_extraction` 或 `general_harms` 的拒絕。請參閱 [Refusals, fallback, and billing](https://platform.claude.com/docs/en/models/sonnet-5-5/whats-new-sonnet-5-5#refusals-fallback-and-billing)。

如果你的提示詞要求模型在回應中包含其推理過程，請移除這些指示，因為它們會招致 `reasoning_extraction` 拒絕。使用自適應思考時，請改從[摘要思考（summarized thinking）](https://platform.claude.com/docs/en/build-with-claude/thinking#summarized-thinking)區塊讀取推理內容（`display: "summarized"`）。
