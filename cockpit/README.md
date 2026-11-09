# cockpit (`chrysa.cockpit`)

Source of truth for the herdr setup (see `work/specs/2026-10-06-cockpit-design.md`).

- `palette.toml`: every color and project slot, used by all surfaces.
- `templates/`: files rendered from the palette with `{{section.key}}` placeholders.
- `render.py <template>`: prints a rendered template.

## Actions

- **Cockpit: setup** (`python3 setup.py [--dry-run]`): renders templates into
  `~/.local/state/chrysa.cockpit/`, links `~/.config/herdr/config.toml` to the
  rendered config, points every Claude account's status line at the rendered
  script, installs the systemd user units, enables the cockpit plugins and
  reloads herdr. Everything it replaces is saved under `backups/<timestamp>/`.
  A second run prints `nothing to do`.
- **Cockpit: status** (`python3 status.py`): read-only drift report, exit 1 on
  any drift.

## Claude Code status line

`templates/statusline.sh`: account (colored), model, folder, git state and
llmtrim's context/savings/cache. Plan limits and pay-as-you-go cost come from
usagebar in herdr, so they are not repeated here.

## Plugin manifest

`plugins.toml` lists every herdr plugin this setup expects, pinned to a commit
(`source = "owner/repo"`, `ref`, `enabled`). `setup` installs what is missing
and applies `enabled`; `status` reports a pinned commit that differs and any
plugin installed but not listed. Nothing is ever uninstalled. To add a plugin,
add it here and run setup.

## Validate and guards

- `python3 validate.py` (also run in CI): palette format, every template
  renders with no placeholder left, JSON/TOML parse, and `herdr config check`
  on the rendered config when herdr is installed.
- `setup` prints its plan and refuses to apply from a checkout with
  uncommitted changes or one that differs from `origin/main`
  (`--force-local` overrides, with a warning).

## Tab bar

`ui.tab_bar_right` runs `bin/herdr-tabbar` every second: account · model · plan
windows with % used and time to reset (`5h 12% (reset 3h05) · hebdo 72% (reset 4j14h)`) ·
context of the focused agent. Both come from the latest Claude Code status line
input of that pane, which the cockpit status line copies to
`~/.local/state/chrysa.cockpit/statusline/<pane>.json` on every message and every
`refreshInterval` (agent-info wakes up when that file changes); without it,
usagebar's cache per account, which the status line also feeds. chrysa.agent-info writes that line to
`~/.local/state/chrysa.agent-info/tabbar` on every focus or status change;
the script only reads the file (no socket call, well under the 2 s timeout).

## What each surface shows

One fact, one place:

| Surface | Shows |
|---|---|
| Sidebar, Spaces | per space: a state icon only when an agent works, waits or has finished (‼ red, ◐ peach, ✓ mauve; ⑂ blue when only subagents, workflows or background tasks work), name bold in the color of its agents' account (dim grey when all idle), agent and subagent counts per state and account, idle ones included (`○2`), the agents waiting on you. A space inside another's folder (or named after it) is its child: spaces form a tree in alphabetical order (`├ GHA`, `└ simul`); siblings starting with the same word get a dim header (`└ plateform` over `├ charts`, `└ socle`) |
| Sidebar, Agents | the selected space's agents: a state icon only when the agent works, waits, has finished or only its subtasks run (same colors as spaces), age, PR, name in its account's color (dim grey when idle), last tool call; subtasks (subagents, `/subtask` forks, workflow agents, background tasks): one line each for the focused agent, one summary line (`⑂ ●2 ✓3`) for the others |
| Tab bar | `‼` on tabs waiting on you; on the right, account · model · plan windows (% used, time to reset) · context of the focused agent |
| agent-panel (right) | the focused conversation: header (folder in the account's color, git, services), Subagents, Messages, Refs, To do (click a tab, or Tab / ←→ / 1–4); an empty Subagents tab opens on To do or Messages; drag the thin divider on its left to resize it (the width is kept) |
| Desktop notifications | an agent starts waiting on you; agent-info tidied up (idle agents quit after 24 h, tabs moved to their repo's space) |

Claude Code's `mission-control` mod (a box under the prompt: context, cost,
tool timeline, a Haiku comment after each turn) is left off: it repeated the
tab bar and agent-panel and cost one model call per turn.

## Filters for herdr's native Agents column

`agent_view.py` drives herdr's `agent.view.set` socket method, which filters
the built-in Agents column itself (sidebar, collapsed sidebar, navigation):

| Key | Filter |
|---|---|
| `prefix+ctrl+p` | next Claude profile: all → perso → pro… (accounts seen on agents) |
| `prefix+ctrl+a` | only active agents (working, blocked) |
| `prefix+ctrl+x` | only the space selected in herdr (on by default) |
| `prefix+ctrl+s` | sort by attention / by space order |
| `prefix+ctrl+z` | show every agent |

herdr >= 0.9.3 adds a second prefix (`ctrl+space`) and `prefix+ctrl+l` to clear a pane while keeping the prompt. `setup` refuses to apply while the running server is older than the binary (restart it after `herdr update`).

Filters combine, a toast shows the current one, and the state is re-applied at
server startup. herdr drops the view when its server exits; a space switch
re-applies it only when the server changed since the last apply, because
setting a view resets the column and its selection.
