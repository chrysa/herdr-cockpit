# agent-info (`chrysa.agent-info`)

What herdr and the plugin marketplace do not cover reliably:

- **`$account` and `$model` tokens** on every agent row, read from local session
  files: the Claude config dir in use (`~/.claude-perso` → `perso`), Codex, or the
  opencode provider; the model from the session transcript. Colored per account
  with native token `rules` in the sidebar config.
- **Subject and attention tokens**, from the same agent list (no extra polling):
  the conversation title of each agent under the token of its account
  (`$topic_perso`, `$topic_pro`, `$topic_codex`, `$topic_other`, one set, the
  others cleared) so the sidebar colors the subject by account; and per space
  `$theme` (a blocked agent's subject first, else the latest one) and `$more`
  ("+2" other subjects), cleared when the last agent leaves.
- **Space names** under one of six tokens, `$space_<busy|idle>_<pro|perso|other>`
  (busy = holds agents), so the sidebar can bold busy spaces and dim idle ones in
  their ecosystem color; a space named after another plus "-suffix" shows
  "↳ suffix". `$blocked` ("‼2") counts the agents waiting on you.
- **State age and current action**: `$age` ("12m", "3h05", "2j") since the agent
  entered its state, measured by the daemon (herdr reports no timestamps) and kept
  in `~/.local/state/chrysa.agent-info/since.json`; `$doing`, the last tool call of
  a working Claude session ("Edit monitor.py"), from the transcript tail.
- **Desktop notification** (`notify-send`, `osascript` on macOS) when an agent
  starts waiting on you: once per blocked state, not for the focused pane nor for
  agents already blocked when the daemon starts. `AGENT_INFO_NOTIFY=0` turns it off.
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
