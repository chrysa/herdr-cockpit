# herdr-cockpit — design of the remaining work

Status: proposed, 2026-10-06. Reference: Forge-Stack-Workshop/synapse
`docs/product-contract-spec` (one source of truth, idempotent `setup`,
`status` reporting drift, a distribution that ships config and themes together).

## 1. Why

The herdr setup now lives in four places (dotfiles `herdr/config.toml`, two
plugins in this repo, Claude Code `settings.json` per account, opencode config)
and each one picks its own colors and symbols. Adding a machine means repeating
manual steps; changing a color means editing three files. Several requests are
still open: tell accounts apart on space rows, filter agents by the selected
space, group by state.

## 2. Decisions

| # | Decision |
|---|----------|
| D1 | A third plugin, `cockpit/` (`chrysa.cockpit`), owns the herdr configuration. Dotfiles stops carrying `herdr/`. |
| D2 | `cockpit/palette.toml` is the only source of colors and state symbols. Every surface (herdr sidebar, info bar, Claude status line, opencode theme) is generated from it. |
| D3 | `cockpit setup` is idempotent: it renders, backs up what it replaces, links, and reloads. Running it twice changes nothing. |
| D4 | `cockpit status` reports drift (hand-edited `config.toml`, missing link, stale status line, plugin disabled) and never writes. |
| D5 | Accounts get a fixed color in the palette (`perso`, `pro`, `codex`, `opencode:<provider>`), used everywhere an account appears. |
| D6 | Anything herdr cannot do natively (filter by selected space, group by state, collapsible sections) is done in the info bar, not by patching herdr. |
| D7 | `spaces`, `agent-info` and `rtk-savings` share one daemon (`cockpit/daemon`) so herdr is polled once per tick, not three times. |
| D8 | No network, no telemetry; text from agents is stripped of control characters before rendering (already true, kept as a rule). |

## 3. Layout

```
herdr-cockpit/
├─ cockpit/                 chrysa.cockpit
│   ├─ herdr-plugin.toml    actions: setup, status; startup: daemon
│   ├─ palette.toml         colors, account colors, state symbols (D2)
│   ├─ templates/
│   │   ├─ config.toml.j2   herdr config (sidebar rows, keys)
│   │   ├─ statusline.sh    Claude Code status line
│   │   └─ opencode-theme.json.j2
│   ├─ setup.py             render + link + reload (D3)
│   ├─ status.py            drift report (D4)
│   └─ daemon.py            single poller feeding spaces/agent-info/rtk (D7)
├─ spaces/                  chrysa.spaces      (renderers only after D7)
├─ agent-info/              chrysa.agent-info  (renderers + info bar)
├─ tests/                   pytest, run in CI
└─ work/                    specs, plans
```

## 4. Features

### 4.1 Accounts on space rows (D5)
Space row 1 becomes `● padam-av  5 agents  perso pro`. Each account name is
drawn in its palette color, deduplicated, ordered by agent count. A space
whose agents all use one account shows one name. Source: `agent-info`'s
account resolution (Claude config dir, Codex, opencode provider). Tokens:
`$acc_<account>` pre-styled rows, one populated per account present, same
trick as `$sp0..7`.

### 4.2 Unified interfaces (D2)
One palette, one symbol set:

| State | Symbol | Color |
|---|---|---|
| working | ◐ | green |
| blocked | ‼ | red |
| done | ✓ | blue |
| idle | ○ | grey |

Applied to herdr `status_indicators`, the info bar, the Claude status line and
an opencode theme `chrysa-cockpit` (written to `~/.config/opencode/themes/`,
selected in `tui.json`). Git symbols `⑂ ↑ ↓ + ~ ?` are shared too.

### 4.3 Filter agents by selected space (D6)
The info bar gains a second mode, `a` (agents): it lists the agents of the
space that holds the focused tab, grouped by state (4.4). herdr exposes the
focused workspace in `workspace list`, so the list follows the user's
selection with a one-second refresh. `a` toggles between "this conversation"
and "this space"; `A` widens to all spaces.

### 4.4 Group by state, collapsible (D6)
In agents mode, sections `‼ bloqués`, `◐ en cours`, `✓ terminés`, `○ en
attente`, each with a count. `1`–`4` collapse or expand a section; collapsed
state persists in the plugin state dir. Empty sections are hidden.

### 4.5 Setup and status (D3, D4)
`herdr plugin install chrysa/herdr-cockpit/cockpit`, then the action
`cockpit: setup`:
1. render templates from `palette.toml` into the plugin state dir;
2. back up and replace `~/.config/herdr/config.toml`, the Claude status line
   (each `~/.claude*` account), the opencode theme;
3. install the systemd user units (config reload, log trim);
4. enable `spaces`, `agent-info`, disable the plugins this setup replaces;
5. `herdr server reload-config`.
`cockpit: status` prints one line per item: ok / drift (with diff) / missing.

### 4.6 One daemon (D7)
One loop reads `agent list`, `workspace list`, `pane list` once per tick and
hands the snapshot to each renderer. `rtk-savings` becomes a renderer too
(its repo stays, the cockpit vendors its renderer).

### 4.7 Blocked-only notification
When an agent enters `blocked`, one desktop notification
(`notify-send`, falling back to herdr toast) naming the agent and its space.
Nothing for other states. Replaces `jyasha11.in-your-face`.

## 5. Testing
pytest in CI on every push: name generation, account resolution, billing
detection, git summary parsing, palette rendering (golden files for each
template), `status` drift detection against fixtures. Renderers take a
snapshot dict, so no live herdr is needed.

## 6. Migration
1. Ship `cockpit` with `setup` producing the current config byte for byte.
2. Run `status` on this machine: expect only the dotfiles link as drift.
3. Run `setup`; remove `herdr/` from dotfiles and its `install.sh` lines; call
   the cockpit setup from `install.sh` instead.
4. Then land 4.1–4.7 one at a time.

## 7. Out of scope
Patching herdr itself; remote/SSH sessions; Windows.
