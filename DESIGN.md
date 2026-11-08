# herdr-cockpit — Design contract

> Contract for the terminal surfaces this repository renders inside herdr: sidebar rows, tab
> bar, toasts, keys, the services pane, the Claude Code status line and the opencode theme.
> Read it before changing what the cockpit prints, colours or binds; update it in the same
> change. Status: **[implemented]** links the code · **[decided]** names the decision ·
> **[proposed]** is not agreed. This file documents the current surface; it does not redesign it.

## 1. Surface and status

- **Surface:** interactive terminal UI hosted by herdr (terminal multiplexer). No web or
  graphical UI. **[implemented]** — herdr config ([config.toml](cockpit/templates/config.toml)),
  Agents-column filters ([agent_view.py](cockpit/agent_view.py)), tab bar
  ([herdr-tabbar](cockpit/bin/herdr-tabbar)), services pane
  ([services_pane.py](agent-info/services_pane.py)), agent-panel header lines
  ([header.py](agent-info/header.py)), Claude Code status line
  ([statusline.sh](cockpit/templates/statusline.sh)), opencode theme
  ([opencode-theme.json](cockpit/templates/opencode-theme.json)), setup and drift reports
  ([setup.py](cockpit/setup.py), [status.py](cockpit/status.py)).
- **Lifecycle:** shipped, v0.7.0 ([CHANGELOG.md](CHANGELOG.md),
  [herdr-plugin.toml](cockpit/herdr-plugin.toml)); Linux and macOS manifests.
- **Detailed specs:** [cockpit design spec](work/specs/2026-10-06-cockpit-design.md) (proposed
  2026-10-06, partly superseded) and [ADR 0001](docs/adr/0001-native-first.md) (accepted
  2026-10-09: native herdr and marketplace plugins first). Plugin keys and tokens:
  [cockpit/README.md](cockpit/README.md), [agent-info/README.md](agent-info/README.md).

## 2. Users, devices and priority tasks

| User | Context and device | Priority tasks (three at most) |
| --- | --- | --- |
| Owner running several Claude Code / Codex agents | Linux terminal, herdr all day, two Claude accounts | spot the agent that needs attention · know which account and model an agent runs on · reach a project's running services |
| Same person setting up a machine | herdr command palette, pager output | install or repair the setup · read drift |

Primary action per view: sidebar — find the blocked agent (`‼`); tab bar — read
account · model · context of the focused agent; services pane — open a URL; status — read
the drift lines.

## 3. Journeys and navigation

- **J1 — Triage agents:** glance at the sidebar (state symbol, subject in the account colour,
  space dimmed) → `prefix+ctrl+a` active only or `prefix+ctrl+s` sort by attention → a herdr
  toast names the current filter → `prefix+ctrl+z` shows every agent. Filters combine and are
  re-applied at server start. **[implemented]** ([agent_view.py](cockpit/agent_view.py))
- **J2 — Project services:** `prefix+ctrl+g` → split pane with containers and listening
  processes of the tab's git project and their URLs, refreshed every 2 s. Outside a git
  project the pane says so. **[implemented]** ([services_pane.py](agent-info/services_pane.py))
- **J3 — Install or repair:** action *Cockpit: setup* → plan, backups under `backups/` → a
  second run prints `nothing to do: cockpit already in place`; it refuses to apply from a
  dirty checkout or an older herdr server. *Cockpit: status* exits 1 on drift.
  **[implemented]** ([setup.py](cockpit/setup.py), [status.py](cockpit/status.py))
- **Information architecture:** herdr sidebar (space rows, agent rows), tab bar, panes
  (services, RTK, usagebar limits, agent-panel), palette actions. Two prefixes (`ctrl+b`,
  `ctrl+space`); every custom key sits behind a prefix and `prefix+?` lists them.
  **[implemented]** ([config.toml](cockpit/templates/config.toml))
- **Density:** compact — one line per agent, an idle space takes one line, folder names are
  never cut (sidebar 40 columns).

## 4. Identity

- **Brand brief:** none; a working tool, no logo or banner. **[implemented]**
- **Why it fits:** many agents on two accounts run at once; attributing an agent to the wrong
  account is the costly error, so the account colour is the one constant.
- **Signature element:** one fixed colour per account (perso, pro, codex, other) on every
  surface that shows an account. **[implemented]** ([palette.toml](cockpit/palette.toml))
- **References:** Catppuccin Mocha colour values, as named in the palette file; no other
  third-party identity.

## 5. Tokens and components (owned elsewhere)

| Concern | Source of truth | Rules of use |
| --- | --- | --- |
| Colour roles and accounts | [palette.toml](cockpit/palette.toml) `[colors]`, `[accounts]`, `[roles]` | templates use `{{section.key}}` placeholders only ([render.py](cockpit/render.py)) |
| State and git symbols | [palette.toml](cockpit/palette.toml) `[symbols]` | same glyph for a state on every surface |
| Typography | the user's terminal font | bold for subjects and titles, dim for secondary text |
| Width | `sidebar_width = 40` in [config.toml](cockpit/templates/config.toml) | longest folder name fits; panes truncate to their width |
| Motion | none | terminal output does not animate |
| Components | native herdr rows, tokens, toasts, panes | custom code only where herdr has no equivalent (ADR 0001) |

