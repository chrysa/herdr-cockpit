# herdr-spaces

Makes the Herdr **spaces sidebar** readable and correlates spaces with their agents.

Every workspace row gets:

- **`◉ N` agent-count chip**, colored by a stable per-space color slot (0..7).
- **worktree list** (`⑂ a | b`) *only* when the space holds more than one git
  worktree of the **same repo** (several unrelated repos in one space is just a
  multi-project space, not shown).

Every agent row gets a **`●` dot in the same color slot as its space**, so a
space and its agents read as one colored group.

## How the color works

Herdr row styling is static, so a per-space color can't come from a value. Same
trick as `chrysa.rtk-savings`: the config pre-styles **8 identical variant rows**
(`sp0..sp7` for spaces, `ag0..ag7` for agents) with 8 fixed colors; the plugin
picks one slot per space (`crc32(workspace_id) % 8`, stable across restarts) and
publishes the chip/dot into just that variant. Config references custom tokens
with a `$` sigil (`$sp0`), the plugin publishes them bare (`sp0=...`).

## Install

```sh
herdr plugin link /path/to/herdr-spaces
herdr plugin action invoke start --plugin chrysa.spaces   # or just open/focus a space
herdr server reload-config
```

The config half lives in `~/.config/herdr/config.toml` under
`[ui.sidebar.spaces]` (`$wt`, `$sp0..$sp7`) and `[ui.sidebar.agents]`
(`$ag0..$ag7`). The 8 hex colors must match between the two sections.

## Data & cost

Local socket reads only (`herdr pane list`, `herdr agent list`) plus one
`git rev-parse` per new pane cwd (cached). Polls every 6 s, one background
daemon guarded by a pidfile lock, auto-restarts on workspace/pane events. No
network, no telemetry.

Commands: `python3 monitor.py {ensure|daemon|stop}`.
