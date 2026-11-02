# agent-info (`chrysa.agent-info`)

Three small things herdr and the plugin marketplace do not cover reliably:

- **`$account` and `$model` tokens** on every agent row, read from local session
  files: the Claude config dir in use (`~/.claude-perso` → `perso`), Codex, or the
  opencode provider; the model from the session transcript. Colored per account
  with native token `rules` in the sidebar config.
- **Space tokens** for the Spaces column, from the same agent list (no extra
  polling): `$agents` ("3 agents"), `$waiting` ("‼1", blocked), `$done` ("✓1")
  and one token per account in use (`$acc_perso`, `$acc_pro`, `$acc_codex`,
  `$acc_other`) so each keeps its color. Cleared when the last agent leaves.
- **Services pane** (`prefix+ctrl+g`): containers of the tab's git project (compose
  working dir or bind mounts inside it) and processes listening on a port from
  inside it, with their URLs. `docker ps` and `ss` run in background threads.

Everything else the former info panel showed now comes from native herdr or
existing plugins: conversation, subagents, messages, refs and to-dos from
[`flowy11/agent-panel`](https://github.com/flowy11/agent-panel); plan limits and
context from usagebar; PRs from `gh-pr`; tab titles from `herdr.auto-title` and
`bcihanc/herdr-claude-session-title`; sidebar agent titles from the agent's own
terminal title (native `terminal_title_stripped`); finished / needs-input notifications from
herdr's own toasts; workspace overview from Go To; RTK from `chrysa.rtk-savings`.

Local reads only; no network. Text from agents is stripped of control characters.
