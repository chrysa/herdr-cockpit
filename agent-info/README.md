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
  `$wait1`..`$wait3` ("‼ subject" of each agent waiting on you, longest wait
  first), `$wait_more` ("+2 en attente"), cleared when nobody waits, and
  `$count_<perso|pro|codex|other>`: agents and subagents per state for that
  account ("‼1 ◐2 ○1 ⑂●2✓1").
- **Agent rows**: `$agent_icon` (‼ ◐ ⑂ ✓, nothing when idle) and the name under
  `$topic_<account>`, or `$topic_idle` (dim grey) for an idle agent.
- **Subtasks** of each Claude agent, `$sub1`..`$sub13` ("⑂ ● Security review")
  and `$sub_more`: one line each for the focused agent, one summary line
  ("⑂ ●2 ✓3") for the others. Finished ones stay 30 min, unfinished ones up to
  6 h (`/subtask` forks included). From `<session>/subagents/` and the
  main transcript's `<task-notification>` entries, read incrementally
  (`subagents.py`, same state rules as agent-panel). Also listed: workflow agents
  (`subagents/workflows/<run>/`, finished once `<session>/workflows/<run>.json`
  reports a final status) and background Bash tasks (a Bash result starting with
  "Command running in background with ID" or "Command did not complete … moved to
  the background (ID: …)", finished by their task notification).
- **"‼" on tabs waiting on you** (herdr's tab `agent_status` = blocked). A tab
  herdr.auto-title named gets its name cleared when the wait ends, so auto-title
  names it again; a tab you named gets your name back. Which kind a tab is comes
  from auto-title's `manual-names.json` and is kept in
  `~/.local/state/chrysa.agent-info/marked-tabs.json`.
- **Agent names** follow the tab name (the conversation title when the tab is
  unnamed, named after a default branch, or auto-title derived its name from it);
  a default branch in auto-title's context is dropped (`repo › main › x` shows
  `repo › x`).
- **Real time**: `events.py` subscribes to herdr events over the socket (one
  status subscription per agent pane, reopened when panes change) and watches
  Claude transcript mtimes every 0.5 s; without a socket it falls back to the
  8 s poll.
- **Space names** under one of six tokens, `$space_<busy|idle>_<pro|perso|other>`
  (busy = an agent there works, waits on you or has finished), so the sidebar can
  bold busy spaces and dim idle ones in their ecosystem color: the account most of
  the space's agents run under (`pro`, `perso`; codex or unknown: grey). A space
  without agents keeps the last color seen there, else takes its nearest parent's.
  Every space counts its agents per state, idle ones included (`○2`); an idle
  space gets no icon: `$space_icon` (‼ ◐ ✓, the most urgent state there) replaces
  herdr's `state_icon`, which also marks idle and unknown spaces; `⑂` when only
  subagents, workflow agents or background tasks work. The config colors the
  icon from the palette's `[states]` and greys out idle spaces.
- **Space groups**: a space is the child of the space whose folder holds its own
  (folders come from the panes' cwd: the one named like the space, else the most
  common), else of the space whose name plus "-" starts its own; the name wins
  when it is the more specific (its space sits inside the folder parent). A child
  drops the leading words it shares with its parent's name. Spaces are drawn
  as a tree, in alphabetical order (case-insensitive) at every level, each child
  right after its parent: a child shows its name without the parent's prefix
  behind `├ ` (`└ ` for the last one, `│ ` to carry the line on). The daemon
  moves spaces into that order (`workspace.move` over the socket). Children of
  one parent whose names start with the same word (one letter of difference
  allowed from 5 letters: `plateform_`, `platform-`) form a second level: a dim
  header row `$group_<eco>` ("└ plateform", the most common spelling) above the
  first one, and each member drops that word and sits one level deeper
  ("⠀⠀└ socle"; herdr trims spaces around a token, so a blank unit is U+2800).
  The member under the header drops its first unit, since herdr already indents
  a space's second row by 2 columns; when the group is not its parent's last
  child, the `│` line skips that one row. Nothing is configured. A space reports
  its 18 tokens in two calls: herdr takes at most 16 per report.
- **State age and current action**: `$age` ("12m", "3h05", "2j") since the agent
  entered its state, measured by the daemon (herdr reports no timestamps) and kept
  in `~/.local/state/chrysa.agent-info/since.json`; `$doing`, the last tool call of
  a working Claude session ("Edit monitor.py"), from the transcript tail.
- **Desktop notification** (`notify-send`, `osascript` on macOS) when an agent
  starts waiting on you: once per blocked state, not for the focused pane nor for
  agents already blocked when the daemon starts. `AGENT_INFO_NOTIFY=0` turns it off.
- **Housekeeping on its own** (`tidy.py`, each action announced by a desktop
  notification):
  - a Claude agent idle for 24 h (`AGENT_INFO_TIDY_HOURS`, 0 = off), not in the
    focused tab, with no subtask and an empty prompt (a dim suggestion does not
    count) is quit with Ctrl+C twice: herdr does not resume it on restart, the
    conversation stays (`claude --resume <id>`, logged in
    `~/.local/state/chrysa.agent-info/closed.jsonl`);
  - a tab whose only pane is an agent started in a git repo below its space's
    folder moves to that repo's space, a new one if needed, sorted under its
    parent (`AGENT_INFO_SORT_TABS=0` turns it off). Never the focused tab, nor an
    agent waiting on you.
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
