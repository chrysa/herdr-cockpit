# Changelog

## Unreleased

- Spaces: the folder comes first, bold, as the space's title; the subject
  ("+N" for the others) moves under it. An idle space still takes one line.
- Agents column: shows only the selected space by default (`prefix+ctrl+x`
  toggles it, `prefix+ctrl+z` shows every agent), in herdr's native
  "priority" order: an active view drops herdr's own sort, so the view now
  carries it (`prefix+ctrl+s` switches to the spaces order). Short view label.
- Agent lines drop the dimmed space name: the column shows one space by
  default, so the conversation title gets the whole width.
- Busy spaces stand out: agent-info publishes each space name under a
  busy (bold) or idle (dim) token per ecosystem color. A space named after
  another plus "-suffix" shows "↳ suffix" (`padam-av-GHA` → `↳ GHA`), so long
  names are no longer cut.
- `agent_panel_sort = "priority"`: herdr's own order matches the Agents view.
- Tabs are auto-named again: agent-info no longer puts ◐ ‼ ✓ in front of tab
  names. herdr.auto-title read each such rename as the user's and locked the
  tab for good; at startup agent-info clears the names it prefixed so
  auto-title takes them back. The state stays in the sidebar.
- Information surfaced from agents: a desktop notification when an agent starts
  waiting on you (once per wait, not for the focused pane; `AGENT_INFO_NOTIFY=0`
  turns it off); how long each agent has been in its state ("12m"); a dim
  second line with a working Claude agent's last tool call ("Edit monitor.py").
- Spaces list only the agents waiting on you: one red "‼ subject" line each
  under the space (longest wait first, 3 max then "+N en attente"), instead of
  the latest subject, which read like an agent line. Every other agent is in
  the Agents column; a space with nobody waiting takes one line.
- Spaces count agents and subagents per state, one group per account in its
  color ("‼1 ◐2 ○1 ⑂●2✓1"), on the line under the name.
- Agents column lists each Claude agent's subagents active in the last 30 min
  with their state ("⑂ ● Security review"; ● running, ◌ stalled, ✗ failed,
  ⊘ killed, ✓ done), 3 max then "⑂ +N". New `agent-info/subagents.py` reads
  Claude's subagent files and the main transcript incrementally, with the
  agent-panel rules.
- Agents are named after their tab, as in the tab bar (`audit`, `vscode`): the
  conversation title only when the tab is unnamed or auto-title derived its
  name from that title (and cut it); a tab with several agents adds each title.
- Real time: the agent-info daemon wakes on herdr events (agent status, panes,
  tabs, spaces) and on Claude transcript writes instead of every 8 s; a change
  reaches the sidebar in about a second. docker/ss snapshots stay every 8 s.
- The cockpit plugin no longer runs `daemon.py` (removed in v0.4.0) at startup and
  on every space focus, where it failed each time; agent-info starts its own daemon.
- Plugins trimmed from 21 to 14 after an audit: herdmates, agent-config-manager,
  mermaid-preview, espalier, workspace-manager, plugin-manager (unused, or doing
  nothing here) and worktrunk (`wt` not installed) are no longer declared.
- Worktrees use herdr's native actions: `open_worktree` prefix+ctrl+w,
  `remove_worktree` prefix+alt+w (`new_worktree` stays prefix+shift+g);
  `rename_workspace` is back on its default prefix+shift+w.
- Agent lines show the branch's PR from gh-pr (`$pr`, "#123 ✓") before the name.

## v0.7.0 — compact sidebar, keys without shadowed defaults (2026-11-02)

- Space folder names are never cut: the folder sits alone on its line and the
  sidebar is 40 columns wide (`sidebar_max_width` raised from herdr's 36). RTK
  savings leave the sidebar (the gauge and `∑` read as noise); they stay in the
  RTK pane (`prefix+ctrl+r`) and the Claude status line.
- Compact spaces: the space's subject on top (a blocked agent's first, else the
  latest, "+N" for the others), then state, folder and RTK on one line; an idle
  space takes one line. The ‼ / ✓ counters are dropped: the state icon and the
  blocked agent's subject already say it.
- Lighter sidebar: a space takes two lines (state, name, ‼ / ✓ counters; RTK);
  branch, agent count and accounts leave the Spaces column. An agent line starts
  with its subject (conversation title) in the color of its account, then the
  space, dimmed; the account word and the model are no longer repeated.
