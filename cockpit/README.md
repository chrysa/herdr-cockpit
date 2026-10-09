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

`ui.tab_bar_right` runs `bin/herdr-tabbar` every 5 s: account · model ·
plan window/context of the focused agent, from tokens other plugins already
publish (no extra polling of its own beyond one `herdr agent list`).

## Filters for herdr's native Agents column

`agent_view.py` drives herdr's `agent.view.set` socket method, which filters
the built-in Agents column itself (sidebar, collapsed sidebar, navigation):

| Key | Filter |
|---|---|
| `prefix+ctrl+p` | next Claude profile: all → perso → pro… (accounts seen on agents) |
| `prefix+ctrl+a` | only active agents (working, blocked) |
| `prefix+ctrl+x` | only the space selected in herdr |
| `prefix+ctrl+s` | sort by attention / by space order |
| `prefix+ctrl+z` | show every agent |

Filters combine, a toast shows the current one, and the state is re-applied at
server startup.
