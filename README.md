# herdr-cockpit

Herdr configuration and two small plugins that make a multi-agent session readable at a glance.
Most of it is native herdr or existing marketplace plugins (see `cockpit/plugins.toml`); the code here only fills the gaps.

| Plugin | Id | What it does |
|---|---|---|
| [`cockpit`](cockpit/) | `chrysa.cockpit` | The whole setup: config templates and palette, `setup` / `status` / `validate`, plugin manifest, filters and sort for herdr's native Agents column, tab bar status, Claude Code status line |
| [`agent-info`](agent-info/) | `chrysa.agent-info` | `$account` / `$model` tokens for the sidebar, and a services pane (containers, ports, URLs of the tab's project) |

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
herdr plugin install chrysa/herdr-cockpit/agent-info --ref v0.2.0
# then, in herdr: action "Cockpit: setup" (or python3 <cockpit root>/setup.py)
```

Sidebar rows and keybindings: see each plugin's README. Why most of the setup is
native or third-party: [ADR 0001](docs/adr/0001-native-first.md). History: [CHANGELOG](CHANGELOG.md).