- Compact sidebar (Notion requests): spaces show `‼ blocked` / `✓ done` counters,
  "N agents" and the accounts in use, each in its color (agent-info publishes them);
  branch and git state share the name line, RTK keeps its own line so its figure is
  never cut; idle spaces take two lines. Agents take one line: state, space,
  account, conversation title (the model stays in the tab bar and the panel, the
  PR token is dropped from the line). Sidebar 36 columns wide.
- Spaces sidebar: names colored by ecosystem (padam in the pro account color,
  chrysa in the perso one), default branches (`develop`, `main`, `master`) dimmed
  so work branches stand out, no blank row between spaces, sidebar 30 columns wide
  (26 cut long names and the RTK figure). On a 56-row terminal ten spaces now fit
  without scrolling instead of six.
- Sidebar agent rows show the conversation title (native `terminal_title_stripped`,
  follows `/rename`) instead of usagebar's `$title`, which repeated the tab's state
  icon next to `state_icon` and kept it stale until the agent settled.
- `config.toml` template regrouped (settings, display, keys) with English comments;
  settings equal to herdr's defaults dropped (`show_agent_labels_on_pane_borders`,
  agents `row_gap`); every custom key has a `group: action` description, RTK pane
  included, so `prefix+?` reads as one list.
- Keys: no custom key shadows a herdr default any more (herdr drops a shadowed
  default without warning). reviewr moves to `prefix+shift+v`, giving back
  `prefix+shift+r` (reload config); `new_workspace` → `prefix+shift+c`,
  `rename_workspace` → `prefix+shift+e`, `swap_pane_down/up` →
  `prefix+shift+down/up`. usagebar keys move behind the prefix
  (`prefix+shift+u` limits, `prefix+ctrl+u` refresh) so panes keep `ctrl+shift+u/m`.
  `tests/test_cockpit_keys.py` checks collisions against herdr 0.9.3 defaults.

## v0.6.0 — agent-panel fork, tab states (2026-10-14)

- Tab names start with their conversation state: ◐ working, ‼ blocked, ✓ done
  (agent-info; nothing when idle).
- agent-panel now comes from the chrysa fork, which adds header lines: account,
  model, full folder, git state and the project's services (agent-info `header.py`).
  While the panel shows an agent, that agent's Claude status line is empty; without
  the panel it ends with the `prefix+ctrl+t` hint.
- `setup` reinstalls a plugin whose source or pinned commit changed.
- Codex sessions get agent-panel's `ACTION:` rule in `~/.codex/AGENTS.md`.
- Dropped `herdr-remote.relay` (no relay running: it only spawned a process per status change).
- `prefix+ctrl+t` toggles agent-panel; `setup` registers its To do / progress hooks.

## v0.5.0 — herdr 0.9.3 (2026-10-11)

- Requires herdr 0.9.3. Second prefix `ctrl+space`, `prefix+ctrl+l` clears a pane.
- `status` compares the herdr binary with the running server; `setup` refuses to
  apply while the server is older (restart it after `herdr update`).

## v0.4.0 — native first (2026-10-09)

See [ADR 0001](docs/adr/0001-native-first.md).

- Removed the `spaces` plugin, the right-hand info panel and the shared daemon,
  replaced by native herdr features and marketplace plugins.
- `agent-info` now only publishes `$account` / `$model` and provides a services pane
  (`prefix+ctrl+g`).
- Native Agents-column sort through `agent.view.set` (`prefix+ctrl+s`), no more
  config edits.
- herdr toasts top-right; OS notifications off.
- `setup` installs herdr's Claude integration in every Claude account.
- Status line simplified (no panel hand-off, cost left to usagebar).

## v0.3.0 (2026-10-08)

- Native Agents-column filters (`agent.view.set`): profile, active, selected space.
- Native tab bar status (`ui.tab_bar_right`), `agent-panel` and
  `claude-session-title` in the manifest, auto-title settings managed by setup.
- Panel key help, PR on sidebar agent rows.

## v0.2.0 (2026-10-07)

- `cockpit` plugin: palette and templates, `setup`, `status` (7 checks),
  `validate` in CI, plugin manifest, setup guards, release workflow.
