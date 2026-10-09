# Changelog

## v0.4.0 — native first (2026-10-09)

See [ADR 0001](docs/adr/0001-native-first.md).

- Removed the `spaces` plugin, the right-hand info panel and the shared daemon,
  replaced by native herdr features and marketplace plugins.
- `agent-info` now only publishes `$account` / `$model` and provides a services pane
  (`prefix+ctrl+g`).
- Native Agents-column sort through `agent.view.set` (`prefix+ctrl+s`), no more
  config edits.
- herdr toasts top-right; OS notifications off.
- `setup` installs herdr's Claude integration in every Claude account.
- Status line simplified (no panel hand-off, cost left to usagebar).

## v0.3.0 (2026-10-08)

- Native Agents-column filters (`agent.view.set`): profile, active, selected space.
- Native tab bar status (`ui.tab_bar_right`), `agent-panel` and
  `claude-session-title` in the manifest, auto-title settings managed by setup.
- Panel key help, PR on sidebar agent rows.

## v0.2.0 (2026-10-07)

- `cockpit` plugin: palette and templates, `setup`, `status` (7 checks),
  `validate` in CI, plugin manifest, setup guards, release workflow.
