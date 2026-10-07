# herdr-cockpit

Herdr plugins that make a multi-agent session readable at a glance.

| Plugin | Id | What it does |
|---|---|---|
| [`spaces`](spaces/) | `chrysa.spaces` | Space rows: agent count in the project color, agents waiting for you (`‼ 2 attendent`, `✓ 1 terminé`), accounts used (one color per account), worktrees |
| [`cockpit`](cockpit/) | `chrysa.cockpit` | Palette and templates for the whole herdr setup (`setup` installs, `status` reports drift) |
| [`agent-info`](agent-info/) | `chrysa.agent-info` | Sidebar tokens per agent (account, model, git, task, subagents), auto-naming `<space>-<topic>`, right-hand info panel with conversation and agents views |

Local reads only: herdr socket, Claude Code / Codex / opencode session files. No network, no telemetry.

## Develop

```sh
uv sync --locked
uv run pytest
```

Specs and plans live in `work/` (`work/specs`, `work/plans`).

Release: bump `version` in the three `herdr-plugin.toml`, merge, then push a
`vX.Y.Z` tag; the release workflow runs tests and `validate`, checks the
versions match the tag, and publishes notes built from the commits.

## Install

Pin a released version (tags `vX.Y.Z`, see Releases) so another machine stays stable:

```sh
herdr plugin install chrysa/herdr-cockpit/cockpit --ref v0.2.0
herdr plugin install chrysa/herdr-cockpit/spaces --ref v0.2.0
herdr plugin install chrysa/herdr-cockpit/agent-info --ref v0.2.0
# then, in herdr: action "Cockpit: setup" (or python3 <cockpit root>/setup.py)
```

Sidebar rows and keybindings: see each plugin's README.
