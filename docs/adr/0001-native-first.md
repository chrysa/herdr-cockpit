# ADR 0001 — Native herdr and marketplace plugins first

- Status: accepted
- Date: 2026-10-09

## Context

The cockpit grew to ~3 200 lines of custom code (a right-hand info panel, a
`spaces` plugin, a shared daemon, auto-naming, notifications) before herdr's
documentation and plugin marketplace had been read in full. Re-reading them
(herdr 0.9.3, ~1 600 marketplace plugins) showed that most of it already exists
natively or as a maintained plugin, sometimes more complete.

## Decision

Use native herdr and existing plugins wherever they cover the need; keep custom
code only for gaps, and record the replacement for each removed piece.

| Removed | Replaced by |
|---|---|
| `spaces` plugin (agent count, accounts, attention, worktree count, colours) | native space rows (`state_icon`, `workspace`, `branch`, `git_status`), native worktree grouping, native Agents-column filter by profile |
| Right-hand info panel (`info.py`) | [`flowy11/agent-panel`](https://github.com/flowy11/agent-panel) (conversation, subagents, messages, refs, to-dos), usagebar limits pane, herdr Go To, `chrysa.rtk-savings` pane |
| Shared daemon | nothing left to share |
| Agent auto-naming | `herdr.auto-title`, [`bcihanc/herdr-claude-session-title`](https://github.com/bcihanc/herdr-claude-session-title) |
| Blocked-agent desktop notification | herdr toasts (`[ui.toast] delivery = "herdr"`, top-right; OS notifications off) |
| `$git` / `$subs` / `$doing` tokens | agent-panel, `gh-pr` |
| Sort toggle editing the rendered config | `agent.view.set` sort (socket API) |
| Account colour variants (`$acc_*`, `$ag0..7`) | native token style `rules` |

Kept, with the reason:

| Kept | Why |
|---|---|
| `$account` / `$model` tokens (`agent-info/monitor.py`) | usagebar's `$provider` is missing for most sessions and mislabels the second account; no plugin reports the model reliably |
| Services pane (`agent-info/services_pane.py`) | no plugin lists a project's containers and listening ports with URLs |
| Agents-column filters and sort (`cockpit/agent_view.py`) | thin wrapper around the native `agent.view.set`; herdr has no built-in keys for it |
| `cockpit setup` / `status` / `validate`, plugin manifest | reproducible install and drift report; no herdr equivalent |
| Tab bar command, Claude Code status line | herdr calls a command; Claude Code needs a script |

Rejected plugins: `hhdebb/herdr-radar` and `levi-qiao/herdr-agent-usage` rewrite
`config.toml` themselves (conflicting with the rendered config), need Node or a
Rust toolchain, and radar is untested on Linux.

## Consequences

- Custom code ~3 200 → ~1 460 lines (templates included).
- Lost: "N agents" and accounts on space rows, per-ecosystem colours, the panel's
  Agents and Espace views. The native profile filter and Go To cover most of it.
- Each Claude account needs herdr's Claude integration for session ids; `setup`
  installs it per account.
- Before adding custom code, check herdr's docs (configuration, socket API) and
  the marketplace index (`https://assets.herdr.dev/plugins/index.json`) first.
