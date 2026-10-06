# herdr-cockpit

Herdr plugins that make a multi-agent session readable at a glance.

| Plugin | Id | What it does |
|---|---|---|
| [`spaces`](spaces/) | `chrysa.spaces` | One color per project ecosystem, agent-count chip, worktree count on each space row |
| [`cockpit`](cockpit/) | `chrysa.cockpit` | Palette and templates for the whole herdr setup (`setup` installs, `status` reports drift) |
| [`agent-info`](agent-info/) | `chrysa.agent-info` | Right-hand info bar for the tab's conversation (account, model, limits, context, subagents, tasks), auto-names agents `<space>-<topic>`, one-line agent rows |

Local reads only: herdr socket, Claude Code / Codex / opencode session files. No network, no telemetry.

## Install

```sh
herdr plugin install chrysa/herdr-cockpit/spaces
herdr plugin install chrysa/herdr-cockpit/agent-info
```

Sidebar rows and keybindings: see each plugin's README.
