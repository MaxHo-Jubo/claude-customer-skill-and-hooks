# TS-HOOKS | extends common/hooks | for-AI-parsing

<rules>

POST-TOOL-USE:
  config: ~/.claude/settings.json
  prettier: auto-format JS/TS after edit
  tsc: run after editing .ts/.tsx
  console-log-warn: warn about console.log in edited files

STOP-HOOKS:
  console-log-audit: check all modified files for console.log before session ends

</rules>
