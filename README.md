# herdr-cockpit

Herdr plugins that make a multi-agent session readable at a glance.

| Plugin | Id | What it does |
|---|---|---|
| [`spaces`](spaces/) | `chrysa.spaces` | Space rows: agent count in the project color, accounts used (one color per account), worktrees |
| [`cockpit`](cockpit/) | `chrysa.cockpit` | Palette and templates for the whole herdr setup (`setup` installs, `status` reports drift) |
| [`agent-info`](agent-info/) | `chrysa.agent-info` | Sidebar tokens per agent (account, model, git, task, subagents), auto-naming `<space>-<topic>`, right-hand info panel with conversation and agents views |

Local reads only: herdr socket, Claude Code / Codex / opencode session files. No network, no telemetry.

## Develop

```sh
uv sync --locked
uv run pytest
```

Specs and plans live in `work/` (`work/specs`, `work/plans`).

## Install

```sh
herdr plugin install chrysa/herdr-cockpit/cockpit
herdr plugin install chrysa/herdr-cockpit/spaces
herdr plugin install chrysa/herdr-cockpit/agent-info
# then, in herdr: action "Cockpit: setup" (or python3 <cockpit root>/setup.py)
```

Sidebar rows and keybindings: see each plugin's README.
