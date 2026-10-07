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

## Shared daemon

`daemon.py` (started with the herdr server) reads herdr once per tick (panes,
agents, workspaces) and hands the snapshot to `chrysa.spaces` and
`chrysa.agent-info`. While it holds its lock, those plugins' own daemons do not
start, and any already running exits at its next tick (their startup hooks race
with this one when the server starts). A renderer that fails does not stop the
others.

## Claude Code status line

`templates/statusline.sh`: account (colored), model, folder, git state (same
symbols as the sidebar), llmtrim context/savings/cache, cost only once billed
past the quota, and a `⌃b ⌃g panel` hint inside herdr. It hides itself while
the herdr info panel is open, since the panel shows all of it.

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
