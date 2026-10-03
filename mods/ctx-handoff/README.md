# ctx-handoff (save-progress variant)

[繁體中文](README.zh-TW.md)

> **Origin:** modified from [cablate/ctx-handoff-mod](https://github.com/cablate/ctx-handoff-mod) by cablate (MIT), based on commit [`f871109`](https://github.com/cablate/ctx-handoff-mod/commit/f871109) (2026-10-03). The original copyright notice is kept in [LICENSE](LICENSE). See [Changes from upstream](#changes-from-upstream).

A Claude Code mod that hands a long conversation over to a fresh one **automatically**: when the main conversation's context reaches a threshold, it has the model run the `save-progress` skill, which writes a handoff record to disk (into the Jira dev note when the branch has a Jira key, otherwise a file named after the branch). Once the file is confirmed written, it runs `/clear` and has the new conversation read that record. While you are away it keeps the prompt cache warm, then saves a record instead of clearing. You type no commands in the normal flow.

**Who it's for:** people who run long Claude Code sessions on a 1M-context model with a Claude subscription (1-hour prompt cache) and have the `save-progress` skill installed. **Status:** experimental, built on Claude Code's early-access function-hooks API. Read [Limitations](#limitations) before relying on it.

## Changes from upstream

| | Upstream | This variant |
|---|---|---|
| How the handoff is made | `$.model.fork` writes a ≤1500-char summary | A real turn runs the `save-progress` skill (a fork has no tools, so it cannot run a skill) |
| Where it is kept | Full text in the mod's `$.store` (last 5) | On disk: the `## 交接紀錄` section of `{project}/.claude/{JIRA-KEY}.md`, or `{project}/.claude/handoff-{branch}.md`; `$.store` keeps only the last 5 paths |
| What the new conversation gets | The handoff text | The record's path, which it reads itself (`/jira` reads it too) |
| Checks before `/clear` | Clears once the fork answers | The save turn must end normally, its last line must be `HANDOFF_FILE: <absolute path>`, and the file must exist and be modified after the save started; otherwise it does **not** clear and says why in a toast |
| Recognising the save turn | Not needed | The save prompt carries `[ctx-handoff:save]`; `turn.start` records its `turnId`. Turns you start meanwhile don't trigger a handoff. A save prompt still unrecognised after 10 minutes is dropped when the next main-loop turn ends |
| Away handoff | Fork summary into `$.store` | Runs `save-progress`, no `/clear`; no further refresh or save once one exists |
| Non-interactive sessions | Hand off like any other | When `session.start` reports `isInteractive: false` (`claude -p`, the SDK, scheduled runners), no automatic handoff and no idle refresh, so a caller waiting for a result never gets a save turn and `/clear` inserted; `/handoff-now yes` still works by hand |
| Failure handling | — | A prompt blocked by another plugin or a settings hook (`{ drop }`) counts as a failure; timer-started work logs and toasts on failure instead of vanishing; after 2 consecutive failed saves, automatic handoff pauses for the session (`/handoff-now yes` still works); `/handoff-resume`／`/handoff-continue` delete the away record only after success, and a held message that cannot be sent goes back into the prompt box |
| Tests | 9 | 24 |

Threshold values, idle-refresh cadence and background-work detection are as upstream; the `/handoff-*` command names are kept, with behaviour adjusted as above.

## What it does

All three paths apply to the main conversation only. Subagent turns are ignored.

| When | What happens | You do |
|---|---|---|
| **A turn ends and context ≥ 600k** (or 80% of the window, whichever is lower) | Waits if background shells, workflows or subagents are still running. Otherwise submits the save prompt; once the record is confirmed, runs `/clear` and the new conversation reads it, reports what it understood and waits for you. | Nothing |
| **You've been idle 55 minutes** | Forks a tiny request to refresh the prompt cache, up to 3 times. At the 4th point it runs `save-progress` for an "away handoff" and does **not** clear. | Nothing |
| **You come back after an away handoff** | Holds your first message and asks you to choose. | `/handoff-resume` clears and has the new conversation read the record and answer your message. `/handoff-continue` stays in the old one. |

Where the record goes is decided by the `save-progress` skill (its STEP 01): `{project}/.claude/{JIRA-KEY}.md` when the branch has a Jira key, `{project}/.claude/handoff-{branch with / → -}.md` otherwise, `{project}/.claude/handoff-{folder}.md` outside git or on a detached HEAD.

## Quick start

Requires a Claude Code build with function hooks (mods) and a local `save-progress` skill. Developed and tested on 2.1.288.

```sh
claude --plugin-dir ~/.claude/mods/ctx-handoff
```

Run `/handoff-status` in the session, then `/handoff-now yes` once to walk the whole flow by hand. To load it in every session, add an absolute path to `env` in `~/.claude/settings.json` (`;` between folders on Windows, `:` on macOS/Linux):

```json
"env": { "CLAUDE_CODE_PLUGIN_DIRS": "/Users/you/.claude/mods/ctx-handoff" }
```

If `claude plugin test` says `hooks modules are turned off in this process`, mods are not enabled for that account yet (server-side flag `tengu_plugin_hooks_modules`).

The mod's messages are in Traditional Chinese.

## Commands

| Command | Purpose |
|---|---|
| `/handoff-status` | Context use, threshold, refresh state, save turn, away handoff, last record path |
| `/handoff-refresh on\|off` | Turn idle cache refresh on or off. When off, the away handoff is saved after 55 idle minutes |
| `/handoff-resume` | Use the away handoff: `/clear`, then have the new conversation read the record and the held message |
| `/handoff-continue` | Drop the away handoff and send the held message in the old conversation |
| `/handoff-now yes` | Run `save-progress` and hand off now (clears once the record is confirmed) |

## Configuration

Constants at the top of [`hooks/register.ts`](hooks/register.ts):

| Constant | Default | Meaning |
|---|---|---|
| `THRESHOLD` | `600_000` | Context tokens that trigger a handoff |
| `WINDOW_RATIO` | `0.8` | On smaller windows, the threshold becomes `window × ratio` |
| `IDLE_MS` | 55 min | Idle time before a refresh (tuned for a 1-hour cache) |
| `MAX_REFRESH` | `3` | Refreshes before the away handoff |
| `MIN_TOKENS` | `30_000` | Below this, skip refresh and the away handoff |
| `SAVE_LOST_MS` | 10 min | Give up on a save prompt still unrecognised after this long, checked when the next main-loop turn ends (not a timer) |
| `MAX_SAVE_FAILURES` | `2` | Consecutive failed saves before automatic handoff pauses for the session |

## Limitations

- **Save-turn recognition is not yet verified in a real session.** It relies on `turn.start` text containing `[ctx-handoff:save]`; whether the engine keeps a mod-submitted prompt's text verbatim there cannot be simulated in tests. If it fails, the first main-loop turn ending more than 10 minutes later shows a "save turn not recognised, the record may already be written" toast; the conversation is not cleared. While you are away with no new turns, the save stays pending until you return.
- **A message sent between the end of the save turn and `/clear` is lost from the handoff.** `/clear` runs once the session is idle, so such a turn runs in the old conversation and is then cleared; the record does not include it.
- **Saving is a real turn.** Running `save-progress` at 600k reads the whole cached context and calls tools; whether it counts against subscription limits is unconfirmed.
- **An away save may stop at a permission prompt** if writing the record needs your approval.
- **Depends on `save-progress` reporting the path** as the last line `HANDOFF_FILE: <absolute path>`; a missing or relative path, or an unmodified file, cancels the handoff.
- **5-minute cache users should turn refresh off** (`/handoff-refresh off`). The mod does not detect the TTL.
- **The idle refresh is unverified** (whether a fork's cache read extends the main conversation's 1-hour entry).
- **Background-work detection is partial.** Workflow and Monitor task IDs are parsed from output text; a never-ending task defers the handoff up to 12 hours. Use `/handoff-now yes` to force it.
- **Held messages keep only their text.**
- **Hot reloads reset** the timers, the save-turn state and the background-task tracking.
- **The API is early access.**

## Development

```sh
claude plugin validate .
claude plugin test .
tsc -p .   # after the mod has loaded once, which writes .claude-plugin/types/
```

## License

[MIT](LICENSE). Original work Copyright (c) 2026 cablate; this variant is distributed under the same license.