- **Shared contract:** `contract.css` and `@chrysa/ui` do not apply to a terminal surface.
- **Design debt:** [header.py](agent-info/header.py) and
  [services_pane.py](agent-info/services_pane.py) hard-code ANSI colours (RGB copies of palette
  values and 16-colour codes) instead of reading the palette; `[roles] done = "green"` while the
  spec table gives *done* blue; the `slots` comment still refers to the removed `chrysa.spaces`.

## 6. Interaction and states

- **Action feedback:** a filter change shows a herdr toast `Agents : <label>`; setup prints its
  plan and what it backed up; status gives one line per item and exit 1 on drift.
  **[implemented]**
- **Forms:** none.
- **Data states:**

  | State | Where it appears | Behaviour |
  | --- | --- | --- |
  | Loading | services pane | first frame drawn while `docker ps` / `ss` snapshots start in background threads; no loading text |
  | Empty | services pane, tab bar, space rows | `Pas de dépôt git dans cet onglet`, `aucun conteneur ni port en écoute`; tab bar prints nothing outside an agent; space row 1 is skipped without agents |
  | Error | services pane | `herdr indisponible : <error>`, pane stays alive; filter actions print a Python traceback when the socket is unreachable, no toast |
  | Offline / backend unreachable | tab bar, header | herdr server down: output is empty, without a message |
  | Stale data | all | no age shown; tab bar every 5 s, pane every 2 s |
  | Reconnect | services pane | next 2 s tick recovers on its own |

- **Real-time:** herdr updates sidebar tokens in place. The services pane clears and redraws
  the whole screen every 2 s; rows beyond the pane height are cut (no scroll).
- **Motion:** none (FE-053, terminal: no animation).

## 7. Responsive and support conventions

24-bit colour escapes are emitted ([statusline.sh](cockpit/templates/statusline.sh)). Keys
follow herdr conventions: no `alt` chords (alt sends ESC in xterm), shadowed herdr defaults
are moved explicitly, `prefix+r` stays resize mode. Text from agents is stripped of control
characters before display. No browser layout, mouse-only control or extra prefix is imposed.

## 8. Accessibility

- **Target:** terminal readability — meaning never by colour alone, 40-column sidebar.
- **Keyboard:** every action has a key or a palette entry; keys are unique and described
  (tests in [test_cockpit_keys.py](tests/test_cockpit_keys.py)). **[implemented]**
- **Perception:** `status_indicators = "symbols"` gives each state a distinct shape.
  **[implemented]** On agent rows the account is shown by subject colour only; the tab bar
  names it in text for the focused agent only.
- **Assistive technology:** not tested with a screen reader.

## 9. Assets

| Asset | Source or generator | Author | Licence and attribution | Permitted use | Formats and variants | Location |
| --- | --- | --- | --- | --- | --- | --- |
| Colour values | Catppuccin Mocha palette | Catppuccin project | unknown (not recorded in the repository) | colour values in rendered config | hex | [palette.toml](cockpit/palette.toml) |
| State and git glyphs | Unicode characters | n/a | n/a | everywhere | text | [palette.toml](cockpit/palette.toml) |

No fonts, icons or images are shipped. Repository code: [MIT](LICENSE).

## 10. Acceptance criteria and evidence

- **Criteria:** a blocked agent is identifiable by its symbol in a greyscale terminal; every
  template renders with no placeholder left and no hard-coded palette colour
  ([test_cockpit_render.py](tests/test_cockpit_render.py)); every custom key is behind a prefix,
  unique and described; agent text never carries control sequences
  ([test_panel_header.py](tests/test_panel_header.py)); a second setup run changes nothing
  ([test_cockpit_setup.py](tests/test_cockpit_setup.py)) and status reports every drift
  ([test_cockpit_status.py](tests/test_cockpit_status.py)); the services pane stays readable at
  40 columns.
- **Evidence log:**

  | Date | Change | Checks run (tool, sizes, modes) | Result | Not run, and why |
  | --- | --- | --- | --- | --- |
  | 2026-11-08 | contract written from the code | source review | gaps listed in §11 | no terminal run: documentation-only change |

## 11. Open choices, known gaps and maintenance

- **Open choices:**
  - **[proposed]** render the colours of `header.py` and `services_pane.py` from the palette, so
    one file owns every colour.
  - **[proposed]** honour `NO_COLOR` in the status line, header and services pane.
  - **[proposed]** choose one interface language: pane, toast and status-line strings are French
    (`tous profils`, `panneau`), key descriptions and actions are English.
  - **[proposed]** show the account in text on agent rows (name or initial), not by colour only.
  - **[proposed]** verify, or add, a light variant: `[theme] auto_switch = true` follows a light
    terminal, but the palette is dark only.
- **Known gaps:** the cockpit manifest still starts and re-arms the shared daemon that ADR 0001
  removed, so that command fails at every start and workspace focus; the manifest description still says setup and status "arrive in the next
  releases"; a socket failure in a filter action gives no visible feedback.
- **Maintenance:** owner of this repository. Update this file with any change to the palette,
  templates, keys, pane wording or plugin manifests, and add an evidence row.
