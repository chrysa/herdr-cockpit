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
