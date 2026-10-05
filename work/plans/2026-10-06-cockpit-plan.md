# herdr-cockpit — plan

Spec: `work/specs/2026-10-06-cockpit-design.md`. Each step is one PR, merged
before the next starts. "Done" = tests green in CI and checked on this machine.

| # | Step | Spec | Done when |
|---|------|------|-----------|
| 1 | CI: pytest workflow, first tests for existing `agent-info` (names, billing, git, model) | §5 | CI green on `main` |
| 2 | `cockpit` skeleton: `palette.toml`, templates rendering today's config unchanged | §4.5, §6.1 | rendered `config.toml` == current file |
| 3 | `cockpit: status` (read-only drift report) | §4.5, D4 | reports only the dotfiles link on this machine |
| 4 | `cockpit: setup` (backup, link, units, reload), idempotent | §4.5, D3 | second run is a no-op |
| 5 | Migrate: dotfiles drops `herdr/`, `install.sh` calls setup | §6 | fresh `install.sh` reproduces the setup |
| 6 | Accounts on space rows | §4.1 | `padam-av` row shows its accounts in color |
| 7 | Unified palette: status line, info bar, opencode theme generated | §4.2 | same symbols and colors on all three |
| 8 | Info bar agents mode, follows selected space | §4.3 | selecting a space updates the list within 1 s |
| 9 | Group by state, collapsible sections | §4.4 | `1`–`4` collapse, state survives restart |
| 10 | Single daemon, rtk renderer vendored | §4.6, D7 | one poller process; herdr API calls ÷3 |
| 11 | Blocked-only notification, drop in-your-face | §4.7 | one notification per blocked transition |

Order rationale: tests first so later refactors are safe; status before setup
so drift is visible before anything is overwritten; migration before features
so new features land in one place only.

Outside this repo, still open:
- dotfiles #45 (preservation, `.claude/settings.json` conflict between hook
  formats) needs a manual merge decision.
- herdr server restart (activates `HERDR_LOG`, clean env, auto-title managed).
- closing idle agents (`forge-*` idle 211 h).
- local `main` of dotfiles diverged from `origin`.
